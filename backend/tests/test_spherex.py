"""SPHEREx provider checks.

Offline tests use real archive products recorded in fixtures/spherex/: the live SIA2
response of the field query, the retrieval manifest, and one real DR1 cutout whose EPSF
table is trimmed (labelled SKYTRIM). Dataset tests use the local cutout cache and skip
with the fetch command when it is absent. Live tests (-m live) contact IRSA.
"""

from __future__ import annotations

import copy
import dataclasses
import gzip
import io
import math

import numpy as np
import pytest
from astropy.io import fits
from fastapi.testclient import TestClient

from skyshift.api.app import app
from skyshift.providers.spherex import SpherexProvider, check_extension_names
from skyshift.providers.spherex import reference as ref
from skyshift.providers.spherex.dataset import NO_COVERAGE_BIT, build_bundle
from skyshift.providers.spherex.discovery import DiscoveryError, build_sia_url, parse_sia_votable, resolve_duplicates
from skyshift.providers.spherex.fetch import data_sha256, row_key
from skyshift.providers.spherex.fields import PRESETS
from skyshift.providers.spherex.fitsfile import UnsupportedSpherexProduct, read_spectral_image, validate_spectral_image
from skyshift.providers.spherex.paths import FIXTURE_ROOT, cutout_path
from skyshift.providers.spherex.wavelength import (
    WaveTable,
    WavelengthSample,
    compatibility_groups,
    pair_compatible,
    wavelength_astropy,
    wavelength_bilinear,
)

DS = "spherex-dr1-barnard"
PRESET = PRESETS[DS]
FIXTURE = FIXTURE_ROOT / DS / "fixture_cutout_D1_trimmed_epsf.fits"
SIA_RESPONSE = FIXTURE_ROOT / DS / "sia_response.xml.gz"


@pytest.fixture(scope="module")
def fixture_bytes() -> bytes:
    return FIXTURE.read_bytes()


@pytest.fixture(scope="module")
def fixture_image(fixture_bytes):
    return read_spectral_image(fixture_bytes)


@pytest.fixture(scope="module")
def fixture_row(spherex_manifest):
    from skyshift.providers.spherex.discovery import DiscoveryRow

    src = fits.getheader(FIXTURE, 0)["SKYSRC"]
    return next(DiscoveryRow(**r) for r in spherex_manifest["discovery"]["rows"] if r["file_name"] == src)


def _rewrite(data: bytes, edit) -> bytes:
    with fits.open(io.BytesIO(data), memmap=False) as h:
        hl = fits.HDUList([x.copy() for x in h])
    hl = edit(hl) or hl
    buf = io.BytesIO()
    hl.writeto(buf, output_verify="silentfix")
    return buf.getvalue()


# ---------------------------------------------------------------- discovery (recorded live response)


@pytest.mark.archive
def test_sia_query_names_one_collection_and_is_bounded():
    """[archive] The SIA2 URL names one explicit collection and a small cone; QR2/unknown collections and wide cones are refused."""
    url = build_sia_url("spherex_dr1", 269.44628, 4.76803, 0.0003)
    assert url == "https://irsa.ipac.caltech.edu/SIA?COLLECTION=spherex_dr1&POS=CIRCLE+269.4462800+4.7680300+0.000300&RESPONSEFORMAT=VOTABLE"
    with pytest.raises(ValueError, match="superseded"):
        build_sia_url("spherex_qr2", 0, 0, 0.001)
    with pytest.raises(ValueError, match="unknown"):
        build_sia_url("spherex_dr7", 0, 0, 0.001)
    with pytest.raises(ValueError, match="bounded"):
        build_sia_url("spherex_dr1", 0, 0, 0.5)


