"""The frozen manifest: which tasks a run attempts, and what it excluded.

`runs/<run-id>/manifest.json` is written **before the first task and never
edited** (docs/DECISIONS.md entry 7). It names the task ids, the population they
were drawn from, every exclusion with its reason, and the settings the run was
executed under.

The rule exists because of one specific way a self-supervising run manufactures
a wrong number: **a denominator that emerges from which tasks happened to fail
is not a denominator.** If the runner could drop a task from the manifest after
seeing it error, the published rate would be computed over the tasks that went
well. So the manifest is written first and this module refuses to change it —
a resume with different arguments is an error, loudly, rather than a quietly
different experiment sharing a run id.

Entry 5 leaves three defensible populations and the choice belongs to
`feat-006`, not to the runner:

    112  the full v1 set
    102  reachable — excludes the 10 omnizon tasks (HTTP 451, DMCA takedown)
     47  reachable *and* scorable with no key but z.ai's — the other 55 have at
         least one `llm_boolean` eval, which agisdk grades with an OpenAI judge

The counts are not hardcoded here. They are derived from the installed task
configs every time a manifest is written, so a set that changes under the
project is caught rather than assumed.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

MANIFEST_NAME = "manifest.json"

#: The site whose replica is gone. Entry 5: three consecutive probes returned
#: HTTP 451 with `x-vercel-error: DMCA_TAKEDOWN`.
UNREACHABLE_SITES = {"omnizon"}
UNREACHABLE_REASON = "site returns HTTP 451 (x-vercel-error: DMCA_TAKEDOWN) — DECISIONS entry 5"

#: agisdk grades `llm_boolean` evals with an OpenAI judge it hardcodes to
#: gpt-4.1 (entry 4). Without that key those tasks cannot be scored at all.
JUDGE_EVAL_TYPE = "llm_boolean"
JUDGE_REASON = (
    "has an llm_boolean eval, which agisdk grades with a hardcoded OpenAI judge "
    "(gpt-4.1); not scorable with z.ai's key alone — DECISIONS entries 4 and 5"
)

POPULATIONS = ("112", "102", "47", "explicit")


class ManifestFrozen(RuntimeError):
    """A run's manifest already exists and the arguments do not match it."""


def _task_table(version: str = "v1") -> list[tuple[str, str, list[str]]]:
    """(task_id, site, eval types) for every task in `version`, from agisdk itself."""
    import agisdk
    from agisdk.REAL.browsergym.webclones.task_config import TASKS_BY_VERSION

    tasks_dir = Path(agisdk.__file__).resolve().parent / "REAL/browsergym/webclones" / version / "tasks"
    table = []
    for name in TASKS_BY_VERSION[version]:
        config = json.loads((tasks_dir / f"{name}.json").read_text())
        table.append((
            f"{version}.{name}",
            config["website"]["id"],
            [e.get("type") for e in config.get("evals", [])],
        ))
    return table


def site_of(task_id: str) -> str:
    """`v1.fly-unified-2` -> `fly-unified`.

    Used to keep two concurrent episodes off the same site (entry 7): REAL
    scores by diffing environment state, and if the replica holds that state
    server-side and shared, two episodes on one host contaminate each other's
    diff and the score is silently wrong.
    """
    name = task_id.split(".", 1)[1] if "." in task_id else task_id
    return name.rsplit("-", 1)[0]


