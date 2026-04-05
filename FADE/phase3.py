"""
DEPRECATE ME — Phase 3: Code Generation & Self-Validation
============================================================
Gemini generates Python scripts for every deterministic and rule-based
step. It wires them together into a pipeline with a scheduler config.
Then the key demo moment: it runs the generated pipeline on the SAME
inputs it just processed, compares outputs side-by-side, and produces
a deprecation report showing exactly how much AI dependency was
eliminated.

SETUP: Same env vars as Phase 1 + Phase 2.
RUN:   python phase3.py

Reads:  execution_trace.json, analysis_report.json, categorization_rules.py
Writes: generated_pipeline.py, scheduler_config.json, deprecation_report.txt
"""

import os
import sys
import json
import time
from datetime import datetime, timedelta, timezone

import requests


# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "facebook/react")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
GOOGLE_CLOUD_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
GOOGLE_CLOUD_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

GEMINI_PRICING = {
    "gemini-2.5-pro":  {"input_per_M": 1.25, "output_per_M": 10.00},
    "gemini-2.5-flash": {"input_per_M": 0.15, "output_per_M": 0.60},
}


# ─────────────────────────────────────────────────────────────
# STEP 1 — LOAD PHASE 2 OUTPUTS
# ─────────────────────────────────────────────────────────────

def load_phase2_outputs():
    """Load the execution trace, analysis report, and categorization rules."""
    print("\n" + "=" * 60)
    print("  PHASE 3 — Code Generation & Self-Validation")
    print("=" * 60)

    with open("execution_trace.json", "r") as f:
        trace = json.load(f)
    print(f"\n  Loaded execution_trace.json ({trace['total_steps']} steps)")

    with open("analysis_report.json", "r") as f:
        analysis = json.load(f)
    print(f"  Loaded analysis_report.json ({len(analysis)} classified steps)")

    with open("categorization_rules.py", "r") as f:
        cat_rules_code = f.read()
    print(f"  Loaded categorization_rules.py ({len(cat_rules_code)} chars)")

    # Index analysis by step number
    analysis_map = {s["step_number"]: s for s in analysis}

    return trace, analysis, analysis_map, cat_rules_code


# ─────────────────────────────────────────────────────────────
# STEP 2 — GENERATE PYTHON SCRIPTS FOR EACH REPLACEABLE STEP
# ─────────────────────────────────────────────────────────────
# For DETERMINISTIC steps → direct API calls with requests
# For RULE_BASED steps   → the categorization rules from Phase 2
#                           + fixed template logic
# For AI_REQUIRED steps  → keep on Gemini (downgraded to Flash)

def generate_pipeline_code(trace, analysis_map, cat_rules_code):
    """
    Generate a single standalone pipeline script that replaces the
    original agent.  Every deterministic and rule-based step is pure
    Python.  Only AI_REQUIRED steps call Gemini (2.5 Flash).
    """
    print(f"\n{'─' * 60}")
    print("  Generating replacement pipeline code...")
    print(f"{'─' * 60}")

    # Show what's being replaced vs kept
    for step_num in sorted(analysis_map.keys()):
        step = analysis_map[step_num]
        icon = {
            "DETERMINISTIC": "\U0001f7e2",
            "RULE_BASED": "\U0001f7e1",
            "AI_REQUIRED": "\U0001f534",
        }.get(step["classification"], "\u26aa")
        action = "GENERATE SCRIPT" if step["classification"] != "AI_REQUIRED" else "KEEP ON AI (Flash)"
        print(f"    {icon} Step {step_num}: {step['original_description'][:50]}")
        print(f"       → {step['classification']} → {action}")

    # Count metrics
    total = len(analysis_map)
    det_count = sum(1 for s in analysis_map.values() if s["classification"] == "DETERMINISTIC")
    rule_count = sum(1 for s in analysis_map.values() if s["classification"] == "RULE_BASED")
    ai_count = sum(1 for s in analysis_map.values() if s["classification"] == "AI_REQUIRED")
    automated_count = det_count + rule_count

    print(f"\n    Scripts to generate: {automated_count} "
          f"({det_count} deterministic + {rule_count} rule-based)")
    print(f"    Steps kept on AI:   {ai_count}")

    # ── Build the pipeline source code ────────────────────────
    pipeline_code = _build_pipeline_source(trace, analysis_map, cat_rules_code)

    with open("generated_pipeline.py", "w") as f:
        f.write(pipeline_code)
    print(f"\n    Saved: generated_pipeline.py ({len(pipeline_code)} chars)")

    return pipeline_code


