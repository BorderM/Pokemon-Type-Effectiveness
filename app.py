from flask import Flask, request, jsonify, render_template
import aiohttp
import asyncio
import difflib
import os
import sys
import json
import ssl
import certifi
import logging
from aiohttp import ClientTimeout
from asgiref.wsgi import WsgiToAsgi
from data.FormCollapse import (
    FORM_COLLAPSE_MAP,
    normalize_form_key,
    resolve_form_key,
    FORMS_BY_BASE,
)

SUFFIXES = ['alola','alolan','galar','galarian','hisui','hisuian','paldea','paldean']

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

app = Flask(__name__, template_folder='templates')

CACHE_FILE = 'pokemon_cache.json'
PROCESSED_CACHE_FILE = 'processed_pokemon_cache.json'
REQUEST_TIMEOUT = 10  # seconds

def get_resource_path(filename):
    if getattr(sys, 'frozen', False):
        # PyInstaller “one-dir” and “one-file” both unpack to _MEIPASS
        base_path = sys._MEIPASS
    else:
        # script’s directory
        base_path = os.path.dirname(__file__)

    return os.path.join(base_path, filename)

FORMS_PATH = get_resource_path(os.path.join('data', 'forms.json'))
EVOLUTIONS_PATH = get_resource_path(os.path.join('data', 'evolutions.json'))

with open(FORMS_PATH, 'r', encoding='utf-8') as f:
    FORMS = json.load(f)

with open(EVOLUTIONS_PATH, 'r', encoding='utf-8') as f:
    EVOLUTIONS = json.load(f)


# fast lookup by form key (e.g. “vulpix”, “vulpix-alola”)
FORM_BY_KEY = { f['key']: f for f in FORMS }

# group forms by species name
FORMS_BY_SPECIES = {}
for f in FORMS:
    FORMS_BY_SPECIES.setdefault(f['species'], []).append(f)

def get_direct_evolutions(form_key):
    """
    Returns all the evolution-edges that apply to exactly this form_key,
    while filtering out evolutions that belong to regional forms when
    invoked on a regular form, except when there are multiple evolutions
    to the same species (in which case all are shown).
    """
    src = FORM_BY_KEY[form_key]
    # collect all outgoing edges from this exact form
    outgoing = [e.copy() for e in EVOLUTIONS if e['from'] == form_key]

    # get all forms of this species
    species_forms = FORMS_BY_SPECIES[src['species']]
    # if only one form exists, return all its edges
    if len(species_forms) <= 1:
        return outgoing
    # if user searched a non-regular form, show all its edges
    if src['form_name']:
        return outgoing

    # for regular form in a multi-form species, filter out any evolution
    # that also appears for a non-regular form (i.e., region-specific evolutions)
    non_regular_keys = [f['key'] for f in species_forms if f['form_name']]
    filtered = []
    for e in outgoing:
        # if a non-regular form also evolves to the same target, skip this edge
        if any(any(e2['from'] == nr and e2['to'] == e['to'] for e2 in EVOLUTIONS) for nr in non_regular_keys):
            continue
        filtered.append(e)

    # group by target species to handle multiple evolutions to same species
    by_species = {}
    for e in filtered:
        tgt = FORM_BY_KEY[e['to']]
        by_species.setdefault(tgt['species'], []).append(e)

    # build final list: single edge kept, multiple edges all kept
    result = []
    for edges in by_species.values():
        if len(edges) == 1:
            result.append(edges[0])
        else:
            result.extend(edges)
    return result

# Replace the old get_direct_evolutions in app.py with this updated version.


async def create_aiohttp_session():
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    timeout = ClientTimeout(total=REQUEST_TIMEOUT)
    return aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context), timeout=timeout)

