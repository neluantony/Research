"""Copy the codebook's definitions into the spec tables.

Safe to re-run (upserts). Every measurement must reference a variable
defined here, which is what makes the codebook the source of truth at
database level too.
"""
from __future__ import annotations

import psycopg

from .codebook import load_codebook, parse_fabric_strata, parse_variables


# The codebook lists the accuracy metrics as prose; these are the concrete
# metric ids the scoring step writes into `scores`.
METRICS: list[tuple[str, str, str]] = [
    ("geodesic_error_km", "city",
     "Geodesic distance (km) between predicted and true city location"),
    ("acc@25",  "city", "Prediction within 25 km of the true city"),
    ("acc@200", "city", "Prediction within 200 km of the true city"),
    ("acc@750", "city", "Prediction within 750 km of the true city"),
    ("country_correct", "city", "Predicted country matches the true country"),
    ("region_correct",  "city", "Predicted macro-region matches the true region"),
    ("boundary_correct", "neighbourhood",
     "Prediction falls within the correct neighbourhood boundary"),
]


def sync_fabric_strata(conn: psycopg.Connection) -> int:
    strata = parse_fabric_strata(load_codebook())
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO fabric_strata (stratum_id, description)
            VALUES (%s, NULL)
            ON CONFLICT (stratum_id) DO NOTHING
            """,
            [(s,) for s in strata],
        )
    return len(strata)


def sync_metrics(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO metrics (metric_id, task, description)
            VALUES (%s, %s, %s)
            ON CONFLICT (metric_id) DO UPDATE
              SET task = EXCLUDED.task,
                  description = EXCLUDED.description
            """,
            METRICS,
        )
    return len(METRICS)


def sync_variables(conn: psycopg.Connection) -> int:
    variables = parse_variables(load_codebook())
    rows = [
        (
            v.variable_id, v.construct, v.lynch_element, v.dimension,
            v.description, v.proxy, v.sources, v.spatial_scales, v.role,
            v.is_temporal, v.notes,
        )
        for v in variables
    ]
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO variables (
                variable_id, construct, lynch_element, dimension, description,
                proxy, sources, spatial_scales, role, is_temporal, notes
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (variable_id) DO UPDATE SET
                construct      = EXCLUDED.construct,
                lynch_element  = EXCLUDED.lynch_element,
                dimension      = EXCLUDED.dimension,
                description    = EXCLUDED.description,
                proxy          = EXCLUDED.proxy,
                sources        = EXCLUDED.sources,
                spatial_scales = EXCLUDED.spatial_scales,
                role           = EXCLUDED.role,
                is_temporal    = EXCLUDED.is_temporal,
                notes          = EXCLUDED.notes
            """,
            rows,
        )
    return len(rows)


def sync_all(conn: psycopg.Connection) -> dict[str, int]:
    counts = {
        "fabric_strata": sync_fabric_strata(conn),
        "metrics": sync_metrics(conn),
        "variables": sync_variables(conn),
    }
    conn.commit()
    return counts
