"""Read and validate SPHEREx Spectral Image files (full images or IRSA cutouts).

Extensions are located by EXTNAME. Flag definitions, units, WCS and ePSF sampling
are read from the file and checked against the documented R7 (DR1/QR3) format
(reference.py). Files from the legacy pipeline (PSF cube; VERSION < 7.0) raise
UnsupportedSpherexProduct instead of being interpreted with R7 assumptions.
"""

from __future__ import annotations

import hashlib
import io
import re
import warnings
from dataclasses import dataclass, field

import astropy.units as u
import numpy as np
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS, FITSFixedWarning

from skyshift.contracts import FileCheck
from skyshift.imaging.epsf import EPSFLibrary
from skyshift.providers.spherex import reference as ref
from skyshift.providers.spherex.discovery import DiscoveryRow
from skyshift.providers.spherex.wavelength import WaveTable, wavelength_astropy, wavelength_bilinear

_MSKN = re.compile(r"^MSKN(\d{4})$")
_CALIB = re.compile(r"^\[CALIB\]\s+(\S+)\s+(\S+)")
QUALITY_KEYS = ("FINAST", "L1DQAFLG", "L2DQAFLG", "ASTRONETSOLVED", "MATCH_NSTARS", "PSF_FWHM", "OMEGA_MEDIAN", "PXSRCMSK", "WCSRETRY")
TIMING_KEYS = ("TIMESYS", "DATE-OBS", "MJD-OBS", "DATE-BEG", "MJD-BEG", "DATE-AVG", "MJD-AVG", "DATE-END", "MJD-END", "XPOSURE", "TELAPSE")
SC_KEYS = ("X_SC", "Y_SC", "Z_SC")


class UnsupportedSpherexProduct(ValueError):
    """A file this build must not interpret (legacy format, wrong product type)."""


@dataclass(frozen=True)
class FlagDef:
    bit: int
    name: str
    description: str
    mask_value: int


@dataclass
class SpectralImage:
    sha256: str
    nbytes: int
    pipeline_version: str
    hdu_names: list[str]
    primary_header: fits.Header
    image_header: fits.Header
    image: np.ndarray  # float32, MJy/sr (as delivered; zodiacal light included)
    flags: np.ndarray  # uint32 bit mask
    variance: np.ndarray  # float32, (MJy/sr)^2
    zodi: np.ndarray  # float32, MJy/sr model (not subtracted from image)
    flag_defs: list[FlagDef]
    wcs: WCS
    wave_hdul: fits.HDUList
    wave_table: WaveTable
    epsf: dict
    units: dict[str, str]
    zodi_model: str = ""
    calibration_refs: dict[str, str] = field(default_factory=dict)
    epsf_library: EPSFLibrary | None = None  # zones overlapping this cutout (+1 px), read from the file's EPSF table

    @property
    def detector(self) -> int:
        return int(self.image_header["DETECTOR"])

    @property
    def obs_id(self) -> str:
        return str(self.image_header["OBSID"]).strip()

    @property
    def shape(self) -> tuple[int, int]:
        return tuple(self.image.shape)  # type: ignore[return-value]

    def header_quality(self) -> dict[str, float | int | str | bool]:
        out: dict[str, float | int | str | bool] = {}
        for k in QUALITY_KEYS:
            if k in self.image_header:
                v = self.image_header[k]
                out[k] = v.strip() if isinstance(v, str) else v
        for k, v in self.image_header.items():
            if k.startswith("L2 N_") and isinstance(v, (int, float)):
                out[k] = v
        return out

    def timing(self) -> dict[str, float | int | str]:
        return {k: (self.image_header[k].strip() if isinstance(self.image_header[k], str) else self.image_header[k]) for k in TIMING_KEYS if k in self.image_header}

    def spacecraft_km(self) -> tuple[float, float, float] | None:
        if all(k in self.image_header for k in SC_KEYS):
            return tuple(float(self.image_header[k]) for k in SC_KEYS)  # type: ignore[return-value]
        return None

    def detector_offset(self) -> tuple[float, float] | None:
        """(dx, dy) so that detector 0-based pixel = cutout 0-based pixel + offset (alternate WCS 'A')."""
        h = self.image_header
        if "CRPIX1A" not in h or str(h.get("CTYPE1A", "")).strip() != "LINEAR":
            return None
        return (1.0 - float(h["CRPIX1A"]) + float(h.get("CRVAL1A", 0.0)), 1.0 - float(h["CRPIX2A"]) + float(h.get("CRVAL2A", 0.0)))

    def sky_to_pixel(self, ra_deg: float, dec_deg: float) -> tuple[float, float]:
        x, y = self.wcs.all_world2pix([[ra_deg, dec_deg]], 0, tolerance=1e-8, maxiter=50)[0]
        return float(x), float(y)

    def wavelength_at(self, x0: float, y0: float) -> tuple[float, float, float]:
        """(lambda_um, bandwidth_um, |astropy - bilinear|) at 0-based cutout pixel."""
        lam, bw = wavelength_astropy(self.image_header, self.wave_hdul, x0, y0)
        lam2, bw2 = wavelength_bilinear(self.image_header, self.wave_table, x0, y0)
        return lam, bw, max(abs(lam - lam2), abs(bw - bw2))

    def flags_near(self, x0: float, y0: float, radius_px: float = ref.FLAG_SUMMARY_RADIUS_PX) -> list[str]:
        ny, nx = self.flags.shape
        yy, xx = np.mgrid[0:ny, 0:nx]
        sel = (xx - x0) ** 2 + (yy - y0) ** 2 <= radius_px**2
        word = int(np.bitwise_or.reduce(self.flags[sel])) if sel.any() else 0
        return [d.name for d in self.flag_defs if word & d.mask_value]


