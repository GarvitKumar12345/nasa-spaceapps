"""Stage-1 checks for a candidate moving target (scripts/target_stage1.py) and the honesty of a field without Gaia data.

The diagnostic S/N is tested on a constructed frame against its analytic expectation (known flux in the
3x3 box, known pixel noise, median-background variance). The van Maanen 2 dataset test needs its local
cutout cache and is skipped otherwise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pytest
from fastapi.testclient import TestClient

from skyshift.science import estimator_stress as es

VM2 = "spherex-dr1-vanmaanen2"


@dataclass
class _Flag:
    name: str
    mask_value: int


class _Frame:
    """Just enough of SpectralImage for scripts.target_stage1.frame_checks (a constructed frame, not archive data)."""

    def __init__(self, image, variance, flags, x0, y0):  # noqa: ANN001
        self.image, self.variance, self.flags = image, variance, flags
        self._xy = (x0, y0)
        self.flag_defs = [_Flag("OVERFLOW", 1 << 1), _Flag("SUR_ERROR", 1 << 2), _Flag("NONFUNC", 1 << 6), _Flag("SOURCE", 1 << 21)]
        self.image_header = {"MJD-AVG": 60870.5, "BUNIT": "MJy/sr"}
        self.obs_id, self.detector = "constructed", 1

    @property
    def shape(self):  # noqa: ANN201
        return self.image.shape

    def sky_to_pixel(self, ra, dec):  # noqa: ANN001, ANN201 - the constructed star sits at a fixed pixel
        return self._xy

    def flags_near(self, x0, y0, radius_px):  # noqa: ANN001, ANN201
        ny, nx = self.flags.shape
        yy, xx = np.mgrid[0:ny, 0:nx]
        word = int(np.bitwise_or.reduce(self.flags[(xx - x0) ** 2 + (yy - y0) ** 2 <= radius_px**2]))
        return [d.name for d in self.flag_defs if word & d.mask_value]


@pytest.mark.measurement
def test_diagnostic_snr_matches_its_analytic_expectation_and_flags_make_frames_unusable():
    """[measurement] A Moffat star of known flux in white noise: the 3x3 diagnostic S/N agrees with
    S_box / sqrt(9 sigma^2 + 81 var(median background)) within its sampling scatter; a saturation flag within
    2.5 px or an excluded flag in the core makes the frame unusable whatever its S/N."""
    from scripts.target_stage1 import TARGETS, frame_checks

    rng = np.random.default_rng(4)
    psf = es.moffat(1.15, 3.0)
    x0, y0, flux, sigma, bg = 20.0, 21.0, 2000.0, 1.5, 7.0
    clean = es.pixel_integrated(psf, (41, 41), x0, y0, flux)
    s_box = float(clean[20:23, 19:22].sum())
    yy, xx = np.mgrid[0:41, 0:41]
    r = np.hypot(xx - x0, yy - y0)
    n_ann = int(((r >= 4) & (r <= 7)).sum())
    expected = s_box / math.sqrt(9 * sigma**2 + 81 * (math.pi / 2) * sigma**2 / n_ann)
    got = []
    for _ in range(40):
        img = clean + bg + rng.normal(0, sigma, clean.shape)
        f = frame_checks(_Frame(img, np.full(img.shape, sigma**2), np.zeros(img.shape, np.uint32), x0, y0), TARGETS[VM2])
        assert f["usable"] and f["saturation_flags_within_2p5px"] == [] and f["core_excluded_flags"] == []
        got.append(f["diagnostic_snr_3x3"])
    assert np.mean(got) == pytest.approx(expected, rel=0.03)  # S/N ~ 200: per-frame scatter ~1 %, mean over 40 well below 3 %
    flags = np.zeros((41, 41), np.uint32)
    flags[22, 21] = 1 << 1  # OVERFLOW 1.4 px from the star
    f = frame_checks(_Frame(clean + bg, np.full((41, 41), sigma**2), flags, x0, y0), TARGETS[VM2])
    assert not f["usable"] and f["saturation_flags_within_2p5px"] == ["OVERFLOW"]
    flags[:] = 0
    flags[21, 20] = 1 << 6  # NONFUNC in the core
    f = frame_checks(_Frame(clean + bg, np.full((41, 41), sigma**2), flags, x0, y0), TARGETS[VM2])
    assert not f["usable"] and f["core_excluded_flags"] == ["NONFUNC"]
    flags[21, 20] = 1 << 21  # SOURCE is informational, not excluded
    assert frame_checks(_Frame(clean + bg, np.full((41, 41), sigma**2), flags, x0, y0), TARGETS[VM2])["usable"]


@pytest.fixture(scope="module")
def vm2_bundle():
    from skyshift.providers.spherex import SpherexProvider
    from skyshift.providers.spherex.paths import manifest_path

    if not manifest_path(VM2).exists():
        pytest.skip("no manifest for the van Maanen 2 field")
    b = SpherexProvider().load_dataset(VM2)
    if not b.extras.get("spectral_images"):
        pytest.skip(f"van Maanen 2 cutouts not cached; run: cd backend && uv run python -m skyshift.providers.spherex.fetch --field {VM2} --from-manifest")
    return b


@pytest.mark.archive
def test_vanmaanen2_field_uses_its_verified_gaia_record_and_keeps_target_measurement_unavailable(vm2_bundle):
    """[archive] The van Maanen 2 field: every selected cutout available; every compatibility group spans both seasons;
    the Gaia overlay and alignment use the verified partner-service record (served by the API); the study target is
    never one of its frames' reference stars; target measurement capabilities stay unavailable in the app."""
    from skyshift.api.app import app
    from skyshift.providers.spherex.fields import PRESETS

    ds = vm2_bundle.dataset
    assert ds.origin == "observed" and all(o.status == "available" for o in ds.observations)
    caps = {c.id: c for c in ds.capabilities}
    assert caps["catalog_overlay"].status == caps["alignment_diagnostics"].status == "available"
    for k in ("source_measurement", "photometry", "astrometric_fit", "difference_imaging", "registration"):
        assert caps[k].status == "unavailable"
    assert "target measurements are not" in ds.description
    groups = [b for b in ds.bands if b.compatibility and len(b.compatibility.member_observation_ids) >= 2]
    assert len(groups) == 6
    obs = {o.id: o for o in ds.observations}
    for g in groups:
        dates = sorted(obs[m].timing.mid.iso_utc[:10] for m in g.compatibility.member_observation_ids)
        assert dates[0] < "2025-10-01" <= dates[-1]  # one member in each season
    c = TestClient(app)
    frame = next(f for f in ds.frames if f.kind == "archive_wcs_reprojection")
    ov = c.get(f"/api/datasets/{VM2}/gaia/overlay", params={"frame_id": frame.id})
    assert ov.status_code == 200 and "gaia.ari.uni-heidelberg.de" in (ov.json()["provenance"].get("source_url") or "") + " ".join(ov.json()["notes"])
    rep = c.get(f"/api/datasets/{VM2}/alignment").json()
    target = PRESETS[VM2].study_target.gaia_dr3_source_id
    seen = [r for f in rep["frames"] for r in f["residuals"] if r["source_id"] == target]
    assert seen and all(r["status"] == "rejected" and r["reason"] == "study_target" for r in seen)
    assert all(c.get(f"/api/datasets/{VM2}/{p}").status_code == 409 for p in ("sources", "sources/S001/measurements"))
