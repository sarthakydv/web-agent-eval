"""Loading the committed observation captures.

These are real observations from real runs against the hosted replica sites,
captured by `scripts/capture_observations.py` and committed under
`fixtures/observations/`. They are what the serializer's tests run against, and
they are the reason those tests need no browser.

A serializer tested against a page a human wrote is a test of the page a human
wrote: the DOM snapshot below has 4 800 strings in it and nobody would have
hand-written the parts that broke.
"""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path

FIXTURE_DIR = Path(
    os.environ.get(
        "WEB_AGENT_EVAL_FIXTURES",
        Path(__file__).resolve().parents[2] / "fixtures" / "observations",
    )
)


def fixture_names() -> list[str]:
    return sorted(p.name[: -len(".json.gz")] for p in FIXTURE_DIR.glob("*.json.gz"))


def load_observation(name: str, *, with_screenshot: bool = True) -> dict:
    """Load one captured observation, shaped exactly as browsergym handed it over.

    The screenshot is stored beside the JSON as a PNG and re-attached here as the
    numpy array the observation originally carried, so a caller cannot tell the
    fixture from a live observation.
    """
    path = FIXTURE_DIR / f"{name}.json.gz"
    obs = json.loads(gzip.decompress(path.read_bytes()))
    png = FIXTURE_DIR / f"{name}.png"
    if with_screenshot and png.exists():
        import numpy as np
        from PIL import Image

        with Image.open(png) as image:
            obs["screenshot"] = np.asarray(image.convert("RGB"))
    return obs
