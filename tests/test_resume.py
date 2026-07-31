"""feat-004: the runner resumes, and never re-runs or re-labels a finished task.

Everything here runs offline against `fake_episodes` — real worker processes,
real atomic writes, real `results.tsv`, fake episodes. The batch's subject is
what happens *around* an episode, and a browser would make these slow and flaky
without testing any of it.

Each rule is tested with the case where it must fire **and** the case where it
must not (AGENTS.md's standing control rule). A resume that skips everything
passes "it re-ran nothing"; a classifier that calls everything a provider error
passes "429 is not a failure". Both are checked from the other side.
"""

from __future__ import annotations

import itertools
import json
import os
import time
from pathlib import Path

import pytest

from web_agent_eval import batch, records
from web_agent_eval import manifest as manifest_module
from web_agent_eval.caps import DEFAULT_MAX_WALL_CLOCK_S

ENTRYPOINT = "fake_episodes:episode"
CAPS = {"max_steps": 25, "max_tokens": 400_000, "max_wall_clock_s": DEFAULT_MAX_WALL_CLOCK_S}


def make_run(tmp_path: Path, task_ids: list[str], *, concurrency: int = 3, run_id: str = "t"):
    run_dir = tmp_path / run_id
    wanted = manifest_module.build(
        run_id,
        population_name="explicit",
        explicit=task_ids,
        concurrency=concurrency,
        caps=CAPS,
        model="fake",
        base_url="fake://",
        episode_entrypoint=ENTRYPOINT,
        real_tasks=False,
    )
    return run_dir, manifest_module.ensure(run_dir, wanted)


def quiet(_msg: str) -> None:
    pass


# --------------------------------------------------------------------------
# resume
# --------------------------------------------------------------------------


def test_resume_skips_terminal_tasks_and_says_how_many(tmp_path):
    tasks = ["v1.pass-1", "v1.pass-2", "v1.fail-1"]
    run_dir, manifest = make_run(tmp_path, tasks)

    first = batch.run_round(run_dir, manifest, round_index=1, log=quiet)
    assert first.skipped == 0, "a fresh run has skipped nothing — the control case"
    assert sorted(first.attempted) == sorted(tasks)
    assert sorted(first.new_terminal) == sorted(tasks)

    second = batch.run_round(run_dir, manifest, round_index=2, log=quiet)
    assert second.skipped == 3
    assert second.attempted == [], "a terminal task must never be attempted again"
    assert second.pending_at_start == 0


def test_resume_loses_no_recorded_result(tmp_path):
    """Round 2 must not touch what round 1 recorded, byte for byte."""
    tasks = ["v1.pass-1", "v1.quota-1"]
    run_dir, manifest = make_run(tmp_path, tasks)
    batch.run_round(run_dir, manifest, round_index=1, log=quiet)

    record_path = records.records_dir(run_dir) / "v1.pass-1.json"
    before = record_path.read_bytes()
    rows_before = len(records.read_attempts(run_dir))

    batch.run_round(run_dir, manifest, round_index=2, log=quiet)

    assert record_path.read_bytes() == before
    # The pending task was attempted again, so exactly one row was added.
    assert len(records.read_attempts(run_dir)) == rows_before + 1


def test_only_pending_tasks_are_retried(tmp_path):
    tasks = ["v1.pass-1", "v1.quota-1", "v1.quota-2"]
    run_dir, manifest = make_run(tmp_path, tasks)
    batch.run_round(run_dir, manifest, round_index=1, log=quiet)

    second = batch.run_round(run_dir, manifest, round_index=2, log=quiet)
    assert sorted(second.attempted) == ["v1.quota-1", "v1.quota-2"]
    assert second.skipped == 1


def test_one_tasks_failure_never_aborts_the_batch(tmp_path):
    tasks = ["v1.boom-1", "v1.pass-1", "v1.capsteps-1", "v1.fail-1"]
    run_dir, manifest = make_run(tmp_path, tasks)
    result = batch.run_round(run_dir, manifest, round_index=1, log=quiet)
    assert len(result.new_terminal) == 4
    assert result.statuses == {"errored": 1, "passed": 1, "capped": 1, "failed": 1}


