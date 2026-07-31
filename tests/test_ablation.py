"""feat-007: what makes two runs comparable, and what must refuse when they are not.

The whole feature is two subtractions between two runs. A subtraction is only
worth printing if the runs differ in exactly one thing, so the checks that
establish that are the feature — more than the arithmetic is. Each is tested
both ways, per AGENTS.md's standing rule: the case where it must pass, and the
case where it must fire. A comparability check never seen to refuse would print
a delta for two runs that share nothing.

Three things are covered:

* the richness level is a **frozen manifest field**, so a resume cannot make
  half a run one arm and half the other,
* `scripts/ablation.py arms` refuses two runs that differ in more than the
  level, or in less,
* `scripts/ablation.py cap` refuses a higher-cap run that is not the baseline's
  capped tasks at a higher step cap.

Offline: no browser, no network, no model. Every run here is a directory of
JSON written by the test.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import ablation

from web_agent_eval import cli, records
from web_agent_eval import manifest as manifest_module

CAPS_25 = {"max_steps": 25, "max_tokens": 400_000, "max_wall_clock_s": 300.0}
CAPS_50 = {"max_steps": 50, "max_tokens": 800_000, "max_wall_clock_s": 600.0}


# --------------------------------------------------------------------------
# building a run directory the scorer can read
# --------------------------------------------------------------------------


def write_run(
    tmp_path: Path,
    run_id: str,
    *,
    outcomes: dict[str, str],
    level: str = "lean",
    caps: dict | None = None,
    task_ids: list[str] | None = None,
    steps: dict[str, int] | None = None,
    model: str = "glm-4.6",
    skip_records: tuple[str, ...] = (),
) -> Path:
    """A run directory: a manifest and one terminal record per task."""
    run_dir = tmp_path / run_id
    (run_dir / "records").mkdir(parents=True, exist_ok=True)
    ids = task_ids if task_ids is not None else sorted(outcomes)
    caps = caps or CAPS_25
    (run_dir / "manifest.json").write_text(json.dumps({
        "run_id": run_id,
        "created": "2026-07-31T00:00:00+00:00",
        "population": "explicit",
        "task_ids": ids,
        "exclusions": [],
        "concurrency": 3,
        "caps": caps,
        "model": model,
        "base_url": "https://api.z.ai/api/coding/paas/v4/",
        "episode_entrypoint": "web_agent_eval.batch:real_episode",
        "level": level,
        "note": f"level {level}",
        "sites": [],
        "site_reachability": [],
        "served_model": {},
    }, indent=2))
    for task_id in ids:
        if task_id in skip_records:
            continue
        status = outcomes[task_id]
        records.write_terminal_record(run_dir, task_id, {
            "task_id": task_id,
            "site": manifest_module.site_of(task_id),
            "status": status,
            "reward": 1.0 if status == "passed" else 0.0,
            "steps": (steps or {}).get(task_id, caps["max_steps"] if status == "capped" else 5),
            "tokens": 40_000 if status == "capped" else 10_000,
            "wall_clock_s": 120.0 if status == "capped" else 40.0,
            "cap": "steps" if status == "capped" else None,
            "needs_judge": False,
            "judge": {"calls": [], "evaluate_calls": 0,
                      "tokens": {"prompt": 0, "completion": 0, "cached_prompt": 0}},
            "level_name": level,
        })
    return run_dir


def run_ablation(argv: list[str], capsys) -> tuple[int, str]:
    code = ablation.main(argv)
    captured = capsys.readouterr()
    return code, captured.out + captured.err


# --------------------------------------------------------------------------
# the level is a frozen manifest field
# --------------------------------------------------------------------------


def built(run_id: str, level: str, **overrides) -> manifest_module.Manifest:
    kwargs = {
        "population_name": "explicit",
        "explicit": ["v1.gomail-1", "v1.staynb-2"],
        "concurrency": 3,
        "caps": CAPS_25,
        "model": "glm-4.6",
        "base_url": "https://example.invalid/",
        "episode_entrypoint": "web_agent_eval.batch:real_episode",
        "level": level,
    }
    kwargs.update(overrides)
    return manifest_module.build(run_id, **kwargs)


def test_the_manifest_records_which_arm_the_run_is(tmp_path):
    manifest = manifest_module.ensure(tmp_path / "r", built("r", "rich"))
    assert manifest.level == "rich"
    stored = json.loads((tmp_path / "r" / "manifest.json").read_text())
    assert stored["level"] == "rich", "the arm has to survive to disk, not only in memory"


def test_a_resume_may_not_change_the_arm(tmp_path):
    """The control is the same-level resume: it must still be allowed.

    Without the refusal, `--level rich` on a run started lean would append rich
    episodes to a lean run's records and the arm would be a mixture nothing
    downstream could detect.
    """
    manifest_module.ensure(tmp_path / "r", built("r", "lean"))
    assert manifest_module.ensure(tmp_path / "r", built("r", "lean")).level == "lean", \
        "the control: the same arm resumes"
    with pytest.raises(manifest_module.ManifestFrozen, match="level"):
        manifest_module.ensure(tmp_path / "r", built("r", "rich"))


def test_a_manifest_written_before_the_field_existed_still_resumes(tmp_path):
    """feat-006's runs have no `level` key. They must stay resumable and scorable.

    Entry 7 requires `supervise.py` to be idempotent on a finished run, and a
    freeze that refused every manifest predating the field would have broken
    that for `full102` — the very run `feat-007` compares against.
    """
    run_dir = tmp_path / "legacy"
    manifest_module.ensure(run_dir, built("legacy", "lean"))
    stored = json.loads((run_dir / "manifest.json").read_text())
    del stored["level"]
    (run_dir / "manifest.json").write_text(json.dumps(stored))

    assert manifest_module.load(run_dir).level == "", "an absent field reads as unrecorded"
    assert manifest_module.ensure(run_dir, built("legacy", "rich")).run_id == "legacy"


def test_the_round_takes_its_level_from_the_manifest_not_the_flag(tmp_path):
    manifest = manifest_module.ensure(tmp_path / "r", built("r", "rich"))
    args = argparse.Namespace(level="lean")
    assert cli.level_for(args, manifest) == "rich"

    legacy = manifest_module.build(
        "l", population_name="explicit", explicit=["v1.gomail-1"], concurrency=1,
        caps=CAPS_25, model="m", base_url="u",
        episode_entrypoint="web_agent_eval.batch:real_episode")
    assert cli.level_for(args, legacy) == "lean", \
        "with nothing recorded there is nothing to obey, so the flag stands"


# --------------------------------------------------------------------------
# establishing which arm a run was
# --------------------------------------------------------------------------


def test_a_legacy_runs_arm_is_read_from_its_note():
    assert ablation.level_of({"run_id": "x", "level": "", "note": "concurrency 3, level lean; "
                                                                 "per-task wall clock"}) == "lean"


def test_a_run_that_will_not_say_which_arm_it_was_is_refused():
    """The control for the test above. Guessing 'probably lean' is how an
    ablation ends up comparing a known arm against an assumption."""
    with pytest.raises(ablation.NotComparable, match="does not record"):
        ablation.level_of({"run_id": "x", "level": "", "note": "concurrency 3"})


# --------------------------------------------------------------------------
# the exact test on the discordant pairs
# --------------------------------------------------------------------------


@pytest.mark.parametrize("only_a,only_b,expected", [
    (0, 0, 1.0),        # nothing flipped either way
    (3, 3, 1.0),        # flips balanced exactly
    (5, 0, 0.0625),     # 2 x (1/2)^5
    (10, 0, 0.001953),  # 2 x (1/2)^10
    (8, 1, 0.039062),   # 2 x (1 + 9)/2^9
])
def test_mcnemar_is_exact_and_two_sided(only_a, only_b, expected):
    assert ablation.mcnemar_exact(only_a, only_b) == pytest.approx(expected, abs=1e-6)


def test_mcnemar_is_symmetric():
    assert ablation.mcnemar_exact(7, 2) == ablation.mcnemar_exact(2, 7)


# --------------------------------------------------------------------------
# arms: the ablation
# --------------------------------------------------------------------------


LEAN_OUTCOMES = {
    "v1.gomail-1": "passed",
    "v1.gomail-2": "failed",
    "v1.staynb-1": "capped",
    "v1.staynb-2": "capped",
}
RICH_OUTCOMES = {
    "v1.gomail-1": "passed",   # passed in both
    "v1.gomail-2": "passed",   # only rich
    "v1.staynb-1": "capped",
    "v1.staynb-2": "failed",
}


def test_two_arms_that_differ_only_in_richness_are_compared(tmp_path, capsys):
    write_run(tmp_path, "lean4", outcomes=LEAN_OUTCOMES, level="lean")
    write_run(tmp_path, "rich4", outcomes=RICH_OUTCOMES, level="rich")

    code, out = run_ablation(
        ["--runs-dir", str(tmp_path), "arms", "--a", "lean4", "--b", "rich4"], capsys)

    assert code == 0
    assert "same task_ids           4 ids, identical" in out
    assert "differs: level         'lean' vs 'rich'" in out
    assert "25.00%" in out and "50.00%" in out
    assert "+25.00% (+1 tasks)" in out
    assert "passed in both         1" in out
    assert "only rich              1  v1.gomail-2" in out
    assert "only lean              0  -" in out


def test_arms_refuses_two_runs_at_the_same_richness(tmp_path, capsys):
    """The control: an 'ablation' whose arms are the same level measures nothing."""
    write_run(tmp_path, "a", outcomes=LEAN_OUTCOMES, level="lean")
    write_run(tmp_path, "b", outcomes=RICH_OUTCOMES, level="lean")

    code, out = run_ablation(["--runs-dir", str(tmp_path), "arms", "--a", "a", "--b", "b"], capsys)
    assert code == 1
    assert "both runs are at richness 'lean'" in out


def test_arms_refuses_two_runs_whose_caps_differ(tmp_path, capsys):
    """Entry 7: caps are held constant across arms. If they are not, the delta is
    not attributable to the richness, and the tool must not print one."""
    write_run(tmp_path, "a", outcomes=LEAN_OUTCOMES, level="lean", caps=CAPS_25)
    write_run(tmp_path, "b", outcomes=RICH_OUTCOMES, level="rich", caps=CAPS_50)

    code, out = run_ablation(["--runs-dir", str(tmp_path), "arms", "--a", "a", "--b", "b"], capsys)
    assert code == 1
    assert "caps differs between the two runs" in out


def test_arms_refuses_two_runs_over_different_task_sets(tmp_path, capsys):
    write_run(tmp_path, "a", outcomes=LEAN_OUTCOMES, level="lean")
    smaller = {k: v for k, v in RICH_OUTCOMES.items() if k != "v1.staynb-2"}
    write_run(tmp_path, "b", outcomes=smaller, level="rich")

    code, out = run_ablation(["--runs-dir", str(tmp_path), "arms", "--a", "a", "--b", "b"], capsys)
    assert code == 1
    assert "task_ids differs" in out


def test_arms_will_not_state_a_delta_against_an_unfinished_arm(tmp_path, capsys):
    """A rate over 3 of 4 tasks subtracted from a rate over 4 is not a delta."""
    write_run(tmp_path, "a", outcomes=LEAN_OUTCOMES, level="lean")
    write_run(tmp_path, "b", outcomes=RICH_OUTCOMES, level="rich",
              skip_records=("v1.staynb-2",))

    code, out = run_ablation(["--runs-dir", str(tmp_path), "arms", "--a", "a", "--b", "b"], capsys)
    assert code == 1
    assert "one arm is incomplete" in out


def test_arms_publishes_which_cap_ended_each_arms_episodes(tmp_path, capsys):
    """Two arms whose episodes end on different caps are not bound by the same
    constraint, so the breakdown is printed rather than assumed identical."""
    write_run(tmp_path, "a", outcomes=LEAN_OUTCOMES, level="lean")
    write_run(tmp_path, "b", outcomes=RICH_OUTCOMES, level="rich")
    _code, out = run_ablation(
        ["--runs-dir", str(tmp_path), "arms", "--a", "a", "--b", "b"], capsys)
    assert 'capped by: {"steps": 2}' in out
    assert 'capped by: {"steps": 1}' in out


# --------------------------------------------------------------------------
# cap: the cap-sensitivity measurement
# --------------------------------------------------------------------------


BASE_OUTCOMES = {
    "v1.gomail-1": "passed",
    "v1.gomail-2": "failed",
    "v1.staynb-1": "capped",
    "v1.staynb-2": "capped",
    "v1.udriver-1": "capped",
}
CAPPED_IDS = ["v1.staynb-1", "v1.staynb-2", "v1.udriver-1"]


def higher_run(tmp_path, outcomes, **overrides):
    kwargs = {"level": "lean", "caps": CAPS_50, "task_ids": sorted(outcomes)}
    kwargs.update(overrides)
    return write_run(tmp_path, "cap50", outcomes=outcomes, **kwargs)


def test_the_capped_tasks_rerun_at_a_higher_cap_are_counted(tmp_path, capsys):
    write_run(tmp_path, "base", outcomes=BASE_OUTCOMES, level="lean")
    higher_run(tmp_path, {"v1.staynb-1": "passed", "v1.staynb-2": "capped",
                          "v1.udriver-1": "failed"},
               steps={"v1.staynb-1": 38})

    code, out = run_ablation(
        ["--runs-dir", str(tmp_path), "cap", "--baseline", "base", "--higher", "cap50"], capsys)

    assert code == 0
    assert "differs: max_steps     25 -> 50" in out
    assert "(allowance per step unchanged)" in out
    assert "converted to a pass     1" in out
    assert "still out of steps      1" in out
    assert "staynb-1=38" in out
    # the composite, and its construction — never a substitute for the headline
    assert "1/5 = 20.00%" in out
    assert "(1 + 1)/5 = 2/5 = 40.00%" in out
    assert "does not replace 20.00% at 25 steps" in out


def test_cap_refuses_a_rerun_that_is_not_the_capped_tasks(tmp_path, capsys):
    """The control. A 'cap sensitivity' run over a different task set measures
    the tasks it happened to pick, and the conversion count would be over a
    denominator that no longer means 'the ones that ran out of steps'."""
    write_run(tmp_path, "base", outcomes=BASE_OUTCOMES, level="lean")
    higher_run(tmp_path, {"v1.staynb-1": "passed", "v1.gomail-2": "passed"})

    code, out = run_ablation(
        ["--runs-dir", str(tmp_path), "cap", "--baseline", "base", "--higher", "cap50"], capsys)
    assert code == 1
    assert "not exactly the tasks" in out


def test_cap_refuses_a_rerun_at_the_same_step_cap(tmp_path, capsys):
    write_run(tmp_path, "base", outcomes=BASE_OUTCOMES, level="lean")
    higher_run(tmp_path, dict.fromkeys(CAPPED_IDS, "capped"), caps=CAPS_25)

    code, out = run_ablation(
        ["--runs-dir", str(tmp_path), "cap", "--baseline", "base", "--higher", "cap50"], capsys)
    assert code == 1
    assert "There is no cap sensitivity to measure" in out


def test_cap_refuses_a_rerun_at_a_different_richness(tmp_path, capsys):
    """Otherwise a converted task might have converted because it could see
    more, not because it had more steps."""
    write_run(tmp_path, "base", outcomes=BASE_OUTCOMES, level="lean")
    higher_run(tmp_path, dict.fromkeys(CAPPED_IDS, "passed"), level="rich")

    code, out = run_ablation(
        ["--runs-dir", str(tmp_path), "cap", "--baseline", "base", "--higher", "cap50"], capsys)
    assert code == 1
    assert "richness differs" in out


def test_cap_says_so_when_the_per_step_allowance_changed(tmp_path, capsys):
    """Doubling the steps without doubling the token cap halves what each step
    may spend, and then the token cap can fire before the step cap. The run is
    still reported — but the line must not read as 'only the steps changed'."""
    write_run(tmp_path, "base", outcomes=BASE_OUTCOMES, level="lean")
    higher_run(tmp_path, dict.fromkeys(CAPPED_IDS, "capped"),
               caps={"max_steps": 50, "max_tokens": 400_000, "max_wall_clock_s": 300.0})

    code, out = run_ablation(
        ["--runs-dir", str(tmp_path), "cap", "--baseline", "base", "--higher", "cap50"], capsys)
    assert code == 0
    assert "ALLOWANCE PER STEP CHANGED" in out


def test_cap_reports_tasks_that_did_not_terminalise_rather_than_dropping_them(tmp_path, capsys):
    write_run(tmp_path, "base", outcomes=BASE_OUTCOMES, level="lean")
    higher_run(tmp_path, dict.fromkeys(CAPPED_IDS, "passed"),
               skip_records=("v1.udriver-1",))

    code, out = run_ablation(
        ["--runs-dir", str(tmp_path), "cap", "--baseline", "base", "--higher", "cap50"], capsys)
    assert code == 0
    assert "NOT TERMINAL            1  v1.udriver-1" in out
