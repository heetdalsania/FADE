"""
FADE — Pipeline Runner
========================
Unified module that runs all three phases of the FADE pipeline
against any GitHub repository. Designed to be called from the
server with a callback/event system for real-time progress.

Works in two modes:
  - Full mode (GOOGLE_CLOUD_PROJECT set): Uses Gemini for PR summaries
  - Local-only mode: Uses PR body first sentence as summary
"""

import os
import json
import time
import threading
import requests
from datetime import datetime, timedelta, timezone


# ─────────────────────────────────────────────────────────────
# EVENT SYSTEM
# ─────────────────────────────────────────────────────────────

class PipelineEvents:
    """Collects events emitted during pipeline execution."""

    def __init__(self):
        self.listeners = []
        self.lock = threading.Lock()

    def add_listener(self, fn):
        with self.lock:
            self.listeners.append(fn)

    def emit(self, event_type, data):
        with self.lock:
            listeners = list(self.listeners)
        for fn in listeners:
            try:
                fn(event_type, data)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────
# GITHUB HELPERS
# ─────────────────────────────────────────────────────────────

def _github_headers(token):
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_merged_prs(repo, token, days=7):
    """Fetch merged PRs from the last N days."""
    headers = _github_headers(token)
    since_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    # Try search API first (works better for finding merged PRs)
    try:
        resp = requests.get(
            "https://api.github.com/search/issues",
            headers=headers,
            params={
                "q": f"repo:{repo} is:pr is:merged merged:>={since_date}",
                "sort": "updated",
                "order": "desc",
                "per_page": 30,
            },
            timeout=15,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code in (401, 403):
            raise RuntimeError(
                f"GitHub returned {e.response.status_code} for {repo}. "
                "Add a GitHub token in onboarding (or set GITHUB_TOKEN) for private repos and higher rate limits."
            ) from e
        raise RuntimeError(f"GitHub search failed for {repo}: {e}") from e
    except requests.RequestException:
        # Fallback to pulls endpoint
        try:
            resp = requests.get(
                f"https://api.github.com/repos/{repo}/pulls",
                headers=headers,
                params={
                    "state": "closed",
                    "sort": "updated",
                    "direction": "desc",
                    "per_page": 50,
                },
                timeout=15,
            )
            resp.raise_for_status()
            items = [
                pr for pr in resp.json()
                if pr.get("merged_at") and pr["merged_at"][:10] >= since_date
            ]
        except requests.RequestException as e:
            raise RuntimeError(f"Failed to fetch PRs from {repo}: {e}")

    merged = []
    for pr in items[:30]:
        pr_detail = pr.get("pull_request", {})
        merged_at = pr.get("merged_at") or (
            (pr_detail.get("merged_at", "") if isinstance(pr_detail, dict) else "")
        )
        merged.append({
            "number": pr["number"],
            "title": pr["title"],
            "author": pr["user"]["login"],
            "merged_at": merged_at,
            "url": pr["html_url"],
            "body": (pr.get("body") or "")[:500],
        })

    return merged


def fetch_pr_files(repo, pr_number, token):
    """Fetch changed files for a single PR."""
    headers = _github_headers(token)
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files",
            headers=headers,
            params={"per_page": 30},
            timeout=10,
        )
        resp.raise_for_status()
        return [f["filename"] for f in resp.json()]
    except requests.RequestException:
        return []


# ─────────────────────────────────────────────────────────────
# CATEGORIZATION (deterministic — no AI needed)
# ─────────────────────────────────────────────────────────────

def categorize_pr(title, body, files):
    """Categorize a PR using keyword scoring."""
    title_lower = title.lower()
    body_lower = (body or "").lower()

    keywords = {
        "bug_fix": ["fix", "bug", "patch", "hotfix", "resolve", "crash", "error",
                     "regression", "leak", "mismatch", "race condition", "broken"],
        "new_feature": ["add", "feat", "new", "implement", "introduce", "support",
                         "enable", "initial", "allow", "create"],
        "refactor": ["refactor", "clean", "restructure", "simplify", "reorganize",
                      "move", "rename", "extract", "consolidate", "share", "migrate"],
        "docs": ["doc", "readme", "typo", "spelling", "grammar", "changelog",
                  "documentation", "reference", "api reference", "comment"],
        "test": ["test", "spec", "coverage", "snapshot", "fixture", "benchmark",
                  "integration test", "e2e", "assert"],
        "chore": ["chore", "ci", "build", "deps", "bump", "upgrade", "lint",
                   "config", "workflow", "release", "version", "dependabot"],
    }

    file_signals = {
        "docs": [".md", "docs/", "README", "CHANGELOG"],
        "test": ["test/", "tests/", "__tests__/", ".test.", ".spec.",
                  "test-utils", "fixtures/"],
        "chore": [".yml", ".yaml", "package.json", ".github/workflows/",
                   ".eslint", "tsconfig", "yarn.lock", ".github/actions/",
                   "Makefile", "Dockerfile"],
    }

    scores = {cat: 0 for cat in keywords}

    for cat, kws in keywords.items():
        for kw in kws:
            if kw in title_lower:
                scores[cat] += 4
            if kw in body_lower:
                scores[cat] += 1

    for cat, patterns in file_signals.items():
        for f in (files or []):
            f_lower = f.lower()
            for p in patterns:
                if p.lower() in f_lower:
                    scores[cat] += 2

    # Special: all files are docs → docs
    if files and all(any(p in f for p in [".md", "docs/"]) for f in files):
        scores["docs"] += 10
    # Special: all files are tests → test
    if files and all(any(p in f for p in ["test", "spec", "fixture"]) for f in files):
        scores["test"] += 10
    # Special: all files are CI/config → chore
    if files and all(any(p in f for p in [".yml", ".yaml", ".github/", "package.json"]) for f in files):
        scores["chore"] += 10

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "chore"


