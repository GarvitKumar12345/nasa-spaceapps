"""Derive the committed offline SPHEREx test fixture from one cached real DR1 cutout.

    cd backend && uv run python scripts/make_spherex_fixture.py

IMAGE, FLAGS, VARIANCE, ZODI and WCS-WAVE (data and headers) are copied unchanged. The EPSF
table is trimmed to the zones nearest the cutout for repository size; the PRIMARY header
records this (SKYTRIM), the source file name (SKYSRC) and the source sha256 (SKYSHA), so the
fixture is never mistaken for an archive file. Live tests check untrimmed downloads.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path

import numpy as np
from astropy.io import fits

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from skyshift.providers.spherex.paths import FIXTURE_ROOT, cutout_path  # noqa: E402

DATASET = "spherex-dr1-barnard"
KEY = "2025W35_2A_0474_4:D1"
KEEP_ZONES = 4


def main() -> int:
    manifest = json.loads((FIXTURE_ROOT / DATASET / "manifest.json").read_text(encoding="utf-8"))
    entry = next(d for d in manifest["downloads"] if d["key"] == KEY)
    src = cutout_path(DATASET, entry["file_name"])
    data = src.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if sha != entry["sha256"]:
        raise SystemExit(f"cached file {src} does not match the manifest sha256")
    with fits.open(io.BytesIO(data), memmap=False) as hdul:
        img = hdul["IMAGE"].header
        ny, nx = hdul["IMAGE"].data.shape
        cx = (nx - 1) / 2 + 1 - float(img["CRPIX1A"])  # detector 0-based centre of the cutout
        cy = (ny - 1) / 2 + 1 - float(img["CRPIX2A"])
        ep = hdul["EPSF"]
        d2 = (np.asarray(ep.data["XCENTER"]) - cx) ** 2 + (np.asarray(ep.data["YCENTER"]) - cy) ** 2
        keep = np.sort(np.argsort(d2)[:KEEP_ZONES])
        trimmed = fits.BinTableHDU(data=ep.data[keep], header=ep.header.copy())
        prim = hdul[0].copy()
        prim.header["SKYTRIM"] = f"SkyShift fixture: EPSF rows {len(ep.data)}->{KEEP_ZONES} (nearest zones)"
        prim.header["SKYSRC"] = entry["file_name"]  # source cutout (IRSA IBE)
        prim.header["SKYSHA"] = sha  # sha256 of the source cutout bytes
        out = fits.HDUList([prim] + [h.copy() if h.name != "EPSF" else trimmed for h in hdul[1:]])
        dest = FIXTURE_ROOT / DATASET / "fixture_cutout_D1_trimmed_epsf.fits"
        out.writeto(dest, overwrite=True, checksum=False)
    print(f"wrote {dest} ({dest.stat().st_size / 1e3:.0f} kB) from {entry['file_name']}; kept EPSF rows {keep.tolist()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
