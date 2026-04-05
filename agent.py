"""
DEPRECATE ME — Step 3: The Agent That Does The Task (And Watches Itself)
=========================================================================
This agent:
1. Connects to GitHub and Slack
2. Uses Gemini with function calling to execute a weekly digest workflow
3. Logs every single step into an execution trace
4. Saves the trace for Phase 2 (self-analysis)

SETUP:
  pip install google-genai requests

  Set these environment variables:
    export GOOGLE_CLOUD_PROJECT="your-project-id"
    export GOOGLE_CLOUD_LOCATION="us-central1"
    export GITHUB_TOKEN="ghp_your_token_here"
    export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/xxx/yyy/zzz"
    export GITHUB_REPO="owner/repo"  (e.g. "facebook/react")
"""

import os
import json
import time
import requests
from datetime import datetime, timedelta, timezone

# ─────────────────────────────────────────────
# 1. EXECUTION TRACE LOGGER
# ─────────────────────────────────────────────
# This is the secret sauce. Every step the agent takes gets recorded here.
# Later, Phase 2 will analyze this trace to figure out which steps need AI.

execution_trace = []

def log_step(step_type, description, input_data, output_data):
    """
    Log a single step in the agent's execution.
    
    step_type: "tool_call" or "reasoning"
      - tool_call  = the agent called an external API (GitHub, Slack, etc.)
      - reasoning   = the agent used Gemini to think/generate/classify
    
    This distinction is what Phase 2 uses to decide what can be automated.
    """
    entry = {
        "step_number": len(execution_trace) + 1,
        "step_type": step_type,
        "description": description,
        "input_summary": _summarize(input_data),
        "output_summary": _summarize(output_data),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    execution_trace.append(entry)
    # Print live so you can watch the agent work
    icon = "🔧" if step_type == "tool_call" else "🧠"
    print(f"  {icon} Step {entry['step_number']}: [{step_type}] {description}")
    return entry

def _summarize(data):
    """Keep trace entries readable — truncate long data."""
    s = str(data)
    if len(s) > 500:
        return s[:500] + "... [truncated]"
    return s


# ─────────────────────────────────────────────
# 2. TOOL FUNCTIONS (what the agent can call)
# ─────────────────────────────────────────────
# These are plain Python functions. Gemini will decide when to call them.
# Each one is wrapped with logging so the trace captures everything.

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
GITHUB_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
}


