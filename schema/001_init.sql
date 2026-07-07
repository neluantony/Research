-- =============================================================================
-- 001_init.sql — Initial schema
-- Project: Urban Imageability & Geographic Knowledge in Vision-Language Models
-- Middlesex University London
-- =============================================================================
-- Engine: PostgreSQL 15+ with PostGIS 3+.
-- Derived from codebook.yaml (the source of truth) and cities_seed.csv:
-- definitions change in the codebook first, then here.
--
-- Layers:
--   1. Spec      — mirrors the codebook so the DB is self-describing
--                  (regions, fabric_strata, variables, metrics).
--   2. Entity    — cities -> neighbourhoods -> points -> images -> views,
--                  plus landmarks.
--   3. Measure   — long, codebook-keyed measurements table.
--   4. Experiment— raw model_responses vs derived scores (kept separate).
--
-- All geometry stored as SRID 4326 (WGS84 lon/lat); geodesic computations
-- use ::geography casts.
-- =============================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS postgis;

-- -----------------------------------------------------------------------------
-- Controlled vocabularies (fixed for this study).
-- Small + immutable -> enums; richer/codebook-driven vocab -> lookup tables.
-- -----------------------------------------------------------------------------
CREATE TYPE population_tier   AS ENUM ('mega', 'large');
CREATE TYPE prominence_tier   AS ENUM ('iconic', 'medium', 'ordinary');
CREATE TYPE design_role       AS ENUM (
    'anchor_iconic',
    'secondary_iconic',
    'secondary_medium',
    'off_diagonal_famous_generic',
    'off_diagonal_distinctive_lesser_known',
    'ordinary_baseline',
    'wildcard_distinctive_low_visibility'
);
CREATE TYPE sv_coverage_status AS ENUM ('ok', 'ok_recent', 'ok_dated', 'verify');
CREATE TYPE sampling_stage     AS ENUM ('A', 'B');
CREATE TYPE point_status       AS ENUM ('accepted', 'resampled', 'rejected');
CREATE TYPE model_access       AS ENUM ('api', 'local');
CREATE TYPE task_type          AS ENUM ('city', 'neighbourhood');
CREATE TYPE construct_type     AS ENUM (
    'imageability', 'cultural_visibility', 'confound', 'key'
);
CREATE TYPE norm_method        AS ENUM (
    'none', 'zscore_within_region', 'zscore_within_city'
);

-- =============================================================================
-- 1. SPEC LAYER — synced from codebook.yaml / cities_seed.csv by the ingester.
-- =============================================================================

-- The 8 balanced macro-regions (region cells) from the seed.
CREATE TABLE regions (
    region_id   text PRIMARY KEY,          -- 'North America', 'Europe', ...
    notes       text
);

-- The 5 fabric strata, equal allocation (codebook.sampling.fabric_strata).
CREATE TABLE fabric_strata (
    stratum_id  text PRIMARY KEY,          -- 'historic_iconic_core', ...
    description text
);

-- One row per codebook variable id. FK target for every measurement, so the
-- DB cannot hold a measurement for a variable the codebook does not define.
-- AUTO-SYNCED from codebook.yaml at ingestion (never hand-edited to diverge).
CREATE TABLE variables (
    variable_id     text PRIMARY KEY,      -- 'lmk_immediate', 'prom_en_pageviews', ...
    construct       construct_type NOT NULL,
    lynch_element   text,                  -- imageability only
    dimension       text,                  -- cultural_visibility only
    description     text,
    proxy           text,
    sources         text[],
    spatial_scales  text[] NOT NULL,       -- {'point'} | {'point','neighbourhood'} | ...
    role            text,
    is_temporal     boolean NOT NULL DEFAULT false,  -- needs training-window snapshot
    notes           text
);

-- Accuracy / scoring metrics (codebook.analysis.accuracy_metrics).
CREATE TABLE metrics (
    metric_id   text PRIMARY KEY,          -- 'geodesic_error_km', 'acc@200', ...
    task        task_type NOT NULL,
    description text
);

-- =============================================================================
-- 2. ENTITY LAYER
-- =============================================================================

-- From cities_seed.csv + resolved covariates (QID, GHSL frame).
CREATE TABLE cities (
    city_id            text PRIMARY KEY,           -- slug, e.g. 'new_york'
    city_name          text NOT NULL,
    country            text NOT NULL,
    region_id          text NOT NULL REFERENCES regions(region_id),
    population_tier    population_tier NOT NULL,
    prominence_tier    prominence_tier NOT NULL,
    design_role        design_role NOT NULL,
    sv_coverage_status sv_coverage_status NOT NULL,
    entity_qid         text,                        -- nullable: resolve from Wikidata, never fabricate
    notes              text,
    -- Resolved GHSL spatial frame ("the city"); nullable until extraction.
    frame_geom         geometry(MultiPolygon, 4326),
    centroid           geometry(Point, 4326),
    ghsl_version       text,
    frame_source       text
);

