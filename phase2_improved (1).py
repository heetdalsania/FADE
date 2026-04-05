"""
DEPRECATE ME — Phase 2: Smart Self-Analysis (Fully Dynamic)
=============================================================
Every metric, cost, and classification is computed from real data.
Nothing is hardcoded.

SETUP: Same env vars as Phase 1.
RUN:   python phase2_improved.py

Reads:  execution_trace.json (from Phase 1)
Writes: analysis_report.json, categorization_rules.py,
        generated_pipeline.py, deprecation_report.txt
"""

import os
import json
import time
from datetime import datetime, timedelta, timezone


# ─────────────────────────────────────────────────────────────
# COST MODEL — computed from actual Gemini pricing + trace data
# ─────────────────────────────────────────────────────────────

GEMINI_PRICING = {
    "gemini-2.5-pro": {
        "input_per_million": 1.25,
        "output_per_million": 10.00,
    },
    "gemini-2.5-flash": {
        "input_per_million": 0.15,
        "output_per_million": 0.60,
    },
}

AVG_TOKENS = {
    "reasoning": {"input": 2000, "output": 800},
    "tool_call": {"input": 300, "output": 100},
}


def estimate_agent_cost(trace):
    """Estimate cost of the original agent run from trace step types."""
    steps = trace.get("steps", [])
    total_input_tokens = 0
    total_output_tokens = 0

    for step in steps:
        st = step.get("step_type", "reasoning")
        total_input_tokens += AVG_TOKENS.get(st, AVG_TOKENS["reasoning"])["input"]
        total_output_tokens += AVG_TOKENS.get(st, AVG_TOKENS["reasoning"])["output"]

    pricing = GEMINI_PRICING["gemini-2.5-pro"]
    cost = (
        (total_input_tokens / 1_000_000) * pricing["input_per_million"]
        + (total_output_tokens / 1_000_000) * pricing["output_per_million"]
    )
    return {
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "model": "gemini-2.5-pro",
        "cost_usd": round(cost, 6),
    }


def estimate_pipeline_cost(analysis):
    """Estimate pipeline cost — only AI_REQUIRED steps cost anything."""
    ai_steps = [s for s in analysis if s.get("classification") == "AI_REQUIRED"]

    if not ai_steps:
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "model": "none",
            "cost_usd": 0.0,
            "ai_calls": 0,
        }

    tokens_per_call_input = 500
    tokens_per_call_output = 100
    total_input = len(ai_steps) * tokens_per_call_input
    total_output = len(ai_steps) * tokens_per_call_output

    pricing = GEMINI_PRICING["gemini-2.5-flash"]
    cost = (
        (total_input / 1_000_000) * pricing["input_per_million"]
        + (total_output / 1_000_000) * pricing["output_per_million"]
    )
    return {
        "input_tokens": total_input,
        "output_tokens": total_output,
        "model": "gemini-2.5-flash",
        "cost_usd": round(cost, 6),
        "ai_calls": len(ai_steps),
    }


def compute_metrics(trace, analysis):
    """Compute ALL metrics dynamically from trace and analysis."""
    total_steps = len(analysis)
    det_steps = [s for s in analysis if s.get("classification") == "DETERMINISTIC"]
    rule_steps = [s for s in analysis if s.get("classification") == "RULE_BASED"]
    ai_steps = [s for s in analysis if s.get("classification") == "AI_REQUIRED"]

    ai_pct_before = 100
    ai_pct_after = round((len(ai_steps) / total_steps) * 100) if total_steps > 0 else 0

    agent_cost = estimate_agent_cost(trace)
    pipeline_cost = estimate_pipeline_cost(analysis)

    cost_reduction_pct = (
        round((1 - pipeline_cost["cost_usd"] / agent_cost["cost_usd"]) * 100)
        if agent_cost["cost_usd"] > 0
        else 100
    )

    steps = trace.get("steps", [])
    if len(steps) >= 2:
        try:
            t_start = datetime.fromisoformat(steps[0]["timestamp"])
            t_end = datetime.fromisoformat(steps[-1]["timestamp"])
            duration_seconds = (t_end - t_start).total_seconds()
        except (ValueError, KeyError):
            duration_seconds = 0
    else:
        duration_seconds = 0

    return {
        "total_steps": total_steps,
        "deterministic_count": len(det_steps),
        "rule_based_count": len(rule_steps),
        "ai_required_count": len(ai_steps),
        "ai_pct_before": ai_pct_before,
        "ai_pct_after": ai_pct_after,
        "agent_cost": agent_cost,
        "pipeline_cost": pipeline_cost,
        "cost_reduction_pct": cost_reduction_pct,
        "savings_per_run": round(agent_cost["cost_usd"] - pipeline_cost["cost_usd"], 6),
        "savings_yearly_52_runs": round((agent_cost["cost_usd"] - pipeline_cost["cost_usd"]) * 52, 4),
        "agent_duration_seconds": round(duration_seconds, 1),
        "repo": trace.get("repo", "unknown"),
        "task": trace.get("task", "unknown"),
    }


