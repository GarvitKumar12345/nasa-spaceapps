"""Integrity seal for a recorded validation study.

A study such as validation/vanmaanen2_motion_stage2.json records the hash of the whole source tree it was computed
from. That hash changes with every edit to the interface, the tests or the documentation, although the recorded numbers
cannot depend on those. Loosening the guard would hide real changes; the seal makes it exact instead.

The seal is made from the original committed reference tree, independently of the legacy whole-tree hash, and records:
  1. the sha256 of the study file itself;
  2. the sha256 of every file the analysis can execute or read: the static import closure of its scripts, the provider
     records (fixtures/gaia_dr3, fixtures/spherex) and the dependency lock;
  3. the text hash of the few shared type declarations (skyshift/contracts.py) that closure imports, together with the
     definitions those refer to, so that appending new API types does not count as an analysis change.

A study is stale when the study file, a sealed file or a sealed definition differs. Changes elsewhere (frontend, tests, the
HTTP layer, documentation, new API types) do not make it stale; application freshness is reported separately. Text files are
hashed with LF line endings, because git checkouts differ by platform (core.autocrlf); binary files are hashed as they are.
A missing or unreadable seal is explicitly unavailable. This is an integrity manifest, not a digital signature or proof of execution.
"""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SEAL_SCHEMA = "skyshift.study_seal/1"
CONTRACTS_FILE = "backend/skyshift/contracts.py"
PACKAGE_ROOT = "backend"  # directory holding the importable `skyshift` package
DATA_DIRS = ("fixtures/gaia_dr3", "fixtures/spherex")  # recorded provider responses and retrieval manifests
LOCK_FILES = ("backend/uv.lock", "backend/pyproject.toml")  # dependency versions that the numbers depend on
TEXT_SUFFIXES = frozenset({".py", ".json", ".csv", ".md", ".toml", ".txt", ".ts", ".tsx", ".css", ".html", ".lock", ".xml"})
RULE = (
    "Stale if the study file, any sealed file or any sealed definition differs from the value recorded here. Changes to other files "
    "(frontend, tests, HTTP layer, documentation, new API types) do not change the recorded numbers and are not stale."
)


class SealError(RuntimeError):
    """The seal cannot be made, or cannot be trusted."""


def canonical_bytes(path: Path) -> bytes:
    """File content as hashed: text files with LF line endings, other files unchanged."""
    data = path.read_bytes()
    return data.replace(b"\r\n", b"\n") if path.suffix.lower() in TEXT_SUFFIXES else data


def sha256_file(path: Path) -> str:
    return hashlib.sha256(canonical_bytes(path)).hexdigest()


# ---------------------------------------------------------------------------
# Definition hashes (shared type declarations)
# ---------------------------------------------------------------------------