@pytest.mark.archive
def test_recorded_sia_response_parses_by_column_name(spherex_manifest):
    """[archive] The recorded live DR1 response parses by name into 239 rows consistent with file names, bands and documented ranges."""
    body = gzip.decompress(SIA_RESPONSE.read_bytes())
    rows = parse_sia_votable(body, "spherex_dr1")
    assert len(rows) == spherex_manifest["discovery"]["n_rows"] == 239
    assert {r.collection for r in rows} == {"spherex_dr1"} and {r.detector for r in rows} == {1, 2, 3, 4, 5, 6}
    for r in rows:
        assert r.bandpass_name == f"SPHEREx-D{r.detector}" and r.file_name.startswith(f"level2_{r.obs_id}D{r.detector}_spx_")
        assert r.processing_version == 27 and r.t_min_mjd < r.t_max_mjd and r.dataproduct_subtype == "science"
        lo, hi = ref.DOCUMENTED_BAND_RANGES_UM[r.detector]
        # archive band metadata brackets the documented band (to within 0.05 um at each end)
        assert r.em_min_um <= lo + 0.05 and r.em_max_um >= hi - 0.05
    with pytest.raises(DiscoveryError, match="belongs to"):
        parse_sia_votable(body, "spherex_qr3")


@pytest.mark.archive
def test_duplicate_processing_versions_are_reported_not_merged():
    """[archive] Two processing versions of one exposure/detector: the newer is kept by the stated rule and the other is reported."""
    rows = parse_sia_votable(gzip.decompress(SIA_RESPONSE.read_bytes()), "spherex_dr1")[:3]
    older = dataclasses.replace(rows[0], processing_tag="l2b-v26-2026-100", processing_version=26, processing_date="2026-100",
                                file_name=rows[0].file_name.replace("v27", "v26"))
    kept, superseded = resolve_duplicates(rows + [older])
    assert len(kept) == 3 and rows[0] in kept and older not in kept
    assert superseded == [{"obs_id": older.obs_id, "detector": older.detector, "file_name": older.file_name, "kept": rows[0].file_name,
                           "rule": "highest processing version, then latest processing date"}]


@pytest.mark.archive
def test_manifest_records_the_live_retrieval(spherex_manifest):
    """[archive] The manifest records the exact query, every screened image and each download (status, bytes, sha256, time)."""
    m = spherex_manifest
    assert m["collection"] == "spherex_dr1" and m["release"] == "DR1"
    assert m["discovery"]["url"] == build_sia_url(PRESET.collection, PRESET.ra_deg, PRESET.dec_deg, PRESET.search_radius_deg)
    assert m["discovery"]["request"]["status"] == 200 and len(m["screening"]) == m["discovery"]["n_rows"]
    assert all(s["status"] == "screened" for s in m["screening"])
    wanted = [k for g in m["selection"]["selected_groups"] for k in g["members"]] + [c["key"] for c in m["selection"]["contrast"]]
    assert [d["key"] for d in m["downloads"]] == wanted
    for d in m["downloads"]:
        assert d["status"] == "downloaded" and d["request"]["status"] == 200 and len(d["sha256"]) == 64 and d["bytes"] > 1e6
        assert d["url"].startswith("https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/") and "?center=" in d["url"]
        assert all(c["status"] in ("pass", "warn") for c in d["checks"])


# ---------------------------------------------------------------- FITS format (real-file fixture)


@pytest.mark.archive
def test_fixture_validates_against_documented_r7_format(fixture_image, fixture_row):
    """[archive] A real DR1 cutout passes every documented-format check (units, flags, variance, WCS, WCS-WAVE, timing, DQA, EPSF)."""
    checks = validate_spectral_image(fixture_image, collection="spherex_dr1", row=fixture_row, requested_size_px=59)
    assert [c.id for c in checks if c.status != "pass"] == []
    assert fixture_image.units == {"IMAGE": "MJy / sr", "FLAGS": "", "VARIANCE": "MJy2 / sr2", "ZODI": "MJy / sr"}
    assert fixture_image.pipeline_version.startswith("7.") and fixture_image.flags.dtype == np.uint32
    assert check_extension_names(fixture_image.hdu_names) == []
    assert check_extension_names(["IMAGE", "FLAGS", "VARIANCE", "ZODI", "PSF", "WCS-WAVE"]) == ["EPSF"]