def _version_tuple(v: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", v)
    return tuple(int(p) for p in parts[:3]) if parts else (0,)


def read_spectral_image(data: bytes) -> SpectralImage:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FITSFixedWarning)
        hdul = fits.open(io.BytesIO(data), memmap=False, lazy_load_hdus=False)
        names = [h.name.strip().upper() for h in hdul]
        primary = hdul[0].header
        version = str(primary.get("VERSION", "")).strip()
        if "EPSF" not in names:
            if ref.LEGACY_PSF_EXTENSION in names:
                raise UnsupportedSpherexProduct(
                    f"legacy pre-R7 file (VERSION {version or 'unknown'}, '{ref.LEGACY_PSF_EXTENSION}' cube, no 'EPSF' table): "
                    "QR1/QR2 products need separately tested handling, which this build does not have"
                )
            raise UnsupportedSpherexProduct("no 'EPSF' extension: not an R7 SPHEREx Spectral Image")
        if not version or _version_tuple(version) < ref.R7_MIN_VERSION:
            raise UnsupportedSpherexProduct(f"pipeline VERSION {version!r} is older than R7 (7.0): unsupported")
        missing = [e for e in ref.EXPECTED_EXTENSIONS_R7 if e not in names]
        if missing:
            raise UnsupportedSpherexProduct(f"missing extensions {missing}")
        img_h = hdul["IMAGE"].header.copy()
        image = np.asarray(hdul["IMAGE"].data, dtype=np.float32)
        flags_raw = np.asarray(hdul["FLAGS"].data)
        if flags_raw.dtype.kind not in "iu":
            raise UnsupportedSpherexProduct(f"FLAGS has non-integer dtype {flags_raw.dtype}")
        flags = flags_raw.astype(np.int64).astype(np.uint32)
        variance = np.asarray(hdul["VARIANCE"].data, dtype=np.float32)
        zodi = np.asarray(hdul["ZODI"].data, dtype=np.float32)
        flag_defs = []
        fh = hdul["FLAGS"].header
        for k in fh.keys():
            m = _MSKN.match(k)
            if m:
                n = int(m.group(1))
                flag_defs.append(FlagDef(n, str(fh[k]).strip(), str(fh.get(f"MSKD{n:04d}", "")).strip(), int(fh.get(f"MSKM{n:04d}", -1))))
        wave_hdul = fits.HDUList([fits.PrimaryHDU(), hdul["WCS-WAVE"].copy()])
        epsf_hdu = hdul["EPSF"]
        epsf_cols = list(epsf_hdu.columns.names)
        epsf_dim = None
        if "EPSF" in epsf_cols:
            epsf_dim = tuple(np.asarray(epsf_hdu.data["EPSF"][0]).shape)
        epsf = {
            "rows": int(epsf_hdu.header.get("NAXIS2", 0)),
            "columns": epsf_cols,
            "sample_shape": epsf_dim,
            "oversampling": (epsf_hdu.header.get("OVSMPX"), epsf_hdu.header.get("OVSMPY")),
            "detector": str(epsf_hdu.header.get("DETECTOR", "")).strip(),
            "calibration_source": next((str(h).split(":", 1)[1].strip() for h in epsf_hdu.header.get("HISTORY", []) if "Calibration source file" in str(h)), None),
            "sum_first_zone": float(np.sum(epsf_hdu.data["EPSF"][0])) if epsf_dim else None,
        }
        units = {n: str(hdul[n].header.get("BUNIT", "")).strip() for n in ("IMAGE", "FLAGS", "VARIANCE", "ZODI")}
        zodi_model = str(hdul["ZODI"].header.get("ZODIMDL", "")).strip()
        calib: dict[str, str] = {}
        for h in img_h.get("HISTORY", []):
            m = _CALIB.match(str(h).strip())
            if m:
                calib[m.group(1)] = m.group(2)
        w = WCS(img_h)
        table = WaveTable.from_hdu(hdul["WCS-WAVE"])
        epsf_library = _cutout_epsf_library(epsf_hdu, img_h, image.shape)
        hdul.close()
    return SpectralImage(
        sha256=hashlib.sha256(data).hexdigest(), nbytes=len(data), pipeline_version=version, hdu_names=names,
        primary_header=primary.copy(), image_header=img_h, image=image, flags=flags, variance=variance, zodi=zodi,
        flag_defs=sorted(flag_defs, key=lambda d: d.bit), wcs=w, wave_hdul=wave_hdul, wave_table=table, epsf=epsf, units=units,
        zodi_model=zodi_model, calibration_refs=calib, epsf_library=epsf_library,
    )


