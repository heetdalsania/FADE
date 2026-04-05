"""
FADE — Dashboard Server
========================
Serves the FADE dashboard and provides API endpoints for
running the analysis pipeline against any GitHub repository.

Usage:
    python server.py              # default port 8080
    python server.py 3000         # custom port

Then open:
    http://localhost:<port>/dashboard.html
"""

import http.server
import socketserver
import socket
import subprocess
import sys
import os
import json
import threading
import queue
import time
import urllib.parse

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080

# Serve from the directory this script lives in
SERVE_DIR = os.path.dirname(os.path.abspath(__file__))
ZIP_PATH = os.path.join(os.path.dirname(SERVE_DIR), "FADE.zip")
os.chdir(SERVE_DIR)

# Import the pipeline runner
sys.path.insert(0, SERVE_DIR)
from pipeline_runner import PipelineEvents, run_pipeline


# ─────────────────────────────────────────────────────────────
# GLOBAL STATE
# ─────────────────────────────────────────────────────────────

current_run = {
    "running": False,
    "repo": None,
    "error": None,
    "result": None,
}
run_lock = threading.Lock()
sse_queues = []
sse_queues_lock = threading.Lock()


def broadcast_event(event_type, data):
    """Send an SSE event to all connected clients."""
    msg = f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"
    with sse_queues_lock:
        dead = []
        for q in sse_queues:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            sse_queues.remove(q)


def run_pipeline_thread(repo, github_token, notification_channels=None):
    """Run the pipeline in a background thread."""
    global current_run

    events = PipelineEvents()
    events.add_listener(broadcast_event)

    with run_lock:
        current_run["running"] = True
        current_run["repo"] = repo
        current_run["error"] = None
        current_run["result"] = None

    try:
        result = run_pipeline(repo, github_token, events, notification_channels=notification_channels or [])
        with run_lock:
            if isinstance(result, dict) and "error" in result:
                current_run["error"] = result["error"]
            else:
                current_run["result"] = result
    except Exception as e:
        with run_lock:
            current_run["error"] = str(e)
        broadcast_event("error", {"message": str(e)})
    finally:
        with run_lock:
            current_run["running"] = False


# ─────────────────────────────────────────────────────────────
# HTTP HANDLER
# ─────────────────────────────────────────────────────────────