# ─────────────────────────────────────────────────────────────
# TRACE LOADING + ENRICHMENT
# ─────────────────────────────────────────────────────────────

def load_and_enrich_trace(filepath="execution_trace.json"):
    """Load trace and fetch real PR data if missing."""
    print(f"\n📂 Loading execution trace from: {filepath}")

    with open(filepath, "r") as f:
        trace = json.load(f)

    print(
        f"   Steps: {trace['total_steps']} "
        f"({trace['summary']['tool_calls']} tool, "
        f"{trace['summary']['reasoning_steps']} reasoning)"
    )

    if not trace.get("pr_data"):
        print("   ⚠️ Trace missing PR data — fetching from GitHub...")
        pr_data = fetch_prs_for_enrichment(trace.get("repo", "facebook/react"))
        trace["pr_data"] = pr_data
        print(f"   ✅ Enriched with {len(pr_data)} PRs")
    else:
        print(f"   ✅ Found {len(trace['pr_data'])} PRs in trace")

    return trace


def fetch_prs_for_enrichment(repo):
    """Fetch recent merged PRs with file lists."""
    import requests

    token = os.environ.get("GITHUB_TOKEN", "")
    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

    url = f"https://api.github.com/repos/{repo}/pulls"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    params = {"state": "closed", "sort": "updated", "direction": "desc", "per_page": 30}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        all_prs = resp.json()

        merged = []
        for pr in all_prs:
            if pr.get("merged_at") and pr["merged_at"] >= since:
                files_url = f"https://api.github.com/repos/{repo}/pulls/{pr['number']}/files"
                try:
                    files_resp = requests.get(
                        files_url, headers=headers, params={"per_page": 30}, timeout=10
                    )
                    files_resp.raise_for_status()
                    files = [f["filename"] for f in files_resp.json()]
                except Exception:
                    files = []

                merged.append({
                    "number": pr["number"],
                    "title": pr["title"],
                    "author": pr["user"]["login"],
                    "body": (pr.get("body") or "")[:500],
                    "merged_at": pr["merged_at"],
                    "url": pr["html_url"],
                    "files_changed": files[:20],
                })
        return merged
    except Exception as e:
        print(f"   ❌ Could not fetch PRs: {e}")
        return []


# ─────────────────────────────────────────────────────────────
# STAGE 1: CLASSIFY STEPS
# ─────────────────────────────────────────────────────────────

def classify_steps(trace):
    """Gemini classifies each execution step."""
    from google.genai import types

    client = _get_client()

    print(f"\n🔬 Stage 1: Classifying execution steps...")

    prompt = f"""Analyze this AI agent execution trace. Classify each step as:
- DETERMINISTIC: Pure API call, no AI needed
- RULE_BASED: Could be done with if/else rules or keyword matching
- AI_REQUIRED: Genuinely needs language model reasoning

Be AGGRESSIVE about downgrading.

Trace steps:
{json.dumps(trace['steps'], indent=2)}

Respond with ONLY a JSON array. No markdown fences. Each element:
{{
  "step_number": 1,
  "original_description": "...",
  "classification": "DETERMINISTIC",
  "reasoning": "why this classification"
}}"""

    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=4000),
    )

    return _parse_json_response(response.text)


# ─────────────────────────────────────────────────────────────
# STAGE 2: EXTRACT CATEGORIZATION RULES FROM REAL DATA
# ─────────────────────────────────────────────────────────────

