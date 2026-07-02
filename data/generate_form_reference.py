#!/usr/bin/env python3
"""Generate context-aware form resolution metadata.

The app needs to treat form names differently depending on context:
- type effectiveness can collapse forms that share the same type signature;
- stats can collapse forms that share the same full base stat signature;
- Bulbapedia links should usually point at the species page, not the raw form key.

This script generates data/form_reference.json plus compatibility copies for the
existing static/pokemon_reference_map_types.json and
static/pokemon_reference_map_stats.json files.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from urllib.parse import quote

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROCESSED_PATH = os.path.join(ROOT, "processed_pokemon_cache.json")
DATA_OUT = os.path.join(ROOT, "data", "form_reference.json")
STATIC_OUT = os.path.join(ROOT, "static", "form_reference.json")
TYPE_MAP_OUT = os.path.join(ROOT, "static", "pokemon_reference_map_types.json")
STATS_MAP_OUT = os.path.join(ROOT, "static", "pokemon_reference_map_stats.json")

# Forms that are usually visual-only or not useful as separate search results.
NOISY_TOKENS = {
    "gmax", "totem", "starter", "busted", "disguised", "original",
    "cap", "cosplay", "rock", "star", "pop", "belle", "phd", "libre",
}

# Better human names and Bulbapedia page names for species where title-casing
# hyphenated keys gives bad results.
SPECIES_NAME_OVERRIDES = {
    "farfetchd": "Farfetch'd",
    "sirfetchd": "Sirfetch'd",
    "mr-mime": "Mr. Mime",
    "mr-rime": "Mr. Rime",
    "mime-jr": "Mime Jr.",
    "ho-oh": "Ho-Oh",
    "porygon-z": "Porygon-Z",
    "type-null": "Type: Null",
    "jangmo-o": "Jangmo-o",
    "hakamo-o": "Hakamo-o",
    "kommo-o": "Kommo-o",
    "nidoran-f": "Nidoran♀",
    "nidoran-m": "Nidoran♂",
    "flabebe": "Flabébé",
    "chien-pao": "Chien-Pao",
    "chi-yu": "Chi-Yu",
    "ting-lu": "Ting-Lu",
    "wo-chien": "Wo-Chien",
}

FORM_NAME_OVERRIDES = {
    "pumpkaboo-average": "Pumpkaboo Average Size / Medium Variety",
    "pumpkaboo-small": "Pumpkaboo Small Size / Small Variety",
    "pumpkaboo-large": "Pumpkaboo Large Size / Large Variety",
    "pumpkaboo-super": "Pumpkaboo Super Size / Jumbo Variety",
    "gourgeist-average": "Gourgeist Average Size",
    "gourgeist-small": "Gourgeist Small Size",
    "gourgeist-large": "Gourgeist Large Size",
    "gourgeist-super": "Gourgeist Super Size",
}

# These labels are cleaner as adjectives in display names.
REGIONAL_FORM_WORDS = {
    "alola": "Alolan",
    "galar": "Galarian",
    "hisui": "Hisuian",
    "paldea": "Paldean",
}


def title_words(text: str) -> str:
    return " ".join(part.capitalize() for part in text.replace("_", "-").split("-") if part)


def species_display(species: str) -> str:
    return SPECIES_NAME_OVERRIDES.get(species, title_words(species))


def clean_form_display(entry: dict) -> str:
    key = entry["name"]
    if key in FORM_NAME_OVERRIDES:
        return FORM_NAME_OVERRIDES[key]

    species = entry.get("species") or key.split("-", 1)[0]
    base_display = species_display(species)
    form = (entry.get("form_name") or "").strip("-")
    if not form or key == species:
        return base_display

    parts = form.split("-")
    for regional_key, regional_label in REGIONAL_FORM_WORDS.items():
        if key.endswith(f"-{regional_key}"):
            return f"{regional_label} {base_display}"
    if len(parts) == 1 and parts[0] in REGIONAL_FORM_WORDS:
        return f"{REGIONAL_FORM_WORDS[parts[0]]} {base_display}"

    # Avoid labels like "Pikachu Original Cap" when these are collapsed; this
    # is only used when a form must remain distinct in a context.
    form_label = title_words(form)
    return f"{base_display} {form_label}"


def type_signature(entry: dict) -> tuple[str, ...]:
    return tuple(sorted(entry.get("types") or []))


def stat_signature(entry: dict) -> tuple[tuple[str, int], ...]:
    stats = entry.get("stats") or {}
    return tuple(sorted(stats.items()))


def representative(forms: list[dict]) -> dict:
    def score(e: dict):
        name = e["name"]
        species = e.get("species") or name.split("-", 1)[0]
        tokens = set(name.split("-"))
        return (
            0 if name == species else 1,
            1 if "gmax" in tokens else 0,
            1 if "totem" in tokens else 0,
            int(e.get("id") or 999999),
            len(name),
            name,
        )

    return sorted(forms, key=score)[0]


def bulbapedia_url(page_name: str) -> str:
    # Spaces become underscores; keep punctuation that MediaWiki accepts.
    page = quote(page_name.replace(" ", "_"), safe="_'.:-é♀♂-")
    return f"https://bulbapedia.bulbagarden.net/wiki/{page}_(Pok%C3%A9mon)"


def build_context(forms: list[dict], signature_fn, context: str) -> dict[str, dict]:
    """Return raw_key -> {key, display, group_size, distinct} for one context."""
    by_species: dict[str, list[dict]] = defaultdict(list)
    for entry in forms:
        by_species[entry.get("species") or entry["name"].split("-", 1)[0]].append(entry)

    out: dict[str, dict] = {}
    for species, species_forms in by_species.items():
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for entry in species_forms:
            groups[signature_fn(entry)].append(entry)

        species_has_one_signature = len(groups) == 1
        for group_forms in groups.values():
            rep = representative(group_forms)
            rep_key = rep["name"]
            # If this exact signature is shared by every form of the species,
            # the distinct form label adds no context-specific information.
            group_display = species_display(species) if species_has_one_signature else clean_form_display(rep)
            for entry in group_forms:
                out[entry["name"]] = {
                    f"{context}_key": rep_key,
                    f"{context}_display": group_display,
                    f"{context}_group_size": len(group_forms),
                    f"{context}_distinct": len(group_forms) == 1 and not species_has_one_signature,
                }
    return out


def main() -> None:
    with open(PROCESSED_PATH, encoding="utf-8") as f:
        processed = json.load(f)

    type_ctx = build_context(processed, type_signature, "type")
    stats_ctx = build_context(processed, stat_signature, "stats")

    reference = {}
    for entry in processed:
        key = entry["name"]
        species = entry.get("species") or key.split("-", 1)[0]
        tokens = set(key.split("-")) | set((entry.get("form_name") or "").split("-"))
        hidden = "totem" in tokens
        species_name = species_display(species)
        page = species_name
        reference[key] = {
            "name": key,
            "species": species,
            "species_display": species_name,
            "raw_display": entry.get("display_name") or clean_form_display(entry),
            "form_display": clean_form_display(entry),
            "form_name": entry.get("form_name") or "",
            "searchable": not hidden,
            "bulbapedia_page": page,
            "bulbapedia_url": bulbapedia_url(page),
            **type_ctx[key],
            **stats_ctx[key],
        }

    # Full reference.
    os.makedirs(os.path.dirname(DATA_OUT), exist_ok=True)
    os.makedirs(os.path.dirname(STATIC_OUT), exist_ok=True)
    for path in (DATA_OUT, STATIC_OUT):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(reference, f, indent=2, ensure_ascii=False)

    # Compatibility maps for existing JS. These include the old fields plus new
    # context-aware fields so templates can be patched incrementally.
    type_map = {}
    stats_map = {}
    for key, meta in reference.items():
        type_map[key] = {
            "base_name": meta["species"],
            "collapse_display_name_to": None if meta["type_key"] == key else meta["type_key"],
            "distinct_types": meta["type_distinct"],
            "distinct_stats": None,
            "force_preserve_name": meta["type_key"] == key,
            **meta,
        }
        stats_map[key] = {
            "base_name": meta["species"],
            "collapse_display_name_to": None if meta["stats_key"] == key else meta["stats_key"],
            "distinct_types": None,
            "distinct_stats": meta["stats_distinct"],
            "force_preserve_name": meta["stats_key"] == key,
            **meta,
        }

    with open(TYPE_MAP_OUT, "w", encoding="utf-8") as f:
        json.dump(type_map, f, indent=2, ensure_ascii=False)
    with open(STATS_MAP_OUT, "w", encoding="utf-8") as f:
        json.dump(stats_map, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(reference)} form reference rows")
    print(f"- {DATA_OUT}")
    print(f"- {STATIC_OUT}")
    print(f"- {TYPE_MAP_OUT}")
    print(f"- {STATS_MAP_OUT}")


if __name__ == "__main__":
    main()