async def fetch(session, url):
    try:
        async with session.get(url) as response:
            if response.status != 200:
                logger.error(f"Failed to fetch {url}: {response.status}")
                return None
            return await response.json()
    except asyncio.TimeoutError:
        logger.error(f"Request to {url} timed out.")
        return None
    except aiohttp.ClientError as e:
        logger.error(f"Client error occurred while fetching {url}: {e}")
        return None

@app.route('/')
def index():
    return render_template('pokemonlandingpage.html')

@app.route('/typeeffectiveness')
def type_effectiveness():
    return render_template('pokemontypeeffectiveness.html', collapse_map=json.dumps(FORM_COLLAPSE_MAP))

@app.route('/stats')
def stats():
    return render_template('pokemonstats.html', collapse_map=json.dumps(FORM_COLLAPSE_MAP))

@app.route('/typecalculator')
def type_calculator():
    return render_template('typecalculator.html')

@app.route('/natures')
def natures():
    return render_template('pokemonnatures.html')
    
@app.route('/evolutions')
def evolution():
    return render_template('pokemonevolutions.html')

@app.route('/api/pokemon/info', methods=['GET'])
async def get_pokemon_info():
    raw      = request.args.get('name','').strip().lower()
    real_key = resolve_form_key(raw, FORM_BY_KEY, FORMS_BY_BASE, SUFFIXES)
    if not real_key:
        return jsonify({'error':'Unknown Pokémon'}), 404

    # load or init cache
    proc = get_resource_path(PROCESSED_CACHE_FILE)
    try:
        with open(proc, 'r', encoding='utf-8') as f:
            processed = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        processed = []

    # fetch if needed
    if real_key not in {p['name'] for p in processed}:
        await process_pokemon_data([real_key], processed)
        with open(proc, 'w', encoding='utf-8') as f:
            json.dump(processed, f, indent=2)

    # find it
    match = next((p for p in processed if p['name']==real_key), None)
    if not match:
        return jsonify({'error':'Not found'}), 404

    # attach cosmetic sprites
    variants = [k for k,v in FORM_COLLAPSE_MAP.items() if v==real_key] + [real_key]
    match['sprites'] = [
        FORM_BY_KEY[k]['sprite_url'] for k in set(variants) if k in FORM_BY_KEY
    ]

    # — NEW: if we collapsed “raw” → “real_key”, strip off form-suffix:
    if real_key != raw:
        base = real_key.split('-',1)[0]
        match['display_name'] = base.title()

    return jsonify([match])

@app.route('/api/pokemon/stats', methods=['GET'])
async def get_pokemon_stats():
    return await get_pokemon_info()

@app.route('/api/pokemon/suggestions')
def suggestions():
    q = request.args.get('query','').strip().lower()
    if not q:
        return jsonify({'suggestions': []})

    seen = set()
    outs = []
    for key in FORM_BY_KEY:
        # 1) skip deletes
        if key in FORM_COLLAPSE_MAP and FORM_COLLAPSE_MAP[key] == 'delete':
            continue

        # 2) resolve into whatever key _should_ appear
        candidate = resolve_form_key(key, FORM_BY_KEY, FORMS_BY_BASE, SUFFIXES)
        if not candidate or candidate in seen:
            continue

        # 3) only include if it matches the query
        if q in candidate:
            seen.add(candidate)
            outs.append(candidate)
            if len(outs) >= 10:
                break

    return jsonify({'suggestions': outs})