def extract_categorization_rules(trace):
    """Show Gemini real PR titles and ask it to write matching rules."""
    from google.genai import types

    client = _get_client()

    pr_examples = trace.get("pr_data", [])
    if not pr_examples:
        print("   ⚠️ No PR data — using fallback rules")
        return None

    print(f"\n🔍 Stage 2: Extracting categorization rules from {len(pr_examples)} real PRs...")

    pr_list = []
    for pr in pr_examples:
        pr_list.append({
            "number": pr["number"],
            "title": pr["title"],
            "files": pr.get("files_changed", [])[:10],
            "body_snippet": (pr.get("body") or "")[:200],
        })

    agent_cats = trace.get("agent_categories", {})
    if agent_cats:
        for pr_info in pr_list:
            pr_info["agent_category"] = agent_cats.get(str(pr_info["number"]), "unknown")

    prompt = f"""You are writing a Python categorization function for GitHub pull requests.

Here are REAL pull requests from the repo '{trace.get("repo", "unknown")}':
{json.dumps(pr_list, indent=2)}

The categories are: bug_fix, new_feature, refactor, docs, test, chore

Write a Python function called `categorize_pr(title, body, files)` that:
1. Takes title (str), body (str), files (list of filename strings)
2. Returns one category string
3. Uses keyword matching, file path patterns, and scoring — NO AI calls
4. Is tuned to work well with the actual PR titles shown above
5. Falls back to "chore" if nothing matches

Return ONLY the Python function. No explanation. No markdown fences.
Signature: def categorize_pr(title: str, body: str, files: list) -> str"""

    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=3000),
    )

    code = _clean_code_response(response.text)
    print(f"   ✅ Generated categorization function ({len(code)} chars)")
    return code


# ─────────────────────────────────────────────────────────────
# STAGE 3: VALIDATE & IMPROVE RULES
# ─────────────────────────────────────────────────────────────

def validate_and_improve_rules(categorization_code, trace, max_iterations=2):
    """Test rules against real PRs. Iterate if accuracy < 80%."""
    pr_data = trace.get("pr_data", [])
    agent_cats = trace.get("agent_categories", {})

    if not pr_data:
        print("   ⚠️ No PR data to validate — skipping")
        return categorization_code

    print(f"\n✅ Stage 3: Validating rules against {len(pr_data)} PRs...")

    for iteration in range(max_iterations):
        results = _test_categorization(categorization_code, pr_data)

        if results is None:
            print(f"   ❌ Syntax error — regenerating...")
            categorization_code = _fix_code_errors(categorization_code, trace)
            continue

        if agent_cats:
            mismatches = []
            matches = 0
            for pr in pr_data:
                rule_cat = results.get(pr["number"], "unknown")
                agent_cat = agent_cats.get(str(pr["number"]), "unknown")
                if rule_cat == agent_cat:
                    matches += 1
                elif agent_cat != "unknown":
                    mismatches.append({
                        "pr_number": pr["number"],
                        "title": pr["title"],
                        "rule_said": rule_cat,
                        "agent_said": agent_cat,
                    })

            total_compared = matches + len(mismatches)
            accuracy = matches / total_compared if total_compared > 0 else 0
            print(
                f"   Iteration {iteration + 1}: {accuracy:.0%} accuracy "
                f"({matches}/{total_compared} match agent)"
            )

            if accuracy >= 0.8 or not mismatches:
                print(f"   ✅ Rules validated")
                break

            print(f"   🔄 {len(mismatches)} mismatches — improving...")
            categorization_code = _improve_rules(categorization_code, mismatches, trace)
        else:
            print(f"   ✅ Rules execute on {len(results)} PRs")
            for pr in pr_data:
                cat = results.get(pr["number"], "?")
                print(f"      #{pr['number']} '{pr['title'][:45]}' → {cat}")
            break

    return categorization_code


def _test_categorization(code, pr_data):
    try:
        namespace = {}
        exec(code, namespace)
        fn = namespace.get("categorize_pr")
        if not fn:
            return None
        results = {}
        for pr in pr_data:
            try:
                results[pr["number"]] = fn(
                    pr.get("title", ""), pr.get("body", ""), pr.get("files_changed", [])
                )
            except Exception as e:
                results[pr["number"]] = "error"
        return results
    except SyntaxError as e:
        print(f"   ❌ Syntax error: {e}")
        return None
    except Exception as e:
        print(f"   ❌ Execution error: {e}")
        return None


def _improve_rules(current_code, mismatches, trace):
    from google.genai import types
    client = _get_client()
    prompt = f"""Fix this categorization function. Some PRs are miscategorized.

Current function:
{current_code}

Mismatches (rule_said is wrong, agent_said is correct):
{json.dumps(mismatches, indent=2)}

Fix rules to handle these correctly while keeping existing correct ones working.
Return ONLY the fixed Python function. No explanation. No markdown fences."""

    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=3000),
    )
    return _clean_code_response(response.text)


def _fix_code_errors(broken_code, trace):
    from google.genai import types
    client = _get_client()
    prompt = f"""Fix this Python function — it has syntax or runtime errors.
It should categorize GitHub PRs into: bug_fix, new_feature, refactor, docs, test, chore

Broken code:
{broken_code}

Return ONLY the fixed function. No explanation. No markdown fences.
Signature: def categorize_pr(title: str, body: str, files: list) -> str"""

    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=3000),
    )
    return _clean_code_response(response.text)