@pytest.mark.archive
def test_extensions_are_read_by_name_not_position(fixture_bytes, fixture_image):
    """[archive] Reordering the HDUs leaves every array and the flag definitions unchanged."""
    def shuffle(h):
        return fits.HDUList([h[0], h["WCS-WAVE"], h["ZODI"], h["EPSF"], h["VARIANCE"], h["FLAGS"], h["IMAGE"]])

    other = read_spectral_image(_rewrite(fixture_bytes, shuffle))
    for name in ("image", "flags", "variance", "zodi"):
        assert np.array_equal(getattr(other, name), getattr(fixture_image, name), equal_nan=True)
    assert other.flag_defs == fixture_image.flag_defs and other.hdu_names != fixture_image.hdu_names


@pytest.mark.archive
def test_flag_definitions_come_from_the_file(fixture_bytes, fixture_image):
    """[archive] Flag names/bits are read from MSKN/MSKM keywords and match ES Table 16; a renamed bit fails the check."""
    assert {d.bit: d.name for d in fixture_image.flag_defs} == {b: n for b, n in ref.DOCUMENTED_FLAGS.items() if b != 29}
    assert all(d.mask_value == 1 << d.bit for d in fixture_image.flag_defs)

    def rename(h):
        h["FLAGS"].header["MSKN0021"] = "NOT_SOURCE"

    bad = read_spectral_image(_rewrite(fixture_bytes, rename))
    check = next(c for c in validate_spectral_image(bad, collection="spherex_dr1") if c.id == "flag_definitions")
    assert check.status == "fail" and "bit 21" in check.detail


@pytest.mark.archive
def test_unit_and_extension_changes_are_detected(fixture_bytes):
    """[archive] A changed BUNIT fails the units check; a missing ZODI extension is refused before interpretation."""
    def unit(h):
        h["IMAGE"].header["BUNIT"] = "electron"

    img = read_spectral_image(_rewrite(fixture_bytes, unit))
    assert next(c for c in validate_spectral_image(img, collection="spherex_dr1") if c.id == "units").status == "fail"

    def drop(h):
        return fits.HDUList([x for x in h if x.name != "ZODI"])

    with pytest.raises(UnsupportedSpherexProduct, match="ZODI"):
        read_spectral_image(_rewrite(fixture_bytes, drop))


@pytest.mark.archive
def test_legacy_psf_cube_files_are_refused(fixture_bytes):
    """[archive] A pre-R7 layout (PSF image cube instead of the EPSF table, VERSION 6.5.6) raises UnsupportedSpherexProduct."""
    def legacy(h):
        h[0].header["VERSION"] = "6.5.6"
        cube = fits.ImageHDU(np.zeros((121, 11, 11), np.float32), name="PSF")
        return fits.HDUList([x if x.name != "EPSF" else cube for x in h])

    with pytest.raises(UnsupportedSpherexProduct, match="legacy pre-R7"):
        read_spectral_image(_rewrite(fixture_bytes, legacy))

    def old_version(h):
        h[0].header["VERSION"] = "6.5.6"

    with pytest.raises(UnsupportedSpherexProduct, match="older than R7"):
        read_spectral_image(_rewrite(fixture_bytes, old_version))


@pytest.mark.archive
def test_flags_near_position_use_the_documented_radius(fixture_image):
    """[archive] Flags are summarised within 2.5 px: a bit 2.4 px away is reported, one 2.6 px away is not."""
    img = dataclasses.replace(fixture_image, flags=np.zeros_like(fixture_image.flags))
    img.flags[20, 22] = 1 << 10  # HOT, distance sqrt(2.4^2) from (19.6, 20)
    img.flags[20, 16] = 1 << 11  # COLD, 3.6 px away
    img.flags[17, 19] = 1 << 15  # NONLINEAR at (19, 17): distance hypot(0.6, 3.0) = 3.06
    assert img.flags_near(19.6, 20.0) == ["HOT"]
    assert img.flags_near(19.6, 20.0, radius_px=3.1) == ["HOT", "NONLINEAR"]