-- Convenience flag: verify-coverage rows (cairo, accra) excluded by default
-- until confirmed via the Street View API.
CREATE VIEW cities_included AS
    SELECT * FROM cities WHERE sv_coverage_status <> 'verify';

CREATE TABLE neighbourhoods (
    neighbourhood_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    city_id                 text NOT NULL REFERENCES cities(city_id),
    name                    text NOT NULL,
    entity_qid              text,                    -- nullable
    boundary_geom           geometry(MultiPolygon, 4326),
    neighbourhood_source    text NOT NULL,           -- official open-data | OSM fallback
    eligible_for_nbhd_task  boolean NOT NULL DEFAULT false  -- set once stage-B floor (>=20) met
);

-- Archives the fixed seed + frame version so a point draw is reproducible.
CREATE TABLE sampling_runs (
    run_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    city_id         text NOT NULL REFERENCES cities(city_id),
    seed            bigint NOT NULL,
    frame_version   text,
    params_json     jsonb,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE points (
    point_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    city_id           text NOT NULL REFERENCES cities(city_id),
    neighbourhood_id  bigint REFERENCES neighbourhoods(neighbourhood_id),  -- via point-in-polygon
    stratum_id        text NOT NULL REFERENCES fabric_strata(stratum_id),
    stage             sampling_stage NOT NULL,
    sampling_run_id   bigint NOT NULL REFERENCES sampling_runs(run_id),
    sampled_geom      geometry(Point, 4326) NOT NULL,  -- the drawn coordinate (archived)
    snapped_geom      geometry(Point, 4326),           -- nearest official panorama
    snap_distance_m   double precision,
    pano_id           text,
    capture_date      date,
    status            point_status NOT NULL DEFAULT 'accepted',
    rejection_reason  text,
    -- Dedup: collapse points snapping to the same panorama within a city.
    CONSTRAINT uq_points_city_pano UNIQUE (city_id, pano_id)
);

-- Archive: full 360 equirectangular panorama (one per accepted point/pano).
CREATE TABLE images (
    image_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    point_id          bigint NOT NULL REFERENCES points(point_id),
    pano_id           text NOT NULL,
    equirect_path     text NOT NULL,
    capture_date      date,
    provider_meta_json jsonb
);

-- Presentation: rectilinear reprojections shown to the models. One panorama ->
-- N views. Kept separate so the still-open presentation scheme (N cardinal
-- views; all-at-once vs sequential vs best-view) needs no schema change.
CREATE TABLE views (
    view_id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    image_id            bigint NOT NULL REFERENCES images(image_id),
    heading_deg         double precision,
    pitch_deg           double precision,
    fov_deg             double precision,
    crop_path           text NOT NULL,
    presentation_scheme text                          -- label of the scheme used
);

-- Landmark objects near points. Same physical object carries BOTH the physical
-- attributes (feed lmk_immediate, imageability) and the fame attributes (feed
-- lmk_fame, cultural visibility): physical salience != fame, in one table.
CREATE TABLE landmarks (
    landmark_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_qid    text,
    name          text,
    geom          geometry(Geometry, 4326),           -- point or footprint
    -- physical (imageability side) --
    height_m      double precision,
    footprint_m2  double precision,
    lmk_type      text,
    -- fame (cultural-visibility side) --
    sitelinks     integer,
    pageviews     bigint,
    source        text
);

-- =============================================================================
-- 3. MEASUREMENT LAYER — long, codebook-keyed.
-- Exactly one of (city/neighbourhood/point/landmark) is non-null, so a real FK
-- is preserved instead of a polymorphic entity_type+id reference.
-- =============================================================================
CREATE TABLE measurements (
    measurement_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    variable_id       text NOT NULL REFERENCES variables(variable_id),
    city_id           text   REFERENCES cities(city_id),
    neighbourhood_id  bigint REFERENCES neighbourhoods(neighbourhood_id),
    point_id          bigint REFERENCES points(point_id),
    landmark_id       bigint REFERENCES landmarks(landmark_id),
    value_num         double precision,
    value_json        jsonb,                          -- non-scalar proxies
    normalised_value  double precision,
    norm_method       norm_method NOT NULL DEFAULT 'none',
    source            text,
    as_of_date        date,                           -- training-window snapshot (temporal proxies)
    pipeline_version  text NOT NULL,
    computed_at       timestamptz NOT NULL DEFAULT now(),
    -- exactly one target entity
    CONSTRAINT ck_measurements_one_target CHECK (
        (city_id          IS NOT NULL)::int
      + (neighbourhood_id IS NOT NULL)::int
      + (point_id         IS NOT NULL)::int
      + (landmark_id      IS NOT NULL)::int = 1
    ),
    -- stable key over the (nullable) target for the uniqueness index below
    target_key text GENERATED ALWAYS AS (
        coalesce('c:'||city_id, 'n:'||neighbourhood_id::text,
                 'p:'||point_id::text, 'l:'||landmark_id::text)
    ) STORED
);

-- One value per (variable, target, snapshot, pipeline version). Recomputes with
-- a new pipeline_version coexist; temporal proxies coexist per as_of_date.
CREATE UNIQUE INDEX uq_measurements_identity ON measurements (
    variable_id, target_key, coalesce(as_of_date, DATE 'epoch'), pipeline_version
);

-- =============================================================================
-- 4. EXPERIMENT LAYER — raw responses kept separate from derived scores,
--    so anything can be re-scored without re-running inference.
-- =============================================================================
CREATE TABLE models (
    model_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                  text NOT NULL,
    exact_version_string  text NOT NULL,              -- pinned, never a guess
    family                text,
    open_weight           boolean NOT NULL,
    training_window_start date,
    training_window_end   date,
    access                model_access NOT NULL,
    CONSTRAINT uq_models_version UNIQUE (name, exact_version_string)
);

CREATE TABLE prompts (
    prompt_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    prompt_version     text NOT NULL,
    task               task_type NOT NULL,
    text               text NOT NULL,
    output_schema_json jsonb,
    CONSTRAINT uq_prompts_version_task UNIQUE (prompt_version, task)
);

-- A configured inference pass. Records that retrieval was disabled.
CREATE TABLE inference_runs (
    run_id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    model_id               bigint NOT NULL REFERENCES models(model_id),
    prompt_id              bigint NOT NULL REFERENCES prompts(prompt_id),
    presentation_config_json jsonb,
    retrieval_disabled     boolean NOT NULL DEFAULT true,
    seed                   bigint,
    started_at             timestamptz NOT NULL DEFAULT now()
);

-- RAW model output — immutable; never overwritten by rescoring.
CREATE TABLE model_responses (
    response_id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    inference_run_id      bigint NOT NULL REFERENCES inference_runs(run_id),
    task                  task_type NOT NULL,
    raw_output_json       jsonb NOT NULL,
    -- parsed-but-unscored fields
    pred_lat              double precision,
    pred_lon             double precision,
    pred_city             text,
    pred_country          text,
    pred_neighbourhood_id bigint REFERENCES neighbourhoods(neighbourhood_id),
    reasoning_text        text,                       -- cue field for Lynch coding
    latency_ms            integer,
    tokens                integer,
    created_at            timestamptz NOT NULL DEFAULT now()
);

-- Which view(s) were shown for a response (multi-view = several rows).
CREATE TABLE response_stimuli (
    response_id  bigint NOT NULL REFERENCES model_responses(response_id),
    view_id      bigint NOT NULL REFERENCES views(view_id),
    position     integer,                             -- order within an all-at-once set
    PRIMARY KEY (response_id, view_id)
);

-- DERIVED scores — rescoring adds rows (new scoring_version), raw untouched.
CREATE TABLE scores (
    score_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    response_id     bigint NOT NULL REFERENCES model_responses(response_id),
    metric_id       text NOT NULL REFERENCES metrics(metric_id),
    value           double precision NOT NULL,
    scoring_version text NOT NULL,
    computed_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_scores_identity UNIQUE (response_id, metric_id, scoring_version)
);

-- Qualitative coding of model-cited cues onto Lynch categories.
CREATE TABLE cue_codes (
    cue_code_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    response_id    bigint NOT NULL REFERENCES model_responses(response_id),
    lynch_category text NOT NULL,                     -- landmark|node|path|edge|district
    cited_text     text,
    coder          text
);

-- -----------------------------------------------------------------------------
-- Indexes
-- -----------------------------------------------------------------------------
CREATE INDEX gix_cities_frame        ON cities          USING gist (frame_geom);
CREATE INDEX gix_neighbourhoods_geom ON neighbourhoods  USING gist (boundary_geom);
CREATE INDEX gix_points_sampled      ON points          USING gist (sampled_geom);
CREATE INDEX gix_points_snapped      ON points          USING gist (snapped_geom);
CREATE INDEX gix_landmarks_geom      ON landmarks       USING gist (geom);

CREATE INDEX ix_points_city          ON points          (city_id);
CREATE INDEX ix_points_neighbourhood ON points          (neighbourhood_id);
CREATE INDEX ix_images_point         ON images          (point_id);
CREATE INDEX ix_views_image          ON views           (image_id);
CREATE INDEX ix_measurements_var     ON measurements    (variable_id);
CREATE INDEX ix_measurements_city    ON measurements    (city_id);
CREATE INDEX ix_measurements_point   ON measurements    (point_id);
CREATE INDEX ix_responses_run        ON model_responses (inference_run_id);
CREATE INDEX ix_scores_response      ON scores          (response_id);

COMMIT;
