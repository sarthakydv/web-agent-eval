#!/bin/bash
# web-agent-eval (P3) — session init and verification.
# Every check here must actually execute. A harness that passes vacuously is
# worse than no harness: the predecessor project shipped four scripts that had
# never once been typechecked because `typecheck` did not exist and `bun test`
# was passing on zero test files.
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
FAILURES=0
fail() { echo "  FAIL: $1"; FAILURES=$((FAILURES + 1)); }

echo "=== web-agent-eval (P3) ==="
echo ""

# --- state ---
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")
DIRTY=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
REMOTE=$(git remote get-url origin 2>/dev/null || echo "none")
echo "  branch: $BRANCH | uncommitted: $DIRTY | remote: $REMOTE"

if [ -f .env ]; then echo "  secrets: present"; else fail "no .env — copy ZAI_API_KEY into it"; fi

# A secret must never be tracked by git.
TRACKED=$(git ls-files 2>/dev/null | grep -E '(^|/)\.env$' || true)
[ -n "$TRACKED" ] && fail "TRACKING A SECRET FILE: $TRACKED"

if [ -f feature_list.json ]; then
  # State report, then the tracker's own rules — see "Feature list rules" in
  # AGENTS.md. A status field an agent can set on its own, with no verification
  # command behind it and no output pasted under it, is an opinion.
  python3 - feature_list.json <<'PY' || fail "feature_list.json broke a tracker rule"
import json, sys
data = json.load(open(sys.argv[1]))
feats = data["features"]
counts = {}
for f in feats:
    counts[f["status"]] = counts.get(f["status"], 0) + 1
print("  features: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))
for f in feats:
    if f["status"] in ("in-progress", "blocked"):
        print(f"  -> {f['status'].upper()}: {f['id']} {f['name']}")
nxt = next((f for f in feats if f["status"] == "not-started"
            and all(any(d == g["id"] and g["status"] == "done" for g in feats)
                    for d in f.get("dependencies", []))), None)
if nxt:
    print(f"  next available: {nxt['id']} {nxt['name']}")

problems = []
no_ev = [f["id"] for f in feats if f["status"] == "done" and not (f.get("evidence") or "").strip()]
if no_ev:
    problems.append("done with an empty evidence field: " + ", ".join(no_ev))
if data.get("verification_required"):
    no_v = [f["id"] for f in feats if not (f.get("verification") or "").strip()]
    if no_v:
        problems.append("no verification field: " + ", ".join(no_v))
wip = [f["id"] for f in feats if f["status"] == "in-progress"]
if len(wip) > 1:
    problems.append("one feature at a time, but in-progress: " + ", ".join(wip))
for p in problems:
    print(f"  FAIL: {p}")
sys.exit(1 if problems else 0)
PY
else
  fail "no feature_list.json"
fi

# --- checks that must pass ---
echo ""
echo "  running checks (env / lint / tests)..."

command -v uv >/dev/null 2>&1 || { echo "  FAIL: uv not installed"; exit 1; }

uv sync --quiet || fail "uv sync"

# The interpreter is pinned deliberately; 3.14 is not supported here.
uv run python -c "
import sys
v = sys.version_info
assert (v.major, v.minor) == (3, 12), f'expected Python 3.12, got {v.major}.{v.minor}'
print(f'  python: {sys.version.split()[0]}')
import agisdk
from agisdk import REAL
assert callable(REAL.harness)
print('  agisdk: import ok, REAL.harness callable')
" || fail "python/agisdk environment"

uv run ruff check . || fail "ruff"
uv run pytest -q || fail "pytest"

# The decisions log is append-only and grows with the project. Nothing may read
# it end to end, so the index at its top is how a session finds an entry — and a
# stale index is worse than none, because it is trusted.
python3 scripts/decisions_index.py --check || fail "docs/DECISIONS.md index is stale"

echo ""
if [ "$FAILURES" -gt 0 ]; then
  echo "=== $FAILURES CHECK(S) FAILED — fix before claiming any feature done ==="
  exit 1
fi

echo "=== All checks passed ==="
echo ""
echo "1. Read AGENTS.md, then ONLY your feature's entry in feature_list.json"
echo "2. Read the entry index at the top of docs/DECISIONS.md; open only the"
echo "   entries your feature depends on. Neither file is read end to end."
echo "3. Take ONE feature id and nothing else"
echo "4. Paste real command output into its evidence field — not 'tests pass'"
echo "5. Stop and report on a [GATE]; never work around it"
