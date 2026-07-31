"""feat-006: what the manifest must carry, and what the site rule costs.

Three things this feature added, each tested with the case where it must fire
and the case where it must not (AGENTS.md's standing control rule):

* the reachability record that goes into the frozen manifest, and the reading
  that decides a host is down,
* the refusal to start a real run without one,
* the accounting for entry 7's "no two concurrent episodes on the same site"
  rule, which the pilot's one-task-per-site set never reached.

Offline. `sites.probe_all` is not called against the live hosts here — that is
what `scripts/preflight.py` does before a run, and a test that needed the
network would fail for reasons that are not this project's.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from web_agent_eval import batch, sites
from web_agent_eval import manifest as manifest_module
from web_agent_eval.caps import DEFAULT_MAX_WALL_CLOCK_S

CAPS = {"max_steps": 25, "max_tokens": 400_000, "max_wall_clock_s": DEFAULT_MAX_WALL_CLOCK_S}


def quiet(_msg: str) -> None:
    pass


def entry(**overrides) -> dict:
    base = {
        "site": "dashdish",
        "url": "https://evals-dashdish.vercel.app",
        "attempts": 3,
        "first_statuses": [200, 200, 200],
        "first_status": 200,
        "status": 200,
        "final_url": "https://evals-dashdish.vercel.app/",
        "final_host": "evals-dashdish.vercel.app",
        "headers": {},
        "body_head": None,
        "error": None,
        "latency_s": 0.2,
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------
# reading a probe
# --------------------------------------------------------------------------


def test_a_200_is_reachable_and_a_308_that_lands_on_200_is_too():
    """gocalendar answers 308 and is a working site — entry 5 measured exactly that."""
    assert sites.is_reachable(entry())
    assert sites.is_reachable(entry(site="gocalendar", first_statuses=[308, 308, 308], status=200))


@pytest.mark.parametrize("bad", [
    {"first_statuses": [451, 451, 451], "status": 451,
     "headers": {"x-vercel-error": "DMCA_TAKEDOWN"}},
    {"first_statuses": [503, 503, 503], "status": 503},
    {"first_statuses": [None, None, None], "status": None,
     "error": "URLError: <urlopen error [Errno 8] nodename nor servname provided>"},
])
def test_a_takedown_an_outage_and_a_dns_failure_are_all_unreachable(bad):
    """The control for the test above: 'reachable' must be able to come out false.

    All three are the same conclusion for the run — the tasks on that host
    cannot be attempted — and entry 5's 451 is only one of the ways a replica
    stops answering.
    """
    assert not sites.is_reachable(entry(site="omnizon", **bad))


def test_the_probe_reads_its_urls_from_the_installed_task_set():
    """Not from a copy in this repo. A copy is what goes stale in silence."""
    urls = sites.site_urls()
    assert len(urls) == 11
    assert urls["omnizon"].startswith("https://")
    assert set(urls) == {manifest_module.site_of(t) for t, _ in
                         [(i, None) for i in manifest_module.population("112")[0]]}


# --------------------------------------------------------------------------
# the manifest carries it, frozen
# --------------------------------------------------------------------------


def test_the_manifest_freezes_the_reachability_record_and_the_served_model(tmp_path):
    probe = [entry(), entry(site="omnizon", first_statuses=[451, 451, 451], status=451,
                            headers={"x-vercel-error": "DMCA_TAKEDOWN"})]
    wanted = manifest_module.build(
        "r", population_name="explicit", explicit=["v1.dashdish-1"],
        concurrency=3, caps=CAPS, model="glm-4.6", base_url="https://z/",
        episode_entrypoint="fake_episodes:episode", real_tasks=False,
        site_reachability=probe,
        served_model={"requested": "glm-4.6", "served": "glm-4.6"},
    )
    manifest_module.ensure(tmp_path / "r", wanted)

    reloaded = manifest_module.load(tmp_path / "r")
    assert sites.unreachable_sites(reloaded.site_reachability) == {"omnizon"}
    assert reloaded.served_model["served"] == "glm-4.6"
    # And it survives a round trip through JSON, which is how a run resuming
    # tomorrow will read it.
    on_disk = json.loads((tmp_path / "r" / "manifest.json").read_text())
    assert on_disk["site_reachability"][1]["headers"]["x-vercel-error"] == "DMCA_TAKEDOWN"


def test_a_manifest_written_before_this_feature_still_loads(tmp_path):
    """The control: the new fields are additive, so `feat-004`'s runs still read."""
    run_dir = tmp_path / "old"
    run_dir.mkdir()
    older = {
        "run_id": "old", "created": "2026-07-31T00:00:00+00:00", "population": "explicit",
        "task_ids": ["v1.pass-1"], "exclusions": [], "concurrency": 3, "caps": CAPS,
        "model": "fake", "base_url": "fake://",
        "episode_entrypoint": "fake_episodes:episode", "note": "", "sites": ["pass"],
    }
    (run_dir / "manifest.json").write_text(json.dumps(older))

    reloaded = manifest_module.load(run_dir)
    assert reloaded.site_reachability == []
    assert reloaded.served_model == {}


