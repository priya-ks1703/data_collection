#!/usr/bin/env python3
# Hardcode your input and output paths here:
INPUT_JSON = "/home/priya/Downloads/scores_20250912_091506.json"
OUTPUT_CSV = "items.csv"

import json
import csv
from pathlib import Path

def run(input_path: str, output_path: str) -> None:
    in_path = Path(input_path)
    out_path = Path(output_path)

    with in_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    scores = data.get("scores", {})
    payloads = data.get("items_payloads", {})
    order = data.get("meta", {}).get("order")

    items = order if isinstance(order, list) else list(scores.keys())

    rows = []
    for item_key in items:
        payload = payloads.get(item_key, {})
        rows.append({
            "item": item_key,
            "id": payload.get("id", ""),
            "content": payload.get("content", ""),
            "score": scores.get(item_key, None),
        })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["item", "id", "content", "score"],
            quoting=csv.QUOTE_ALL
        )
        writer.writeheader()
        writer.writerows(rows)

if __name__ == "__main__":
    run(INPUT_JSON, OUTPUT_CSV)
