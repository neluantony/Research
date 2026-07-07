-- =============================================================================
-- 002_capture_views.sql — align the images table with codebook v0.3.7
-- =============================================================================
-- The presentation-scheme decision (codebook capture, v0.3.7) supersedes the
-- plan to archive one equirectangular panorama per point: capture is now
-- 4 rectilinear cardinal views per panorama, fetched from the Static API
-- (server-side reprojection). The images row therefore anchors a *directory*
-- of views, not a single equirect file; the per-view files live in `views`
-- (crop_path), which already modelled this and needs no change.
-- =============================================================================

BEGIN;

ALTER TABLE images RENAME COLUMN equirect_path TO archive_dir;
COMMENT ON COLUMN images.archive_dir IS
    'Directory holding the point''s archived views (codebook v0.3.7: 4 '
    'cardinal rectilinear views; was a single equirectangular path pre-0.3.7)';

COMMIT;
