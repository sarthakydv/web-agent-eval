"""feat-005: the aggregate comes back out of the stored records, and only those.

Offline, against hand-written run directories — no episodes, no browser, no key.
The subject here is the arithmetic and its provenance, and a real run would test
neither more thoroughly.

The controls matter as much as the checks. "The score reproduces" is worth
nothing unless a changed record makes it stop reproducing, and "judge tokens are
counted" is worth nothing unless the agent's far larger token count is kept out
of that column.
"""

from __future__ import annotations

import json
from pathlib import Path

from web_agent_eval import records, scoring


def judge_ledger(*, calls: int = 1, prompt: int = 160, completion: int = 3) -> dict:
    return {
        "installed": True,
        "endpoint": {"host": "api.openai.com", "model_default": "gpt-4.1"},
        "evaluate_calls": 1 if calls else 0,
        "judge_calls": calls,
        "llm_evals": [{"similarity": 1.0, "is_correct": True, "rubric": "r", "model_response": "a"}]
        * calls,
        "calls": [
            {
                "requested_model": "gpt-4.1",
                "served_model": "gpt-4.1-2025-04-14",
                "base_url": "https://api.openai.com/v1/",
                "host": "api.openai.com",
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": prompt + completion,
                "cached_tokens": 0,
            }
        ]
        * calls,
        "errors": [],
        "tokens": {
            "prompt": prompt * calls,
            "completion": completion * calls,
            "cached_prompt": 0,
            "total": (prompt + completion) * calls,
        },
    }


def make_run(tmp_path: Path, rows: list[dict], *, run_id: str = "r") -> Path:
    """A run directory holding only what `scoring` is allowed to read."""
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text(json.dumps({
        "run_id": run_id,
        "population": "explicit",
        "task_ids": [r["task_id"] for r in rows],
        "model": "glm-4.6",
        "caps": {"max_steps": 25, "max_tokens": 400_000, "max_wall_clock_s": 300.0},
    }))
    for row in rows:
        if row.get("status"):
            records.write_terminal_record(run_dir, row["task_id"], row)
    return run_dir


def task(task_id: str, status: str, *, tokens: int, steps: int = 5, secs: float = 30.0,
         needs_judge: bool = False, ledger: dict | None = None) -> dict:
    return {
        "task_id": task_id,
        "site": task_id.split(".", 1)[1].rsplit("-", 1)[0],
        "status": status,
        "reward": 1.0 if status == records.PASSED else 0.0,
        "steps": steps,
        "tokens": tokens,
        "wall_clock_s": secs,
        "cap": "steps" if status == records.CAPPED else None,
        "needs_judge": needs_judge,
        "judge": ledger,
    }


def test_the_rate_and_both_token_columns_come_from_the_records():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        run_dir = make_run(Path(tmp), [
            task("v1.gomail-1", records.PASSED, tokens=4464, needs_judge=True,
                 ledger=judge_ledger(prompt=100, completion=3)),
            task("v1.zilloft-1", records.PASSED, tokens=15823, needs_judge=True,
                 ledger=judge_ledger(prompt=137, completion=3)),
            task("v1.staynb-2", records.CAPPED, tokens=71382),
            task("v1.topwork-5", records.FAILED, tokens=14273, needs_judge=True,
                 ledger=judge_ledger(prompt=168, completion=3)),
        ])
        payload = scoring.score(run_dir)

    assert payload["passed"] == 2
    assert payload["terminal"] == 4
    assert payload["rate_over_terminal"] == 0.5
    assert payload["rate_over_manifest"] == 0.5
    assert payload["agent"]["tokens"]["total"] == 4464 + 15823 + 71382 + 14273
    assert payload["judge"]["tokens"] == {
        "prompt": 405, "completion": 9, "cached_prompt": 0, "total": 414,
    }
    # Two columns, never one. The agent's provider publishes no rate for this
    # key, so its dollar cell is empty on purpose rather than estimated.
    assert payload["agent"]["usd"] is None
    assert payload["agent"]["rate_published"] is False
    assert payload["judge"]["usd"] == round((405 * 2.00 + 9 * 8.00) / 1_000_000, 6)
    assert payload["judge"]["hosts"] == ["api.openai.com"]
    assert payload["judge"]["models_served"] == ["gpt-4.1-2025-04-14"]


