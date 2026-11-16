"""Evaluate the vision provider on hand-labelled real photos.

    python eval/run_eval.py eval/my-set/labels.jsonl                 # mock: checks the plumbing only
    python eval/run_eval.py eval/my-set/labels.jsonl --split dev --live --i-approve-spending

Run from the ``backend`` folder. Live runs need OPENAI_API_KEY and both flags.
The evaluation keeps its own database and cost ledger under the output
folder; it never opens your working database. See eval/README.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("labels", type=Path)
    ap.add_argument("--split", choices=["dev", "heldout", "all"], default="dev",
                    help="Default dev. Score heldout rarely, and never tune against it.")
    ap.add_argument("--out", type=Path, default=None, help="Output folder (default: <labels folder>/runs/<split>)")
    ap.add_argument("--allowance", default="0.50", help="Most this run may spend, in dollars (default 0.50)")
    ap.add_argument("--live", action="store_true", help="Call the real provider (costs money)")
    ap.add_argument("--i-approve-spending", action="store_true", help="Required together with --live")
    args = ap.parse_args()

    examples = [json.loads(line) for line in args.labels.read_text().splitlines() if line.strip()]
    out = args.out or args.labels.parent / "runs" / args.split
    out.mkdir(parents=True, exist_ok=True)
    os.environ["PROFIT_HUNTER_DB"] = str(out / "eval.db")
    os.environ["PROFIT_HUNTER_IMAGES"] = str(out / "images")

    from sqlalchemy import select

    from profit_hunter.config import Settings
    from profit_hunter.db import init_db, make_engine, make_session_factory
    from profit_hunter.db.models import AiUsage, Item
    from profit_hunter.services import WORKSPACE, ai_ledger, image_service, settings_service, to_db_time, utcnow, vision_service
    from profit_hunter.vision import evaluation, openai_provider
    from profit_hunter.vision.mock import MockProvider

    problems = evaluation.validate_labels(examples)
    if problems:
        print("The label file has problems:\n  " + "\n  ".join(problems))
        return 2
    chosen = [e for e in examples if args.split == "all" or e["split"] == args.split]
    if any("REPLACE WITH" in json.dumps(e) or "TEMPLATE ROW" in json.dumps(e) for e in chosen):
        print("The label file still contains template rows. Replace them with real, hand-checked labels.")
        return 2

    settings = Settings(ai_pilot_allowance=Decimal(args.allowance), ai_max_cost_per_item=Decimal(args.allowance))
    if args.live:
        if not args.i_approve_spending:
            print("Refusing to make paid calls without --i-approve-spending.")
            return 2
        if not openai_provider.api_key_present():
            print(f"Set {openai_provider.API_KEY_ENV} first.")
            return 2
        provider = openai_provider.OpenAIProvider()
    else:
        provider = MockProvider(review_model=settings.vision_review_model)
        print("MOCK RUN: this checks that the harness works. It measures NOTHING about accuracy.\n")

    engine = make_engine()
    init_db(engine)
    records = []
    with make_session_factory(engine)() as db:
        settings_service.save_settings(db, settings)
        for e in chosen:
            item = Item(description=f"eval {e['id']}", created_at=to_db_time(utcnow()))
            db.add(item)
            db.flush()
            rows = [image_service.add_image(db, item, (args.labels.parent / i["path"]).read_bytes(), i["role"])
                    for i in e["images"]]
            db.commit()
            try:
                r = vision_service.identify(db, settings, item, rows, e.get("seller_text", ""), provider=provider)
            except ai_ledger.AllowanceExceeded as exc:
                print(f"Stopped at {e['id']}: {exc}")
                break
            attempts = db.scalars(select(AiUsage).where(AiUsage.item_id == item.id)).all()
            f = (r.result or {}).get("fields", {})
            get = lambda name, key: (f.get(name) or {}).get(key)  # noqa: E731
            records.append(evaluation.Record(
                example=e, valid=r.outcome == "OK", status=r.status, brand=get("brand", "value"),
                brand_basis=get("brand", "basis") or "unknown", style=get("style", "value"),
                style_basis=get("style", "basis") or "unknown",
                latency_ms=next((a.latency_ms for a in reversed(attempts) if a.latency_ms is not None), None),
                cost_micros=sum(a.charged_micros for a in attempts)))
            with (out / "results.jsonl").open("a") as fh:
                fh.write(json.dumps({"id": e["id"], "split": e["split"], "case_type": e["case_type"],
                                     "truth": e["truth"], "outcome": r.outcome, "status": r.status,
                                     "result": r.result, "error": r.error, "model": r.model,
                                     "cost_usd": records[-1].cost_micros / 1e6}) + "\n")
        spent = ai_ledger.totals(db, settings, WORKSPACE)

    report = {"labels": str(args.labels), "split": args.split, "live": args.live,
              "provider": provider.name, "model": settings.vision_primary_model,
              "accuracy_is_meaningful": bool(args.live),
              "overall": evaluation.score(records),
              "by_case_type": {c: evaluation.score([r for r in records if r.example["case_type"] == c])
                               for c in evaluation.CASE_TYPES if any(r.example["case_type"] == c for r in records)},
              "ledger_charged_usd": spent.charged_micros / 1e6, "unresolved_attempts": spent.unresolved_count}
    (out / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report["overall"], indent=2))
    print(f"\nFull report: {out / 'report.json'}")
    if not args.live:
        print("Reminder: mock run. Real-world accuracy is UNTESTED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
