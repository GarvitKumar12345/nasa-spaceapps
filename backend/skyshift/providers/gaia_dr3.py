"""Gaia DR3 catalog provider boundary.

Implemented offline: the explicit ADQL query builder and the mapping of a
gaiadr3.gaia_source row to the CatalogSource contract. Not implemented: the
network query (planned: ESA Gaia TAP via astroquery.gaia with
Gaia.MAIN_GAIA_TABLE set explicitly). Epoch propagation lives in
skyshift.science.catalog.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from skyshift.contracts import CatalogSource, Epoch, ProviderStatus, Provenance, Quality, Reference, SkyPosition
from skyshift.coords.time import make_epoch
from skyshift.providers.archive_common import BRIEF_REVIEW_UTC, DOC_NOTE, cap
from skyshift.providers.base import ProviderUnavailable

GAIA_TABLE = "gaiadr3.gaia_source"
GAIA_RELEASE = "Gaia DR3"
CORRELATION_COLUMNS = (
    "ra_dec_corr", "ra_parallax_corr", "ra_pmra_corr", "ra_pmdec_corr", "dec_parallax_corr",
    "dec_pmra_corr", "dec_pmdec_corr", "parallax_pmra_corr", "parallax_pmdec_corr", "pmra_pmdec_corr",
)
GAIA_COLUMNS = (
    "source_id", "ref_epoch", "ra", "dec", "ra_error", "dec_error", "parallax", "parallax_error",
    "pmra", "pmra_error", "pmdec", "pmdec_error", *CORRELATION_COLUMNS, "astrometric_params_solved",
    "ruwe", "astrometric_excess_noise", "phot_g_mean_mag", "radial_velocity", "radial_velocity_error",
)
SOLUTION_BY_PARAMS = {3: "2-parameter", 31: "5-parameter", 95: "6-parameter"}
REFERENCES = [
    Reference(title="Gaia DR3 documentation (ESA)", url="https://gea.esac.esa.int/archive/documentation/GDR3/"),
    Reference(title="Astroquery Gaia TAP", url="https://docs.astropy.org/projects/astroquery/en/stable/gaia/gaia.html"),
    Reference(title="Gaia mission resources at MAST", url="https://archive.stsci.edu/missions-and-data/gaia"),
]


def build_cone_query(ra_deg: float, dec_deg: float, radius_deg: float, row_limit: int = 2000) -> str:
    """ADQL cone search on gaiadr3.gaia_source with explicit columns and a TOP limit."""
    if not (0 < radius_deg <= 1.0):
        raise ValueError("radius_deg must be in (0, 1] for a bounded query")
    if not (0 < row_limit <= 100_000):
        raise ValueError("row_limit must be in (0, 100000]")
    cols = ", ".join(GAIA_COLUMNS)
    return (
        f"SELECT TOP {int(row_limit)} {cols} FROM {GAIA_TABLE} "
        f"WHERE 1 = CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra_deg:.10f}, {dec_deg:.10f}, {radius_deg:.10f}))"
    )


def _num(row: Mapping[str, Any], key: str) -> float | None:
    value = row.get(key)
    if value is None:
        return None
    try:
        if getattr(value, "mask", False) is True:  # numpy masked scalar
            return None
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def gaia_row_to_catalog_source(row: Mapping[str, Any]) -> CatalogSource:
    """Map one gaiadr3.gaia_source row (documented column names) to CatalogSource.

    The reference epoch is kept in its own convention (jyear, TCB) — never
    relabelled as UTC. NaN/masked values become None; a missing radial velocity
    stays None. ra_error is sigma of RA*cos(Dec) in mas (Gaia convention).
    """
    ref_epoch = _num(row, "ref_epoch")
    if ref_epoch is None:
        raise ValueError("row has no ref_epoch")
    nparams = row.get("astrometric_params_solved")
    nparams_int = int(nparams) if nparams is not None and _num(row, "astrometric_params_solved") is not None else None
    solution = SOLUTION_BY_PARAMS.get(nparams_int, "unknown") if nparams_int is not None else "unknown"
    ra, dec = _num(row, "ra"), _num(row, "dec")
    if ra is None or dec is None:
        raise ValueError("row has no position")
    epoch: Epoch = make_epoch(ref_epoch, "jyear", "tcb")
    correlations = {c: v for c in CORRELATION_COLUMNS if (v := _num(row, c)) is not None}
    two_param = solution == "2-parameter"
    return CatalogSource(
        id=f"gaiadr3:{int(row['source_id'])}",
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
        quality_indicators={k: _num(row, k) for k in ("ruwe", "astrometric_excess_noise")},
        photometry={"phot_g_mean_mag": _num(row, "phot_g_mean_mag")},
        uncertainty_status="catalog_reported",
        provenance=Provenance(origin="catalog", provider="gaia_dr3", release=GAIA_RELEASE, method=f"ADQL on {GAIA_TABLE}",
                              notes=["Values as published in Gaia DR3; reference epoch J2016.0 (TCB) unless the row states otherwise."]),
        quality=Quality(status="ok"),
    )


class GaiaDR3Provider:
    id = "gaia_dr3"

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            id="gaia_dr3",
            name="Gaia DR3 reference catalog (ESA)",
            role="catalog",
            status="documented",
            release_policy=f"Pinned: {GAIA_RELEASE}, table {GAIA_TABLE} selected explicitly (never a changing default; not EDR3).",
            access_route=f"Planned: ESA Gaia TAP via astroquery.gaia with an explicit ADQL query on {GAIA_TABLE} (bounded, padded cone).",
            capabilities=[
                cap("ADQL query builder", "implemented", f"Explicit columns from {GAIA_TABLE} with a TOP limit (build_cone_query)."),
                cap("Row -> CatalogSource mapping", "implemented", "2/5/6-parameter solutions, Gaia correlations, J2016.0 TCB kept, NaN -> None."),
                cap("Epoch propagation + observer parallax", "implemented", "skyshift.science.catalog.propagate_catalog_source (shared with the simulated catalog)."),
                cap("Cross-matching with ambiguity handling", "implemented", "skyshift.science.catalog.associate (matched / ambiguous / unmatched)."),
                cap("Catalog query (network)", "not_implemented", "No TAP request is made by this build."),
                cap("Live DR3 query check", "not_run", "No live request has been made from this build."),
            ],
            references=REFERENCES,
            notes=[DOC_NOTE, "Gaia returns catalog records, not image frames. A Gaia non-detection is not evidence of a new object."],
            last_reviewed_utc=BRIEF_REVIEW_UTC,
        )

    def query_region(self, center: SkyPosition, radius_deg: float, observation_epochs: list[Epoch]) -> list[CatalogSource]:
        raise ProviderUnavailable("gaia_dr3", "query_region", "network query not implemented in this build; see docs/providers/gaia_dr3.md")
