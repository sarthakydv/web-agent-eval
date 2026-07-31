"""Are the replica hosts actually up, right now, before a run commits to them?

docs/DECISIONS.md entry 5 recorded that `evals-omnizon.vercel.app` returns
**HTTP 451 / `x-vercel-error: DMCA_TAKEDOWN`**, which is why the population is
102 and not 112. That was measured at planning time. It is not a property of
the benchmark — it is the state of somebody else's hosting on one afternoon.

So it is re-measured before the first task of every real run and **written into
the frozen manifest**. The reason is specific: a host that disappears is
indistinguishable, from inside the run, from an agent that suddenly cannot do
ten tasks. One of those is an exclusion with a reason published beside the rate;
the other is a success rate that is quietly ten points too low. The only thing
that tells them apart is a reachability record taken at a known moment, so this
module takes one and the manifest carries it.

The URLs are read from the installed task configs (`website.url`), not restated
here, for the same reason `manifest.population` derives its counts from them: a
copy is a thing that goes stale in silence.
"""

from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

#: Headers worth keeping when a host refuses. `x-vercel-error` is what named the
#: takedown in entry 5, and `retry-after` distinguishes "gone" from "throttled".
INTERESTING_HEADERS = ("x-vercel-error", "x-vercel-id", "retry-after", "server", "location")

DEFAULT_ATTEMPTS = 3
DEFAULT_TIMEOUT_S = 20.0


def site_urls(version: str = "v1") -> dict[str, str]:
    """`{site_id: url}` for every site the installed task set references."""
    import agisdk
    from agisdk.REAL.browsergym.webclones.task_config import TASKS_BY_VERSION

    tasks_dir = (
        Path(agisdk.__file__).resolve().parent
        / "REAL/browsergym/webclones"
        / version
        / "tasks"
    )
    urls: dict[str, str] = {}
    for name in TASKS_BY_VERSION[version]:
        config = json.loads((tasks_dir / f"{name}.json").read_text())
        website = config["website"]
        urls.setdefault(website["id"], website["url"])
    return dict(sorted(urls.items()))


def _one_request(url: str, *, timeout: float, follow: bool) -> dict:
    """One GET. Returns the status, and never raises for an HTTP status code."""

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    handlers = [] if follow else [_NoRedirect()]
    opener = urllib.request.build_opener(
        *handlers, urllib.request.HTTPSHandler(context=ssl.create_default_context())
    )
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "web-agent-eval/1.0"})
    started = time.monotonic()
    try:
        with opener.open(request, timeout=timeout) as response:
            return {
                "status": response.status,
                "final_url": response.url,
                "headers": {
                    k: v for k, v in ((h, response.headers.get(h)) for h in INTERESTING_HEADERS)
                    if v
                },
                "latency_s": round(time.monotonic() - started, 3),
                "error": None,
            }
    except urllib.error.HTTPError as exc:
        # A 4xx/5xx is an answer, not a failure to reach the host, and its body
        # and headers are exactly what named the takedown in entry 5.
        try:
            body = exc.read().decode("utf-8", "replace")[:200]
        except Exception as read_error:  # noqa: BLE001 — the status is the finding
            body = f"(body unreadable: {type(read_error).__name__})"
        return {
            "status": exc.code,
            "final_url": url,
            "headers": {
                k: v for k, v in ((h, exc.headers.get(h)) for h in INTERESTING_HEADERS) if v
            },
            "body_head": " ".join(body.split())[:200] or None,
            "latency_s": round(time.monotonic() - started, 3),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 — DNS, TLS, timeout: all "not reachable"
        return {
            "status": None,
            "final_url": None,
            "headers": {},
            "latency_s": round(time.monotonic() - started, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }


def probe_site(
    site: str,
    url: str,
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> dict:
    """Probe one host `attempts` times, and follow redirects once at the end.

    Three probes, not one, because entry 5's finding was only trustworthy for
    being three consecutive 451s rather than a blip. `first_status` is recorded
    without following redirects (gocalendar answers 308) and `status` is what
    the browser would end up on.
    """
    raw = [_one_request(url, timeout=timeout, follow=False) for _ in range(attempts)]
    followed = _one_request(url, timeout=timeout, follow=True)
    statuses = [r["status"] for r in raw]
    entry = {
        "site": site,
        "url": url,
        "attempts": attempts,
        "first_statuses": statuses,
        "first_status": statuses[0],
        "status": followed["status"],
        "final_url": followed["final_url"],
        "final_host": urlsplit(followed["final_url"]).hostname if followed["final_url"] else None,
        "headers": followed["headers"] or (raw[0]["headers"] if raw else {}),
        "body_head": followed.get("body_head") or raw[0].get("body_head"),
        "error": followed["error"],
        "latency_s": followed["latency_s"],
    }
    entry["reachable"] = is_reachable(entry)
    entry["consistent"] = len(set(statuses)) == 1
    return entry


def is_reachable(entry: dict) -> bool:
    """Reachable means the host served a page, after redirects, on every probe.

    A 451, a 5xx, a DNS failure and a timeout are all "not reachable". A 308
    that lands on a 200 is reachable, which is what gocalendar does.
    """
    if entry.get("error"):
        return False
    status = entry.get("status")
    if status is None or status >= 400:
        return False
    return all(s is not None and (s < 400 or 300 <= s < 400) for s in entry["first_statuses"])


def probe_all(
    version: str = "v1",
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> list[dict]:
    """Every site the task set uses, probed. Ordered, so two probes diff cleanly."""
    return [
        probe_site(site, url, attempts=attempts, timeout=timeout)
        for site, url in site_urls(version).items()
    ]


def unreachable_sites(entries: list[dict]) -> set[str]:
    """Which sites did not answer. Re-derived rather than trusting the stored flag.

    `probe_site` stores `reachable` for readability, but the verdict is
    recomputed from the statuses here so a hand-edited or older record cannot
    assert a site was up that the recorded statuses say was not.
    """
    return {e["site"] for e in entries if not is_reachable(e)}


def render(entries: list[dict]) -> str:
    lines = []
    for entry in entries:
        mark = "up  " if entry["reachable"] else "DOWN"
        statuses = "/".join(str(s) for s in entry["first_statuses"])
        tail = ""
        if entry["headers"].get("x-vercel-error"):
            tail = f"  {entry['headers']['x-vercel-error']}"
        elif entry["error"]:
            tail = f"  {entry['error'][:60]}"
        lines.append(
            f"  {mark} {entry['site']:14s} {statuses:>11s} -> {entry['status']!s:>4s}"
            f"  {entry['latency_s']:>6.2f}s{tail}"
        )
    return "\n".join(lines)
