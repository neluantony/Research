"""Sync prompts (inference/prompts.py) and models (models_seed.yaml) to the DB.

Safe to re-run. Models with an empty exact_version_string are skipped with
a warning: version identifiers must be checked against the provider's docs
by hand — a guessed identifier would make runs untraceable.
"""
from __future__ import annotations

import json
from pathlib import Path

from .prompts import PROMPTS

MODELS_SEED = Path(__file__).resolve().parent.parent / "models_seed.yaml"


def register_prompts(conn) -> int:
    n = 0
    with conn.cursor() as cur:
        for p in PROMPTS:
            cur.execute(
                """
                INSERT INTO prompts (prompt_version, task, text, output_schema_json)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (prompt_version, task) DO UPDATE SET
                    text = EXCLUDED.text,
                    output_schema_json = EXCLUDED.output_schema_json
                """,
                (p["prompt_version"], p["task"], p["text"],
                 json.dumps(p["output_schema"])),
            )
            n += 1
    return n


def load_models_seed(path: Path = MODELS_SEED) -> tuple[list[dict], list[str]]:
    """(registrable models, names skipped for missing version strings)."""
    import yaml

    with open(path, "r", encoding="utf-8") as fh:
        entries = yaml.safe_load(fh)["models"]
    ready = [m for m in entries if (m.get("exact_version_string") or "").strip()]
    skipped = [m["name"] for m in entries
               if not (m.get("exact_version_string") or "").strip()]
    return ready, skipped


def register_models(conn) -> tuple[int, list[str]]:
    ready, skipped = load_models_seed()
    with conn.cursor() as cur:
        for m in ready:
            cur.execute(
                """
                INSERT INTO models (name, exact_version_string, family,
                                    open_weight, training_window_start,
                                    training_window_end, access)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (name, exact_version_string) DO UPDATE SET
                    family = EXCLUDED.family,
                    open_weight = EXCLUDED.open_weight,
                    training_window_start = EXCLUDED.training_window_start,
                    training_window_end = EXCLUDED.training_window_end,
                    access = EXCLUDED.access
                """,
                (m["name"], m["exact_version_string"], m.get("family"),
                 m["open_weight"], m.get("training_window_start"),
                 m.get("training_window_end"), m["access"]),
            )
    return len(ready), skipped