def _top_level_definitions(tree: ast.Module) -> dict[str, ast.stmt]:
    defs: dict[str, ast.stmt] = {}
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            defs[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defs[target.id] = node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defs[node.target.id] = node
    return defs


def definition_hashes(source: str, roots: Iterable[str]) -> dict[str, str | None]:
    """sha256 of the text of each named top-level definition and of the same-file definitions it refers to (transitively).

    Names that are not top-level definitions map to None. Text, not the syntax tree, is hashed so that the value does not depend
    on the Python version."""
    source = source.replace("\r\n", "\n")
    tree = ast.parse(source)
    lines = source.split("\n")
    defs = _top_level_definitions(tree)

    def text(node: ast.stmt) -> str:
        first = min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", []))])
        return "\n".join(lines[first - 1 : node.end_lineno])

    wanted: set[str] = set()
    queue = list(roots)
    while queue:
        name = queue.pop()
        if name in wanted:
            continue
        wanted.add(name)
        node = defs.get(name)
        if node is None:
            continue
        for sub in ast.walk(node):
            ref = sub.id if isinstance(sub, ast.Name) else sub.value if isinstance(sub, ast.Constant) and isinstance(sub.value, str) else None
            if ref in defs and ref not in wanted:
                queue.append(ref)  # a name, or a quoted forward reference to a definition of this file
    return {name: (hashlib.sha256(text(defs[name]).encode("utf-8")).hexdigest() if name in defs else None) for name in sorted(wanted)}


# ---------------------------------------------------------------------------
# Scope: what the analysis can execute or read
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Scope:
    python_files: tuple[str, ...]
    data_files: tuple[str, ...]
    contract_symbols: tuple[str, ...]
    excluded: dict[str, str] = field(default_factory=dict)


def _module_file(root: Path, dotted: str) -> Path | None:
    base = root / PACKAGE_ROOT / Path(*dotted.split("."))
    if base.with_suffix(".py").is_file():
        return base.with_suffix(".py")
    if (base / "__init__.py").is_file():
        return base / "__init__.py"
    return None


def _absolute_module(root: Path, path: Path, node: ast.ImportFrom) -> str | None:
    if not node.level:
        return node.module
    try:
        parts = list(path.relative_to(root / PACKAGE_ROOT).parts[:-1])
    except ValueError:
        return None
    base = parts[: len(parts) - (node.level - 1)] if node.level > 1 else parts
    return ".".join([*base, *([node.module] if node.module else [])])


def _imports(root: Path, path: Path) -> tuple[set[str], set[str], set[str], bool]:
    """(candidate skyshift modules, names imported from skyshift.contracts, top-level module names, imports contracts as a whole)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    names: set[str] = set()
    tops: set[str] = set()
    whole = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                tops.add(alias.name.split(".")[0])
                if alias.name.startswith("skyshift"):
                    modules.add(alias.name)
                    whole = whole or alias.name == "skyshift.contracts"
        elif isinstance(node, ast.ImportFrom):
            module = _absolute_module(root, path, node)
            if module is None:
                continue
            tops.add(module.split(".")[0])
            if not module.startswith("skyshift"):
                continue
            modules.add(module)
            for alias in node.names:
                modules.add(f"{module}.{alias.name}")  # a submodule imported by name
                if module == "skyshift.contracts":
                    if alias.name == "*":
                        whole = True
                    else:
                        names.add(alias.name)
    return modules, names, tops, whole


def derive_scope(root: Path, entry_scripts: Sequence[str], excluded: Mapping[str, str]) -> Scope:
    """Static import closure of the entry scripts (skyshift modules and sibling scripts), minus the excluded files."""
    seen: dict[str, Path] = {}
    contract_names: set[str] = set()
    contracts_whole = False
    stack = [root / s for s in entry_scripts]
    while stack:
        path = stack.pop()
        rel = path.relative_to(root).as_posix()
        if rel in excluded:
            continue
        if rel in seen:
            continue
        if not path.is_file():
            raise SealError(f"entry or imported file not found: {rel}")
        seen[rel] = path
        parent = path.parent
        while parent != root / PACKAGE_ROOT and parent.is_relative_to(root / PACKAGE_ROOT):
            init = parent / "__init__.py"
            if init.is_file() and init != path:
                stack.append(init)
            parent = parent.parent
        modules, names, tops, whole = _imports(root, path)
        contract_names |= names
        contracts_whole = contracts_whole or whole
        for dotted in modules:
            target = _module_file(root, dotted)
            if target is not None:
                stack.append(target)
        for top in tops:  # sibling scripts imported through sys.path (scripts/target_motion_stage2.py -> scripts/target_astrometry.py)
            sibling = path.parent / f"{top}.py"
            if path.parent.name == "scripts" and sibling.is_file():
                stack.append(sibling)
    python = sorted(r for r in seen if r not in excluded and (contracts_whole or r != CONTRACTS_FILE))
    data: list[str] = []
    for d in DATA_DIRS:
        base = root / d
        if base.exists():
            data += [p.relative_to(root).as_posix() for p in base.rglob("*") if p.is_file()]
    data += [f for f in LOCK_FILES if (root / f).is_file()]
    return Scope(
        python_files=tuple(python),
        data_files=tuple(sorted(data)),
        contract_symbols=() if contracts_whole else tuple(sorted(contract_names)),
        excluded={k: v for k, v in excluded.items() if k in seen},
    )


# ---------------------------------------------------------------------------
# Make and verify
# ---------------------------------------------------------------------------


def make_seal(
    root: Path,
    study: str,
    entry_scripts: Sequence[str],
    excluded: Mapping[str, str],
    commit: str,
    tree_hash: str,
    sealed_utc: str,
) -> dict[str, Any]:
    """The seal of a study as computed from the tree at `root`. `tree_hash` is that tree's whole-tree source hash, which the caller has
    computed independently; it may differ from the historical pre-commit execution hash."""
    study_path = root / study
    raw = json.loads(study_path.read_text(encoding="utf-8"))
    scope = derive_scope(root, entry_scripts, excluded)
    contracts = definition_hashes((root / CONTRACTS_FILE).read_text(encoding="utf-8"), scope.contract_symbols) if scope.contract_symbols else {}
    missing = [n for n, h in contracts.items() if h is None]
    if missing:
        raise SealError(f"imported from contracts.py but not defined there: {missing}")
    files = {rel: sha256_file(root / rel) for rel in (*scope.python_files, *scope.data_files)}
    return {
        "schema": SEAL_SCHEMA,
        "study": study,
        "study_sha256": sha256_file(study_path),
        "study_generated_utc": raw.get("generated_utc"),
        "study_source_hash": raw["source_hash"],
        "reference_tree_source_hash": tree_hash,
        "execution_hash_matches_reference": raw["source_hash"] == tree_hash,
        "attestation": "Files match the committed reference; the legacy execution hash is preserved, not retrospectively certified.",
        "sealed_at_commit": commit,
        "sealed_utc": sealed_utc,
        "entry_scripts": list(entry_scripts),
        "hashing": "sha256 of file content; text files with CRLF read as LF",
        "files": files,
        "contract_definitions": contracts,
        "excluded": dict(excluded),
        "rule": RULE,
    }


def seal_path(study_file: Path) -> Path:
    return study_file.with_suffix(".seal.json")


def load_seal(study_file: Path) -> dict[str, Any] | None:
    path = seal_path(study_file)
    if not path.is_file():
        return None
    try:
        seal = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return seal if isinstance(seal, dict) and seal.get("schema") == SEAL_SCHEMA else None


def verify_seal(seal: Mapping[str, Any], root: Path) -> list[str]:
    """Differences between the tree at `root` and the sealed state; empty when the study is unchanged."""
    problems: list[str] = []
    study = root / str(seal["study"])
    if not study.is_file():
        problems.append(f"missing: {seal['study']}")
    elif sha256_file(study) != seal["study_sha256"]:
        problems.append(f"changed: {seal['study']} (the recorded study)")
    for rel, digest in seal["files"].items():
        path = root / rel
        if not path.is_file():
            problems.append(f"missing: {rel}")
        elif sha256_file(path) != digest:
            problems.append(f"changed: {rel}")
    sealed = seal.get("contract_definitions") or {}
    if sealed:
        contracts = root / CONTRACTS_FILE
        if not contracts.is_file():
            problems.append(f"missing: {CONTRACTS_FILE}")
        else:
            current = definition_hashes(contracts.read_text(encoding="utf-8"), sealed)
            problems += [f"changed: {CONTRACTS_FILE}::{name}" for name, digest in sealed.items() if current.get(name) != digest]
            source = contracts.read_text(encoding="utf-8")
            imports = [ast.get_source_segment(source, n) for n in ast.parse(source).body if isinstance(n, (ast.Import, ast.ImportFrom))]
            if "contracts_imports" in seal and imports != seal["contracts_imports"]:
                problems.append(f"changed: {CONTRACTS_FILE} imports")
    return problems


def integrity_status(study_file: Path, root: Path) -> dict[str, Any]:
    """Verify committed scientific evidence without running a fit or contacting an archive."""
    seal = load_seal(study_file)
    if seal is None:
        return {"status": "unavailable", "reference_commit": None, "problems": ["Scientific integrity manifest missing or unreadable."],
                "cache_status": "not_checked", "cache_missing": [], "cache_changed": []}
    try:
        paths = [seal["study"], *seal["files"]]
        if seal["study"] != study_file.relative_to(root).as_posix() or any(
            Path(p).is_absolute() or ".." in Path(p).parts or not (root / p).resolve().is_relative_to(root.resolve()) for p in paths
        ):
            raise SealError("Unsafe or mismatched manifest paths")
        problems = verify_seal(seal, root)
        missing, changed = [], []
        from skyshift.providers.spherex.paths import cache_root
        for name, digest in seal.get("cutouts", {}).items():
            if Path(name).name != name:
                raise SealError("Unsafe cutout name")
            p = cache_root() / "spherex-dr1-vanmaanen2" / "cutouts" / name
            if not p.is_file():
                missing.append(name)
            elif hashlib.sha256(p.read_bytes()).hexdigest() != digest:
                changed.append(name)
        problems += [f"changed local cutout: {name}" for name in changed]
        return {"status": "changed" if problems else "verified", "reference_commit": seal["sealed_at_commit"], "problems": problems,
                "cache_status": "changed" if changed else "missing" if missing else "verified", "cache_missing": missing, "cache_changed": changed}
    except (KeyError, TypeError, ValueError, OSError, SyntaxError, SealError) as exc:
        return {"status": "unavailable", "reference_commit": None, "problems": [f"Integrity verification unavailable: {exc}"],
                "cache_status": "not_checked", "cache_missing": [], "cache_changed": []}


__all__ = ["SEAL_SCHEMA", "Scope", "SealError", "definition_hashes", "derive_scope", "load_seal", "make_seal", "seal_path", "sha256_file", "verify_seal"]
