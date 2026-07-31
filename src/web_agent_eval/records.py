"""What a run records: terminal records, the attempt log, and what counts as a failure.

Three rules from docs/DECISIONS.md entry 7 live here, and each one closes a way
an unattended run publishes a wrong number.

**A record is written atomically or not at all.** `runs/<run-id>/records/<task>.json`
is written to a temp file and `os.replace`d into place, so a `SIGKILL` landing
mid-write leaves either the old file or the new one — never half of one. A
truncated record read back on resume would be a task that is neither done nor
pending.

**A provider error is not a task failure.** `429`, `401`, an entitlement change
or a connection reset from z.ai says nothing about whether the agent can do the
task. Those get `provider_error`, which is **non-terminal**: no record file is
written, the task stays unattempted, and the supervisor may retry it. The
alternative — recording them as zero-reward failures — is exactly how a run that
met a rate cap publishes a success rate that is really a report on the rate cap.

**Attempts append; the score reads the first terminal attempt.** `results.tsv`
holds one row per *attempt*, retries included, and the row is appended
**before** the terminal record is written. That order is deliberate: a kill in
between leaves an attempt visible with no terminal record, so the task is
retried and nothing is lost. The reverse order could mark a task done with no
trace of the attempt that did it.

Terminal: `passed`, `failed`, `capped`, `errored`.
Non-terminal: `provider_error`, `worker_died`, `aborted`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

PASSED = "passed"
FAILED = "failed"
CAPPED = "capped"
ERRORED = "errored"
PROVIDER_ERROR = "provider_error"
WORKER_DIED = "worker_died"
ABORTED = "aborted"

TERMINAL_STATUSES = (PASSED, FAILED, CAPPED, ERRORED)
NON_TERMINAL_STATUSES = (PROVIDER_ERROR, WORKER_DIED, ABORTED)

RESULTS_NAME = "results.tsv"
RECORDS_DIR = "records"
EPISODES_DIR = "episodes"

COLUMNS = (
    "timestamp", "run_id", "round", "attempt", "task_id", "site", "status",
    "terminal", "reward", "steps", "tokens", "wall_clock_s", "cap",
    "error_type", "note",
)

# --------------------------------------------------------------------------
# is this the provider's fault or the agent's?
# --------------------------------------------------------------------------

#: openai-SDK exception names that mean "the provider did not serve the call".
#: `BadRequestError` is deliberately absent: a malformed request is this
#: project's bug and must not be retried forever as though z.ai were down.
PROVIDER_ERROR_TYPES = frozenset({
    "RateLimitError",
    "AuthenticationError",
    "PermissionDeniedError",
    "APIConnectionError",
    "APITimeoutError",
    "APIConnectionTimeoutError",
    "InternalServerError",
    "APIStatusError",
    "APIError",
    "ConnectionError",
    "ConnectionResetError",
})

#: Substrings that identify a provider refusal even when the type is generic.
#: The first two are entry 4's measured responses on this key, verbatim.
PROVIDER_ERROR_MARKERS = (
    "insufficient balance",              # 429 / code 1113, pay-as-you-go endpoint
    "token expired or incorrect",        # 401, a bad key
    "rate limit",
    "too many requests",
    "concurrency",
    "error code: 429",
    "error code: 401",
    "error code: 503",
    "connection reset",
    "connection error",
    "temporarily unavailable",
    "service unavailable",
)


def is_provider_error(error: dict | None) -> bool:
    """Did z.ai refuse the call, as opposed to the agent failing the task?

    Takes an episode record's `error` dict (`type`, `message`). Anything that
    is not recognisably the provider's is the agent's, because the safe default
    is the one that gets counted honestly: a real task failure recorded as a
    provider error would be retried forever and never counted at all.
    """
    if not error:
        return False
    if (error.get("type") or "") in PROVIDER_ERROR_TYPES:
        return True
    blob = f"{error.get('type', '')}: {error.get('message', '')}".lower()
    return any(marker in blob for marker in PROVIDER_ERROR_MARKERS)


def classify(record: dict) -> str:
    """The status entry 7 fixes, from one episode record.

    `feat-003`'s loop reports `completed`, `capped` or `errored` and hands over
    the reward; it deliberately does not decide `passed`. That decision is here,
    and it is the only place a reward becomes a pass.
    """
    outcome = record.get("outcome")
    if outcome == "errored":
        return PROVIDER_ERROR if is_provider_error(record.get("error")) else ERRORED
    if outcome == "capped":
        return CAPPED
    if outcome == "completed":
        return PASSED if (record.get("reward") or 0) > 0 else FAILED
    # An outcome the loop is not supposed to be able to produce. Recorded as an
    # error rather than guessed at.
    return ERRORED


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATUSES


# --------------------------------------------------------------------------
# the attempt log
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Attempt:
    """One row of `results.tsv` — one attempt at one task."""

    run_id: str
    round: int
    attempt: int
    task_id: str
    site: str
    status: str
    reward: float | None = None
    steps: int | None = None
    tokens: int | None = None
    wall_clock_s: float | None = None
    cap: str | None = None
    error_type: str | None = None
    note: str = ""
    timestamp: str = ""

    def to_row(self) -> str:
        def cell(value) -> str:
            if value is None:
                return ""
            if isinstance(value, float):
                return f"{value:.3f}"
            return str(value).replace("\t", " ").replace("\n", " ")

        stamp = self.timestamp or datetime.now(UTC).isoformat(timespec="seconds")
        values = [
            stamp, self.run_id, self.round, self.attempt, self.task_id, self.site,
            self.status, str(is_terminal(self.status)).lower(), self.reward, self.steps,
            self.tokens, self.wall_clock_s, self.cap, self.error_type, self.note,
        ]
        return "\t".join(cell(v) for v in values) + "\n"


def results_path(run_dir: Path | str) -> Path:
    return Path(run_dir) / RESULTS_NAME


def append_attempt(run_dir: Path | str, attempt: Attempt) -> None:
    """Append one attempt row. Safe from several worker processes at once.

    One `os.write` to a descriptor opened `O_APPEND`: the kernel makes the
    offset-and-write atomic, so concurrent workers cannot interleave halves of
    two rows. The file is opened and closed per row rather than held open,
    because a held buffer is what gets lost when the process is killed.
    """
    path = results_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "" if path.exists() else "\t".join(COLUMNS) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, (header + attempt.to_row()).encode())
        os.fsync(fd)
    finally:
        os.close(fd)


def read_attempts(run_dir: Path | str) -> list[dict]:
    """Every attempt ever made in this run, in the order they were appended."""
    path = results_path(run_dir)
    if not path.exists():
        return []
    lines = path.read_text().splitlines()
    if not lines:
        return []
    header = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        cells = line.split("\t")
        # A row truncated by a kill is dropped rather than half-read; the task
        # it belonged to has no terminal record either, so it is simply retried.
        if len(cells) != len(header):
            continue
        rows.append(dict(zip(header, cells)))
    return rows


def tokens_spent(run_dir: Path | str) -> int:
    """Every token this run has spent, over every attempt including retried ones.

    Read from the attempt log rather than from the terminal records, because a
    provider error and an abandoned attempt cost tokens too and a budget that
    ignored them would be a budget on the tokens that went well.
    """
    total = 0
    for row in read_attempts(run_dir):
        try:
            total += int(row["tokens"] or 0)
        except ValueError:
            continue
    return total


def attempt_number(run_dir: Path | str, task_id: str) -> int:
    """Which attempt at `task_id` the next one is. 1-based."""
    return sum(1 for row in read_attempts(run_dir) if row["task_id"] == task_id) + 1


# --------------------------------------------------------------------------
# terminal records
# --------------------------------------------------------------------------


def records_dir(run_dir: Path | str) -> Path:
    return Path(run_dir) / RECORDS_DIR


def episodes_dir(run_dir: Path | str) -> Path:
    return Path(run_dir) / EPISODES_DIR


def write_terminal_record(run_dir: Path | str, task_id: str, payload: dict) -> Path:
    """Write one terminal record atomically. Only terminal statuses get here.

    The presence of this file **is** what "done" means on resume, so it is
    written last and written whole: temp file in the same directory, flushed,
    then `os.replace`, which is atomic on POSIX.
    """
    status = payload.get("status")
    if not is_terminal(status or ""):
        raise ValueError(
            f"{task_id}: refusing to write a terminal record for status {status!r} — "
            f"only {TERMINAL_STATUSES} are terminal (DECISIONS entry 7)"
        )
    directory = records_dir(run_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{task_id}.json"
    tmp = directory / f".{task_id}.json.tmp{os.getpid()}"
    with open(tmp, "w") as handle:
        json.dump(payload, handle, indent=2, default=str)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    return path


def terminal_records(run_dir: Path | str) -> dict[str, dict]:
    """Every task that is done, and what it recorded. Corrupt files are not done."""
    directory = records_dir(run_dir)
    if not directory.exists():
        return {}
    out: dict[str, dict] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError:
            # Should be impossible given the atomic write, and if it ever
            # happens the honest reading is "not done" rather than "done, with
            # unknown content".
            continue
        out[path.stem] = payload
    return out


def terminal_task_ids(run_dir: Path | str) -> set[str]:
    return set(terminal_records(run_dir))


def summarise(run_dir: Path | str, task_ids: list[str]) -> dict:
    """The run's state: what is done, what each status cost, what is left.

    The rate is computed from each task's **first terminal attempt** (entry 7).
    Retries exist to survive provider errors and interruptions, never to re-roll
    a task until it passes, and reading the last attempt is precisely the bug
    that rule exists to prevent.
    """
    records = terminal_records(run_dir)
    attempts = read_attempts(run_dir)

    first_terminal: dict[str, dict] = {}
    for row in attempts:
        if row["terminal"] == "true" and row["task_id"] not in first_terminal:
            first_terminal[row["task_id"]] = row

    counts: dict[str, int] = {}
    for task_id in task_ids:
        row = first_terminal.get(task_id)
        status = row["status"] if row else (records.get(task_id, {}).get("status") or "pending")
        counts[status] = counts.get(status, 0) + 1

    done = [t for t in task_ids if t in records]
    tokens = 0
    for row in attempts:
        try:
            tokens += int(row["tokens"] or 0)
        except ValueError:
            pass
    passed = counts.get(PASSED, 0)
    scored = sum(counts.get(s, 0) for s in TERMINAL_STATUSES)
    return {
        "tasks": len(task_ids),
        "terminal": len(done),
        "pending": [t for t in task_ids if t not in records],
        "attempts": len(attempts),
        "counts": counts,
        "passed": passed,
        "scored": scored,
        # Stated only over what has actually been scored; the manifest's `n` is
        # what `feat-006` publishes against, and it is not this number.
        "rate_over_scored": (passed / scored) if scored else None,
        "tokens": tokens,
        "provider_errors": sum(
            1 for row in attempts if row["status"] == PROVIDER_ERROR
        ),
    }
