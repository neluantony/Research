"""Data-building pipeline for the study.

Reads codebook.yaml (the source of truth for every definition) and
cities_seed.csv, then fills the PostGIS database step by step:
cities -> frames -> sampled points -> neighbourhoods -> imagery.
Nothing here invents definitions, QIDs or coordinates — everything comes
from the codebook or an authoritative source.
"""