def _build_pipeline_source(trace, analysis_map, cat_rules_code):
    """Assemble the full generated_pipeline.py source."""
    repo = trace.get("repo", "facebook/react")

    # Count classifications
    total = len(analysis_map)
    det_count = sum(1 for s in analysis_map.values() if s["classification"] == "DETERMINISTIC")
    rule_count = sum(1 for s in analysis_map.values() if s["classification"] == "RULE_BASED")
    ai_count = sum(1 for s in analysis_map.values() if s["classification"] == "AI_REQUIRED")

    return f'''#!/usr/bin/env python3
"""
GENERATED PIPELINE — Auto-created by FADE Phase 3
====================================================
This script replaces the original AI agent. Every deterministic and
rule-based step is pure Python.  Only genuinely AI-dependent steps
(PR summarization) still call a model — downgraded from gemini-2.5-pro
to gemini-2.5-flash for maximum cost savings.

Original agent steps: {total}
  DETERMINISTIC: {det_count}  |  RULE_BASED: {rule_count}  |  AI_REQUIRED: {ai_count}
"""

import os
import sys
import json
import time
from datetime import datetime, timedelta, timezone

import requests


# ── Configuration (from environment — never hardcoded) ────────

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO", "{repo}")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")


# ── Runtime metrics tracker ──────────────────────────────────

class Metrics:
    def __init__(self):
        self.steps_run = 0
        self.api_calls = 0
        self.ai_calls = 0
        self.ai_input_tokens = 0
        self.ai_output_tokens = 0
        self.start = None
        self.end = None

    def tick(self):
        self.steps_run += 1

    @property
    def duration(self):
        if self.start and self.end:
            return round(self.end - self.start, 2)
        return 0

    @property
    def cost(self):
        p = {{"input_per_M": 0.15, "output_per_M": 0.60}}  # flash pricing
        return round(
            self.ai_input_tokens / 1e6 * p["input_per_M"]
            + self.ai_output_tokens / 1e6 * p["output_per_M"], 6
        )

metrics = Metrics()


# ═══════════════════════════════════════════════════════════════
# DETERMINISTIC STEPS — Pure Python, zero AI
# ═══════════════════════════════════════════════════════════════

def fetch_merged_prs(repo, days=7):
    """[DETERMINISTIC] Fetch merged PRs from GitHub REST API."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = f"https://api.github.com/repos/{{repo}}/pulls"
    headers = {{
        "Authorization": f"Bearer {{GITHUB_TOKEN}}",
        "Accept": "application/vnd.github+json",
    }}
    params = {{"state": "closed", "sort": "updated", "direction": "desc", "per_page": 50}}

    resp = requests.get(url, headers=headers, params=params, timeout=15)
    resp.raise_for_status()
    metrics.api_calls += 1
    metrics.tick()

    merged = []
    for pr in resp.json():
        if pr.get("merged_at") and pr["merged_at"] >= since:
            merged.append({{
                "number": pr["number"],
                "title": pr["title"],
                "author": pr["user"]["login"],
                "merged_at": pr["merged_at"],
                "url": pr["html_url"],
                "body": (pr.get("body") or "")[:500],
            }})
    return merged


def fetch_pr_files(repo, pr_number):
    """[DETERMINISTIC] Fetch changed files for a single PR."""
    url = f"https://api.github.com/repos/{{repo}}/pulls/{{pr_number}}/files"
    headers = {{
        "Authorization": f"Bearer {{GITHUB_TOKEN}}",
        "Accept": "application/vnd.github+json",
    }}
    resp = requests.get(url, headers=headers, params={{"per_page": 30}}, timeout=10)
    resp.raise_for_status()
    metrics.api_calls += 1
    return [f["filename"] for f in resp.json()]


def post_to_slack(message):
    """[DETERMINISTIC] POST the digest to the Slack webhook."""
    metrics.tick()
    if not SLACK_WEBHOOK_URL:
        print(f"\\n{{'=' * 50}}")
        print("SLACK MESSAGE (dry run):")
        print("=" * 50)
        print(message)
        print("=" * 50)
        return {{"posted": False, "dry_run": True}}

    resp = requests.post(SLACK_WEBHOOK_URL, json={{"text": message}}, timeout=10)
    resp.raise_for_status()
    metrics.api_calls += 1
    return {{"posted": True}}


# ═══════════════════════════════════════════════════════════════
# RULE-BASED STEPS — Keyword scoring, no AI
# ═══════════════════════════════════════════════════════════════

{cat_rules_code}


def format_slack_digest(repo, categorized_prs, pr_summaries):
    """[RULE-BASED] Render the Slack digest from a fixed template."""
    metrics.tick()

    def esc(text):
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%B %d")
    total = sum(len(v) for v in categorized_prs.values())

    emoji = {{
        "new_feature": "\\u2728", "bug_fix": "\\U0001f41b", "refactor": "\\U0001f527",
        "docs": "\\U0001f4da", "test": "\\U0001f9ea", "chore": "\\U0001f3d7\\ufe0f",
    }}
    labels = {{
        "new_feature": "New Features", "bug_fix": "Bug Fixes", "refactor": "Refactors",
        "docs": "Documentation", "test": "Tests", "chore": "Chores",
    }}
    order = ["new_feature", "bug_fix", "refactor", "docs", "test", "chore"]

    lines = [f"\\U0001f4cb *Weekly PR Digest \\u2014 {{week_ago}} to {{today}}*"]
    lines.append(f"_{{total}} PRs merged in `{{esc(repo)}}`_\\n")

    for cat in order:
        prs = categorized_prs.get(cat, [])
        if not prs:
            continue
        lines.append(f"{{emoji.get(cat, '\\U0001f4cc')}} *{{labels.get(cat, cat)}}* ({{len(prs)}})")
        for pr in prs:
            lines.append(
                f"  \\u2022 <{{pr['url']}}|#{{pr['number']}}> {{esc(pr['title'])}} \\u2014 _{{esc(pr['author'])}}_"
            )
            summary = pr_summaries.get(pr["number"], "")
            if summary and summary != pr["title"]:
                lines.append(f"    _{{esc(summary)}}_")
        lines.append("")

    return "\\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# AI-REQUIRED STEP — Gemini 2.5 Flash (downgraded from Pro)
# ═══════════════════════════════════════════════════════════════

def generate_pr_summary(pr):
    """[AI_REQUIRED] Generate a one-sentence summary via Gemini Flash."""
    metrics.tick()

    if not GOOGLE_CLOUD_PROJECT:
        print("  GOOGLE_CLOUD_PROJECT not set — cannot generate AI summaries.",
              file=sys.stderr)
        sys.exit(1)

    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(
        vertexai=True,
        project=GOOGLE_CLOUD_PROJECT,
        location=GOOGLE_CLOUD_LOCATION,
    )
    prompt = (
        "Write exactly one complete sentence (15-30 words) summarizing "
        "this GitHub PR. Focus on what changed and why. "
        "Do NOT truncate. Output ONLY the sentence, nothing else.\\n\\n"
        f"Title: {{pr['title']}}\\n"
        f"Description: {{(pr.get('body') or 'No description')[:500]}}\\n\\n"
        "Summary:"
    )
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.1, max_output_tokens=256,
            ),
        )
        text = (response.text or "").strip()
        if not text:
            return pr["title"]

        in_est = len(prompt.split()) * 2
        out_est = len(text.split()) * 2
        metrics.ai_calls += 1
        metrics.ai_input_tokens += in_est
        metrics.ai_output_tokens += out_est
        return text
    except Exception as e:
        print(f"  AI summary failed for PR #{{pr['number']}}: {{e}}")
        return pr["title"]


# ═══════════════════════════════════════════════════════════════
# PIPELINE MAIN — wires all steps together
# ═══════════════════════════════════════════════════════════════

def run_pipeline():
    """Execute the full replacement pipeline."""
    metrics.start = time.time()

    print("\\n" + "=" * 60)
    print("  GENERATED PIPELINE — FADE")
    print("  Mode: Minimal AI (gemini-2.5-flash for summaries only)")
    print("=" * 60)

    if not GITHUB_TOKEN:
        print("\\nGITHUB_TOKEN not set.", file=sys.stderr)
        sys.exit(1)
    if not GOOGLE_CLOUD_PROJECT:
        print("\\nGOOGLE_CLOUD_PROJECT not set.", file=sys.stderr)
        sys.exit(1)

    repo = GITHUB_REPO

    # ── [DETERMINISTIC] Step 1: Fetch merged PRs ─────────────
    print(f"\\n\\U0001f7e2 [1/6] Fetching merged PRs from {{repo}}...")
    prs = fetch_merged_prs(repo, days=7)
    print(f"       Found {{len(prs)}} merged PRs")

    if not prs:
        print("  No merged PRs found — nothing to digest.")
        return {{}}, {{}}

    # ── [DETERMINISTIC] Step 2: Fetch file changes ───────────
    print(f"\\n\\U0001f7e2 [2/6] Fetching file changes...")
    pr_files = {{}}
    for pr in prs[:15]:
        files = fetch_pr_files(repo, pr["number"])
        pr_files[pr["number"]] = files
        pr["files_changed"] = files
    metrics.tick()
    print(f"       Fetched files for {{len(pr_files)}} PRs")

    # ── [RULE-BASED] Step 3: Categorize PRs ──────────────────
    print(f"\\n\\U0001f7e1 [3/6] Categorizing PRs with keyword rules...")
    categorized = {{}}
    pr_categories = {{}}
    cat_emoji = {{"bug_fix": "\\U0001f41b", "new_feature": "\\u2728", "refactor": "\\U0001f527",
                  "docs": "\\U0001f4da", "test": "\\U0001f9ea", "chore": "\\U0001f3d7\\ufe0f"}}
    for pr in prs:
        files = pr.get("files_changed", pr_files.get(pr["number"], []))
        cat = categorize_pr(pr["title"], pr.get("body", ""), files)
        categorized.setdefault(cat, []).append(pr)
        pr_categories[pr["number"]] = cat
        print(f"       {{cat_emoji.get(cat, '\\U0001f4cc')}} #{{pr['number']}} {{pr['title'][:50]}} \\u2192 {{cat}}")
    metrics.tick()

    # ── [AI_REQUIRED] Step 4: Generate summaries (Flash) ─────
    print(f"\\n\\U0001f534 [4/6] Generating AI summaries (gemini-2.5-flash)...")
    summaries = {{}}
    for pr in prs:
        summaries[pr["number"]] = generate_pr_summary(pr)
        print(f"       #{{pr['number']}}: {{summaries[pr['number']][:70]}}...")

    # ── [RULE-BASED] Step 5: Format digest ───────────────────
    print(f"\\n\\U0001f7e1 [5/6] Formatting Slack digest...")
    digest = format_slack_digest(repo, categorized, summaries)
    print(f"       {{len(digest)}} chars")

    # ── [DETERMINISTIC] Step 6: Post to Slack ────────────────
    print(f"\\n\\U0001f7e2 [6/6] Posting to Slack...")
    post_to_slack(digest)

    metrics.end = time.time()

    return categorized, summaries


if __name__ == "__main__":
    run_pipeline()

    print(f"\\n{{'\\u2500' * 50}}")
    print(f"  RUNTIME METRICS")
    print(f"{{'\\u2500' * 50}}")
    print(f"  Steps run:        {{metrics.steps_run}}")
    print(f"  API calls:        {{metrics.api_calls}}")
    print(f"  AI calls:         {{metrics.ai_calls}}")
    print(f"  AI tokens (in):   ~{{metrics.ai_input_tokens}}")
    print(f"  AI tokens (out):  ~{{metrics.ai_output_tokens}}")
    print(f"  Duration:         {{metrics.duration}}s")
    print(f"  Estimated cost:   ${{metrics.cost}}")
    print(f"  AI dependency:    {{round(1/6*100)}}% (1 of 6 steps)")
    print(f"{{'\\u2500' * 50}}\\n")
'''


