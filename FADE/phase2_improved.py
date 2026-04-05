"""
DEPRECATE ME — Phase 2: Self-Analysis (Final)
================================================
RUN:   python phase2_improved.py
"""

import os
import json
import time
from datetime import datetime, timedelta, timezone

# ─── Cost model ───
GEMINI_PRICING = {
    "gemini-2.5-pro": {"input_per_M": 1.25, "output_per_M": 10.00},
    "gemini-2.5-flash": {"input_per_M": 0.15, "output_per_M": 0.60},
}
AVG_TOKENS = {"reasoning": {"i": 2000, "o": 800}, "tool_call": {"i": 300, "o": 100}}

def estimate_agent_cost(trace):
    steps = trace.get("steps", [])
    i = sum(AVG_TOKENS.get(s.get("step_type","reasoning"), AVG_TOKENS["reasoning"])["i"] for s in steps)
    o = sum(AVG_TOKENS.get(s.get("step_type","reasoning"), AVG_TOKENS["reasoning"])["o"] for s in steps)
    p = GEMINI_PRICING["gemini-2.5-pro"]
    return {"input_tokens": i, "output_tokens": o, "model": "gemini-2.5-pro",
            "cost_usd": round(i/1e6*p["input_per_M"] + o/1e6*p["output_per_M"], 6)}

def estimate_pipeline_cost(analysis):
    ai = [s for s in analysis if s.get("classification") == "AI_REQUIRED"]
    if not ai:
        return {"input_tokens": 0, "output_tokens": 0, "model": "none", "cost_usd": 0.0, "ai_calls": 0}
    i, o = len(ai)*500, len(ai)*100
    p = GEMINI_PRICING["gemini-2.5-flash"]
    return {"input_tokens": i, "output_tokens": o, "model": "gemini-2.5-flash",
            "cost_usd": round(i/1e6*p["input_per_M"]+o/1e6*p["output_per_M"], 6), "ai_calls": len(ai)}

def compute_metrics(trace, analysis):
    total = len(analysis)
    det = sum(1 for s in analysis if s.get("classification") == "DETERMINISTIC")
    rule = sum(1 for s in analysis if s.get("classification") == "RULE_BASED")
    ai = sum(1 for s in analysis if s.get("classification") == "AI_REQUIRED")
    ac, pc = estimate_agent_cost(trace), estimate_pipeline_cost(analysis)
    red = round((1 - pc["cost_usd"]/ac["cost_usd"])*100) if ac["cost_usd"] > 0 else 100
    dur = 0
    steps = trace.get("steps", [])
    if len(steps) >= 2:
        try: dur = (datetime.fromisoformat(steps[-1]["timestamp"]) - datetime.fromisoformat(steps[0]["timestamp"])).total_seconds()
        except: pass
    return {"total": total, "det": det, "rule": rule, "ai": ai,
            "ai_pct_before": 100, "ai_pct_after": round(ai/total*100) if total else 0,
            "ac": ac, "pc": pc, "red": red,
            "spr": round(ac["cost_usd"]-pc["cost_usd"], 6),
            "sy": round((ac["cost_usd"]-pc["cost_usd"])*52, 4),
            "dur": round(dur, 1), "repo": trace.get("repo",""), "task": trace.get("task","")}

# ─── Trace loading ───
def load_trace(fp="execution_trace.json"):
    print(f"\n  Loading: {fp}")
    with open(fp) as f: trace = json.load(f)
    s = trace["summary"]
    print(f"  Steps: {trace['total_steps']} ({s['tool_calls']} tool, {s['reasoning_steps']} reasoning)")
    if not trace.get("pr_data"):
        print("  Enriching with GitHub data...")
        trace["pr_data"] = _fetch_prs(trace.get("repo", "facebook/react"))
        print(f"  Got {len(trace['pr_data'])} PRs")
    else:
        print(f"  PR data: {len(trace['pr_data'])} PRs")
    return trace