def test_a_worker_that_dies_without_reporting_leaves_the_task_pending(tmp_path):
    """What a SIGKILL leaves behind: an attempt row, no record, still pending."""
    run_dir, manifest = make_run(tmp_path, ["v1.die-1", "v1.pass-1"])
    result = batch.run_round(run_dir, manifest, round_index=1, log=quiet)

    assert result.statuses.get(records.WORKER_DIED) == 1
    assert "v1.die-1" not in records.terminal_task_ids(run_dir)
    assert "v1.pass-1" in records.terminal_task_ids(run_dir)
    rows = [r for r in records.read_attempts(run_dir) if r["task_id"] == "v1.die-1"]
    assert [r["status"] for r in rows] == [records.WORKER_DIED]
    assert rows[0]["terminal"] == "false"


# --------------------------------------------------------------------------
# a provider error is not a task failure
# --------------------------------------------------------------------------


def test_provider_error_is_not_terminal_and_writes_no_record(tmp_path):
    run_dir, manifest = make_run(tmp_path, ["v1.quota-1"])
    result = batch.run_round(run_dir, manifest, round_index=1, log=quiet)

    assert result.statuses == {records.PROVIDER_ERROR: 1}
    assert result.new_terminal == []
    assert records.terminal_task_ids(run_dir) == set()
    assert not records.records_dir(run_dir).exists() or \
        list(records.records_dir(run_dir).glob("*.json")) == []


def test_an_agent_side_error_is_a_task_failure(tmp_path):
    """The control: if everything read as a provider error, nothing would count."""
    run_dir, manifest = make_run(tmp_path, ["v1.boom-1"])
    result = batch.run_round(run_dir, manifest, round_index=1, log=quiet)

    assert result.statuses == {records.ERRORED: 1}
    assert result.new_terminal == ["v1.boom-1"]
    assert "v1.boom-1" in records.terminal_task_ids(run_dir)


@pytest.mark.parametrize("error,expected", [
    ({"type": "RateLimitError", "message": "Error code: 429"}, True),
    ({"type": "APIConnectionError", "message": "Connection error."}, True),
    ({"type": "AuthenticationError", "message": "token expired or incorrect"}, True),
    ({"type": "RuntimeError",
      "message": "Error code: 429 - {'error': {'code': '1113', 'message': "
                 "'Insufficient balance or no resource package.'}}"}, True),
    ({"type": "RuntimeError", "message": "concurrency limit exceeded"}, True),
    # ...and the ones that are this project's problem, not z.ai's:
    ({"type": "PolicyProducedNoAction", "message": "policy returned no action"}, False),
    ({"type": "BadRequestError", "message": "invalid max_tokens"}, False),
    ({"type": "PlaywrightTimeoutError", "message": "waiting for selector"}, False),
    ({"type": "ValueError", "message": "Received a multi-action"}, False),
    (None, False),
])
def test_provider_error_classification_both_ways(error, expected):
    assert records.is_provider_error(error) is expected


def test_classify_maps_outcomes_to_entry_sevens_four_terminal_statuses():
    assert records.classify({"outcome": "completed", "reward": 1.0}) == records.PASSED
    assert records.classify({"outcome": "completed", "reward": 0.0}) == records.FAILED
    assert records.classify({"outcome": "completed", "reward": None}) == records.FAILED
    assert records.classify({"outcome": "capped", "cap": {"cap": "steps"}}) == records.CAPPED
    assert records.classify(
        {"outcome": "errored", "error": {"type": "ValueError", "message": "x"}}
    ) == records.ERRORED
    assert records.classify(
        {"outcome": "errored", "error": {"type": "RateLimitError", "message": "429"}}
    ) == records.PROVIDER_ERROR


def test_a_non_terminal_status_can_never_be_written_as_a_record(tmp_path):
    with pytest.raises(ValueError, match="only"):
        records.write_terminal_record(tmp_path, "v1.quota-1", {"status": records.PROVIDER_ERROR})
    records.write_terminal_record(tmp_path, "v1.pass-1", {"status": records.PASSED})
    assert (records.records_dir(tmp_path) / "v1.pass-1.json").exists()


# --------------------------------------------------------------------------
# the attempt log
# --------------------------------------------------------------------------