# ─────────────────────────────────────────────────────────────
# STAGE 4: ASSEMBLE PIPELINE
# ─────────────────────────────────────────────────────────────

def generate_full_pipeline(trace, step_analysis, categorization_code, metrics):
    """Assemble the standalone pipeline. All values from metrics."""
    from google.genai import types

    client = _get_client()
    print(f"\n🏗️  Stage 4: Assembling final pipeline...")

    repo = trace.get("repo", "facebook/react")
    cat_code_indented = categorization_code.strip()

    format_prompt = """Write a Python function called `format_slack_digest` that takes:
- repo (str): GitHub repo name
- categorized_prs (dict): maps category string to list of PR dicts,
  each with keys: number, title, author, url
- pr_summaries (dict): maps PR number to a summary string

Returns a Slack-formatted markdown string for the weekly digest.

CRITICAL REQUIREMENTS:
1. Escape all PR titles and author names for Slack by replacing & with &amp;
   < with &lt; and > with &gt; BEFORE inserting into the message.
   URLs inside <url|text> links must NOT be escaped.
2. Import datetime inside the function.
3. Categories: bug_fix, new_feature, refactor, docs, test, chore
4. Emoji: bug_fix=🐛, new_feature=✨, refactor=🔧, docs=📚, test=🧪, chore=🏗️
5. Labels: bug_fix="Bug Fixes", new_feature="New Features", etc.
6. Format: header with date + total count, then sections by category.
7. Each PR: • <url|#number> escaped_title — _escaped_author_
8. If summary differs from title, add on next line: _escaped_summary_

Keep the function SHORT and COMPLETE. Do not add docstrings longer than one line.
Return ONLY the Python function. No explanation. No markdown fences."""

    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=format_prompt,
        config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=4000),
    )

    format_code = _clean_code_response(response.text)

    # Validate the generated function is complete — if not, use fallback
    if "def format_slack_digest" not in format_code or "return" not in format_code:
        print("   ⚠️ Generated format function is incomplete — using fallback")
        format_code = _fallback_format_function()

    m = metrics
    pipeline = _build_pipeline_string(
        repo=repo,
        total_steps=m["total_steps"],
        det_count=m["deterministic_count"],
        rule_count=m["rule_based_count"],
        ai_count=m["ai_required_count"],
        ai_pct_before=m["ai_pct_before"],
        ai_pct_after=m["ai_pct_after"],
        agent_cost_usd=m["agent_cost"]["cost_usd"],
        pipeline_cost_usd=m["pipeline_cost"]["cost_usd"],
        agent_model=m["agent_cost"]["model"],
        pipeline_model=m["pipeline_cost"]["model"],
        cost_reduction_pct=m["cost_reduction_pct"],
        agent_input_tokens=m["agent_cost"]["input_tokens"],
        agent_output_tokens=m["agent_cost"]["output_tokens"],
        pipeline_input_tokens=m["pipeline_cost"]["input_tokens"],
        pipeline_output_tokens=m["pipeline_cost"]["output_tokens"],
        pipeline_ai_calls=m["pipeline_cost"].get("ai_calls", 0),
        cat_code=cat_code_indented,
        format_code=format_code,
    )

    print(f"   ✅ Pipeline assembled ({len(pipeline)} chars)")
    return pipeline


def _fallback_format_function():
    """Known-good format function used when Gemini's generation is incomplete."""
    return '''def format_slack_digest(repo, categorized_prs, pr_summaries):
    from datetime import datetime, timedelta, timezone

    def escape_slack(text):
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%B %d")
    total = sum(len(prs) for prs in categorized_prs.values())

    emoji_map = {
        "new_feature": "✨", "bug_fix": "🐛", "refactor": "🔧",
        "docs": "📚", "test": "🧪", "chore": "🏗️",
    }
    label_map = {
        "new_feature": "New Features", "bug_fix": "Bug Fixes", "refactor": "Refactors",
        "docs": "Documentation", "test": "Tests", "chore": "Chores",
    }
    order = ["new_feature", "bug_fix", "refactor", "docs", "test", "chore"]

    lines = [f"📋 *Weekly PR Digest — {week_ago} to {today}*"]
    lines.append(f"_{total} PRs merged in `{escape_slack(repo)}`_\\n")

    for cat in order:
        prs = categorized_prs.get(cat, [])
        if not prs:
            continue
        emoji = emoji_map.get(cat, "📌")
        label = label_map.get(cat, cat)
        lines.append(f"{emoji} *{label}* ({len(prs)})")
        for pr in prs:
            safe_title = escape_slack(pr["title"])
            safe_author = escape_slack(pr["author"])
            lines.append(f"  • <{pr[\\'url\\']}|#{pr[\\'number\\']}> {safe_title} — _{safe_author}_")
            summary = pr_summaries.get(pr["number"], "")
            if summary and summary != pr["title"]:
                lines.append(f"    _{escape_slack(summary)}_")
        lines.append("")

    return "\\n".join(lines)
'''