def population(
    name: str, explicit: list[str] | None = None, *, real_tasks: bool = True
) -> tuple[list[str], list[dict]]:
    """The task ids in `name`, and the exclusions that produced them.

    `real_tasks=False` is for a run driven by something other than a real REAL
    episode — `feat-004`'s own tests run fake episodes whose ids encode how they
    misbehave. Only an explicit task list may do that, and the manifest still
    records exactly which ids were run.
    """
    if name not in POPULATIONS:
        raise ValueError(f"population must be one of {POPULATIONS}, got {name!r}")

    if name == "explicit" and not real_tasks:
        if not explicit:
            raise ValueError("population 'explicit' needs a task list")
        return list(dict.fromkeys(explicit)), [{
            "task_id": "*",
            "reason": "run over an explicit task list not drawn from REAL's v1 set "
                      "(a non-default --entrypoint); no REAL population applies",
        }]

    table = _task_table()

    if name == "explicit":
        if not explicit:
            raise ValueError("population 'explicit' needs a task list")
        known = {t[0] for t in table}
        unknown = [t for t in explicit if t not in known]
        if unknown:
            raise ValueError(f"not REAL v1 tasks: {unknown}")
        chosen = list(dict.fromkeys(explicit))
        excluded = [
            {"task_id": t[0], "reason": "not in the explicit --tasks list for this run"}
            for t in table if t[0] not in set(chosen)
        ]
        return chosen, excluded

    chosen: list[str] = []
    excluded: list[dict] = []
    for task_id, site, evals in table:
        if name in ("102", "47") and site in UNREACHABLE_SITES:
            excluded.append({"task_id": task_id, "reason": UNREACHABLE_REASON})
            continue
        if name == "47" and JUDGE_EVAL_TYPE in evals:
            excluded.append({"task_id": task_id, "reason": JUDGE_REASON})
            continue
        chosen.append(task_id)

    expected = int(name)
    if len(chosen) != expected:
        raise RuntimeError(
            f"population '{name}' should hold {expected} tasks but the installed task set "
            f"yields {len(chosen)}. The set changed under the project — say so rather than "
            f"publishing a denominator that no longer means what entry 5 measured."
        )
    return chosen, excluded


@dataclass(frozen=True)
class Manifest:
    """What the run is, fixed before the first task runs."""

    run_id: str
    created: str
    population: str
    task_ids: list[str]
    exclusions: list[dict]
    concurrency: int
    caps: dict
    model: str
    base_url: str
    episode_entrypoint: str
    #: Per entry 7: per-task wall clock at N=3 is not comparable to sequential,
    #: so any timing number read out of this run carries the level it ran at.
    note: str = ""
    sites: list[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.task_ids)

    def to_dict(self) -> dict:
        return asdict(self)

    #: The fields a resume may not silently differ on. Task ids and population
    #: decide the denominator; caps decide what the numbers mean.
    FROZEN = ("population", "task_ids", "caps", "episode_entrypoint", "model")

    def conflicts_with(self, other: Manifest) -> list[str]:
        return [
            f"{k}: manifest has {getattr(self, k)!r}, this invocation asked for {getattr(other, k)!r}"
            for k in self.FROZEN
            if getattr(self, k) != getattr(other, k)
        ]


def build(
    run_id: str,
    *,
    population_name: str,
    explicit: list[str] | None = None,
    concurrency: int,
    caps: dict,
    model: str,
    base_url: str,
    episode_entrypoint: str,
    note: str = "",
    real_tasks: bool = True,
) -> Manifest:
    task_ids, exclusions = population(population_name, explicit, real_tasks=real_tasks)
    # Entry 7: per-task wall clock at N>1 is not comparable to sequential, so
    # the caveat travels with the manifest rather than with whoever wrote the
    # command line.
    note = note or (f"concurrency {concurrency}; per-task wall clock at N>1 is not "
                    f"comparable to sequential (DECISIONS entry 7)")
    return Manifest(
        run_id=run_id,
        created=datetime.now(UTC).isoformat(timespec="seconds"),
        population=population_name,
        task_ids=task_ids,
        exclusions=exclusions,
        concurrency=concurrency,
        caps=caps,
        model=model,
        base_url=base_url,
        episode_entrypoint=episode_entrypoint,
        note=note,
        sites=sorted({site_of(t) for t in task_ids}),
    )


def load(run_dir: Path) -> Manifest:
    data = json.loads((Path(run_dir) / MANIFEST_NAME).read_text())
    return Manifest(**data)


def ensure(run_dir: Path, wanted: Manifest) -> Manifest:
    """Write the manifest if this run is new; otherwise check `wanted` against it.

    Never edits an existing manifest. A resume that asks for a different
    population, task set, caps, model or entrypoint is refused — those are the
    fields that decide what the run's number means, and continuing under a run
    id that already published different ones would make the record wrong.
    """
    run_dir = Path(run_dir)
    path = run_dir / MANIFEST_NAME
    if path.exists():
        existing = load(run_dir)
        conflicts = existing.conflicts_with(wanted)
        if conflicts:
            raise ManifestFrozen(
                f"run '{existing.run_id}' was started with a different definition and a "
                f"manifest is never edited (DECISIONS entry 7):\n  " + "\n  ".join(conflicts)
            )
        return existing

    run_dir.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(wanted.to_dict(), indent=2))
    os.replace(tmp, path)
    return wanted
