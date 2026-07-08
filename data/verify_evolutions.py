#!/usr/bin/env python3
"""Audit local evolution data.

Default mode performs offline consistency checks against the files bundled with the app.
Use --online to compare local species-level edges against live PokéAPI evolution chains.

Why there are multiple counts:
  - Local form-level edges: app rows such as "dunsparce -> dudunsparce-two-segment".
  - Local species-level edges: form rows collapsed to species, used for PokéAPI comparison.
  - PokéAPI chain count: family trees, including single-stage species with no evolution edge.
  - PokéAPI species-level direct edges: parent -> child links inside those family trees.

Examples:
  python data/verify_evolutions.py
  python data/verify_evolutions.py --online
  python data/verify_evolutions.py --online --output data/evolution_audit_report.json
  python data/verify_evolutions.py --online --cache-online data/pokeapi_evolution_chains_cache.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_EVOLUTIONS = os.path.join(ROOT, "data", "evolutions.json")
DEFAULT_CACHE = os.path.join(ROOT, "processed_pokemon_cache.json")
DEFAULT_OUTPUT = os.path.join(ROOT, "data", "evolution_audit_report.json")
DEFAULT_ONLINE_CACHE = os.path.join(ROOT, "data", "pokeapi_evolution_chains_cache.json")
POKEAPI_BASE = "https://pokeapi.co/api/v2"

# A small set of recent/commonly-missed form-level edges that should always be present locally.
# These are not a substitute for --online; they catch mistakes when the app is used offline.
REQUIRED_LOCAL_EDGES = {
    ("applin", "dipplin"),
    ("dipplin", "hydrapple"),
    ("duraludon", "archaludon"),
    ("dunsparce", "dudunsparce-two-segment"),
    ("dunsparce", "dudunsparce-three-segment"),
    ("darumaka", "darmanitan-standard"),
    ("darumaka-galar", "darmanitan-galar-standard"),
    ("finizen", "palafin-zero"),
    ("lechonk", "oinkologne-male"),
    ("tandemaus", "maushold-family-of-four"),
}

# PokéAPI includes this as a species-level chain edge, but core-game references treat
# Phione and Manaphy as not evolving into/from one another. Keep it out of app data
# and out of failure counts unless you intentionally want strict PokéAPI parity.
IGNORED_POKEAPI_EDGES = {
    ("phione", "manaphy"),
}

# Some PokéAPI species are represented locally by a specific form key. This map is used only
# when a local edge references a form whose processed cache species field is missing/unexpected.
SPECIES_ALIASES = {
    "basculin-white-striped": "basculin",
    "basculegion-male": "basculegion",
    "basculegion-female": "basculegion",
    "dudunsparce-two-segment": "dudunsparce",
    "dudunsparce-three-segment": "dudunsparce",
    "maushold-family-of-three": "maushold",
    "maushold-family-of-four": "maushold",
    "palafin-zero": "palafin",
    "palafin-hero": "palafin",
    "tatsugiri-curly": "tatsugiri",
    "tatsugiri-droopy": "tatsugiri",
    "tatsugiri-stretchy": "tatsugiri",
}


def load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def display_edge(edge: Tuple[str, str]) -> str:
    return f"{edge[0]} -> {edge[1]}"


def clean_species_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return name
    return SPECIES_ALIASES.get(name, name)


def pokemon_maps(processed: List[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    by_key = {p["name"]: p for p in processed if p.get("name")}
    key_to_species = {k: clean_species_name(v.get("species") or k) for k, v in by_key.items()}
    for key, species in SPECIES_ALIASES.items():
        key_to_species.setdefault(key, species)
    return by_key, key_to_species


def local_species_edge(edge: Dict[str, Any], key_to_species: Dict[str, str]) -> Tuple[str, str]:
    return (
        clean_species_name(key_to_species.get(edge.get("from"), edge.get("from"))),
        clean_species_name(key_to_species.get(edge.get("to"), edge.get("to"))),
    )


def detect_cycles(edges: List[Dict[str, Any]]) -> List[List[str]]:
    graph: Dict[str, List[str]] = defaultdict(list)
    for edge in edges:
        graph[edge.get("from")].append(edge.get("to"))

    cycles: List[List[str]] = []
    visiting: Set[str] = set()
    visited: Set[str] = set()
    stack: List[str] = []

    def dfs(node: str) -> None:
        if node in visiting:
            try:
                start = stack.index(node)
                cycles.append(stack[start:] + [node])
            except ValueError:
                cycles.append([node, node])
            return
        if node in visited:
            return
        visiting.add(node)
        stack.append(node)
        for child in graph.get(node, []):
            dfs(child)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for node in list(graph):
        dfs(node)
    return cycles


def offline_audit(evolutions: List[Dict[str, Any]], processed: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_key, key_to_species = pokemon_maps(processed)
    pokemon_keys = set(by_key)

    missing_from = sorted({e.get("from") for e in evolutions if e.get("from") not in pokemon_keys})
    missing_to = sorted({e.get("to") for e in evolutions if e.get("to") not in pokemon_keys})

    exact_counts = Counter((
        e.get("from"), e.get("to"), e.get("trigger"), e.get("item"), e.get("held_item"),
        e.get("known_move"), e.get("known_move_type"), e.get("location"), e.get("min_level"),
        e.get("min_happiness"), e.get("time_of_day"), e.get("gender"),
    ) for e in evolutions)
    duplicate_exact_edges = [{"edge": list(edge), "count": count} for edge, count in exact_counts.items() if count > 1]

    local_species_edges = {local_species_edge(e, key_to_species) for e in evolutions}
    required_missing = sorted(REQUIRED_LOCAL_EDGES - {(e.get("from"), e.get("to")) for e in evolutions})

    inbound = defaultdict(list)
    for e in evolutions:
        inbound[e.get("to")].append(e)

    multiple_inbound_targets = sorted(
        [k for k, v in inbound.items() if len({(x.get("from"), x.get("trigger"), x.get("item"), x.get("known_move")) for x in v}) > 1]
    )

    cycles = detect_cycles(evolutions)

    return {
        "mode": "offline",
        "notes": {
            "counting_modes": [
                "pokemon_entries counts forms/varieties in processed_pokemon_cache.json.",
                "local_form_level_edges counts app rows in data/evolutions.json.",
                "local_species_level_edges collapses app edges to PokéAPI species names for online comparison.",
                "PokéAPI evolution-chain count is family-tree count, not direct evolution count.",
            ]
        },
        "summary": {
            "pokemon_entries": len(processed),
            "local_form_level_edges": len(evolutions),
            "local_species_level_edges": len(local_species_edges),
            "missing_from_references": len(missing_from),
            "missing_to_references": len(missing_to),
            "duplicate_exact_edges": len(duplicate_exact_edges),
            "cycles": len(cycles),
            "required_recent_edges_missing": len(required_missing),
        },
        "missing_from_references": missing_from,
        "missing_to_references": missing_to,
        "duplicate_exact_edges": duplicate_exact_edges,
        "cycles": cycles,
        "required_recent_edges_missing": [display_edge(e) for e in required_missing],
        "multiple_inbound_targets_review": multiple_inbound_targets,
        "local_species_edges": [display_edge(e) for e in sorted(local_species_edges)],
    }


def fetch_json(url: str, pause: float = 0.0, retries: int = 3) -> Any:
    if pause:
        time.sleep(pause)
    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PokemonTypingEvolutionAudit/1.0"})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"Failed to fetch {url}: {last_error}")


def extract_pokeapi_edges(chain_node: Dict[str, Any]) -> Set[Tuple[str, str]]:
    edges: Set[Tuple[str, str]] = set()
    parent = chain_node["species"]["name"]
    for child in chain_node.get("evolves_to", []):
        child_name = child["species"]["name"]
        edges.add((parent, child_name))
        edges |= extract_pokeapi_edges(child)
    return edges


def collect_pokeapi_chain_species(chain_node: Dict[str, Any]) -> Set[str]:
    species = {chain_node["species"]["name"]}
    for child in chain_node.get("evolves_to", []):
        species |= collect_pokeapi_chain_species(child)
    return species


def online_data_from_rest(limit: int | None = None, pause: float = 0.03) -> Dict[str, Any]:
    species_index = fetch_json(f"{POKEAPI_BASE}/pokemon-species?limit=10000")
    chain_index = fetch_json(f"{POKEAPI_BASE}/evolution-chain?limit=10000")

    results = chain_index.get("results", [])
    if limit:
        results = results[:limit]

    official_edges: Set[Tuple[str, str]] = set()
    chain_species: Set[str] = set()
    chains: List[Dict[str, Any]] = []

    for i, item in enumerate(results, 1):
        chain = fetch_json(item["url"], pause=pause)
        chains.append(chain)
        official_edges |= extract_pokeapi_edges(chain["chain"])
        chain_species |= collect_pokeapi_chain_species(chain["chain"])
        if i % 50 == 0:
            print(f"Fetched {i}/{len(results)} PokéAPI chains...", file=sys.stderr)

    return {
        "source": "pokeapi-rest",
        "fetched_at_unix": int(time.time()),
        "pokemon_species_count": species_index.get("count"),
        "evolution_chain_count": chain_index.get("count"),
        "fetched_chain_count": len(results),
        "chain_species_count": len(chain_species),
        "direct_species_edges": [list(e) for e in sorted(official_edges)],
        "chains": chains,
    }


def load_or_fetch_online_data(cache_path: Optional[str], refresh: bool, limit: int | None, pause: float) -> Dict[str, Any]:
    if cache_path and os.path.exists(cache_path) and not refresh and not limit:
        return load_json(cache_path)
    data = online_data_from_rest(limit=limit, pause=pause)
    if cache_path and not limit:
        save_json(cache_path, data)
    return data


def merge_online_audit(report: Dict[str, Any], evolutions: List[Dict[str, Any]], processed: List[Dict[str, Any]], limit: int | None, pause: float, cache_path: Optional[str], refresh_online: bool) -> Dict[str, Any]:
    _, key_to_species = pokemon_maps(processed)
    local_edges = {local_species_edge(e, key_to_species) for e in evolutions}
    online = load_or_fetch_online_data(cache_path=cache_path, refresh=refresh_online, limit=limit, pause=pause)
    official_edges = {tuple(edge) for edge in online.get("direct_species_edges", [])}

    comparable_official_edges = official_edges - IGNORED_POKEAPI_EDGES
    ignored_present = sorted(official_edges & IGNORED_POKEAPI_EDGES)

    missing = sorted(comparable_official_edges - local_edges)
    extra = sorted(local_edges - comparable_official_edges)

    species_count = online.get("pokemon_species_count")
    chain_count = online.get("evolution_chain_count")
    expected_edges_from_counts = None
    if isinstance(species_count, int) and isinstance(chain_count, int) and not limit:
        expected_edges_from_counts = species_count - chain_count

    report["mode"] = "online"
    report["online_source"] = {
        "name": "PokéAPI REST",
        "base_url": POKEAPI_BASE,
        "fetched_chain_count": online.get("fetched_chain_count"),
        "evolution_chain_count": chain_count,
        "pokemon_species_count": species_count,
        "chain_species_count": online.get("chain_species_count"),
        "expected_direct_species_edges_from_counts": expected_edges_from_counts,
        "direct_species_edges_extracted": len(official_edges),
        "direct_species_edges_compared": len(comparable_official_edges),
        "ignored_pokeapi_edges": [display_edge(e) for e in ignored_present],
        "cache_path": cache_path,
    }
    report["summary"].update({
        "pokeapi_evolution_chain_count": chain_count,
        "pokeapi_pokemon_species_count": species_count,
        "pokeapi_direct_species_edges": len(official_edges),
        "pokeapi_direct_species_edges_compared": len(comparable_official_edges),
        "ignored_pokeapi_edges": len(ignored_present),
        "expected_direct_species_edges_from_counts": expected_edges_from_counts,
        "missing_vs_pokeapi": len(missing),
        "extra_vs_pokeapi": len(extra),
    })
    report["ignored_pokeapi_edges"] = [display_edge(e) for e in ignored_present]
    report["missing_vs_pokeapi"] = [display_edge(e) for e in missing]
    report["extra_vs_pokeapi"] = [display_edge(e) for e in extra]
    return report


def write_missing_template(path: str, missing_edges: Iterable[str]) -> None:
    template = []
    for edge in missing_edges:
        if " -> " not in edge:
            continue
        src, dst = edge.split(" -> ", 1)
        template.append({
            "from": src,
            "to": dst,
            "trigger": "TODO",
            "item": None,
            "min_level": None,
            "notes": "Generated from PokéAPI missing_vs_pokeapi; verify method before merging.",
        })
    save_json(path, template)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit app evolution data.")
    parser.add_argument("--evolutions", default=DEFAULT_EVOLUTIONS)
    parser.add_argument("--cache", default=DEFAULT_CACHE)
    parser.add_argument("--online", action="store_true", help="Compare against live PokéAPI evolution-chain data.")
    parser.add_argument("--limit", type=int, default=None, help="Limit PokéAPI chain fetches for testing.")
    parser.add_argument("--pause", type=float, default=0.03, help="Seconds to pause between PokéAPI chain requests.")
    parser.add_argument("--cache-online", default=DEFAULT_ONLINE_CACHE, help="Cache full PokéAPI chain data here; use empty string to disable.")
    parser.add_argument("--refresh-online", action="store_true", help="Ignore cached PokéAPI data and fetch fresh online data.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--write-missing-template", default=None, help="Optional path for starter JSON entries for missing PokéAPI edges.")
    args = parser.parse_args()

    evolutions = load_json(args.evolutions)
    processed = load_json(args.cache)
    report = offline_audit(evolutions, processed)

    if args.online:
        report = merge_online_audit(
            report,
            evolutions,
            processed,
            limit=args.limit,
            pause=args.pause,
            cache_path=args.cache_online or None,
            refresh_online=args.refresh_online,
        )

    save_json(args.output, report)

    if args.write_missing_template and args.online:
        write_missing_template(args.write_missing_template, report.get("missing_vs_pokeapi", []))

    print(json.dumps(report["summary"], indent=2))
    print(f"Report written to {args.output}")
    if args.online:
        print("\nReminder: PokéAPI evolution_chain_count is family-tree count, not direct-evolution edge count.")
        print("Compare local_species_level_edges to pokeapi_direct_species_edges_compared when ignored_pokeapi_edges is nonzero.")

    failed = (
        report["summary"]["missing_from_references"]
        or report["summary"]["missing_to_references"]
        or report["summary"]["duplicate_exact_edges"]
        or report["summary"]["cycles"]
        or report["summary"]["required_recent_edges_missing"]
    )
    if args.online:
        failed = failed or report["summary"].get("missing_vs_pokeapi", 0)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
