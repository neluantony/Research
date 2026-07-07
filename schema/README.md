## Layers

| Layer | Tables | Purpose |
|---|---|---|
| **Spec** | `regions`, `fabric_strata`, `variables`, `metrics` | Mirror the codebook so the DB is self-describing; synced from `codebook.yaml` at ingestion. |
| **Entity** | `cities`, `neighbourhoods`, `sampling_runs`, `points`, `images`, `views`, `landmarks` | The physical/spatial facts: the `cities → neighbourhoods → points → images → views` hierarchy plus landmarks. |
| **Measurement** | `measurements` | Long, codebook-keyed: one row per (variable, entity, snapshot). |
| **Experiment** | `models`, `prompts`, `inference_runs`, `model_responses`, `response_stimuli`, `scores`, `cue_codes` | Raw model output kept separate from derived scores. |

## How the schema enforces the method

| Principle | Where it lands in the schema |
|---|---|
| Codebook is source of truth | `variables`/`fabric_strata`/`metrics` synced from the YAML; every `measurements` row FKs to `variables`, so no measurement can exist for an undefined variable. |
| No retrieval at inference; pinned versions | `inference_runs.retrieval_disabled`; `models.exact_version_string` (NOT NULL, unique with name). |
| Raw output separate from scores | `model_responses` (raw, immutable) vs `scores` (derived, versioned by `scoring_version`). Rescoring adds rows. |
| Reproducibility | `sampling_runs` (seed + parameters + rejection stats); `points.sampled_geom` archives the drawn coordinate alongside `snapped_geom`. |
| Never fabricate identifiers | `entity_qid` columns are nullable until resolved from Wikidata. |
| Coverage flags respected | the `cities_included` view excludes `sv_coverage_status = 'verify'` rows. |
| Physical salience ≠ fame | `landmarks` carries disjoint physical columns (`height_m`, `footprint_m2`, `lmk_type`) and fame columns (`sitelinks`, `pageviews`). |
| No cultural-visibility composite | each visibility variable is a separate `variables` row, stored as independent `measurements`, never aggregated. |
| Training-window snapshots | `measurements.as_of_date` stores a temporal proxy once per model training window. |
| Snapping / dedup rules | `points.snap_distance_m`, `pano_id`, `status`, and `UNIQUE (city_id, pano_id)`. |

## Design notes

- **Long measurements table.** One `measurements` table keyed to `variables`
  rather than wide per-construct columns: variables span four spatial scales
  (point / neighbourhood / city / landmark) and the set evolves with the
  codebook. Exactly one of `city_id` / `neighbourhood_id` / `point_id` /
  `landmark_id` is non-null (CHECK constraint), keeping real foreign keys
  instead of a polymorphic reference.
- **`images` (archive) split from `views` (presentation).** An `images` row
  anchors a point's archive directory; the individual files shown to models
  live in `views`, labelled by `presentation_scheme`. This is how the
  original and text-blurred variants of the same panorama coexist
  (`cardinal4_fov90_640_v1` vs `cardinal4_blurred_v1`) with no schema change.
- **Geometry.** All geometry is SRID 4326 (WGS84 lon/lat); geodesic distances
  use `::geography` casts. GiST indexes on every geometry column.

## Files

- `001_init.sql` — the full initial schema (22 tables).
- `002_capture_views.sql` — renames `images.equirect_path` to `archive_dir`,
  matching the final capture decision (4 rectilinear views per panorama
  instead of one stitched equirectangular file).