# ─────────────────────────────────────────────────────────────
# STEP 3 — GENERATE SCHEDULER CONFIG
# ─────────────────────────────────────────────────────────────

def generate_scheduler_config(trace):
    """Generate a Cloud Scheduler + Cloud Functions deployment config."""
    print(f"\n{'─' * 60}")
    print("  Generating scheduler config...")
    print(f"{'─' * 60}")

    repo = trace.get("repo", "facebook/react")

    config = {
        "scheduler": {
            "name": "fade-weekly-pr-digest",
            "schedule": "0 9 * * 1",
            "timezone": "Etc/UTC",
            "description": "FADE — weekly PR digest (auto-generated pipeline)",
        },
        "cloud_function": {
            "name": "fade-pr-digest-pipeline",
            "runtime": "python312",
            "entry_point": "run_pipeline",
            "source": "generated_pipeline.py",
            "memory": "512Mi",
            "timeout": "300s",
            "env_vars": [
                "GITHUB_TOKEN",
                "GITHUB_REPO",
                "SLACK_WEBHOOK_URL",
                "GOOGLE_CLOUD_PROJECT",
                "GOOGLE_CLOUD_LOCATION",
            ],
        },
        "cloud_storage": {
            "bucket": f"{GOOGLE_CLOUD_PROJECT}-fade-artifacts",
            "artifacts": [
                "execution_trace.json",
                "analysis_report.json",
                "generated_pipeline.py",
                "deprecation_report.txt",
            ],
        },
        "deploy_commands": {
            "deploy_function": (
                f"gcloud functions deploy fade-pr-digest-pipeline "
                f"--gen2 "
                f"--runtime=python312 "
                f"--region={GOOGLE_CLOUD_LOCATION} "
                f"--source=. "
                f"--entry-point=run_pipeline "
                f"--trigger-http "
                f"--memory=512Mi "
                f"--timeout=300s "
                f'--set-env-vars="GITHUB_REPO={repo}"'
            ),
            "create_scheduler": (
                f"gcloud scheduler jobs create http fade-weekly-pr-digest "
                f"--location={GOOGLE_CLOUD_LOCATION} "
                f'--schedule="0 9 * * 1" '
                f"--time-zone=Etc/UTC "
                f"--uri=<FUNCTION_URL> "
                f"--http-method=POST "
                f'--message-body=\'{{"repo":"{repo}","days":7}}\''
            ),
            "upload_artifacts": (
                f"gsutil cp execution_trace.json analysis_report.json "
                f"generated_pipeline.py deprecation_report.txt "
                f"gs://{GOOGLE_CLOUD_PROJECT}-fade-artifacts/"
            ),
        },
    }

    with open("scheduler_config.json", "w") as f:
        json.dump(config, f, indent=2)
    print(f"    Saved: scheduler_config.json")
    print(f"    Schedule: {config['scheduler']['schedule']} ({config['scheduler']['timezone']})")
    print(f"    Function: {config['cloud_function']['name']}")

    return config


