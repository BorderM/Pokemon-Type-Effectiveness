#!/usr/bin/env python3
import re
import yaml
import json
import os
import requests
from collections import defaultdict
from pokeapi_client import fetch_evolution_chain, flatten_chain
from config import POKEAPI_BASE_URL

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG & PATHS
# ─────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR     = os.path.dirname(__file__)
PROJECT_ROOT   = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir))
PROCESSED_CACHE_PATH = os.path.join(PROJECT_ROOT, 'processed_pokemon_cache.json')
DATA_DIR       = os.path.join(PROJECT_ROOT, 'data')
OVERRIDES_PATH = os.path.join(DATA_DIR, 'overrides.yml')
OUTPUT_EVO     = os.path.join(DATA_DIR, 'evolutions.json')

os.makedirs(DATA_DIR, exist_ok=True)

# which suffixes we treat as “regional variants”
SUFFIXES    = ['alola','alolan','galar','galarian','hisui','hisuian','paldea','paldean']
_SUFFIX_RE  = re.compile(r'^(.+)-(' + '|'.join(SUFFIXES) + r')$')

def get_base(name: str) -> str:
    """ Strip off any of our known regional suffixes """
    m = _SUFFIX_RE.match(name)
    return m.group(1) if m else name

# ─────────────────────────────────────────────────────────────────────────────
# 0) Load your processed cache (contains *every* form already)
# ─────────────────────────────────────────────────────────────────────────────
processed = json.load(open(PROCESSED_CACHE_PATH, encoding='utf-8'))

# group every form name by its “base species”
species_to_forms = defaultdict(list)
all_forms = set()
for entry in processed:
    form = entry['form']             # e.g. "aegislash-shield"
    species = get_base(form)         # e.g. "aegislash"
    species_to_forms[species].append(form)
    all_forms.add(form)

# ─────────────────────────────────────────────────────────────────────────────
# 1) For each species, fetch its evolution_chain_id
# ─────────────────────────────────────────────────────────────────────────────
species_meta = {}
for species, forms in species_to_forms.items():
    try:
        spj = requests.get(
            f"{POKEAPI_BASE_URL}/pokemon-species/{species}"
        , timeout=10).json()
        chain_url = spj.get('evolution_chain',{}).get('url')
        cid = int(chain_url.rstrip('/').split('/')[-1]) if chain_url else None
    except Exception:
        cid = None
    species_meta[species] = cid

# ─────────────────────────────────────────────────────────────────────────────
# 2a) Flatten every *species*-level chain into edges
# ─────────────────────────────────────────────────────────────────────────────
species_edges = []
chain_ids = {cid for cid in species_meta.values() if cid}
for cid in sorted(chain_ids):
    try:
        chain = fetch_evolution_chain(cid).chain
    except Exception:
        continue
    for e in flatten_chain(chain):
        # only keep it if *both* endpoints are base-species we know
        if e['from'] in species_to_forms and e['to'] in species_to_forms:
            species_edges.append(e)

print(f"↳ Collected {len(species_edges)} species‐level edges")

# ─────────────────────────────────────────────────────────────────────────────
# 2b) Expand those to *form*-level (propagate region suffixes)
# ─────────────────────────────────────────────────────────────────────────────
REGIONAL = set(SUFFIXES)
form_edges = []
for e in species_edges:
    sp_from, sp_to = e['from'], e['to']

    # default→default
    form_edges.append({ **e })  

    # and for each regional form of `sp_from`, if same suffix exists on sp_to
    for frm in species_to_forms[sp_from]:
        if '-' not in frm: 
            continue
        suffix = frm.split('-',1)[1]
        if suffix not in REGIONAL:
            continue
        tof = f"{sp_to}-{suffix}"
        if tof in species_to_forms[sp_to]:
            ne = { **e, 'from': frm, 'to': tof }
            form_edges.append(ne)

print(f"↳ Expanded to {len(form_edges)} form‐level edges")

# ─────────────────────────────────────────────────────────────────────────────
# 3) Load & apply your manual overrides.yml
# ─────────────────────────────────────────────────────────────────────────────
overrides_raw = yaml.safe_load(open(OVERRIDES_PATH)) or {}
# normalize keys to lower-case
overrides = {
    frm.lower(): [
        { k:(v.lower() if isinstance(v,str) else v) for k,v in m.items() }
        for m in methods
    ]
    for frm, methods in overrides_raw.items()
}

# 3a) drop any API edge that *exactly* matches an override
def matches_override(edge, ov):
    if edge['to'] != ov['to']:
        return False
    for fld,val in ov.items():
        if fld == 'to': continue
        if edge.get(fld) != val:
            return False
    return True

cleaned = []
for e in form_edges:
    methods = overrides.get(e['from'], [])
    if any(matches_override(e, m) for m in methods):
        continue
    cleaned.append(e)
form_edges = cleaned

# 3b) inject *all* overrides
for frm, methods in overrides.items():
    for m in methods:
        edge = {'from': frm, 'to': m['to']}
        for fld in ['trigger','min_level','item','min_happiness','min_beauty',
                    'gender','time_of_day','location','held_item','known_move',
                    'known_move_type','party_species','party_type',
                    'relative_physical_stats','trade_species','note']:
            edge[fld] = m.get(fld)
        form_edges.append(edge)

# ─────────────────────────────────────────────────────────────────────────────
# 4) Deduplicate by trigger‐priority & write out
# ─────────────────────────────────────────────────────────────────────────────
priority = {
    'level-up-day':   5,
    'level-up-night': 5,
    'level-up-dusk':  5,
    'level-up':       4,
    'use-item':       3,
    'trade':          2,
    'other':          1
}
best = {}
for e in form_edges:
    key   = (e['from'], e['to'])
    score = priority.get(e.get('trigger','other'), 0)
    prev  = best.get(key)
    if not prev or score > priority.get(prev['trigger'],0):
        best[key] = e

final = []
fields = ['from','to','trigger','item','min_level','time_of_day','location',
          'held_item','known_move','known_move_type','min_happiness',
          'min_beauty','relative_physical_stats','party_species','party_type',
          'trade_species','gender','note']
for e in best.values():
    for f in fields:
        e.setdefault(f, None)
    final.append(e)

with open(OUTPUT_EVO, 'w', encoding='utf-8') as fp:
    json.dump(final, fp, indent=2)

print(f"✔ Wrote {len(final)} edges → {OUTPUT_EVO}")