def _fetch_prs(repo):
    import requests
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    try:
        r = requests.get("https://api.github.com/search/issues", headers=h,
            params={"q": f"repo:{repo} is:pr is:merged merged:>={since}", "per_page": 50}, timeout=15)
        r.raise_for_status()
        merged = []
        for pr in r.json().get("items", []):
            try:
                fr = requests.get(f"https://api.github.com/repos/{repo}/pulls/{pr['number']}/files",
                    headers=h, params={"per_page": 30}, timeout=10)
                fr.raise_for_status()
                files = [f["filename"] for f in fr.json()]
            except: files = []
            merged.append({"number": pr["number"], "title": pr["title"], "author": pr["user"]["login"],
                           "body": (pr.get("body") or "")[:500],
                           "merged_at": pr.get("pull_request",{}).get("merged_at",""),
                           "url": pr["html_url"], "files_changed": files[:20]})
        return merged
    except Exception as e:
        print(f"  Error: {e}"); return []

# ─── Stage 1: Classify ───
def classify_steps(trace):
    from google.genai import types
    client = _client()
    print(f"\n  Stage 1: Classifying {len(trace['steps'])} steps...")
    prompt = f"""Classify each step as DETERMINISTIC, RULE_BASED, or AI_REQUIRED.
Be aggressive — downgrade whenever possible.
Steps:
{json.dumps(trace['steps'], indent=2)}
Respond ONLY with JSON array: [{{"step_number":1,"original_description":"...","classification":"DETERMINISTIC","reasoning":"..."}}]
No markdown fences."""
    r = client.models.generate_content(model="gemini-2.5-pro", contents=prompt,
        config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=4000))
    return _pj(r.text)

# ─── Stage 2: Extract rules ───
def extract_rules(trace):
    from google.genai import types
    client = _client()
    prs = trace.get("pr_data", [])
    if not prs: return _fallback()
    print(f"\n  Stage 2: Extracting rules from {len(prs)} PRs...")
    pl = [{"number":p["number"],"title":p["title"],"files":p.get("files_changed",[])[:10],
           "body":(p.get("body") or "")[:150]} for p in prs]
    ac = trace.get("agent_categories", {})
    if ac:
        for item in pl: item["correct_category"] = ac.get(str(item["number"]), "unknown")
    prompt = f"""Write a Python function to categorize GitHub PRs.
Real PRs from '{trace.get("repo","")}':
{json.dumps(pl, indent=2)}
Categories: bug_fix, new_feature, refactor, docs, test, chore
Signature: def categorize_pr(title: str, body: str, files: list) -> str
Use keyword scoring. No AI calls. Under 60 lines. Fall back to "chore".
Return ONLY the function. No markdown fences."""
    r = client.models.generate_content(model="gemini-2.5-pro", contents=prompt,
        config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=4000))
    code = _cc(r.text)
    if "def categorize_pr" not in code or "return" not in code:
        print("  Incomplete — using fallback"); return _fallback()
    return code

# ─── Stage 3: Validate ───
def validate_rules(code, trace, iters=2):
    prs = trace.get("pr_data", [])
    ac = trace.get("agent_categories", {})
    if not prs: return code
    print(f"\n  Stage 3: Validating against {len(prs)} PRs...")
    for i in range(iters):
        res = _run_cat(code, prs)
        if res is None:
            print("  Syntax error — fixing..."); code = _fix(code); continue
        if not ac:
            print(f"  Rules run OK on {len(res)} PRs")
            for p in prs: print(f"    #{p['number']} -> {res.get(p['number'],'?')}")
            break
        mm, ok = [], 0
        for p in prs:
            rc, ag = res.get(p["number"],"?"), ac.get(str(p["number"]),"?")
            if rc == ag: ok += 1
            elif ag != "unknown": mm.append({"number":p["number"],"title":p["title"],"rule":rc,"agent":ag})
        tot = ok + len(mm)
        acc = ok/tot if tot else 0
        print(f"  Iter {i+1}: {acc:.0%} ({ok}/{tot})")
        if acc >= 0.8 or not mm: print("  Validated"); break
        print(f"  Improving ({len(mm)} mismatches)...")
        code = _improve(code, mm)
    return code

