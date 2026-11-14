"""Catalog epoch propagation and cross-matching.

Catalog positions refer to the catalog reference epoch (Gaia DR3: J2016.0, TCB).
They are propagated to each observation epoch before matching:

  * space motion: linear in gnomonic coordinates about the catalog position
    (exact for straight-line motion with radial velocity 0; when a radial
    velocity and a positive parallax are present, astropy apply_space_motion
    is used instead);
  * observer parallax: parallax * parallax factors of the observer at the
    observation epoch (separate geometry; never inverted into a distance);
  * uncertainties: full 5x5 covariance from the catalog errors/correlations,
    propagated linearly. 2-parameter solutions (no parallax/pm) are not
    propagated; their uncertainty is inflated by an explicit pm allowance.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import astropy.units as u
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.time import Time

from skyshift.contracts import (
    AssociationCandidate,
    CatalogAssociation,
    CatalogSource,
    Epoch,
    ObserverModel,
    PropagatedPosition,
)
from skyshift.coords.observer import GEOCENTER_BUILTIN, observer_barycentric_au
from skyshift.coords.tangent import angular_separation_deg, apply_offsets_mas, offsets_mas
from skyshift.coords.time import JULIAN_YEAR_DAYS
from skyshift.science.astrometry import parallax_factors

CATALOG_METHOD_VERSION = "1.0.0"
DEFAULT_PM_ALLOWANCE_MAS_YR = 20.0

# Gaia DR3 correlation column for each (i, j) of the parameter order below.
PARAM_ORDER = ("ra", "dec", "parallax", "pmra", "pmdec")
CORRELATION_NAMES: dict[tuple[int, int], str] = {
    (0, 1): "ra_dec_corr",
    (0, 2): "ra_parallax_corr",
    (0, 3): "ra_pmra_corr",
    (0, 4): "ra_pmdec_corr",
    (1, 2): "dec_parallax_corr",
    (1, 3): "dec_pmra_corr",
    (1, 4): "dec_pmdec_corr",
    (2, 3): "parallax_pmra_corr",
    (2, 4): "parallax_pmdec_corr",
    (3, 4): "pmra_pmdec_corr",
}


@dataclass(frozen=True)
class ImagePoint:
    """A measured image position to associate with catalog sources."""

    source_id: str
    measurement_id: str | None
    ra_deg: float
    dec_deg: float
    sigma_ra_cosdec_mas: float
    sigma_dec_mas: float


def has_full_astrometry(src: CatalogSource) -> bool:
    return None not in (src.parallax_mas, src.pmra_mas_yr, src.pmdec_mas_yr, src.parallax_error_mas, src.pmra_error_mas_yr, src.pmdec_error_mas_yr)


def catalog_covariance(src: CatalogSource) -> np.ndarray:
    """5x5 covariance (mas, mas, mas, mas/yr, mas/yr) in PARAM_ORDER; zeros for absent parameters."""
    sig = np.array(
        [
            src.ra_error_mas or 0.0,
            src.dec_error_mas or 0.0,
            src.parallax_error_mas or 0.0,
            src.pmra_error_mas_yr or 0.0,
            src.pmdec_error_mas_yr or 0.0,
        ],
        dtype=float,
    )
    corr = np.eye(5)
    for (i, j), name in CORRELATION_NAMES.items():
        value = src.correlations.get(name)
        if value is not None:
            corr[i, j] = corr[j, i] = float(value)
    return corr * np.outer(sig, sig)


def propagate_catalog_source(
    src: CatalogSource,
    epoch: Epoch,
    observer: ObserverModel = GEOCENTER_BUILTIN,
    include_parallax: bool = True,
    pm_allowance_mas_yr: float = DEFAULT_PM_ALLOWANCE_MAS_YR,
) -> PropagatedPosition:
    """Predicted apparent position of a catalog source at `epoch` (model prediction)."""
    dt = (epoch.mjd_tdb - src.reference_epoch.mjd_tdb) / JULIAN_YEAR_DAYS
    notes: list[str] = []
    cov5 = catalog_covariance(src)
    full = has_full_astrometry(src)
    if full:
        pmra, pmdec, plx = float(src.pmra_mas_yr), float(src.pmdec_mas_yr), float(src.parallax_mas)  # type: ignore[arg-type]
        rv = src.radial_velocity_km_s
        if rv is not None and plx > 0:
            c = SkyCoord(
                ra=src.ra_deg * u.deg,
                dec=src.dec_deg * u.deg,
                distance=(1000.0 / plx) * u.pc,
                pm_ra_cosdec=pmra * u.mas / u.yr,
                pm_dec=pmdec * u.mas / u.yr,
                radial_velocity=rv * u.km / u.s,
                obstime=Time(src.reference_epoch.mjd_tdb, format="mjd", scale="tdb"),
            ).apply_space_motion(new_obstime=Time(epoch.mjd_tdb, format="mjd", scale="tdb"))
            east_sm, north_sm = offsets_mas(c.ra.deg, c.dec.deg, src.ra_deg, src.dec_deg)
            east_sm, north_sm = float(east_sm), float(north_sm)
            method = "astropy apply_space_motion (catalog radial velocity) + observer parallax factors"
        else:
            east_sm, north_sm = pmra * dt, pmdec * dt
            method = "linear gnomonic space motion (radial velocity 0) + observer parallax factors"
            if rv is None:
                notes.append("Radial velocity missing: space motion propagated with radial velocity 0 (exact for straight-line motion; perspective acceleration neglected).")
        f_ra = f_dec = 0.0
        apply_plx = include_parallax
        if apply_plx:
            fr, fd = parallax_factors(src.ra_deg, src.dec_deg, observer_barycentric_au(np.array([epoch.mjd_tdb]), observer))
            f_ra, f_dec = float(fr[0]), float(fd[0])
            if plx <= 0:
                notes.append(f"Catalog parallax {plx:.3g} mas is not positive; applied as a statistical estimate in the parallax term (never inverted).")
        east = east_sm + plx * f_ra
        north = north_sm + plx * f_dec
        jac = np.array([[1.0, 0.0, f_ra, dt, 0.0], [0.0, 1.0, f_dec, 0.0, dt]])
        cov2 = jac @ cov5 @ jac.T
        includes_sm, includes_plx = True, apply_plx
    else:
        east = north = 0.0
        allowance = pm_allowance_mas_yr * abs(dt)
        cov2 = cov5[:2, :2] + np.diag([allowance**2, allowance**2])
        method = "not propagated (2-parameter solution: no proper motion or parallax)"
        notes.append(
            f"{src.astrometric_solution} solution: position kept at the catalog epoch; uncertainty inflated by an assumed "
            f"proper-motion allowance of {pm_allowance_mas_yr:g} mas/yr x |dt| = {allowance:.1f} mas."
        )
        includes_sm, includes_plx = False, False
    ra, dec = apply_offsets_mas(east, north, src.ra_deg, src.dec_deg)
    s_e, s_n = math.sqrt(max(cov2[0, 0], 0.0)), math.sqrt(max(cov2[1, 1], 0.0))
    corr = float(cov2[0, 1] / (s_e * s_n)) if s_e > 0 and s_n > 0 else None
    return PropagatedPosition(
        catalog_source_id=src.id,
        epoch=epoch,
        ra_deg=float(ra),
        dec_deg=float(dec),
        sigma_ra_cosdec_mas=s_e if s_e > 0 else None,
        sigma_dec_mas=s_n if s_n > 0 else None,
        corr_ra_dec=corr,
        includes_space_motion=includes_sm,
        includes_observer_parallax=includes_plx,
        method=f"{method} (catalog epoch {src.reference_epoch.value} {src.reference_epoch.format} {src.reference_epoch.scale.upper()} -> MJD {epoch.mjd_tdb:.5f} TDB, dt = {dt:+.3f} yr)",
        notes=notes,
    )


def padded_search_radius_deg(
    field_radius_deg: float,
    catalog_epoch: Epoch,
    observation_epochs: Sequence[Epoch],
    max_pm_arcsec_yr: float = 5.0,
    margin_arcsec: float = 2.0,
) -> float:
    """Search radius that includes sources moving into the field between the catalog and observation epochs."""
    if not observation_epochs:
        return field_radius_deg + margin_arcsec / 3600.0
    dt_max = max(abs(e.mjd_tdb - catalog_epoch.mjd_tdb) for e in observation_epochs) / JULIAN_YEAR_DAYS
    return field_radius_deg + (max_pm_arcsec_yr * dt_max + margin_arcsec) / 3600.0


def _combined_cov(point: ImagePoint, prop: PropagatedPosition) -> np.ndarray:
    se = prop.sigma_ra_cosdec_mas or 0.0
    sn = prop.sigma_dec_mas or 0.0
    rho = prop.corr_ra_dec or 0.0
    cat = np.array([[se * se, rho * se * sn], [rho * se * sn, sn * sn]])
    img = np.diag([point.sigma_ra_cosdec_mas**2, point.sigma_dec_mas**2])
    return cat + img


def associate(
    points: Sequence[ImagePoint],
    catalog: Sequence[CatalogSource],
    epoch: Epoch,
    observer: ObserverModel = GEOCENTER_BUILTIN,
    resolution_arcsec: float = 1.0,
    n_sigma: float = 5.0,
    propagated: Sequence[PropagatedPosition] | None = None,
) -> list[CatalogAssociation]:
    """Associate image points with catalog sources propagated to `epoch`.

    Radius per pair: max(n_sigma * combined sigma, 0.5 * resolution). A point
    is 'matched' only when exactly one catalog source lies within its radius,
    that source has no other catalog source within the resolution (no blend),
    and the point is the nearest image point to it. Otherwise 'ambiguous'
    (all candidates kept) or 'unmatched' (none). No counterpart is invented.
    """
    props = list(propagated) if propagated is not None else [propagate_catalog_source(s, epoch, observer) for s in catalog]
    if not props:
        return [
            CatalogAssociation(
                image_source_id=p.source_id, measurement_id=p.measurement_id, epoch=epoch, status="not_evaluated",
                match_radius_arcsec=0.0, criteria="no catalog sources supplied",
                notes=["No catalog sources were available for this field and epoch."],
            )
            for p in points
        ]
    cra = np.array([pp.ra_deg for pp in props])
    cdec = np.array([pp.dec_deg for pp in props])
    # Catalog sources closer to each other than the resolution form blends.
    blend: dict[int, list[int]] = {}
    for i in range(len(props)):
        sep = angular_separation_deg(cra[i], cdec[i], cra, cdec) * 3600.0
        blend[i] = [j for j in np.flatnonzero(sep < resolution_arcsec) if j != i]
    pra = np.array([p.ra_deg for p in points])
    pdec = np.array([p.dec_deg for p in points])
    criteria = (
        f"radius = max({n_sigma:g} x combined sigma, 0.5 x resolution {resolution_arcsec:.2f}\"); unique candidate, "
        "no catalog blend within the resolution, and mutual nearest neighbour"
    )
    out: list[CatalogAssociation] = []
    for k, point in enumerate(points):
        sep_arcsec = angular_separation_deg(point.ra_deg, point.dec_deg, cra, cdec) * 3600.0
        candidates: list[AssociationCandidate] = []
        radii: list[float] = []
        for i, prop in enumerate(props):
            cov = _combined_cov(point, prop)
            sigma_arcsec = math.sqrt(max(np.linalg.eigvalsh(cov).max(), 0.0)) / 1000.0
            radius = max(n_sigma * sigma_arcsec, 0.5 * resolution_arcsec)
            radii.append(radius)
            if sep_arcsec[i] <= radius:
                de, dn = offsets_mas(prop.ra_deg, prop.dec_deg, point.ra_deg, point.dec_deg)
                d = np.array([float(de), float(dn)])
                maha = float(math.sqrt(d @ np.linalg.solve(cov, d))) if np.linalg.det(cov) > 0 else None
                candidates.append(AssociationCandidate(catalog_source_id=prop.catalog_source_id, separation_arcsec=float(sep_arcsec[i]),
                                                       normalized_separation=maha, propagated=prop))
        candidates.sort(key=lambda c: c.separation_arcsec)
        notes: list[str] = []
        if not candidates:
            status = "unmatched"
            notes.append("No catalog counterpart within the match radius at this epoch. This is not by itself evidence of a new object: the source may be below the catalog limit, blended, or spurious.")
        elif len(candidates) > 1:
            status = "ambiguous"
            notes.append(f"{len(candidates)} catalog sources lie within the match radius; all candidates are kept.")
        else:
            i = next(j for j, pp in enumerate(props) if pp.catalog_source_id == candidates[0].catalog_source_id)
            others = angular_separation_deg(cra[i], cdec[i], pra, pdec) * 3600.0
            nearest_point = int(np.argmin(others))
            if blend[i]:
                status = "ambiguous"
                notes.append(f"The candidate has {len(blend[i])} other catalog source(s) within the image resolution ({resolution_arcsec:.2f}\"): possible blend.")
            elif nearest_point != k and others[nearest_point] < sep_arcsec[i]:
                status = "ambiguous"
                notes.append("Another image source is closer to this catalog source (not a mutual nearest neighbour).")
            else:
                status = "matched"
        out.append(
            CatalogAssociation(
                image_source_id=point.source_id,
                measurement_id=point.measurement_id,
                epoch=epoch,
                status=status,  # type: ignore[arg-type]
                candidates=candidates,
                match_radius_arcsec=float(max(radii)) if candidates else float(min(radii)),
                criteria=criteria,
                notes=notes,
            )
        )
    return out


__all__ = [
    "CATALOG_METHOD_VERSION",
    "ImagePoint",
    "associate",
    "catalog_covariance",
    "has_full_astrometry",
    "padded_search_radius_deg",
    "propagate_catalog_source",
]