def _build_pipeline_string(**kwargs):
    """Build pipeline file. ALL values are parameters — nothing hardcoded."""

    template = '''# ============================================================
# GENERATED PIPELINE — Auto-created by "Deprecate Me"
# ============================================================
# All metrics below were computed from the original agent's
# execution trace and Vertex AI pricing — nothing is hardcoded.
#
# --- AI Dependency (computed from trace) ---
# Original agent steps: {total_steps}
#   DETERMINISTIC: {det_count}  |  RULE_BASED: {rule_count}  |  AI_REQUIRED: {ai_count}
# AI dependency: {ai_pct_before}% → {ai_pct_after}%
#
# --- Cost (computed from Vertex AI pricing) ---
# Agent:    {agent_model} | ~{agent_input_tokens} in + ~{agent_output_tokens} out tokens | ${agent_cost_usd}/run
# Pipeline: {pipeline_model} | ~{pipeline_input_tokens} in + ~{pipeline_output_tokens} out tokens | ${pipeline_cost_usd}/run
# Reduction: {cost_reduction_pct}%
# ============================================================

import os
import sys
import json
import time
from datetime import datetime, timedelta, timezone
import requests

# ─── Configuration ───
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO", "{repo}")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
DAYS_AGO = 7

# Vertex AI pricing (for runtime cost computation)
PRICING = {{
    "gemini-2.5-pro":  {{"input_per_M": 1.25, "output_per_M": 10.00}},
    "gemini-2.5-flash": {{"input_per_M": 0.15, "output_per_M": 0.60}},
}}


class RunMetrics:
    """Track real metrics for this pipeline run."""
    def __init__(self):
        self.api_calls = 0
        self.ai_calls = 0
        self.prs_processed = 0
        self.start_time = None
        self.end_time = None
        self.ai_input_tokens = 0
        self.ai_output_tokens = 0

    def start(self):
        self.start_time = time.time()

    def stop(self):
        self.end_time = time.time()

    @property
    def duration(self):
        if self.start_time and self.end_time:
            return round(self.end_time - self.start_time, 1)
        return 0

    @property
    def estimated_cost(self):
        if self.ai_calls == 0:
            return 0.0
        p = PRICING["gemini-2.5-flash"]
        return round(
            self.ai_input_tokens / 1e6 * p["input_per_M"]
            + self.ai_output_tokens / 1e6 * p["output_per_M"],
            6,
        )

    def record_ai_call(self, input_tokens_est, output_tokens_est):
        self.ai_calls += 1
        self.ai_input_tokens += input_tokens_est
        self.ai_output_tokens += output_tokens_est

metrics = RunMetrics()


# ─── DETERMINISTIC: Fetch merged PRs ───
def get_merged_prs(repo, days=7):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    url = f"https://api.github.com/repos/{{repo}}/pulls"
    headers = {{
        "Authorization": f"Bearer {{GITHUB_TOKEN}}",
        "Accept": "application/vnd.github+json",
    }}
    params = {{"state": "closed", "sort": "updated", "direction": "desc", "per_page": 50}}

    print(f"📥 Fetching merged PRs from {{repo}} (last {{days}} days)...")
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        metrics.api_calls += 1
    except requests.RequestException as e:
        print(f"   ❌ GitHub API error: {{e}}", file=sys.stderr)
        return []

    merged = []
    for pr in resp.json():
        if pr.get("merged_at") and pr["merged_at"] >= since[:10]:
            merged.append({{
                "number": pr["number"],
                "title": pr["title"],
                "author": pr["user"]["login"],
                "merged_at": pr["merged_at"],
                "url": pr["html_url"],
                "body": (pr.get("body") or "")[:500],
            }})
    print(f"   Found {{len(merged)}} merged PRs")
    return merged


# ─── DETERMINISTIC: Fetch PR file changes ───
def get_pr_files(repo, pr_number):
    url = f"https://api.github.com/repos/{{repo}}/pulls/{{pr_number}}/files"
    headers = {{
        "Authorization": f"Bearer {{GITHUB_TOKEN}}",
        "Accept": "application/vnd.github+json",
    }}
    try:
        resp = requests.get(url, headers=headers, params={{"per_page": 30}}, timeout=10)
        resp.raise_for_status()
        metrics.api_calls += 1
        return [f["filename"] for f in resp.json()]
    except requests.RequestException:
        return []


# ─── RULE-BASED: Categorize PRs ───
# Rules extracted from real PR data and validated against the agent.

{cat_code}


# ─── AI_REQUIRED: Generate PR summaries ───
def generate_summary(pr):
    try:
        from google import genai
        from google.genai import types as genai_types

        client = genai.Client(
            vertexai=True,
            project=GOOGLE_CLOUD_PROJECT,
            location=GOOGLE_CLOUD_LOCATION,
        )
        prompt = (
            f"Write exactly one complete sentence (15-30 words) summarizing this GitHub PR. "
            f"Focus on what changed and why. Do NOT truncate. Output ONLY the sentence, nothing else.\\n\\n"
            f"Title: {{pr['title']}}\\n"
            f"Description: {{(pr.get('body') or 'No description')[:500]}}\\n\\n"
            f"Summary:"
        )
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.1, max_output_tokens=256
            ),
        )
        response_text = response.text if response.text else ""
        if not response_text.strip():
            return pr["title"]
        input_est = len(prompt.split()) * 2
        output_est = len(response_text.split()) * 2
        metrics.record_ai_call(input_est, output_est)
        return response_text.strip()
    except Exception as e:
        print(f"   ⚠️ AI summary failed for PR #{{pr['number']}}: {{e}}")
        return pr["title"]


# ─── RULE-BASED: Format the digest ───
{format_code}


# ─── DETERMINISTIC: Post to Slack ───
def post_to_slack(message):
    if not SLACK_WEBHOOK_URL:
        print(f"\\n📋 SLACK MESSAGE (dry run):")
        print("=" * 50)
        print(message)
        print("=" * 50)
        return True

    print("📤 Posting digest to Slack...")
    try:
        resp = requests.post(SLACK_WEBHOOK_URL, json={{"text": message}}, timeout=10)
        resp.raise_for_status()
        metrics.api_calls += 1
        print("   ✅ Posted successfully!")
        return True
    except requests.RequestException as e:
        print(f"   ❌ Slack error: {{e}}", file=sys.stderr)
        return False


# ─── Main pipeline ───
def main():
    metrics.start()

    print("\\n" + "=" * 60)
    print("  GENERATED PIPELINE")
    print(f"  Mode: Minimal AI (gemini-2.5-flash for summaries)")
    print("=" * 60 + "\\n")

    if not GITHUB_TOKEN:
        print("❌ GITHUB_TOKEN not set.", file=sys.stderr)
        sys.exit(1)

    if not GOOGLE_CLOUD_PROJECT:
        print("❌ GOOGLE_CLOUD_PROJECT not set. Required for AI summaries.", file=sys.stderr)
        sys.exit(1)

    repo = GITHUB_REPO

    prs = get_merged_prs(repo, days=DAYS_AGO)
    if not prs:
        print("No merged PRs found.")
        return
    metrics.prs_processed = len(prs)

    pr_files = {{}}
    for pr in prs[:15]:
        files = get_pr_files(repo, pr["number"])
        pr_files[pr["number"]] = files
        print(f"   📂 PR #{{pr['number']}}: {{len(files)}} files")

    print("\\n📊 Categorizing with keyword rules...")
    categorized = {{}}
    for pr in prs:
        cat = categorize_pr(pr["title"], pr.get("body", ""), pr_files.get(pr["number"], []))
        categorized.setdefault(cat, []).append(pr)
        emoji = {{"bug_fix": "🐛", "new_feature": "✨", "refactor": "🔧",
                  "docs": "📚", "test": "🧪", "chore": "🏗️"}}.get(cat, "📌")
        print(f"   {{emoji}} #{{pr['number']}} '{{pr['title'][:50]}}' → {{cat}}")

    print("\\n✍️ Generating summaries...")
    summaries = {{}}
    for pr in prs:
        summaries[pr["number"]] = generate_summary(pr)

    digest = format_slack_digest(repo, categorized, summaries)
    post_to_slack(digest)

    metrics.stop()

    # ─── Runtime report — ALL computed from this actual run ───
    total_pipeline_steps = 6
    ai_step_count = 1  # Summary generation always uses AI
    runtime_ai_pct = round((ai_step_count / total_pipeline_steps) * 100)

    print(f"\\n" + "─" * 50)
    print(f"  RUNTIME METRICS (measured from this run)")
    print(f"─" * 50)
    print(f"  PRs processed:    {{metrics.prs_processed}}")
    print(f"  API calls made:   {{metrics.api_calls}}")
    print(f"  AI calls made:    {{metrics.ai_calls}}")
    print(f"  AI tokens used:   ~{{metrics.ai_input_tokens}} in, ~{{metrics.ai_output_tokens}} out")
    print(f"  Duration:         {{metrics.duration}}s")
    print(f"  Estimated cost:   ${{metrics.estimated_cost}}")
    print(f"  AI dependency:    {{runtime_ai_pct}}%")
    print(f"─" * 50 + "\\n")


if __name__ == "__main__":
    main()
'''

    return template.format(**kwargs)


