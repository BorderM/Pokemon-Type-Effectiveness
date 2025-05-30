import json
from collections import defaultdict

IGNORED_TOKENS = {"totem", "gmax", "busted", "disguised", "original"}
COLOR_WORDS = {"red", "orange", "yellow", "green", "blue", "indigo", "violet", "white", "black", "brown", "pink"}
REGIONAL_SUFFIXES = {"alola", "galar", "hisui", "paldea", "paldean"}

def normalize_name(name):
    tokens = name.lower().split('-')
    filtered = [t for t in tokens if t not in COLOR_WORDS and t not in IGNORED_TOKENS]
    return '-'.join(filtered)

def types_equal(t1, t2):
    return set(t1 or []) == set(t2 or [])

def generate_type_map(input_path, output_path):
    with open(input_path, "r") as f:
        data = json.load(f)

    species_forms = defaultdict(list)
    for entry in data:
        base = normalize_name(entry["species"])
        species_forms[base].append(entry)

    final_map = {}

    for base_name, forms in species_forms.items():
        # Cluster forms by type signature
        clusters = defaultdict(list)
        for form in forms:
            tkey = ','.join(sorted(form["types"]))
            clusters[tkey].append(form)

        for cluster_forms in clusters.values():
            # Find the primary representative (non-gmax preferred)
            rep_form = sorted(
                cluster_forms,
                key=lambda f: ('gmax' in f['name'], f['name'])  # prioritize non-gmax
            )[0]
            rep_name = rep_form["name"]

            for form in cluster_forms:
                name = form["name"]
                form_types = form["types"]
                region_tokens = name.lower().split("-")
                has_region = any(tok in REGIONAL_SUFFIXES for tok in region_tokens)

                is_representative = name == rep_name
                collapse_to = None if is_representative or has_region else rep_name
                preserve = is_representative or has_region

                final_map[name] = {
                    "base_name": base_name,
                    "collapse_display_name_to": collapse_to,
                    "distinct_types": is_representative,
                    "distinct_stats": None,
                    "force_preserve_name": preserve
                }

    with open(output_path, "w") as f:
        json.dump(final_map, f, indent=2)

    print(f"✅ Type map written to: {output_path}")
# Usage:
generate_type_map(
    input_path="processed_pokemon_cache.json",
    output_path="pokemon_reference_map_types.json"
)
