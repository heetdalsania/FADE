def categorize_pr(title: str, body: str, files: list) -> str:
    title_lower = title.lower()
    body_lower = (body or "").lower()

    # Keyword scoring per category — tuned against facebook/react PRs
    keywords = {
        "bug_fix": ["fix", "bug", "patch", "hotfix", "resolve", "crash", "error",
                     "regression", "leak", "mismatch", "race condition"],
        "new_feature": ["add", "feat", "new", "implement", "introduce", "support",
                        "enable", "initial"],
        "refactor": ["refactor", "clean", "restructure", "simplify", "reorganize",
                      "move", "rename", "extract", "consolidate", "share"],
        "docs": ["doc", "readme", "typo", "spelling", "grammar", "changelog",
                  "documentation", "reference", "api reference"],
        "test": ["test", "spec", "coverage", "snapshot", "fixture", "benchmark",
                  "integration test"],
        "chore": ["chore", "ci", "build", "deps", "bump", "upgrade", "lint",
                   "config", "workflow", "typescript", "eslint"],
    }

    # File path signals — strong indicators based on React repo structure
    file_signals = {
        "docs": [".md", "docs/", "README", "CHANGELOG"],
        "test": ["__tests__/", "-test.js", "-test.ts", ".test.", ".spec.",
                  "test-utils", "fixtures/"],
        "chore": [".yml", ".yaml", "package.json", ".github/workflows/",
                   ".eslint", "tsconfig", "yarn.lock", ".github/actions/"],
    }

    scores = {cat: 0 for cat in keywords}

    # Score title keywords (highest weight — title is most informative)
    for cat, kws in keywords.items():
        for kw in kws:
            if kw in title_lower:
                scores[cat] += 4
            if kw in body_lower:
                scores[cat] += 1

    # Score file path signals
    for cat, patterns in file_signals.items():
        for f in (files or []):
            f_lower = f.lower()
            for p in patterns:
                if p.lower() in f_lower:
                    scores[cat] += 2

    # Special handling: if ALL files are docs, it's docs
    if files and all(any(p in f for p in [".md", "docs/"]) for f in files):
        scores["docs"] += 10

    # Special handling: if ALL files are tests, it's test
    if files and all(any(p in f for p in ["test", "spec", "fixture"]) for f in files):
        scores["test"] += 10

    # Special handling: if ALL files are CI/config, it's chore
    if files and all(any(p in f for p in [".yml", ".yaml", ".github/", "package.json", "tsconfig", "yarn.lock"]) for f in files):
        scores["chore"] += 10

    # Tiebreaker: "update" in title with version-like patterns → chore
    if "update" in title_lower and ("bump" in title_lower or "v5" in title_lower or "v4" in title_lower or any(c.isdigit() for c in title_lower.split("to")[-1] if len(title_lower.split("to")) > 1)):
        scores["chore"] += 3

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "chore"
