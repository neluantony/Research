"""CLI for the inference harness.

Examples
--------
    python -m inference register            # sync prompts + pinned models to DB
    python -m inference status              # runs/responses per model+task
    python -m inference run --model claude-opus-4-8 --task city --limit 5           # dry-run count
    python -m inference run --model claude-opus-4-8 --task city --limit 5 --write   # live pilot
    python -m inference run --model mock --task city --limit 2 --write              # no-network smoke test
"""
from __future__ import annotations

import argparse
import sys

from ingest import db

from . import harness, registry


def cmd_register(_args) -> int:
    from . import scoring

    with db.connect() as conn:
        n_prompts = registry.register_prompts(conn)
        n_models, skipped = registry.register_models(conn)
        n_metrics = scoring.register_metrics(conn)
        conn.commit()
    print(f"prompts registered/updated: {n_prompts}")
    print(f"models registered/updated:  {n_models}")
    print(f"metrics registered/updated: {n_metrics}")
    for name in skipped:
        print(f"  [skipped] {name} — exact_version_string not pinned yet (models_seed.yaml)")
    return 0


def _fetch_model(conn, name: str) -> tuple[int, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT model_id, exact_version_string FROM models "
                    "WHERE name = %s ORDER BY model_id DESC LIMIT 1", (name,))
        row = cur.fetchone()
    if not row:
        raise SystemExit(f"model '{name}' not in the models table — "
                         "add it to models_seed.yaml and run `register`")
    return row


def _fetch_prompt(conn, task: str, version: str | None) -> dict:
    import json
    with conn.cursor() as cur:
        if version:
            cur.execute("SELECT prompt_id, text, output_schema_json FROM prompts "
                        "WHERE task = %s AND prompt_version = %s", (task, version))
        else:
            cur.execute("SELECT prompt_id, text, output_schema_json FROM prompts "
                        "WHERE task = %s ORDER BY prompt_id DESC LIMIT 1", (task,))
        row = cur.fetchone()
    if not row:
        raise SystemExit(f"no prompt for task '{task}' — run `register` first")
    schema = row[2] if isinstance(row[2], dict) else json.loads(row[2])
    return {"prompt_id": row[0], "text": row[1], "output_schema": schema}


def cmd_run(args) -> int:
    from .providers import AnthropicProvider, MockProvider

    with db.connect() as conn:
        if args.model == "mock":
            provider = MockProvider()
            model_id = _register_mock(conn)
        else:
            model_id, version_string = _fetch_model(conn, args.model)
            provider = AnthropicProvider(version_string)
        prompt_row = _fetch_prompt(conn, args.task, args.prompt_version)
        res = harness.run(conn, provider, model_id, prompt_row, args.task,
                          limit=args.limit, write=args.write,
                          scheme=args.scheme)
    if args.write:
        print(f"answered {res['answered']}/{res['pending']} points "
              f"({res['failed']} failed) — run_id {res.get('run_id')}")
    else:
        print(f"DRY RUN: {res['pending']} points pending for this model+prompt. "
              "Add --write to run inference.")
    return 0


def _register_mock(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO models (name, exact_version_string, family, open_weight, access) "
            "VALUES ('mock', 'mock-1', 'mock', true, 'local') "
            "ON CONFLICT (name, exact_version_string) DO UPDATE SET family = 'mock' "
            "RETURNING model_id")
        model_id = cur.fetchone()[0]
    conn.commit()
    return model_id


def cmd_status(_args) -> int:
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT m.name, p.prompt_version, mr.task, count(*) "
            "FROM model_responses mr "
            "JOIN inference_runs ir ON ir.run_id = mr.inference_run_id "
            "JOIN models m ON m.model_id = ir.model_id "
            "JOIN prompts p ON p.prompt_id = ir.prompt_id "
            "GROUP BY m.name, p.prompt_version, mr.task ORDER BY m.name")
        rows = cur.fetchall()
    if not rows:
        print("no responses stored yet")
        return 0
    print(f"{'model':20s} {'prompt':10s} {'task':13s} {'responses':>9s}")
    for name, version, task, n in rows:
        print(f"{name:20s} {version:10s} {task:13s} {n:9d}")
    return 0


def cmd_score(args) -> int:
    from . import scoring

    with db.connect() as conn:
        tasks = ["city", "neighbourhood"] if args.task == "all" else [args.task]
        for task in tasks:
            res = scoring.score_task(conn, task,
                                     scoring_version=args.scoring_version,
                                     write=args.write)
            mode = "written" if res["written"] else "computed (dry run, not written)"
            print(f"{task}: {res['responses']} responses -> {res['scores']} scores {mode}")
        rows = scoring.summary(conn, args.scoring_version)
    if rows:
        print(f"\n{'model':20s} {'task':13s} {'n':>5s} {'meanErr':>8s} {'medErr':>8s} "
              f"{'acc25':>6s} {'acc200':>6s} {'country':>7s} {'city':>6s} {'nbhd':>6s}")
        for name, task, n, mean_e, med_e, a25, a200, ctry, city, nbhd in rows:
            fmt = lambda v: "-" if v is None else str(v)
            print(f"{name:20s} {task:13s} {n:5d} {fmt(mean_e):>8s} {fmt(med_e):>8s} "
                  f"{fmt(a25):>6s} {fmt(a200):>6s} {fmt(ctry):>7s} {fmt(city):>6s} {fmt(nbhd):>6s}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="inference", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("register", help="sync prompts + pinned models to the DB").set_defaults(func=cmd_register)
    sub.add_parser("status", help="responses stored per model/prompt/task").set_defaults(func=cmd_status)

    sc = sub.add_parser("score", help="derive scores from stored responses (raw rows untouched)")
    sc.add_argument("--task", default="all", choices=["city", "neighbourhood", "all"])
    sc.add_argument("--scoring-version", default="v1")
    sc.add_argument("--write", action="store_true", help="write scores to the DB")
    sc.set_defaults(func=cmd_score)

    r = sub.add_parser("run", help="run one model on one task (dry-run by default)")
    r.add_argument("--model", required=True, help="model name from models_seed.yaml, or 'mock'")
    r.add_argument("--task", required=True, choices=["city", "neighbourhood"])
    r.add_argument("--prompt-version", help="specific prompt version (default: latest)")
    r.add_argument("--limit", type=int, help="max points this run")
    r.add_argument("--scheme", default="cardinal4_blurred_v1",
                   help="which stimuli to show: cardinal4_blurred_v1 (default) "
                        "or cardinal4_fov90_640_v1 (unblurred ablation)")
    r.add_argument("--write", action="store_true", help="actually call the model + store responses")
    r.set_defaults(func=cmd_run)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
