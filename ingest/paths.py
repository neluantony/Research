"""Canonical file locations, resolved relative to the repository root."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CODEBOOK_YAML = REPO_ROOT / "codebook.yaml"
CITIES_SEED = REPO_ROOT / "cities_seed.csv"
SCHEMA_SQL = REPO_ROOT / "schema" / "001_init.sql"