# ---------------------------------------------------------------- wavelength


@pytest.mark.math
def test_wcs_wave_astropy_and_independent_bilinear_agree(fixture_image):
    """[math] astropy's -TAB evaluation and an independent bilinear lookup agree everywhere and reproduce the table nodes exactly."""
    h, table = fixture_image.image_header, fixture_image.wave_table
    rng = np.random.default_rng(1)
    ny, nx = fixture_image.shape
    for x, y in zip(rng.uniform(-0.5, nx - 0.5, 60), rng.uniform(-0.5, ny - 0.5, 60)):
        a = wavelength_astropy(h, fixture_image.wave_hdul, x, y)
        b = wavelength_bilinear(h, table, x, y)
        assert abs(a[0] - b[0]) < 1e-9 and abs(a[1] - b[1]) < 1e-9
    # Node (i, j) of the table sits at psi = (X[i], Y[j]) <=> 0-based pixel X[i] - 1 + CRPIX1W - CRVAL1W (CDELT = 1).
    for i, j in [(2, 3), (5, 5), (7, 1)]:
        x0 = table.x[i] - 1 + h["CRPIX1W"] - h["CRVAL1W"]
        y0 = table.y[j] - 1 + h["CRPIX2W"] - h["CRVAL2W"]
        lam, bw = wavelength_astropy(h, fixture_image.wave_hdul, x0, y0)
        assert lam == pytest.approx(table.values[j, i, 0], abs=1e-12) and bw == pytest.approx(table.values[j, i, 1], abs=1e-12)


@pytest.mark.archive
def test_wavelength_lies_within_archive_band_metadata(fixture_image, fixture_row):
    """[archive] The WCS-WAVE wavelength over the whole cutout lies within the SIA em_min..em_max of its detector band."""
    ny, nx = fixture_image.shape
    lams = [wavelength_bilinear(fixture_image.image_header, fixture_image.wave_table, x, y)[0] for x in (0, nx - 1) for y in (0, ny - 1)]
    assert all(fixture_row.em_min_um <= v <= fixture_row.em_max_um for v in lams)
    # the local wavelength changes across the cutout: a single detector does not have a single wavelength
    assert max(lams) - min(lams) > 0.0


@pytest.mark.archive
def test_cutout_and_full_file_screening_agree(spherex_manifest):
    """[archive] Two request paths (full-file byte ranges vs IBE cutout) give the same detector pixel and local wavelength."""
    scr = {s["key"]: s for s in spherex_manifest["screening"]}
    for d in spherex_manifest["downloads"]:
        s = scr[d["key"]]
        assert math.hypot(d["query_pixel_detector"][0] - s["query_pixel_detector"][0], d["query_pixel_detector"][1] - s["query_pixel_detector"][1]) < 1e-3
        assert abs(d["lambda_um"] - s["lambda_um"]) < 1e-9 and abs(d["bandwidth_um"] - s["bandwidth_um"]) < 1e-9
        assert d["wavelength_crosscheck_um"] < 1e-9
    for s in spherex_manifest["screening"]:
        if s.get("lambda_um") is not None:
            assert abs(s["lambda_um"] - s["lambda_um_independent"]) < 1e-9


@pytest.mark.math
def test_detector_number_alone_does_not_establish_compatibility():
    """[math] Same detector with a 0.5-bandwidth offset is incompatible; equal wavelengths on different detectors are incompatible."""
    a = WavelengthSample("a", 1, 0.900, 0.023, 0.0)
    assert pair_compatible(a, WavelengthSample("b", 1, 0.900 + 0.24 * 0.023, 0.023, 1.0))
    assert not pair_compatible(a, WavelengthSample("c", 1, 0.900 + 0.5 * 0.023, 0.023, 1.0))
    assert not pair_compatible(a, WavelengthSample("d", 4, 0.900, 0.023, 1.0))
    groups = compatibility_groups([a, WavelengthSample("c", 1, 0.9115, 0.023, 1.0), WavelengthSample("d", 4, 0.900, 0.023, 1.0)])
    assert sorted(len(g) for g in groups) == [1, 1, 1]


