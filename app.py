from flask import Flask, request, jsonify, render_template
from flask import send_from_directory
import aiohttp
import asyncio
import os
import sys
import json
import ssl
import certifi
import logging
import yaml
from aiohttp import ClientTimeout
from asgiref.wsgi import WsgiToAsgi
from collections import defaultdict

# ─── CONFIG ──────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

SUFFIXES = ['alola','alolan','galar','galarian','hisui','hisuian','paldea','paldean']
REQUEST_TIMEOUT = 10

app = Flask(__name__, template_folder='templates')

def get_resource_path(*parts):
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(__file__)
    return os.path.join(base, *parts)

# ─── LOAD CACHES & OVERRIDES ───────────────────────────────────────────
PCACHE = get_resource_path('processed_pokemon_cache.json')
with open(PCACHE, 'r', encoding='utf-8') as f:
    PROCESSED = json.load(f)

FORM_BY_KEY = {p['name']: p for p in PROCESSED}
FORMS_BY_BASE = {}
for p in PROCESSED:
    FORMS_BY_BASE.setdefault(p['species'], []).append(p['name'])

EVO_PATH = get_resource_path('data','evolutions.json')
with open(EVO_PATH, encoding='utf-8') as f:
    EVOLUTIONS = json.load(f)

OV_PATH = get_resource_path('data','overrides.yml')
_raw_ov = yaml.safe_load(open(OV_PATH)) or {}
FORM_COLLAPSE_MAP = {
    frm.lower(): [m['to'].lower() for m in methods]
    for frm, methods in _raw_ov.items()
}

# ─── FORM RESOLUTION ───────────────────────────────────────────────────
def resolve_form_key(raw: str):
    k = raw.strip().lower()
    if k in FORM_BY_KEY:
        return k
    if k in FORM_COLLAPSE_MAP:
        return FORM_COLLAPSE_MAP[k][0]
    if '-' in k:
        base, suf = k.split('-',1)
        if base in FORMS_BY_BASE and suf in SUFFIXES:
            return base
    return None

# ─── DIRECT EVOLUTIONS FILTER ──────────────────────────────────────────
def get_direct_evolutions(form_key):
    src = FORM_BY_KEY[form_key]
    outgoing = [e.copy() for e in EVOLUTIONS if e['from']==form_key]
    species_forms = FORMS_BY_BASE[src['species']]

    if len(species_forms)<=1 or src.get('form_name'):
        return outgoing

    non_reg = [f for f in species_forms if '-' in f]
    filtered = []
    for e in outgoing:
        if any(any(e2['from']==nr and e2['to']==e['to'] for e2 in EVOLUTIONS) for nr in non_reg):
            continue
        filtered.append(e)

    by_sp = {}
    for e in filtered:
        tgt = FORM_BY_KEY[e['to']]
        by_sp.setdefault(tgt['species'], []).append(e)

    result=[]
    for lst in by_sp.values():
        result.extend(lst if len(lst)>1 else [lst[0]])
    return result

# ─── TYPE EFFECTIVENESS CALCULATOR ───────────────────────────────────
def calculate_type_effectiveness(type_data_list):
    damage = {}
    for td in type_data_list:
        for rel, arr in td['damage_relations'].items():
            m = {'double_damage_from':2,'half_damage_from':0.5,'no_damage_from':0}.get(rel,1)
            for o in arr:
                damage[o['name']] = damage.get(o['name'],1)*m

    categories = {
      'four_times_effective': [],'super_effective':[], 'normal_effective':[],
      'two_times_resistant':[],'four_times_resistant':[],'immune':[]
    }
    all_types = {'normal','fire','water','electric','grass','ice','fighting',
                 'poison','ground','flying','psychic','bug','rock','ghost',
                 'dragon','dark','steel','fairy'}
    for t,m in damage.items():
        if m==4:   categories['four_times_effective'].append(t)
        elif m==2: categories['super_effective'].append(t)
        elif m==0.5:categories['two_times_resistant'].append(t)
        elif m==0.25:categories['four_times_resistant'].append(t)
        elif m==0: categories['immune'].append(t)
    categories['normal_effective'] = list(all_types - set().union(*categories.values()))
    return categories