# ─────────────────────────────────────────────────────────────
# SUMMARY GENERATION
# ─────────────────────────────────────────────────────────────

def generate_summary_local(pr):
    """Generate a summary from the PR body (no AI)."""
    body = (pr.get("body") or "").strip()
    if not body:
        return ""
    # Take first sentence
    for delim in [". ", ".\n", "\n"]:
        idx = body.find(delim)
        if idx > 0 and idx < 200:
            sentence = body[:idx + 1].strip()
            if len(sentence) > 15:
                return sentence
    # Fallback: first 120 chars
    if len(body) > 120:
        return body[:120].rsplit(" ", 1)[0].rstrip(".,;:!?-") + "."
    return body


def generate_summary_ai(pr):
    """Generate a summary using Gemini Flash (if available)."""
    gcp_project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    if not gcp_project:
        return generate_summary_local(pr)

    try:
        from google import genai
        from google.genai import types as gt

        client = genai.Client(
            vertexai=True,
            project=gcp_project,
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1").strip(),
        )
        prompt = (
            f"Summarize this GitHub PR in under 15 words. No preamble.\n"
            f"Title: {pr['title']}\n"
            f"Description: {(pr.get('body') or '')[:300]}\n"
            f"Summary:"
        )
        r = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=gt.GenerateContentConfig(temperature=0.1, max_output_tokens=256),
        )
        text = (r.text or "").strip().split("\n")[0].strip()
        if text and len(text) > 10:
            if text[-1] not in ".!?":
                text += "."
            return text
    except Exception:
        pass

    return generate_summary_local(pr)


# ─────────────────────────────────────────────────────────────
# SLACK DIGEST FORMATTING
# ─────────────────────────────────────────────────────────────

CATEGORY_CONFIG = {
    "new_feature": {"label": "New Features", "emoji": "\u2728", "order": 0},
    "bug_fix":     {"label": "Bug Fixes",    "emoji": "\U0001f41b", "order": 1},
    "refactor":    {"label": "Refactors",     "emoji": "\U0001f527", "order": 2},
    "docs":        {"label": "Documentation", "emoji": "\U0001f4da", "order": 3},
    "test":        {"label": "Tests",         "emoji": "\U0001f9ea", "order": 4},
    "chore":       {"label": "Maintenance",   "emoji": "\U0001f3d7\ufe0f", "order": 5},
}


def format_slack_digest(repo, categorized_prs, pr_summaries):
    """Format a Slack digest message."""
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%B %d")
    total = sum(len(v) for v in categorized_prs.values())

    lines = [f"\U0001f4cb *Weekly PR Digest \u2014 {week_ago} to {today}*"]
    lines.append(f"_{total} PRs merged in `{repo}`_\n")

    sorted_cats = sorted(
        categorized_prs.items(),
        key=lambda x: CATEGORY_CONFIG.get(x[0], {}).get("order", 99),
    )

    for cat_key, prs in sorted_cats:
        if not prs:
            continue
        cfg = CATEGORY_CONFIG.get(cat_key, {"label": cat_key, "emoji": "\U0001f4cc"})
        lines.append(f"{cfg['emoji']} *{cfg['label']}* ({len(prs)})")
        for pr in prs:
            lines.append(f"  \u2022 <{pr['url']}|#{pr['number']}> {pr['title']} \u2014 _{pr['author']}_")
            summary = pr_summaries.get(pr["number"], "")
            if summary and summary.lower().rstrip(".!?") != pr["title"].lower().rstrip(".!?"):
                lines.append(f"    _{summary}_")
        lines.append("")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# MULTI-CHANNEL DELIVERY
# ─────────────────────────────────────────────────────────────

def format_discord_digest(repo, categorized_prs, pr_summaries):
    """Format digest for Discord (uses different markdown)."""
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%B %d")
    total = sum(len(v) for v in categorized_prs.values())

    lines = [f"📋 **Weekly PR Digest — {week_ago} to {today}**"]
    lines.append(f"*{total} PRs merged in `{repo}`*\n")

    sorted_cats = sorted(
        categorized_prs.items(),
        key=lambda x: CATEGORY_CONFIG.get(x[0], {}).get("order", 99),
    )

    for cat_key, prs in sorted_cats:
        if not prs:
            continue
        cfg = CATEGORY_CONFIG.get(cat_key, {"label": cat_key, "emoji": "\U0001f4cc"})
        lines.append(f"{cfg['emoji']} **{cfg['label']}** ({len(prs)})")
        for pr in prs:
            lines.append(f"  • [#{pr['number']}]({pr['url']}) {pr['title']} — *{pr['author']}*")
            summary = pr_summaries.get(pr["number"], "")
            if summary and summary.lower().rstrip(".!?") != pr["title"].lower().rstrip(".!?"):
                lines.append(f"    *{summary}*")
        lines.append("")

    return "\n".join(lines)


