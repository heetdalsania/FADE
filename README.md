# FADE — Fast Agent Deprecation Engine

FADE is an autonomous, self-analyzing platform that generates weekly Pull Request digests for any GitHub repository — and then figures out which parts of itself no longer need AI to do it.

The core idea: an AI agent executes a real workflow, logs every step it takes, and then reads its own execution trace to classify each step as `DETERMINISTIC`, `RULE_BASED`, or `AI_REQUIRED`. It generates a leaner pipeline that replaces AI calls with deterministic code wherever possible, cutting per-run cost by up to 99.8% without changing the output.

---

## How It Works

**Phase 1 — Agent Execution**
The agent runs the full PR digest workflow against a real GitHub repository. Every step — API calls, categorization decisions, summary generation, formatting, and delivery — is logged into an execution trace with timestamps and step types.

**Phase 2 — Self-Analysis**
The agent reads its own trace and classifies every step. Steps that are always the same HTTP call become `DETERMINISTIC`. Steps that follow predictable patterns (like keyword-based PR categorization) become `RULE_BASED`. Only steps that genuinely require language understanding stay `AI_REQUIRED`.

**Phase 3 — Pipeline Generation**
FADE generates a standalone Python pipeline that replaces all `DETERMINISTIC` and `RULE_BASED` steps with plain code, and downgrades remaining AI calls from Gemini 2.5 Pro to Gemini 2.5 Flash. The output is a working script, a cost comparison report, and a side-by-side digest comparison proving the output is identical.

---

## Features

- **Real-time dashboard** — browser-based UI with live step-by-step execution tracing via Server-Sent Events (SSE)
- **Multi-channel delivery** — Slack, Discord, Microsoft Teams (Adaptive Cards), and Email (Gmail SMTP)
- **Intelligent PR categorization** — keyword scoring across title, body, and file paths; validated against real PR data
- **Dual summarization modes** — Gemini 2.5 Flash for AI summaries, deterministic body parsing as a zero-cost fallback
- **Cost analysis** — per-run and annualized savings computed from token estimates and model pricing
- **Generated artifacts** — `generated_pipeline.py`, `analysis_report.json`, `categorization_rules.py`, `deprecation_report.txt`

---

## Project Structure

```
server.py              — HTTP server, SSE streaming, API endpoints
pipeline_runner.py     — Phases 1–3 execution engine and delivery
agent.py               — Standalone CLI agent with execution trace logging
dashboard.html         — Frontend dashboard
dashboard_app.js       — React UI (SSE client, real-time phase rendering)
dashboard_styles.css   — Dashboard styles
phase2_improved.py     — Offline self-analysis runner (CLI)
categorization_rules.py — Generated keyword-scoring categorization function
```

---

## Prerequisites

- Python 3.8+
- Google Cloud Platform project with Vertex AI enabled (for Gemini features)
- GitHub Personal Access Token (recommended; required for private repos)

---

## Installation

```bash
git clone <repository_url>
cd FADE
pip install requests google-genai
```

---

## Environment Variables

```bash
# Required for fetching PR data
export GITHUB_TOKEN="ghp_your_github_token"

# Required for AI summarization (Phase 1 and 2)
export GOOGLE_CLOUD_PROJECT="your-gcp-project-id"
export GOOGLE_CLOUD_LOCATION="us-central1"

# Optional — Slack webhook delivery
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/xxx/yyy/zzz"

# Optional — Email delivery (Gmail App Password, not your account password)
export FADE_EMAIL_SENDER="your-email@gmail.com"
export FADE_EMAIL_PASSWORD="your-app-password"
```

For Google Cloud authentication:
```bash
gcloud auth application-default login
```

---

## Usage

**Start the dashboard server:**
```bash
python server.py 8080
# Open http://localhost:8080/dashboard.html
```

Enter any public GitHub repo (`owner/repo`), optionally add a token and delivery channels, and hit Run. FADE streams all three phases live to the browser.

**Run the agent from the CLI:**
```bash
# Local mode — no Gemini required, uses deterministic categorization
python agent.py --manual

# Full AI mode — requires GOOGLE_CLOUD_PROJECT
python agent.py
```

**Run self-analysis offline (after generating a trace):**
```bash
python phase2_improved.py
```

---

## AI & Tool Disclosure

FADE uses the following external AI models and tools. All core logic — the execution trace design, the three-phase self-analysis architecture, the step classification system, the rule extraction and validation loop, the pipeline code generation, and the cost analysis engine — was designed and implemented by our team.

| Tool / Service | Role |
|---|---|
| **Gemini 2.5 Pro** (via Vertex AI) | Agent execution, step classification in Phase 2, categorization rule extraction and repair |
| **Gemini 2.5 Flash** (via Vertex AI) | PR summary generation in the optimized pipeline |
| **Google Fonts** (Inter, JetBrains Mono) | Dashboard typography |
| **React 18** (CDN) | Dashboard frontend rendering |
| **Babel Standalone** (CDN) | In-browser JSX transpilation (no build step) |

FADE is not a wrapper around an existing tool. The self-deprecating agent pattern — where an agent analyzes its own execution trace and generates leaner code to replace itself — is the original contribution of this project. The AI models are used as components inside a larger system designed entirely by our team.

---

## Cost Analysis

For a weekly PR digest on `microsoft/vscode` (30 PRs):

| | Model | Cost per run |
|---|---|---|
| Original agent | Gemini 2.5 Pro (all 8 steps) | ~$0.056 |
| Generated pipeline | Gemini 2.5 Flash (1 step only) | ~$0.000135 |
| **Reduction** | | **99.8%** |

7 of 8 steps were replaced with deterministic Python. Only PR summarization genuinely required a language model.