# ─── EVOLUTION CONDITIONS FORMATTER ───────────────────────────────────
def get_evolution_conditions(details):
    conds = []
    for d in details:
        c = {}
        if d.get('trigger'):      c['Triggered by'] = d['trigger'].replace('-',' ').title()
        if d.get('item'):         c['Item']         = d['item'].replace('-',' ').title()
        if d.get('min_level')!=None:   c['Minimum Level'] = d['min_level']
        if d.get('time_of_day'):  c['Time of Day']  = d['time_of_day'].replace('-',' ').title()
        if d.get('location'):     c['Location']     = d['location'].replace('-',' ').title()
        if d.get('held_item'):    c['Held Item']    = d['held_item'].replace('-',' ').title()
        if d.get('known_move'):   c['Known Move']   = d['known_move'].replace('-',' ').title()
        if d.get('known_move_type'): c['Known Move Type']=d['known_move_type'].replace('-',' ').title()
        if d.get('min_happiness')!=None: c['Min Happiness']=d['min_happiness']
        if d.get('min_beauty')!=None:    c['Min Beauty']   =d['min_beauty']
        if d.get('party_species'): c['Party Species'] = d['party_species'].replace('-',' ').title()
        if d.get('party_type'):   c['Party Type']    = d['party_type'].replace('-',' ').title()
        if d.get('relative_physical_stats')!=None:
                                  c['Relative Phys Stats']=d['relative_physical_stats']
        if d.get('trade_species'):c['Trade Species'] = d['trade_species'].replace('-',' ').title()
        if d.get('gender'):       c['Gender']        = d['gender'].replace('-',' ').title()
        if c:
            conds.append(c)
    # dedupe
    return [dict(t) for t in {tuple(x.items()) for x in conds}]

# ─── AIOHTTP FETCH HELPERS ────────────────────────────────────────────
async def create_aiohttp_session():
    ctx = ssl.create_default_context(cafile=certifi.where())
    timeout = ClientTimeout(total=REQUEST_TIMEOUT)
    return aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=ctx),
        timeout=timeout
    )

async def fetch(session, url):
    try:
        async with session.get(url) as r:
            return await r.json() if r.status==200 else None
    except Exception as e:
        logger.error("Fetch error %s", e)
        return None

# ─── DYNAMIC CACHE FILLER ─────────────────────────────────────────────
async def process_pokemon_data(names, processed):
    session = await create_aiohttp_session()
    async with session:
        raw_cache = get_resource_path('pokemon_cache.json')
        master     = json.load(open(raw_cache))
        to_fetch   = {p['name']:p['url'] for p in master['results'] if p['name'] in names}
        for name, url in to_fetch.items():
            v = await fetch(session,url)
            if not v: continue
            # stats
            stats = {s['stat']['name'].replace('-','_'):s['base_stat'] for s in v['stats']}
            stats['total'] = sum(stats.values())
            # types
            type_urls = [t['type']['url'] for t in v['types']]
            type_data = [d for d in (await asyncio.gather(*[fetch(session,u) for u in type_urls])) if d]
            eff = calculate_type_effectiveness(type_data)
            processed.append({
                'name':         name,
                'display_name': name.replace('-',' ').title(),
                'form':         v['name'],
                'id':           v['id'],
                'species':      name.split('-',1)[0],
                'form_name':    (v['name'].split('-',1)[1] if '-' in v['name'] else ''),
                'sprite_url':   f"/static/sprites/{name}.png",
                'types':        [t['type']['name'] for t in v['types']],
                'effectiveness':eff,
                'stats':        stats
            })

# ─── ROUTES ───────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('pokemonlandingpage.html')

@app.route('/typeeffectiveness')
def page_type_effectiveness():
    return render_template('pokemontypeeffectiveness.html',
        collapse_map=json.dumps(FORM_COLLAPSE_MAP),
        forms_by_base_json=json.dumps(FORMS_BY_BASE)
    )

@app.route('/stats')
def page_stats():
    return render_template('pokemonstats.html',
        collapse_map=json.dumps(FORM_COLLAPSE_MAP),
        forms_by_base_json=json.dumps(FORMS_BY_BASE)
    )