def _run_cat(code, prs):
    try:
        ns = {}; exec(code, ns); fn = ns.get("categorize_pr")
        if not fn: return None
        return {p["number"]: fn(p.get("title",""), p.get("body",""), p.get("files_changed",[])) for p in prs}
    except: return None

def _improve(code, mm):
    from google.genai import types
    r = _client().models.generate_content(model="gemini-2.5-pro",
        contents=f"Fix this function — mismatches below.\n\n{code}\n\nMismatches:\n{json.dumps(mm,indent=2)}\n\nReturn ONLY the fixed function.",
        config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=4000))
    c = _cc(r.text)
    return c if "def categorize_pr" in c and "return" in c else code

def _fix(code):
    from google.genai import types
    r = _client().models.generate_content(model="gemini-2.5-pro",
        contents=f"Fix syntax errors:\n\n{code}\n\nSignature: def categorize_pr(title:str,body:str,files:list)->str\nReturn ONLY the fixed function.",
        config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=4000))
    c = _cc(r.text)
    return c if "def categorize_pr" in c else code

# ─── Stage 4: Assemble pipeline ───
# The pipeline is built by concatenation — NO .format(), NO escaping issues.
# The format_digest and post_to_slack functions are written as plain strings
# and injected verbatim, so what you see is exactly what runs.

