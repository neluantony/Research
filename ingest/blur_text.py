"""Blur readable text in the archived views (codebook capture.text_blurring).

Models could geolocate by reading shop signs and street plates instead of by
recognising the place, so the stimuli they see are text-blurred copies of the
archived views. Text regions are found with EasyOCR's CRAFT detector
(detection only — it finds text in any script without reading it) and
Gaussian-blurred with some padding. Originals are never modified; blurred
copies go to a parallel folder tree and are registered in `views` under the
scheme label cardinal4_blurred_v1.

The detector output is also the measurement of the text_cue_present
confound: the number of detected text boxes per point (across its 4 views)
is written to `measurements`. One pass produces both the stimuli and the
covariate. Resumable: views that already have a blurred copy are skipped.
"""
from __future__ import annotations

import json
from pathlib import Path

BLUR_SCHEME = "cardinal4_blurred_v1"
SOURCE_SCHEME = "cardinal4_fov90_640_v1"
PIPELINE_VERSION = "blur_v1"
BOX_PAD_PX = 4          # grow each detected box a little so edges don't leak
BLUR_KERNEL = 31        # Gaussian kernel size (odd); strong enough at 640px


def pad_box(box: tuple, width: int, height: int,
            pad: int = BOX_PAD_PX) -> tuple[int, int, int, int]:
    """Pad (x_min, x_max, y_min, y_max) and clip it to the image bounds."""
    x_min, x_max, y_min, y_max = box
    return (max(0, int(x_min) - pad), min(width, int(x_max) + pad),
            max(0, int(y_min) - pad), min(height, int(y_max) + pad))


def blur_regions(img, boxes: list[tuple]) -> "object":
    """Gaussian-blur each padded box region of a BGR/RGB ndarray in place."""
    import cv2

    h, w = img.shape[:2]
    for box in boxes:
        x0, x1, y0, y1 = pad_box(box, w, h)
        if x1 <= x0 or y1 <= y0:
            continue
        region = img[y0:y1, x0:x1]
        img[y0:y1, x0:x1] = cv2.GaussianBlur(region, (BLUR_KERNEL, BLUR_KERNEL), 0)
    return img


class TextBlurrer:
    """Wraps the CRAFT detector: find text boxes, write a blurred copy."""

    def __init__(self):
        import easyocr

        # recognizer=False: we only need WHERE the text is, not what it says,
        # and CRAFT detection works for any script
        self._reader = easyocr.Reader(["en"], gpu=False, recognizer=False,
                                      verbose=False)

    def detect_boxes(self, path: str | Path) -> list[tuple]:
        """Text boxes as (x_min, x_max, y_min, y_max) tuples."""
        horizontal, free = self._reader.detect(str(path))
        boxes = [tuple(b) for b in (horizontal[0] if horizontal else [])]
        # free-form (rotated) boxes come as 4 corner points -> take their bbox
        for quad in (free[0] if free else []):
            xs = [p[0] for p in quad]
            ys = [p[1] for p in quad]
            boxes.append((min(xs), max(xs), min(ys), max(ys)))
        return boxes

    def blur_file(self, src: str | Path, dst: str | Path) -> int:
        """Write a text-blurred copy of src to dst; returns the box count."""
        import cv2

        boxes = self.detect_boxes(src)
        img = cv2.imread(str(src))
        if img is None:
            raise ValueError(f"cannot read image: {src}")
        if boxes:
            img = blur_regions(img, boxes)
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(dst), img):
            raise IOError(f"cannot write image: {dst}")
        return len(boxes)


def blurred_path(crop_path: str | Path, out_root: str | Path) -> Path:
    """Mirror data/images/<city>/<pano>/hXXX.jpg under the blurred root."""
    p = Path(crop_path)
    return Path(out_root) / p.parent.parent.name / p.parent.name / p.name


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------

def pending_views(conn, limit: int | None = None) -> list[tuple]:
    """Original views without a blurred counterpart yet, grouped per image.

    Returns (image_id, point_id, [view rows...]) so text_cue_present can be
    written per point once all 4 views are processed."""
    q = """
        SELECT i.image_id, i.point_id,
               array_agg(v.view_id ORDER BY v.heading_deg),
               array_agg(v.heading_deg ORDER BY v.heading_deg),
               array_agg(v.crop_path ORDER BY v.heading_deg)
        FROM images i
        JOIN views v ON v.image_id = i.image_id AND v.presentation_scheme = %s
        WHERE NOT EXISTS (
            SELECT 1 FROM views b
            WHERE b.image_id = i.image_id AND b.presentation_scheme = %s)
        GROUP BY i.image_id, i.point_id
        ORDER BY i.image_id
        """
    with conn.cursor() as cur:
        if limit:
            cur.execute(q + " LIMIT %s", (SOURCE_SCHEME, BLUR_SCHEME, limit))
        else:
            cur.execute(q, (SOURCE_SCHEME, BLUR_SCHEME))
        return cur.fetchall()


def run(conn, out_root: str = "data/images_blurred",
        limit: int | None = None, write: bool = False) -> dict:
    """Blur pending views; register blurred views + text_cue_present."""
    todo = pending_views(conn, limit)
    if not write:
        return {"pending_images": len(todo), "processed": 0, "failed": 0}

    blurrer = TextBlurrer()
    processed = failed = 0
    for image_id, point_id, _view_ids, headings, paths in todo:
        try:
            per_view = []
            rows = []
            for heading, src in zip(headings, paths):
                dst = blurred_path(src, out_root)
                n_boxes = blurrer.blur_file(src, dst)
                per_view.append({"heading": int(heading), "text_boxes": n_boxes})
                rows.append((image_id, heading, 90, str(dst), BLUR_SCHEME))
        except Exception as exc:
            failed += 1
            print(f"  [error] image {image_id}: {exc}", flush=True)
            continue
        total_boxes = sum(v["text_boxes"] for v in per_view)
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO views (image_id, heading_deg, pitch_deg, fov_deg, "
                "crop_path, presentation_scheme) VALUES (%s, %s, 0, %s, %s, %s)",
                rows)
            cur.execute(
                """
                INSERT INTO measurements (variable_id, point_id, value_num,
                                          value_json, source, pipeline_version)
                VALUES ('text_cue_present', %s, %s, %s, 'easyocr CRAFT detector', %s)
                ON CONFLICT DO NOTHING
                """,
                (point_id, total_boxes, json.dumps(per_view), PIPELINE_VERSION))
        conn.commit()
        processed += 1
        if processed % 50 == 0:
            print(f"  ... {processed}/{len(todo)} images blurred", flush=True)
    return {"pending_images": len(todo), "processed": processed, "failed": failed}
