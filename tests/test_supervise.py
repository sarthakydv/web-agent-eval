"""feat-004: the supervisor stops on a condition, and only on the three it may.

`scripts/supervise.py` is driven here the way an unattended run drives it — as a
subprocess, with a real exit code — over fake episodes. Its three outcomes
(docs/DECISIONS.md entry 7) are:

    0  every manifest task has a terminal record
    1  K consecutive rounds added no new terminal record — stalled
    2  the token or wall-clock budget was exceeded

Every one of them is tested with its control, because each has a degenerate
implementation that would pass on its own: a supervisor that always exits 1
passes the stall test, one that always exits 2 passes the budget test, and one
that never runs a round at all passes the "no wrong records were written" test.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from web_agent_eval import records

ROOT = Path(__file__).resolve().parent.parent
SUPERVISE = ROOT / "scripts" / "supervise.py"
ENTRYPOINT = "fake_episodes:episode"


def supervise(tmp_path: Path, tasks: list[str], *extra: str, run_id: str = "t", env=None):
    command = [
        sys.executable, str(SUPERVISE),
        "--run-id", run_id,
        "--runs-dir", str(tmp_path),
        "--population", "explicit",
        "--tasks", ",".join(tasks),
        "--entrypoint", ENTRYPOINT,
        "--concurrency", "2",
        "--backoff-s", "0",
        "--stall-rounds", "2",
        "--max-rounds", "4",
        *extra,
    ]
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parent)}
    environment.update(env or {})
    completed = subprocess.run(
        command, cwd=ROOT, env=environment, capture_output=True, text=True,
        timeout=600, check=False
    )
    return completed


def tree_fingerprint(root: Path) -> dict:
    """Every file under `root`, by content and mtime. Used to prove a no-op."""
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[str(path.relative_to(root))] = (
                hashlib.sha256(path.read_bytes()).hexdigest(),
                path.stat().st_mtime_ns,
            )
    return out


# --------------------------------------------------------------------------
# exit 0 — everything terminal
# --------------------------------------------------------------------------


def test_exit_0_when_every_task_has_a_terminal_record(tmp_path):
    result = supervise(tmp_path, ["v1.pass-1", "v1.fail-1", "v1.capsteps-1", "v1.boom-1"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "EXIT 0 (COMPLETE)" in result.stdout
    assert records.terminal_task_ids(tmp_path / "t") == {
        "v1.pass-1", "v1.fail-1", "v1.capsteps-1", "v1.boom-1"
    }


def test_a_task_that_needs_a_second_round_does_not_read_as_a_stall(tmp_path):
    """The control for the stall test: slow progress is progress, not a stall."""
    result = supervise(tmp_path, ["v1.flaky-1", "v1.flaky-2", "v1.pass-1"])
    assert result.returncode == 0, result.stdout + result.stderr
    rows = records.read_attempts(tmp_path / "t")
    flaky = [r for r in rows if r["task_id"] == "v1.flaky-1"]
    assert [r["status"] for r in flaky] == [records.PROVIDER_ERROR, records.PASSED]


def test_rerunning_a_completed_run_changes_no_file(tmp_path):
    first = supervise(tmp_path, ["v1.pass-1", "v1.fail-1"])
    assert first.returncode == 0
    before = tree_fingerprint(tmp_path)

    second = supervise(tmp_path, ["v1.pass-1", "v1.fail-1"])
    assert second.returncode == 0
    assert "already complete" in second.stdout
    assert tree_fingerprint(tmp_path) == before, "a completed run must be a read, not a write"


# --------------------------------------------------------------------------
# exit 1 — stalled, and not one invented failure
# --------------------------------------------------------------------------


def test_exit_1_when_the_provider_refuses_every_call_and_nothing_is_recorded(tmp_path):
    tasks = ["v1.quota-1", "v1.quota-2", "v1.quota-3"]
    result = supervise(tmp_path, tasks)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "EXIT 1 (STALLED)" in result.stdout
    run_dir = tmp_path / "t"
    assert records.terminal_task_ids(run_dir) == set(), \
        "a provider outage must not produce a single terminal record"
    assert not (run_dir / records.RECORDS_DIR).exists() or \
        list((run_dir / records.RECORDS_DIR).glob("*.json")) == []
    rows = records.read_attempts(run_dir)
    assert rows and all(r["status"] == records.PROVIDER_ERROR for r in rows)
    assert all(r["terminal"] == "false" for r in rows)
    summary = records.summarise(run_dir, tasks)
    assert summary["passed"] == 0 and summary["scored"] == 0
    assert summary["counts"] == {"pending": 3}


def test_the_stall_takes_k_consecutive_empty_rounds(tmp_path):
    result = supervise(tmp_path, ["v1.quota-1"], "--stall-rounds", "3")
    assert result.returncode == 1
    lines = [json.loads(x) for x in (tmp_path / "t" / "supervise.jsonl").read_text().splitlines()]
    assert len(lines) == 3, "it must not give up before K rounds"
    assert [x["stalled_rounds"] for x in lines] == [1, 2, 3]
    assert all(x["new_terminal"] == 0 for x in lines)


def test_the_supervisor_is_bounded_even_when_it_is_neither_done_nor_stalled(tmp_path):
    """--max-rounds is the "never runs unbounded" clause, and it reports as stalled."""
    result = supervise(tmp_path, ["v1.quota-1"], "--stall-rounds", "99", "--max-rounds", "2")
    assert result.returncode == 1
    assert "round limit of 2" in result.stdout


# --------------------------------------------------------------------------
# exit 2 — the budget
# --------------------------------------------------------------------------


def test_exit_2_mid_run_with_every_already_terminal_record_intact(tmp_path):
    tasks = [f"v1.fat-{i}" for i in range(1, 7)]
    result = supervise(
        tmp_path, tasks, "--budget-tokens", "100000", "--concurrency", "1",
        env={"WAE_FAKE_FAT_TOKENS": "40000"},
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "EXIT 2 (BUDGET)" in result.stdout

    run_dir = tmp_path / "t"
    done = records.terminal_task_ids(run_dir)
    assert 0 < len(done) < len(tasks), "the budget must bite mid-run"
    for task_id in done:
        payload = json.loads((records.records_dir(run_dir) / f"{task_id}.json").read_text())
        assert payload["status"] == records.PASSED
        assert payload["tokens"] == 40000
        assert payload["reward"] == 1.0


def test_a_budget_the_run_can_meet_exits_0(tmp_path):
    """The control: a supervisor that always exits 2 would pass the test above."""
    result = supervise(
        tmp_path, ["v1.fat-1", "v1.fat-2"], "--budget-tokens", "10000000",
        env={"WAE_FAKE_FAT_TOKENS": "1000"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert records.summarise(tmp_path / "t", ["v1.fat-1", "v1.fat-2"])["terminal"] == 2


# --------------------------------------------------------------------------
# what each round logs
# --------------------------------------------------------------------------


def test_each_round_logs_what_it_attempted_what_became_terminal_and_any_backoff(tmp_path):
    result = supervise(tmp_path, ["v1.flaky-1", "v1.quota-1"], "--backoff-s", "0.01")
    assert result.returncode == 1
    lines = [json.loads(x) for x in (tmp_path / "t" / "supervise.jsonl").read_text().splitlines()]
    assert lines
    for entry in lines:
        for key in ("round", "attempted", "new_terminal", "pending",
                    "provider_errors", "backoff_s", "next_concurrency"):
            assert key in entry
    assert lines[0]["attempted"] == 2
    # Round 1 refuses both; the flaky task only becomes terminal on its second
    # attempt, which is the round the log has to show as progress.
    assert lines[0]["new_terminal"] == 0
    assert lines[1]["new_terminal"] == 1
    assert lines[1]["stalled_rounds"] == 0, "a round that added a record resets the stall"
    assert any(entry["backoff_s"] > 0 for entry in lines)
    assert any(entry["provider_errors"] > 0 for entry in lines)
    # And the round's own file, which the supervisor reads back.
    round_one = json.loads((tmp_path / "t" / "rounds" / "round_001.json").read_text())
    assert round_one["skipped_already_terminal"] == 0
    assert round_one["pending_at_start"] == 2


def test_the_runner_reports_how_many_it_skipped_on_resume(tmp_path):
    supervise(tmp_path, ["v1.pass-1", "v1.quota-1"])
    result = supervise(tmp_path, ["v1.pass-1", "v1.quota-1"])
    assert "1 of 2 already terminal (skipping them)" in result.stdout


def test_a_frozen_manifest_refuses_a_resume_that_changes_the_run(tmp_path):
    supervise(tmp_path, ["v1.pass-1", "v1.pass-2"])
    changed = supervise(tmp_path, ["v1.pass-1", "v1.fail-1"])
    assert changed.returncode == 3
    assert "manifest is never edited" in changed.stderr


@pytest.mark.parametrize("population,size", [("112", 112), ("102", 102), ("47", 47)])
def test_the_manifest_names_its_population_and_every_exclusion(tmp_path, population, size):
    """No run of the real set here — only the manifest it would freeze."""
    from web_agent_eval import manifest as manifest_module

    built = manifest_module.build(
        "m", population_name=population, concurrency=3,
        caps={"max_steps": 25, "max_tokens": 400000, "max_wall_clock_s": 300.0},
        model="glm-4.6", base_url="https://api.z.ai/api/coding/paas/v4/",
        episode_entrypoint="web_agent_eval.batch:real_episode",
    )
    assert built.size == size
    assert len(built.task_ids) + len(built.exclusions) == 112
    assert all(e["reason"] for e in built.exclusions)