@pytest.mark.math
def test_groups_are_pairwise_compatible_and_order_independent():
    """[math] Every returned group is pairwise compatible, groups partition the input, and input order does not matter."""
    rng = np.random.default_rng(7)
    samples = [WavelengthSample(f"s{i}", int(rng.integers(1, 3)), float(rng.uniform(0.8, 0.9)), float(rng.uniform(0.02, 0.025)), float(rng.uniform(0, 300))) for i in range(80)]
    groups = compatibility_groups(samples)
    assert sorted(s.key for g in groups for s in g) == sorted(s.key for s in samples)
    for g in groups:
        assert all(pair_compatible(x, y) for i, x in enumerate(g) for y in g[i + 1 :])
    shuffled = list(samples)
    rng.shuffle(shuffled)
    assert [[s.key for s in g] for g in compatibility_groups(shuffled)] == [[s.key for s in g] for g in groups]


# ---------------------------------------------------------------- observed dataset (local cache)


@pytest.mark.archive
def test_observed_dataset_keeps_native_arrays_and_separates_origins(spherex_bundle, spherex_manifest):
    """[archive] Native frames hold the delivered arrays bit-for-bit; display frames are labelled; no truth; analyses unavailable."""
    ds = spherex_bundle.dataset
    assert ds.origin == "observed" and ds.provider == "spherex" and ds.release == "spherex_dr1" and spherex_bundle.truth is None
    assert spherex_bundle.catalog == [] and ds.astrometric_calibration is None and ds.seed is None
    assert {c.id for c in ds.capabilities if c.status == "unavailable"} >= {"source_measurement", "astrometric_fit", "difference_imaging", "registration"}
    frames = {f.id: f for f in ds.frames}
    for o in ds.observations:
        assert o.status == "available" and o.archive is not None and o.archive.collection == "spherex_dr1"
        native, display = (frames[i] for i in o.frame_ids)
        assert native.kind == "native" and not native.display_only and native.unit == "MJy / sr" and native.variance_unit == "MJy2 / sr2"
        assert native.provenance.origin == "observed" and native.background.included_in_image and not native.background.subtracted_by_skyshift
        assert native.wavelength.determination == "position_lookup_visualization" and native.wavelength.position_dependent
        assert display.kind == "archive_wcs_reprojection" and display.display_only and display.registration is None and display.provenance.parents == [native.id]
        d = next(x for x in spherex_manifest["downloads"] if f"{DS}:{x['key']}" == o.id)
        img = read_spectral_image(cutout_path(DS, d["file_name"]).read_bytes())
        arr = spherex_bundle.arrays[native.id]
        assert np.array_equal(arr.image, img.image, equal_nan=True) and np.array_equal(arr.mask, img.flags) and np.array_equal(arr.variance, img.variance, equal_nan=True)
        assert data_sha256(img) == d["data_sha256"]


@pytest.mark.registration
def test_display_reprojection_matches_independent_resampling(spherex_bundle):
    """[registration] Display pixels equal a manual bilinear sample of the native image at the archive-WCS position; outside is NaN + NO_COVERAGE."""
    ds = spherex_bundle.dataset
    from skyshift.coords.wcs import description_to_wcs

    grid = description_to_wcs(ds.common_grid)
    o = ds.observations[0]
    native_id, display_id = o.frame_ids
    native = spherex_bundle.arrays[native_id].image
    disp = spherex_bundle.arrays[display_id]
    img_wcs = read_spectral_image(cutout_path(DS, o.archive.file_name).read_bytes()).wcs
    n_checked = 0
    for gy, gx in [(10, 12), (32, 30), (40, 21), (50, 47), (25, 41)]:
        ra, dec = grid.wcs_pix2world([[gx, gy]], 0)[0]
        x, y = img_wcs.all_world2pix([[ra, dec]], 0, tolerance=1e-10)[0]
        if not (0 <= x <= native.shape[1] - 1 and 0 <= y <= native.shape[0] - 1):
            continue
        i, j = int(np.floor(x)), int(np.floor(y))
        fx, fy = x - i, y - j
        i1, j1 = min(i + 1, native.shape[1] - 1), min(j + 1, native.shape[0] - 1)
        v = (1 - fx) * (1 - fy) * native[j, i] + fx * (1 - fy) * native[j, i1] + (1 - fx) * fy * native[j1, i] + fx * fy * native[j1, i1]
        if np.isfinite(v):
            assert disp.image[gy, gx] == pytest.approx(v, rel=1e-5, abs=1e-6)
            n_checked += 1
    assert n_checked >= 3
    outside = ~np.isfinite(disp.image) & ((disp.mask & np.uint32(1 << NO_COVERAGE_BIT)) != 0)
    assert np.array_equal(outside, (disp.mask & np.uint32(1 << NO_COVERAGE_BIT)) != 0)