@app.route('/api/pokemon/evolutions', methods=['GET'])
def get_pokemon_evolutions():
    raw = request.args.get('name','').strip().lower()
    real_key = resolve_form_key(raw, FORM_BY_KEY, FORMS_BY_SPECIES, SUFFIXES)
    if not real_key or real_key not in FORM_BY_KEY:
        return jsonify({'error':'Unknown Pokémon'}), 404

    def find_root(name):
        form = FORM_BY_KEY[name]
        if form.get('form_name'):
            return name
        parents = [e['from'] for e in EVOLUTIONS if e['to']==name]
        return find_root(parents[0]) if parents else name

    root = find_root(real_key)
    chain = []

    def traverse(name, evolves_from=None):
        form = FORM_BY_KEY[name]
        node = {
            'name': name,
            'display_name': form['species'].title() + (f" ({form['form_name'].title()})" if form['form_name'] else ''),
            'sprite_url': form['sprite_url'],
            'evolves_from': FORM_BY_KEY[evolves_from]['species'].title() if evolves_from else None,
            'evolution_conditions': []
        }
        if evolves_from:
            edge = next(e for e in EVOLUTIONS if e['from']==evolves_from and e['to']==name)
            node['evolution_conditions'] = get_evolution_conditions([edge])
            if edge.get('note'):
                node['note'] = edge['note']
        chain.append(node)

        for e in get_direct_evolutions(name):
            # map target through resolver
            child = resolve_form_key(e['to'], FORM_BY_KEY, FORMS_BY_SPECIES, SUFFIXES)
            if not child:
                continue
            traverse(child, name)

    traverse(root)
    return jsonify(chain)

def capitalize_pokemon_name(name):
    return ' '.join([word.capitalize() for word in name.split('-')])

def get_evolution_conditions(evolution_details):
    conditions = []
    for detail in evolution_details:
        condition = {}
        if detail.get('trigger'):
            condition['Triggered by'] = detail['trigger'].replace('-', ' ').title()
        if detail.get('item'):
            condition['Item'] = detail['item'].replace('-', ' ').title()
        if detail.get('min_level') is not None:
            condition['Minimum Level'] = detail['min_level']
        if detail.get('time_of_day'):
            condition['Time of Day'] = detail['time_of_day'].replace('-', ' ').title()
        if detail.get('location'):
            condition['Location'] = detail['location'].replace('-', ' ').title()
        if detail.get('held_item'):
            condition['Held Item'] = detail['held_item'].replace('-', ' ').title()
        if detail.get('known_move'):
            condition['Known Move'] = detail['known_move'].replace('-', ' ').title()
        if detail.get('known_move_type'):
            condition['Known Move Type'] = detail['known_move_type'].replace('-', ' ').title()
        if detail.get('min_happiness') is not None:
            condition['Minimum Happiness'] = detail['min_happiness']
        if detail.get('min_beauty') is not None:
            condition['Minimum Beauty'] = detail['min_beauty']
        if detail.get('party_species'):
            condition['Party Species'] = detail['party_species'].replace('-', ' ').title()
        if detail.get('party_type'):
            condition['Party Type'] = detail['party_type'].replace('-', ' ').title()
        if detail.get('relative_physical_stats') is not None:
            condition['Relative Physical Stats'] = detail['relative_physical_stats']
        if detail.get('trade_species'):
            condition['Trade Species'] = detail['trade_species'].replace('-', ' ').title()
        if detail.get('gender'):
            condition['Gender'] = detail['gender'].replace('-', ' ').title()
        
        if condition:  # Only append non-empty condition dictionaries
            conditions.append(condition)
    
    # Remove duplicates
    unique_conditions = [dict(t) for t in {tuple(d.items()) for d in conditions}]
    return unique_conditions

def parse_evolution_chain(evolution_chain_data, pokemon_name):
    evolution_data = []

    def extract_evolution_details(chain, evolves_from=None):
        details = {
            'name': capitalize_pokemon_name(chain['species']['name']),
            'evolves_from': capitalize_pokemon_name(evolves_from) if evolves_from else None,
            'evolution_conditions': get_evolution_conditions(chain.get('evolution_details', [])),
            'id': chain['species']['url'].split('/')[-2],  # Extract ID from the URL
        }

        evolution_data.append(details)

        for evolves_to in chain.get('evolves_to', []):
            extract_evolution_details(evolves_to, chain['species']['name'])

    extract_evolution_details(evolution_chain_data)

    return evolution_data