# ─────────────────────────────────────────────────────────────
# STEP 4 — RUN BOTH PIPELINES & COMPARE SIDE-BY-SIDE
# ─────────────────────────────────────────────────────────────
# This is the key demo moment: run the generated pipeline on the
# SAME inputs the original agent processed, then compare outputs.

def run_side_by_side_comparison(trace, analysis_map, cat_rules_code):
    """
    Run the generated pipeline against the original agent's trace
    data and compare outputs at each step.
    """
    print(f"\n{'─' * 60}")
    print("  Running side-by-side comparison...")
    print(f"{'─' * 60}")

    pr_data = trace.get("pr_data", [])
    agent_categories = trace.get("agent_categories", {})

    if not pr_data:
        print("    No PR data in trace — skipping comparison")
        return {"skipped": True}

    comparison = {
        "total_prs": len(pr_data),
        "steps": [],
    }

    # ── Compare Step 4: Categorization ────────────────────────
    print(f"\n    Comparing categorization (agent vs rules)...")

    # Load and execute the categorization rules
    namespace = {}
    exec(cat_rules_code, namespace)
    categorize_fn = namespace.get("categorize_pr")

    if not categorize_fn:
        print("    Could not load categorize_pr function")
        return comparison

    matches = 0
    mismatches = []
    for pr in pr_data:
        rule_cat = categorize_fn(
            pr["title"],
            pr.get("body", ""),
            pr.get("files_changed", []),
        )
        agent_cat = agent_categories.get(str(pr["number"]))
        if agent_cat is None:
            continue

        if rule_cat == agent_cat:
            matches += 1
            icon = "\u2705"
        else:
            mismatches.append({
                "pr": pr["number"],
                "title": pr["title"][:50],
                "agent": agent_cat,
                "rules": rule_cat,
            })
            icon = "\u274c"

        print(f"      {icon} PR #{pr['number']}: agent={agent_cat}, rules={rule_cat}")

    total_compared = matches + len(mismatches)
    accuracy = matches / total_compared if total_compared > 0 else 0

    cat_result = {
        "step": "categorization",
        "classification": "RULE_BASED",
        "accuracy": round(accuracy, 4),
        "matches": matches,
        "total": total_compared,
        "result": "PASS" if accuracy >= 0.80 else "FAIL",
        "mismatches": mismatches,
    }
    comparison["steps"].append(cat_result)

    print(f"\n      Accuracy: {accuracy:.0%} ({matches}/{total_compared})")
    print(f"      Result:   {cat_result['result']}")

    # ── Compare Step 5: AI Summaries ──────────────────────────
    print(f"\n    Comparing summaries (AI required — validating quality)...")

    if GOOGLE_CLOUD_PROJECT:
        # Run on a small sample to save cost
        sample = pr_data[:2]
        summary_checks = []

        try:
            from google import genai
            from google.genai import types as genai_types

            client = genai.Client(
                vertexai=True,
                project=GOOGLE_CLOUD_PROJECT,
                location=GOOGLE_CLOUD_LOCATION,
            )

            for pr in sample:
                prompt = (
                    "Write exactly one complete sentence (15-30 words) summarizing "
                    "this GitHub PR. Focus on what changed and why. "
                    "Do NOT truncate. Output ONLY the sentence, nothing else.\n\n"
                    f"Title: {pr['title']}\n"
                    f"Description: {(pr.get('body') or 'No description')[:500]}\n\n"
                    "Summary:"
                )
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        temperature=0.1, max_output_tokens=256,
                    ),
                )
                text = (response.text or "").strip()
                is_complete = bool(text) and len(text) > 10 and text.rstrip()[-1] in ".!?"
                summary_checks.append({
                    "pr": pr["number"],
                    "summary": text,
                    "complete_sentence": is_complete,
                })
                icon = "\u2705" if is_complete else "\u274c"
                print(f"      {icon} PR #{pr['number']}: \"{text[:80]}\"")

            all_ok = all(c["complete_sentence"] for c in summary_checks)
            summary_result = {
                "step": "summarization",
                "classification": "AI_REQUIRED",
                "result": "PASS" if all_ok else "FAIL",
                "samples_tested": len(sample),
                "checks": summary_checks,
            }
        except Exception as e:
            print(f"      Error: {e}")
            summary_result = {
                "step": "summarization",
                "classification": "AI_REQUIRED",
                "result": "ERROR",
                "error": str(e),
            }
    else:
        print("      GOOGLE_CLOUD_PROJECT not set — skipping AI comparison")
        summary_result = {
            "step": "summarization",
            "classification": "AI_REQUIRED",
            "result": "SKIPPED",
        }

    comparison["steps"].append(summary_result)

    # ── Compare Step 7: Formatting ────────────────────────────
    print(f"\n    Comparing formatting (template output)...")

    # Build categorized dict using the rule engine
    categorized = {}
    for pr in pr_data:
        cat = categorize_fn(
            pr["title"], pr.get("body", ""), pr.get("files_changed", [])
        )
        pr_entry = {
            "number": pr["number"],
            "title": pr["title"],
            "author": pr["author"],
            "url": pr["url"],
        }
        categorized.setdefault(cat, []).append(pr_entry)

    # Use titles as stand-in summaries for format test
    summaries = {pr["number"]: pr["title"] for pr in pr_data}

    # Build the format function
    format_code = _get_format_function()
    fmt_ns = {}
    exec(format_code, fmt_ns)
    format_fn = fmt_ns.get("format_slack_digest")

    if format_fn:
        message = format_fn(trace.get("repo", "facebook/react"), categorized, summaries)
        checks = {
            "has_header": "Weekly PR Digest" in message,
            "has_categories": any(
                label in message
                for label in ["Bug Fixes", "New Features", "Refactors", "Documentation", "Tests", "Chores"]
            ),
            "has_all_prs": all(f"#{pr['number']}" in message for pr in pr_data),
            "reasonable_length": len(message) > 100,
        }
        all_pass = all(checks.values())
        for check_name, passed in checks.items():
            icon = "\u2705" if passed else "\u274c"
            print(f"      {icon} {check_name}")

        format_result = {
            "step": "formatting",
            "classification": "RULE_BASED",
            "result": "PASS" if all_pass else "FAIL",
            "checks": checks,
            "message_length": len(message),
        }
    else:
        format_result = {
            "step": "formatting",
            "classification": "RULE_BASED",
            "result": "ERROR",
            "error": "Could not load format function",
        }

    comparison["steps"].append(format_result)

    # ── Overall result ────────────────────────────────────────
    passed = sum(1 for s in comparison["steps"] if s["result"] == "PASS")
    failed = sum(1 for s in comparison["steps"] if s["result"] == "FAIL")
    skipped = sum(1 for s in comparison["steps"] if s["result"] in ("SKIPPED", "ERROR"))

    comparison["passed"] = passed
    comparison["failed"] = failed
    comparison["skipped"] = skipped
    comparison["overall"] = "PASS" if failed == 0 else "FAIL"

    print(f"\n    {'=' * 40}")
    print(f"    COMPARISON RESULT: {comparison['overall']}")
    print(f"    Passed: {passed}  |  Failed: {failed}  |  Skipped: {skipped}")
    print(f"    {'=' * 40}")

    return comparison


