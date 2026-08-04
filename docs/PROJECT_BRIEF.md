# Project Briefing: Urban Imageability & Geographic Knowledge in Vision-Language Models

**Institution:** Middlesex University London · **Prepared:** June 2026 · **Codebook:** v0.3.1

---

## 1. Aim

Study how Vision-Language Models (VLMs) recognise **cities** and **neighbourhoods**
from street-level imagery, and *why*, testing whether recognisability is driven by
the **physical distinctiveness** of a scene (imageability, after Kevin Lynch) or by the
**cultural visibility** of the place (a proxy for its presence in the model's training
data), and crucially by **their interaction**.

**Research questions:** (1) city-identification accuracy; (2) neighbourhood
discrimination within a city; (3) role of landmarks/distinctive form; (4) do
higher-imageability places get recognised better; (5) are some world regions
systematically more "visible" to models; (6) form vs cultural visibility vs both;
(7) do VLMs show geographic cognition analogous to human mental maps.

## 2. Core design (what makes it a study, not a demo)

- **Two constructs, measured *separately*** so main effects *and* their interaction can
  be tested. Imageability is a **composite** (Lynch sub-components: landmark/node/path/
  edge/district + image measures), with weights to be **learned from human ratings**.
  Cultural visibility is kept as **separate competing predictors** (global reach, local
  prominence, visual footprint, landmark fame), *not* collapsed, because the question is
  *which* dimension predicts recognition.
- **Physical salience ≠ fame.** Landmarks enter imageability by physical attributes
  (height/footprint/type) only; their fame lives entirely in cultural visibility.
