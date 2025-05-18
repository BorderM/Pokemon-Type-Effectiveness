#!/usr/bin/env python3
import re
import yaml
import json
import os
import sys
import requests
from pokeapi_client import fetch_form_metadata, fetch_evolution_chain, flatten_chain
from config import POKEAPI_BASE_URL

# --------------------------------------------------------------------------------------------------
# CONFIG & PATHS
# --------------------------------------------------------------------------------------------------
SCRIPT_DIR     = os.path.dirname(__file__)
PROJECT_ROOT   = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir))
CACHE_PATH     = os.path.join(PROJECT_ROOT, 'pokemon_cache.json')
DATA_DIR       = os.path.join(PROJECT_ROOT, 'data')
OVERRIDES_PATH = os.path.join(DATA_DIR, 'overrides.yml')
OUTPUT_FORMS   = os.path.join(DATA_DIR, 'forms.json')
OUTPUT_EVO     = os.path.join(DATA_DIR, 'evolutions.json')

os.makedirs(DATA_DIR, exist_ok=True)

# suffixes we consider “regional variants”
SUFFIXES = ['alola','alolan','galar','galarian','hisui','hisuian','paldea','paldean']
_SUFFIX_RE = re.compile(r'^(.+)-(' + '|'.join(SUFFIXES) + r')$')


# --------------------------------------------------------------------------------------------------
# 0) Load your master cache
# --------------------------------------------------------------------------------------------------
raw = json.load(open(CACHE_PATH, encoding='utf-8'))
if isinstance(raw, dict) and 'results' in raw:
    cache_entries = raw['results']
elif isinstance(raw, dict) and all(isinstance(v, str) for v in raw.values()):
    cache_entries = [{'name': k, 'url': v} for k, v in raw.items()]
elif isinstance(raw, list):
    cache_entries = raw
else:
    raise ValueError("Invalid pokemon_cache.json format")


# --------------------------------------------------------------------------------------------------
# 1) Build forms.json
# --------------------------------------------------------------------------------------------------
print("⟳ Building forms list…")
forms = []
form_keys = set()

for entry in cache_entries:
    key = entry['name']
    m = _SUFFIX_RE.match(key)
    # species = base before region suffix, or whole key if it’s a true form
    species = m.group(1) if m else key
    # pokeapi numeric ID
    pid = int(entry['url'].rstrip('/').split('/')[-1])

    meta = fetch_form_metadata(key)
    form_name = (meta.get('form_name') or '').strip().lower()
    # skip purely cosmetic forms
    if form_name.endswith(" size") or form_name in ("male","female"):
        continue

    forms.append({
        'key':        key,
        'species':    species,
        'form_name':  meta.get('form_name',''),
        'sprite_url': f"/static/sprites/{key}.png",
        'pokeapi_id': pid
    })
    form_keys.add(key)

# 1a) ensure every species has a “base” entry
species_groups = {}
for f in forms:
    species_groups.setdefault(f['species'], []).append(f)

for sp, group in species_groups.items():
    if sp not in {f['key'] for f in group}:
        default = next((f for f in group if not f['form_name']), group[0])
        forms.append({
            'key':        sp,
            'species':    sp,
            'form_name':  '',
            'sprite_url': default['sprite_url'],
            'pokeapi_id': default['pokeapi_id']
        })
        form_keys.add(sp)

with open(OUTPUT_FORMS, 'w', encoding='utf-8') as fp:
    json.dump(forms, fp, indent=2)
print(f"✔ Wrote {len(forms)} forms → {OUTPUT_FORMS}")


# --------------------------------------------------------------------------------------------------
# 2) Pull every base‐form chain from PokeAPI
# --------------------------------------------------------------------------------------------------
print("⟳ Building evolution chains from PokeAPI…")
all_forms = set(form_keys)
base_keys = sorted(k for k in all_forms if '-' not in k)

all_edges = []

for base in base_keys:
    species_url = f"{POKEAPI_BASE_URL}/pokemon-species/{base}"
    try:
        r = requests.get(species_url, timeout=10)
        r.raise_for_status()
        sp = r.json()
    except Exception as ex:
        print(f"  [skip base {base}]: could not fetch species → {ex}")
        continue

    chain_url = sp.get('evolution_chain', {}).get('url')
    if not chain_url:
        continue
    cid = int(chain_url.rstrip('/').split('/')[-1])

    try:
        chain = fetch_evolution_chain(cid).chain
    except Exception as ex:
        print(f"  [skip chain {base}]: error fetching chain → {ex}")
        continue

    for edge in flatten_chain(chain):
        # only keep edges where both ends are in your forms.json
        if edge['from'] in all_forms and edge['to'] in all_forms:
            all_edges.append(edge)

print(f"↳ Collected {len(all_edges)} raw edges from API")


# --------------------------------------------------------------------------------------------------
# 3) Apply overrides.yml
# --------------------------------------------------------------------------------------------------
print("⟳ Applying overrides…")
overrides = yaml.safe_load(open(OVERRIDES_PATH)) or {}

# warn about any override key not actually present in forms.json
for override_key in overrides:
    if override_key not in all_forms:
        print(f"  [⚠️] override for “{override_key}” but no such form-key found")

def edge_matches_override(edge, ov):
    if edge['to'] != ov['to']:
        return False
    for fld, val in ov.items():
        if fld == 'to': continue
        # treat missing vs null the same
        if edge.get(fld) != val:
            return False
    return True

# 3a) drop any API‐provided edges that exactly match an override
filtered = []
for e in all_edges:
    methods = overrides.get(e['from'], [])
    if any(edge_matches_override(e, m) for m in methods):
        continue
    filtered.append(e)
all_edges = filtered

# 3b) inject *all* overrides, even if they didn’t exist in the API data
for frm, methods in overrides.items():
    for m in methods:
        edge = {'from':frm, 'to':m['to']}
        # fill in every possible field (defaulting to None)
        for fld in [
            'trigger','min_level','item','min_happiness','min_beauty',
            'gender','time_of_day','location','held_item','known_move',
            'known_move_type','party_species','party_type',
            'relative_physical_stats','trade_species','note'
        ]:
            edge[fld] = m.get(fld)
        all_edges.append(edge)


# --------------------------------------------------------------------------------------------------
# 4) Dedupe by trigger‐priority & emit final JSON
# --------------------------------------------------------------------------------------------------
print("⟳ Deduplicating edges…")
priority = {
    'level-up': 4,
    'use-item': 3,
    'trade':    2,
    'other':    1
}
best = {}
for e in all_edges:
    key = (e['from'], e['to'])
    score = priority.get(e.get('trigger'), 0)
    # choose the edge with highest priority
    prev = best.get(key)
    if not prev or score > priority.get(prev['trigger'], 0):
        best[key] = e

final = []
fields = [
    'from','to','trigger','item','min_level','time_of_day','location','held_item',
    'known_move','known_move_type','min_happiness','min_beauty',
    'relative_physical_stats','party_species','party_type','trade_species','gender'
]
for e in best.values():
    # ensure every field + note is at least None
    for f in fields + ['note']:
        e.setdefault(f, None)
    final.append(e)

with open(OUTPUT_EVO, 'w', encoding='utf-8') as fp:
    json.dump(final, fp, indent=2)
print(f"✔ Wrote {len(final)} edges → {OUTPUT_EVO}")
