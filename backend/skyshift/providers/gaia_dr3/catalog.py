"""Parse and check a recorded gaiadr3.gaia_source TAP response.

Source identifiers are 64-bit integers (up to ~6.9e18), beyond the 2^53 range a
JavaScript number or a float64 represents exactly. They are converted once,
from the VOTable 'long' column, to decimal strings and stay strings in every
contract, API response and frontend structure. No float conversion is ever
applied to them.
"""

from __future__ import annotations

import gzip
import io
import re
import warnings
from dataclasses import dataclass, field

import astropy.units as u
import numpy as np
from astropy.io.votable import parse

from skyshift.contracts import FileCheck
from skyshift.providers.gaia_dr3 import reference as ref

SOURCE_ID_RE = re.compile(r"^[1-9][0-9]{0,18}$")
INT64_MAX = 2**63 - 1
BOOLEAN_COLUMNS = frozenset(c.name for c in ref.FIELD_COLUMNS if c.datatypes == ("boolean",))
INTEGER_DATATYPES = ("unsignedByte", "short", "int", "long")


class GaiaResponseError(ValueError):
    """The TAP response is not a usable gaiadr3.gaia_source result."""


def source_id_string(value: object) -> str:
    """Exact decimal string of a Gaia source_id; refuses floats (which may already have lost digits)."""
    if isinstance(value, (bool, float, np.floating)):
        raise TypeError(f"source_id must be an integer type, got {type(value).__name__}")
    if isinstance(value, str):
        s = value.strip()
    elif isinstance(value, (int, np.integer)):
        s = str(int(value))
    else:
        raise TypeError(f"source_id must be an integer or decimal string, got {type(value).__name__}")
    if not SOURCE_ID_RE.match(s) or int(s) > INT64_MAX:
        raise ValueError(f"not a Gaia source_id: {s!r}")
    return s


@dataclass
class GaiaField:
    name: str
    unit: str | None
    datatype: str
    ucd: str | None


@dataclass
class GaiaCatalog:
    source_id: list[str]
    columns: dict[str, np.ndarray]  # numeric -> float64 with NaN for NULL; booleans -> bool; strings -> object
    null: dict[str, np.ndarray]  # True where the archive returned NULL
    fields: list[GaiaField]
    infos: dict[str, str]
    params: dict[str, str]
    coosys: list[dict[str, str | None]]
    sha256: str | None = None
    index: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.index = {sid: i for i, sid in enumerate(self.source_id)}

    def __len__(self) -> int:
        return len(self.source_id)

    def value(self, name: str, i: int) -> float | bool | str | None:
        if self.null[name][i]:
            return None
        v = self.columns[name][i]
        if isinstance(v, (np.floating, float)):
            return float(v)
        if isinstance(v, (np.bool_, bool)):
            return bool(v)
        return v if not isinstance(v, bytes) else v.decode()

    def row(self, i: int) -> dict[str, object]:
        out: dict[str, object] = {"source_id": self.source_id[i]}
        for name in self.columns:
            out[name] = self.value(name, i)
        return out


def parse_gaia_votable(body: bytes) -> GaiaCatalog:
    """Parse a TAP VOTable (plain or gzip) into a GaiaCatalog; columns are read by name."""
    raw = gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        vot = parse(io.BytesIO(raw))
    if not vot.resources:
        raise GaiaResponseError("VOTable has no RESOURCE")
    res = vot.resources[0]
    all_infos = [(i.name, str(i.value)) for r in vot.resources for i in r.infos] + [(i.name, str(i.value)) for i in vot.infos]
    infos = {name: value for name, value in all_infos if name != "QUERY_STATUS"}
    # TAP/DALI: an overflow is reported by an additional QUERY_STATUS INFO *after* the table, while the first
    # one still says OK. Every QUERY_STATUS value is therefore inspected, not only the first.
    statuses = [value for name, value in all_infos if name == "QUERY_STATUS"]
    infos["QUERY_STATUS"] = "ERROR" if "ERROR" in statuses else "OVERFLOW" if "OVERFLOW" in statuses else (statuses[0] if statuses else "")
    infos["QUERY_STATUS_ALL"] = ",".join(statuses)
    params = {p.name: str(p.value) for p in res.params}
    coosys = [{"system": c.system, "epoch": c.epoch, "equinox": c.equinox} for r in vot.resources for c in r.coordinate_systems]
    coosys += [{"system": c.system, "epoch": c.epoch, "equinox": c.equinox} for c in vot.coordinate_systems]
    if infos["QUERY_STATUS"] == "ERROR":
        raise GaiaResponseError(f"TAP QUERY_STATUS=ERROR: {infos}")
    tables = list(vot.iter_tables())
    if len(tables) != 1:
        raise GaiaResponseError(f"expected one result table, found {len(tables)}")
    vt = tables[0]
    fields = [GaiaField(f.name, str(f.unit) if f.unit is not None else None, f.datatype, f.ucd) for f in vt.fields]
    names = [f.name for f in fields]
    if "source_id" not in names:
        raise GaiaResponseError("response has no source_id column")
    arr = vt.array
    sid_col = arr["source_id"]
    if np.any(np.ma.getmaskarray(sid_col)):
        raise GaiaResponseError("NULL source_id in response")
    if sid_col.dtype.kind not in "iu":
        raise GaiaResponseError(f"source_id column is {sid_col.dtype}, not an integer type")
    source_ids = [source_id_string(v) for v in np.asarray(sid_col.data)]
    columns: dict[str, np.ndarray] = {}
    null: dict[str, np.ndarray] = {}
    for f in fields:
        if f.name == "source_id":
            continue
        col = arr[f.name]
        mask = np.ma.getmaskarray(col).copy()
        data = np.asarray(col.data)
        if f.name in BOOLEAN_COLUMNS and data.dtype.kind in "iu" and set(np.unique(data[~mask]).tolist()) <= {0, 1}:
            data = data.astype(bool)  # a documented boolean delivered as 0/1 integers by a partner service (datatype checked separately)
        if data.dtype.kind in "fiu":
            vals = data.astype(float)
            mask |= ~np.isfinite(vals)
            vals = np.where(mask, np.nan, vals)
        elif data.dtype.kind == "b":
            vals = data.astype(bool)
        else:
            vals = np.array([v.decode() if isinstance(v, bytes) else str(v) for v in data], dtype=object)
        columns[f.name] = vals
        null[f.name] = mask
    return GaiaCatalog(source_id=source_ids, columns=columns, null=null, fields=fields, infos=infos, params=params, coosys=coosys)


