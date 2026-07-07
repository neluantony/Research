"""Download the 4 views (N/E/S/W, fov 90, 640x640) for each sampled point.

Images are requested by panorama id, not coordinates, so the exact archived
panorama is pinned. Each point gets one `images` row and 4 `views` rows.

Dry-run by default; --limit caps spend (4 requests per point, ~£5.25 per
1,000 — Google bills in USD, converted at the project's assumed rate —
~10k free per month); resumable — points that already have images
are skipped and each point commits on its own. Retired panoramas answer
404 (not billed) and are skipped cleanly. Image storage is covered by the
research permission obtained for the project.

Files: {out_dir}/{city_id}/{pano_id}/h000..h270.jpg
"""
from __future__ import annotations

import urllib.parse
import urllib.request
from pathlib import Path

STATIC_URL = "https://maps.googleapis.com/maps/api/streetview"
# Google bills $7.00 USD per 1,000 requests; costs are reported in GBP at
# the assumed rate below (same rate as the budget document).
COST_GBP_PER_1000 = 7.0 * 0.75
HEADINGS = (0, 90, 180, 270)          # N / E / S / W
FOV = 90
SIZE = "640x640"
PRESENTATION_SCHEME = "cardinal4_fov90_640_v1"   # label stored on every view


def view_url(pano_id: str, heading: int, key: str,
             fov: int = FOV, size: str = SIZE) -> str:
    """Static API URL for one rectilinear view of a panorama."""
    params = {
        "pano": pano_id,               # address by pano_id: pins the archived pano
        "heading": heading,
        "pitch": 0,
        "fov": fov,
        "size": size,
        "return_error_code": "true",   # dead pano -> HTTP 404, not a grey JPEG
        "key": key,
    }
    return f"{STATIC_URL}?{urllib.parse.urlencode(params)}"


def view_path(out_dir: Path, city_id: str, pano_id: str, heading: int) -> Path:
    return out_dir / city_id / pano_id / f"h{heading:03d}.jpg"


def fetch_view(url: str, timeout: int = 60) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read()


def fetch_point(out_dir: Path, city_id: str, pano_id: str, key: str) -> list[Path]:
    """Fetch all 4 views of one panorama to disk. Raises on any failure
    (caller decides how to record it); returns the 4 file paths."""
    paths = []
    for heading in HEADINGS:
        data = fetch_view(view_url(pano_id, heading, key))
        p = view_path(out_dir, city_id, pano_id, heading)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        paths.append(p)
    return paths


def pending_points(conn, limit: int | None = None) -> list[tuple]:
    """Points with a pano_id and no images row yet (deterministic order)."""
    q = ("SELECT p.point_id, p.city_id, p.pano_id, p.capture_date "
         "FROM points p WHERE p.pano_id IS NOT NULL "
         "AND NOT EXISTS (SELECT 1 FROM images i WHERE i.point_id = p.point_id) "
         "ORDER BY p.point_id")
    with conn.cursor() as cur:
        if limit:
            cur.execute(q + " LIMIT %s", (limit,))
        else:
            cur.execute(q)
        return cur.fetchall()


def write_point(conn, point_id: int, pano_id: str, capture_date,
                archive_dir: Path, paths: list[Path]) -> None:
    """One images row + 4 views rows for a fetched point. Commits."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO images (point_id, pano_id, archive_dir, capture_date) "
            "VALUES (%s, %s, %s, %s) RETURNING image_id",
            (point_id, pano_id, str(archive_dir), capture_date))
        image_id = cur.fetchone()[0]
        cur.executemany(
            "INSERT INTO views (image_id, heading_deg, pitch_deg, fov_deg, "
            "crop_path, presentation_scheme) VALUES (%s, %s, 0, %s, %s, %s)",
            [(image_id, h, FOV, str(p), PRESENTATION_SCHEME)
             for h, p in zip(HEADINGS, paths)])
    conn.commit()


def run(conn, key: str, out_dir: str = "data/images",
        limit: int | None = None, write: bool = False) -> dict:
    """Fetch views for up to ``limit`` pending points. Dry-run lists only."""
    import urllib.error

    out = Path(out_dir)
    todo = pending_points(conn, limit)
    est_requests = len(todo) * len(HEADINGS)
    if not write:
        return {"pending": len(todo), "requests": est_requests,
                "est_cost_gbp": round(est_requests * COST_GBP_PER_1000 / 1000, 2),
                "fetched": 0, "dead_panos": 0}

    fetched = dead = errors = 0
    for point_id, city_id, pano_id, capture_date in todo:
        try:
            paths = fetch_point(out, city_id, pano_id, key)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                dead += 1              # pano retired since snapping; skip
                print(f"  [dead pano] point {point_id} {city_id} {pano_id}", flush=True)
                continue
            errors += 1
            print(f"  [http {exc.code}] point {point_id} {city_id}", flush=True)
            continue
        except Exception as exc:
            errors += 1
            print(f"  [error] point {point_id} {city_id}: {exc}", flush=True)
            continue
        write_point(conn, point_id, pano_id, capture_date,
                    out / city_id / pano_id, paths)
        fetched += 1
        if fetched % 100 == 0:
            print(f"  ... {fetched}/{len(todo)} points fetched", flush=True)
    return {"pending": len(todo), "requests": est_requests,
            "est_cost_gbp": round(est_requests * COST_GBP_PER_1000 / 1000, 2),
            "fetched": fetched, "dead_panos": dead, "errors": errors}
