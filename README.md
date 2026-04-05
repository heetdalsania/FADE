# FADE — The Self-Eliminating Agent

**F**unction-call **A**nalysis and **D**ependency **E**limination

> *"You don't need me anymore." — The Agent*

FADE is an agentic system that watches itself work, analyzes its own execution trace, and progressively eliminates its own AI dependency — replacing LLM reasoning with deterministic pipelines wherever possible.

---

## Overview

Most AI agents use a language model for every step of a workflow. FADE challenges that assumption. It runs a real task (a GitHub PR digest posted to Slack), records a structured execution trace, then feeds that trace back to a second-stage analyzer that classifies each step:

| Classification | Description | Action |
|---|---|---|
| 🟢 **DETERMINISTIC** | Pure API call, always the same | Replace with direct function call |
| 🟡 **RULE_BASED** | Predictable decision, extractable as heuristics | Generate if/else rules, validate against real data |
| 🔴 **AI_REQUIRED** | Genuine language understanding needed | Keep, but downgrade to cheaper model |

The result is a **generated pipeline** — a standalone Python script that performs the same task with a fraction of the original AI overhead.

---

## Architecture

```
Phase 1 (agent.py)
  └─► Gemini + function calling runs the task
  └─► Every step is logged to execution_trace.json

Phase 2 (phase2_improved.py)
  └─► Reads execution_trace.json
  └─► Stage 1: Classifies each step (DETERMINISTIC / RULE_BASED / AI_REQUIRED)
  └─► Stage 2: Extracts categorization rules from real PR data
  └─► Stage 3: Validates rules, iterates until ≥80% accuracy
  └─► Stage 4: Assembles generated_pipeline.py
  └─► Writes deprecation_report.txt with computed cost metrics
```

**Output files (written at runtime):**

| File | Description |
|---|---|
| `execution_trace.json` | Step-by-step log of the agent's actions |
| `analysis_report.json` | Per-step classifications from Phase 2 |
| `categorization_rules.py` | Auto-generated PR categorization function |
| `generated_pipeline.py` | The final minimal-AI pipeline |
| `deprecation_report.txt` | Cost metrics and AI dependency comparison |

---

## Requirements

- Python 3.10+
- A Google Cloud project with Vertex AI enabled
- A GitHub personal access token (read access to the target repo)
- A Slack incoming webhook URL (optional — dry-run mode works without it)

Install dependencies:

```bash
pip install google-genai requests
```

---

## Configuration

Set the following environment variables before running:

```bash
export GOOGLE_CLOUD_PROJECT="your-gcp-project-id"
export GOOGLE_CLOUD_LOCATION="us-central1"
export GITHUB_TOKEN="ghp_your_token_here"
export GITHUB_REPO="owner/repo"              # e.g. facebook/react
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."  # optional
```

Authenticate with Google Cloud:

```bash
gcloud auth application-default login
```

---

## Usage

### Phase 1 — Run the Agent

```bash
# Full mode (requires Vertex AI credentials)
python agent.py

# Manual mode — tests GitHub/Slack connectivity without Gemini
python agent.py --manual
```

Produces `execution_trace.json`.

### Phase 2 — Self-Analysis

```bash
python phase2_improved.py
```

Reads `execution_trace.json`. Produces `analysis_report.json`, `categorization_rules.py`, `generated_pipeline.py`, and `deprecation_report.txt`.

### Run the Generated Pipeline

```bash
python generated_pipeline.py
```

This is the deprecation artifact — the same task, minimal AI.

---

## Dashboard (GitHub Pages)

The `/docs` folder contains a static dashboard that visualizes the output files. GitHub Pages serves this folder directly — no server required.

**To update the dashboard:**

1. Run Phase 1 and Phase 2 locally
2. Copy the output JSON files into `/docs`:
   ```bash
   cp execution_trace.json analysis_report.json deprecation_report.txt docs/
   ```
3. Commit and push — the dashboard updates automatically

**To automate this with GitHub Actions** (run weekly, auto-update dashboard):

Create `.github/workflows/run_fade.yml`:

```yaml
name: Run FADE Pipeline

on:
  schedule:
    - cron: '0 9 * * 1'   # Every Monday at 9am UTC
  workflow_dispatch:        # Also allow manual trigger

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install google-genai requests

      - name: Run agent (manual mode)
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_REPO: ${{ secrets.GITHUB_REPO }}
        run: python agent.py --manual

      - name: Run Phase 2 analysis
        env:
          GOOGLE_CLOUD_PROJECT: ${{ secrets.GOOGLE_CLOUD_PROJECT }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_REPO: ${{ secrets.GITHUB_REPO }}
        run: python phase2_improved.py

      - name: Copy outputs to docs/
        run: |
          cp execution_trace.json docs/
          cp analysis_report.json docs/
          cp deprecation_report.txt docs/

      - name: Commit and push
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add docs/
          git diff --staged --quiet || git commit -m "chore: update FADE outputs [skip ci]"
          git push
```

Add your secrets under **Settings → Secrets and variables → Actions**.

---

## Enabling GitHub Pages

1. Go to your repository **Settings → Pages**
2. Under **Source**, select **Deploy from a branch**
3. Set branch to `main`, folder to `/docs`
4. Save — your dashboard will be live at `https://<your-username>.github.io/FADE`

> **Note:** The dashboard displays previously generated output files. It does not trigger new agent runs — use the GitHub Actions workflow or run locally for that.

---

## Project Structure

```
FADE/
├── agent.py                  # Phase 1: the agent that runs and logs itself
├── phase2_improved.py        # Phase 2: self-analysis and pipeline generation
├── docs/
│   ├── index.html            # Static dashboard (reads JSON outputs)
│   ├── execution_trace.json  # Last run's step log
│   ├── analysis_report.json  # Last run's step classifications
│   └── deprecation_report.txt
├── .github/
│   └── workflows/
│       └── run_fade.yml      # Optional automation
└── README.md
```

---

## How the Cost Model Works

All cost estimates are computed dynamically from the actual execution trace — nothing is hardcoded. Phase 2 counts token usage per step type, applies current Vertex AI pricing (Gemini 2.5 Pro for the agent, Gemini 2.5 Flash for the optimized pipeline), and reports:

- **Cost per run** before and after optimization
- **AI dependency** (% of steps requiring a language model)
- **Projected annual savings** over 52 weekly runs

---

## License

MIT
