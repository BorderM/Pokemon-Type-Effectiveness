import re
import yaml
import json
import os
import requests
from pokeapi_client import fetch_form_metadata
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

ROOT_DIR = os.path.dirname(__file__)
CACHE_PATH = os.path.join(ROOT_DIR, 'pokemon_cache.json')
OVERRIDES_PATH = os.path.join(ROOT_DIR, 'overrides.yml')
OUTPUT_DIR = os.path.join(ROOT_DIR, 'data')
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

# 2. Build evolutions.json via Poké DB
print("Building evolution chains from Poké DB…")
all_edges = []

def fetch_pokemondb_evolutions(species):
    """
    Scrape https://pokemondb.net/pokedex/{species} → Evolution chart
    and return a list of dicts with the same keys your app expects:
    from, to, trigger, min_level, item, time_of_day, location,
    held_item, known_move, known_move_type, min_happiness, min_beauty,
    party_species, party_type, relative_physical_stats, trade_species, gender, note
    """
    url = f"https://pokemondb.net/pokedex/{species}"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # find the Evolution chart section
    h2 = soup.find("h2", string=re.compile(r"Evolution chart", re.I))
    if not h2:
        return []

    ul = h2.find_next_sibling("ul", class_="infocard-list-evo")
    if not ul:
        return []

    items = ul.find_all("li", recursive=False)
    chains = []
    for i in range(len(items) - 1):
        frm_li, to_li = items[i], items[i+1]
        frm = frm_li.select_one("a.ent-name").text.strip().lower().replace(" ", "-")
        to  = to_li.select_one("a.ent-name").text.strip().lower().replace(" ", "-")

        note_node = frm_li.find_next_sibling(["small","em"])
        note = note_node.text.strip() if note_node else None

        # now extract every field
        m_lvl    = re.search(r"\blevel\s*(\d+)\b", note or "", re.I)
        m_item   = re.search(r"\b(Ice|Moon|Thunder|Fire|Leaf) Stone\b", note or "", re.I)
        m_time   = re.search(r"\b(during the day|at night)\b", note or "", re.I)
        m_loc    = re.search(r"\bleveled up (?:in|near) ([A-Za-z0-9' ]+?)(?:\.|,|$)", note or "", re.I)
        m_happy  = re.search(r"(?:high friendship|happiness of at least (\d+))", note or "", re.I)
        m_beauty = re.search(r"beauty of at least (\d+)", note or "", re.I)
        m_hold   = re.search(r"holding (.+?)(?:\.|,|$)", note or "", re.I)
        m_known  = re.search(r"knowing (?:the move )?(.+?)(?:\.|,|$)", note or "", re.I)
        m_kmt    = re.search(r"knowing a (.+?)-type move", note or "", re.I)
        m_party  = re.search(r"with a ([A-Za-z0-9' ]+?) in (?:the )?party", note or "", re.I)
        m_ptype  = re.search(r"with a ([A-Za-z0-9' ]+?)-type (?:Pokémon|move)", note or "", re.I)
        m_trade  = re.search(r"\btrade\b", note or "", re.I)
        m_tspec  = re.search(r"traded for (.+?)(?:\.|,|$)", note or "", re.I)
        m_gender = re.search(r"\bfor (male|female)\b", note or "", re.I)
        m_rps    = None
        # look for Attack > Defense etc.
        if note and ">" in note:
            if "attack > defense" in note.lower(): m_rps = 1
            if "attack < defense" in note.lower(): m_rps = -1
            if "attack = defense" in note.lower() or "attack = defense" in note.lower(): m_rps = 0

        chains.append({
            "from":                    frm,
            "to":                      to,
            "trigger":                 (
                                        "level-up"    if m_lvl else
                                        "use-item"    if m_item else
                                        "trade"       if m_trade else
                                        "other"
                                       ),
            "min_level":               int(m_lvl.group(1))    if m_lvl    else None,
            "item":                    m_item.group(0).lower().replace(" ", "-") if m_item else None,
            "time_of_day":             m_time.group(1).split()[-1].lower() if m_time else None,
            "location":                m_loc.group(1).strip().lower().replace(" ", "-") if m_loc else None,
            "min_happiness":           int(m_happy.group(1))   if m_happy and m_happy.group(1) else (220 if m_happy else None),
            "min_beauty":              int(m_beauty.group(1))  if m_beauty else None,
            "held_item":               m_hold.group(1).lower().replace(" ", "-") if m_hold else None,
            "known_move":              m_known.group(1).lower().replace(" ", "-") if m_known else None,
            "known_move_type":         m_kmt.group(1).lower()  if m_kmt else None,
            "party_species":           m_party.group(1).lower().replace(" ", "-") if m_party else None,
            "party_type":              m_ptype.group(1).lower() if m_ptype else None,
            "relative_physical_stats": m_rps,
            "trade_species":           m_tspec.group(1).lower().replace(" ", "-") if m_tspec else None,
            "gender":                  m_gender.group(1).lower() if m_gender else None,
            "note":                    note
        })

    return chains

form_keys = {f['key'] for f in forms}
species_list = sorted({f['species'] for f in forms})

for sp in species_list:
    try:
        edges = fetch_pokemondb_evolutions(sp)
    except Exception as e:
        print(f"  ✗ {sp}: {e}")
        continue

    # only keep chains where both ends exist locally
    for e in edges:
        if e['from'] in form_keys and e['to'] in form_keys:
            all_edges.append(e)

    # re-apply your region suffix logic
    for suffix in SUFFIXES:
        suf = "-" + suffix
        for e in list(all_edges):
            if e['from'] == sp and (e['to'] + suf) in form_keys:
                ve = e.copy()
                ve['from'] += suf
                ve['to']   += suf
                all_edges.append(ve)

# 3. Apply overrides for unique methods
overrides = yaml.safe_load(open(OVERRIDES_PATH)) or {}

# 3a. Drop only API edges matching explicit overrides
cleaned = []
for e in all_edges:
    methods = overrides.get(e['from'], [])
    if any(m['to'] == e['to'] for m in methods):
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

# 4. Deduplicate and ensure all edge keys
print("Deduplicating edges...")
seen = set()
final_edges = []
fields = ['from','to','trigger','item','min_level','min_happiness','min_beauty','gender',
          'time_of_day','location','held_item','known_move','known_move_type',
          'party_species','party_type','relative_physical_stats','trade_species','note']
for e in all_edges:
    key_tuple = tuple(e.get(k) for k in ['from','to','trigger','item','min_level','min_happiness','min_beauty','gender'])
    if key_tuple in seen:
        continue
    seen.add(key_tuple)
    for k in fields:
        e.setdefault(k, None)
    final_edges.append(e)

# 4a. Propagate variant edges up to base species
to_add = []
for e in final_edges:
    frm = e['from']
    if '-' in frm:
        base = frm.split('-',1)[0]
        if not any(x['from']==base and x['to']==e['to'] for x in final_edges):
            cp = e.copy()
            cp['from'] = base
            to_add.append(cp)
final_edges.extend(to_add)

with open(os.path.join(OUTPUT_DIR, 'evolutions.json'), 'w') as f:
    json.dump(final_edges, f, indent=2)
print(f"Wrote {len(final_edges)} evolution edges to data/evolutions.json")