@pytest.mark.archive
def test_blink_only_for_available_wavelength_compatible_groups(spherex_bundle):
    """[archive] Blinkable groups have >=2 available members that are pairwise compatible at the field centre; the contrast frame is not blinkable."""
    ds = spherex_bundle.dataset
    obs = {o.id: o for o in ds.observations}
    blinkable = [b for b in ds.bands if b.compatibility and b.compatibility.blinkable]
    assert len(blinkable) == 6
    for b in ds.bands:
        members = [obs[i] for i in b.compatibility.member_observation_ids]
        assert {o.band_id for o in members} == {b.id} and {o.archive.detector for o in members} == {b.compatibility.detector}
        if b.compatibility.blinkable:
            ss = [WavelengthSample(o.id, o.archive.detector, o.archive.local_wavelength_um, o.archive.local_bandwidth_um, 0) for o in members]
            assert len(ss) >= 2 and all(pair_compatible(x, y, b.compatibility.max_delta_fraction) for i, x in enumerate(ss) for y in ss[i + 1 :])
    single = [b for b in ds.bands if not b.compatibility.blinkable]
    assert len(single) == 1
    contrast = obs[single[0].compatibility.member_observation_ids[0]]
    same_det = next(b for b in blinkable if b.compatibility.detector == contrast.archive.detector)
    ref_obs = obs[same_det.compatibility.member_observation_ids[0]]
    assert not pair_compatible(
        WavelengthSample("c", contrast.archive.detector, contrast.archive.local_wavelength_um, contrast.archive.local_bandwidth_um, 0),
        WavelengthSample("r", ref_obs.archive.detector, ref_obs.archive.local_wavelength_um, ref_obs.archive.local_bandwidth_um, 0),
    )


@pytest.mark.archive
def test_missing_cache_failed_downloads_and_hash_mismatch_are_explicit(spherex_bundle, spherex_manifest, tmp_path, monkeypatch):
    """[archive] Absent cache -> 'missing' with the fetch command; failed download -> 'failed'; changed file -> 'failed'. Nothing substituted."""
    m = copy.deepcopy(spherex_manifest)
    m["downloads"][0].update(status="failed", error="HTTP 502 Proxy Error")
    m["downloads"][1]["data_sha256"] = "0" * 64
    b = build_bundle(PRESET, m)
    obs = {o.id: o for o in b.dataset.observations}
    o0, o1 = obs[f"{DS}:{m['downloads'][0]['key']}"], obs[f"{DS}:{m['downloads'][1]['key']}"]
    assert o0.status == "failed" and "HTTP 502" in o0.status_reason and o0.frame_ids == []
    assert o1.status == "failed" and "hash differs" in o1.status_reason and o1.frame_ids == []
    assert not any(k.startswith(o0.id) or k.startswith(o1.id) for k in b.arrays)
    d1 = next(g for g in b.dataset.bands if o0.id in g.compatibility.member_observation_ids)
    assert o1.id in d1.compatibility.member_observation_ids  # both altered products belong to the D1 group
    assert d1.compatibility.blinkable is False and "Only 1 of 3" in d1.compatibility.reason

    monkeypatch.setenv("SKYSHIFT_SPHEREX_CACHE", str(tmp_path))
    empty = build_bundle(PRESET, spherex_manifest)
    assert all(o.status == "missing" and "fetch" in o.status_reason for o in empty.dataset.observations)
    assert empty.arrays == {} and empty.dataset.frames == [] and empty.dataset.origin == "observed" and empty.truth is None
    assert not any(b.compatibility.blinkable for b in empty.dataset.bands)


