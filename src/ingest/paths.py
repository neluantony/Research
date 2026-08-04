"""Canonical file locations, resolved relative to the repository root.

Layout (professor's required structure):
    <repo>/src/            code + config (this package lives here)
    <repo>/data/raw/       read-only input data (the sampling seed)
    <repo>/results/tables/ generated report CSVs
"""
from __future__ import annotations

from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent          # .../src
REPO_ROOT = SRC_DIR.parent                                # repository root

CODEBOOK_YAML = SRC_DIR / "codebook.yaml"
SCHEMA_SQL = SRC_DIR / "schema" / "001_init.sql"
CITIES_SEED = REPO_ROOT / "data" / "raw" / "cities_seed.csv"

RESULTS_TABLES = REPO_ROOT / "results" / "tables"         # generated report CSVs


def results_table(name: str) -> Path:
    """Path for a generated report CSV, creating results/tables/ if needed."""
    RESULTS_TABLES.mkdir(parents=True, exist_ok=True)
    return RESULTS_TABLES / name