def test_results_tsv_holds_one_row_per_attempt_with_retries_visible(tmp_path):
    run_dir, manifest = make_run(tmp_path, ["v1.flaky-1", "v1.pass-1"])
    batch.run_round(run_dir, manifest, round_index=1, log=quiet)
    batch.run_round(run_dir, manifest, round_index=2, log=quiet)

    rows = records.read_attempts(run_dir)
    flaky = [r for r in rows if r["task_id"] == "v1.flaky-1"]
    assert [r["status"] for r in flaky] == [records.PROVIDER_ERROR, records.PASSED]
    assert [r["attempt"] for r in flaky] == ["1", "2"]
    assert [r["round"] for r in flaky] == ["1", "2"]
    assert [r["terminal"] for r in flaky] == ["false", "true"]
    # The passing task was attempted once and never re-rolled.
    assert len([r for r in rows if r["task_id"] == "v1.pass-1"]) == 1
    assert records.results_path(run_dir).read_text().splitlines()[0].split("\t") == \
        list(records.COLUMNS)


def test_the_rate_reads_the_first_terminal_attempt_not_the_last(tmp_path):
    """Retries survive interruptions; they do not re-roll a task until it passes."""
    run_dir, _ = make_run(tmp_path, ["v1.fail-1"])
    for attempt, status in enumerate([records.FAILED, records.PASSED], start=1):
        records.append_attempt(run_dir, records.Attempt(
            run_id="t", round=attempt, attempt=attempt, task_id="v1.fail-1",
            site="fail", status=status, reward=0.0 if status == records.FAILED else 1.0,
        ))
    summary = records.summarise(run_dir, ["v1.fail-1"])
    assert summary["counts"] == {records.FAILED: 1}
    assert summary["passed"] == 0


def test_attempt_rows_survive_a_truncated_write(tmp_path):
    run_dir, _ = make_run(tmp_path, ["v1.pass-1"])
    records.append_attempt(run_dir, records.Attempt(
        run_id="t", round=1, attempt=1, task_id="v1.pass-1", site="pass",
        status=records.PASSED, reward=1.0, tokens=10,
    ))
    with open(records.results_path(run_dir), "a") as handle:
        handle.write("2026-07-31T00:00:00+00:00\tt\t1\t1\tv1.half-1\thalf")  # killed mid-row
    rows = records.read_attempts(run_dir)
    assert [r["task_id"] for r in rows] == ["v1.pass-1"], "a half row is not a result"


# --------------------------------------------------------------------------
# the frozen manifest
# --------------------------------------------------------------------------


def test_the_manifest_is_written_before_the_first_task_and_never_edited(tmp_path):
    run_dir, manifest = make_run(tmp_path, ["v1.pass-1"])
    path = run_dir / manifest_module.MANIFEST_NAME
    assert path.exists()
    before = path.read_bytes()
    batch.run_round(run_dir, manifest, round_index=1, log=quiet)
    assert path.read_bytes() == before


def test_a_resume_that_changes_the_population_is_refused(tmp_path):
    run_dir, _ = make_run(tmp_path, ["v1.pass-1", "v1.pass-2"])
    same = manifest_module.build(
        "t", population_name="explicit", explicit=["v1.pass-1", "v1.pass-2"],
        concurrency=3, caps=CAPS, model="fake", base_url="fake://",
        episode_entrypoint=ENTRYPOINT, real_tasks=False,
    )
    assert manifest_module.ensure(run_dir, same).size == 2, "the control: same run, allowed"

    dropped = manifest_module.build(
        "t", population_name="explicit", explicit=["v1.pass-1"],
        concurrency=3, caps=CAPS, model="fake", base_url="fake://",
        episode_entrypoint=ENTRYPOINT, real_tasks=False,
    )
    with pytest.raises(manifest_module.ManifestFrozen, match="task_ids"):
        manifest_module.ensure(run_dir, dropped)

    looser = manifest_module.build(
        "t", population_name="explicit", explicit=["v1.pass-1", "v1.pass-2"],
        concurrency=3, caps={**CAPS, "max_steps": 100}, model="fake",
        base_url="fake://", episode_entrypoint=ENTRYPOINT, real_tasks=False,
    )
    with pytest.raises(manifest_module.ManifestFrozen, match="caps"):
        manifest_module.ensure(run_dir, looser)


