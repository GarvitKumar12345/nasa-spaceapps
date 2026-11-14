"""Export SkyShift contracts to JSON Schema (for TypeScript generation).

Usage (from backend/):  uv run python scripts/export_contracts.py
Writes ../frontend/src/api/contracts.schema.json. The npm script
`npm run gen:contracts` (frontend/) converts it to contracts.gen.ts.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic.json_schema import models_json_schema

from skyshift.contracts import CONTRACTS_VERSION, EXPORTED_MODELS


def _strip_property_titles(node, top=True):
    """Keep model titles (interface names) but drop per-field titles, which
    json-schema-to-typescript would otherwise turn into alias types."""
    if isinstance(node, dict):
        if "$ref" in node:
            # A $ref with sibling keywords (e.g. a field description) makes json2ts
            # emit a duplicate interface; keep the bare reference.
            return {"$ref": node["$ref"]}
        if "prefixItems" in node:
            # Draft 2020-12 tuple -> draft-07 tuple form understood by json2ts.
            node = dict(node)
            items = node.pop("prefixItems")
            node["items"] = items
            node["minItems"] = node.get("minItems", len(items))
            node["maxItems"] = node.get("maxItems", len(items))
        out = {}
        for k, v in node.items():
            if k == "title" and not top:
                continue
            if k == "properties" and isinstance(v, dict):
                out[k] = {pk: _strip_property_titles(pv, top=False) for pk, pv in v.items()}
            else:
                out[k] = _strip_property_titles(v, top=False)
        return out
    if isinstance(node, list):
        return [_strip_property_titles(v, top=False) for v in node]
    return node


def build_schema() -> dict:
    _, defs_schema = models_json_schema(
        [(m, "serialization") for m in EXPORTED_MODELS], ref_template="#/$defs/{model}"
    )
    defs = {name: _strip_property_titles(d) for name, d in defs_schema.get("$defs", {}).items()}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "SkyShiftContracts",
        "description": f"Generated from backend/skyshift/contracts.py ({CONTRACTS_VERSION}). Do not edit.",
        "type": "object",
        "properties": {m.__name__: {"$ref": f"#/$defs/{m.__name__}"} for m in EXPORTED_MODELS},
        "additionalProperties": False,
        "$defs": defs,
    }


def main() -> int:
    out = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api" / "contracts.schema.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build_schema(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