def test_run_batch_refuses_a_real_run_with_no_reachability_record(tmp_path, monkeypatch):
    """A real run without a probe is a run that cannot tell a dead host from a
    failing agent. It is refused rather than started and explained afterwards."""
    import subprocess
    import sys

    root = Path(__file__).resolve().parent.parent
    run_dir = tmp_path / "noprobe"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(json.dumps({
        "run_id": "noprobe", "created": "2026-07-31T00:00:00+00:00", "population": "explicit",
        "task_ids": ["v1.dashdish-1"], "exclusions": [], "concurrency": 1, "caps": CAPS,
        "model": "glm-4.6", "base_url": "https://z/",
        "episode_entrypoint": "web_agent_eval.batch:real_episode", "note": "",
        "sites": ["dashdish"],
    }))

    completed = subprocess.run(
        [sys.executable, str(root / "scripts" / "run_batch.py"),
         "--run-id", "noprobe", "--runs-dir", str(tmp_path),
         "--population", "explicit", "--tasks", "v1.dashdish-1", "--concurrency", "1"],
        cwd=root, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 1
    assert "no site reachability record" in completed.stderr
    assert "preflight" in completed.stderr
    # Nothing was attempted: the refusal happens before the first browser.
    assert not (run_dir / "records").exists()


# --------------------------------------------------------------------------
# what the site rule costs
# --------------------------------------------------------------------------


def make_run(tmp_path: Path, task_ids: list[str], *, concurrency: int):
    run_dir = tmp_path / "t"
    wanted = manifest_module.build(
        "t", population_name="explicit", explicit=task_ids, concurrency=concurrency,
        caps=CAPS, model="fake", base_url="fake://",
        episode_entrypoint="fake_episodes:episode", real_tasks=False,
    )
    return run_dir, manifest_module.ensure(run_dir, wanted)


def test_the_site_rule_is_exercised_and_its_cost_is_recorded(tmp_path, monkeypatch):
    """Three slow tasks on one site, three workers: the rule must bind and bill.

    This is the case the pilot never reached — its ten tasks were one per site,
    so entry 7's rule was never actually engaged. Here two of three slots sit
    idle for the length of an episode, and the round must say so rather than
    reporting a concurrency of 3 it never had.
    """
    monkeypatch.setenv("WAE_FAKE_SLOW_S", "1.0")
    run_dir, manifest = make_run(tmp_path, ["v1.slow-1", "v1.slow-2", "v1.slow-3"],
                                 concurrency=3)

    result = batch.run_round(run_dir, manifest, round_index=1, log=quiet)

    assert len(result.new_terminal) == 3
    assert result.site_blocked_events >= 1, "the site rule never engaged"
    assert result.site_idle_slot_s > 1.0, "idle worker slots were not billed to the rule"
    payload = result.to_dict()["site_constraint"]
    assert payload["idle_fraction"] > 0
    assert payload["slot_s_available"] >= payload["idle_slot_s"]


def test_the_site_rule_costs_nothing_when_the_sites_differ(tmp_path, monkeypatch):
    """The control. Without it, an accounting that always bills something — or a
    rule that quietly serialised the whole run — would pass the test above."""
    monkeypatch.setenv("WAE_FAKE_SLOW_S", "1.0")
    run_dir, manifest = make_run(tmp_path, ["v1.pass-1", "v1.fail-1", "v1.capsteps-1"],
                                 concurrency=3)

    result = batch.run_round(run_dir, manifest, round_index=1, log=quiet)

    assert len(result.new_terminal) == 3
    assert result.site_blocked_events == 0
    assert result.site_idle_slot_s == 0.0


def test_a_launch_that_steps_over_a_busy_site_is_counted(tmp_path, monkeypatch):
    """The reorder counter: two slots, two same-site tasks queued ahead of a third.

    `v1.slow-1` launches, `v1.slow-2` cannot, so the scheduler steps over it to
    reach `v1.pass-1`. That reordering is the rule working, and over 102 tasks
    on 10 sites it is what happens on nearly every launch.
    """
    monkeypatch.setenv("WAE_FAKE_SLOW_S", "1.0")
    run_dir, manifest = make_run(tmp_path, ["v1.slow-1", "v1.slow-2", "v1.pass-1"],
                                 concurrency=2)

    result = batch.run_round(run_dir, manifest, round_index=1, log=quiet)

    assert len(result.new_terminal) == 3
    assert result.site_reorders >= 1
    assert result.site_tasks_passed_over >= 1
