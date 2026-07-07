"""The inference loop: images in, raw model answers out.

One run = one model x one prompt version x one task. For every pending
point (4 views on disk, not yet answered by this model+prompt) it loads the
views in N/E/S/W order, calls the provider, and stores the raw answer plus
which exact views were shown. Commits per point, so a run can be stopped
and resumed anytime — answered points are skipped. Scoring happens
elsewhere and never touches these rows.
"""
from __future__ import annotations

import json


def parse_city_fields(parsed: dict | None) -> dict:
    """Map the city-task JSON to model_responses columns (None-safe)."""
    if not parsed:
        return {"pred_city": None, "pred_country": None,
                "pred_lat": None, "pred_lon": None, "reasoning_text": None}
    return {
        "pred_city": parsed.get("city"),
        "pred_country": parsed.get("country"),
        "pred_lat": parsed.get("latitude"),
        "pred_lon": parsed.get("longitude"),
        "reasoning_text": parsed.get("reasoning"),
    }


def parse_neighbourhood_fields(parsed: dict | None) -> dict:
    """Neighbourhood task: the name is free text; pred_neighbourhood_id is
    resolved against boundaries at SCORING time, not here."""
    if not parsed:
        return {"pred_city": None, "pred_country": None,
                "pred_lat": None, "pred_lon": None, "reasoning_text": None}
    return {
        "pred_city": parsed.get("neighbourhood"),   # free-text name, resolved later
        "pred_country": None, "pred_lat": None, "pred_lon": None,
        "reasoning_text": parsed.get("reasoning"),
    }


# Models see the text-blurred stimuli by default (codebook v0.3.8); the
# unblurred originals are used only for the OCR-reliance ablation.
DEFAULT_SCHEME = "cardinal4_blurred_v1"


def pending_points(conn, model_id: int, prompt_id: int, task: str,
                   limit: int | None = None,
                   scheme: str = DEFAULT_SCHEME) -> list[tuple]:
    """Points whose views (of the given scheme) this model+prompt hasn't
    answered yet.

    Returns (point_id, city_name, country, [view_id...], [crop_path...]),
    views ordered by heading (N, E, S, W). For the neighbourhood task only
    points inside an eligible neighbourhood qualify. The answered-check is
    scheme-aware, so a blurred run and an unblurred ablation on the same
    point coexist."""
    nbhd_filter = (
        "AND EXISTS (SELECT 1 FROM neighbourhoods n "
        "            WHERE n.neighbourhood_id = p.neighbourhood_id "
        "            AND n.eligible_for_nbhd_task) "
        if task == "neighbourhood" else "")
    q = f"""
        SELECT p.point_id, c.city_name, c.country,
               array_agg(v.view_id ORDER BY v.heading_deg),
               array_agg(v.crop_path ORDER BY v.heading_deg)
        FROM points p
        JOIN cities c USING (city_id)
        JOIN images i ON i.point_id = p.point_id
        JOIN views v ON v.image_id = i.image_id AND v.presentation_scheme = %s
        WHERE NOT EXISTS (
            SELECT 1 FROM model_responses mr
            JOIN inference_runs ir ON ir.run_id = mr.inference_run_id
            JOIN response_stimuli rs ON rs.response_id = mr.response_id
            JOIN views v2 ON v2.view_id = rs.view_id
            JOIN images i2 ON i2.image_id = v2.image_id
            WHERE ir.model_id = %s AND ir.prompt_id = %s
              AND v2.presentation_scheme = %s
              AND i2.point_id = p.point_id)
        {nbhd_filter}
        GROUP BY p.point_id, c.city_name, c.country
        ORDER BY p.point_id
        """
    with conn.cursor() as cur:
        if limit:
            cur.execute(q + " LIMIT %s", (scheme, model_id, prompt_id, scheme, limit))
        else:
            cur.execute(q, (scheme, model_id, prompt_id, scheme))
        return cur.fetchall()


def create_run(conn, model_id: int, prompt_id: int, config: dict) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO inference_runs (model_id, prompt_id, "
            "presentation_config_json, retrieval_disabled) "
            "VALUES (%s, %s, %s, true) RETURNING run_id",
            (model_id, prompt_id, json.dumps(config)))
        return cur.fetchone()[0]


def store_response(conn, run_id: int, task: str, result: dict,
                   view_ids: list[int]) -> None:
    fields = (parse_city_fields(result["parsed"]) if task == "city"
              else parse_neighbourhood_fields(result["parsed"]))
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO model_responses (
                inference_run_id, task, raw_output_json, pred_lat, pred_lon,
                pred_city, pred_country, reasoning_text, latency_ms, tokens
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING response_id
            """,
            (run_id, task, json.dumps(result["raw"]),
             fields["pred_lat"], fields["pred_lon"], fields["pred_city"],
             fields["pred_country"], fields["reasoning_text"],
             result["latency_ms"], result["tokens"]))
        response_id = cur.fetchone()[0]
        cur.executemany(
            "INSERT INTO response_stimuli (response_id, view_id, position) "
            "VALUES (%s, %s, %s)",
            [(response_id, vid, pos) for pos, vid in enumerate(view_ids)])
    conn.commit()


def run(conn, provider, model_id: int, prompt_row: dict, task: str,
        limit: int | None = None, write: bool = False,
        scheme: str = DEFAULT_SCHEME) -> dict:
    """Drive one inference pass. prompt_row: {prompt_id, text, output_schema}."""
    todo = pending_points(conn, model_id, prompt_row["prompt_id"], task, limit,
                          scheme=scheme)
    if not write:
        return {"pending": len(todo), "answered": 0, "failed": 0}

    run_id = create_run(conn, model_id, prompt_row["prompt_id"], {
        "presentation_scheme": scheme,
        "images_per_point": 4, "order": "N,E,S,W",
    })
    conn.commit()

    answered = failed = 0
    for point_id, city_name, country, view_ids, paths in todo:
        prompt_text = prompt_row["text"].format(city_name=city_name, country=country) \
            if task == "neighbourhood" else prompt_row["text"]
        try:
            result = provider.complete(prompt_text, paths, prompt_row["output_schema"])
        except Exception as exc:
            failed += 1
            print(f"  [error] point {point_id}: {exc}", flush=True)
            continue
        store_response(conn, run_id, task, result, view_ids)
        answered += 1
        if answered % 50 == 0:
            print(f"  ... {answered}/{len(todo)} answered", flush=True)
    return {"pending": len(todo), "answered": answered, "failed": failed,
            "run_id": run_id}
