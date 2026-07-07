"""Check cities_seed.csv and codebook.yaml before anything touches the DB.

Catches seed values outside the schema's enums, duplicate or missing ids,
malformed QIDs, and spatial scales the measurements table cannot store.
The allowed-value sets below mirror the enums in schema/001_init.sql —
if an enum changes there, update it here too.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from .codebook import load_codebook, parse_variables
from .paths import CITIES_SEED

# --- mirrored from schema/001_init.sql enums --------------------------------
POPULATION_TIERS = {"mega", "large"}
PROMINENCE_TIERS = {"iconic", "medium", "ordinary"}
DESIGN_ROLES = {
    "anchor_iconic", "secondary_iconic", "secondary_medium",
    "off_diagonal_famous_generic", "off_diagonal_distinctive_lesser_known",
    "ordinary_baseline", "wildcard_distinctive_low_visibility",
}
SV_COVERAGE_STATUS = {"ok", "ok_recent", "ok_dated", "verify"}
# --- entity scales a measurement can target (city/nbhd/point/landmark) -------
ALLOWED_SPATIAL_SCALES = {"point", "neighbourhood", "city", "landmark"}

QID_RE = re.compile(r"^Q[1-9][0-9]*$")
REQUIRED_SEED_COLUMNS = {
    "city_id", "city_name", "country", "region", "population_tier",
    "prominence_tier", "design_role", "sv_coverage_status", "entity_qid", "notes",
}


def _read_seed(path: Path) -> list[dict[str, str]]:
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def validate_seed(rows: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    if not rows:
        return ["seed is empty"]

    missing_cols = REQUIRED_SEED_COLUMNS - set(rows[0].keys())
    if missing_cols:
        errors.append(f"seed missing columns: {sorted(missing_cols)}")
        return errors  # column checks below would be meaningless

    seen_ids: set[str] = set()
    for i, r in enumerate(rows, start=2):  # header is line 1
        cid = r["city_id"]
        if cid in seen_ids:
            errors.append(f"line {i}: duplicate city_id '{cid}'")
        seen_ids.add(cid)
        if not cid or " " in cid or cid != cid.lower():
            errors.append(f"line {i}: city_id '{cid}' should be a lowercase slug")

        for col, allowed in (
            ("population_tier", POPULATION_TIERS),
            ("prominence_tier", PROMINENCE_TIERS),
            ("design_role", DESIGN_ROLES),
            ("sv_coverage_status", SV_COVERAGE_STATUS),
        ):
            val = r[col]
            if val not in allowed:
                errors.append(
                    f"line {i} ({cid}): {col}='{val}' not in schema enum {sorted(allowed)}"
                )

        qid = (r["entity_qid"] or "").strip()
        if qid and not QID_RE.match(qid):
            errors.append(f"line {i} ({cid}): entity_qid '{qid}' is not a valid Wikidata QID")

        if not r["region"].strip():
            errors.append(f"line {i} ({cid}): region is empty")

    return errors


def validate_codebook(codebook: dict) -> list[str]:
    errors: list[str] = []
    for v in parse_variables(codebook):  # also raises on duplicate ids
        if not v.spatial_scales:
            errors.append(f"variable '{v.variable_id}': no spatial_scale")
        bad = set(v.spatial_scales) - ALLOWED_SPATIAL_SCALES
        if bad:
            errors.append(
                f"variable '{v.variable_id}': spatial scale(s) {sorted(bad)} "
                f"are not targetable by measurements {sorted(ALLOWED_SPATIAL_SCALES)}"
            )
    return errors


def validate_all() -> list[str]:
    errors: list[str] = []
    errors += validate_seed(_read_seed(CITIES_SEED))
    try:
        errors += validate_codebook(load_codebook())
    except ValueError as exc:  # duplicate variable ids
        errors.append(str(exc))
    return errors


if __name__ == "__main__":
    import sys
    errs = validate_all()
    if errs:
        print(f"FAIL — {len(errs)} problem(s):")
        for e in errs:
            print(f"  - {e}")
        sys.exit(1)
    print("OK — seed and codebook are consistent with the schema vocabulary.")