def get_merged_prs(repo: str, days: int = 7) -> str:
    """
    Fetch all pull requests merged in the last N days from a GitHub repo.
    
    Args:
        repo: GitHub repository in 'owner/repo' format (e.g. 'facebook/react')
        days: Number of days to look back (default 7)
    
    Returns:
        JSON string with list of merged PRs including title, author, and URL
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    log_step("tool_call", f"Fetching merged PRs from {repo} (last {days} days)",
             {"repo": repo, "since": since}, "...pending...")
    
    url = f"https://api.github.com/repos/{repo}/pulls"
    params = {"state": "closed", "sort": "updated", "direction": "desc", "per_page": 30}
    
    try:
        resp = requests.get(url, headers=GITHUB_HEADERS, params=params, timeout=10)
        resp.raise_for_status()
        all_prs = resp.json()
    except Exception as e:
        result = f"Error fetching PRs: {e}"
        # Update the last trace entry with the error
        execution_trace[-1]["output_summary"] = result
        return result
    
    # Filter to only merged PRs within our date range
    merged_prs = []
    for pr in all_prs:
        if pr.get("merged_at") and pr["merged_at"] >= since:
            merged_prs.append({
                "number": pr["number"],
                "title": pr["title"],
                "author": pr["user"]["login"],
                "merged_at": pr["merged_at"],
                "url": pr["html_url"],
                "body": (pr.get("body") or "")[:200],  # First 200 chars of description
            })
    
    result = json.dumps(merged_prs, indent=2)
    # Update trace with actual result
    execution_trace[-1]["output_summary"] = f"Found {len(merged_prs)} merged PRs"
    return result


def get_pr_diff(repo: str, pr_number: int) -> str:
    """
    Get the file changes (diff summary) for a specific pull request.
    
    Args:
        repo: GitHub repository in 'owner/repo' format
        pr_number: The PR number to get the diff for
    
    Returns:
        JSON string with list of changed files and their change statistics
    """
    log_step("tool_call", f"Fetching diff for PR #{pr_number}",
             {"repo": repo, "pr_number": pr_number}, "...pending...")
    
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files"
    
    try:
        resp = requests.get(url, headers=GITHUB_HEADERS, params={"per_page": 30}, timeout=10)
        resp.raise_for_status()
        files = resp.json()
    except Exception as e:
        result = f"Error fetching diff: {e}"
        execution_trace[-1]["output_summary"] = result
        return result
    
    changes = []
    for f in files:
        changes.append({
            "filename": f["filename"],
            "status": f["status"],  # added, removed, modified, renamed
            "additions": f["additions"],
            "deletions": f["deletions"],
        })
    
    result = json.dumps(changes, indent=2)
    execution_trace[-1]["output_summary"] = f"{len(changes)} files changed"
    return result


def post_to_slack(message: str) -> str:
    """
    Post a formatted message to a Slack channel via webhook.
    
    Args:
        message: The markdown-formatted message to post to Slack
    
    Returns:
        Success or error message
    """
    log_step("tool_call", "Posting digest to Slack",
             {"message_length": len(message)}, "...pending...")
    
    if not SLACK_WEBHOOK_URL:
        result = "SLACK_WEBHOOK_URL not set — would have posted:\n" + message
        execution_trace[-1]["output_summary"] = "Slack not configured (dry run)"
        print(f"\n📋 SLACK MESSAGE (dry run):\n{'='*50}\n{message}\n{'='*50}\n")
        return result
    
    try:
        resp = requests.post(SLACK_WEBHOOK_URL, json={"text": message}, timeout=10)
        resp.raise_for_status()
        result = "Successfully posted to Slack"
    except Exception as e:
        result = f"Error posting to Slack: {e}"
    
    execution_trace[-1]["output_summary"] = result
    return result


# ─────────────────────────────────────────────
# 3. THE AGENT (Gemini + Function Calling)
# ─────────────────────────────────────────────

def run_agent():
    """
    Run the full weekly digest agent.
    
    This is where Gemini takes control. It decides:
    - Which tools to call and in what order
    - How to interpret the results
    - How to categorize PRs (this is the "reasoning" step)
    - How to write the summary (another "reasoning" step)
    
    The execution trace captures everything for Phase 2.
    """
    from google import genai
    from google.genai import types
    
    # ── Initialize the client ──
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "your-project-id")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    
    client = genai.Client(vertexai=True, project=project, location=location)
    
    repo = os.environ.get("GITHUB_REPO", "facebook/react")
    
    print(f"\n{'='*60}")
    print(f"  DEPRECATE ME — Agent Executing Task")
    print(f"  Repo: {repo}")
    print(f"  Task: Weekly PR Digest → Slack")
    print(f"{'='*60}\n")
    
    # ── The system prompt tells Gemini what to do ──
    system_prompt = f"""You are a developer productivity agent. Your task is to create 
a weekly PR digest for the GitHub repo: {repo}

Follow these steps exactly:
1. Call get_merged_prs to fetch all PRs merged in the last 7 days
2. For the top 5 most interesting PRs, call get_pr_diff to understand what changed
3. Categorize each PR as one of: bug_fix, new_feature, refactor, docs, chore, test
4. Write a clean weekly digest summary in Slack markdown format
5. Call post_to_slack to post the digest

The digest should include:
- A header with the week and total PR count
- PRs grouped by category
- For each PR: title, author, and a one-line description of the change

