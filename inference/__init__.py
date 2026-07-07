"""The experiment layer: show images to the models and store their answers.

Kept separate from ingest/ (which builds the dataset). Two principles hold
everywhere here: models get NO internet access of any kind — the study
measures what they already know — and raw answers are stored verbatim and
never modified; scores are derived separately so re-scoring is always
possible without re-running (and re-paying for) inference.
"""
