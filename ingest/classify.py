"""Classify a city's candidate points into the 5 fabric strata.

Combines the pieces: random points from sampling.py, an "innerness" score
(distance to centre + built-up density from density.py, split into
within-city tertiles), land use and heritage from osm.py, and the final
rule from strata.py. Everything is reprojected once to the city's UTM zone
so the 150 m buffers are correct.

Two entry points: classify_city_points draws and classifies the stage-A
candidates; CityClassifier fits the city-wide thresholds once (same seed =
same thresholds) and can then classify any extra point — stage B uses this
so its points get the same zoning as stage A.
"""
from __future__ import annotations

from typing import Callable

import numpy as np
from shapely import STRtree
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from .osm import point_function, point_heritage
from .sampling import sample_points_in_polygon
from .strata import classify_stratum

ANALYSIS_RADIUS_M = 150  # codebook sampling.fabric_strata.derivation.analysis_radius_m


def _tree_hits(tree: STRtree | None, geoms, buf: BaseGeometry) -> list:
    """Geometries in ``geoms`` that actually intersect ``buf`` (STRtree-prefiltered)."""
    if tree is None:
        return []
    return [geoms[j] for j in tree.query(buf) if geoms[j].intersects(buf)]


class CityClassifier:
    """City-wide fabric-strata classifier: fit once, classify many.

    Fitting draws ``n_ref`` seeded reference candidates in the frame and
    derives the innerness tertile thresholds from them — with the stage-A
    seed this reproduces the stage-A zoning exactly. New points are then
    scored against the SAME thresholds: centrality against the reference
    max distance, density as an out-of-sample quantile against the sorted
    reference densities.
    """

    def __init__(self, frame_geom: BaseGeometry, osm: dict, n_ref: int, seed: int,
                 density_fn: Callable[[float, float], float] | None = None,
                 radius_m: int = ANALYSIS_RADIUS_M):
        import geopandas as gpd

        self._gpd = gpd
        self.radius_m = radius_m
        self.density_fn = density_fn

        frame_gs = gpd.GeoSeries([frame_geom], crs="EPSG:4326")
        self.metric = frame_gs.estimate_utm_crs()          # city-local UTM (metres)
        self.frame_m = frame_gs.to_crs(self.metric).iloc[0]
        self._centroid = self.frame_m.centroid

        def to_metric(geoms):
            if not geoms:
                return []
            return list(gpd.GeoSeries(geoms, crs="EPSG:4326").to_crs(self.metric).values)

        self._lu_geoms = to_metric([g for g, _ in osm["landuse"]])
        lu_buckets = [b for _, b in osm["landuse"]]
        self._com_geoms = to_metric(osm["commercial"])
        self._her_geoms = to_metric(osm["heritage"])
        self._lu_tree = STRtree(self._lu_geoms) if self._lu_geoms else None
        self._com_tree = STRtree(self._com_geoms) if self._com_geoms else None
        self._her_tree = STRtree(self._her_geoms) if self._her_geoms else None
        self._lu_index = {id(g): b for g, b in zip(self._lu_geoms, lu_buckets)}

        # --- fit: reference draw -> innerness tertile thresholds ---------------
        pts_m = sample_points_in_polygon(self.frame_m, n_ref, seed)
        self._ref_pts_m = [Point(x, y) for x, y in pts_m]
        self._ref_lonlat = gpd.GeoSeries(self._ref_pts_m, crs=self.metric).to_crs("EPSG:4326")

        dists = np.array([p.distance(self._centroid) for p in self._ref_pts_m])
        self._max_dist = float(dists.max()) if len(dists) and dists.max() > 0 else 1.0
        centrality = 1.0 - dists / self._max_dist if dists.max() > 0 else np.ones(len(pts_m))
        if density_fn is not None:
            density = np.array([density_fn(p.x, p.y) for p in self._ref_lonlat], dtype=float)
            # within-city quantile rank (codebook density_norm), robust to outliers;
            # stable sort so tied values (e.g. many zeros) rank deterministically
            order = density.argsort(kind="stable").argsort(kind="stable")
            density_norm = order / (len(density) - 1) if len(density) > 1 else np.zeros_like(density)
            self._ref_innerness = (centrality + density_norm) / 2.0
            self._ref_density_sorted = np.sort(density)
        else:
            self._ref_innerness = centrality
            self._ref_density_sorted = None
        self._t1, self._t2 = np.quantile(self._ref_innerness, [1 / 3, 2 / 3])

    # --- classification ---------------------------------------------------------

    def _zone(self, v: float) -> str:
        return "core" if v >= self._t2 else ("mid" if v >= self._t1 else "edge")

    def _classify(self, pts_geom_m, lonlat, innerness) -> list[dict]:
        results: list[dict] = []
        for i, p in enumerate(pts_geom_m):
            buf = p.buffer(self.radius_m)
            lu_hit = [(g, self._lu_index[id(g)])
                      for g in _tree_hits(self._lu_tree, self._lu_geoms, buf)]
            com_ct = len(_tree_hits(self._com_tree, self._com_geoms, buf))
            function = point_function(buf, lu_hit, com_ct)
            heritage = point_heritage(buf, _tree_hits(self._her_tree, self._her_geoms, buf))
            zone = self._zone(innerness[i])
            results.append({
                "lon": float(lonlat.iloc[i].x), "lat": float(lonlat.iloc[i].y),
                "zone": zone, "function": function, "heritage": heritage,
                "stratum": classify_stratum(zone, function, heritage),
            })
        return results

    def classify_reference(self) -> list[dict]:
        """Classify the fitted reference draw (the stage-A candidate set)."""
        return self._classify(self._ref_pts_m, self._ref_lonlat, self._ref_innerness)

    def classify_lonlat(self, coords: list[tuple[float, float]]) -> list[dict]:
        """Classify arbitrary (lon, lat) points against the fitted city zoning."""
        if not coords:
            return []
        pts = self._gpd.GeoSeries([Point(lon, lat) for lon, lat in coords], crs="EPSG:4326")
        pts_m = list(pts.to_crs(self.metric).values)
        dists = np.array([p.distance(self._centroid) for p in pts_m])
        centrality = 1.0 - np.minimum(dists / self._max_dist, 1.0)
        if self.density_fn is not None:
            density = np.array([self.density_fn(lon, lat) for lon, lat in coords], dtype=float)
            # out-of-sample quantile against the reference distribution
            denom = max(len(self._ref_density_sorted) - 1, 1)
            density_norm = np.searchsorted(self._ref_density_sorted, density, side="left") / denom
            innerness = (centrality + np.clip(density_norm, 0.0, 1.0)) / 2.0
        else:
            innerness = centrality
        return self._classify(pts_m, pts, innerness)


def classify_city_points(
    frame_geom: BaseGeometry,
    osm: dict,
    n: int,
    seed: int,
    density_fn: Callable[[float, float], float] | None = None,
    radius_m: int = ANALYSIS_RADIUS_M,
) -> list[dict]:
    """Classify ``n`` candidate points in ``frame_geom`` (EPSG:4326) into strata.

    ``osm`` is the dict from ``osm.load_city_osm``. ``density_fn`` maps
    (lon, lat) to a built-up density; if None, innerness = centrality only.
    Returns one dict per point: lon, lat, zone, function, heritage, stratum.
    """
    clf = CityClassifier(frame_geom, osm, n_ref=n, seed=seed,
                         density_fn=density_fn, radius_m=radius_m)
    return clf.classify_reference()
