# src/scripts/add_fundamentals_exemplar.py

import json
from pathlib import Path

from src.llm.exemplar_bank import append_exemplar_jsonl


def main():
    """Append a curated fundamentals exemplar to artifacts/exemplars_fundamentals.jsonl.

    Usage:
      python -m src.scripts.add_fundamentals_exemplar --focus "services" --ticker "AAPL" --drivers-file artifacts/good_drivers.json

    The drivers file should be a JSON list of bullet strings.
    """
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--focus", required=True)
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--drivers-file", required=True)
    ap.add_argument("--notes", default="")
    args = ap.parse_args()

    drivers = json.loads(Path(args.drivers_file).read_text(encoding="utf-8"))
    if not isinstance(drivers, list) or not all(isinstance(x, str) for x in drivers):
        raise ValueError("drivers-file must be a JSON list of strings")

    record = {
        "focus": args.focus,
        "ticker": args.ticker,
        "drivers": drivers,
        "notes": args.notes,
    }

    append_exemplar_jsonl("artifacts/exemplars_fundamentals.jsonl", record)
    print("✅ Appended exemplar to artifacts/exemplars_fundamentals.jsonl")


if __name__ == "__main__":
    main()
