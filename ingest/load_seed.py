"""Load cities_seed.csv into the regions and cities tables.

Safe to re-run: descriptive columns update, but values resolved later
(QIDs, frame geometry) are never overwritten with blanks from the seed.
Empty QIDs stay NULL — they are resolved from Wikidata, never made up.
"""
from __future__ import annotations

import csv
from pathlib import Path

import psycopg

from .paths import CITIES_SEED


def _read_seed(path: Path) -> list[dict[str, str]]:
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def load_regions(conn: psycopg.Connection, rows: list[dict[str, str]]) -> int:
    """Controlled vocab of macro-regions, derived from the seed's region column."""
    regions = sorted({r["region"] for r in rows})
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO regions (region_id, notes)
            VALUES (%s, NULL)
            ON CONFLICT (region_id) DO NOTHING
            """,
            [(r,) for r in regions],
        )
    return len(regions)


def load_cities(conn: psycopg.Connection, rows: list[dict[str, str]]) -> int:
    params = []
    for r in rows:
        qid = (r.get("entity_qid") or "").strip() or None
        notes = (r.get("notes") or "").strip() or None
        params.append((
            r["city_id"], r["city_name"], r["country"], r["region"],
            r["population_tier"], r["prominence_tier"], r["design_role"],
            r["sv_coverage_status"], qid, notes,
        ))
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO cities (
                city_id, city_name, country, region_id, population_tier,
                prominence_tier, design_role, sv_coverage_status,
                entity_qid, notes
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (city_id) DO UPDATE SET
                city_name          = EXCLUDED.city_name,
                country            = EXCLUDED.country,
                region_id          = EXCLUDED.region_id,
                population_tier    = EXCLUDED.population_tier,
                prominence_tier    = EXCLUDED.prominence_tier,
                design_role        = EXCLUDED.design_role,
                sv_coverage_status = EXCLUDED.sv_coverage_status,
                -- preserve a resolved QID; never overwrite it with an empty seed value
                entity_qid         = COALESCE(cities.entity_qid, EXCLUDED.entity_qid),
                notes              = EXCLUDED.notes
            """,
            params,
        )
    return len(params)


def load_all(conn: psycopg.Connection) -> dict[str, int]:
    rows = _read_seed(CITIES_SEED)
    counts = {
        "regions": load_regions(conn, rows),  # must precede cities (FK)
        "cities": load_cities(conn, rows),
    }
    conn.commit()
    return counts