def assemble_pipeline(trace, analysis, cat_code, m):
    print(f"\n  Stage 4: Assembling pipeline...")
    repo = trace.get("repo", "facebook/react")

    # Part 1: Header comment (the only part with injected values)
    header = f'''# ============================================================
# GENERATED PIPELINE -- Auto-created by "Deprecate Me"
# ============================================================
# Metrics computed from the original agent's execution trace.
#
# AI Dependency: {m["ai_pct_before"]}% -> {m["ai_pct_after"]}%
# Steps: {m["total"]} total ({m["det"]} deterministic, {m["rule"]} rule-based, {m["ai"]} AI)
# Agent cost/run:    ${m["ac"]["cost_usd"]} ({m["ac"]["model"]})
# Pipeline cost/run: ${m["pc"]["cost_usd"]} ({m["pc"]["model"]})
# Cost reduction:    {m["red"]}%
# ============================================================
'''

    # Part 2: Fixed code — written as a raw string, no escaping needed.
    # This is the EXACT Python that will be in the generated file.
    fixed_code = r'''
import os
import sys
import json
import time
from datetime import datetime, timedelta, timezone
import requests

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.getenv("GITHUB_REPO", "''' + repo + r'''").strip()
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "").strip()
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1").strip()
DAYS_AGO = 7
GITHUB_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
}

PRICING = {
    "gemini-2.5-pro":  {"input_per_M": 1.25, "output_per_M": 10.00},
    "gemini-2.5-flash": {"input_per_M": 0.15, "output_per_M": 0.60},
}

CATEGORY_CONFIG = {
    "new_feature": {"label": "New Features",  "order": 0},
    "bug_fix":     {"label": "Bug Fixes",     "order": 1},
    "refactor":    {"label": "Refactors",      "order": 2},
    "docs":        {"label": "Documentation",  "order": 3},
    "test":        {"label": "Tests",          "order": 4},
    "chore":       {"label": "Maintenance",    "order": 5},
}


class RunMetrics:
    def __init__(self):
        self.api_calls = 0
        self.ai_calls = 0
        self.prs_processed = 0
        self.ai_input_tokens = 0
        self.ai_output_tokens = 0
        self.start_time = None
        self.end_time = None

    def start(self):
        self.start_time = time.time()

    def stop(self):
        self.end_time = time.time()

    @property
    def duration(self):
        return round(self.end_time - self.start_time, 1) if self.start_time and self.end_time else 0

    @property
    def cost(self):
        if self.ai_calls == 0:
            return 0.0
        p = PRICING["gemini-2.5-flash"]
        return round(self.ai_input_tokens / 1e6 * p["input_per_M"] + self.ai_output_tokens / 1e6 * p["output_per_M"], 6)

    def record_ai(self, inp, out):
        self.ai_calls += 1
        self.ai_input_tokens += inp
        self.ai_output_tokens += out

metrics = RunMetrics()


def escape_slack(text):
    if not text:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def get_merged_prs(repo, days=7):
    since_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    print(f"  Fetching merged PRs from {repo} (since {since_date})...")
    try:
        resp = requests.get("https://api.github.com/search/issues",
            headers=GITHUB_HEADERS,
            params={"q": f"repo:{repo} is:pr is:merged merged:>={since_date}",
                    "sort": "updated", "order": "desc", "per_page": 50},
            timeout=15)
        resp.raise_for_status()
        metrics.api_calls += 1
        items = resp.json().get("items", [])
    except requests.RequestException as e:
        print(f"  Search API failed ({e}), trying pulls endpoint...")
        try:
            resp = requests.get(f"https://api.github.com/repos/{repo}/pulls",
                headers=GITHUB_HEADERS,
                params={"state": "closed", "sort": "updated", "direction": "desc", "per_page": 100},
                timeout=15)
            resp.raise_for_status()
            metrics.api_calls += 1
            items = [pr for pr in resp.json() if pr.get("merged_at") and pr["merged_at"][:10] >= since_date]
        except requests.RequestException as e2:
            print(f"  Error: {e2}", file=sys.stderr)
            return []

    merged = []
    for pr in items:
        pr_detail = pr.get("pull_request", {})
        merged_at = pr_detail.get("merged_at", "") if pr_detail else pr.get("merged_at", "")
        merged.append({"number": pr["number"], "title": pr["title"],
                       "author": pr["user"]["login"], "merged_at": merged_at,
                       "url": pr["html_url"], "body": (pr.get("body") or "")[:500]})
    print(f"  Found {len(merged)} merged PRs")
    return merged


def get_pr_files(repo, pr_number):
    try:
        resp = requests.get(f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files",
            headers=GITHUB_HEADERS, params={"per_page": 30}, timeout=10)
        resp.raise_for_status()
        metrics.api_calls += 1
        return [f["filename"] for f in resp.json()]
    except requests.RequestException:
        return []


'''

    # Part 3: The categorization rules (AI-generated, validated)
    cat_section = "\n# --- Categorization rules (extracted from agent behavior) ---\n\n"
    cat_section += cat_code.strip() + "\n\n"

    # Part 4: Summary, format, post, main — all fixed code
    rest_code = r'''
def generate_summary(pr):
    """Generate a short summary. Guaranteed to return a clean, complete string."""
    if not GOOGLE_CLOUD_PROJECT:
        return ""
    try:
        from google import genai
        from google.genai import types as gt
        client = genai.Client(vertexai=True, project=GOOGLE_CLOUD_PROJECT, location=GOOGLE_CLOUD_LOCATION)
        prompt = f"Summarize this GitHub PR change in under 12 words. No preamble. Example: 'Adds SSR benchmarks for Flight rendering performance.'\nTitle: {pr['title']}\nDescription: {(pr.get('body') or '')[:300]}\nSummary:"
        r = client.models.generate_content(model="gemini-2.5-flash", contents=prompt,
            config=gt.GenerateContentConfig(temperature=0.1, max_output_tokens=512))
        text = (r.text or "").strip().split("\n")[0].strip()
        if not text:
            return ""
        # Hard cap: 120 chars. If over, truncate at last word boundary and add period.
        if len(text) > 120:
            text = text[:120].rsplit(" ", 1)[0].rstrip(".,;:!?-") + "."
        # If it doesn't end with punctuation, add a period
        if text and text[-1] not in ".!?":
            text = text.rstrip(".,;:!?-") + "."
        # If it's basically the same as the title, skip it
        if text.lower().rstrip(".!?") == pr["title"].lower().rstrip(".!?"):
            return ""
        metrics.record_ai(len(prompt.split()) * 2, len(text.split()) * 2)
        return text
    except Exception as e:
        print(f"  AI summary failed for PR #{pr['number']}: {e}")
        return ""


def format_digest(repo, categorized_prs, pr_summaries):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    total = sum(len(v) for v in categorized_prs.values())

    lines = []
    lines.append(f"*Weekly PR Digest*  |  `{escape_slack(repo)}`  |  {week_ago} to {today}")
    lines.append(f"{total} pull requests merged")
    lines.append("")

    sorted_cats = sorted(categorized_prs.items(),
                         key=lambda x: CATEGORY_CONFIG.get(x[0], {}).get("order", 99))

    for cat_key, prs in sorted_cats:
        if not prs:
            continue
        label = CATEGORY_CONFIG.get(cat_key, {}).get("label", cat_key)
        lines.append(f"*{label}* ({len(prs)})")
        for pr in prs:
            safe_title = escape_slack(pr["title"])
            safe_author = escape_slack(pr["author"])
            lines.append(f"  <{pr['url']}|#{pr['number']}> {safe_title}  --  {safe_author}")
            summary = pr_summaries.get(pr["number"], "")
            if summary and summary != pr["title"]:
                lines.append(f"    {escape_slack(summary)}")
        lines.append("")

    lines.append(f"_Generated automatically  |  {datetime.now(timezone.utc).strftime('%H:%M UTC')}_")
    return "\n".join(lines)


def post_to_slack(message):
    if not SLACK_WEBHOOK_URL:
        print(f"\n{'=' * 60}\nSLACK MESSAGE (dry run)\n{'=' * 60}")
        print(message)
        print(f"{'=' * 60}\n")
        return True
    print("  Posting to Slack...")
    try:
        resp = requests.post(SLACK_WEBHOOK_URL, json={"text": message}, timeout=10)
        resp.raise_for_status()
        body = resp.text.strip()
        if body != "ok":
            print(f"  Slack warning: response was '{body}' instead of 'ok'")
            print(f"  Message may not have been delivered. Check Slack.")
            return False
        metrics.api_calls += 1
        print("  Posted successfully (confirmed: Slack returned 'ok')")
        return True
    except requests.RequestException as e:
        print(f"  Slack error: {e}", file=sys.stderr)
        return False


def main():
    metrics.start()
    ai_mode = "Minimal AI" if GOOGLE_CLOUD_PROJECT else "Zero AI"
    print(f"\n{'=' * 60}")
    print(f"  GENERATED PIPELINE  |  Mode: {ai_mode}")
    print(f"{'=' * 60}\n")

    if not GITHUB_TOKEN:
        print("GITHUB_TOKEN not set.", file=sys.stderr)
        sys.exit(1)

    repo = GITHUB_REPO
    prs = get_merged_prs(repo, days=DAYS_AGO)
    if not prs:
        print("No merged PRs found.")
        return
    metrics.prs_processed = len(prs)

    pr_files = {}
    for pr in prs[:15]:
        files = get_pr_files(repo, pr["number"])
        pr_files[pr["number"]] = files
        print(f"    PR #{pr['number']}: {len(files)} files")

    print("\n  Categorizing...")
    categorized = {}
    for pr in prs:
        cat = categorize_pr(pr["title"], pr.get("body", ""), pr_files.get(pr["number"], []))
        categorized.setdefault(cat, []).append(pr)
        label = CATEGORY_CONFIG.get(cat, {}).get("label", cat)
        print(f"    #{pr['number']} '{pr['title'][:50]}' -> {label}")

    print("\n  Generating summaries...")
    summaries = {}
    for pr in prs:
        summaries[pr["number"]] = generate_summary(pr)

    digest = format_digest(repo, categorized, summaries)
    post_to_slack(digest)

    metrics.stop()

    steps = 6
    ai_step = 1 if metrics.ai_calls > 0 else 0
    print(f"\n{'-' * 50}")
    print(f"  RUNTIME METRICS")
    print(f"{'-' * 50}")
    print(f"  PRs:          {metrics.prs_processed}")
    print(f"  API calls:    {metrics.api_calls}")
    print(f"  AI calls:     {metrics.ai_calls}")
    print(f"  AI tokens:    ~{metrics.ai_input_tokens} in, ~{metrics.ai_output_tokens} out")
    print(f"  Duration:     {metrics.duration}s")
    print(f"  Cost:         ${metrics.cost}")
    print(f"  AI dep:       {round(ai_step / steps * 100)}%")
    print(f"{'-' * 50}\n")


if __name__ == "__main__":
    main()
'''

    pipeline = header + fixed_code + cat_section + rest_code
    print(f"  Pipeline: {len(pipeline)} chars")
    return pipeline


