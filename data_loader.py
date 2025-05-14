import re
import yaml
import json
import os
import requests
from pokeapi_client import fetch_form_metadata, fetch_evolution_chain, flatten_chain
from config import POKEAPI_BASE_URL

# Allowed variant suffixes
SUFFIXES = ['alola','alolan','galar','galarian','hisui','hisuian','paldea','paldean']
suffix_re = re.compile(r'^(.+)-(' + '|'.join(SUFFIXES) + r')$')

ROOT_DIR = os.path.dirname(__file__)
CACHE_PATH = os.path.join(ROOT_DIR, 'pokemon_cache.json')
OVERRIDES_PATH = os.path.join(ROOT_DIR, 'overrides.yml')
OUTPUT_DIR = os.path.join(ROOT_DIR, 'data')
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 0. Load cache
raw = json.load(open(CACHE_PATH))
if isinstance(raw, dict) and 'results' in raw:
    cache_entries = raw['results']
elif isinstance(raw, dict) and all(isinstance(v, str) for v in raw.values()):
    cache_entries = [{'name': k, 'url': v} for k, v in raw.items()]
elif isinstance(raw, list):
    cache_entries = raw
else:
    raise ValueError("Invalid pokemon_cache.json format")

# 1. Build forms.json
print("Building forms list...")
forms = []
form_keys = set()
for entry in cache_entries:
    key = entry['name']
    # Determine base species: only split known variant suffixes
    m = suffix_re.match(key)
    species = m.group(1) if m else key
    # Skip forms with hyphens not in SUFFIXES
    if '-' in key and not m:
        species = key  # treat entire key as species
    pid = int(str(entry['url']).rstrip('/').split('/')[-1])
    meta = fetch_form_metadata(key)
    forms.append({
        'key': key,
        'species': species,
        'form_name': meta['form_name'],
        'sprite_url': meta['sprite_url'],
        'pokeapi_id': pid
    })
    form_keys.add(key)
forms_path = os.path.join(OUTPUT_DIR, 'forms.json')
with open(forms_path, 'w') as f:
    json.dump(forms, f, indent=2)
print(f"Wrote {len(forms)} forms to {forms_path}")

# 2. Build evolutions.json
print("Building evolution chains...")
all_edges = []
species_set = {f['species'] for f in forms}
for species in species_set:
    try:
        resp = requests.get(f"{POKEAPI_BASE_URL}/pokemon-species/{species}", timeout=10)
        resp.raise_for_status()
        sp_data = resp.json()
    except Exception:
        print(f"Skipping species {species}: fetch error.")
        continue
    chain_url = sp_data.get('evolution_chain', {}).get('url')
    if not chain_url:
        continue
    chain_id = int(chain_url.rstrip('/').split('/')[-1])
    base_edges = flatten_chain(fetch_evolution_chain(chain_id).chain)
    all_edges.extend(base_edges)

# 3. Apply overrides for variant forms
overrides = yaml.safe_load(open(OVERRIDES_PATH)) or {}
for form_key, methods in overrides.items():
    if form_key not in form_keys:
        continue
    for m in methods:
        edge = {'from': form_key}
        edge['to'] = m.get('to') or m.get('evolves_to')
        for field in ['trigger','min_level','item','min_happiness','min_beauty','min_affection','time_of_day','location','held_item','known_move','known_move_type','party_species','party_type','relative_physical_stats','trade_species']:
            edge[field] = m.get(field)
        all_edges.append(edge)

# 4. Deduplicate edges
print("Deduplicating edges...")
seen = set()
final_edges = []
for e in all_edges:
    key_tuple = (
        e.get('from'), e.get('to'), e.get('trigger'), e.get('item'),
        e.get('min_level'), e.get('min_happiness'), e.get('min_beauty'), e.get('min_affection')
    )
    if key_tuple in seen:
        continue
    seen.add(key_tuple)
    # Ensure all keys exist
    for k in ['trigger','min_level','item','min_happiness','min_beauty','min_affection','time_of_day','location','held_item','known_move','known_move_type','party_species','party_type','relative_physical_stats','trade_species']:
        e.setdefault(k, None)
    final_edges.append(e)

evos_path = os.path.join(OUTPUT_DIR, 'evolutions.json')
with open(evos_path, 'w') as f:
    json.dump(final_edges, f, indent=2)
print(f"Wrote {len(final_edges)} evolution edges to {evos_path}")