- **Uniform spatial frame.** "The city" = **GHSL Urban Centre extent** (same density rule
  worldwide), not administrative boundaries (which aren't comparable across countries).
- **Stratified sampling.** Fixed **N = 200 points/city**, equal allocation across **5
  fabric strata** (historic core / dense residential / commercial / suburban / peripheral),
  so recognition differences reflect the *kind of place* vs the *city*, not sampling bias.
- **No retrieval at inference.** Models get the image only, no web/RAG, so we measure
  knowledge *internal* to the model. Exact model versions pinned.
- **Encoder non-circularity.** Any image-based distinctiveness measure uses a frozen
  self-supervised encoder (e.g. DINO) *different* from the VLMs under test.
- **Reproducibility.** Fixed seeds; all sampled coordinates + metadata archived; raw model
  responses stored separately from derived scores so re-scoring never re-runs inference.

## 3. Data pipeline

```
cities ─► Wikidata QIDs ─► centroids ─► GHSL frames ─► fabric-strata classifier
   ─► reproducible point sampling ─► Street View snapping ─► points table
   ─► [images ─► rectilinear views ─► VLM inference ─► scores] (next phase)
```
| Stage | Status |
|---|---|
| 50-city sampling frame (region-balanced) | ✅ |
| Wikidata QIDs, centroids | ✅ 50/50 |
| GHSL Urban Centre frames | ✅ 50/50 |
| Fabric-strata classifier (OSM land-use × centrality/density) | ✅ built + validated |
| Stage-A point sampling + Street View snapping | ✅ pipeline done; **14 cities sampled** |
| Remaining ~34 cities | ⏳ mechanical (download OSM extract, run batch) |
| Images → views → inference → scores | ⛔ next phase (1 design decision open) |

## 4. Repository structure

- **`codebook.yaml`**, single source of truth: every variable, both constructs,
  confounds, spatial frame, sampling design, normalisation. The DB schema and code are
  *derived* from it. (`codebook.md` = human-readable mirror.)
- **`cities_seed.csv`**, the 50-city frame (8 balanced macro-regions + 2 wildcards).
- **`schema/001_init.sql`**, PostgreSQL/PostGIS schema (22 tables; raw responses separated
  from scores).
- **`ingest/`**, pipeline: spec sync, validation, QID resolution, GHSL frame matching,
  reproducible sampler, strata classifier, OSM reader, Street View snapping, batch driver.
- **`tests/`**, 46 passing unit tests on the deterministic logic.

## 5. Current status (concrete)

- Database (PostgreSQL 18 + PostGIS): **50 cities** with QID + centroid + GHSL frame.
- **14 cities fully sampled** into the `points` table (≈200 stratified, Street-View-snapped
  points each): amman, paris, accra, auckland, cape_town, colombo, dakar, johannesburg,
  lagos, nairobi, seoul, tunis, valparaiso, lima.
- Calibration validated on a **sparse** city (Amman) and a **dense** one (Paris).
- Street View snapping runs on the **free metadata endpoint** (£0); imagery itself not yet
  fetched.

## 6. Problems encountered & how they were resolved

| Problem | Resolution |
|---|---|
| Admin city boundaries not comparable across countries | Adopted **GHSL Urban Centre** morphological extent (uniform worldwide). |
| **Google Street View Terms forbid storing imagery** (only `pano_id` may be kept) | Confirmed against the ToS (didn't assume). Snapping uses the **free metadata** endpoint; image-*storage* decision deferred (keep pano_ids + re-fetch, or switch to **Mapillary**, which permits storage). |
| **No official Street View in North Africa**, cairo (Egypt) 1%, casablanca (Morocco) 0% | Verified via free coverage probes. **cairo → substituted by Tunis**; **casablanca → pending substitute**. Documented as a *region-correlated coverage gap* (directly relevant to RQ5 and the `conf_sv_coverage` control), not hidden. |
| Wikidata QID ambiguity (e.g. "Tunis" resolving to the country Tunisia; cities vs states/universities/films) | Resolver filters to **settlement types**, ranks by **sitelinks**, prefers in-country, and defers on ambiguity rather than guessing; exceptional case (Tunis) **pinned** with a verified QID. |
| OSM country extracts with **antimeridian/overseas territory** (New Zealand) had globe-spanning bounding boxes that falsely matched far-away southern cities → wrong data | City→extract matching now adds a **road-feature check**; false matches are rejected. Bad rows were detected and deleted. |
| Two strata (commercial, historic) **under-supplied** by default thresholds | Calibrated per the codebook's own definition ("shop density high" → commercial via POI density) + larger candidate pool; genuinely rare strata **record shortfalls** rather than forcing points. |
| Low-coverage city (Tunis, 14% official) | Still fills 200 points via heavier oversampling; coverage recorded as the `conf_sv_coverage` value. |

## 7. Open decisions & risks

- **Inference presentation scheme** (the one open codebook decision): how to present the
  360° capture as rectilinear views (N cardinal views; all-at-once vs sequential vs
  best-view). Does not block data collection.
- **Image source/storage** (driven by the ToS finding): Google `pano_id`-only + re-fetch,
  vs Mapillary (storable). Determines whether ~10k images live on disk (~5–30 GB) or not.
- **casablanca substitute**, North-African coverage is exhausted (only Tunisia); a
  Gulf/Levant candidate will be probed and chosen.
- **Coverage as a regional confound**, Street View availability itself varies by region;
  this is a genuine limitation but also feeds RQ5 (it must be modelled, not ignored).

## 8. Next steps

1. Finish stage-A sampling for the remaining cities (download OSM extracts, run the batch).
2. Resolve the casablanca substitute and (optionally) add GHS-BUILT density to the strata.
3. Close the presentation-scheme decision and the image-source decision.
4. Acquire imagery → reprojected views → **VLM inference** (open-weight: Qwen-VL/LLaVA/
   InternVL; proprietary: GPT/Gemini/Claude; structured JSON incl. a reasoning/cue field).
5. **Scoring** (city task: geodesic error, accuracy@{25,200,750} km, country/region
   accuracy; neighbourhood task: correct-boundary match) → **analysis** (recognition ~
   imageability × cultural visibility + region + controls).

## 9. Tech stack

PostgreSQL 18 + PostGIS · Python 3.14 (geopandas, shapely, pyogrio, rasterio) ·
GHS-UCDB R2024A (urban frames) · OpenStreetMap via Geofabrik `.osm.pbf` (GDAL driver) ·
Wikidata API (identity + coordinates) · Google Street View metadata API (snapping/coverage)
· later: a frozen DINO-class encoder + the VLMs under test.

## 10. Selected background literature

The project sits at the intersection of urban cognition, street-imagery science,
image geolocation, and bias in vision models. Real, citable sources, grouped by pillar
(verify exact page/DOI in a reference manager before formal citation).

**Urban legibility & cognitive mapping, the theoretical anchor**
- **Lynch, K. (1960). *The Image of the City*. MIT Press.**, Introduces *imageability* and
  the five elements (landmark/node/path/edge/district); the conceptual backbone of the
  imageability construct.

**Quantifying urban perception from street imagery**
- **Salesses, Schechtner & Hidalgo (2013). "The Collaborative Image of the City." *PLoS ONE*.**
 , The original Place Pulse: crowdsourced perceptual ratings of streetscapes; precedent for
  the human-rating validation of imageability.
- **Dubey, Naik, Parikh, Raskar & Hidalgo (2016). "Deep Learning the City: Quantifying Urban
  Perception at a Global Scale." *ECCV*.**, Place Pulse 2.0 (~110k images, 56 cities) + CNNs;
  template for image-based scene measures.
- **Li et al. (2015). "Assessing street-level urban greenery… green view index." *Urban
  Forestry & Urban Greening*.**, Treepedia-style greenery/sky-view metric from panoramas;
  basis for the `img_skyview_green` variable.

**Urban morphology & a comparable global definition of "the city"**
- **Boeing (2017). "OSMnx: New methods for… complex street networks." *Computers, Environment
  and Urban Systems*.**, Tool/method for street-network structure from OSM; underpins the
  path/node measures.
- **Boeing (2019). "Urban Spatial Order: Street Network Orientation, Configuration, and
  Entropy." *Applied Network Science*.**, Orientation entropy (grid vs organic) across 100
  cities; directly the `path_entropy` variable.
- **Florczyk et al. (2019). *Description of the GHS Urban Centre Database 2015* (GHS-UCDB), JRC**
  and **Dijkstra et al. (2020), Degree of Urbanisation.**, The density-based, UN-endorsed city
  definition + the urban-centre dataset used as the project's spatial frame (why GHSL, not
  admin boundaries).

**Image geolocation, the task, classic → CLIP-era**
- **Hays & Efros (2008). "IM2GPS: estimating geographic information from a single image."
  *CVPR*.**, Founding work on inferring location from one photo.
- **Weyand, Kostrikov & Philbin (2016). "PlaNet, Photo Geolocation with CNNs." *ECCV*.**,
  Frames global geolocation as classification over geocells.
- **Haas, Skreta, Alberti & Finn (2024). "PIGEON: Predicting Image Geolocations." *CVPR*
  (+ their StreetCLIP, 2023).**, SOTA street-image geolocation on CLIP; closest technical
  precedent, and StreetCLIP is a candidate frozen encoder.

**Geographic knowledge, bias & privacy in (vision-)language models**
- **"Granular Privacy Control for Geolocation with Vision Language Models." *EMNLP 2024*.**,
  Shows GPT-4V-class models geolocate images; evidence VLMs carry the geographic knowledge we
  probe.
- **"Assessing the Geolocation Capabilities, Limitations and Societal Risks of Generative
  Vision-Language Models." *arXiv:2508.19967 (2025)*.**, Benchmarks 25 VLMs on geolocation;
  motivates a controlled study like this one.
- **DeVries, Misra, Wang & van der Maaten (2019). "Does Object Recognition Work for Everyone?"
  *CVPR Workshops*.**, Documents amero/euro-centric performance bias by region/income; the
  prior behind RQ5 and the cultural-visibility construct.

**Methodological tools**
- **Caron, Touvron, Misra et al. (2021). "Emerging Properties in Self-Supervised Vision
  Transformers" (DINO). *ICCV*; Oquab et al. (2023). "DINOv2." *arXiv:2304.07193*.**, The
  frozen, general self-supervised encoder for the *non-circular* image-distinctiveness measure.
- **Schuhmann et al. (2022). "LAION-5B…" *NeurIPS Datasets & Benchmarks*.**, The web-scraped
  image-text corpus behind open VLMs; rationale for caption/training-frequency as a
  cultural-visibility proxy.
