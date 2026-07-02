#!/usr/bin/env python3
"""Audit and optionally repair local Pokémon sprite references.

The processed cache stores one sprite_url per form. Some entries point at form
filenames that may not exist locally even though an equivalent species or sibling
form sprite is present. This script reports those missing paths and can create
local alias copies so every cache sprite_url resolves.

Usage:
  python data/verify_sprites.py
  python data/verify_sprites.py --fix
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH = ROOT / "processed_pokemon_cache.json"
SPRITE_DIR = ROOT / "static" / "sprites"
REPORT_PATH = ROOT / "data" / "sprite_audit_report.json"

# Prefer these known-good local sprites when the exact form file is absent.
# These are only local file aliases; they do not change the Pokémon data model.
PREFERRED_SOURCE_BY_KEY = {
    "palafin-zero": "palafin.png",
    "oinkologne-male": "oinkologne.png",
    "maushold-family-of-four": "maushold.png",
    "dudunsparce-two-segment": "dudunsparce.png",
    "squawkabilly-green-plumage": "squawkabilly.png",
    "tatsugiri-curly": "tatsugiri.png",
    "zygarde-10": "zygarde-10-power-construct.png",
}

NOISY_FORM_TOKENS = ("gmax", "totem", "starter")


def load_cache() -> list[dict]:
    with CACHE_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def sprite_path_from_url(url: str) -> Path | None:
    if not url or not url.startswith("/static/sprites/"):
        return None
    return ROOT / url.lstrip("/")


def find_repair_source(entry: dict, entries_by_species: dict[str, list[dict]]) -> Path | None:
    key = entry.get("name", "")
    species = entry.get("species", "")

    preferred = PREFERRED_SOURCE_BY_KEY.get(key)
    if preferred:
        preferred_path = SPRITE_DIR / preferred
        if preferred_path.exists():
            return preferred_path

    species_path = SPRITE_DIR / f"{species}.png"
    if species_path.exists():
        return species_path

    sibling_entries = entries_by_species.get(species, [])
    sibling_candidates = []
    for sibling in sibling_entries:
        if sibling.get("name") == key:
            continue
        path = sprite_path_from_url(sibling.get("sprite_url", ""))
        if path and path.exists():
            sibling_candidates.append((sibling.get("name", ""), path))

    if not sibling_candidates:
        return None

    sibling_candidates.sort(key=lambda item: (
        any(token in item[0] for token in NOISY_FORM_TOKENS),
        len(item[0]),
        item[0],
    ))
    return sibling_candidates[0][1]


def audit(fix: bool = False) -> dict:
    entries = load_cache()
    entries_by_species: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        entries_by_species[entry.get("species", "")].append(entry)

    missing = []
    repaired = []
    unrepaired = []

    for entry in entries:
        sprite_url = entry.get("sprite_url", "")
        target = sprite_path_from_url(sprite_url)
        if target is None:
            missing.append({
                "name": entry.get("name"),
                "species": entry.get("species"),
                "sprite_url": sprite_url,
                "reason": "not a local /static/sprites URL",
            })
            continue
        if target.exists():
            continue

        source = find_repair_source(entry, entries_by_species)
        item = {
            "name": entry.get("name"),
            "species": entry.get("species"),
            "missing_sprite_url": sprite_url,
            "target": str(target.relative_to(ROOT)),
            "repair_source": str(source.relative_to(ROOT)) if source else None,
        }
        missing.append(item)

        if fix and source:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            repaired.append(item)
        elif not source:
            unrepaired.append(item)

    unresolved_after_fix = []
    if fix:
        for entry in entries:
            target = sprite_path_from_url(entry.get("sprite_url", ""))
            if target is None or not target.exists():
                unresolved_after_fix.append({
                    "name": entry.get("name"),
                    "species": entry.get("species"),
                    "sprite_url": entry.get("sprite_url", ""),
                })

    report = {
        "pokemon_entries": len(entries),
        "sprite_directory": str(SPRITE_DIR),
        "missing_before_fix": len(missing),
        "repaired": len(repaired),
        "unrepaired_without_source": len(unrepaired),
        "unresolved_after_fix": len(unresolved_after_fix),
        "missing": missing,
        "repaired_items": repaired,
        "unrepaired_items": unrepaired,
        "unresolved_after_fix_items": unresolved_after_fix,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit local Pokémon sprite files.")
    parser.add_argument("--fix", action="store_true", help="Copy local fallback sprites into missing exact form filenames.")
    args = parser.parse_args()

    report = audit(fix=args.fix)
    print(json.dumps({
        "pokemon_entries": report["pokemon_entries"],
        "missing_before_fix": report["missing_before_fix"],
        "repaired": report["repaired"],
        "unrepaired_without_source": report["unrepaired_without_source"],
        "unresolved_after_fix": report["unresolved_after_fix"],
        "report_path": str(REPORT_PATH),
    }, indent=2))


if __name__ == "__main__":
    main()