def _cutout_epsf_library(epsf_hdu, image_header, shape: tuple[int, int]) -> EPSFLibrary | None:  # noqa: ANN001
    """The EPSF zones overlapping this cutout (1 px margin) plus their grid neighbours, or None if unreadable.

    Positions inside the cutout always fall in an overlapping zone; the neighbouring zones are kept
    only for the PSF-mismatch sensitivity test (refits with an adjacent zone's ePSF)."""
    try:
        lib = EPSFLibrary.from_hdu(epsf_hdu)
    except (ValueError, KeyError):
        return None
    if str(image_header.get("CTYPE1A", "")).strip() != "LINEAR" or "CRPIX1A" not in image_header:
        return lib
    ox = 1.0 - float(image_header["CRPIX1A"]) + float(image_header.get("CRVAL1A", 0.0))
    oy = 1.0 - float(image_header["CRPIX2A"]) + float(image_header.get("CRVAL2A", 0.0))
    ny, nx = shape
    x0, x1, y0, y1 = ox - 1.5, ox + nx + 0.5, oy - 1.5, oy + ny + 0.5
    overlap = [z for z in lib.zones
               if z.x_center + 0.5 * z.x_width >= x0 and z.x_center - 0.5 * z.x_width <= x1 and z.y_center + 0.5 * z.y_width >= y0 and z.y_center - 0.5 * z.y_width <= y1]
    if not overlap:
        return lib
    bins = {(z.binx, z.biny) for z in overlap}
    near = {(bx + dx, by + dy) for bx, by in bins for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))}
    keep = [z.index for z in lib.zones if (z.binx, z.biny) in near]
    zones = [lib.zones[i] for i in keep]
    from dataclasses import replace

    return EPSFLibrary([replace(z, index=k) for k, z in enumerate(zones)], lib.arrays[keep], lib.oversampling, lib.detector)


def _chk(cid: str, ok: bool | None, detail: str, reference: str | None = None, warn: bool = False) -> FileCheck:
    status = "pass" if ok else ("warn" if warn or ok is None else "fail")
    return FileCheck(id=cid, status=status, detail=detail, reference=reference)