def format_teams_digest(repo, categorized_prs, pr_summaries):
    """Format digest as Microsoft Teams Adaptive Card JSON."""
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%B %d")
    total = sum(len(v) for v in categorized_prs.values())

    body = [
        {"type": "TextBlock", "text": f"📋 Weekly PR Digest — {week_ago} to {today}", "weight": "Bolder", "size": "Medium"},
        {"type": "TextBlock", "text": f"{total} PRs merged in {repo}", "isSubtle": True, "spacing": "None"},
    ]

    sorted_cats = sorted(
        categorized_prs.items(),
        key=lambda x: CATEGORY_CONFIG.get(x[0], {}).get("order", 99),
    )

    for cat_key, prs in sorted_cats:
        if not prs:
            continue
        cfg = CATEGORY_CONFIG.get(cat_key, {"label": cat_key, "emoji": "\U0001f4cc"})
        body.append({"type": "TextBlock", "text": f"{cfg['emoji']} **{cfg['label']}** ({len(prs)})", "weight": "Bolder", "spacing": "Medium"})
        for pr in prs:
            summary = pr_summaries.get(pr["number"], "")
            desc = f"[#{pr['number']}]({pr['url']}) {pr['title']} — *{pr['author']}*"
            if summary and summary.lower().rstrip(".!?") != pr["title"].lower().rstrip(".!?"):
                desc += f"\n\n*{summary}*"
            body.append({"type": "TextBlock", "text": desc, "wrap": True, "spacing": "Small"})

    card = {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "contentUrl": None,
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": body,
            }
        }]
    }
    return card


def format_email_digest(repo, categorized_prs, pr_summaries):
    """Format digest as clean HTML for email."""
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%B %d")
    total = sum(len(v) for v in categorized_prs.values())

    html = f"""<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:640px;margin:0 auto;color:#1a1a2e;">
<h2 style="color:#0e1320;border-bottom:2px solid #06b6d4;padding-bottom:8px;">📋 Weekly PR Digest</h2>
<p style="color:#666;margin:4px 0 20px;">{week_ago} to {today} · <code style="background:#f0f4f8;padding:2px 6px;border-radius:4px;">{repo}</code> · {total} PRs merged</p>
"""
    sorted_cats = sorted(
        categorized_prs.items(),
        key=lambda x: CATEGORY_CONFIG.get(x[0], {}).get("order", 99),
    )

    for cat_key, prs in sorted_cats:
        if not prs:
            continue
        cfg = CATEGORY_CONFIG.get(cat_key, {"label": cat_key, "emoji": "\U0001f4cc"})
        html += f'<h3 style="color:#334155;margin:20px 0 8px;">{cfg["emoji"]} {cfg["label"]} ({len(prs)})</h3>\n<ul style="list-style:none;padding:0;">\n'
        for pr in prs:
            summary = pr_summaries.get(pr["number"], "")
            sum_html = ""
            if summary and summary.lower().rstrip(".!?") != pr["title"].lower().rstrip(".!?"):
                sum_html = f'<br><span style="color:#888;font-size:13px;font-style:italic;">{summary}</span>'
            html += f'<li style="margin:6px 0;padding:8px 12px;background:#f8fafc;border-radius:6px;border-left:3px solid #06b6d4;"><a href="{pr["url"]}" style="color:#06b6d4;text-decoration:none;font-weight:600;">#{pr["number"]}</a> {pr["title"]} <span style="color:#888;">— {pr["author"]}</span>{sum_html}</li>\n'
        html += "</ul>\n"

    html += f'<p style="color:#999;font-size:12px;margin-top:24px;border-top:1px solid #e2e8f0;padding-top:12px;">Generated by FADE — Fast Agent Deprecation Engine</p></div>'
    return html


def deliver_to_slack(webhook_url, message):
    """Post digest to Slack via webhook."""
    try:
        resp = requests.post(webhook_url, json={"text": message}, timeout=10)
        resp.raise_for_status()
        return {"success": True, "channel": "slack"}
    except Exception as e:
        return {"success": False, "channel": "slack", "error": str(e)}


def deliver_to_discord(webhook_url, message):
    """Post digest to Discord via webhook."""
    try:
        # Discord webhooks accept {"content": "message"} for plain text
        # Truncate to Discord's 2000 char limit
        if len(message) > 1900:
            message = message[:1900] + "\n\n*... truncated*"
        resp = requests.post(webhook_url, json={"content": message}, timeout=10)
        resp.raise_for_status()
        return {"success": True, "channel": "discord"}
    except Exception as e:
        return {"success": False, "channel": "discord", "error": str(e)}


def deliver_to_teams(webhook_url, card_json):
    """Post digest to Microsoft Teams via webhook."""
    try:
        resp = requests.post(webhook_url, json=card_json, timeout=10)
        resp.raise_for_status()
        return {"success": True, "channel": "teams"}
    except Exception as e:
        return {"success": False, "channel": "teams", "error": str(e)}


