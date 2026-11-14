"""SPHEREx discovery through IRSA SIA2 with an explicit collection.

The query is a bounded cone (`POS=CIRCLE ra dec r`) in one named collection;
results are parsed by column name. Duplicate processing versions of the same
exposure and detector are never combined silently: one is kept by a stated
rule and the others are reported.
"""

from __future__ import annotations

import io
import re
import urllib.parse
import warnings
from dataclasses import asdict, dataclass

import numpy as np
from astropy.io.votable import parse
from astropy.io.votable.exceptions import VOWarning

from skyshift.providers.spherex.reference import COLLECTIONS, UNSUPPORTED_COLLECTIONS

SIA_ENDPOINT = "https://irsa.ipac.caltech.edu/SIA"
MAX_RADIUS_DEG = 0.05  # small bounded queries only
REQUIRED_COLUMNS = (
    "obs_id", "obs_collection", "energy_bandpassname", "t_min", "t_max", "t_exptime", "em_min", "em_max",
    "access_url", "s_region", "obs_publisher_did", "dataproduct_subtype", "calib_level",
)
_FILENAME = re.compile(r"^level2_(?P<obs>.+?)D(?P<det>[1-6])_spx_(?P<tag>l2b[-_A-Za-z0-9]*)\.fits$")
_TAG = re.compile(r"v(?P<ver>\d+)-(?P<year>\d{4})-(?P<doy>\d{3})")


class DiscoveryError(ValueError):
    """The service answered, but not with a usable SIA2 result."""


def check_collection(collection: str) -> None:
    if collection in UNSUPPORTED_COLLECTIONS:
        raise ValueError(f"{collection}: {UNSUPPORTED_COLLECTIONS[collection]}")
    if collection not in COLLECTIONS:
        raise ValueError(f"unknown SPHEREx collection {collection!r}; choose one of {sorted(COLLECTIONS)}")


def build_sia_url(collection: str, ra_deg: float, dec_deg: float, radius_deg: float) -> str:
    """Exact SIA2 request URL (recorded in manifests so the query can be repeated verbatim)."""
    check_collection(collection)
    if not (0.0 < radius_deg <= MAX_RADIUS_DEG):
        raise ValueError(f"radius must be in (0, {MAX_RADIUS_DEG}] deg for a bounded query")
    if not (-90.0 <= dec_deg <= 90.0):
        raise ValueError("dec out of range")
    params = {"COLLECTION": collection, "POS": f"CIRCLE {ra_deg % 360.0:.7f} {dec_deg:.7f} {radius_deg:.6f}", "RESPONSEFORMAT": "VOTABLE"}
    return f"{SIA_ENDPOINT}?{urllib.parse.urlencode(params)}"


@dataclass(frozen=True)
class DiscoveryRow:
    obs_id: str
    collection: str
    detector: int
    bandpass_name: str
    t_min_mjd: float  # SIA t_min/t_max: MJD; equal to header MJD-BEG/MJD-END (TIMESYS=UTC), checked per file
    t_max_mjd: float
    t_exptime_s: float
    em_min_um: float
    em_max_um: float
    access_url: str
    file_name: str
    processing_tag: str
    processing_version: int | None
    processing_date: str | None  # YYYY-DDD
    s_region: str
    obs_publisher_did: str
    dataproduct_subtype: str
    calib_level: int

    @property
    def key(self) -> tuple[str, int]:
        return (self.obs_id, self.detector)

    def as_dict(self) -> dict:
        return asdict(self)


def parse_processing_tag(access_url: str) -> tuple[str, str, int, int | None, str | None]:
    """(file_name, tag, detector, version, YYYY-DDD) from a Spectral Image URL."""
    name = urllib.parse.urlparse(access_url).path.rsplit("/", 1)[-1]
    m = _FILENAME.match(name)
    if not m:
        raise DiscoveryError(f"unexpected Spectral Image file name {name!r}")
    tag = m.group("tag")
    t = _TAG.search(tag)
    return name, tag, int(m.group("det")), (int(t.group("ver")) if t else None), (f"{t.group('year')}-{t.group('doy')}" if t else None)


def _text(v: object) -> str:
    if isinstance(v, bytes):
        return v.decode()
    if np.ma.is_masked(v):
        return ""
    return str(v)