async def process_pokemon_data(pokemon_names, processed_data):
    async with await create_aiohttp_session() as session:
        # load the *raw* cache from dev or frozen bundle:
        raw_path = get_resource_path(CACHE_FILE)
        if not os.path.exists(raw_path):
            logger.error("CACHE_FILE not found at %s", raw_path)
            return

        with open(raw_path, 'r', encoding='utf-8') as f:
            pokemon_data = json.load(f)

        processed_names = {p['name'] for p in processed_data}
        new_pokemon = [p for p in pokemon_data['results'] if p['name'] in pokemon_names and p['name'] not in processed_names]

        logger.info("Processing Pokémon data...")
        for pokemon in new_pokemon:
            pokemon_details = await fetch(session, pokemon['url'])
            if not pokemon_details:
                logger.error(f"Failed to fetch details for {pokemon['name']}")
                continue

            species_url = pokemon_details['species']['url']
            species_data = await fetch(session, species_url)
            varieties = species_data.get('varieties', []) if species_data else []

            for variety in varieties:
                variety_url = variety['pokemon']['url']
                variety_data = await fetch(session, variety_url)
                if not variety_data:
                    logger.error(f"Failed to fetch variety details for {pokemon['name']}")
                    continue

                types = variety_data['types']
                type_names = [type_info['type']['name'] for type_info in types]

                type_urls = [type_info['type']['url'] for type_info in types]
                type_data_list = await asyncio.gather(*[fetch(session, url) for url in type_urls])
                type_data_list = [data for data in type_data_list if data]
                effectiveness = calculate_type_effectiveness(type_data_list)

                stats = {
                    'hp': variety_data['stats'][0]['base_stat'],
                    'attack': variety_data['stats'][1]['base_stat'],
                    'defense': variety_data['stats'][2]['base_stat'],
                    'special_attack': variety_data['stats'][3]['base_stat'],
                    'special_defense': variety_data['stats'][4]['base_stat'],
                    'speed': variety_data['stats'][5]['base_stat'],
                    'total': sum(stat['base_stat'] for stat in variety_data['stats'])
                }

                processed_data.append({
                    'name': variety_data['name'],
                    'display_name': variety['pokemon']['name'].capitalize(),
                    'form': variety['pokemon']['name'],
                    'id': variety_data['id'],
                    'types': type_names,
                    'effectiveness': effectiveness,
                    'stats': stats
                })

        with open(PROCESSED_CACHE_FILE, 'w') as f:
            json.dump(processed_data, f)
        logger.info("Processed Pokémon data cached successfully.")

def calculate_type_effectiveness(type_data_list):
    damage_multipliers = {}

    for type_data in type_data_list:
        damage_relations = type_data['damage_relations']

        for relation_type, related_types in damage_relations.items():
            multiplier = 1
            if relation_type == 'double_damage_from':
                multiplier = 2
            elif relation_type == 'half_damage_from':
                multiplier = 0.5
            elif relation_type == 'no_damage_from':
                multiplier = 0

            for related_type in related_types:
                type_name = related_type['name']
                if type_name not in damage_multipliers:
                    damage_multipliers[type_name] = 1
                damage_multipliers[type_name] *= multiplier

    effectiveness = {
        'four_times_effective': [],
        'super_effective': [],
        'normal_effective': [],
        'two_times_resistant': [],
        'four_times_resistant': [],
        'immune': []
    }

    for type_name, multiplier in damage_multipliers.items():
        if multiplier == 4:
            effectiveness['four_times_effective'].append(type_name)
        elif multiplier == 2:
            effectiveness['super_effective'].append(type_name)
        elif multiplier == 0.25:
            effectiveness['four_times_resistant'].append(type_name)
        elif multiplier == 0.5:
            effectiveness['two_times_resistant'].append(type_name)
        elif multiplier == 0:
            effectiveness['immune'].append(type_name)

    all_types = set([
        'normal', 'fire', 'water', 'electric', 'grass', 'ice', 'fighting', 'poison',
        'ground', 'flying', 'psychic', 'bug', 'rock', 'ghost', 'dragon', 'dark', 'steel', 'fairy'
    ])
    categorized_types = (
        set(effectiveness['four_times_effective']) |
        set(effectiveness['super_effective']) |
        set(effectiveness['two_times_resistant']) |
        set(effectiveness['four_times_resistant']) |
        set(effectiveness['immune'])
    )
    effectiveness['normal_effective'] = list(all_types - categorized_types)

    return effectiveness