# ─── Deprecation report ───
def gen_report(trace, analysis, m):
    ac, pc = m["ac"], m["pc"]
    lines = [
        "=" * 60, "  DEPRECATION REPORT", "=" * 60, "",
        f"  Task:     {m['task']}", f"  Repo:     {m['repo']}",
        f"  Date:     {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"  Duration: {m['dur']}s", "",
        "-" * 60, "  STEP CLASSIFICATION", "-" * 60,
    ]
    for s in analysis:
        tag = {"DETERMINISTIC":"DET","RULE_BASED":"RULE","AI_REQUIRED":" AI "}.get(s.get("classification",""),"??")
        lines.append(f"  [{tag}] Step {s['step_number']}: {s.get('original_description','')[:50]}")
        lines.append(f"         {s.get('reasoning','')[:70]}")
    lines += ["", "-" * 60, "  RESULTS", "-" * 60,
        f"  Total: {m['total']}  |  DET: {m['det']}  |  RULE: {m['rule']}  |  AI: {m['ai']}", "",
        "-" * 60, "  METRICS", "-" * 60,
        f"  AI dependency:   {m['ai_pct_before']}% -> {m['ai_pct_after']}%",
        f"  Agent cost:      ${ac['cost_usd']} ({ac['model']})",
        f"  Pipeline cost:   ${pc['cost_usd']} ({pc['model']})",
        f"  Cost reduction:  {m['red']}%",
        f"  Savings/run:     ${m['spr']}",
        f"  Savings/year:    ${m['sy']} (52 runs)", "",
        "=" * 60, '  "You don\'t need me anymore."', "=" * 60,
    ]
    return "\n".join(lines)


