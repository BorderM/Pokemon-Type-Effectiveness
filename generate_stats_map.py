import json
from collections import defaultdict

REGIONAL_SUFFIXES = {"alola", "galar", "hisui", "paldea", "paldean"}
IGNORED_TOKENS = {"totem", "gmax", "busted", "disguised", "original"}
COLOR_WORDS = {
    "red", "orange", "yellow", "green", "blue", "indigo", "violet",
    "white", "black", "brown", "pink"
}

def normalize_name(name):
    tokens = name.lower().split('-')
    filtered = [t for t in tokens if t not in IGNORED_TOKENS and t not in COLOR_WORDS]
    return '-'.join(filtered)

def stats_equal(s1, s2):
    if not s1 or not s2:
        return False
    return all(s1.get(k) == s2.get(k) for k in s1)

def generate_stats_map(input_path, output_path):
    with open(input_path, 'r') as f:
        data = json.load(f)

    species_groups = defaultdict(list)
    for form in data:
        base = normalize_name(form["species"])
        species_groups[base].append(form)

    result = {}

    for species, forms in species_groups.items():
        # group by stat signature
        sig_to_forms = defaultdict(list)
        for form in forms:
            stats = form.get("stats")
            sig_key = json.dumps(stats or {})  # support null
            sig_to_forms[sig_key].append(form)

        for sig, form_group in sig_to_forms.items():
            if not sig or sig == "{}":
                # no stats — mark each as distinct
                for form in form_group:
                    name = form["name"]
                    result[name] = {
                        "base_name": normalize_name(form["species"]),
                        "collapse_display_name_to": None,
                        "distinct_types": None,
                        "distinct_stats": None,
                        "force_preserve_name": True
                    }
                continue

            # Pick the "canonical" name from the group
            canonical = sorted(form_group, key=lambda f: len(f["name"]))[0]["name"]

            for form in form_group:
                name = form["name"]
                base_name = normalize_name(form["species"])
                has_region = any(part in name.lower().split('-') for part in REGIONAL_SUFFIXES)

                result[name] = {
                    "base_name": base_name,
                    "collapse_display_name_to": None if name == canonical else canonical,
                    "distinct_types": None,
                    "distinct_stats": True,  # these are a distinct stat cluster
                    "force_preserve_name": has_region or name == canonical
                }

    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"✅ Stats map saved to {output_path}")


# Usage:
generate_stats_map(
    input_path="processed_pokemon_cache.json",
    output_path="pokemon_reference_map_stats.json"
)