def test_the_three_populations_are_the_ones_entry_five_measured():
    for name, size in (("112", 112), ("102", 102), ("47", 47)):
        tasks, exclusions = manifest_module.population(name)
        assert len(tasks) == size
        assert len(tasks) + len(exclusions) == 112
    _, excluded_102 = manifest_module.population("102")
    assert {e["task_id"].split(".")[1].rsplit("-", 1)[0] for e in excluded_102} == {"omnizon"}
    assert all("451" in e["reason"] for e in excluded_102)
    _, excluded_47 = manifest_module.population("47")
    assert sum("llm_boolean" in e["reason"] for e in excluded_47) == 55


def test_a_typo_in_an_explicit_task_list_is_caught_before_any_browser_starts():
    with pytest.raises(ValueError, match="not REAL v1 tasks"):
        manifest_module.population("explicit", ["v1.gomail-2", "v1.gomial-3"])
    tasks, _ = manifest_module.population("explicit", ["v1.gomail-2"])
    assert tasks == ["v1.gomail-2"], "the control: a real id is accepted"


# --------------------------------------------------------------------------
# concurrency, sites, and retiring a wedged process
# --------------------------------------------------------------------------


def test_no_two_concurrent_episodes_on_the_same_site(tmp_path, monkeypatch):
    """REAL scores by diffing state; two episodes on one host contaminate both."""
    log = tmp_path / "windows.tsv"
    monkeypatch.setenv("WAE_FAKE_LOG", str(log))
    monkeypatch.setenv("WAE_FAKE_SLOW_S", "1.0")
    tasks = ["v1.slow-1", "v1.slow-2", "v1.slow-3"]
    run_dir, manifest = make_run(tmp_path, tasks, concurrency=3)

    batch.run_round(run_dir, manifest, round_index=1, log=quiet)

    windows = [line.split("\t") for line in log.read_text().splitlines()]
    assert len(windows) == 3
    spans = sorted((float(w[2]), float(w[3])) for w in windows)
    for (_, first_end), (second_start, _) in itertools.pairwise(spans):
        assert second_start >= first_end - 0.05, \
            "two episodes overlapped on one site — their state diffs are not independent"


def test_different_sites_do_run_concurrently(tmp_path, monkeypatch):
    """The control: the site rule must not have quietly serialised the whole run."""
    log = tmp_path / "windows.tsv"
    monkeypatch.setenv("WAE_FAKE_LOG", str(log))
    monkeypatch.setenv("WAE_FAKE_SLOW_S", "0.0")
    tasks = ["v1.pass-1", "v1.fail-1", "v1.capsteps-1"]
    run_dir, manifest = make_run(tmp_path, tasks, concurrency=3)

    started = time.monotonic()
    result = batch.run_round(run_dir, manifest, round_index=1, log=quiet)
    elapsed = time.monotonic() - started

    assert len(result.new_terminal) == 3
    windows = [line.split("\t") for line in log.read_text().splitlines()]
    assert len({w[1] for w in windows}) == 3
    # Three spawned interpreters in the time three sequential ones could not run.
    assert elapsed < 60


def test_a_wall_clock_capped_worker_is_killed_and_never_reused(tmp_path):
    """The rule this feature was told to add, and the reason it is not optional.

    A wall-clock cap fires by abandoning the episode's worker thread — Python
    cannot kill a thread — and the abandoned thread may still be driving a
    browser. `v1.wedge-1` reproduces that exactly: it returns a wall-clock cap
    with a live non-daemon thread behind it, which would keep its process alive
    for an hour at exit. If the parent did not retire the process, this test
    would not finish.
    """
    run_dir, manifest = make_run(tmp_path, ["v1.wedge-1", "v1.pass-1"], concurrency=2)

    started = time.monotonic()
    result = batch.run_round(run_dir, manifest, round_index=1, log=quiet)
    elapsed = time.monotonic() - started

    assert elapsed < 60, f"the round took {elapsed:.0f}s — the wedged worker was waited on"
    retired = [r for r in result.retired if r["task_id"] == "v1.wedge-1"]
    assert retired and retired[0]["killed"] is True
    assert "abandoned" in retired[0]["reason"]
    # A cap is still a terminal result, scored and published separately.
    assert result.statuses[records.CAPPED] == 1
    record = json.loads((records.records_dir(run_dir) / "v1.wedge-1.json").read_text())
    assert record["cap"] == "wall_clock"

    # The control: a worker that ended normally exits on its own and is not killed.
    assert [r for r in result.retired if r["task_id"] == "v1.pass-1"] == []


