# Codebook — Urban Imageability & Geographic Knowledge in Vision-Language Models

**Institution:** Middlesex University London  **Version:** 0.3.1  **Date:** 2026-06-22
**Status:** draft v0.3.7 — sampling phase complete (17,566 snap-verified points: stage A 9,842 / 50 cities; stage B 7,724 / 48 cities, 545 eligible neighbourhoods); image source decided (Google Street View, institutional permission via supervisor); presentation scheme decided (4 cardinal views, one multi-image prompt). **No open decisions.**

This codebook is the **single source of truth** for the operational definitions of the two constructs hypothesised to drive urban recognisability in VLMs. The database schema and the ingestion code are *derived* from it: definitions change here first, then in code. The companion `codebook.yaml` is the machine-readable version the pipeline reads to know which variables to compute.

The central hypothesis is that recognisability emerges from the interaction of two distinct forces — the **physical distinctiveness** of a scene (imageability, after Lynch) and the **prominence** of a place in collective and digital memory (cultural visibility, a proxy for presence in the training corpus). The two are measured *separately* so their main effects **and their interaction** can be tested.

---

## Cross-cutting design principles

These constrain every variable below; violating any one collapses the separation between the constructs.

- **Physical salience ≠ fame.** Imageability weights landmarks by physical attributes only (height, footprint, type), blind to fame. Fame lives entirely in cultural visibility. The same object enters both constructs by different properties (Eiffel Tower: *height* → `lmk_immediate`; *celebrity* → `lmk_fame`).
- **Global vs local.** Cultural visibility is decomposed into global vs local prominence, never aggregated. The gap between them is itself a predictor and the suspected mechanism behind regional recognition bias.
- **Encoder non-circularity.** Image-based distinctiveness uses a frozen, general, self-supervised encoder (e.g. DINO) *different* from the VLMs under test.
- **Text cue isolated.** Readable geo-informative text (OCR) is a separate variable, never folded into imageability — reading a sign is OCR, not Lynchian cognition.
- **Proxy, not observable.** Cultural-visibility proxies approximate an unobservable latent (training-data presence); for closed-weight models this is necessarily indirect and must be stated as a limitation.

## Capture

**Resolved (v0.3.7).** Each panorama is captured as **4 rectilinear cardinal views (N/E/S/W, fov 90°, 640×640)** from the Street View Static API — which reprojects server-side, superseding the original plan to archive raw equirectangular panoramas and reproject locally. The four fov-90 views tile the full 360° horizontally, keeping imageability framing-independent without feeding models an out-of-distribution projection. **Presentation: all 4 views in a single multi-image prompt, one response per point.** Single-view and per-view-scored variants remain as ablations on subsets. The zenith is not captured; if `img_skyview_green` is computed, one upward (pitch 90) capture-only view per point is an additive increment.

*ToS checks (resolved):* imagery may not be stored/cached without permission (`pano_id` exempt — everything stored so far is compliant); institutional permission for research use is being secured via the supervisor, with the UK CDPA s.29A TDM exception as statutory backstop; 4 static requests per point (~70k total, ~£5.25/1,000 — billed in USD — partly coverable by the monthly free tier); the OCR confound (`text_cue_present`) is measured on the same 4-view set the models see.

**Text blurring (v0.3.8, supervisor requirement).** All model-facing stimuli are **text-blurred copies** of the archived views: scene-text regions are detected automatically (CRAFT-class detector, script-agnostic) and Gaussian-blurred, so models cannot geolocate by reading signage. Originals stay archived untouched (scheme `cardinal4_fov90_640_v1`); blurred copies are registered as `cardinal4_blurred_v1` and are the default inference stimuli. An **unblurred ablation** re-runs the models on original views for 20 seeded-random stage-A points per city (1,000 points) — the blurred-vs-unblurred accuracy gap directly quantifies reliance on readable text (an RQ3 result in itself). The detector's output doubles as the `text_cue_present` measurement (text-box count per point). Limitation: detector recall < 100%; the residual-text rate is validated on a manual sample and reported.

## Spatial frame — what counts as "the city"

Administrative boundaries are **not comparable across countries** (the Toronto amalgam vs Paris intra-muros, Chinese municipalities that include rural land), so sampling uses a uniform morphological extent for all 50 cities: the **GHSL Urban Centre / built-up extent** (JRC, Degree of Urbanisation). The same density rule applies worldwide, so "the city" means continuous built-up fabric above a density threshold, not a political boundary.

## Sampling — points within each city

**Stratified random, fixed N per city, equal allocation across fabric strata**, with a fixed seed and the frame and all coordinates archived for reproducibility.

Five **fabric strata** with equal allocation (so every city has the same fabric mix): historic/iconic core, dense residential, commercial/business, low-density suburban residential, peripheral edge.