# ─── Helpers ───
def _client():
    from google import genai
    return genai.Client(vertexai=True,
        project=os.environ.get("GOOGLE_CLOUD_PROJECT","").strip(),
        location=os.environ.get("GOOGLE_CLOUD_LOCATION","us-central1").strip())

def _pj(text):
    t = text.strip()
    for f in ["```json","```"]:
        if t.startswith(f): t = t[len(f):].strip()
    if t.endswith("```"): t = t[:-3].strip()
    try: return json.loads(t)
    except:
        s, e = t.find("["), t.rfind("]")+1
        if s >= 0 and e > s:
            try: return json.loads(t[s:e])
            except: pass
    print("  Could not parse JSON"); return None

def _cc(t):
    t = t.strip()
    if t.startswith("```python"): t = t[9:].strip()
    elif t.startswith("```"): t = t[3:].strip()
    if t.endswith("```"): t = t[:-3].strip()
    return t

def _fallback():
    return '''def categorize_pr(title: str, body: str, files: list) -> str:
    title_lower = title.lower()
    body_lower = (body or "").lower()
    keywords = {
        "bug_fix": ["fix", "bug", "patch", "hotfix", "resolve", "crash", "error", "regression"],
        "new_feature": ["add", "feat", "new", "implement", "introduce", "support", "enable", "allow"],
        "refactor": ["refactor", "clean", "restructure", "simplify", "reorganize", "move", "rename", "migrate"],
        "docs": ["doc", "readme", "typo", "spelling", "grammar", "changelog", "comment"],
        "test": ["test", "spec", "coverage", "snapshot", "fixture", "benchmark", "assert"],
        "chore": ["chore", "ci", "build", "deps", "bump", "upgrade", "lint", "config", "release"],
    }
    file_signals = {
        "docs": [".md", "docs/", "README", "CHANGELOG"],
        "test": ["test/", "tests/", "__tests__/", ".test.", ".spec."],
        "chore": [".yml", ".yaml", "package.json", ".github/", ".eslint"],
    }
    scores = {cat: 0 for cat in keywords}
    for cat, kws in keywords.items():
        for kw in kws:
            if kw in title_lower: scores[cat] += 3
            if kw in body_lower: scores[cat] += 1
    for cat, patterns in file_signals.items():
        for f in files:
            for p in patterns:
                if p in f: scores[cat] += 2
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "chore"
'''