def test_a_provider_error_halves_concurrency_and_recovery_is_slow(tmp_path):
    tasks = [f"v1.quota-{i}" for i in range(1, 3)] + [f"v1.pass-{i}" for i in range(1, 8)]
    run_dir, manifest = make_run(tmp_path, tasks, concurrency=4)
    result = batch.run_round(run_dir, manifest, round_index=1, log=quiet)

    assert result.concurrency_start == 4
    assert result.provider_errors == 2
    # Halved at least once, and never recovered by more than one worker per five
    # clean episodes — so it cannot be back at 4 after seven of them.
    assert 1 <= result.concurrency_end <= 3


def test_the_manifest_records_the_concurrency_the_run_was_executed_at(tmp_path):
    run_dir, _manifest = make_run(tmp_path, ["v1.pass-1"], concurrency=2)
    on_disk = json.loads((run_dir / manifest_module.MANIFEST_NAME).read_text())
    assert on_disk["concurrency"] == 2
    assert "not comparable to sequential" in on_disk["note"]


def test_site_of_handles_hyphenated_site_names():
    assert manifest_module.site_of("v1.fly-unified-2") == "fly-unified"
    assert manifest_module.site_of("v1.gomail-2") == "gomail"


# --------------------------------------------------------------------------
# budgets
# --------------------------------------------------------------------------


def test_a_budget_stops_the_run_and_leaves_terminal_records_intact(tmp_path, monkeypatch):
    monkeypatch.setenv("WAE_FAKE_FAT_TOKENS", "40000")
    tasks = [f"v1.fat-{i}" for i in range(1, 7)]
    run_dir, manifest = make_run(tmp_path, tasks, concurrency=1)

    result = batch.run_round(
        run_dir, manifest, round_index=1,
        budget=batch.Budget(tokens=100_000), log=quiet,
    )

    assert result.budget_stop and "token budget exceeded" in result.budget_stop
    done = records.terminal_task_ids(run_dir)
    assert 0 < len(done) < len(tasks), "it must stop mid-run, not before or after it"
    for task_id in done:
        payload = json.loads((records.records_dir(run_dir) / f"{task_id}.json").read_text())
        assert payload["status"] == records.PASSED
        assert payload["tokens"] == 40000


def test_a_budget_the_run_can_meet_does_not_fire(tmp_path, monkeypatch):
    """The control: a runner that always exits on budget would pass the test above."""
    monkeypatch.setenv("WAE_FAKE_FAT_TOKENS", "1000")
    tasks = [f"v1.fat-{i}" for i in range(1, 4)]
    run_dir, manifest = make_run(tmp_path, tasks, concurrency=3)
    result = batch.run_round(
        run_dir, manifest, round_index=1,
        budget=batch.Budget(tokens=1_000_000, wall_clock_s=3600), log=quiet,
    )
    assert result.budget_stop is None
    assert len(result.new_terminal) == 3


def test_the_wall_clock_budget_is_measured_from_the_runs_start_not_this_process(tmp_path):
    run_dir, manifest = make_run(tmp_path, ["v1.pass-1", "v1.pass-2"])
    result = batch.run_round(
        run_dir, manifest, round_index=1,
        budget=batch.Budget(wall_clock_s=60),
        run_started=time.monotonic() - 3600,  # the run began an hour ago
        log=quiet,
    )
    assert result.budget_stop and "wall-clock budget exceeded" in result.budget_stop
    assert result.attempted == [], "nothing may be launched past the run's budget"


# --------------------------------------------------------------------------
# atomicity
# --------------------------------------------------------------------------


def test_a_record_is_written_whole_or_not_at_all(tmp_path):
    payload = {"status": records.PASSED, "reward": 1.0, "steps": 3, "tokens": 10}
    path = records.write_terminal_record(tmp_path, "v1.pass-1", payload)
    assert json.loads(path.read_text())["reward"] == 1.0
    # os.replace leaves no partial file behind and no temp file lying around.
    assert list(records.records_dir(tmp_path).glob(".*tmp*")) == []
    assert os.path.getsize(path) > 0
