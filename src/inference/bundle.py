"""Export a self-contained inference bundle for Google Colab, and import the
results back.

Colab cannot reach the local PostgreSQL database, so the open-weight models
run there as a pure worker: this module writes a folder with the stimulus
images, the prompt text and the answer schema, plus a manifest listing the
points (with NO ground truth, so the models are not told where they are).
The Colab notebook reads that folder and emits one responses JSONL; the
import step below loads it back into model_responses so scoring and the
analyses run unchanged on the local DB.

The stimulus is a 2x2 grid of the four blurred cardinal views composed into
one image (top-left N, top-right E, bottom-left S, bottom-right W), one
portable image every VLM can take, including single-image models.
"""
from __future__ import annotations

import json
from pathlib import Path

SOURCE_SCHEME = "cardinal4_blurred_v1"     # the 4 blurred views we compose from
GRID_SCHEME = "grid2x2_blurred_v1"          # the composed stimulus we present
CELL_PX = 640                                # source crops are 640x640
GUTTER_PX = 8                                # black separator so adjacent
                                             # cardinal views don't read as one
                                             # continuous panorama


# ---------------------------------------------------------------------------
# grid composition
# ---------------------------------------------------------------------------

def compose_grid(paths_nesw: list, out_path: str | Path, cell: int = CELL_PX,
                 gutter: int = GUTTER_PX) -> None:
    """Compose 4 crops (ordered N, E, S, W) into a 2x2 grid image, with a
    black gutter between cells.

    Layout:  [ N | E ]
             [ S | W ]
    """
    import cv2
    import numpy as np

    if len(paths_nesw) != 4:
        raise ValueError(f"need exactly 4 views, got {len(paths_nesw)}")
    cells = []
    for p in paths_nesw:
        img = cv2.imread(str(p))
        if img is None:
            raise ValueError(f"cannot read view: {p}")
        cells.append(cv2.resize(img, (cell, cell)))
    side = 2 * cell + gutter
    grid = np.zeros((side, side, 3), dtype=np.uint8)   # black canvas = gutters
    far = cell + gutter                                 # top-left of 2nd cell
    grid[0:cell, 0:cell] = cells[0]        # N  top-left
    grid[0:cell, far:far + cell] = cells[1]  # E  top-right
    grid[far:far + cell, 0:cell] = cells[2]  # S  bottom-left
    grid[far:far + cell, far:far + cell] = cells[3]  # W  bottom-right
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(out_path), grid):
        raise IOError(f"cannot write grid: {out_path}")


# ---------------------------------------------------------------------------
# point selection (the SAME balanced subset as the Gemini pilot)
# ---------------------------------------------------------------------------

