import re
import yaml
import json
import os, sys
import requests
from pokeapi_client import fetch_form_metadata, fetch_evolution_chain, flatten_chain
from config import POKEAPI_BASE_URL
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/114.0.0.0 Safari/537.36"
}

# Allowed variant suffixes
SUFFIXES = ['alola','alolan','galar','galarian','hisui','hisuian','paldea','paldean']
suffix_re = re.compile(r'^(.+)-(' + '|'.join(SUFFIXES) + r')$')

SCRIPT_DIR   = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir))
CACHE_PATH = os.path.join(PROJECT_ROOT, 'pokemon_cache.json')
DATA_DIR       = os.path.join(PROJECT_ROOT, 'data')
OVERRIDES_PATH = os.path.join(DATA_DIR, 'overrides.yml')
OUTPUT_DIR     = DATA_DIR
os.makedirs(OUTPUT_DIR, exist_ok=True)

def fetch_pokemondb_evolutions(species):
    """
    Scrape https://pokemondb.net/evolution/{species}
    and return a list of {"from","to","trigger","min_level","item","note"} dicts.
    """
    url = f"https://pokemondb.net/evolution/{species}"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    chains = []
    for evo_list in soup.select("h2 ~ .infocard-list-evo"):
        items = evo_list.find_all("li")
        for i, li in enumerate(items[:-1]):
            frm = li.select_one("a.ent-name").text.strip().lower().replace(" ", "-")
            to  = items[i+1].select_one("a.ent-name").text.strip().lower().replace(" ", "-")
            trigger_node = li.find_next_sibling(["small","em"])
            note = trigger_node.text.strip() if trigger_node else None

            level = None
            item  = None
            m_lvl = re.search(r"level\s*(\d+)", note or "", re.I)
            m_it  = re.search(r"(Ice|Moon|Thunder|Fire|Leaf) Stone", note or "", re.I)
            if m_lvl:
                level = int(m_lvl.group(1))
            if m_it:
                item = m_it.group(0).lower().replace(" ", "-")

            chains.append({
                "from":      frm,
                "to":        to,
                "trigger":   "level-up"    if level else
                             "use-item"    if item  else
                             "other",
                "min_level": level,
                "item":      item,
                "note":      note
            })
    return chains

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
    m = suffix_re.match(key)
    species = m.group(1) if m else key
    if '-' in key and not m:
        species = key
    pid = int(str(entry['url']).rstrip('/').split('/')[-1])
    meta = fetch_form_metadata(key)

    # Skip pure cosmetic variants (size/gender)
    form_name = (meta.get('form_name') or '').strip()
    fn_lower = form_name.lower()
    if fn_lower.endswith(" size") or fn_lower in ("male", "female"):
        continue

    forms.append({
        'key': key,
        'species': species,
        'form_name': form_name,
        'sprite_url': meta['sprite_url'],
        'pokeapi_id': pid
    })
    form_keys.add(key)

# 1a. Add synthetic base forms for species missing a direct key
species_groups = {}
for f in forms:
    species_groups.setdefault(f['species'], []).append(f)
new_bases = []
for sp, group in species_groups.items():
    if not any(f['key'] == sp for f in group):
        # choose default variant (no form_name) or first
        default = next((f for f in group if not f['form_name']), group[0])
        new_bases.append({
            'key':       sp,
            'species':   sp,
            'form_name': '',
            'sprite_url': default['sprite_url'],
            'pokeapi_id': default['pokeapi_id']
        })
forms.extend(new_bases)

with open(os.path.join(OUTPUT_DIR, 'forms.json'), 'w') as f:
    json.dump(forms, f, indent=2)
print(f"Wrote {len(forms)} forms to data/forms.json")

#2. Build evolutions.json by fetching *every* form’s species JSON
print("Building evolution chains from PokeAPI JSON per form…")
all_edges = []
# only call the API for your true base forms (no hyphens)
base_keys = sorted(k for k in {f['key'] for f in forms} if '-' not in k)

for key in base_keys:
    url = f"{POKEAPI_BASE_URL}/pokemon-species/{key}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        sp = resp.json()
    except Exception as ex:
        # you can even silence these if you like:
        #   continue
        print(f"  [skipping API fetch for {key}]: {ex}")
        continue

    chain_url = sp.get("evolution_chain", {}).get("url")
    if not chain_url:
        continue
    cid = int(chain_url.rstrip("/").split("/")[-1])

    # flatten the chain and keep only edges for forms you actually have
    for e in flatten_chain(fetch_evolution_chain(cid).chain):
        if e["from"] in form_keys and e["to"] in form_keys:
            all_edges.append(e)

# 3. Apply overrides for unique methods
overrides = yaml.safe_load(open(OVERRIDES_PATH)) or {}

# 3a. Drop API edges that exactly match any override entry
def edge_matches_override(edge, override):
    # override has keys: 'to', plus any of trigger, min_level, item, ...
    if edge['to'] != override['to']:
        return False
    # for every field in the override, the edge must match
    for field, val in override.items():
        if field == 'to':  # we've already matched this
            continue
        # Normalize None vs missing
        if edge.get(field) != val:
            return False
    return True

cleaned = []
for e in all_edges:
    methods = overrides.get(e['from'], [])
    # if **any** override method fully matches this edge, drop it
    if any(edge_matches_override(e, m) for m in methods):
        continue
    cleaned.append(e)
all_edges = cleaned

# 3b. Inject manual overrides
for from_key, methods in overrides.items():
    for m in methods:
        edge = {'from': from_key, 'to': m['to']}
        for field in ['trigger','min_level','item','min_happiness','min_beauty',
                      'gender','time_of_day','location','held_item','known_move',
                      'known_move_type','party_species','party_type',
                      'relative_physical_stats','trade_species','note']:
            edge[field] = m.get(field)
        all_edges.append(edge)

print("Deduplicating edges with priority…")

# assign a priority to each trigger type
priority = {
    'level-up':   4,
    'use-item':   3,
    'trade':      2,
    'other':      1
}

# build a map from (from, to) → best edge so far
best = {}
for e in all_edges:
    key = (e['from'], e['to'])
    score = priority.get(e.get('trigger'), 0)
    # if we haven't seen this pair yet, or this edge is higher-priority, replace
    if key not in best or score > priority.get(best[key]['trigger'], 0):
        best[key] = e

# now collect, fill defaults, and write out
final_edges = []
fields = [
    'from','to','trigger','item','min_level',
    'time_of_day','location','held_item',
    'known_move','known_move_type',
    'min_happiness','min_beauty',
    'relative_physical_stats','party_species','party_type',
    'trade_species','gender'
]
for e in best.values():
    for f in fields + ['note']:
        e.setdefault(f, None)
    final_edges.append(e)

with open(os.path.join(OUTPUT_DIR, 'evolutions.json'), 'w') as f:
    json.dump(final_edges, f, indent=2)
print(f"Wrote {len(final_edges)} evolution edges to data/evolutions.json")