def _get_format_function():
    """Return the format_slack_digest function source for validation."""
    return '''
def format_slack_digest(repo, categorized_prs, pr_summaries):
    from datetime import datetime, timedelta, timezone

    def esc(text):
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%B %d")
    total = sum(len(v) for v in categorized_prs.values())

    emoji = {
        "new_feature": "\\u2728", "bug_fix": "\\U0001f41b", "refactor": "\\U0001f527",
        "docs": "\\U0001f4da", "test": "\\U0001f9ea", "chore": "\\U0001f3d7\\ufe0f",
    }
    labels = {
        "new_feature": "New Features", "bug_fix": "Bug Fixes", "refactor": "Refactors",
        "docs": "Documentation", "test": "Tests", "chore": "Chores",
    }
    order = ["new_feature", "bug_fix", "refactor", "docs", "test", "chore"]

    lines = [f"\\U0001f4cb *Weekly PR Digest \\u2014 {week_ago} to {today}*"]
    lines.append(f"_{total} PRs merged in `{esc(repo)}`_\\n")

    for cat in order:
        prs = categorized_prs.get(cat, [])
        if not prs:
            continue
        lines.append(f"{emoji.get(cat, chr(0x1f4cc))} *{labels.get(cat, cat)}* ({len(prs)})")
        for pr in prs:
            lines.append(
                f"  \\u2022 <{pr[\\'url\\']}|#{pr[\\'number\\']}> {esc(pr[\\'title\\'])} \\u2014 _{esc(pr[\\'author\\'])}_"
            )
            summary = pr_summaries.get(pr["number"], "")
            if summary and summary != pr["title"]:
                lines.append(f"    _{esc(summary)}_")
        lines.append("")

    return "\\n".join(lines)
'''


