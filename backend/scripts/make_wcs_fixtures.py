"""Generate fixtures/wcs/*.json: astropy TAN WCS and gnomonic-projection cases for browser parity tests.

Usage (from backend/): uv run python scripts/make_wcs_fixtures.py
The TypeScript tests (frontend/src/lib/tanwcs.test.ts, tangent.test.ts) compare
their results with these astropy/Python values.
"""

from __future__ import annotations

import json
from pathlib import Path

import astropy
import numpy as np

from skyshift.coords.tangent import offsets_mas
from skyshift.coords.wcs import make_tan_wcs, pixel_to_sky, wcs_to_description

OUT = Path(__file__).resolve().parents[2] / "fixtures" / "wcs"


def tan_cases() -> dict:
    cases = []
    specs = [
        ("generic field", 180.0, 35.0, 0.4, (176, 176), 0.0),
        ("RA wrap near 0", 0.002, 12.0, 0.4, (160, 160), 0.0),
        ("near north pole", 45.0, 89.9, 0.4, (160, 160), 0.0),
        ("south, rotated", 300.0, -62.5, 1.1, (120, 140), 27.0),
    ]
    rng = np.random.default_rng(7)
    for label, ra, dec, scale, shape, rot in specs:
        w = make_tan_wcs(ra, dec, scale, shape, rotation_deg=rot)
        ny, nx = shape
        xs = np.concatenate([[-0.5, nx - 0.5, (nx - 1) / 2], rng.uniform(-0.5, nx - 0.5, 12)])
        ys = np.concatenate([[-0.5, ny - 0.5, (ny - 1) / 2], rng.uniform(-0.5, ny - 0.5, 12)])
        r, d = pixel_to_sky(w, xs, ys)
        cases.append({
            "label": label,
            "wcs": wcs_to_description(w, shape, "common_grid").model_dump(mode="json"),
            "points": [{"x": float(x), "y": float(y), "ra": float(a), "dec": float(b)} for x, y, a, b in zip(xs, ys, r, d, strict=True)],
        })
    return {"generator": "backend/scripts/make_wcs_fixtures.py", "method": "astropy.wcs all_pix2world (origin 0)", "astropy": astropy.__version__,
            "tolerance_note": "TAN is analytic: browser and astropy agree to floating-point round-off (< 1e-6 px, < 1e-4 mas).", "cases": cases}


def tangent_cases() -> dict:
    rng = np.random.default_rng(11)
    cases = []
    for ra0, dec0 in ((180.0, 35.0), (0.0005, -10.0), (250.0, 89.95), (90.0, -89.9)):
        ra = (ra0 + rng.uniform(-0.02, 0.02, 10)) % 360.0
        dec = np.clip(dec0 + rng.uniform(-0.02, 0.02, 10), -90, 90)
        e, n = offsets_mas(ra, dec, ra0, dec0)
        cases.append({"ra0": ra0, "dec0": dec0, "points": [{"ra": float(a), "dec": float(b), "east_mas": float(x), "north_mas": float(y)} for a, b, x, y in zip(ra, dec, e, n, strict=True)]})
    return {"generator": "backend/scripts/make_wcs_fixtures.py", "method": "skyshift.coords.tangent.offsets_mas (gnomonic)", "cases": cases}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "tan_cases.json").write_text(json.dumps(tan_cases(), indent=1) + "\n", encoding="utf-8")
    (OUT / "tangent_cases.json").write_text(json.dumps(tangent_cases(), indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