**Operational derivation (v0.3.0).** Each candidate point is classified by crossing two axes within a ~150 m window. The **position/density axis** combines normalised distance-to-centroid with built-up surface fraction (GHS-BUILT-S) into an *innerness* score (1 = core, 0 = edge), split into within-city tertiles (core / mid / edge) — within-city quantiles so "dense" is relative to each city. The **land-use function axis** takes the dominant OSM signal: commercial (`landuse=commercial/retail`, `office=*`), residential (`landuse=residential`), or heritage (`historic=*`, `tourism=`, conservation/old-town). A first-match priority rule maps the pair to a stratum: heritage in core/mid → *historic_iconic_core*; commercial → *commercial_business*; residential in core/mid → *dense_residential*; residential at edge → *low_density_suburban_residential*; else → *peripheral_edge*. Points are oversampled and binned to fill a quota of N/5 per stratum; a genuine shortfall in a city is recorded, not forced. Thresholds are **defaults to calibrate on a pilot** before the full run.

The design is **two-stage** to serve both tasks without inflating the dataset. *Stage A* (city task + all morphological covariates): **N = 200 points per city** (~10,000 images total; the primary cost/power lever). Fixed N means very different sampling *density* (sparse in Tokyo, dense in Adelaide) — intended, because the unit of the research question is the city, not the km². *Stage B* (neighbourhood task, capped v0.3.4): **12 neighbourhoods per city, selected by seeded uniform random draw**, each topped up to a **floor of 20 images** by reusing stage-A points inside it plus targeted points (same snap/dedupe/quality rules, sampled in neighbourhood∩frame). The cap exists because topping up *all* ~2,167 loaded neighbourhoods would cost ~35k images (3.5× stage A), multiplied again at inference per model; random selection keeps the tested set unbiased and the task size comparable across cities. Selected neighbourhoods that cannot reach the floor drop out of the neighbourhood task but keep their points in the city task; non-selected neighbourhoods keep their organic stage-A points for robustness checks.

**Street View handling rules** (the panorama layer is not continuous): snap to the nearest official panorama within **50 m**, else resample within the same stratum; log snap distance, rejection rate, `pano_id` and capture date (rejection rate is itself a coverage signal → ties to `conf_sv_coverage`); deduplicate points snapping to the same `pano_id`; keep **official outdoor road panoramas only**, excluding indoor and user contributions.

## Neighbourhood — boundary definition

"Neighbourhood" varies hugely (official districts vs vernacular areas). Aim for **comparable granularity** (~15–40 units per city) from a **coherent source with documented fallback**: official open-data city boundaries where clean, otherwise OSM administrative/suburb polygons, recording a `neighbourhood_source` field per city. The neighbourhood task is intrinsically less comparable across cities than the city task — stated as an explicit limitation.

**Loaded (v0.3.4).** OSM administrative polygons; per city, the admin level is chosen automatically by unit count in the 15–40 band plus a centre-containment / ≥50%-frame-coverage rule (source recorded as `osm_admin_level_N`). **48/50 cities, 2,167 neighbourhoods.** *valparaiso* and *kuala_lumpur* are excluded from the neighbourhood task (no usable OSM partition — max 5 comunas at any level / no Federal Territory subdivision polygons); their city-task participation is unaffected, and the official open-data route remains open for both.

## Normalisation & aggregation

Every proxy is **z-scored within region** (within city for neighbourhood-level variables), so the absolute level of one continent or city does not swamp the others. All time-varying cultural-visibility proxies are **snapshotted in each model's training window**, not at query time (Wikipedia pageviews are dated and support this).

---

## Construct 1 — Imageability (physical distinctiveness, after Lynch)

**Type:** composite. Sub-components are reported individually *and* combined, with composite weights **learned from human distinctiveness ratings** (not hand-set). Computed at point level, aggregated to neighbourhood/city per task.

| ID | Lynch element | Proxy / source | Scale | Role / notes |
|---|---|---|---|---|
| `lmk_immediate` | landmark | Landmarks ≤200 m weighted by **physical salience** (height/footprint/type); OSM + Wikidata geometry | point | fame excluded → see `lmk_fame` |
| `lmk_panoramic` | landmark | Tall objects ≤1.5 km, height/distance heuristic; OSM (ideal: viewshed on DSM) | point | |
| `node_intersection` | node | Junction degree/complexity in street graph; OSM | point, nbhd | |
| `node_plaza_transit` | node | Squares, pedestrian areas, transit hubs, roundabouts; OSM | point | |
| `path_entropy` | path | Orientation entropy (OSMnx); OSM | nbhd | **sign left to analysis** — grid ≠ automatically more imageable |
| `path_distinctive` | path | Distinctive path types (canals, boulevards, stairways); OSM | point, nbhd | |
| `edge_water` | edge | Distance to coast/water (≤300 m); OSM | point | strongest Lynchian edge |
| `edge_topo` | edge | Slope / ridge strength; DEM/SRTM | point | |
| `edge_infra` | edge | Linear barriers (rail, walls); OSM | point | |
| `district_homogeneity` | district | Land-use/typology homogeneity; OSM + image-based | nbhd | hardest from a single point; be explicit in paper |
| `img_clutter` | scene | Edge density / visual entropy; panorama | point | |
| `img_skyview_green` | scene | Sky-view factor + vegetation index; panorama | point | panorama is the native format |
| `img_atypicality` | scene | Distance from streetscape centroid in **frozen non-VLM** encoder (DINO); on rectilinear crops | point | non-circularity constraint |
| `human_distinctiveness` | validation | Human distinctiveness ratings (subset) | point, nbhd | validates proxies **and** learns composite weights |
| `text_cue_present` | confound | OCR detection of signage/plates/driving side | point | recorded separately; **never** part of imageability |