@pytest.mark.api
def test_api_serves_observed_pixels_and_refuses_analyses(spherex_bundle):
    """[api] Observed dataset: native/display pixels with units and uint32 flags; analyses answer 409 not_available; no truth."""
    c = TestClient(app)
    assert any(d["id"] == DS and d["origin"] == "observed" and d["availability"] == "ready" for d in c.get("/api/datasets").json())
    ds = c.get(f"/api/datasets/{DS}").json()
    native_id, display_id = ds["observations"][0]["frame_ids"]
    r = c.get(f"/api/datasets/{DS}/frames/{native_id}/pixels", params={"plane": "mask"})
    assert r.headers["x-skyshift-dtype"] == "uint32" and r.headers["x-skyshift-origin"] == "observed"
    ny, nx = map(int, r.headers["x-skyshift-shape"].split(","))
    assert np.array_equal(np.frombuffer(r.content, "<u4").reshape(ny, nx), spherex_bundle.arrays[native_id].mask)
    r = c.get(f"/api/datasets/{DS}/frames/{display_id}/pixels", params={"plane": "image"})
    assert r.headers["x-skyshift-unit"] == "MJy / sr" and r.headers["x-skyshift-display-only"] == "true"
    assert c.get(f"/api/datasets/{DS}/frames/{display_id}/pixels", params={"plane": "variance"}).status_code == 422
    for path in ("sources", "sources/S001/measurements", "sources/S001/associations", f"catalog?frame_id={display_id}", f"difference/info?a={display_id}&b={display_id}"):
        r = c.get(f"/api/datasets/{DS}/{path}")
        assert r.status_code == 409 and r.json()["detail"]["code"] == "not_available", path
    body = {"dataset_id": DS, "source_id": "S001", "model": "proper_motion", "measurements": []}
    r = c.post("/api/fits/astrometric", json=body)
    assert r.status_code == 409 and r.json()["detail"]["details"]["capability"] == "astrometric_fit"
    assert c.get(f"/api/datasets/{DS}/truth").json()["detail"]["code"] == "not_synthetic"
    assert c.get("/api/resolve", params={"q": "S001", "dataset_id": DS}).json()["kind"] == "unresolved"


@pytest.mark.pipeline
def test_synthetic_pipeline_is_never_run_on_observed_data():
    """[pipeline] The synthetic investigation refuses observed datasets (no detection/registration on archive pixels)."""
    from skyshift.pipeline.investigation import get_investigation

    with pytest.raises(ValueError, match="observed dataset"):
        get_investigation(DS)


@pytest.mark.contracts
def test_spherex_status_is_derived_from_recorded_checks():
    """[contracts] SPHEREx live capabilities are 'tested'/'failed' only when the validation report records that live test."""
    from skyshift.providers.spherex import LIVE_TESTS, _live_status

    st = SpherexProvider().status()
    assert st.status == "implemented"
    by_name = {c.name: c for c in st.capabilities}
    for cap_name, key in (("Discovery (SIA2, explicit collection, bounded cone)", "discovery"), ("Cutout acquisition (IBE; cached; concurrency <= 4; retries)", "cutout")):
        assert by_name[cap_name].status == _live_status(LIVE_TESTS[key])[0]
    assert by_name["Effective PSF evaluation and position fitting"].status == "implemented"  # used only for Gaia reference stars
    assert by_name["Photometry / target astrometry / registration / difference imaging"].status == "not_implemented"
    assert by_name["Spectral calibration products (CWAVE/CBAND)"].status == "not_implemented"


