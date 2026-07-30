"""feat-001 [GATE] — one REAL task end to end on GLM, plus the three answers.

Run:  uv run python scripts/run_gate.py [task]   (default: v1.gomail-2)

The default task is chosen so the score comes from agisdk alone: gomail-2 has a
single `jmespath` eval, which is a deterministic query over the site's own
/finish state. Tasks with an `llm_boolean` eval are graded by an LLM judge that
agisdk hardcodes to OpenAI gpt-4.1 — see question 3 below.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from agisdk import REAL
from agisdk.REAL.browsergym.webclones.task_config import TaskConfig

from web_agent_eval import glm
from web_agent_eval.gate_agent import GateAgentArgs

TASK = sys.argv[1] if len(sys.argv) > 1 else "v1.gomail-2"


def rule(text: str) -> None:
    print(f"\n{'=' * 72}\n{text}\n{'=' * 72}")


# --------------------------------------------------------------------------
# Q1 — does agisdk accept a custom OpenAI-compatible base_url?
# --------------------------------------------------------------------------
rule("Q1  custom OpenAI-compatible base_url")

client = glm.make_client()
print(f"client base_url : {client.base_url}")
print(f"model           : {glm.DEFAULT_MODEL}")

probe = client.chat.completions.create(
    model=glm.DEFAULT_MODEL,
    messages=[{"role": "user", "content": "Reply with exactly: ok"}],
    max_tokens=64,
    temperature=0.0,
    extra_body={"thinking": {"type": "disabled"}},
)
print(f"direct probe    : content={probe.choices[0].message.content!r} "
      f"model={probe.model} usage={probe.usage.total_tokens} tokens")

# The seam agisdk actually offers. The built-in agent routes on model-name
# prefix and exposes no base_url, so the custom-agent route is the one that
# works — this asserts it is a real agisdk agent, not a lookalike.
TRACE = ROOT / "runs" / "gate" / f"{TASK}.trace.jsonl"
agent_args = GateAgentArgs(trace_path=str(TRACE))
from agisdk.REAL.browsergym.experiments import AbstractAgentArgs, Agent

print(f"agentargs       : {type(agent_args).__name__}, "
      f"AbstractAgentArgs={isinstance(agent_args, AbstractAgentArgs)}")
print(f"made agent      : {type(agent_args.make_agent()).__name__}, "
      f"REAL Agent={isinstance(agent_args.make_agent(), Agent)}")

# --------------------------------------------------------------------------
# Q2 — are the 11 replica sites local or hosted?
# --------------------------------------------------------------------------
rule("Q2  where the replica sites are served from")

cfg = TaskConfig(TASK)
start_url = cfg.get_start_url()
host = urlparse(start_url).hostname
print(f"task            : {cfg.canonical_id}")
print(f"start_url       : {start_url}")
print(f"host            : {host}")
print(f"resolves to     : {sorted({a[4][0] for a in socket.getaddrinfo(host, 443)})}")
print(f"is localhost    : {host in ('localhost', '127.0.0.1')}")
print(f"WEBCLONE_URL env: {os.environ.get('WEBCLONE_URL')!r}  (unset => config URL is used)")

t0 = time.time()
reachable = cfg.is_task_url_reachable()
print(f"reachable       : {reachable}  ({time.time() - t0:.2f}s round trip)")

# --------------------------------------------------------------------------
# Q3 — does local scoring need a leaderboard key?
# --------------------------------------------------------------------------
rule("Q3  leaderboard key")

print(f"REAL_API_KEY set: {bool(os.environ.get('REAL_API_KEY'))}")
print(f"RUNID set       : {os.environ.get('RUNID')!r}")
print(f"eval types      : {[e.type for e in cfg.get_evals()]}")
print("harness call    : leaderboard=False, run_id=None, api_key=None")

# --------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------
rule(f"RUN  {TASK}")

results_dir = ROOT / "runs" / "gate"
harness = REAL.harness(
    agentargs=agent_args,
    task_name=TASK,
    leaderboard=False,
    headless=True,
    max_steps=15,
    use_html=False,
    use_axtree=True,
    use_screenshot=False,
    results_dir=str(results_dir),
    use_cache=False,
    num_workers=1,
)

start = time.time()
results = harness.run()
elapsed = time.time() - start

rule("RESULT")
for name, record in results.items():
    print(f"task            : {name}")
    print(f"cum_reward      : {record.get('cum_reward')}")
    print(f"n_steps         : {record.get('n_steps')}")
    print(f"terminated      : {record.get('terminated')}")
    print(f"err_msg         : {record.get('err_msg')}")
print(f"wall clock      : {elapsed:.1f}s")
print(f"RUNID after run : {os.environ.get('RUNID')!r}")

steps = [json.loads(line) for line in TRACE.read_text().splitlines() if line.strip()]
tokens = sum(s["usage"]["total_tokens"] for s in steps if s.get("usage"))
print(f"model steps     : {len(steps)}")
print(f"GLM tokens      : {tokens} total for the episode")
print("actions         :")
for s in steps:
    err = f"   <- ERROR: {s['last_action_error'].strip().splitlines()[0]}" if s["last_action_error"] else ""
    print(f"  {s['step']:>2}. {s['action'][:90]}{err}")

summary = {
    "task": TASK,
    "base_url": str(client.base_url),
    "model": glm.DEFAULT_MODEL,
    "start_url": start_url,
    "leaderboard": False,
    "results": {k: {"cum_reward": v.get("cum_reward"), "n_steps": v.get("n_steps")}
                for k, v in results.items()},
}
out = results_dir / "gate_summary.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(summary, indent=2))
print(f"summary written : {out}")
