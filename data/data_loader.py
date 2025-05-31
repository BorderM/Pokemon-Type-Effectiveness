#!/usr/bin/env python3
import re
import json
import os
import requests
from collections import defaultdict
from pokeapi_client import fetch_evolution_chain, flatten_chain
from config import POKEAPI_BASE_URL

# ──────────────────────────────────────────────────────────────────
# CONFIG & PATHS
# ──────────────────────────────────────────────────────────────────
SCRIPT_DIR     = os.path.dirname(__file__)
PROJECT_ROOT   = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir))
PROCESSED_CACHE_PATH = os.path.join(PROJECT_ROOT, 'processed_pokemon_cache.json')
DATA_DIR       = os.path.join(PROJECT_ROOT, 'data')
OUTPUT_EVO     = os.path.join(DATA_DIR, 'evolutions.json')

os.makedirs(DATA_DIR, exist_ok=True)

SUFFIXES    = ['alola','alolan','galar','galarian','hisui','hisuian','paldea','paldean']
_SUFFIX_RE  = re.compile(r'^(.+)-(' + '|'.join(SUFFIXES) + r')$')

def get_base(name: str) -> str:
    m = _SUFFIX_RE.match(name)
    return m.group(1) if m else name

HARDCODED_OVERRIDES = {
    'eevee': [
        {
            'to': 'glaceon',
            'note': 'Can evolve via Ice Rock or Ice Stone',
            'methods': [
                { 'trigger': 'level-up', 'location': 'ice-rock' },
                { 'trigger': 'use-item', 'item': 'ice-stone' }
            ]
        },
        {
            'to': 'leafeon',
            'note': 'Can evolve via Moss Rock or Leaf Stone',
            'methods': [
                { 'trigger': 'level-up', 'location': 'moss-rock' },
                { 'trigger': 'use-item', 'item': 'leaf-stone' }
            ]
        }
    ]
}