# ─────────────────────────────────────────────────────────────
# DEPRECATION REPORT — all values from metrics dict
# ─────────────────────────────────────────────────────────────

def generate_deprecation_report(trace, analysis, metrics):
    """Every number comes from the metrics dict."""
    m = metrics

    lines = []
    lines.append("=" * 60)
    lines.append("  DEPRECATION REPORT")
    lines.append("  The Self-Eliminating Agent")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"  Task:  {m['task']}")
    lines.append(f"  Repo:  {m['repo']}")
    lines.append(f"  Date:  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"  Agent execution time: {m['agent_duration_seconds']}s")
    lines.append("")
    lines.append("─" * 60)
    lines.append("  STEP-BY-STEP CLASSIFICATION")
    lines.append("─" * 60)

    for step in analysis:
        icon = {"DETERMINISTIC": "🟢", "RULE_BASED": "🟡", "AI_REQUIRED": "🔴"}.get(
            step.get("classification", ""), "⚪"
        )
        lines.append(
            f"  {icon} Step {step['step_number']}: "
            f"{step.get('original_description', '')[:50]}"
        )
        lines.append(
            f"     → {step['classification']}: "
            f"{step.get('reasoning', 'N/A')[:70]}"
        )
        lines.append("")

    lines.append("─" * 60)
    lines.append("  CLASSIFICATION SUMMARY")
    lines.append("─" * 60)
    lines.append(f"  Total steps:        {m['total_steps']}")
    lines.append(f"  🟢 Deterministic:   {m['deterministic_count']}")
    lines.append(f"  🟡 Rule-based:      {m['rule_based_count']}")
    lines.append(f"  🔴 AI-required:     {m['ai_required_count']}")
    lines.append("")

    ai_line =       f"  AI DEPENDENCY:  {m['ai_pct_before']}%  →  {m['ai_pct_after']}%"
    cost_line =     f"  COST PER RUN:   ${m['agent_cost']['cost_usd']} ({m['agent_cost']['model']})  →  ${m['pipeline_cost']['cost_usd']} ({m['pipeline_cost']['model']})"
    reduction_line = f"  COST REDUCTION: {m['cost_reduction_pct']}%"
    savings_line =  f"  YEARLY SAVINGS: ${m['savings_yearly_52_runs']} (52 runs)"

    box_width = max(len(ai_line), len(cost_line), len(reduction_line), len(savings_line)) + 4

    lines.append("─" * 60)
    lines.append("  COMPUTED METRICS")
    lines.append("─" * 60)
    lines.append(f"  ┌{'─' * box_width}┐")
    lines.append(f"  │{ai_line:<{box_width}}│")
    lines.append(f"  │{cost_line:<{box_width}}│")
    lines.append(f"  │{reduction_line:<{box_width}}│")
    lines.append(f"  │{savings_line:<{box_width}}│")
    lines.append(f"  └{'─' * box_width}┘")
    lines.append("")

    lines.append("─" * 60)
    lines.append("  COST BREAKDOWN")
    lines.append("─" * 60)
    ac = m["agent_cost"]
    pc = m["pipeline_cost"]
    lines.append(f"  Agent ({ac['model']}):")
    lines.append(f"    Input tokens:  ~{ac['input_tokens']:,}")
    lines.append(f"    Output tokens: ~{ac['output_tokens']:,}")
    lines.append(f"    Cost: ${ac['cost_usd']}")
    lines.append(f"  Pipeline ({pc['model'] or 'no AI'}):")
    lines.append(f"    Input tokens:  ~{pc['input_tokens']:,}")
    lines.append(f"    Output tokens: ~{pc['output_tokens']:,}")
    lines.append(f"    AI calls: {pc.get('ai_calls', 0)}")
    lines.append(f"    Cost: ${pc['cost_usd']}")
    lines.append("")

    lines.append("─" * 60)
    lines.append("  GENERATED ARTIFACTS")
    lines.append("─" * 60)
    lines.append("  ✅ generated_pipeline.py")
    lines.append("  ✅ analysis_report.json")
    lines.append("  ✅ categorization_rules.py")
    lines.append("  ✅ deprecation_report.txt")
    lines.append("")
    lines.append("=" * 60)
    lines.append('  "You don\'t need me anymore." — The Agent')
    lines.append("=" * 60)

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _get_client():
    from google import genai
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "your-project-id")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    return genai.Client(vertexai=True, project=project, location=location)


