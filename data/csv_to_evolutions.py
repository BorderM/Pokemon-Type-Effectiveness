import pandas as pd
import json
import os

# 1. load CSVs
base = os.path.dirname(__file__)
species_df     = pd.read_csv(os.path.join(base, "pokemon_species.csv"))
evo_df         = pd.read_csv(os.path.join(base, "pokemon_evolution.csv"))
trigger_df     = pd.read_csv(os.path.join(base, "evolution_triggers.csv"))
items_df       = pd.read_csv(os.path.join(base, "items.csv"))
moves_df       = pd.read_csv(os.path.join(base, "moves.csv"))
types_df       = pd.read_csv(os.path.join(base, "types.csv"))
locs_df        = pd.read_csv(os.path.join(base, "locations.csv"))

with open(os.path.join(base, "forms.json")) as f:
    forms = json.load(f)
form_keys = {entry["key"] for entry in forms}

# 2. build lookup maps
# species_id → species_name (e.g. 28 → 'pikachu')
sp_map    = species_df.set_index("id")["identifier"].to_dict()
# trigger_id → trigger_name ('level-up', 'use-item', etc.)
tr_map    = trigger_df.set_index("id")["identifier"].to_dict()
# item_id → item_name ('ice-stone', etc.)
item_map  = items_df.set_index("id")["identifier"].to_dict()
# move_id → move_name
move_map  = moves_df.set_index("id")["identifier"].to_dict()
# type_id → type_name
type_map  = types_df.set_index("id")["identifier"].to_dict()
# location_id → location_name
loc_map   = locs_df.set_index("id")["identifier"].to_dict()
# pokemon_forms: find which forms exist so later you can filter to just the keys you care about
with open(os.path.join(base, "forms.json")) as f:
    forms = json.load(f)
form_keys = { entry["key"] for entry in forms }

# 3. assemble each edge
edges = []
for _, row in evo_df.iterrows():
    frm_sp = sp_map[row["id"]]
    to_sp  = sp_map[row["evolved_species_id"]]
    tod = row["time_of_day"]

    e = {
        "from": frm_sp,
        "to":   to_sp,
        "trigger": tr_map.get(row["evolution_trigger_id"]),
        "min_level": int(row["minimum_level"]) if not pd.isna(row["minimum_level"]) else None,
        "item":      item_map.get(row["trigger_item_id"]),
        "time_of_day": tod if pd.notna(tod) else None,
        "location":  loc_map.get(row["location_id"]),
        "held_item": item_map.get(row["held_item_id"]),
        "known_move": move_map.get(row["known_move_id"]),
        "known_move_type": type_map.get(row["known_move_type_id"]),
        "min_happiness": int(row["minimum_happiness"]) if not pd.isna(row["minimum_happiness"]) else None,
        "min_beauty":    int(row["minimum_beauty"])    if not pd.isna(row["minimum_beauty"])    else None,
        "party_species": sp_map.get(row["party_species_id"]),
        "party_type":    type_map.get(row["party_type_id"]),
        "relative_physical_stats": (
            int(row["relative_physical_stats"])
            if not pd.isna(row["relative_physical_stats"]) else None
        ),
        "trade_species": sp_map.get(row["trade_species_id"]),
        "gender":        ("male" if row["gender_id"] == 1 else "female" if row["gender_id"] == 2 else None),
        "note":          None,
    }
    # only keep if you actually have that form key
    if e["from"] in form_keys and e["to"] in form_keys:
        edges.append(e)

edges = [e for e in edges if e["from"] in form_keys and e["to"] in form_keys]
         
# 4. optionally: filter to only those edges whose from/to appear in your forms.json keys
#    (so you don’t get “pichu → pikachu” if you haven’t included that form)
# form_keys = load your data/forms.json keys here...
# edges = [e for e in edges if e['from'] in form_keys and e['to'] in form_keys]

print("Sample Alolan forms:", [k for k in form_keys if "-alola" in k][:10])
print("Total form-keys:", len(form_keys))
print("Total edges after filter:", len(edges))

# 5. dump to JSON
out_path = os.path.join(base, "evolutions.json")
with open(out_path, "w") as f:
    json.dump(edges, f, indent=2)
print(f"Wrote {len(edges)} edges to {out_path}")