FALLBACK_EVOLUTIONS = [
    { 'from': 'sandshrew-alola', 'to': 'sandslash-alola', 'trigger': 'use-item', 'item': 'ice-stone' },
    { 'from': 'rattata-alola', 'to': 'raticate-alola', 'trigger': 'level-up', 'min_level': 20, 'time_of_day': 'night' },
    { 'from': 'vulpix-alola', 'to': 'ninetales-alola', 'trigger': 'use-item', 'item': 'ice-stone' },
    { 'from': 'meowth-galar', 'to': 'perrserker', 'trigger': 'level-up', 'min_level': 28 },
    { 'from': 'voltorb-hisui', 'to': 'electrode-hisui', 'trigger': 'use-item', 'item': 'leaf-stone' },
    { 'from': 'wooper-paldea', 'to': 'clodsire', 'trigger': 'level-up', 'min_level': 20 },
    { 'from': 'corsola-galar', 'to': 'cursola', 'trigger': 'level-up', 'min_level': 38 },
    { 'from': 'dartrix', 'to': 'decidueye-hisui', 'trigger': 'level-up', 'min_level': 36, 'note': 'Only evolves into Hisuian Decidueye in the Hisui region.' },
    { 'from': 'pikachu', 'to': 'raichu-alola', 'trigger': 'use-item', 'item': 'thunder-stone', 'note': 'Only evolves into Alolan Raichu in the Alola region.' },
    { 'from': 'exeggcute', 'to': 'exeggutor-alola', 'trigger': 'use-item', 'item': 'leaf-stone', 'note': 'Only evolves into Alolan Exeggutor in the Alola region.' },
    { 'from': 'cubone', 'to': 'marowak-alola', 'trigger': 'level-up', 'min_level': 28, 'time_of_day': 'night', 'note': 'Only evolves into Alolan Marowak in the Alola region.' },
    { 'from': 'koffing', 'to': 'weezing-galar', 'trigger': 'level-up', 'min_level': 35, 'note': 'Only evolves into Galarian Weezing in the Galar region.' },
    { 'from': 'petilil', 'to': 'lilligant-hisui', 'trigger': 'use-item', 'item': 'sun-stone', 'note': 'Only evolves into Hisuian Lilligant in the Hisui region.' },
    { 'from': 'rufflet', 'to': 'braviary-hisui', 'trigger': 'level-up', 'min_level': 54, 'note': 'Only evolves into Hisuian Braviary in the Hisui region.' },
    { 'from': 'goomy', 'to': 'sliggoo-hisui', 'trigger': 'level-up', 'min_level': 40, 'note': 'Only evolves into Hisuian Sliggoo in the Hisui region.' },
    { 'from': 'sliggoo-hisui', 'to': 'goodra-hisui', 'trigger': 'level-up', 'min_level': 50, 'note': 'Must be raining.' },
    { 'from': 'slowpoke-galar', 'to': 'slowking-galar', 'trigger': 'use-item', 'item': 'galarica-wreath' },
    { 'from': 'slowpoke-galar', 'to': 'slowbro-galar', 'trigger': 'use-item', 'item': 'galarica-cuff' },
    { 'from': 'meowth-alola', 'to': 'persian-alola', 'trigger': 'level-up', 'min_happines': 160 },
    { 'from': 'farfetchd-galar', 'to': 'sirfetchd', 'trigger': 'other', 'note': 'Requires 3 critical hits in one battle.' },
    { 'from': 'qwilfish-hisui', 'to': 'overqwil', 'trigger': 'level-up', 'known_move': 'barb-barrage' },
    { 'from': 'sneasel-hisui', 'to': 'sneasler', 'trigger': 'level-up', 'held_item': 'razor-claw', 'time_of_day': 'day' },
    { 'from': 'yamask-galar', 'to': 'runerigus', 'trigger': 'other', 'note': 'Take 49+ damage and travel under large rock in Dusty Bowl.' },
    { 'from': 'mime-jr', 'to': 'mr-mime-galar', 'trigger': 'level-up', 'known_move': 'mimic', 'note': 'Only evolves into Galarian Mr. Mime in Galar.' },
    { 'from': 'mime-jr', 'to': 'mr-mime', 'trigger': 'level-up', 'known_move': 'mimic' },
    { 'from': 'mr-mime-galar', 'to': 'mr-rime', 'trigger': 'level-up', 'min_level': 42 },
    { 'from': 'diglett-alola', 'to': 'dugtrio-alola', 'trigger': 'level-up', 'min_level': 26 },
    { 'from': 'growlithe-hisui', 'to': 'arcanine-hisui', 'trigger': 'use-item', 'item': 'fire-stone' },
    { 'from': 'geodude-alola', 'to': 'graveler-alola', 'trigger': 'level-up', 'min_level': 25 },
    { 'from': 'graveler-alola', 'to': 'golem-alola', 'trigger': 'trade', 'note': 'Some versions have link items to fake a trade to evolve.' },
    { 'from': 'ponyta-galar', 'to': 'rapidash-galar', 'trigger': 'level-up', 'min_level': 40 },
    { 'from': 'grimer-alola', 'to': 'muk-alola', 'trigger': 'level-up', 'min_level': 38 },
    { 'from': 'quilava', 'to': 'typhlosion-hisui', 'trigger': 'level-up', 'min_level': 36, 'note': 'Only evolves into Hisuian Typhlosion in the Hisui region.' },
    { 'from': 'zorua-hisui', 'to': 'zoroark-hisui', 'trigger': 'level-up', 'min_level': 30 },
    { 'from': 'bergmite', 'to': 'avalugg-hisui', 'trigger': 'level-up', 'min_level': 37 },
    { 'from': 'zigzagoon-galar', 'to': 'linoone-galar', 'trigger': 'level-up', 'min_level': 20 },
    { 'from': 'linoone-galar', 'to': 'obstagoon', 'trigger': 'level-up', 'min_level': 35, 'time_of_day': 'night' },
    { 'from': 'dewott', 'to': 'samurott-hisui', 'trigger': 'level-up', 'min_level': 36, 'note': 'Only evolves into Hisuian Samurott in the Hisui region.' },
    { 'from': 'basculin-white-striped', 'to': 'basculegion-male', 'trigger': 'level-up', 'note': 'Basculin White Striped evolves after losing at least 294 HP from recoil damage without fainting' },
    { 'from': 'nincada', 'to': 'shedinja', 'trigger': 'level-up', 'min_level': 20, 'note': 'Upon evolving Nincada to Ninjask, if there is at least one space in your party and a pokeball in your bag.' },
    { 'from': 'espurr', 'to': 'meowstic', 'trigger': 'level-up', 'min_level': 25 },
    { 'from': 'rockruff', 'to': 'lycanroc-midday', 'trigger': 'level-up-during-day', 'min_level': 25, 'time_of_day': 'day', 'note': 'Ability must be Keen Eye, Vital Spirit, or Steadfast' },
    { 'from': 'rockruff', 'to': 'lycanroc-midnight', 'trigger': 'level-up-during-night', 'min_level': 25, 'time_of_day': 'night', 'note': 'Ability must be Keen Eye, Vital Spirit, or Steadfast' },
    { 'from': 'rockruff', 'to': 'lycanroc-dusk', 'trigger': 'level-up-during-evening', 'min_level': 25, 'time_of_day': 'evening', 'note': 'Ability must be Own Tempo' },
    { 'from': 'poltchageist', 'to': 'sinistcha', 'trigger': 'use-item', 'item': 'unremarkable teacup OR masterpiece teacup', 'note': 'Form-dependent evolution method' },
    { 'from': 'toxel', 'to': 'toxtricity-amped', 'trigger': 'level-up', 'min_level': 30, 'note': 'Nature must be one of Hardy, Brave, Adamant, Naughty, Docile, Impish, Lax, Hasty, Jolly, Naive, Rash, Sassy, or Quirky.' },
    { 'from': 'toxel', 'to': 'toxtricity-low-key', 'trigger': 'level-up', 'min_level': 30, 'note': 'Nature must be one of Lonely, Bold, Relaxed, Timid, Serious, Modest, Mild, Quiet, Bashful, Calm, Gentle, or Careful.' },
    { 'from': 'doublade', 'to': 'aegislash', 'trigger': 'use-item', 'min_level': 35, 'item': 'dusk-stone' },
    { 'from': 'pumpkaboo-average', 'to': 'gourgeist-average', 'trigger': 'trade' },
    { 'from': 'burmy', 'to': 'wormadam', 'trigger': 'level-up', 'min_level': 20, 'gender': 'female', 'note': 'Form depends on previous battle environment prior to level up (plant, sandy, trash)' },
    { 'from': 'burmy', 'to': 'mothim', 'trigger': 'level-up', 'min_level': 20, 'gender': 'male' },
    { 'from': 'kubfu', 'to': 'urshifu-single-strike', 'trigger': 'use-item', 'item': 'scroll-of-darkness' },
    { 'from': 'kubfu', 'to': 'urshifu-rapid-strike', 'trigger': 'use-item', 'item': 'scroll-of-waters' }
]