Be concise but informative."""

    # ── Register tools ──
    # The Google Gen AI SDK can auto-detect function signatures
    tools = [get_merged_prs, get_pr_diff, post_to_slack]
    
    # ── Run the agent in a loop ──
    # Gemini will call tools, we execute them and feed results back
    
    log_step("reasoning", "Agent starting — planning workflow",
             {"task": "weekly PR digest", "repo": repo}, "Initializing...")
    
    print("\n🤖 Agent is thinking...\n")
    
    try:
        response = client.models.generate_content(
            model="gemini-2.5-pro",
            contents=f"Please create the weekly PR digest for {repo}. Start by fetching the merged PRs.",
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                tools=tools,
                temperature=0.2,  # Low temperature for consistent, deterministic behavior
            ),
        )
        
        # ── Process the response ──
        # The SDK with automatic function calling handles the tool loop for us.
        # But we need to log the reasoning steps too.
        
        if response.text:
            log_step("reasoning", "Agent generated final output",
                     {"prompt": "digest generation"}, response.text[:300])
            print(f"\n📝 Agent's final output:\n{response.text[:500]}")
        
        # Check if there are function call parts in the response
        if response.candidates:
            for candidate in response.candidates:
                for part in candidate.content.parts:
                    if hasattr(part, 'function_call') and part.function_call:
                        fc = part.function_call
                        log_step("reasoning", f"Agent decided to call {fc.name}",
                                 dict(fc.args), "Function call requested")
    
    except Exception as e:
        print(f"\n❌ Error during agent execution: {e}")
        print(f"   This might mean:")
        print(f"   - Your GOOGLE_CLOUD_PROJECT is not set correctly")
        print(f"   - The Vertex AI API is not enabled")
        print(f"   - Your authentication isn't set up (run: gcloud auth application-default login)")
        log_step("reasoning", f"Agent encountered error: {str(e)[:200]}",
                 {}, str(e)[:200])
    
    return execution_trace


def run_agent_manual():
    """
    A manual version that doesn't require Gemini — useful for testing
    the trace logging and tools before you have GCP set up.
    
    This simulates what Gemini would do so you can:
    1. Test that your GitHub/Slack connections work
    2. See what the execution trace looks like
    3. Build the UI while the agent logic is still in progress
    """
    repo = os.environ.get("GITHUB_REPO", "facebook/react")
    
    print(f"\n{'='*60}")
    print(f"  DEPRECATE ME — Manual Agent (no Gemini required)")
    print(f"  Repo: {repo}")
    print(f"{'='*60}\n")
    
    # Step 1: Fetch PRs (tool call — deterministic)
    log_step("reasoning", "Planning: need to fetch merged PRs first",
             {"task": "weekly digest"}, "Will call get_merged_prs")
    
    prs_json = get_merged_prs(repo, days=7)
    prs = json.loads(prs_json) if not prs_json.startswith("Error") else []
    
    print(f"\n  Found {len(prs)} merged PRs\n")
    
    # Step 2: Fetch diffs for top PRs (tool call — deterministic)
    diffs = {}
    for pr in prs[:5]:  # Top 5
        log_step("reasoning", f"Deciding to inspect PR #{pr['number']}: {pr['title'][:50]}",
                 {"pr": pr["number"]}, "Will fetch diff")
        
        diff_json = get_pr_diff(repo, pr["number"])
        diffs[pr["number"]] = json.loads(diff_json) if not diff_json.startswith("Error") else []
    
    # Step 3: Categorize each PR (this is the REASONING step — needs AI)
    log_step("reasoning", "Categorizing PRs based on titles and diffs",
             {"pr_count": len(prs)}, "Applying categories...")
    
    categories = {"bug_fix": [], "new_feature": [], "refactor": [], "docs": [], "chore": [], "test": []}
    
    for pr in prs:
        title = pr["title"].lower()
        # Simple heuristic categorization (Phase 2 will extract these rules!)
        if any(w in title for w in ["fix", "bug", "patch", "hotfix", "issue"]):
            cat = "bug_fix"
        elif any(w in title for w in ["feat", "add", "new", "implement", "introduce"]):
            cat = "new_feature"
        elif any(w in title for w in ["refactor", "clean", "restructure", "simplify"]):
            cat = "refactor"
        elif any(w in title for w in ["doc", "readme", "comment", "typo"]):
            cat = "docs"
        elif any(w in title for w in ["test", "spec", "coverage"]):
            cat = "test"
        else:
            cat = "chore"
        categories[cat].append(pr)
    
    log_step("reasoning", "Categorization complete",
             {"method": "keyword matching on PR titles"},
             {cat: len(prs_list) for cat, prs_list in categories.items() if prs_list})
    
    # Step 4: Write the summary (this is REASONING — needs AI for good prose)
    log_step("reasoning", "Writing weekly digest summary",
             {"categories": list(categories.keys())}, "Generating markdown...")
    
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%B %d")
    
    emoji_map = {
        "bug_fix": "🐛", "new_feature": "✨", "refactor": "🔧",
        "docs": "📚", "chore": "🏗️", "test": "🧪"
    }
    label_map = {
        "bug_fix": "Bug Fixes", "new_feature": "New Features", "refactor": "Refactors",
        "docs": "Documentation", "chore": "Chores", "test": "Tests"
    }
    
    lines = [f"📋 *Weekly PR Digest — {week_ago} to {today}*"]
    lines.append(f"_{len(prs)} PRs merged in `{repo}`_\n")
    
    for cat, prs_list in categories.items():
        if prs_list:
            lines.append(f"\n{emoji_map[cat]} *{label_map[cat]}* ({len(prs_list)})")
            for pr in prs_list[:5]:  # Max 5 per category
                lines.append(f"  • <{pr['url']}|#{pr['number']}> {pr['title']} — _{pr['author']}_")
    
    digest = "\n".join(lines)
    
    log_step("reasoning", "Digest written",
             {"line_count": len(lines)}, digest[:200])
    
    # Step 5: Post to Slack (tool call — deterministic)
    post_to_slack(digest)
    
    # ── Save the execution trace ──
    save_trace()
    
    return execution_trace


def save_trace():
    """Save the execution trace to a JSON file for Phase 2."""
    trace_file = "execution_trace.json"
    
    trace_data = {
        "task": "weekly_pr_digest",
        "repo": os.environ.get("GITHUB_REPO", "facebook/react"),
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "total_steps": len(execution_trace),
        "steps": execution_trace,
        "summary": {
            "tool_calls": sum(1 for s in execution_trace if s["step_type"] == "tool_call"),
            "reasoning_steps": sum(1 for s in execution_trace if s["step_type"] == "reasoning"),
        }
    }
    
    with open(trace_file, "w") as f:
        json.dump(trace_data, f, indent=2)
    
    print(f"\n{'='*60}")
    print(f"  ✅ Execution trace saved to: {trace_file}")
    print(f"  📊 Total steps: {trace_data['total_steps']}")
    print(f"     🔧 Tool calls:      {trace_data['summary']['tool_calls']}")
    print(f"     🧠 Reasoning steps:  {trace_data['summary']['reasoning_steps']}")
    print(f"\n  → This trace is the input for Phase 2 (self-analysis)")
    print(f"{'='*60}\n")


# ─────────────────────────────────────────────
# 4. RUN IT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    
    print("\n🚀 DEPRECATE ME — The Self-Eliminating Agent")
    print("─" * 45)
    
    if "--manual" in sys.argv:
        # Run without Gemini (for testing tools + trace)
        print("Running in MANUAL mode (no Gemini calls)")
        trace = run_agent_manual()
    else:
        # Run with Gemini function calling
        print("Running with Gemini (full agent mode)")
        print("Tip: use --manual flag to test without Gemini\n")
        trace = run_agent()
        save_trace()
    
    # Print the trace summary
    print("\n📜 FULL EXECUTION TRACE:")
    print("─" * 45)
    for step in trace:
        icon = "🔧" if step["step_type"] == "tool_call" else "🧠"
        print(f"  {icon} {step['step_number']}. {step['description']}")
    print()