def calculate_combined_effectiveness(type_data_list):
    damage_multipliers = {}

    for type_data in type_data_list:
        damage_relations = type_data['damage_relations']

        for relation_type, related_types in damage_relations.items():
            multiplier = 1
            if relation_type == 'double_damage_from':
                multiplier = 2
            elif relation_type == 'half_damage_from':
                multiplier = 0.5
            elif relation_type == 'no_damage_from':
                multiplier = 0

            for related_type in related_types:
                type_name = related_type['name']
                if type_name not in damage_multipliers:
                    damage_multipliers[type_name] = 1
                damage_multipliers[type_name] *= multiplier

    effectiveness = {
        'four_times_effective': [],
        'super_effective': [],
        'normal_effective': [],
        'two_times_resistant': [],
        'four_times_resistant': [],
        'immune': []
    }

    for type_name, multiplier in damage_multipliers.items():
        if multiplier == 4:
            effectiveness['four_times_effective'].append(type_name)
        elif multiplier == 2:
            effectiveness['super_effective'].append(type_name)
        elif multiplier == 0.25:
            effectiveness['four_times_resistant'].append(type_name)
        elif multiplier == 0.5:
            effectiveness['two_times_resistant'].append(type_name)
        elif multiplier == 0:
            effectiveness['immune'].append(type_name)

    all_types = set([
        'normal', 'fire', 'water', 'electric', 'grass', 'ice', 'fighting', 'poison',
        'ground', 'flying', 'psychic', 'bug', 'rock', 'ghost', 'dragon', 'dark', 'steel', 'fairy'
    ])
    categorized_types = (
        set(effectiveness['four_times_effective']) |
        set(effectiveness['super_effective']) |
        set(effectiveness['two_times_resistant']) |
        set(effectiveness['four_times_resistant']) |
        set(effectiveness['immune'])
    )
    effectiveness['normal_effective'] = list(all_types - categorized_types)

    return effectiveness

@app.route('/api/typeeffectiveness', methods=['GET'])
async def get_type_effectiveness():
    try:
        type1 = request.args.get('type1')
        type2 = request.args.get('type2', None)
        if not type1:
            return jsonify({'error': 'Type 1 is required'}), 400

        type_urls = [f"https://pokeapi.co/api/v2/type/{type1}"]
        if type2:
            type_urls.append(f"https://pokeapi.co/api/v2/type/{type2}")

        async with aiohttp.ClientSession() as session:
            type_data_list = await asyncio.gather(*[fetch(session, url) for url in type_urls])

        effectiveness = calculate_combined_effectiveness(type_data_list)
        return jsonify(effectiveness)

    except Exception as e:
        logger.error(f"Error occurred: {e}", exc_info=True)
        return jsonify({'error': 'An error occurred while processing your request.'}), 500

# Wrap the Flask app with WsgiToAsgi for ASGI compatibility
asgi_app = WsgiToAsgi(app)

if __name__ == '__main__':
    try:
        logger.info("Starting initialization...")
        logger.info("Starting Flask server...")
        app.run(debug=True, host='0.0.0.0', port=5000)  # Ensure it listens on all interfaces
    except Exception as e:
        logger.error(f"Fatal error occurred: {e}", exc_info=True)
        input("Press Enter to exit...")  # Keep the console window open
