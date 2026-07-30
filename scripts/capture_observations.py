"""Capture real agisdk observations and store them as serializer fixtures.

Run:  uv run python scripts/capture_observations.py [task ...]

feat-001's gate did not persist observations — `runs/gate/*/` holds
`summary_info.json`, `experiment.log` and the agent's own action trace, none of
which contain a DOM, an accessibility tree or a screenshot. So the fixtures the
serializer is tested against are captured here, from a real run against the
hosted replica sites, and committed under `fixtures/observations/`.

The point of committing them: a serializer tested against a hand-written page is
a test of the hand-written page. These are byte-for-byte what browsergym handed
the agent — the full CDP DOM snapshot, the merged accessibility tree, the
extracted element properties and the PNG screenshot.

Each step writes:
    <task>_step<NN>.json.gz    everything except the screenshot
    <task>_step<NN>.png        the screenshot, as PNG

The agent that drives the page is `GateAgent` — gate scaffolding, used here only
because it is a working agent that makes the page advance. Nothing about the
serializer depends on it.
"""

from __future__ import annotations

import dataclasses
import gzip
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from agisdk import REAL
from PIL import Image

from web_agent_eval.gate_agent import GateAgent, GateAgentArgs

OUT_DIR = ROOT / "fixtures" / "observations"

# Two different sites, so the serializer is not tuned to one page shape.
DEFAULT_TASKS = ["v1.gomail-2", "v1.staynb-1"]

# Numpy-valued or per-run keys that are not worth storing verbatim.
_DROP = {"screenshot", "active_page_index", "elapsed_time"}


def _fallback(o):
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.integer, np.floating, np.bool_)):
        return o.item()
    return str(o)


class CaptureAgent(GateAgent):
    """GateAgent that dumps every raw observation before preprocessing."""

    def __init__(self, task: str, out_dir: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.task = task
        self.out_dir = Path(out_dir)
        self.captured = 0

    def obs_preprocessor(self, obs: dict) -> dict:
        step = self.captured
        self.captured += 1
        stem = f"{self.task}_step{step:02d}"
        self.out_dir.mkdir(parents=True, exist_ok=True)

        payload = {k: v for k, v in obs.items() if k not in _DROP}
        payload["capture"] = {
            "task": self.task,
            "step": step,
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "source": "agisdk REAL harness, headless chromium 1280x720, live run",
        }
        blob = json.dumps(payload, default=_fallback).encode()
        packed = gzip.compress(blob)
        (self.out_dir / f"{stem}.json.gz").write_bytes(packed)

        shot = obs.get("screenshot")
        if isinstance(shot, np.ndarray):
            Image.fromarray(shot).save(self.out_dir / f"{stem}.png")

        print(f"  captured {stem}  json.gz={len(packed):>9,}B  raw={len(blob):>10,}B  "
              f"url={obs.get('url')}")
        return super().obs_preprocessor(obs)


@dataclasses.dataclass
class CaptureAgentArgs(GateAgentArgs):
    task: str = "unknown"
    out_dir: str = str(OUT_DIR)

    def make_agent(self) -> CaptureAgent:
        return CaptureAgent(
            task=self.task,
            out_dir=self.out_dir,
            model_name=self.model_name,
            max_axtree_chars=self.max_axtree_chars,
            trace_path=self.trace_path,
        )


def main() -> None:
    tasks = sys.argv[1:] or DEFAULT_TASKS
    for task in tasks:
        print(f"\n=== capturing {task} ===")
        args = CaptureAgentArgs(
            task=task,
            trace_path=str(ROOT / "runs" / "capture" / f"{task}.trace.jsonl"),
        )
        harness = REAL.harness(
            agentargs=args,
            task_name=task,
            leaderboard=False,
            headless=True,
            max_steps=4,  # enough for a first page plus a couple of navigations
            use_html=False,
            use_axtree=True,
            use_screenshot=False,
            results_dir=str(ROOT / "runs" / "capture"),
            use_cache=False,
            num_workers=1,
        )
        results = harness.run()
        for name, record in results.items():
            print(f"  {name}: reward={record.get('cum_reward')} "
                  f"steps={record.get('n_steps')} err={record.get('err_msg')}")

    print("\ncaptured files:")
    for p in sorted(OUT_DIR.glob("*")):
        print(f"  {p.relative_to(ROOT)}  {p.stat().st_size:,}B")


if __name__ == "__main__":
    main()
