#!/usr/bin/env python3
"""Build offline Pokédex profile details for the Flask app.

Runtime pages should not call PokéAPI. Run this script manually when you want to
refresh abilities and move learnsets, then deploy the generated JSON with the app.

Examples:
  python data/build_profile_details_cache.py --online
  python data/build_profile_details_cache.py --online --limit 25
  python data/build_profile_details_cache.py --online --only palafin-zero charizard
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import requests
except Exception:  # pragma: no cover - friendly CLI error when dependency missing
    requests = None

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
PROCESSED_PATH = os.path.join(ROOT, "processed_pokemon_cache.json")
OUTPUT_PATH = os.path.join(SCRIPT_DIR, "pokemon_profile_details.json")
SHARD_INDEX_PATH = os.path.join(SCRIPT_DIR, "pokemon_profile_details_index.json")
SHARD_DIR = os.path.join(SCRIPT_DIR, "profile_details_shards")
POKEAPI_BASE = "https://pokeapi.co/api/v2"

VERSION_GROUP_GENERATIONS = {
    "red-blue": "Generation I", "yellow": "Generation I",
    "gold-silver": "Generation II", "crystal": "Generation II",
    "ruby-sapphire": "Generation III", "emerald": "Generation III",
    "firered-leafgreen": "Generation III", "colosseum": "Generation III", "xd": "Generation III",
    "diamond-pearl": "Generation IV", "platinum": "Generation IV", "heartgold-soulsilver": "Generation IV",
    "black-white": "Generation V", "black-2-white-2": "Generation V",
    "x-y": "Generation VI", "omega-ruby-alpha-sapphire": "Generation VI",
    "sun-moon": "Generation VII", "ultra-sun-ultra-moon": "Generation VII", "lets-go-pikachu-lets-go-eevee": "Generation VII",
    "sword-shield": "Generation VIII", "brilliant-diamond-and-shining-pearl": "Generation VIII", "legends-arceus": "Generation VIII",
    "scarlet-violet": "Generation IX",
}
GENERATION_ORDER = [
    "Generation IX", "Generation VIII", "Generation VII", "Generation VI", "Generation V",
    "Generation IV", "Generation III", "Generation II", "Generation I", "Other",
]
METHOD_DISPLAY = {
    "level-up": "Level Up", "machine": "TM/TR/HM", "egg": "Egg", "tutor": "Tutor",
    "stadium-surfing-pikachu": "Special", "light-ball-egg": "Egg", "colosseum-purification": "Purification",
    "xd-shadow": "XD Shadow", "xd-purification": "Purification", "form-change": "Form Change",
    "zygarde-cube": "Zygarde Cube",
}

# Some PokeAPI species do not expose a base /pokemon/{species} endpoint.
# The app may intentionally collapse these forms for display, so the offline
# profile cache builder uses a representative PokeAPI form to obtain shared
# abilities/moves. Runtime pages still display the clean app name.
POKEAPI_DETAIL_FALLBACKS = {
    "frillish": ["frillish-male", "frillish-female"],
    "jellicent": ["jellicent-male", "jellicent-female"],
    "pyroar": ["pyroar-male", "pyroar-female"],
    "meowstic": ["meowstic-male", "meowstic-female"],
    "mimikyu": ["mimikyu-disguised", "mimikyu-busted"],
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_label(value: str) -> str:
    return (value or "").replace("-", " ").replace("_", " ").title()


def load_json(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)



def profile_shard_id(key: str) -> str:
    value = (key or "").strip().lower()
    if not value:
        return "other"
    first = value[0]
    return first if first.isalnum() else "other"


def write_sharded_runtime_cache(cache: Dict[str, Any], strip_single: bool = False) -> Dict[str, Any]:
    """Write a PythonAnywhere-friendly sharded profile cache.

    The full pokemon_profile_details.json can easily exceed PythonAnywhere's
    browser upload limit. This writes small shard files under
    data/profile_details_shards/ plus a small index file. Runtime Flask pages
    load only the shard for the requested Pokémon.
    """
    profiles = cache.get("profiles", {}) if isinstance(cache, dict) else {}
    if not isinstance(profiles, dict) or not profiles:
        raise SystemExit("No profiles found to shard. Build or copy pokemon_profile_details.json first.")

    os.makedirs(SHARD_DIR, exist_ok=True)
    for filename in os.listdir(SHARD_DIR):
        if filename.endswith(".json"):
            try:
                os.remove(os.path.join(SHARD_DIR, filename))
            except OSError:
                pass

    shards: Dict[str, Dict[str, Any]] = defaultdict(dict)
    key_to_shard: Dict[str, str] = {}
    for key, details in sorted(profiles.items()):
        shard = profile_shard_id(key)
        shards[shard][key] = details
        key_to_shard[key] = shard

    shard_counts = {}
    for shard, shard_profiles in sorted(shards.items()):
        shard_payload = {
            "schema_version": "1.1-sharded-profile-details",
            "generated_at": cache.get("generated_at") or utc_now(),
            "source": cache.get("source") or "PokéAPI REST summarized for offline runtime use",
            "shard": shard,
            "profiles": shard_profiles,
        }
        shard_path = os.path.join(SHARD_DIR, f"{shard}.json")
        save_json(shard_path, shard_payload)
        shard_counts[shard] = len(shard_profiles)

    index_payload = {
        "schema_version": "1.1-sharded-profile-details-index",
        "generated_at": cache.get("generated_at") or utc_now(),
        "source": cache.get("source") or "PokéAPI REST summarized for offline runtime use",
        "profiles_cached": len(profiles),
        "errors_count": len(cache.get("errors", [])),
        "errors": cache.get("errors", []),
        "shard_dir": "profile_details_shards",
        "shard_counts": shard_counts,
        "key_to_shard": key_to_shard,
    }
    save_json(SHARD_INDEX_PATH, index_payload)

    if strip_single:
        stub = {
            "schema_version": "1.1-sharded-runtime-stub",
            "generated_at": index_payload["generated_at"],
            "source": "Profiles are stored in data/profile_details_shards/. See pokemon_profile_details_index.json.",
            "profiles": {},
            "errors": cache.get("errors", []),
            "profiles_cached_in_shards": len(profiles),
        }
        save_json(OUTPUT_PATH, stub)

    return index_payload


def load_profile_cache_for_status() -> Dict[str, Any]:
    """Load either the sharded runtime index or the older single-file cache."""
    index = load_json(SHARD_INDEX_PATH, {})
    if isinstance(index, dict) and isinstance(index.get("key_to_shard"), dict):
        return {
            "format": "sharded",
            "profiles": {key: True for key in index.get("key_to_shard", {})},
            "errors": index.get("errors", []),
            "generated_at": index.get("generated_at"),
            "profiles_cached": index.get("profiles_cached", len(index.get("key_to_shard", {}))),
            "index_path": SHARD_INDEX_PATH,
        }
    cache = load_json(OUTPUT_PATH, {})
    profiles = cache.get("profiles", {}) if isinstance(cache, dict) else {}
    return {
        "format": "single",
        "profiles": profiles if isinstance(profiles, dict) else {},
        "errors": cache.get("errors", []) if isinstance(cache, dict) else [],
        "generated_at": cache.get("generated_at") if isinstance(cache, dict) else None,
        "profiles_cached": len(profiles) if isinstance(profiles, dict) else 0,
        "index_path": None,
    }

def request_json(session: "requests.Session", url: str, timeout: int, retries: int = 3) -> Dict[str, Any]:
    last_exc: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            response = session.get(url, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except Exception as exc:  # pragma: no cover - depends on network
            last_exc = exc
            if attempt < retries:
                time.sleep(0.35 * attempt)
    raise RuntimeError(f"Could not fetch {url}: {last_exc}")


def pokeapi_get(session: "requests.Session", endpoint: str, timeout: int) -> Dict[str, Any]:
    endpoint = endpoint.strip("/")
    return request_json(session, f"{POKEAPI_BASE}/{endpoint}", timeout=timeout)


def _add_candidate(candidates: List[str], seen: set, value: Optional[str]) -> None:
    value = (value or "").strip().lower()
    if value and value not in seen:
        candidates.append(value)
        seen.add(value)


def pokemon_endpoint_candidates(pokemon_key: str, species: str) -> List[str]:
    """Return likely /pokemon endpoint names for an app key.

    The processed cache sometimes uses display-collapsed keys such as
    "frillish" or "pyroar" while PokeAPI only exposes gender/form endpoints
    like "frillish-male" or "pyroar-male".
    """
    candidates: List[str] = []
    seen = set()
    key = (pokemon_key or "").strip().lower()
    sp = (species or "").strip().lower()
    _add_candidate(candidates, seen, key)
    _add_candidate(candidates, seen, sp)
    for fallback in POKEAPI_DETAIL_FALLBACKS.get(key, []):
        _add_candidate(candidates, seen, fallback)
    for fallback in POKEAPI_DETAIL_FALLBACKS.get(sp, []):
        _add_candidate(candidates, seen, fallback)
    return candidates


def fetch_pokemon_payload_with_fallbacks(
    session: "requests.Session",
    pokemon_key: str,
    species: str,
    timeout: int,
) -> Tuple[str, Dict[str, Any]]:
    """Fetch a Pokémon payload, trying representative forms when needed."""
    errors: List[str] = []
    tried = set()

    for candidate in pokemon_endpoint_candidates(pokemon_key, species):
        tried.add(candidate)
        try:
            return candidate, pokeapi_get(session, f"pokemon/{candidate}", timeout)
        except Exception as exc:
            errors.append(f"{candidate}: {exc}")

    # Last-resort dynamic fallback: ask PokeAPI species for its varieties and
    # try the listed pokemon endpoints. This catches future collapsed form cases
    # without needing to edit POKEAPI_DETAIL_FALLBACKS every time.
    species_key = (species or pokemon_key or "").strip().lower()
    if species_key:
        try:
            species_payload = pokeapi_get(session, f"pokemon-species/{species_key}", timeout)
            varieties = species_payload.get("varieties", [])
            # Prefer the default variety first, then shorter names for stable UI data.
            varieties = sorted(varieties, key=lambda v: (not bool(v.get("is_default")), len(v.get("pokemon", {}).get("name") or "")))
            for variety in varieties:
                candidate = variety.get("pokemon", {}).get("name")
                if not candidate or candidate in tried:
                    continue
                tried.add(candidate)
                try:
                    return candidate, pokeapi_get(session, f"pokemon/{candidate}", timeout)
                except Exception as exc:
                    errors.append(f"{candidate}: {exc}")
        except Exception as exc:
            errors.append(f"pokemon-species/{species_key}: {exc}")

    raise RuntimeError("Could not fetch any candidate Pokémon endpoint: " + " | ".join(errors[-8:]))


def summarize_ability_detail(entry: Dict[str, Any], ability_details: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    ability_name = entry.get("ability", {}).get("name") or ""
    detail = ability_details.get(ability_name) or {}
    effect = ""
    flavor = ""
    for effect_entry in detail.get("effect_entries", []):
        if effect_entry.get("language", {}).get("name") == "en":
            effect = effect_entry.get("short_effect") or effect_entry.get("effect") or ""
            break
    for flavor_entry in reversed(detail.get("flavor_text_entries", [])):
        if flavor_entry.get("language", {}).get("name") == "en":
            flavor = " ".join((flavor_entry.get("flavor_text") or "").split())
            break
    return {
        "name": clean_label(ability_name),
        "key": ability_name,
        "is_hidden": bool(entry.get("is_hidden")),
        "slot": entry.get("slot"),
        "effect": effect,
        "flavor_text": flavor,
    }


def summarize_moves_by_generation(pokemon_payload: Dict[str, Any]) -> Tuple[Dict[str, List[Dict[str, Any]]], List[str]]:
    grouped: Dict[str, Dict[tuple, Dict[str, Any]]] = defaultdict(dict)
    for move_entry in pokemon_payload.get("moves", []):
        move_name = move_entry.get("move", {}).get("name")
        if not move_name:
            continue
        for detail in move_entry.get("version_group_details", []):
            version_group = detail.get("version_group", {}).get("name") or "unknown"
            generation = VERSION_GROUP_GENERATIONS.get(version_group, "Other")
            method = detail.get("move_learn_method", {}).get("name") or "unknown"
            level = detail.get("level_learned_at") or 0

            # The profile page is organized by generation. Within the same generation,
            # the exact game/version group is usually noise for in-game lookup.
            # Collapse rows that have the same move, method, and level in that generation.
            row_key = (move_name, method, level)
            existing = grouped[generation].get(row_key)
            if existing:
                if version_group not in existing["version_groups"]:
                    existing["version_groups"].append(version_group)
                    existing["version_group_displays"].append(clean_label(version_group))
                continue

            grouped[generation][row_key] = {
                "name": clean_label(move_name),
                "key": move_name,
                "version_group": version_group,
                "version_group_display": clean_label(version_group),
                "version_groups": [version_group],
                "version_group_displays": [clean_label(version_group)],
                "learn_method": method,
                "learn_method_display": METHOD_DISPLAY.get(method, clean_label(method)),
                "level": level,
            }

    result: Dict[str, List[Dict[str, Any]]] = {}
    for generation, moves_by_key in grouped.items():
        result[generation] = sorted(moves_by_key.values(), key=lambda m: (
            m["learn_method_display"],
            m["level"] if m["level"] else 999,
            m["name"],
        ))
    move_generations = [g for g in GENERATION_ORDER if g in result] + sorted(g for g in result if g not in GENERATION_ORDER)
    return result, move_generations


def build_for_pokemon(
    session: "requests.Session",
    pokemon_key: str,
    species: str,
    ability_raw_cache: Dict[str, Dict[str, Any]],
    timeout: int,
    pause: float,
) -> Dict[str, Any]:
    source_key, pokemon_payload = fetch_pokemon_payload_with_fallbacks(session, pokemon_key, species, timeout)

    # Fetch each ability detail once and reuse across every Pokémon.
    for entry in pokemon_payload.get("abilities", []):
        ability_name = entry.get("ability", {}).get("name")
        if ability_name and ability_name not in ability_raw_cache:
            ability_raw_cache[ability_name] = pokeapi_get(session, f"ability/{ability_name}", timeout)
            if pause:
                time.sleep(pause)

    abilities = [summarize_ability_detail(entry, ability_raw_cache) for entry in pokemon_payload.get("abilities", [])]
    moves_by_generation, move_generations = summarize_moves_by_generation(pokemon_payload)
    return {
        "source": "pokeapi-local-cache-build",
        "source_key": source_key,
        "abilities": abilities,
        "moves_by_generation": moves_by_generation,
        "move_generations": move_generations,
    }



def drop_errors_for_key(errors: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    return [err for err in errors if err.get("key") != key]


def upsert_error(errors: List[Dict[str, Any]], key: str, species: str, message: str) -> List[Dict[str, Any]]:
    filtered = drop_errors_for_key(errors, key)
    filtered.append({"key": key, "species": species, "error": message, "last_seen": utc_now()})
    return filtered

def build_cache(args: argparse.Namespace) -> Dict[str, Any]:
    if requests is None:
        raise SystemExit("The 'requests' package is required. Install requirements.txt first.")
    if not args.online:
        raise SystemExit("Pass --online to fetch and rebuild the local profile cache.")

    processed = load_json(PROCESSED_PATH, [])
    if not isinstance(processed, list):
        raise SystemExit(f"Could not read list from {PROCESSED_PATH}")

    selected_keys = {k.lower() for k in args.only} if args.only else None
    entries = [p for p in processed if p.get("name")]
    if selected_keys:
        entries = [p for p in entries if p.get("name", "").lower() in selected_keys or p.get("species", "").lower() in selected_keys]
    if args.limit:
        entries = entries[:args.limit]

    existing = load_json(OUTPUT_PATH, {}) if args.resume else {}
    if not isinstance(existing, dict) or not isinstance(existing.get("profiles"), dict):
        existing = {
            "schema_version": "1.0",
            "generated_at": None,
            "source": "PokéAPI REST",
            "profiles": {},
            "ability_raw_cache": {},
            "errors": [],
        }

    profiles: Dict[str, Any] = existing.setdefault("profiles", {})
    ability_raw_cache: Dict[str, Dict[str, Any]] = existing.setdefault("ability_raw_cache", {})
    errors: List[Dict[str, Any]] = existing.setdefault("errors", [])

    session = requests.Session()
    total = len(entries)
    for idx, entry in enumerate(entries, 1):
        key = entry.get("name")
        species = entry.get("species") or key
        if not args.force and key in profiles:
            continue
        try:
            profiles[key] = build_for_pokemon(session, key, species, ability_raw_cache, args.timeout, args.pause)
            errors = drop_errors_for_key(errors, key)
            existing["errors"] = errors
        except Exception as exc:  # pragma: no cover - depends on live API
            errors = upsert_error(errors, key, species, str(exc))
            existing["errors"] = errors
        if idx % args.save_every == 0 or idx == total:
            existing.update({
                "schema_version": "1.0",
                "generated_at": utc_now(),
                "source": "PokéAPI REST summarized for offline runtime use",
                "pokemon_entries_requested": total,
                "profiles_cached": len(profiles),
                "errors_count": len(errors),
            })
            save_json(OUTPUT_PATH, existing)
            print(f"Cached {len(profiles)}/{total} requested Pokémon details...", flush=True)
        if args.pause:
            time.sleep(args.pause)

    # Ability raw responses are useful for resume but not needed at runtime. Keep
    # them by default for incremental rebuilds; --strip-raw removes them.
    existing.update({
        "schema_version": "1.0",
        "generated_at": utc_now(),
        "source": "PokéAPI REST summarized for offline runtime use",
        "pokemon_entries_requested": total,
        "profiles_cached": len(profiles),
        "errors_count": len(errors),
    })
    if args.strip_raw:
        existing.pop("ability_raw_cache", None)
    save_json(OUTPUT_PATH, existing)
    if getattr(args, "write_shards", False):
        write_sharded_runtime_cache(existing, strip_single=getattr(args, "strip_single_after_shards", False))
    return existing



def cache_status() -> Dict[str, Any]:
    processed = load_json(PROCESSED_PATH, [])
    runtime_cache = load_profile_cache_for_status()
    keys = [p.get("name") for p in processed if p.get("name")] if isinstance(processed, list) else []
    profiles = runtime_cache.get("profiles", {})
    missing = [k for k in keys if k not in profiles]
    errors = runtime_cache.get("errors", []) if isinstance(runtime_cache, dict) else []
    unresolved_errors = [e for e in errors if e.get("key") in missing]
    return {
        "expected": len(keys),
        "cached": len(profiles),
        "missing": len(missing),
        "missing_keys": missing,
        "stored_errors": len(errors),
        "unresolved_errors": len(unresolved_errors),
        "unresolved_error_keys": [e.get("key") for e in unresolved_errors],
        "cache_format": runtime_cache.get("format"),
        "generated_at": runtime_cache.get("generated_at"),
        "shard_index_path": runtime_cache.get("index_path"),
    }

def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build local ability/move details cache for Pokémon profile pages.")
    parser.add_argument("--online", action="store_true", help="Allow network requests to PokéAPI and rebuild the cache.")
    parser.add_argument("--only", nargs="*", default=[], help="Optional Pokémon keys/species to rebuild, e.g. palafin-zero charizard.")
    parser.add_argument("--limit", type=int, default=0, help="Limit entries for a quick test build.")
    parser.add_argument("--timeout", type=int, default=20, help="Request timeout in seconds.")
    parser.add_argument("--pause", type=float, default=0.03, help="Pause between requests to be polite to the API.")
    parser.add_argument("--save-every", type=int, default=25, help="Write progress every N Pokémon.")
    parser.add_argument("--resume", action="store_true", default=True, help="Resume from existing cache. Enabled by default.")
    parser.add_argument("--force", action="store_true", help="Refetch keys that already exist in the cache.")
    parser.add_argument("--strip-raw", action="store_true", help="Remove raw ability cache after build to reduce file size.")
    parser.add_argument("--write-shards", action="store_true", help="Also write PythonAnywhere-friendly profile shards after building.")
    parser.add_argument("--strip-single-after-shards", action="store_true", help="After writing shards, replace the large single JSON with a tiny stub.")
    parser.add_argument("--split-shards", action="store_true", help="Split an existing pokemon_profile_details.json into shards without fetching.")
    parser.add_argument("--status", action="store_true", help="Print current cache coverage without fetching anything.")
    parser.add_argument("--retry-missing", action="store_true", help="Fetch only keys missing from the current local cache.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.split_shards:
        cache = load_json(OUTPUT_PATH, {})
        index = write_sharded_runtime_cache(cache, strip_single=args.strip_single_after_shards)
        print(json.dumps({
            "cache_format": "sharded",
            "index_path": SHARD_INDEX_PATH,
            "shard_dir": SHARD_DIR,
            "profiles_cached": index.get("profiles_cached"),
            "shards": len(index.get("shard_counts", {})),
            "single_file_replaced_with_stub": bool(args.strip_single_after_shards),
        }, indent=2))
        return 0

    if args.status:
        print(json.dumps(cache_status(), indent=2))
        return 0

    if args.retry_missing:
        status = cache_status()
        args.only = status.get("missing_keys", [])
        args.online = True
        args.force = True
        if not args.only:
            print(json.dumps(status, indent=2))
            return 0

    cache = build_cache(args)
    print(json.dumps({
        "output_path": OUTPUT_PATH,
        "schema_version": cache.get("schema_version"),
        "generated_at": cache.get("generated_at"),
        "profiles_cached": cache.get("profiles_cached", len(cache.get("profiles", {}))),
        "errors_count": cache.get("errors_count", len(cache.get("errors", []))),
        "shards_written": bool(getattr(args, "write_shards", False)),
        "single_file_replaced_with_stub": bool(getattr(args, "strip_single_after_shards", False)),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
