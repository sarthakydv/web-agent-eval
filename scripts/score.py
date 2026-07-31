"""Score a run from its stored per-task records, and prove the figure reproduces.

    uv run python scripts/score.py --run-id pilot            # compute and write score.json
    uv run python scripts/score.py --run-id pilot --check    # recompute, fail on any drift

`feat-005`'s verification is that the aggregate comes back out of
`runs/<id>/` alone. This reads `manifest.json` and `records/*.json` and nothing
else — no results.tsv, no in-memory state from the run that produced them — so
`--check` failing means the stored records and the published figure disagree,
which is the only way this project would be allowed to notice that.

Exit codes:
    0  computed, or checked and identical
    1  the run directory is unusable, or --check found a difference
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from web_agent_eval import scoring


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--check", action="store_true",
                        help="recompute and compare against the stored score.json")
    parser.add_argument("--json", action="store_true", help="print the payload, not the table")
    args = parser.parse_args(argv)

    run_dir = Path(args.runs_dir) / args.run_id
    if not (run_dir / "manifest.json").exists():
        print(f"no manifest at {run_dir / 'manifest.json'}", file=sys.stderr)
        return 1

    payload = scoring.score(run_dir)

    if args.check:
        path = scoring.score_path(run_dir)
        if not path.exists():
            print(f"nothing to check against: {path} does not exist", file=sys.stderr)
            return 1
        stored = json.loads(path.read_text())
        recomputed = payload["digest"]
        if stored.get("digest") != recomputed:
            print("RECOMPUTED SCORE DIFFERS FROM THE STORED ONE", file=sys.stderr)
            print(f"  stored     digest: {stored.get('digest')}", file=sys.stderr)
            print(f"  recomputed digest: {recomputed}", file=sys.stderr)
            for key in sorted(set(stored) | set(payload)):
                if key != "digest" and stored.get(key) != payload.get(key):
                    print(f"  differs: {key}", file=sys.stderr)
            return 1
        print(f"score reproduces from {run_dir}/records/ alone")
        print(f"  digest {recomputed}")
        print(f"  passed {payload['passed']}/{payload['terminal']} terminal, "
              f"agent {payload['agent']['tokens']['total']} tokens, "
              f"judge {payload['judge']['tokens']['total']} tokens "
              f"= ${payload['judge']['usd']:.6f}")
        return 0

    path = scoring.write(run_dir, payload)
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(scoring.render(payload))
    print(f"\nwritten: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