## Construct 2 — Cultural visibility (prominence in collective & digital memory)

**Type:** separate predictors — deliberately **not** a composite. No human supervisory signal exists as it does for distinctiveness, and the research question is precisely *which* dimension (global reach / visual footprint / landmark fame) drives recognition; collapsing them would destroy that answer.

| ID | Dimension | Proxy / source | Scale | Role / notes |
|---|---|---|---|---|
| `prom_global_sitelinks` | encyclopaedic | Wikipedia language editions / Wikidata sitelinks | city, nbhd | global reach |
| `prom_en_pageviews` | encyclopaedic | English Wikipedia pageviews | city, nbhd | dominant training subset; training-window snapshot |
| `prom_local_pageviews` | encyclopaedic | Local-language edition pageviews | city, nbhd | domestic prominence; training-window snapshot |
| `prom_global_local_ratio` | encyclopaedic | Derived global/local ratio | city, nbhd | candidate driver of regional bias |
| `vis_photo_density` | visual footprint | Geotagged photo density; Mapillary, Wikimedia Commons | city, nbhd | sparse at nbhd level (noisier) |
| `vis_training_count` | visual footprint | Caption counts in Re-LAION (local index) | city, landmark | high cost; valid for open-weight, indirect for closed |
| `lmk_fame` | landmark fame | Sitelinks/pageviews of nearby landmarks | point | fame half of the split landmark; pairs with `lmk_immediate` |
| `tourism_arrivals` | tourism | International arrivals; official stats | city | borderline confound |

> **Re-LAION availability:** the public `knn.laion.ai` API has been offline since 2023-12-19 and not restored; the cleaned Re-LAION-5B was released 2024-08-30. The index must be downloaded and hosted locally rather than queried through a public API.

## Confounds (controls, not predictors of interest)

| ID | Proxy / source | Scale | Role |
|---|---|---|---|
| `conf_gdp` | GDP / urban economy; World Bank, national sources | city | control |
| `conf_sv_coverage` | Street View coverage; SV API preliminary check | city | control **and** sampling constraint |

## Keys

| ID | Proxy / source | Scale | Role / notes |
|---|---|---|---|
| `entity_qid` | Wikidata QID | city, nbhd | resolves toponym ambiguity (Cambridge UK vs MA); free-text counts still need disambiguation |

---

## Analysis hooks

**Central model:** `recognition_accuracy ~ imageability_composite + cultural_visibility_predictors + region + controls`, with an **interaction term** between physical imageability and cultural visibility.

**Accuracy metrics —** *city task:* geodesic distance error, accuracy@{25, 200, 750} km, country/region accuracy. *Neighbourhood task:* correct-boundary match.

**Qualitative:** model-cited cues coded onto Lynch categories (landmark / district / node / edge / path).

## Status of design decisions

**Resolved in this version (0.2.0):** city list — 50 cities, region-balanced (8 cells of 6 + 2 wildcards), seeded in `cities_seed.csv`; spatial frame — GHSL Urban Centre extent; point-sampling — stratified random, fixed N = 200/city, two-stage; neighbourhood source — official open-data with OSM fallback.

**Still open:** none — the presentation scheme was the last open decision (resolved v0.3.7, see Capture).

**Street View coverage (resolved, v0.3.1).** Checked via the free metadata endpoint: **accra kept** (56% official coverage); **cairo dropped** (~1% — Egypt has effectively no official car coverage) and **substituted by Tunis** (Alexandria also ~0%, same Egypt gap, rejected).

**Street View coverage (resolved, v0.3.2).** **casablanca dropped** (0% official — Morocco has effectively no official coverage) and **substituted by Muscat** (Oman, 23% official), keeping the MENA `ordinary_baseline` role. A 2026-07 probe confirmed a **region-wide Gulf/North-Africa gap**: Saudi Arabia (Riyadh, Jeddah), Kuwait, Bahrain, Iraq, Egypt and Morocco are all ~0% official; only Oman (Muscat 23%), Lebanon (Beirut 10%) and Israel (Tel Aviv 50%) are covered. This coverage gap is region-correlated — a documented limitation that itself feeds RQ5 and the `conf_sv_coverage` control.

**Stage-A sampling (complete, v0.3.2).** All 50 cities sampled into the `points` table: **9,839 Street-View-snapped points**, equal-allocation strata (~1,970 each; `historic_iconic_core` slightly light at 1,869 as it is genuinely rare and records shortfalls rather than forcing points).