processed = json.load(open(PROCESSED_CACHE_PATH, encoding='utf-8'))
species_to_forms = defaultdict(list)
all_forms = set()
for entry in processed:
    form = entry['form']
    species = get_base(form)
    species_to_forms[species].append(form)
    all_forms.add(form)

species_meta = {}
for species, forms in species_to_forms.items():
    try:
        spj = requests.get(f"{POKEAPI_BASE_URL}/pokemon-species/{species}", timeout=10).json()
        chain_url = spj.get('evolution_chain',{}).get('url')
        cid = int(chain_url.rstrip('/').split('/')[-1]) if chain_url else None
    except Exception:
        cid = None
    species_meta[species] = cid

species_edges = []
chain_ids = {cid for cid in species_meta.values() if cid}
for cid in sorted(chain_ids):
    try:
        chain = fetch_evolution_chain(cid).chain
    except Exception:
        continue
    for e in flatten_chain(chain):
        if e['from'] in species_to_forms and e['to'] in species_to_forms:
            species_edges.append(e)

species_edges = [
    e for e in species_edges
    if not (e['from'] == 'mr-mime' and e['to'] == 'mr-rime')
]

print(f"↓ Collected {len(species_edges)} species‐level edges")

REGIONAL = set(SUFFIXES)
form_edges = []
for e in species_edges:
    sp_from, sp_to = e['from'], e['to']
    form_edges.append({ **e })
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

print(f"↓ Expanded to {len(form_edges)} form‐level edges")

# Inject hardcoded evolution fixes
for frm, methods in HARDCODED_OVERRIDES.items():
    for m in methods:
        if 'methods' in m:
            for sub in m['methods']:
                edge = {'from': frm, 'to': m['to'], 'note': m.get('note')}
                edge.update(sub)
                form_edges.append(edge)
        else:
            edge = {'from': frm, 'to': m['to']}
            for fld in ['trigger','min_level','item','min_happiness','min_beauty',
                        'gender','time_of_day','location','held_item','known_move',
                        'known_move_type','party_species','party_type',
                        'relative_physical_stats','trade_species','note']:
                edge[fld] = m.get(fld)
            form_edges.append(edge)

# Fallbacks for known evolutions not caught by API
existing_keys = set((e['from'], e['to']) for e in form_edges)
added = 0
for fb in FALLBACK_EVOLUTIONS:
    key = (fb['from'], fb['to'])
    existing = next((e for e in form_edges if (e['from'], e['to']) == key), None)
    if not existing:
        form_edges.append(fb)
        print(f"↳ Injected fallback: {fb['from']} → {fb['to']}")
        added += 1
    else:
        # Merge missing fields from fallback (especially note)
        updated = False
        for k, v in fb.items():
            if k not in existing or not existing[k]:
                existing[k] = v
                updated = True
        if updated:
            print(f"↳ Merged fallback note/fields into: {fb['from']} → {fb['to']}")
print(f"↳ Added {added} fallback evolutions")

priority = {
    'level-up-during-day':   5,
    'level-up-during-night': 5,
    'level-up-during-evening':  5,
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
    if not prev or score > priority.get(prev.get('trigger','other'),0):
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
