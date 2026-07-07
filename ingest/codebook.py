"""Parse codebook.yaml into rows for the spec tables.

Pure functions (no DB, no network), so this is easy to unit-test.
When the codebook changes, the change enters the pipeline here.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .paths import CODEBOOK_YAML


@dataclass(frozen=True)
class Variable:
    """One row of the ``variables`` spec table, derived from a codebook entry."""
    variable_id: str
    construct: str                       # imageability|cultural_visibility|confound|key
    lynch_element: str | None
    dimension: str | None
    description: str | None
    proxy: str | None
    sources: list[str]
    spatial_scales: list[str]
    role: str | None
    is_temporal: bool
    notes: str | None


def _as_list(value) -> list[str]:
    """Normalise a YAML scalar-or-list field to a list of strings."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return [str(value)]


def _variable_from_entry(entry: dict, construct: str) -> Variable:
    return Variable(
        variable_id=entry["id"],
        construct=construct,
        lynch_element=entry.get("lynch_element"),
        dimension=entry.get("dimension"),
        description=entry.get("description"),
        proxy=entry.get("proxy"),
        sources=_as_list(entry.get("source")),
        spatial_scales=_as_list(entry.get("spatial_scale")),
        role=entry.get("role"),
        # cultural-visibility proxies carry a `temporal:` note when they must be
        # snapshotted in the model's training window.
        is_temporal=bool(entry.get("temporal")),
        notes=entry.get("notes"),
    )


def load_codebook(path: Path = CODEBOOK_YAML) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def parse_variables(codebook: dict) -> list[Variable]:
    """Enumerate every variable id across both constructs, confounds and keys.

    This mirrors the codebook's own structure: ``imageability.variables``,
    ``cultural_visibility.variables``, ``confounds`` and ``keys``.
    """
    out: list[Variable] = []
    for entry in codebook.get("imageability", {}).get("variables", []):
        out.append(_variable_from_entry(entry, "imageability"))
    for entry in codebook.get("cultural_visibility", {}).get("variables", []):
        out.append(_variable_from_entry(entry, "cultural_visibility"))
    for entry in codebook.get("confounds", []):
        out.append(_variable_from_entry(entry, "confound"))
    for entry in codebook.get("keys", []):
        out.append(_variable_from_entry(entry, "key"))

    _assert_unique_ids(out)
    return out


def parse_fabric_strata(codebook: dict) -> list[str]:
    """The 5 fabric strata ids (sampling.fabric_strata.classes)."""
    return list(
        codebook.get("sampling", {}).get("fabric_strata", {}).get("classes", [])
    )


def _assert_unique_ids(variables: list[Variable]) -> None:
    seen: set[str] = set()
    dupes: set[str] = set()
    for v in variables:
        if v.variable_id in seen:
            dupes.add(v.variable_id)
        seen.add(v.variable_id)
    if dupes:
        raise ValueError(f"Duplicate variable ids in codebook: {sorted(dupes)}")


if __name__ == "__main__":
    # Quick self-check: print what would be synced (no DB needed).
    cb = load_codebook()
    vars_ = parse_variables(cb)
    print(f"{len(vars_)} variables parsed from {CODEBOOK_YAML.name}:")
    for v in vars_:
        scales = ",".join(v.spatial_scales)
        flag = " [temporal]" if v.is_temporal else ""
        print(f"  {v.construct:20s} {v.variable_id:24s} ({scales}){flag}")
    print(f"\nfabric strata: {parse_fabric_strata(cb)}")