def pilot_points(conn, per_city: int) -> list[tuple]:
    """The fixed per-city subset (per_city/5 points per stratum, ranked by
    point_id) with the 4 blurred crop paths per point, ordered N,E,S,W.

    Identical ranking to harness.pending_points' --per-city filter, but with
    no answered-check, so the subset is exactly the pilot's 124 points."""
    per_stratum = max(1, per_city // 5)
    q = """
        SELECT p.point_id,
               array_agg(v.crop_path ORDER BY v.heading_deg),
               array_agg(v.view_id ORDER BY v.heading_deg)
        FROM points p
        JOIN images i ON i.point_id = p.point_id
        JOIN views v ON v.image_id = i.image_id
                    AND v.presentation_scheme = %s
        WHERE p.point_id IN (
            SELECT point_id FROM (
                SELECT p2.point_id,
                       row_number() OVER (PARTITION BY p2.city_id, p2.stratum_id
                                          ORDER BY p2.point_id) AS rn
                FROM points p2
                JOIN images i2 ON i2.point_id = p2.point_id
            ) ranked WHERE rn <= %s)
        GROUP BY p.point_id
        ORDER BY p.point_id
        """
    with conn.cursor() as cur:
        cur.execute(q, (SOURCE_SCHEME, per_stratum))
        return cur.fetchall()


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

def export_bundle(conn, out_dir: str | Path, per_city: int,
                  prompt_version: str = "city_grid_v1") -> dict:
    """Write grids/, manifest.jsonl, prompt_city.txt and schema_city.json."""
    out = Path(out_dir)
    (out / "grids").mkdir(parents=True, exist_ok=True)

    with conn.cursor() as cur:
        cur.execute("SELECT text, output_schema_json FROM prompts "
                    "WHERE task = 'city' AND prompt_version = %s", (prompt_version,))
        row = cur.fetchone()
    if not row:
        raise SystemExit(f"prompt '{prompt_version}' not in DB, run "
                         "`python -m inference register` first")
    prompt_text, schema = row
    schema = schema if isinstance(schema, dict) else json.loads(schema)

    (out / "prompt_city.txt").write_text(prompt_text, encoding="utf-8")
    (out / "schema_city.json").write_text(json.dumps(schema, indent=2), encoding="utf-8")

    points = pilot_points(conn, per_city)
    manifest = []
    for point_id, crop_paths, view_ids in points:
        rel = f"grids/{point_id}.jpg"
        compose_grid(crop_paths, out / rel)
        # view_ids kept so the import can link the response to the exact 4
        # underlying views (scoring joins position 0 -> point -> truth)
        manifest.append({"point_id": point_id, "image": rel,
                         "view_ids": list(view_ids)})

    with open(out / "manifest.jsonl", "w", encoding="utf-8") as fh:
        for m in manifest:
            fh.write(json.dumps(m) + "\n")

    meta = {"scheme": GRID_SCHEME, "prompt_version": prompt_version,
            "source_scheme": SOURCE_SCHEME, "n_points": len(manifest),
            "cell_px": CELL_PX}
    (out / "bundle_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


# ---------------------------------------------------------------------------
# import (load a Colab responses JSONL back into the local DB)
# ---------------------------------------------------------------------------

def _read_manifest(bundle_dir: Path) -> dict:
    """point_id -> [view_id, ...] (the 4 views under each grid)."""
    out = {}
    with open(bundle_dir / "manifest.jsonl", encoding="utf-8") as fh:
        for line in fh:
            m = json.loads(line)
            out[m["point_id"]] = m["view_ids"]
    return out


def lenient_recover(raw_text: str | None) -> dict | None:
    """Pull the city-task fields out of a malformed model answer.

    Weak open models often emit JSON with unquoted keys ({city: "Accra"}) or
    truncate it mid-way when they hit the token cap. Strict json.loads rejects
    both, throwing away a real geolocation. Here the four fields that scoring
    needs are grabbed by regex, which survives unquoted keys and truncation
    (the scalars come before the cues/reasoning that get cut off)."""
    import re

    if not raw_text:
        return None

    def grab_str(key):
        m = re.search(rf'["\']?{key}["\']?\s*:\s*["\']([^"\']+)["\']', raw_text)
        return m.group(1) if m else None

    def grab_num(key):
        m = re.search(rf'["\']?{key}["\']?\s*:\s*(-?\d+(?:\.\d+)?)', raw_text)
        return float(m.group(1)) if m else None

    city = grab_str("city")
    lat, lon = grab_num("latitude"), grab_num("longitude")
    if city is None and lat is None:
        return None
    return {"city": city, "country": grab_str("country"),
            "latitude": lat, "longitude": lon,
            "confidence": grab_num("confidence"),
            "cues": [], "reasoning": grab_str("reasoning")}


def _upsert_model(conn, meta: dict) -> int:
    """Model row from the results '_meta' header. exact_version_string pins
    the HF repo AND the resolved commit, so a run is fully reproducible."""
    version = meta["hf_id"]
    if meta.get("hf_revision"):
        version = f"{meta['hf_id']}@{meta['hf_revision']}"
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO models (name, exact_version_string, family, "
            "open_weight, access) VALUES (%s, %s, %s, true, 'local') "
            "ON CONFLICT (name, exact_version_string) DO UPDATE "
            "SET family = EXCLUDED.family RETURNING model_id",
            (meta["model_name"], version, meta.get("family")))
        return cur.fetchone()[0]


def import_results(conn, results_path: str | Path, bundle_dir: str | Path) -> dict:
    """Load a Colab responses JSONL into model_responses (+ response_stimuli).

    File format: first line is {"_meta": {...}} (model_name, hf_id,
    hf_revision, family, scheme, prompt_version, effective_prompt), then one
    line per point: {point_id, raw_text, parsed|null, latency_ms, tokens?}.
    Scoring and the analyses then run unchanged (the responses link to the
    same 4 blurred views, so the truth-join still resolves each point)."""
    from . import harness

    bundle_dir = Path(bundle_dir)
    manifest = _read_manifest(bundle_dir)

    with open(results_path, encoding="utf-8") as fh:
        first = json.loads(fh.readline())
        meta = first["_meta"]
        model_id = _upsert_model(conn, meta)
        with conn.cursor() as cur:
            cur.execute("SELECT prompt_id FROM prompts WHERE task = 'city' "
                        "AND prompt_version = %s", (meta["prompt_version"],))
            row = cur.fetchone()
        if not row:
            raise SystemExit(f"prompt '{meta['prompt_version']}' not in DB, "
                             "run `python -m inference register`")
        prompt_id = row[0]
        run_id = harness.create_run(conn, model_id, prompt_id, {
            "presentation_scheme": meta["scheme"],
            "prompt_version": meta["prompt_version"],
            "hf_revision": meta.get("hf_revision"),
            "images_per_point": 4, "order": "N,E,S,W", "grid": True,
            "effective_prompt": meta.get("effective_prompt"),
        })
        conn.commit()

        imported = skipped = 0
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            pid = rec["point_id"]
            if pid not in manifest:
                skipped += 1
                continue
            # recover fields from malformed/truncated raw when the model's own
            # JSON did not parse in the notebook; raw stays stored verbatim
            parsed = rec.get("parsed") or lenient_recover(rec.get("raw_text"))
            result = {
                "parsed": parsed,
                "raw": {"text": rec.get("raw_text"),
                        "hf_revision": meta.get("hf_revision")},
                "latency_ms": rec.get("latency_ms"),
                "tokens": rec.get("tokens") or 0,
            }
            harness.store_response(conn, run_id, "city", result, manifest[pid])
            imported += 1

    return {"run_id": run_id, "model_id": model_id,
            "imported": imported, "skipped": skipped,
            "model_name": meta["model_name"]}