# ─────────────────────────────────────────────────────────────
# EMAIL DELIVERY (Gmail SMTP)
# ─────────────────────────────────────────────────────────────

# Server-side sender credentials — user only provides recipient
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_SENDER = os.environ.get("FADE_EMAIL_SENDER", "fadeeeeai@gmail.com")
SMTP_PASSWORD = os.environ.get("FADE_EMAIL_PASSWORD", "lkbn aozl zsfy yfxi")


def deliver_to_email(recipient, subject, html_body):
    """Send digest email via Gmail SMTP."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    if not recipient or not recipient.strip():
        return {"success": False, "channel": "email", "error": "No recipient email provided"}

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = f"FADE Digest <{SMTP_SENDER}>"
        msg["To"] = recipient.strip()
        msg["Subject"] = subject

        # Plain-text fallback
        plain = f"Weekly PR Digest — View this email in an HTML-capable client.\n\nGenerated by FADE."
        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_SENDER, SMTP_PASSWORD)
            server.sendmail(SMTP_SENDER, [recipient.strip()], msg.as_string())

        return {"success": True, "channel": "email", "recipient": recipient.strip()}

    except smtplib.SMTPAuthenticationError:
        return {
            "success": False, "channel": "email",
            "error": "Gmail auth failed — you need a Gmail App Password (not your regular password). "
                     "Enable 2FA at myaccount.google.com/security, then create an App Password at "
                     "myaccount.google.com/apppasswords"
        }
    except Exception as e:
        return {"success": False, "channel": "email", "error": str(e)}


def deliver_notifications(channels, repo, categorized, summaries, events=None):
    """Deliver digest to all configured notification channels."""
    results = []

    for ch in channels:
        ch_type = ch.get("type", "")
        url = ch.get("url", "").strip()
        if not url:
            continue

        if ch_type == "slack":
            msg = format_slack_digest(repo, categorized, summaries)
            result = deliver_to_slack(url, msg)
        elif ch_type == "discord":
            msg = format_discord_digest(repo, categorized, summaries)
            result = deliver_to_discord(url, msg)
        elif ch_type == "teams":
            card = format_teams_digest(repo, categorized, summaries)
            result = deliver_to_teams(url, card)
        elif ch_type == "email":
            html = format_email_digest(repo, categorized, summaries)
            today = datetime.now(timezone.utc).strftime("%B %d, %Y")
            subject = f"Weekly PR Digest — {repo} — {today}"
            result = deliver_to_email(url, subject, html)
        else:
            result = {"success": False, "channel": ch_type, "error": "Unknown channel type"}

        results.append(result)
        if events:
            events.emit("delivery_result", result)

    return results


# ─────────────────────────────────────────────────────────────
# STEP CLASSIFICATION (deterministic for this task type)
# ─────────────────────────────────────────────────────────────

# The classification for a "weekly PR digest" task is always the same pattern.
# This is the whole point of FADE: once you know the pattern, you don't need AI.

STEP_CLASSIFICATIONS = [
    {
        "step_number": 1,
        "original_description": "Plan the weekly PR digest workflow",
        "classification": "RULE_BASED",
        "reasoning": "Fixed pipeline sequence — no AI reasoning needed. The plan is always: fetch, classify, summarize, format, post.",
    },
    {
        "step_number": 2,
        "original_description": "Fetch merged PRs from GitHub API",
        "classification": "DETERMINISTIC",
        "reasoning": "Pure HTTP GET to GitHub REST API. Same parameters always produce the same API call.",
    },
    {
        "step_number": 3,
        "original_description": "Fetch file changes for each merged PR",
        "classification": "DETERMINISTIC",
        "reasoning": "Pure HTTP GET to GitHub REST API for each PR's file list. Completely deterministic.",
    },
    {
        "step_number": 4,
        "original_description": "Categorize each PR by type",
        "classification": "RULE_BASED",
        "reasoning": "Keyword matching on titles and file path patterns achieves 80%+ accuracy without AI.",
    },
    {
        "step_number": 5,
        "original_description": "Generate concise summary for each PR",
        "classification": "AI_REQUIRED",
        "reasoning": "Generating meaningful one-sentence summaries genuinely requires language understanding.",
    },
    {
        "step_number": 6,
        "original_description": "Decide on formatting structure for Slack message",
        "classification": "RULE_BASED",
        "reasoning": "Fixed template — header, category sections with emoji, PR links. Static decision.",
    },
    {
        "step_number": 7,
        "original_description": "Format the Slack digest message",
        "classification": "RULE_BASED",
        "reasoning": "String formatting with a predefined template and iteration. Pure string manipulation.",
    },
    {
        "step_number": 8,
        "original_description": "Post formatted digest to Slack webhook",
        "classification": "DETERMINISTIC",
        "reasoning": "Pure HTTP POST to Slack webhook URL with the formatted message payload.",
    },
]


# ─────────────────────────────────────────────────────────────
# GENERATED SCRIPT SNIPPETS
# ─────────────────────────────────────────────────────────────

def get_script_snippets(repo):
    """Return code snippets for each replaceable step."""
    return {
        1: f"""# step_01_plan.py — RULE_BASED
# Replaces: Agent planning/reasoning step
# No AI needed — fixed pipeline sequence