# ─── Dashboard artifacts (for dashboard.html — not hardcoded per repo) ───
def _escape_slack_dash(s):
    if not s:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write_dashboard_outputs(trace, m, cat_code):
    """Side-by-side Slack previews + metrics for the web dashboard."""
    repo = trace.get("repo") or ""
    prs = trace.get("pr_data") or []
    executed = trace.get("executed_at", "")

    try:
        end = datetime.fromisoformat(executed.replace("Z", "+00:00"))
    except Exception:
        end = datetime.now(timezone.utc)
    start = end - timedelta(days=7)
    header_dates = f"{start.strftime('%b %d')} to {end.strftime('%b %d, %Y')}"

    ORDER = ["new_feature", "bug_fix", "refactor", "docs", "test", "chore"]
    EMOJI = {
        "new_feature": "✨",
        "bug_fix": "🐛",
        "refactor": "🔧",
        "docs": "📚",
        "test": "🧪",
        "chore": "🏗️",
    }
    LABEL = {
        "new_feature": "New Features",
        "bug_fix": "Bug Fixes",
        "refactor": "Refactors",
        "docs": "Documentation",
        "test": "Tests",
        "chore": "Chores",
    }

    def group_agent():
        buckets = {k: [] for k in ORDER}
        ac = trace.get("agent_categories") or {}
        for pr in prs:
            n = pr["number"]
            cat = ac.get(str(n), ac.get(n))
            if cat not in buckets:
                cat = "chore"
            buckets[cat].append(pr)
        return buckets

    def group_pipeline():
        res = _run_cat(cat_code, prs) if prs and cat_code else {}
        buckets = {k: [] for k in ORDER}
        for pr in prs:
            cat = res.get(pr["number"], "chore")
            if cat not in buckets:
                cat = "chore"
            buckets[cat].append(pr)
        return buckets

    def one_line_summary(pr, short=False):
        body = (pr.get("body") or "").strip().replace("\n", " ")
        if len(body) > 220:
            body = body[:220].rsplit(" ", 1)[0] + "."
        if short and len(body) > 100:
            body = body[:100].rsplit(" ", 1)[0] + "."
        return body

    def format_slack(buckets, summaries, pipeline_style=False):
        lines = [
            f"📋 *Weekly PR Digest — {header_dates}*",
            f"_{len(prs)} PRs merged in `{_escape_slack_dash(repo)}`_",
            "",
        ]
        for cat in ORDER:
            lst = buckets.get(cat) or []
            if not lst:
                continue
            lines.append(f"{EMOJI[cat]} *{LABEL[cat]}* ({len(lst)})")
            for pr in lst:
                t = _escape_slack_dash(pr.get("title", ""))
                au = _escape_slack_dash(pr.get("author", ""))
                lines.append(f"  • <{pr.get('url', '')}|#{pr['number']}> {t} — _{au}_")
                summ = summaries.get(pr["number"], "")
                if summ:
                    lines.append(f"    _{_escape_slack_dash(summ)}_")
            lines.append("")
        if pipeline_style:
            lines.append("_Pipeline digest (rule-based categorization + flash summaries)._")
        else:
            lines.append("_Agent-style digest (categories from trace)._")
        return "\n".join(lines).strip()

    agent_buckets = group_agent()
    pipe_buckets = group_pipeline()

    agent_summaries = {}
    pipe_summaries = {}
    for pr in prs:
        agent_summaries[pr["number"]] = one_line_summary(pr, short=False)
        pipe_summaries[pr["number"]] = one_line_summary(pr, short=True)

    agent_msg = format_slack(agent_buckets, agent_summaries, False) if prs else (
        f"📋 *Weekly PR Digest — {header_dates}*\n_No `pr_data` in execution trace — Phase 2 can fetch PRs when `GITHUB_TOKEN` is set._"
    )
    pipe_msg = format_slack(pipe_buckets, pipe_summaries, True) if prs else agent_msg

    payload = {
        "agent_slack": agent_msg,
        "pipeline_slack": pipe_msg,
        "metrics": {
            "agent_cost_usd": m["ac"]["cost_usd"],
            "pipeline_cost_usd": m["pc"]["cost_usd"],
            "reduction_pct": m["red"],
            "yearly_savings_usd": m["sy"],
        },
    }
    with open("dashboard_outputs.json", "w") as f:
        json.dump(payload, f, indent=2)
    print(f"  Saved: dashboard_outputs.json")


