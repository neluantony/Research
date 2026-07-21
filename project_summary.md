# Urban Imageability and Geographic Knowledge in Vision-Language Models

Research project, Middlesex University London.

Vision-language models (VLMs) are surprisingly good at telling where in the
world a street photo was taken. This project asks *why*: is it because the
place physically looks distinctive (Kevin Lynch's *imageability*), or because
the place is famous and appears all over the models' training data (*cultural
visibility*)? The two forces are measured separately across 50 cities in 8
world regions, and tested against what the models can actually recognise.

## The two experiments

- **City task** — a model sees 4 photos from one street location (facing
  N/E/S/W) and must say which city it is, with coordinates, confidence, the
  visual cues it used, and its reasoning. No internet access: answers come
  from knowledge inside the model.
- **Neighbourhood task** — same photos, but the model is told the city and
  asked for the neighbourhood.

Models see **text-blurred** copies of the images (readable signage would let
them geolocate by OCR instead of by recognising the place); an unblurred
ablation on a fixed subset measures how much text actually contributes.

## Layout

| Path | What it is |
|---|---|
| `codebook.yaml` | Source of truth: every variable, threshold and design decision (with history). `codebook.md` is the readable version. |
| `cities_seed.csv` | The 50-city sampling frame (8 regions, off-diagonal and wildcard cities). |
| `models_seed.yaml` | The models under test, with pinned version identifiers. |
| `schema/` | PostgreSQL/PostGIS schema (22 tables; raw model answers kept separate from derived scores). |
| `ingest/` | Data pipeline: city resolution, GHSL frames, strata classification, point sampling, Street View snapping, neighbourhoods, imagery fetch, text blurring. Run as `python -m ingest <command>`. |
| `inference/` | Experiment layer: prompts, model registry, inference loop, scoring. Run as `python -m inference <command>`. |
| `tests/` | 104 unit tests over the deterministic logic (`pytest -q`). |
| `docs/` | Project brief and document sources. |

Large inputs (OpenStreetMap extracts, GHSL rasters, the imagery archive) are
not in the repository — see `.gitignore`; paths are configured by environment
variables (`DATABASE_URL`, `GOOGLE_MAPS_API_KEY`, `GHS_BUILT_S_PATH`).

## Status

Sampling complete: 17,566 Street-View-snapped points across 50 cities, 545
eligible neighbourhoods. Imagery collection in progress (paced against the
API free tier), with automated text blurring. Inference and scoring
pipelines built and validated; full model runs pending.

## Notes on method

- Everything is reproducible: fixed random seeds, all sampled coordinates and
  run parameters archived in the database.
- Raw model answers are stored verbatim and never modified; scores are
  derived separately and can be recomputed.
- Street View imagery is stored locally under a research permission and is
  not redistributed here (only panorama IDs are kept in the database, which
  Google's terms allow).