ES = ref.EXPLANATORY_SUPPLEMENT
DP = "SPHEREx data-product documentation"


def validate_spectral_image(img: SpectralImage, *, collection: str, row: DiscoveryRow | None = None, requested_size_px: int | None = None) -> list[FileCheck]:
    """Executed checks of one file against the documented R7 format (and its discovery row)."""
    checks: list[FileCheck] = []
    h = img.image_header
    # Extensions and pipeline version
    checks.append(_chk("extensions", True, f"HDUs by EXTNAME: {', '.join(img.hdu_names)} (all of {', '.join(ref.EXPECTED_EXTENSIONS_R7)} present)", DP))
    r7 = _version_tuple(img.pipeline_version) >= ref.R7_MIN_VERSION
    coll_ok = collection in ref.COLLECTIONS and ref.COLLECTIONS[collection].pipeline.startswith("R7")
    checks.append(_chk("pipeline_version", r7 and coll_ok, f"PRIMARY VERSION={img.pipeline_version} ({'R7' if r7 else 'pre-R7'}); collection {collection} documented as R7", "IRSA tutorial: SPHEREx PSF models"))
    # Units
    try:
        ui = u.Unit(img.units["IMAGE"])
        uv = u.Unit(img.units["VARIANCE"])
        uz = u.Unit(img.units["ZODI"])
        units_ok = ui == u.MJy / u.sr and uv == (u.MJy / u.sr) ** 2 and uz == u.MJy / u.sr
        unit_detail = f"IMAGE '{img.units['IMAGE']}', VARIANCE '{img.units['VARIANCE']}', ZODI '{img.units['ZODI']}', FLAGS '{img.units['FLAGS']}'"
    except ValueError as exc:
        units_ok, unit_detail = False, f"unparseable BUNIT: {exc}"
    checks.append(_chk("units", units_ok and img.units["FLAGS"] == "", unit_detail + " (documented: MJy/sr, (MJy/sr)^2, MJy/sr, dimensionless)", DP))
    # Shapes and dtypes
    shapes = {n: a.shape for n, a in (("IMAGE", img.image), ("FLAGS", img.flags), ("VARIANCE", img.variance), ("ZODI", img.zodi))}
    same = len(set(shapes.values())) == 1 and all(s[0] <= ref.DETECTOR_SHAPE[0] and s[1] <= ref.DETECTOR_SHAPE[1] for s in shapes.values())
    checks.append(_chk("shapes", same, f"planes {shapes['IMAGE']} (detector {ref.DETECTOR_SHAPE[0]}x{ref.DETECTOR_SHAPE[1]})", DP))
    # Variance
    finite_img = np.isfinite(img.image)
    fv = np.isfinite(img.variance)
    neg = int(np.sum(img.variance[fv] < 0))
    var_ok = neg == 0 and bool(np.all(fv[finite_img]))
    checks.append(_chk("variance", var_ok, f"{int(fv.sum())}/{fv.size} finite, {neg} negative; finite wherever IMAGE is finite: {bool(np.all(fv[finite_img]))}", DP))
    nonfinite_unflagged = int(np.sum(~finite_img & (img.flags == 0)))
    checks.append(_chk("missing_values_flagged", nonfinite_unflagged == 0, f"{int((~finite_img).sum())} non-finite IMAGE pixels, {nonfinite_unflagged} without any flag", f"{ES}, Sect. 3.2.12"))
    # Flag definitions read from the file vs the documented table
    bad_defs = [f"bit {d.bit} '{d.name}'" for d in img.flag_defs if ref.DOCUMENTED_FLAGS.get(d.bit) != d.name or d.mask_value != (1 << d.bit)]
    checks.append(_chk("flag_definitions", not bad_defs and bool(img.flag_defs),
                       f"{len(img.flag_defs)} bits defined by MSKN/MSKM/MSKD keywords" + (f"; mismatches: {', '.join(bad_defs)}" if bad_defs else "; all match Table 16"), f"{ES}, Table 16"))
    defined = 0
    for d in img.flag_defs:
        defined |= d.mask_value
    used = int(np.bitwise_or.reduce(img.flags.ravel())) if img.flags.size else 0
    undefined = [b for b in range(32) if used & (1 << b) and not defined & (1 << b)]
    checks.append(_chk("flag_values", not undefined, f"bits in use: {[b for b in range(32) if used & (1 << b)]}" + (f"; undefined bits {undefined}" if undefined else ""), f"{ES}, Table 16"))
    # Spatial WCS
    ctype = (str(h.get("CTYPE1", "")).strip(), str(h.get("CTYPE2", "")).strip())
    sip = img.wcs.sip is not None
    ny, nx = img.shape
    yy, xx = np.mgrid[0:ny:max(1, ny // 6), 0:nx:max(1, nx // 6)]
    world = img.wcs.all_pix2world(np.column_stack([xx.ravel(), yy.ravel()]).astype(float), 0)
    back = img.wcs.all_world2pix(world, 0, tolerance=1e-10, maxiter=50)
    rt = float(np.max(np.abs(back - np.column_stack([xx.ravel(), yy.ravel()]))))
    scale = float(np.sqrt(abs(np.linalg.det(img.wcs.pixel_scale_matrix))) * 3600.0)
    wcs_ok = ctype == ("RA---TAN-SIP", "DEC--TAN-SIP") and sip and str(h.get("RADESYS", "")).strip() == "ICRS" and rt < 1e-6 and abs(scale / ref.NOMINAL_PIXEL_SCALE_ARCSEC - 1) < 0.03
    checks.append(_chk("spatial_wcs", wcs_ok, f"{ctype[0]}/{ctype[1]}, SIP order A={h.get('A_ORDER')}, RADESYS={h.get('RADESYS')}, linear scale {scale:.3f} arcsec/px; "
                       f"numerical pixel->sky->pixel round trip {rt:.1e} px (not an accuracy test)", f"{ES}, Sect. 3.2.8"))
    off = img.detector_offset()
    if off is not None:
        x0, y0 = off
        inside = 0 <= x0 and 0 <= y0 and x0 + nx - 1 <= ref.DETECTOR_SHAPE[1] - 1 and y0 + ny - 1 <= ref.DETECTOR_SHAPE[0] - 1
        checks.append(_chk("detector_coordinates", inside and str(h.get("WCSNAMEA", "")).strip() == "0-based active pixel coordinates",
                           f"alternate WCS 'A': cutout origin at detector pixel ({x0:.0f}, {y0:.0f})", "IRSA tutorial: SPHEREx spectral image cutouts"))
    if requested_size_px is not None:
        complete = ny >= requested_size_px - 1 and nx >= requested_size_px - 1
        checks.append(_chk("cutout_complete", complete, f"cutout {ny}x{nx} px for a requested ~{requested_size_px} px (IRSA clips at detector edges)", "IRSA IBE cutout service", warn=True))
    # Spectral WCS (WCS-WAVE)
    cx, cy = (nx - 1) / 2.0, (ny - 1) / 2.0
    pts = [(cx, cy), (0.0, 0.0), (nx - 1.0, ny - 1.0)]
    evals = [img.wavelength_at(px, py) for px, py in pts]
    agree = max(e[2] for e in evals)
    lam_c, bw_c, _ = evals[0]
    spec_ok = str(h.get("CUNIT1W", "")).strip() == "um" and agree < 1e-6 and lam_c > 0 and bw_c > 0
    checks.append(_chk("spectral_wcs", spec_ok, f"WAVE-TAB lookup '{h.get('PS1_0W')}': centre lambda {lam_c:.4f} um, bandwidth {bw_c:.4f} um; "
                       f"astropy -TAB vs independent bilinear max difference {agree:.1e} um (visualization-grade, ~1 nm documented)", DP))
    det = img.detector
    lo, hi = ref.DOCUMENTED_BAND_RANGES_UM.get(det, (np.nan, np.nan))
    if row is not None:
        in_sia = row.em_min_um - 1e-4 <= lam_c <= row.em_max_um + 1e-4
        checks.append(_chk("wavelength_range", in_sia, f"centre lambda {lam_c:.4f} um within SIA em_min..em_max {row.em_min_um:.4f}-{row.em_max_um:.4f} um "
                           f"(documented band {det}: {lo}-{hi} um)", DP))
    # Timing
    t = img.timing()
    try:
        beg, avg, end = float(t["MJD-BEG"]), float(t["MJD-AVG"]), float(t["MJD-END"])
        tdate = abs((Time(str(t["DATE-AVG"]), format="isot", scale="utc").mjd - avg) * 86400.0)
        time_ok = t.get("TIMESYS") == "UTC" and beg <= avg <= end and abs(avg - 0.5 * (beg + end)) * 86400 < 1e-3 and tdate < 1e-3 and 0 < float(t["XPOSURE"]) <= float(t.get("TELAPSE", np.inf))
        tdetail = f"TIMESYS={t.get('TIMESYS')}; MJD-BEG <= MJD-AVG <= MJD-END; |DATE-AVG - MJD-AVG| = {tdate:.1e} s; XPOSURE {t['XPOSURE']} s <= TELAPSE {t.get('TELAPSE')} s"
    except (KeyError, ValueError) as exc:
        time_ok, tdetail = False, f"timing keywords incomplete: {exc}"
    checks.append(_chk("timing", time_ok, tdetail, f"{ES}, Table A.35"))
    # Identity and discovery consistency
    if row is not None:
        same_id = img.obs_id == row.obs_id and det == row.detector
        checks.append(_chk("identity", same_id, f"OBSID {img.obs_id} / DETECTOR {det} vs discovery {row.obs_id} / D{row.detector}"))
        try:
            dt = abs(float(t["MJD-BEG"]) - row.t_min_mjd) * 86400.0
            dexp = abs(float(t["XPOSURE"]) - row.t_exptime_s)
            checks.append(_chk("discovery_timing", dt < 0.5 and dexp < 0.01, f"|SIA t_min - MJD-BEG| = {dt:.3f} s; |t_exptime - XPOSURE| = {dexp:.4f} s (SIA times are UTC MJD)"))
        except (KeyError, ValueError):
            checks.append(_chk("discovery_timing", False, "timing keywords missing"))
    # Archive data-quality keywords
    fin = h.get("FINAST")
    checks.append(_chk("finast", fin == ref.FINAST_GOOD, f"FINAST={fin} (0 good, 1 partial, >1 poor)", f"{ES}, Sect. 3.2.8", warn=fin == 1))
    l2 = str(h.get("L2DQAFLG", "")).strip()
    checks.append(_chk("l2_dqa", l2.lower() == "pass", f"L2DQAFLG='{l2}', L1DQAFLG='{str(h.get('L1DQAFLG', '')).strip()}'", f"{ES}, Sect. 3.2.12"))
    # ePSF format (recognised and recorded; not evaluated in this build)
    e = img.epsf
    cols_ok = all(c in e["columns"] for c in ref.EPSF_COLUMNS)
    trimmed = "SKYTRIM" in img.primary_header
    rows_ok = e["rows"] == ref.EPSF_ZONES.get(det)
    checks.append(_chk("epsf_format", cols_ok and e["sample_shape"] == (33, 33) and e["oversampling"] == (5, 5) and (rows_ok or trimmed),
                       f"EPSF table: {e['rows']} zones (documented {ref.EPSF_ZONES.get(det)}{'; fixture trimmed' if trimmed else ''}), samples {e['sample_shape']}, "
                       f"OVSMPX/OVSMPY={e['oversampling']}, source {e['calibration_source']}; not evaluated by SkyShift", f"{ES}, Sect. 4.2.3"))
    zodi_unit_ok = img.units["ZODI"] == ref.IMAGE_UNIT
    checks.append(_chk("zodi", zodi_unit_ok and bool(np.isfinite(img.zodi).any()),
                       f"ZODI model '{img.zodi_model}' present in MJy/sr; documented as NOT subtracted from IMAGE (SkyShift does not subtract it either)", DP))
    return checks


def checks_passed(checks: list[FileCheck]) -> bool:
    return all(c.status != "fail" for c in checks)
