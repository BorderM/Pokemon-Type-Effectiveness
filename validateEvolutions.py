import json

# Paths to your cache and data files
PROCESSED_PATH = './static/processed_pokemon_cache.json'
EVOLUTIONS_PATH = './data/evolutions.json'

with open(PROCESSED_PATH, encoding='utf-8') as f:
    processed = json.load(f)

with open(EVOLUTIONS_PATH, encoding='utf-8') as f:
    evolutions = json.load(f)

valid_keys = {entry['form'].lower() for entry in processed}
errors = []

# Check each evolution entry
for evo in evolutions:
    frm = evo['from'].lower()
    to  = evo['to'].lower()

    if frm not in valid_keys:
        errors.append(f"[MISSING FROM] {frm} not in processed_pokemon_cache")
    if to not in valid_keys:
        errors.append(f"[MISSING TO]   {to} not in processed_pokemon_cache")

    if not evo.get('trigger'):
        errors.append(f"[NO TRIGGER]   {frm} → {to} has no trigger set")

# Summary
print(f"✅ Checked {len(evolutions)} evolution entries.")
if errors:
    print(f"❌ Found {len(errors)} issues:")
    for e in errors:
        print(" •", e)
else:
    print("🎉 All evolution entries look valid.")