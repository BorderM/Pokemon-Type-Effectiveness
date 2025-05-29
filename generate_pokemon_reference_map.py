import json
from collections import defaultdict

def generate_reference_map(input_path, output_path):
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    species_groups = defaultdict(list)
    for entry in data:
        species_groups[entry["species"]].append(entry)

    def stats_equal(stats1, stats2):
        return all(stats1.get(k) == stats2.get(k) for k in stats1)

    def types_equal(types1, types2):
        return set(types1) == set(types2)

    reference_map = {}

    for species, forms in species_groups.items():
        for form in forms:
            name = form["name"]
            has_different_stats = False
            has_different_types = False

            for other in forms:
                if other["name"] == name:
                    continue
                if not stats_equal(form["stats"], other["stats"]):
                    has_different_stats = True
                if not types_equal(form["types"], other["types"]):
                    has_different_types = True

            all_same = not has_different_stats and not has_different_types
            display_collapse = name if all_same else None

            reference_map[name] = {
                "base_name": species,
                "collapse_display_name_to": display_collapse,
                "distinct_types": has_different_types,
                "distinct_stats": has_different_stats,
                "force_preserve_name": has_different_types or has_different_stats
            }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(reference_map, f, indent=2, ensure_ascii=False)

# Example usage
generate_reference_map("processed_pokemon_cache.json", "pokemon_reference_map.json")