def rebuild_zip():
    """Rebuild FADE.zip from the current project directory."""
    try:
        if os.path.exists(ZIP_PATH):
            os.remove(ZIP_PATH)
        subprocess.run(
            ["zip", "-r", ZIP_PATH, "."],
            cwd=SERVE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print(f"  Warning: Could not build zip: {e}")


class FADEHandler(http.server.SimpleHTTPRequestHandler):
    """Serves files + API endpoints."""

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "":
            # Redirect to dashboard
            self.send_response(302)
            self.send_header("Location", "/dashboard.html")
            self.end_headers()

        elif path == "/api/stream":
            self.handle_sse()

        elif path == "/api/status":
            self.handle_status()

        elif path == "/api/fade-state" or path == "/api/fade-state/":
            self.serve_fade_state()

        elif path == "/download" or path == "/download/":
            self.serve_zip()

        else:
            super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/run":
            self.handle_run()
        else:
            self.send_error(404, "Not found")

    def handle_run(self):
        """Start a new pipeline run."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self.send_json(400, {"error": "Invalid JSON"})
            return

        repo = data.get("repo", "").strip()
        github_token = data.get("github_token", "").strip()
        notification_channels = data.get("notification_channels", [])

        if not repo:
            self.send_json(400, {"error": "Repository is required"})
            return

        if "/" not in repo:
            self.send_json(400, {"error": "Repository must be in 'owner/repo' format"})
            return

        with run_lock:
            if current_run["running"]:
                self.send_json(409, {"error": "A pipeline is already running"})
                return

        # Start pipeline in background thread
        t = threading.Thread(
            target=run_pipeline_thread,
            args=(repo, github_token, notification_channels),
            daemon=True,
        )
        t.start()

        self.send_json(200, {"status": "started", "repo": repo})

    def handle_sse(self):
        """Server-Sent Events endpoint for real-time updates."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        q = queue.Queue(maxsize=200)
        with sse_queues_lock:
            sse_queues.append(q)

        try:
            # Send initial connection event
            self.wfile.write(b"event: connected\ndata: {}\n\n")
            self.wfile.flush()

            while True:
                try:
                    msg = q.get(timeout=15)
                    self.wfile.write(msg.encode("utf-8"))
                    self.wfile.flush()
                except queue.Empty:
                    # Send keepalive
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with sse_queues_lock:
                if q in sse_queues:
                    sse_queues.remove(q)

    def handle_status(self):
        """Return current run status."""
        with run_lock:
            status = {
                "running": current_run["running"],
                "repo": current_run["repo"],
                "error": current_run["error"],
                "has_result": current_run["result"] is not None,
            }
        self.send_json(200, status)

    def serve_fade_state(self):
        """JSON bundle for dashboard.html: trace, analysis, optional Slack previews."""
        trace_path = os.path.join(SERVE_DIR, "execution_trace.json")
        analysis_path = os.path.join(SERVE_DIR, "analysis_report.json")
        outputs_path = os.path.join(SERVE_DIR, "dashboard_outputs.json")

        try:
            with open(trace_path, "r", encoding="utf-8") as f:
                trace = json.load(f)
        except FileNotFoundError:
            self.send_json(
                404,
                {
                    "ok": False,
                    "error": "missing_execution_trace",
                    "message": (
                        "No execution_trace.json — run the pipeline for your repo "
                        "(POST /api/run) or generate traces with agent.py / phase2."
                    ),
                },
            )
            return
        except json.JSONDecodeError as e:
            self.send_json(
                500,
                {
                    "ok": False,
                    "error": "invalid_json",
                    "path": "execution_trace.json",
                    "detail": str(e),
                },
            )
            return

        steps = trace.get("steps") or []
        trace["total_steps"] = len(steps)
        if "summary" not in trace or not isinstance(trace["summary"], dict):
            trace["summary"] = {
                "tool_calls": sum(1 for s in steps if s.get("step_type") == "tool_call"),
                "reasoning_steps": sum(1 for s in steps if s.get("step_type") == "reasoning"),
            }

        analysis = []
        try:
            with open(analysis_path, "r", encoding="utf-8") as f:
                analysis = json.load(f)
            if not isinstance(analysis, list):
                analysis = []
        except (FileNotFoundError, json.JSONDecodeError):
            analysis = []

        outputs = None
        if os.path.isfile(outputs_path):
            try:
                with open(outputs_path, "r", encoding="utf-8") as f:
                    outputs = json.load(f)
            except json.JSONDecodeError:
                outputs = None

        self.send_json(200, {"ok": True, "trace": trace, "analysis": analysis, "outputs": outputs})

    def serve_zip(self):
        """Serve FADE.zip as a downloadable file."""
        rebuild_zip()
        if not os.path.exists(ZIP_PATH):
            self.send_error(500, "Could not generate zip")
            return
        file_size = os.path.getsize(ZIP_PATH)
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", "attachment; filename=FADE.zip")
        self.send_header("Content-Length", str(file_size))
        self.end_headers()
        with open(ZIP_PATH, "rb") as f:
            self.wfile.write(f.read())

    def send_json(self, code, data):
        """Send a JSON response."""
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        # Suppress SSE keepalive noise
        if "/api/stream" not in str(args[0]):
            print(f"  {self.address_string()} — {args[0]}")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def get_local_ip():
    """Get the machine's LAN IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Threaded TCP server for handling SSE + normal requests concurrently."""
    allow_reuse_address = True
    daemon_threads = True


def main():
    rebuild_zip()

    with ThreadedTCPServer(("0.0.0.0", PORT), FADEHandler) as httpd:
        local_ip = get_local_ip()

        print()
        print("=" * 50)
        print("  FADE — Dashboard Server")
        print("=" * 50)
        print()
        print(f"  Dashboard:  http://localhost:{PORT}/dashboard.html")
        print(f"  API:        http://localhost:{PORT}/api/run  |  /api/fade-state  |  /api/stream")
        print()
        print(f"  Network:    http://{local_ip}:{PORT}/dashboard.html")
        print()
        print("  Press Ctrl+C to stop.")
        print()
        print("-" * 50)

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n\n  Server stopped.\n")


if __name__ == "__main__":
    main()