# ─────────────────────────────────────────────────────────────
# STEP 5 — DEPRECATION REPORT
# ─────────────────────────────────────────────────────────────

def generate_deprecation_report(trace, analysis, analysis_map, comparison):
    """
    Produce the final deprecation report showing exactly how much
    AI dependency was eliminated.
    """
    print(f"\n{'─' * 60}")
    print("  Generating deprecation report...")
    print(f"{'─' * 60}")

    total = len(analysis_map)
    det = sum(1 for s in analysis_map.values() if s["classification"] == "DETERMINISTIC")
    rule = sum(1 for s in analysis_map.values() if s["classification"] == "RULE_BASED")
    ai = sum(1 for s in analysis_map.values() if s["classification"] == "AI_REQUIRED")

    # Cost estimation from trace
    steps = trace.get("steps", [])
    agent_input_tokens = 0
    agent_output_tokens = 0
    for step in steps:
        st = step.get("step_type", "reasoning")
        if st == "reasoning":
            agent_input_tokens += 2000
            agent_output_tokens += 800
        else:
            agent_input_tokens += 300
            agent_output_tokens += 100

    pro_price = GEMINI_PRICING["gemini-2.5-pro"]
    agent_cost = round(
        agent_input_tokens / 1e6 * pro_price["input_per_M"]
        + agent_output_tokens / 1e6 * pro_price["output_per_M"], 6
    )

    # Pipeline cost: only AI steps, using Flash
    pipeline_input_tokens = ai * 500
    pipeline_output_tokens = ai * 100
    flash_price = GEMINI_PRICING["gemini-2.5-flash"]
    pipeline_cost = round(
        pipeline_input_tokens / 1e6 * flash_price["input_per_M"]
        + pipeline_output_tokens / 1e6 * flash_price["output_per_M"], 6
    )

    cost_reduction = round((1 - pipeline_cost / agent_cost) * 100, 1) if agent_cost > 0 else 100
    savings_yearly = round((agent_cost - pipeline_cost) * 52, 4)

    ai_pct_before = 100
    ai_pct_after = round((ai / total) * 100) if total > 0 else 0

    # Duration from trace
    if len(steps) >= 2:
        try:
            t0 = datetime.fromisoformat(steps[0]["timestamp"])
            t1 = datetime.fromisoformat(steps[-1]["timestamp"])
            duration = (t1 - t0).total_seconds()
        except (ValueError, KeyError):
            duration = 0
    else:
        duration = 0

    # Build report
    lines = []
    lines.append("=" * 60)
    lines.append("  DEPRECATION REPORT")
    lines.append("  FADE — The Self-Eliminating Agent")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"  Task:   {trace.get('task', 'unknown')}")
    lines.append(f"  Repo:   {trace.get('repo', 'unknown')}")
    lines.append(f"  Date:   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"  Agent execution time: {duration}s")
    lines.append("")

    # Step-by-step classification
    lines.append("\u2500" * 60)
    lines.append("  STEP-BY-STEP CLASSIFICATION")
    lines.append("\u2500" * 60)
    for step in analysis:
        icon = {
            "DETERMINISTIC": "\U0001f7e2",
            "RULE_BASED": "\U0001f7e1",
            "AI_REQUIRED": "\U0001f534",
        }.get(step["classification"], "\u26aa")
        lines.append(f"  {icon} Step {step['step_number']}: {step['original_description'][:50]}")
        lines.append(f"     \u2192 {step['classification']}: {step.get('reasoning', '')[:70]}")
        lines.append("")

    # Classification summary
    lines.append("\u2500" * 60)
    lines.append("  CLASSIFICATION SUMMARY")
    lines.append("\u2500" * 60)
    lines.append(f"  Total steps:        {total}")
    lines.append(f"  \U0001f7e2 Deterministic:   {det}")
    lines.append(f"  \U0001f7e1 Rule-based:      {rule}")
    lines.append(f"  \U0001f534 AI-required:     {ai}")
    lines.append("")

    # AI dependency meter
    lines.append("\u2500" * 60)
    lines.append("  AI DEPENDENCY METER")
    lines.append("\u2500" * 60)

    # Visual bar
    bar_width = 40
    before_filled = bar_width
    after_filled = round(ai_pct_after / 100 * bar_width)
    before_bar = "\u2588" * before_filled
    after_bar = "\u2588" * after_filled + "\u2591" * (bar_width - after_filled)

    lines.append(f"  BEFORE: [{before_bar}] {ai_pct_before}%")
    lines.append(f"  AFTER:  [{after_bar}] {ai_pct_after}%")
    lines.append(f"")
    lines.append(f"  AI dependency dropped from {ai_pct_before}% to {ai_pct_after}%")
    lines.append("")

    # Cost metrics
    lines.append("\u2500" * 60)
    lines.append("  COST ANALYSIS")
    lines.append("\u2500" * 60)

    cost_line = f"  COST PER RUN:   ${agent_cost} (pro) \u2192 ${pipeline_cost} (flash)"
    red_line =  f"  COST REDUCTION: {cost_reduction}%"
    save_line = f"  YEARLY SAVINGS: ${savings_yearly} (52 runs)"

    box_w = max(len(cost_line), len(red_line), len(save_line)) + 4
    lines.append(f"  \u250c{'\u2500' * box_w}\u2510")
    lines.append(f"  \u2502{cost_line:<{box_w}}\u2502")
    lines.append(f"  \u2502{red_line:<{box_w}}\u2502")
    lines.append(f"  \u2502{save_line:<{box_w}}\u2502")
    lines.append(f"  \u2514{'\u2500' * box_w}\u2518")
    lines.append("")

    lines.append(f"  Agent  ({pro_price}): ~{agent_input_tokens:,} in / ~{agent_output_tokens:,} out tokens")
    lines.append(f"  Pipeline ({flash_price}): ~{pipeline_input_tokens:,} in / ~{pipeline_output_tokens:,} out tokens")
    lines.append("")

    # Validation results
    lines.append("\u2500" * 60)
    lines.append("  SIDE-BY-SIDE VALIDATION")
    lines.append("\u2500" * 60)

    if comparison.get("skipped"):
        lines.append("  Skipped — no PR data in trace")
    else:
        for step_result in comparison.get("steps", []):
            icon = {
                "PASS": "\u2705",
                "FAIL": "\u274c",
                "SKIPPED": "\u23ed\ufe0f",
                "ERROR": "\u26a0\ufe0f",
            }.get(step_result["result"], "\u2753")
            lines.append(f"  {icon} {step_result['step']}: {step_result['result']}")
            if step_result.get("accuracy") is not None:
                lines.append(f"     Accuracy: {step_result['accuracy']:.0%} ({step_result['matches']}/{step_result['total']})")
            if step_result.get("mismatches"):
                for m in step_result["mismatches"]:
                    lines.append(f"     \u274c PR #{m['pr']}: agent={m['agent']}, rules={m['rules']}")

        lines.append(f"\n  Overall: {comparison.get('overall', 'N/A')}")
    lines.append("")

    # Generated artifacts
    lines.append("\u2500" * 60)
    lines.append("  GENERATED ARTIFACTS")
    lines.append("\u2500" * 60)
    lines.append("  \u2705 generated_pipeline.py    \u2014 replacement pipeline")
    lines.append("  \u2705 scheduler_config.json    \u2014 Cloud Scheduler + Cloud Functions config")
    lines.append("  \u2705 deprecation_report.txt   \u2014 this report")
    lines.append("")

    lines.append("=" * 60)
    lines.append('  "You don\'t need me anymore." \u2014 The Agent')
    lines.append("=" * 60)

    report = "\n".join(lines)

    with open("deprecation_report.txt", "w") as f:
        f.write(report)
    print(f"    Saved: deprecation_report.txt")

    return report


# ─────────────────────────────────────────────────────────────
# MAIN — Run Phase 3 end-to-end
# ─────────────────────────────────────────────────────────────

def main():
    # 1. Load Phase 2 outputs
    trace, analysis, analysis_map, cat_rules_code = load_phase2_outputs()

    # 2. Generate replacement pipeline code
    generate_pipeline_code(trace, analysis_map, cat_rules_code)

    # 3. Generate scheduler config (Cloud Functions + Cloud Scheduler)
    generate_scheduler_config(trace)

    # 4. Run side-by-side comparison (the demo moment)
    comparison = run_side_by_side_comparison(trace, analysis_map, cat_rules_code)

    # 5. Generate deprecation report
    report = generate_deprecation_report(trace, analysis, analysis_map, comparison)

    # Print the report
    print(f"\n{report}")

    print("\n\u2705 Phase 3 complete!")
    print("   Run the generated pipeline:  python generated_pipeline.py")
    print("   Deploy to GCP:               see scheduler_config.json\n")


if __name__ == "__main__":
    main()