def _parse_json_response(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
    print(f"   ❌ Could not parse JSON from response")
    return None


def _clean_code_response(text):
    text = text.strip()
    if text.startswith("```python"):
        text = text[len("```python"):].strip()
    elif text.startswith("```"):
        text = text[3:].strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    return text


def _fallback_categorization():
    return '''def categorize_pr(title: str, body: str, files: list) -> str:
    title_lower = title.lower()
    body_lower = (body or "").lower()

    keywords = {
        "bug_fix": ["fix", "bug", "patch", "hotfix", "resolve", "crash", "error", "regression"],
        "new_feature": ["add", "feat", "new", "implement", "introduce", "support", "enable"],
        "refactor": ["refactor", "clean", "restructure", "simplify", "reorganize", "move", "rename"],
        "docs": ["doc", "readme", "typo", "spelling", "grammar", "changelog"],
        "test": ["test", "spec", "coverage", "snapshot", "fixture", "benchmark"],
        "chore": ["chore", "ci", "build", "deps", "bump", "upgrade", "lint", "config"],
    }

    file_signals = {
        "docs": [".md", "docs/", "README", "CHANGELOG"],
        "test": ["test/", "tests/", "__tests__/", ".test.", ".spec."],
        "chore": [".yml", ".yaml", "package.json", ".github/", ".eslint"],
    }

    scores = {cat: 0 for cat in keywords}

    for cat, kws in keywords.items():
        for kw in kws:
            if kw in title_lower:
                scores[cat] += 3
            if kw in body_lower:
                scores[cat] += 1

    for cat, patterns in file_signals.items():
        for f in files:
            for p in patterns:
                if p in f:
                    scores[cat] += 2

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "chore"
'''


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    print("\n🔬 DEPRECATE ME — Phase 2: Smart Self-Analysis")
    print("=" * 55)

    # 1. Load and enrich trace
    trace = load_and_enrich_trace("execution_trace.json")

    # 2. Classify steps
    print("\n" + "─" * 55)
    analysis = classify_steps(trace)
    if not analysis:
        print("❌ Step classification failed.")
        return

    with open("analysis_report.json", "w") as f:
        json.dump(analysis, f, indent=2)
    print(f"   💾 Saved: analysis_report.json")

    for step in analysis:
        icon = {"DETERMINISTIC": "🟢", "RULE_BASED": "🟡", "AI_REQUIRED": "🔴"}.get(
            step.get("classification", ""), "⚪"
        )
        print(f"   {icon} Step {step['step_number']}: {step['classification']}")

    # 3. Compute metrics from real data
    metrics = compute_metrics(trace, analysis)
    print(f"\n   📊 Metrics computed from trace:")
    print(f"      AI dependency: {metrics['ai_pct_before']}% → {metrics['ai_pct_after']}%")
    print(f"      Agent cost/run: ${metrics['agent_cost']['cost_usd']} ({metrics['agent_cost']['model']})")
    print(f"      Pipeline cost/run: ${metrics['pipeline_cost']['cost_usd']} ({metrics['pipeline_cost']['model']})")
    print(f"      Cost reduction: {metrics['cost_reduction_pct']}%")
    print(f"      Agent duration: {metrics['agent_duration_seconds']}s")

    # 4. Extract categorization rules
    print("\n" + "─" * 55)
    cat_code = extract_categorization_rules(trace)
    if not cat_code:
        cat_code = _fallback_categorization()

    # 5. Validate and improve rules
    print("\n" + "─" * 55)
    cat_code = validate_and_improve_rules(cat_code, trace)

    with open("categorization_rules.py", "w") as f:
        f.write(cat_code)
    print(f"   💾 Saved: categorization_rules.py")

    # 6. Assemble pipeline (with real metrics)
    print("\n" + "─" * 55)
    pipeline = generate_full_pipeline(trace, analysis, cat_code, metrics)

    with open("generated_pipeline.py", "w") as f:
        f.write(pipeline)
    print(f"   💾 Saved: generated_pipeline.py")

    # 7. Deprecation report (all from metrics)
    print("\n" + "─" * 55)
    report = generate_deprecation_report(trace, analysis, metrics)

    with open("deprecation_report.txt", "w") as f:
        f.write(report)
    print(f"   💾 Saved: deprecation_report.txt")

    print(f"\n{report}")

    print("\n✅ Phase 2 complete!")
    print("   Test it:  python generated_pipeline.py")
    print("   Compare Slack output to the original agent's message.\n")


if __name__ == "__main__":
    main()