def _unit_equal(found: str | None, expected: str | None) -> bool:
    if expected is None:
        return found in (None, "", "None")
    if found in (None, "", "None"):
        return False
    try:
        return u.Unit(found) == u.Unit(expected)
    except ValueError:
        return False


def _epoch_label(e: object) -> str:
    s = str(e).strip().upper()
    s = s[1:] if s.startswith("J") else s
    return f"J{float(s):.1f}" if re.fullmatch(r"[0-9]+(\.[0-9]*)?", s) else str(e)


def schema_checks(cat: GaiaCatalog, *, expected_columns: tuple[ref.ColumnSpec, ...] = ref.FIELD_COLUMNS, expected_rows: int | None = None,
                  service: str = "esa") -> list[FileCheck]:
    """Checks of the response against the documented data model and provenance (each pass/fail with detail).

    For the ESA archive (the archive of record) the RELEASE parameter and COOSYS J2016.0 are required. A partner data
    centre does not declare RELEASE and may write the COOSYS epoch as '2016' or omit it: these become 'warn', and the
    release identity rests instead on the explicit table name plus the recorded row-for-row verification of that
    service against the ESA response (checked by load_recorded_field), never on the service's word alone."""
    out: list[FileCheck] = []
    by_name = {f.name: f for f in cat.fields}
    missing = [c.name for c in expected_columns if c.name not in by_name]
    unexpected = [n for n in by_name if n not in {c.name for c in expected_columns}]
    out.append(FileCheck(id="columns", status="pass" if not missing and not unexpected else "fail",
                         detail=f"{len(by_name)} columns by name; missing {missing or 'none'}; unexpected {unexpected or 'none'}",
                         reference="Gaia DR3 data model: gaiadr3.gaia_source"))
    bad_units = [f"{c.name}: {by_name[c.name].unit!r} != {c.unit!r}" for c in expected_columns if c.name in by_name and not _unit_equal(by_name[c.name].unit, c.unit)]
    out.append(FileCheck(id="units", status="pass" if not bad_units else "fail",
                         detail="all column units equal the documented units (astropy unit comparison)" if not bad_units else "; ".join(bad_units),
                         reference="Gaia DR3 data model: gaiadr3.gaia_source"))
    bad_types = [f"{c.name}: {by_name[c.name].datatype}" for c in expected_columns if c.name in by_name and by_name[c.name].datatype not in c.datatypes]
    # A partner service may deliver a documented boolean as 0/1 integers; the parser reads it as boolean only if every value is 0 or 1.
    as_int_bool = [b for b in bad_types if service != "esa" and b.split(":")[0] in BOOLEAN_COLUMNS and b.split(": ")[1] in INTEGER_DATATYPES
                   and cat.columns[b.split(":")[0]].dtype.kind == "b"]
    hard = [b for b in bad_types if b not in as_int_bool]
    out.append(FileCheck(id="datatypes", status="fail" if hard else ("warn" if as_int_bool else "pass"),
                         detail=("VOTable datatypes as documented (source_id is 'long')" if not bad_types else "; ".join(hard) if hard else
                                 f"documented booleans delivered as 0/1 integers by {service!r}, read as boolean: {', '.join(as_int_bool)}")))
    release = cat.params.get("RELEASE")
    if service == "esa" or release is not None:
        out.append(FileCheck(id="release", status="pass" if release == ref.GAIA_RELEASE else "fail",
                             detail=f"VOTable PARAM RELEASE = {release!r} (expected {ref.GAIA_RELEASE!r})", reference="ESA Gaia archive TAP response metadata"))
    else:
        out.append(FileCheck(id="release", status="warn",
                             detail=f"service {service!r} declares no RELEASE parameter; Gaia DR3 identity rests on the table name {ref.GAIA_TABLE} and the "
                                    "row-for-row verification of this service against the ESA-recorded reference response"))
    query = cat.infos.get("QUERY", "")
    out.append(FileCheck(id="table", status="pass" if f"FROM {ref.GAIA_TABLE} " in query else "fail",
                         detail=f"query recorded by the service names {ref.GAIA_TABLE}" if f"FROM {ref.GAIA_TABLE} " in query else f"query text: {query[:120]!r}"))
    epochs = {c.get("epoch") for c in cat.coosys}
    systems = {c.get("system") for c in cat.coosys}
    if service == "esa":
        out.append(FileCheck(id="coosys", status="pass" if epochs == {ref.COOSYS_EPOCH} and systems == {"ICRS"} else "fail",
                             detail=f"COOSYS system {sorted(map(str, systems))}, epoch {sorted(map(str, epochs))} (expected ICRS, {ref.COOSYS_EPOCH})"))
    elif not cat.coosys:
        out.append(FileCheck(id="coosys", status="warn",
                             detail=f"service {service!r} declares no COOSYS; positions are ICRS at the reference epoch per the Gaia DR3 data model "
                                    "and ref_epoch = 2016.0 is checked on every row"))
    else:
        labels = {_epoch_label(e) for e in epochs}
        out.append(FileCheck(id="coosys", status="pass" if labels == {ref.COOSYS_EPOCH} and systems == {"ICRS"} else "fail",
                             detail=f"COOSYS system {sorted(map(str, systems))}, epoch {sorted(map(str, epochs))} read as {sorted(labels)} (expected ICRS, {ref.COOSYS_EPOCH})"))
    status = cat.infos.get("QUERY_STATUS")
    out.append(FileCheck(id="query_status", status="pass" if status == "OK" else "fail",
                         detail=f"QUERY_STATUS = {status!r} (OVERFLOW would mean a truncated result)"))
    if "ref_epoch" in cat.columns:
        re_vals = cat.columns["ref_epoch"][~cat.null["ref_epoch"]]
        ok = len(re_vals) == len(cat) and bool(np.all(re_vals == ref.REFERENCE_EPOCH_JYEAR))
        out.append(FileCheck(id="ref_epoch", status="pass" if ok else "fail",
                             detail=f"ref_epoch = {ref.REFERENCE_EPOCH_JYEAR} (Julian year, TCB) for {len(re_vals)} of {len(cat)} rows"))
    unique = len(set(cat.source_id)) == len(cat.source_id)
    ordered = all(int(a) < int(b) for a, b in zip(cat.source_id, cat.source_id[1:]))
    out.append(FileCheck(id="source_ids", status="pass" if unique and ordered else "fail",
                         detail=f"{len(cat)} decimal-string source_ids, unique={unique}, ascending={ordered} (ORDER BY source_id)"))
    if "astrometric_params_solved" in cat.columns:
        aps = cat.columns["astrometric_params_solved"]
        codes = sorted({int(v) for v in aps[np.isfinite(aps)]})
        unknown = [c for c in codes if c not in ref.SOLUTION_BY_PARAMS]
        two = np.isfinite(aps) & (aps == 3)
        nulls_ok = all(bool(np.all(cat.null[c][two])) for c in ("parallax", "pmra", "pmdec") if c in cat.null)
        full = np.isfinite(aps) & (aps != 3)
        present_ok = all(not bool(np.any(cat.null[c][full])) for c in ("parallax", "pmra", "pmdec", "parallax_error", "pmra_error", "pmdec_error") if c in cat.null)
        out.append(FileCheck(id="solution_types", status="pass" if not unknown and nulls_ok and present_ok else "fail",
                             detail=f"astrometric_params_solved codes {codes}; 2-parameter rows have NULL parallax/pm: {nulls_ok}; "
                                    f"5/6-parameter rows have parallax/pm and errors: {present_ok}"))
    if expected_rows is not None:
        out.append(FileCheck(id="row_count", status="pass" if expected_rows == len(cat) else "fail",
                             detail=f"{len(cat)} rows returned; independent COUNT(*) of the same circle = {expected_rows}"))
    return out


__all__ = ["GaiaCatalog", "GaiaField", "GaiaResponseError", "parse_gaia_votable", "schema_checks", "source_id_string"]