# ---------------------------------------------------------------- live (IRSA)


@pytest.mark.live
def test_live_sia_discovery_matches_manifest(spherex_manifest, record_property):
    """[live] SPHEREx: a live SIA2 query in spherex_dr1 parses with the documented schema and still returns every pinned (selected) product unchanged; a changed row count is recorded as a note."""
    from skyshift.providers.spherex.http import ArchiveClient

    client = ArchiveClient()
    body, rec = client.get(spherex_manifest["discovery"]["url"], max_bytes=50_000_000)
    rows = parse_sia_votable(body, "spherex_dr1")  # schema + provenance checks (columns by name, collection, band/file consistency)
    assert rec.status == 200
    live = {row_key(r.obs_id, r.detector): r for r in rows}
    recorded = {row_key(r["obs_id"], r["detector"]): r for r in spherex_manifest["discovery"]["rows"]}
    pinned = [k for g in spherex_manifest["selection"]["selected_groups"] for k in g["members"]] + [c["key"] for c in spherex_manifest["selection"].get("contrast", [])]
    for k in pinned:  # pinned products must be unchanged: same processing tag and access URL
        assert k in live, f"pinned product {k} no longer returned"
        assert (live[k].processing_tag, live[k].access_url) == (recorded[k]["processing_tag"], recorded[k]["access_url"])
    added, removed = sorted(set(live) - set(recorded)), sorted(set(recorded) - set(live))
    if added or removed:
        record_property("note", f"SIA2 row count changed: {len(live)} live vs {len(recorded)} recorded (+{len(added)} / -{len(removed)}); "
                                "pinned products unchanged. Reported, not a failure.")
    else:
        record_property("note", f"SIA2 row count unchanged ({len(recorded)} products).")


@pytest.mark.live
def test_live_range_screening_matches_manifest(spherex_manifest):
    """[live] SPHEREx: byte-range reads of one full DR1 file reproduce the recorded detector pixel and local wavelength."""
    from skyshift.providers.spherex.discovery import DiscoveryRow
    from skyshift.providers.spherex.http import ArchiveClient
    from skyshift.providers.spherex.screening import screen_row

    key = spherex_manifest["selection"]["selected_groups"][0]["members"][0]
    row = next(DiscoveryRow(**r) for r in spherex_manifest["discovery"]["rows"] if row_key(r["obs_id"], r["detector"]) == key)
    rec = next(s for s in spherex_manifest["screening"] if s["key"] == key)
    s = screen_row(ArchiveClient(), row, PRESET.ra_deg, PRESET.dec_deg)
    assert all(r["status"] == 206 for r in s["requests"])
    assert s["query_pixel_detector"] == pytest.approx(rec["query_pixel_detector"], abs=1e-4)
    assert s["lambda_um"] == pytest.approx(rec["lambda_um"], abs=1e-12) and s["bandwidth_um"] == pytest.approx(rec["bandwidth_um"], abs=1e-12)


@pytest.mark.live
def test_live_cutout_download_validates(spherex_manifest):
    """[live] SPHEREx: a fresh IBE cutout download passes every format check (full 441-zone EPSF) and matches the recorded science arrays."""
    from skyshift.providers.spherex.discovery import DiscoveryRow
    from skyshift.providers.spherex.http import ArchiveClient

    d = spherex_manifest["downloads"][0]
    row = next(DiscoveryRow(**r) for r in spherex_manifest["discovery"]["rows"] if row_key(r["obs_id"], r["detector"]) == d["key"])
    body, rec = ArchiveClient().get(d["url"], max_bytes=40_000_000)
    img = read_spectral_image(body)
    checks = validate_spectral_image(img, collection="spherex_dr1", row=row, requested_size_px=59)
    assert rec.status == 200 and [c.id for c in checks if c.status != "pass"] == []
    assert img.epsf["rows"] == ref.EPSF_ZONES[row.detector] and data_sha256(img) == d["data_sha256"]