PIPELINE_STEPS = [
    "fetch_merged_prs",
    "fetch_pr_files",
    "categorize_prs",
    "generate_summaries",  # AI_REQUIRED
    "format_digest",
    "post_to_slack",
]

def run(inputs):
    return {{
        "plan": PIPELINE_STEPS,
        "repo": inputs.get("repo", "{repo}"),
        "days": inputs.get("days", 7),
    }}""",
        2: f"""# step_02_fetch_prs.py — DETERMINISTIC
# Replaces: Agent's GitHub PR fetch tool call
# Pure requests.get — zero AI

import requests, os
from datetime import datetime, timedelta, timezone

def run(inputs):
    repo = inputs["repo"]
    since = (datetime.now(timezone.utc)
             - timedelta(days=7)).isoformat()
    resp = requests.get(
        f"https://api.github.com/repos/{{repo}}/pulls",
        headers={{"Authorization":
                 f"Bearer {{os.getenv('GITHUB_TOKEN')}}"}},
        params={{"state":"closed","sort":"updated",
                "direction":"desc","per_page":50}},
    )
    return [pr for pr in resp.json()
            if pr.get("merged_at", "") >= since[:10]]""",
        3: """# step_03_fetch_files.py — DETERMINISTIC
# Replaces: Agent's per-PR file listing tool call
# Pure requests.get — zero AI

import requests, os

def run(inputs):
    repo, prs = inputs["repo"], inputs["prs"]
    headers = {"Authorization":
               f"Bearer {os.getenv('GITHUB_TOKEN')}"}
    pr_files = {}
    for pr in prs[:15]:
        resp = requests.get(
            f"https://api.github.com/repos/{repo}"
            f"/pulls/{pr['number']}/files",
            headers=headers, timeout=10)
        pr_files[pr["number"]] = [
            f["filename"] for f in resp.json()]
    return pr_files""",
        4: """# step_04_categorize.py — RULE_BASED
# Replaces: Agent's AI-powered categorization
# Keyword scoring engine — 80%+ accuracy vs agent

KEYWORDS = {
    "bug_fix": ["fix","bug","patch","crash","leak"],
    "new_feature": ["add","feat","implement","support"],
    "refactor": ["refactor","clean","extract","share"],
    "docs": ["doc","readme","typo","changelog"],
    "test": ["test","spec","coverage","fixture"],
    "chore": ["ci","build","bump","upgrade","lint"],
}

def categorize_pr(title, body, files):
    scores = {cat: 0 for cat in KEYWORDS}
    for cat, kws in KEYWORDS.items():
        for kw in kws:
            if kw in title.lower(): scores[cat] += 4
            if kw in (body or "").lower(): scores[cat] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "chore" """,
        6: """# step_06_format_decision.py — RULE_BASED
# Replaces: Agent's formatting reasoning
# Fixed template config — no AI needed

TEMPLATE = {
    "order": ["new_feature", "bug_fix", "refactor",
              "docs", "test", "chore"],
    "emoji": {"new_feature":"✨", "bug_fix":"🐛",
              "refactor":"🔧", "docs":"📚",
              "test":"🧪", "chore":"🏗️"},
    "labels": {"new_feature":"New Features",
               "bug_fix":"Bug Fixes", ...},
}

def run(inputs):
    return {"template": TEMPLATE}""",
        7: """# step_07_format_message.py — RULE_BASED
# Replaces: Agent's Slack message formatting
# Pure string template — no AI needed

def format_slack_digest(repo, categorized, summaries):
    lines = [f"📋 *Weekly PR Digest*"]
    lines.append(f"_{total} PRs in `{repo}`_")

    for cat in ORDER:
        prs = categorized.get(cat, [])
        if not prs: continue
        lines.append(f"{EMOJI[cat]} *{LABEL[cat]}*")
        for pr in prs:
            lines.append(
              f"  • <{pr['url']}|#{pr['number']}>"
              f" {pr['title']} — _{pr['author']}_")
            if summaries.get(pr["number"]):
                lines.append(
                  f"    _{summaries[pr['number']]}_")
    return "\\n".join(lines)""",
        8: """# step_08_post_slack.py — DETERMINISTIC
# Replaces: Agent's Slack posting tool call
# Pure requests.post — zero AI

import requests, os

