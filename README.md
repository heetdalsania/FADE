# FADE - Fast Agent Deprecation Engine 🚀

FADE (Fast Agent Deprecation Engine) is an autonomous, self-analyzing platform designed to generate high-quality periodic (e.g., weekly) Pull Request digests for GitHub repositories. It fetches PR data, intelligently categorizes changes, generates concise summaries (via Gemini AI or local rule-based parsing), formats them beautifully, and posts them to channels like Slack, Discord, Microsoft Teams, and Email.

The unique premise of FADE lies in its architecture: an AI agent that **watches its own execution trace**, categorizing and transitioning its AI-dependent reasoning steps into deterministic code snippets once a fixed pattern is established, essentially "deprecating" its reliance on the AI model for repeated tasks to save cost and increase performance.

## 🌟 Features

*   **Multi-Channel Digest Delivery:** Automatically broadcast digest reports to:
    *   Slack & Discord (via webhooks)
    *   Microsoft Teams (Adaptive Cards)
    *   Email (Server-side Gmail SMTP delivery)
*   **Intelligent Categorization:** Automatically sort PRs into insightful categories like `New Features`, `Bug Fixes`, `Refactors`, `Tests`, `Documentation`, and `Chores`.
*   **Dual-Mode Summarization:**
    *   *AI Mode:* Uses Google Gemini 2.5 Flash/Pro for human-like PR summarization.
    *   *Local Mode:* Deterministic parsing of PR body for local execution fallback.
*   **Interactive Dashboard UI:** Includes a comprehensive web dashboard (`dashboard.html`) equipped with real-time SSE (Server-Sent Events) pipeline tracing and delivery status visualization.
*   **Execution Tracing:** FADE logs every step (both API "tool calls" and AI "reasoning") into a JSON trace format, later analyzing it to classify steps into `RULE_BASED`, `DETERMINISTIC`, or `AI_REQUIRED`.

## 📂 Project Structure

*   `server.py`: The FADE Dashboard HTTP Server, serving the UI and API endpoints. 
*   `pipeline_runner.py`: The robust pipeline execution and delivery module (runs GitHub extraction, categorization, formatting, and webhook/SMTP dispatch).
*   `agent.py`: The core autonomous agent logic demonstrating the "Self-Eliminating Agent" concept and generating execution traces.
*   `dashboard.html / css / js`: The frontend Web Dashboard client.

## 📋 Prerequisites

*   Python 3.8+
*   Google Cloud Platform project (if using Gemini AI features)
*   GitHub Personal Access Token (for fetching PR data)

## 🛠️ Installation

1. **Clone the repository:**
   ```bash
   git clone <repository_url>
   cd FADE
   ```

2. **Install dependent Python libraries:**
   ```bash
   pip install requests google-genai
   ```

## ⚙️ Environment Variables Setup

Depending on the pieces of FADE you want to utilize, you need to set up certain environment variables. 

### GitHub Setup (Required)
```bash
export GITHUB_TOKEN="ghp_your_github_token"
export GITHUB_REPO="owner/repo" # e.g. "facebook/react" (used for agent.py test runs)
```

### Google Cloud & Gemini Platform Setup (Optional, for AI summarizations)
```bash
export GOOGLE_CLOUD_PROJECT="your-google-project-id"
export GOOGLE_CLOUD_LOCATION="us-central1"
# Ensure your local gcloud application-default auth is set if required for Vertex AI
```

### Email Notifications via Gmail SMTP (Optional)
To enable FADE to send emails, you need an app password from your Google account.
```bash
export FADE_EMAIL_SENDER="your-email@gmail.com" # E.g., fadeeeeai@gmail.com
export FADE_EMAIL_PASSWORD="your-app-password"  # Your Google App Password (not your usual password)
```

### Webhook Notification Channels Setup (Optional)
```bash
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/xxx/yyy/zzz"
```

## 🚀 Usage Guide

### 1. Starting the Full FADE Dashboard Server
Run the local HTTP server to launch the frontend web interface:
```bash
python server.py 8080
```
Then, navigate your browser to:
`http://localhost:8080/dashboard.html`

From the interactive dashboard, you can trigger pipeline runs against any repository, provide GitHub tokens securely via the UI, visualize the execution trace in real-time, and download execution reports.

### 2. Running The Autonomous Agent Directly (CLI)
You can directly execute the main agent sequence outside the server wrapper.

**Manual (Local) Deterministic Mode** (Runs local heuristic categorization and dry-runs notifications without utilizing Gemini):
```bash
python agent.py --manual
```

**AI Agent Mode** (Invokes Gemini to reason about PR topics and formats):
```bash
python agent.py
```
*Note: Ensure `GOOGLE_CLOUD_PROJECT` is set before running in AI Agent Mode.*

## 📈 Cost Analysis Engine

FADE runs an embedded cost calculation to evaluate efficiency gains: computing the financial impact of shifting repetitive reasoning nodes (traditionally routed to large foundation models) into hard-coded scripted steps, outputting the projected savings locally per repository.