@app.route('/typecalculator')
def page_typecalc():
    return render_template('typecalculator.html')

@app.route('/natures')
def page_natures():
    return render_template('pokemonnatures.html')

@app.route('/evolutions')
def evolution():
    # load processed cache
    proc_path = PCACHE
    try:
        with open(proc_path, 'r', encoding='utf-8') as f:
            processed = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        processed = []

    return render_template(
        'pokemonevolutions.html',
        collapse_map=json.dumps(FORM_COLLAPSE_MAP),
        forms_by_base_json=json.dumps(FORMS_BY_BASE),
        processed_cache_json=json.dumps(processed),
        evolutions_json=json.dumps(EVOLUTIONS)
    )

@app.route('/api/pokemon/info')
@app.route('/api/pokemon/stats')
async def api_info():
    raw = request.args.get('name','').lower().strip()
    real = resolve_form_key(raw)
    if not real:
        return jsonify({'error':'Unknown Pokémon'}),404

    proc = get_resource_path('processed_pokemon_cache.json')
    processed = json.load(open(proc))
    if real not in {p['name'] for p in processed}:
        await process_pokemon_data([real], processed)
        json.dump(processed, open(proc,'w'), indent=2)

    p = next((x for x in processed if x['name']==real),None)
    if not p:
        return jsonify({'error':'Not found'}),404
    if real!=raw:
        p['display_name']=real.split('-',1)[0].title()
    return jsonify([p])

@app.route('/api/pokemon/suggestions')
def suggestions():
    q = request.args.get('query','').lower()
    # 1) find all raw form-keys whose display_name matches
    raw = [k for k,v in FORM_BY_KEY.items()
           if q in v['display_name'].lower()]

    # 2) bucket them by collapsed base (resolve_form_key strips suffixes/overrides)
    buckets = defaultdict(list)
    for form_key in raw:
        base = resolve_form_key(form_key)
        buckets[base].append(form_key)

    # 3) for each base, pick the one raw form that actually has evolutions
    suggestions = []
    for base, forms in buckets.items():
        # find a form with at least one direct evolution
        rep = next((f for f in forms if get_direct_evolutions(f)), forms[0])
        suggestions.append({
            'display': FORM_BY_KEY[rep]['display_name'],
            'key':       rep
        })

    return jsonify(suggestions=suggestions)

@app.route('/api/pokemon/evolutions')
def api_evo():
    raw = request.args.get('name','').lower().strip()
    # 1) resolve any form back to its canonical key
    key = resolve_form_key(raw) or raw
    # 2) fallback to base species if needed
    if key not in FORM_BY_KEY:
        base = key.split('-',1)[0]
        key = resolve_form_key(base) or base
    if key not in FORM_BY_KEY:
        return jsonify([]), 200

    # ─── NEW: climb up the tree to the ultimate chain root ─────────────
    def find_chain_root(name):
        # always work with your canonical form key
        candidate = resolve_form_key(name) or name
        while True:
            # look for any evolution edge that targets this candidate
            parent = next((e for e in EVOLUTIONS if e['to'] == candidate), None)
            if not parent:
                return candidate
            # step up to its parent
            candidate = resolve_form_key(parent['from']) or parent['from']

    root = find_chain_root(key)
    # ─────────────────────────────────────────────────────────────────

    chain = []
    def trav(name, frm=None):
        if name not in FORM_BY_KEY:
            return
        f = FORM_BY_KEY[name]
        node = {
            'name': name,
            'display_name': f['species'].title() + (f" ({f['form_name'].title()})" if f['form_name'] else ''),
            'sprite_url': f['sprite_url'],
            'evolves_from': FORM_BY_KEY[frm]['species'].title() if frm else None,
            'evolution_conditions': []
        }
        if frm:
            edge = next((e for e in EVOLUTIONS if e['from']==frm and e['to']==name), None)
            if edge:
                node['evolution_conditions'] = get_evolution_conditions([edge])
                if edge.get('note'):
                    node['note'] = edge['note']
        chain.append(node)
        for e in get_direct_evolutions(name):
            child = resolve_form_key(e['to']) or e['to']
            trav(child, name)

    trav(root)
    return jsonify(chain)


asgi_app = WsgiToAsgi(app)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