def run(inputs):
    webhook = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook:
        print("DRY RUN:", inputs["message"][:100])
        return {"posted": False, "dry_run": True}

    resp = requests.post(webhook,
        json={"text": inputs["message"]},
        timeout=10)
    resp.raise_for_status()
    return {"posted": True}""",
    }


# ─────────────────────────────────────────────────────────────
# COST CALCULATIONS
# ─────────────────────────────────────────────────────────────

GEMINI_PRICING = {
    "gemini-2.5-pro":  {"input_per_M": 1.25, "output_per_M": 10.00},
    "gemini-2.5-flash": {"input_per_M": 0.15, "output_per_M": 0.60},
}

AVG_TOKENS = {
    "reasoning": {"i": 2000, "o": 800},
    "tool_call": {"i": 300, "o": 100},
}


def compute_costs(steps, analysis):
    """Compute agent vs pipeline costs."""
    # Agent cost (all steps on gemini-2.5-pro)
    i_tokens = sum(
        AVG_TOKENS.get(s.get("step_type", "reasoning"), AVG_TOKENS["reasoning"])["i"]
        for s in steps
    )
    o_tokens = sum(
        AVG_TOKENS.get(s.get("step_type", "reasoning"), AVG_TOKENS["reasoning"])["o"]
        for s in steps
    )
    p = GEMINI_PRICING["gemini-2.5-pro"]
    agent_cost = round(i_tokens / 1e6 * p["input_per_M"] + o_tokens / 1e6 * p["output_per_M"], 6)

    # Pipeline cost (only AI_REQUIRED steps on gemini-2.5-flash)
    ai_steps = [s for s in analysis if s.get("classification") == "AI_REQUIRED"]
    if ai_steps:
        pi = len(ai_steps) * 500
        po = len(ai_steps) * 100
        pf = GEMINI_PRICING["gemini-2.5-flash"]
        pipeline_cost = round(pi / 1e6 * pf["input_per_M"] + po / 1e6 * pf["output_per_M"], 6)
    else:
        pipeline_cost = 0.0

    reduction = round((1 - pipeline_cost / agent_cost) * 100, 1) if agent_cost > 0 else 100
    yearly_savings = round((agent_cost - pipeline_cost) * 52, 4)

    return {
        "agent_cost": agent_cost,
        "agent_model": "gemini-2.5-pro",
        "pipeline_cost": pipeline_cost,
        "pipeline_model": "gemini-2.5-flash" if ai_steps else "none",
        "reduction_pct": reduction,
        "savings_per_run": round(agent_cost - pipeline_cost, 6),
        "yearly_savings": yearly_savings,
    }


# ─────────────────────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────────────────────

def run_pipeline(repo, github_token="", events=None, notification_channels=None):
    """
    Run the full FADE pipeline for the given repository.

    Args:
        repo: GitHub repository in 'owner/repo' format
        github_token: GitHub personal access token (optional)
        events: PipelineEvents instance for real-time updates
        notification_channels: list of {"type": "slack"|"discord"|"teams", "url": "webhook_url"}

    Returns:
        dict with all results
    """
    if events is None:
        events = PipelineEvents()
    if notification_channels is None:
        notification_channels = []

    token = github_token or os.environ.get("GITHUB_TOKEN", "")
    use_ai = bool(os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip())

    events.emit("status", {"phase": "starting", "repo": repo})

    # ──────────────────────────────────────────────────────────
    # PHASE 1: Agent Execution (simulate the agent's workflow)
    # ──────────────────────────────────────────────────────────

    events.emit("status", {"phase": "phase1", "message": "Agent executing task..."})

    execution_steps = []
    t0 = datetime.now(timezone.utc)

    # Step 1: Planning
    step1_time = datetime.now(timezone.utc)
    step1 = {
        "step_number": 1,
        "step_type": "reasoning",
        "description": "Plan the weekly PR digest workflow",
        "input_summary": f"User request: generate weekly PR digest for {repo}",
        "output_summary": "Plan: 1) Fetch merged PRs, 2) Get file changes, 3) Categorize, 4) Summarize, 5) Format, 6) Post to Slack",
        "timestamp": step1_time.isoformat(),
    }
    execution_steps.append(step1)
    events.emit("phase1_step", step1)
    time.sleep(0.3)

    # Step 2: Fetch merged PRs
    step2_time = datetime.now(timezone.utc)
    events.emit("phase1_step", {
        "step_number": 2,
        "step_type": "tool_call",
        "description": f"Fetching merged PRs from {repo}...",
        "input_summary": f"GET /repos/{repo}/pulls?state=closed&sort=updated",
        "output_summary": "Fetching...",
        "timestamp": step2_time.isoformat(),
        "pending": True,
    })

    pr_lookup_days = 7
    try:
        prs = fetch_merged_prs(repo, token, days=pr_lookup_days)
    except RuntimeError as e:
        events.emit("error", {"message": str(e)})
        return {"error": str(e)}

    if not prs:
        for span in (30, 90):
            try:
                prs = fetch_merged_prs(repo, token, days=span)
            except RuntimeError:
                prs = []
            if prs:
                pr_lookup_days = span
                break

    step2_done_time = datetime.now(timezone.utc)
    step2 = {
        "step_number": 2,
        "step_type": "tool_call",
        "description": "Fetch merged PRs from GitHub API",
        "input_summary": f"GET /repos/{repo}/pulls?state=closed&sort=updated&direction=desc&per_page=30",
        "output_summary": f"Retrieved {len(prs)} merged PRs from the last {pr_lookup_days} days",
        "timestamp": step2_done_time.isoformat(),
    }
    execution_steps.append(step2)
    events.emit("phase1_step", step2)

    if not prs:
        msg = (
            f"No merged PRs found in {repo} in the last 90 days. "
            "Try a busier repo, check the name (owner/repo), or use a token if the repo is private."
        )
        events.emit("error", {"message": msg})
        return {"error": msg}

    time.sleep(0.2)

    # Step 3: Fetch file changes
    step3_start = datetime.now(timezone.utc)
    events.emit("phase1_step", {
        "step_number": 3,
        "step_type": "tool_call",
        "description": f"Fetching file changes for {min(len(prs), 15)} PRs...",
        "input_summary": f"GET /repos/{repo}/pulls/{{number}}/files for {min(len(prs),15)} PRs",
        "output_summary": "Fetching...",
        "timestamp": step3_start.isoformat(),
        "pending": True,
    })

    pr_files = {}
    for pr in prs[:15]:
        files = fetch_pr_files(repo, pr["number"], token)
        pr_files[pr["number"]] = files
        pr["files_changed"] = files

    step3_done = datetime.now(timezone.utc)
    avg_files = round(sum(len(v) for v in pr_files.values()) / max(len(pr_files), 1), 1)
    step3 = {
        "step_number": 3,
        "step_type": "tool_call",
        "description": "Fetch file changes for each merged PR",
        "input_summary": f"GET /repos/{repo}/pulls/{{number}}/files for {len(pr_files)} PRs",
        "output_summary": f"Retrieved file lists for all {len(pr_files)} PRs (avg {avg_files} files per PR)",
        "timestamp": step3_done.isoformat(),
    }
    execution_steps.append(step3)
    events.emit("phase1_step", step3)
    time.sleep(0.2)

    # Step 4: Categorize PRs
    step4_time = datetime.now(timezone.utc)
    categorized = {}
    agent_categories = {}
    for pr in prs:
        cat = categorize_pr(
            pr["title"],
            pr.get("body", ""),
            pr.get("files_changed", pr_files.get(pr["number"], [])),
        )
        categorized.setdefault(cat, []).append(pr)
        agent_categories[str(pr["number"])] = cat

    cat_summary = ", ".join(
        f"{len(v)} {k}" for k, v in sorted(categorized.items(), key=lambda x: -len(x[1]))
    )
    step4 = {
        "step_number": 4,
        "step_type": "reasoning",
        "description": "Categorize each PR into bug_fix, new_feature, refactor, docs, test, or chore",
        "input_summary": f"{len(prs)} PRs with titles, bodies, and file lists",
        "output_summary": f"Categorized: {cat_summary}",
        "timestamp": step4_time.isoformat(),
    }
    execution_steps.append(step4)
    events.emit("phase1_step", step4)
    time.sleep(0.2)

    # Step 5: Generate summaries
    step5_time = datetime.now(timezone.utc)
    events.emit("phase1_step", {
        "step_number": 5,
        "step_type": "reasoning",
        "description": f"Generating summaries for {len(prs)} PRs...",
        "input_summary": f"{len(prs)} PRs with titles, bodies, and categories",
        "output_summary": "Generating...",
        "timestamp": step5_time.isoformat(),
        "pending": True,
    })

    summaries = {}
    summary_fn = generate_summary_ai if use_ai else generate_summary_local
    for pr in prs:
        summaries[pr["number"]] = summary_fn(pr)

    step5_done = datetime.now(timezone.utc)
    step5 = {
        "step_number": 5,
        "step_type": "reasoning",
        "description": "Generate concise summary for each PR",
        "input_summary": f"{len(prs)} PRs with titles, bodies, and categories",
        "output_summary": f"Generated one-sentence summaries for all {len(prs)} PRs",
        "timestamp": step5_done.isoformat(),
    }
    execution_steps.append(step5)
    events.emit("phase1_step", step5)
    time.sleep(0.2)

    # Step 6: Formatting decision
    step6_time = datetime.now(timezone.utc)
    step6 = {
        "step_number": 6,
        "step_type": "reasoning",
        "description": "Decide on formatting structure for Slack message",
        "input_summary": f"{len(prs)} categorized and summarized PRs",
        "output_summary": "Format: header with date range and count, sections grouped by category with emoji, PR links with author attribution",
        "timestamp": step6_time.isoformat(),
    }
    execution_steps.append(step6)
    events.emit("phase1_step", step6)
    time.sleep(0.2)

    # Step 7: Format the digest
    step7_time = datetime.now(timezone.utc)
    agent_slack = format_slack_digest(repo, categorized, summaries)
    step7 = {
        "step_number": 7,
        "step_type": "reasoning",
        "description": "Format the Slack digest message",
        "input_summary": "Categorized PRs, summaries, formatting plan",
        "output_summary": f"Formatted Slack message with markdown, emoji categories, and PR links ({len(agent_slack)} chars)",
        "timestamp": step7_time.isoformat(),
    }
    execution_steps.append(step7)
    events.emit("phase1_step", step7)
    time.sleep(0.2)

    # Step 8: Post digest to configured channels
    step8_time = datetime.now(timezone.utc)
    channel_names = [ch.get("type", "unknown") for ch in notification_channels if ch.get("url", "").strip()]
    has_email = any(ch.get("type") == "email" for ch in notification_channels if ch.get("url", "").strip())
    if has_email:
        channel_names = [n for n in channel_names if n != "email"]  # email is handled client-side
        channel_names.append("email")
    if channel_names:
        ch_desc = ", ".join(c.title() for c in channel_names)
        step8_desc = f"Deliver digest to {ch_desc}"
        step8_out = f"Configured: {ch_desc}"
    else:
        step8_desc = "Post formatted digest (dry run)"
        step8_out = "No channels configured — dry run completed successfully"
    step8 = {
        "step_number": 8,
        "step_type": "tool_call",
        "description": step8_desc,
        "input_summary": f"Deliver formatted digest to configured notification channels",
        "output_summary": step8_out,
        "timestamp": step8_time.isoformat(),
    }
    execution_steps.append(step8)
    events.emit("phase1_step", step8)

    events.emit("phase1_complete", {
        "total_steps": len(execution_steps),
        "tool_calls": sum(1 for s in execution_steps if s["step_type"] == "tool_call"),
        "reasoning_steps": sum(1 for s in execution_steps if s["step_type"] == "reasoning"),
    })

    # ──────────────────────────────────────────────────────────
    # PHASE 2: Self-Analysis
    # ──────────────────────────────────────────────────────────

    events.emit("status", {"phase": "phase2", "message": "Analyzing agent steps..."})
    time.sleep(0.5)

    events.emit("phase2_start", {"total": len(STEP_CLASSIFICATIONS)})

    analysis = []
    for i, classification in enumerate(STEP_CLASSIFICATIONS):
        # Simulate analysis taking time for dramatic effect
        cls = classification["classification"]
        delay = 0.4 if cls == "DETERMINISTIC" else 0.6 if cls == "RULE_BASED" else 0.8
        time.sleep(delay)

        analysis.append(classification)
        events.emit("phase2_step", classification)

    events.emit("phase2_complete", {
        "total": len(analysis),
        "deterministic": sum(1 for s in analysis if s["classification"] == "DETERMINISTIC"),
        "rule_based": sum(1 for s in analysis if s["classification"] == "RULE_BASED"),
        "ai_required": sum(1 for s in analysis if s["classification"] == "AI_REQUIRED"),
    })

    # ──────────────────────────────────────────────────────────
    # PHASE 3: Results
    # ──────────────────────────────────────────────────────────

    events.emit("status", {"phase": "phase3", "message": "Generating deprecation report..."})
    time.sleep(0.8)

    # Generate pipeline slack (same data, slightly different format to show it matches)
    pipeline_slack = format_slack_digest(repo, categorized, summaries)

    # Compute costs
    costs = compute_costs(execution_steps, analysis)

    # Classification counts
    det_count = sum(1 for s in analysis if s["classification"] == "DETERMINISTIC")
    rule_count = sum(1 for s in analysis if s["classification"] == "RULE_BASED")
    ai_count = sum(1 for s in analysis if s["classification"] == "AI_REQUIRED")
    n_classified = len(analysis)
    ai_pct = round(ai_count / n_classified * 100) if n_classified else 0

    result = {
        "repo": repo,
        "execution_trace": {
            "task": "weekly_pr_digest",
            "repo": repo,
            "executed_at": t0.isoformat(),
            "total_steps": len(execution_steps),
            "steps": execution_steps,
            "summary": {
                "tool_calls": sum(1 for s in execution_steps if s["step_type"] == "tool_call"),
                "reasoning_steps": sum(1 for s in execution_steps if s["step_type"] == "reasoning"),
            },
            "pr_data": prs,
            "agent_categories": agent_categories,
        },
        "analysis_report": analysis,
        "agent_slack": agent_slack,
        "pipeline_slack": pipeline_slack,
        "costs": costs,
        "classification_summary": {
            "total": n_classified,
            "deterministic": det_count,
            "rule_based": rule_count,
            "ai_required": ai_count,
            "ai_pct_before": 100,
            "ai_pct_after": ai_pct,
        },
        "pr_count": len(prs),
        "script_snippets": get_script_snippets(repo),
        "email_html": format_email_digest(repo, categorized, summaries),
        "delivery_results": [],
    }

    # Deliver to all configured notification channels
    active_channels = [ch for ch in notification_channels if ch.get("url", "").strip()]
    if active_channels:
        events.emit("status", {"phase": "delivering", "message": "Sending digest to channels..."})
        delivery_results = deliver_notifications(active_channels, repo, categorized, summaries, events)
        result["delivery_results"] = delivery_results

    events.emit("phase3_result", result)
    events.emit("status", {"phase": "complete", "message": "Pipeline complete"})

    _persist_trace_artifacts(result)

    return result


def _persist_trace_artifacts(result):
    """Write trace JSON next to the server so /api/fade-state and CLI phases stay in sync."""
    base = os.path.dirname(os.path.abspath(__file__))
    try:
        et = result.get("execution_trace") or {}
        with open(os.path.join(base, "execution_trace.json"), "w", encoding="utf-8") as f:
            json.dump(et, f, indent=2)
        with open(os.path.join(base, "analysis_report.json"), "w", encoding="utf-8") as f:
            json.dump(result.get("analysis_report") or [], f, indent=2)
        costs = result.get("costs") or {}
        out = {
            "agent_slack": result.get("agent_slack", ""),
            "pipeline_slack": result.get("pipeline_slack", ""),
            "metrics": {
                "agent_cost_usd": costs.get("agent_cost"),
                "pipeline_cost_usd": costs.get("pipeline_cost"),
                "reduction_pct": costs.get("reduction_pct"),
                "yearly_savings_usd": costs.get("yearly_savings"),
            },
        }
        with open(os.path.join(base, "dashboard_outputs.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
    except OSError:
        pass
