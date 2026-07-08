#!/usr/bin/env python3
"""Verify and apply curated evolution-method display overrides.

This script does two related jobs:

1. Apply curated evolution-method display overrides, such as preferring modern
   item methods over older game/location-specific methods when both are valid.
2. Report remaining game-specific or review-worthy methods so they can be
   curated deliberately rather than guessed.

It does not fetch from the internet and it does not invent missing methods. Add
new choices to data/evolution_method_overrides.json, then run with --apply.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[1]
EVOLUTIONS_PATH = ROOT / "data" / "evolutions.json"
OVERRIDES_PATH = ROOT / "data" / "evolution_method_overrides.json"
REPORT_PATH = ROOT / "data" / "evolution_method_audit_report.json"

FIELDS = [
    "trigger", "item", "min_level", "time_of_day", "location", "held_item",
    "known_move", "known_move_type", "min_happiness", "min_happines",
    "min_beauty", "party_species", "party_type", "relative_physical_stats",
    "trade_species", "gender", "note",
]

GAME_SPECIFIC_NOTE_PATTERNS = [
    "only evolves into",
    "region",
    "older games",
    "dusty bowl",
    "mount lanakila",
    "moss rock",
    "ice rock",
    "magnetic field",
    "union circle",
    "let’s go",
    "lets go",
]

UNUSUAL_TRIGGERS = {
    "other", "spin", "shed", "take-damage", "three-critical-hits",
    "strong-style-move", "agile-style-move",
    "level-up-during-day", "level-up-during-night", "level-up-during-evening",
}


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def dump_json(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    tmp.replace(path)


def edge_key(edge: Dict[str, Any]) -> str:
    return f"{edge.get('from')}->{edge.get('to')}"


def comparable_override_fields(override: Dict[str, Any]) -> Iterable[str]:
    for field in FIELDS:
        if field in override:
            yield field


def compare(evolutions: List[Dict[str, Any]], overrides: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_key = {edge_key(e): e for e in evolutions}
    rows = []
    for key, override in sorted(overrides.items()):
        edge = by_key.get(key)
        if not edge:
            rows.append({"key": key, "status": "missing-edge", "differences": {}})
            continue
        differences = {}
        for field in comparable_override_fields(override):
            if edge.get(field) != override.get(field):
                differences[field] = {"current": edge.get(field), "expected": override.get(field)}
        rows.append({
            "key": key,
            "status": "ok" if not differences else "diff",
            "differences": differences,
            "reason": override.get("reason"),
        })
    return rows


def apply_overrides(evolutions: List[Dict[str, Any]], overrides: Dict[str, Dict[str, Any]]) -> int:
    changed = 0
    for edge in evolutions:
        override = overrides.get(edge_key(edge))
        if not override:
            continue
        for field in comparable_override_fields(override):
            if edge.get(field) != override.get(field):
                edge[field] = override.get(field)
                changed += 1
    return changed


def classify_method_items(evolutions: List[Dict[str, Any]], overrides: Dict[str, Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Classify evolution-method rows after applying curated overrides.

    unresolved_review_items are rows that still look wrong for the app's
    preferred display policy: location as the primary method, item methods shown
    as level-up methods, or vague level-up rows with no condition at all.

    intentional_specific_cases are special/regional mechanics that are inherently
    specific and should remain visible as notes unless a better general method is
    curated later.
    """
    unresolved = []
    intentional = []
    for edge in evolutions:
        key = edge_key(edge)
        reasons = []
        note = str(edge.get("note") or "").lower()
        trigger = edge.get("trigger")

        if edge.get("location"):
            reasons.append("has-location-primary-method")
        if edge.get("item") and trigger not in ("use-item", None):
            reasons.append("has-item-but-trigger-is-not-use-item")
        if trigger == "level-up" and not edge.get("min_level") and not any(edge.get(f) for f in [
            "item", "min_happiness", "min_beauty", "time_of_day", "known_move",
            "known_move_type", "party_species", "party_type", "relative_physical_stats",
            "gender", "note",
        ]):
            reasons.append("level-up-has-no-condition")

        specific_reasons = []
        if trigger in UNUSUAL_TRIGGERS:
            specific_reasons.append("has-unusual-trigger")
        if any(pattern in note for pattern in GAME_SPECIFIC_NOTE_PATTERNS):
            specific_reasons.append("has-game-specific-note")

        row = {
            "key": key,
            "from": edge.get("from"),
            "to": edge.get("to"),
            "trigger": trigger,
            "item": edge.get("item"),
            "min_level": edge.get("min_level"),
            "location": edge.get("location"),
            "note": edge.get("note"),
        }
        if reasons:
            unresolved.append({**row, "reasons": sorted(set(reasons))})
        elif specific_reasons:
            intentional.append({**row, "reasons": sorted(set(specific_reasons))})

    return {
        "unresolved_review_items": unresolved,
        "intentional_specific_cases": intentional,
    }


def print_human_summary(report: Dict[str, Any]) -> None:
    summary = report["summary"]
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if report.get("unresolved_review_items"):
        print("\nUnresolved evolution methods that may need curation:")
        for row in report["unresolved_review_items"][:50]:
            print(f"- {row['key']}: {', '.join(row['reasons'])}")
        if len(report["unresolved_review_items"]) > 50:
            print(f"...and {len(report['unresolved_review_items']) - 50} more. See the report JSON.")
    if report.get("intentional_specific_cases"):
        print("\nIntentional special/regional cases kept as notes:")
        for row in report["intentional_specific_cases"][:20]:
            print(f"- {row['key']}: {', '.join(row['reasons'])}")
        if len(report["intentional_specific_cases"]) > 20:
            print(f"...and {len(report['intentional_specific_cases']) - 20} more. See the report JSON.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write curated method overrides into evolutions.json.")
    parser.add_argument("--report", action="store_true", help="Write data/evolution_method_audit_report.json.")
    parser.add_argument("--json", action="store_true", help="Print full JSON report instead of a compact summary.")
    args = parser.parse_args()

    evolutions = load_json(EVOLUTIONS_PATH)
    payload = load_json(OVERRIDES_PATH)
    overrides = payload.get("overrides", {})

    before = compare(evolutions, overrides)
    changed = 0
    if args.apply:
        changed = apply_overrides(evolutions, overrides)
        dump_json(EVOLUTIONS_PATH, evolutions)
        # Reload to verify the written file rather than the in-memory object only.
        evolutions = load_json(EVOLUTIONS_PATH)

    after = compare(evolutions, overrides)
    classified = classify_method_items(evolutions, overrides)
    unresolved_review_items = classified["unresolved_review_items"]
    intentional_specific_cases = classified["intentional_specific_cases"]

    report = {
        "schema_version": "1.1",
        "description": "Evolution method display audit. Curated overrides prefer general/modern methods while preserving game-specific alternatives as notes.",
        "summary": {
            "evolution_edges": len(evolutions),
            "overrides_checked": len(overrides),
            "differences_before_apply": sum(1 for r in before if r["status"] != "ok"),
            "fields_changed": changed,
            "differences_after_apply": sum(1 for r in after if r["status"] != "ok"),
            "unresolved_review_items_count": len(unresolved_review_items),
            "intentional_specific_cases_count": len(intentional_specific_cases),
        },
        "override_details": after,
        "unresolved_review_items": unresolved_review_items,
        "intentional_specific_cases": intentional_specific_cases,
    }

    if args.report:
        dump_json(REPORT_PATH, report)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_human_summary(report)
        if args.report:
            print(f"\nReport written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