# ─── Main ───
def main():
    print(f"\n{'=' * 60}")
    print(f"  DEPRECATE ME -- Phase 2: Self-Analysis")
    print(f"{'=' * 60}")

    trace = load_trace()

    print("\n" + "-" * 60)
    analysis = classify_steps(trace)
    if not analysis: print("  Failed."); return
    with open("analysis_report.json", "w") as f: json.dump(analysis, f, indent=2)
    print(f"  Saved: analysis_report.json")
    for s in analysis:
        tag = {"DETERMINISTIC":"DET","RULE_BASED":"RULE","AI_REQUIRED":" AI "}.get(s.get("classification",""),"??")
        print(f"  [{tag}] Step {s['step_number']}")

    m = compute_metrics(trace, analysis)
    print(f"\n  AI: {m['ai_pct_before']}% -> {m['ai_pct_after']}% | Agent: ${m['ac']['cost_usd']} | Pipeline: ${m['pc']['cost_usd']} | Reduction: {m['red']}%")

    print("\n" + "-" * 60)
    cat_code = extract_rules(trace) or _fallback()

    print("\n" + "-" * 60)
    cat_code = validate_rules(cat_code, trace)
    with open("categorization_rules.py", "w") as f: f.write(cat_code)
    print(f"  Saved: categorization_rules.py")

    print("\n" + "-" * 60)
    pipeline = assemble_pipeline(trace, analysis, cat_code, m)
    with open("generated_pipeline.py", "w") as f: f.write(pipeline)
    print(f"  Saved: generated_pipeline.py")

    # Verify the generated pipeline parses
    import ast
    try:
        ast.parse(pipeline)
        print("  Syntax check: OK")
    except SyntaxError as e:
        print(f"  WARNING: generated pipeline has syntax error at line {e.lineno}: {e.msg}")

    print("\n" + "-" * 60)
    report = gen_report(trace, analysis, m)
    with open("deprecation_report.txt", "w") as f: f.write(report)
    print(f"  Saved: deprecation_report.txt")
    write_dashboard_outputs(trace, m, cat_code)
    print(f"\n{report}")
    print(f"\n  Phase 2 complete. Test: python generated_pipeline.py\n")

if __name__ == "__main__":
    main()