def test_a_task_that_needed_the_judge_and_never_got_one_is_named_not_absorbed():
    """The real case from the pilot: `v1.fly-unified-1` capped on steps without
    the agent ever answering, so agisdk's `validate()` short-circuited and
    `evaluate()` never ran. It is a genuine zero and it counts as a failure —
    but it is not a grade the judge gave, and a judged rate quoted over it
    would be quoting tasks that were never judged."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        run_dir = make_run(Path(tmp), [
            task("v1.fly-unified-1", records.CAPPED, tokens=75407, needs_judge=True,
                 ledger=judge_ledger(calls=0)),
            task("v1.gomail-1", records.PASSED, tokens=4464, needs_judge=True,
                 ledger=judge_ledger()),
        ])
        payload = scoring.score(run_dir)

    assert payload["judge"]["tasks_needing_judge"] == 2
    assert payload["judge"]["tasks_judged"] == 1
    assert payload["judge"]["tasks_unjudged"] == ["v1.fly-unified-1"]
    # It still counts against the rate. Not judged is not not counted.
    assert payload["passed"] == 1
    assert payload["terminal"] == 2
    assert payload["rate_over_terminal"] == 0.5


def test_the_agents_tokens_never_land_in_the_judges_column():
    """The control on the split. The agent spends thousands of times what the
    judge does, so a leak in this direction would be invisible in the rate and
    enormous in the dollar figure."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        run_dir = make_run(Path(tmp), [
            task("v1.staynb-2", records.CAPPED, tokens=71382, ledger=judge_ledger(calls=0)),
        ])
        payload = scoring.score(run_dir)

    assert payload["agent"]["tokens"]["total"] == 71382
    assert payload["judge"]["tokens"]["total"] == 0
    assert payload["judge"]["usd"] == 0.0


def test_a_pending_task_holds_the_denominator_open():
    """A manifest task with no record is pending, not absent. Entry 7: a
    denominator that emerges from which tasks happened to finish is not a
    denominator, so `rate_over_manifest` stays None until every one is in."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        run_dir = make_run(Path(tmp), [
            task("v1.gomail-1", records.PASSED, tokens=4464),
            {"task_id": "v1.zilloft-1", "status": None},
        ])
        payload = scoring.score(run_dir)

    assert payload["manifest_n"] == 2
    assert payload["terminal"] == 1
    assert payload["pending"] == ["v1.zilloft-1"]
    assert payload["rate_over_terminal"] == 1.0
    assert payload["rate_over_manifest"] is None


def test_the_score_reproduces_from_the_records_alone():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        run_dir = make_run(Path(tmp), [
            task("v1.gomail-1", records.PASSED, tokens=4464, needs_judge=True,
                 ledger=judge_ledger()),
            task("v1.staynb-2", records.CAPPED, tokens=71382),
        ])
        first = scoring.score(run_dir)
        scoring.write(run_dir, first)
        second = scoring.score(run_dir)

    assert first["digest"] == second["digest"]
    assert first == second


def test_a_changed_record_changes_the_digest():
    """The control. A reproducibility check that cannot fail proves nothing —
    this is the whole reason `--check` compares a digest of every per-task row
    rather than the headline rate, which two different runs can share."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        run_dir = make_run(Path(tmp), [
            task("v1.gomail-1", records.PASSED, tokens=4464),
            task("v1.staynb-2", records.CAPPED, tokens=71382),
        ])
        before = scoring.score(run_dir)

        path = records.records_dir(run_dir) / "v1.gomail-1.json"
        payload = json.loads(path.read_text())
        payload["status"] = records.FAILED
        path.write_text(json.dumps(payload))
        after = scoring.score(run_dir)

    assert before["digest"] != after["digest"]
    assert before["passed"] == 1
    assert after["passed"] == 0


def test_a_token_count_edited_by_a_single_token_changes_the_digest():
    """The same control, one field over. The rate is identical either way, so
    only a digest over every row catches it."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        run_dir = make_run(Path(tmp), [task("v1.gomail-1", records.PASSED, tokens=4464)])
        before = scoring.score(run_dir)

        path = records.records_dir(run_dir) / "v1.gomail-1.json"
        payload = json.loads(path.read_text())
        payload["tokens"] = 4465
        path.write_text(json.dumps(payload))
        after = scoring.score(run_dir)

    assert before["rate_over_terminal"] == after["rate_over_terminal"] == 1.0
    assert before["digest"] != after["digest"]


def test_render_never_prints_a_combined_cost():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        run_dir = make_run(Path(tmp), [
            task("v1.gomail-1", records.PASSED, tokens=4464, needs_judge=True,
                 ledger=judge_ledger()),
        ])
        text = scoring.render(scoring.score(run_dir))

    assert "AGENT" in text and "JUDGE" in text
    assert "USD: none" in text
    assert "z.ai publishes no rate" in text
    # The agent's token count must never appear inside a dollar figure.
    assert "$" not in text.split("AGENT")[1].split("JUDGE")[0]