def parse_sia_votable(body: bytes, collection: str) -> list[DiscoveryRow]:
    """Parse an SIA2 VOTable by column name; rows from any other collection are rejected."""
    check_collection(collection)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", VOWarning)
        vot = parse(io.BytesIO(body))
    for res in vot.resources:
        for info in res.infos:
            if info.name == "QUERY_STATUS" and str(info.value).upper() == "ERROR":
                raise DiscoveryError(f"SIA2 QUERY_STATUS=ERROR: {info.content or ''}".strip())
            if info.name == "QUERY_STATUS" and str(info.value).upper() == "OVERFLOW":
                raise DiscoveryError("SIA2 result truncated (QUERY_STATUS=OVERFLOW); narrow the query")
    table = vot.get_first_table().to_table(use_names_over_ids=True)
    missing = [c for c in REQUIRED_COLUMNS if c not in table.colnames]
    if missing:
        raise DiscoveryError(f"SIA2 response lacks columns {missing}")
    rows: list[DiscoveryRow] = []
    for r in table:
        coll = _text(r["obs_collection"])
        if coll != collection:
            raise DiscoveryError(f"row {_text(r['obs_id'])} belongs to {coll!r}, not the requested {collection!r}")
        url = _text(r["access_url"])
        name, tag, det, ver, date = parse_processing_tag(url)
        band = _text(r["energy_bandpassname"])
        if band != f"SPHEREx-D{det}":
            raise DiscoveryError(f"{name}: bandpass {band!r} disagrees with detector D{det} in the file name")
        obs_id = _text(r["obs_id"])
        if not name.startswith(f"level2_{obs_id}D{det}_"):
            raise DiscoveryError(f"{name}: file name does not match obs_id {obs_id!r}")
        rows.append(
            DiscoveryRow(
                obs_id=obs_id, collection=coll, detector=det, bandpass_name=band,
                t_min_mjd=float(r["t_min"]), t_max_mjd=float(r["t_max"]), t_exptime_s=float(r["t_exptime"]),
                em_min_um=float(r["em_min"]) * 1e6, em_max_um=float(r["em_max"]) * 1e6,
                access_url=url, file_name=name, processing_tag=tag, processing_version=ver, processing_date=date,
                s_region=_text(r["s_region"]), obs_publisher_did=_text(r["obs_publisher_did"]),
                dataproduct_subtype=_text(r["dataproduct_subtype"]), calib_level=int(r["calib_level"]),
            )
        )
    return sorted(rows, key=lambda x: (x.t_min_mjd, x.detector, x.obs_id))


def resolve_duplicates(rows: list[DiscoveryRow]) -> tuple[list[DiscoveryRow], list[dict]]:
    """Keep one product per (obs_id, detector): highest processing version, then latest processing date.

    Returns (kept, superseded) where each superseded entry names the kept product.
    """
    by_key: dict[tuple[str, int], list[DiscoveryRow]] = {}
    for r in rows:
        by_key.setdefault(r.key, []).append(r)
    kept: list[DiscoveryRow] = []
    superseded: list[dict] = []
    for group in by_key.values():
        ordered = sorted(group, key=lambda r: (r.processing_version or -1, r.processing_date or "", r.processing_tag), reverse=True)
        kept.append(ordered[0])
        for other in ordered[1:]:
            superseded.append({"obs_id": other.obs_id, "detector": other.detector, "file_name": other.file_name, "kept": ordered[0].file_name,
                               "rule": "highest processing version, then latest processing date"})
    return sorted(kept, key=lambda x: (x.t_min_mjd, x.detector, x.obs_id)), superseded


def parse_s_region(s_region: str) -> list[tuple[float, float]]:
    """Corner list of an ObsCore 'POLYGON ICRS ra1 dec1 ...' (or 'POLYGON ra1 dec1 ...') region."""
    toks = s_region.replace(",", " ").split()
    if not toks or toks[0].upper() != "POLYGON":
        raise DiscoveryError(f"unsupported s_region {s_region[:40]!r}")
    nums = [t for t in toks[1:] if not t.isalpha()]
    vals = [float(t) for t in nums]
    if len(vals) < 6 or len(vals) % 2:
        raise DiscoveryError("s_region polygon needs at least three (ra, dec) pairs")
    return [(vals[i] % 360.0, vals[i + 1]) for i in range(0, len(vals), 2)]
