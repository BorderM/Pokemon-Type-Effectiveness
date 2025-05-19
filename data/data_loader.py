#!/usr/bin/env python3
import re, yaml, json, os, sys, requests
from collections import defaultdict
from pokeapi_client import fetch_form_metadata, fetch_evolution_chain, flatten_chain
from config import POKEAPI_BASE_URL

COLLAPSE_MAP = json.load(open(os.path.join(os.path.dirname)))

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
SUFFIXES  = ['alola','alolan','galar','galarian','hisui','hisuian','paldea','paldean']
_SUFFIX_RE = re.compile(r'^(.+)-(' + '|'.join(SUFFIXES) + r')$')

def get_base(name: str) -> str:
    """
    Strip off our known regional suffixes (alola, galar, etc.).
    Leave everything else—e.g. ho-oh, mr-mime—alone.
    """
    m = _SUFFIX_RE.match(name)
    return m.group(1) if m else name

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
# 1) Build forms.json (with species_id + evolution_chain_id)
# --------------------------------------------------------------------------------------------------
print("⟳ Building forms list…")
forms = []

for entry in cache_entries:
    key     = entry['name']
    species = get_base(key)

    # 1. fetch the /pokemon/{key} to get its true species URL
    try:
        p_resp = requests.get(f"{POKEAPI_BASE_URL}/pokemon/{key}", timeout=10)
        p_resp.raise_for_status()
        pj = p_resp.json()
        poke_id = pj['id']

        # 2. fetch that species to get species_id and chain
        sp_url = pj['species']['url']
        sp_resp = requests.get(sp_url, timeout=10)
        sp_resp.raise_for_status()
        spj = sp_resp.json()
        species_id = spj['id']
        chain_url = spj.get('evolution_chain', {}).get('url')
        evo_chain_id = (
            int(chain_url.rstrip('/').split('/')[-1])
            if chain_url else None
        )
    except Exception as ex:
        print(f"  [warn] fetching /pokemon or /species for {key} → {ex}")
        poke_id = None
        species_id = None
        evo_chain_id = None

    meta      = fetch_form_metadata(key)
    form_name = (meta.get('form_name') or '').strip().lower()
    # skip pure cosmetic forms
    if form_name.endswith(" size") or form_name in ("male","female"):
        continue

    forms.append({
        'key':                key,
        'species':            species,
        'form_name':          meta.get('form_name',''),
        'sprite_url':         f"/static/sprites/{key}.png",
        'pokeapi_id':         poke_id,
        'species_id':         species_id,
        'evolution_chain_id': evo_chain_id
    })

# 1a) Ensure every species-group has a "base" entry
species_groups = defaultdict(list)
for f in forms:
    species_groups[f['species']].append(f)

existing_keys = {f['key'] for f in forms}
for sp, group in species_groups.items():
    if sp not in existing_keys:
        default = next((f for f in group if not f['form_name']), group[0])
        forms.append({
            'key':                sp,
            'species':            sp,
            'form_name':          '',
            'sprite_url':         default['sprite_url'],
            'pokeapi_id':         default['pokeapi_id'],
            'species_id':         default['species_id'],
            'evolution_chain_id': default['evolution_chain_id']
        })
        existing_keys.add(sp)

# 1b) Cover any raw species skipped entirely (pumpkaboo, basculin, etc.)
raw_species = {get_base(e['name']) for e in cache_entries}
for sp in raw_species - existing_keys:
    entry = next(e for e in cache_entries if get_base(e['name']) == sp)
    pid   = int(entry['url'].rstrip('/').split('/')[-1])
    forms.append({
        'key':                sp,
        'species':            sp,
        'form_name':          '',
        'sprite_url':         f"/static/sprites/{sp}.png",
        'pokeapi_id':         pid,
        'species_id':         pid,
        'evolution_chain_id': None
    })
    existing_keys.add(sp)

form_keys = set(existing_keys)

with open(OUTPUT_FORMS, 'w', encoding='utf-8') as fp:
    json.dump(forms, fp, indent=2)
print(f"✔ Wrote {len(forms)} forms → {OUTPUT_FORMS}")


