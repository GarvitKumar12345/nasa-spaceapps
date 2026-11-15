"""Mapping of one gaiadr3.gaia_source row to the CatalogSource contract (+ a generic cone builder).

The reference epoch is kept in its own convention (Julian year, TCB), never
relabelled as UTC. NULL/NaN values become None; a missing radial velocity
stays None. ra_error is the uncertainty of alpha* = alpha cos(dec) in mas and
pmra is mu_alpha* = d(alpha)/dt cos(dec) in mas/yr (Gaia conventions). The
source_id stays a decimal string ('gaiadr3:<source_id>').
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from skyshift.contracts import CatalogSource, Epoch, Provenance, Quality, SkyPosition
from skyshift.coords.time import make_epoch
from skyshift.providers.gaia_dr3 import reference as ref
from skyshift.providers.gaia_dr3.catalog import source_id_string

GAIA_TABLE = ref.GAIA_TABLE
GAIA_RELEASE = ref.GAIA_RELEASE
CORRELATION_COLUMNS = ref.CORRELATION_COLUMNS
SOLUTION_BY_PARAMS = ref.SOLUTION_BY_PARAMS
QUALITY_COLUMNS = ("ruwe", "astrometric_excess_noise", "astrometric_excess_noise_sig", "visibility_periods_used",
                   "ipd_frac_multi_peak", "ipd_gof_harmonic_amplitude", "non_single_star", "nu_eff_used_in_astrometry", "pseudocolour")
PHOTOMETRY_COLUMNS = ("phot_g_mean_mag", "phot_bp_mean_mag", "phot_rp_mean_mag", "bp_rp", "grvs_mag")


def build_cone_query(ra_deg: float, dec_deg: float, radius_deg: float, row_limit: int = 2000) -> str:
    """Generic ADQL cone on gaiadr3.gaia_source with explicit columns and a TOP limit (field queries use query.build_field_query)."""
    if not (0 < radius_deg <= 1.0):
        raise ValueError("radius_deg must be in (0, 1] for a bounded query")
    if not (0 < row_limit <= 100_000):
        raise ValueError("row_limit must be in (0, 100000]")
    cols = ", ".join(ref.COLUMN_NAMES)
    return (
        f"SELECT TOP {int(row_limit)} {cols} FROM {GAIA_TABLE} "
        f"WHERE 1 = CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra_deg:.10f}, {dec_deg:.10f}, {radius_deg:.10f}))"
    )


def _num(row: Mapping[str, Any], key: str) -> float | None:
    value = row.get(key)
    if value is None or isinstance(value, (str, bytes)):
        return None
    try:
        if getattr(value, "mask", False) is True:  # numpy masked scalar
            return None
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def gaia_row_to_catalog_source(row: Mapping[str, Any], *, retrieved_utc: str | None = None, source_url: str | None = None) -> CatalogSource:
    """Map one gaiadr3.gaia_source row (documented column names) to CatalogSource."""
    ref_epoch = _num(row, "ref_epoch")
    if ref_epoch is None:
        raise ValueError("row has no ref_epoch")
    nparams = _num(row, "astrometric_params_solved")
    nparams_int = int(nparams) if nparams is not None else None
    solution = SOLUTION_BY_PARAMS.get(nparams_int, "unknown") if nparams_int is not None else "unknown"
    ra, dec = _num(row, "ra"), _num(row, "dec")
    if ra is None or dec is None:
        raise ValueError("row has no position")
    sid = source_id_string(row["source_id"])
    epoch: Epoch = make_epoch(ref_epoch, "jyear", ref.REFERENCE_EPOCH_SCALE)
    correlations = {c: v for c in CORRELATION_COLUMNS if (v := _num(row, c)) is not None}
    two_param = solution == "2-parameter"
    quality: dict[str, float | int | None] = {k: _num(row, k) for k in QUALITY_COLUMNS if k in row}
    if "duplicated_source" in row and row["duplicated_source"] is not None:
        quality["duplicated_source"] = int(bool(row["duplicated_source"]))
    flags: list[str] = []
    messages: list[str] = []
    ruwe = _num(row, "ruwe")
    if ruwe is not None and ruwe > ref.RUWE_THRESHOLD:
        flags.append("RUWE_HIGH")
        messages.append(f"RUWE {ruwe:.2f} > {ref.RUWE_THRESHOLD}: the single-star astrometric model fits poorly (possible binary).")
    if quality.get("duplicated_source"):
        flags.append("DUPLICATED_SOURCE")
        messages.append("duplicated_source: the source was merged from duplicates during processing.")
    if two_param:
        flags.append("NO_PROPER_MOTION")
        messages.append("2-parameter solution: no parallax or proper motion; its position at other epochs is not predictable.")
    return CatalogSource(
        id=f"gaiadr3:{sid}",
        source_id=sid,
        catalog=GAIA_TABLE,
        catalog_release=GAIA_RELEASE,
        origin="catalog",
        reference_epoch=epoch,
        ra_deg=SkyPosition(ra_deg=ra % 360.0, dec_deg=dec).ra_deg,
        dec_deg=dec,
        ra_error_mas=_num(row, "ra_error"),
        dec_error_mas=_num(row, "dec_error"),
        parallax_mas=None if two_param else _num(row, "parallax"),
        parallax_error_mas=None if two_param else _num(row, "parallax_error"),
        pmra_mas_yr=None if two_param else _num(row, "pmra"),
        pmra_error_mas_yr=None if two_param else _num(row, "pmra_error"),
        pmdec_mas_yr=None if two_param else _num(row, "pmdec"),
        pmdec_error_mas_yr=None if two_param else _num(row, "pmdec_error"),
        correlations=correlations,
        radial_velocity_km_s=_num(row, "radial_velocity"),
        radial_velocity_error_km_s=_num(row, "radial_velocity_error"),
        astrometric_solution=solution,  # type: ignore[arg-type]
        astrometric_params_solved=nparams_int,
        quality_indicators=quality,
        photometry={k: _num(row, k) for k in PHOTOMETRY_COLUMNS if k in row} or {"phot_g_mean_mag": _num(row, "phot_g_mean_mag")},
        uncertainty_status="catalog_reported",
        provenance=Provenance(origin="catalog", provider="gaia_dr3", release=GAIA_RELEASE, method=f"ADQL on {GAIA_TABLE}",
                              source_url=source_url, retrieved_utc=retrieved_utc,
                              notes=[f"Values as published in Gaia DR3; reference epoch J{ref_epoch:.1f} (TCB)."]),
        quality=Quality(status="warning" if flags else "ok", flags=flags, messages=messages),
    )


__all__ = ["CORRELATION_COLUMNS", "GAIA_RELEASE", "GAIA_TABLE", "SOLUTION_BY_PARAMS", "build_cone_query", "gaia_row_to_catalog_source"]
