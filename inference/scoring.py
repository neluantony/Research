"""Turn stored model answers into scores.

City task: distance error in km (panorama -> predicted coordinates),
accuracy within 25/200/750 km, and city / country / macro-region match.
Neighbourhood task: does the predicted name match the neighbourhood the
point actually lies in. Scoring only reads model_responses and writes
scores; raw answers are never touched, and a new scoring_version can
coexist with old scores. Name matching uses normalised equality or
word-level containment ("Marais" matches "Le Marais") — a documented
simplification.
"""
from __future__ import annotations

import math

from .geo import countries_match, normalize_name, region_for_country

SCORING_VERSION = "v1"
ACCURACY_KM = (25, 200, 750)

METRICS = [
    ("geodesic_error_km", "city", "Geodesic distance (km) from panorama to predicted coordinates"),
    ("acc_25km", "city", "1 if geodesic error <= 25 km"),
    ("acc_200km", "city", "1 if geodesic error <= 200 km"),
    ("acc_750km", "city", "1 if geodesic error <= 750 km"),
    ("city_match", "city", "1 if predicted city name matches the true city (normalized/containment)"),
    ("country_match", "city", "1 if predicted country matches (normalized, alias-aware)"),
    ("region_match", "city", "1 if predicted country's macro-region cell matches the city's"),
    ("nbhd_boundary_match", "neighbourhood",
     "1 if the predicted name matches the containing neighbourhood (normalized/containment)"),
]


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6_371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def names_match(pred: str | None, true: str | None) -> bool:
    """Normalized equality or containment either way (multiword only)."""
    a, b = normalize_name(pred), normalize_name(true)
    if not a or not b:
        return False
    return a == b or f" {a} " in f" {b} " or f" {b} " in f" {a} "


def score_city(pred: dict, truth: dict) -> dict[str, float]:
    """pred: pred_lat/pred_lon/pred_city/pred_country (may be None on refusal).
    truth: lat/lon/city_name/country/region. Missing prediction -> worst case
    (max error is capped at half Earth circumference; matches 0)."""
    out: dict[str, float] = {}
    if pred.get("pred_lat") is not None and pred.get("pred_lon") is not None:
        err = haversine_km(pred["pred_lon"], pred["pred_lat"],
                           truth["lon"], truth["lat"])
    else:
        err = 20_037.5  # no coordinates given: antipodal worst case
    out["geodesic_error_km"] = round(err, 2)
    for km in ACCURACY_KM:
        out[f"acc_{km}km"] = 1.0 if err <= km else 0.0
    out["city_match"] = 1.0 if names_match(pred.get("pred_city"), truth["city_name"]) else 0.0
    out["country_match"] = 1.0 if countries_match(pred.get("pred_country"), truth["country"]) else 0.0
    pred_region = region_for_country(pred.get("pred_country"))
    out["region_match"] = 1.0 if (pred_region is not None
                                  and pred_region == truth["region"]) else 0.0
    return out


def score_neighbourhood(pred_name: str | None, true_name: str | None) -> dict[str, float]:
    return {"nbhd_boundary_match": 1.0 if names_match(pred_name, true_name) else 0.0}


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------

def register_metrics(conn) -> int:
    with conn.cursor() as cur:
        for metric_id, task, description in METRICS:
            cur.execute(
                "INSERT INTO metrics (metric_id, task, description) "
                "VALUES (%s, %s, %s) "
                "ON CONFLICT (metric_id) DO UPDATE SET "
                "task = EXCLUDED.task, description = EXCLUDED.description",
                (metric_id, task, description))
    return len(METRICS)


_TRUTH_JOIN = """
    FROM model_responses mr
    JOIN response_stimuli rs ON rs.response_id = mr.response_id AND rs.position = 0
    JOIN views v ON v.view_id = rs.view_id
    JOIN images i ON i.image_id = v.image_id
    JOIN points p ON p.point_id = i.point_id
    JOIN cities c ON c.city_id = p.city_id
"""


def pending(conn, task: str, scoring_version: str = SCORING_VERSION) -> list[tuple]:
    nbhd_col = ("(SELECT n.name FROM neighbourhoods n "
                " WHERE n.neighbourhood_id = p.neighbourhood_id)")
    q = f"""
        SELECT mr.response_id, mr.pred_lat, mr.pred_lon, mr.pred_city,
               mr.pred_country, ST_Y(p.snapped_geom), ST_X(p.snapped_geom),
               c.city_name, c.country, c.region_id, {nbhd_col}
        {_TRUTH_JOIN}
        WHERE mr.task = %s AND NOT EXISTS (
            SELECT 1 FROM scores s
            WHERE s.response_id = mr.response_id AND s.scoring_version = %s)
        ORDER BY mr.response_id
        """
    with conn.cursor() as cur:
        cur.execute(q, (task, scoring_version))
        return cur.fetchall()


def score_task(conn, task: str, scoring_version: str = SCORING_VERSION,
               write: bool = False) -> dict:
    todo = pending(conn, task, scoring_version)
    rows = []
    for (response_id, plat, plon, pcity, pcountry,
         tlat, tlon, tcity, tcountry, tregion, tnbhd) in todo:
        if task == "city":
            scores = score_city(
                {"pred_lat": plat, "pred_lon": plon,
                 "pred_city": pcity, "pred_country": pcountry},
                {"lat": tlat, "lon": tlon, "city_name": tcity,
                 "country": tcountry, "region": tregion})
        else:
            # neighbourhood task: pred_city holds the predicted nbhd name
            scores = score_neighbourhood(pcity, tnbhd)
        rows.extend((response_id, mid, val, scoring_version)
                    for mid, val in scores.items())
    if write and rows:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO scores (response_id, metric_id, value, scoring_version) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (response_id, metric_id, scoring_version) DO NOTHING",
                rows)
        conn.commit()
    return {"responses": len(todo), "scores": len(rows), "written": bool(write and rows)}


def summary(conn, scoring_version: str = SCORING_VERSION) -> list[tuple]:
    """Per model x task: n, mean geodesic error, median error, accuracy rates."""
    q = """
        SELECT m.name, mr.task, count(DISTINCT mr.response_id) AS n,
               round(avg(s.value) FILTER (WHERE s.metric_id = 'geodesic_error_km')::numeric, 1),
               round((percentile_cont(0.5) WITHIN GROUP (ORDER BY s.value)
                      FILTER (WHERE s.metric_id = 'geodesic_error_km'))::numeric, 1),
               round(avg(s.value) FILTER (WHERE s.metric_id = 'acc_25km')::numeric, 3),
               round(avg(s.value) FILTER (WHERE s.metric_id = 'acc_200km')::numeric, 3),
               round(avg(s.value) FILTER (WHERE s.metric_id = 'country_match')::numeric, 3),
               round(avg(s.value) FILTER (WHERE s.metric_id = 'city_match')::numeric, 3),
               round(avg(s.value) FILTER (WHERE s.metric_id = 'nbhd_boundary_match')::numeric, 3)
        FROM scores s
        JOIN model_responses mr ON mr.response_id = s.response_id
        JOIN inference_runs ir ON ir.run_id = mr.inference_run_id
        JOIN models m ON m.model_id = ir.model_id
        WHERE s.scoring_version = %s
        GROUP BY m.name, mr.task ORDER BY m.name, mr.task
        """
    with conn.cursor() as cur:
        cur.execute(q, (scoring_version,))
        return cur.fetchall()