# --------------------------------------------------------------------------------------------------
# 2a) Pull every unique species‐level evolution chain
# --------------------------------------------------------------------------------------------------
print("⟳ Building evolution chains from PokeAPI…")
species_edges = []
chain_ids = {f['evolution_chain_id'] for f in forms if f.get('evolution_chain_id')}
for cid in sorted(chain_ids):
    try:
        chain = fetch_evolution_chain(cid).chain
    except Exception as ex:
        print(f"  [skip chain {cid}]: error → {ex}")
        continue
    for edge in flatten_chain(chain):
        # only species‐level names here
        if edge['from'] in form_keys and edge['to'] in form_keys:
            species_edges.append(edge)

print(f"↳ Collected {len(species_edges)} species‐edges from {len(chain_ids)} chains")


# --------------------------------------------------------------------------------------------------
# 2b) Expand to form‐level: default→default + regional→regional
# --------------------------------------------------------------------------------------------------
print("⟳ Expanding species-edges to forms…")
REGIONAL = {'alola','galar','hisui'}
forms_by_species = defaultdict(list)
for f in forms:
    forms_by_species[f['species']].append(f['key'])

all_edges = []
for e in species_edges:
    sp_from, sp_to = e['from'], e['to']

    # default→default
    all_edges.append(e.copy())

    # and propagate any regional suffix present
    for frm in forms_by_species[sp_from]:
        if frm == sp_from or '-' not in frm:
            continue
        suffix = frm.split('-',1)[1]
        if suffix not in REGIONAL:
            continue
        tof = f"{sp_to}-{suffix}"
        if tof in forms_by_species[sp_to]:
            ne = e.copy()
            ne['from'] = frm
            ne['to']   = tof
            all_edges.append(ne)

print(f"↳ Expanded to {len(all_edges)} form‐edges")


# --------------------------------------------------------------------------------------------------
# 3) Apply overrides.yml
# --------------------------------------------------------------------------------------------------
print("⟳ Applying overrides…")
raw_ov = yaml.safe_load(open(OVERRIDES_PATH)) or {}
overrides = {
    frm.lower(): [
        {k:(v.lower() if isinstance(v,str) else v) for k,v in m.items()}
        for m in methods
    ]
    for frm, methods in raw_ov.items()
}

for o in overrides:
    if o not in form_keys:
        print(f"  [⚠️] override for “{o}” but no such form-key found")

# drop fully‐overridden edges
filtered = []
for e in all_edges:
    methods = overrides.get(e['from'], [])
    if any(
        e['to']==m['to'] and all(e.get(f)==m.get(f) for f in m if f!='to')
        for m in methods
    ):
        continue
    filtered.append(e)
all_edges = filtered

# inject *all* overrides
for frm, methods in overrides.items():
    for m in methods:
        edge = {'from':frm,'to':m['to']}
        for fld in [
            'trigger','min_level','item','min_happiness','min_beauty','gender',
            'time_of_day','location','held_item','known_move','known_move_type',
            'party_species','party_type','relative_physical_stats','trade_species','note'
        ]:
            edge[fld] = m.get(fld)
        all_edges.append(edge)


# --------------------------------------------------------------------------------------------------
# 4) Deduplicate by trigger priority & write out
# --------------------------------------------------------------------------------------------------
print("⟳ Deduplicating edges…")
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
for e in all_edges:
    k  = (e['from'], e['to'])
    sc = priority.get(e.get('trigger'), 0)
    prev = best.get(k)
    if not prev or sc > priority.get(prev['trigger'], 0):
        best[k] = e

fields = [
    'from','to','trigger','item','min_level','time_of_day','location','held_item',
    'known_move','known_move_type','min_happiness','min_beauty',
    'relative_physical_stats','party_species','party_type','trade_species','gender'
]
final = []
for e in best.values():
    for f in fields + ['note']:
        e.setdefault(f, None)
    final.append(e)

with open(OUTPUT_EVO, 'w', encoding='utf-8') as fp:
    json.dump(final, fp, indent=2)
print(f"✔ Wrote {len(final)} edges → {OUTPUT_EVO}")
