from flask import Flask, request, jsonify, render_template
import aiohttp
import asyncio
import difflib
import os
import json
import ssl
import certifi
import logging
from aiohttp import ClientTimeout
from asgiref.wsgi import WsgiToAsgi

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

app = Flask(__name__, template_folder='templates')

CACHE_FILE = 'pokemon_cache.json'
PROCESSED_CACHE_FILE = 'processed_pokemon_cache.json'
REQUEST_TIMEOUT = 10  # seconds

def get_resource_path(filename):
    """Get the absolute path to a resource, works for dev and for PyInstaller."""
    try:
        # PyInstaller stores data files in a tmp folder referred to as _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, filename)

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
    return render_template('pokemontypeeffectiveness.html')

@app.route('/stats')
def stats():
    return render_template('pokemonstats.html')

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
    try:
        pokemon_names = request.args.getlist('name')
        if not pokemon_names:
            return jsonify({'error': 'No Pokémon names provided'}), 400

        # Load processed cache if exists, otherwise create an empty list
        if os.path.exists(PROCESSED_CACHE_FILE):
            with open(PROCESSED_CACHE_FILE, 'r') as f:
                processed_data = json.load(f)
        else:
            processed_data = []

        # Check for missing Pokémon in the cache
        processed_names = {p['name'] for p in processed_data}
        missing_pokemon = [name for name in pokemon_names if name.lower() not in processed_names]

        if missing_pokemon:
            await process_pokemon_data(missing_pokemon, processed_data)

        # Load the updated processed cache
        with open(PROCESSED_CACHE_FILE, 'r') as f:
            processed_data = json.load(f)

        matches = []
        for pokemon_name in pokemon_names:
            match = next((pokemon for pokemon in processed_data if pokemon_name.lower() == pokemon['name'].lower()), None)
            if match:
                matches.append(match)
            else:
                closest_matches = difflib.get_close_matches(pokemon_name.lower(), [p['name'] for p in processed_data])
                if closest_matches:
                    suggestions = ', '.join([f'<a href="#" onclick="selectSuggestion(\'{match}\')">{match.capitalize()}</a>' for match in closest_matches])
                    return jsonify({'error': f'Pokémon {pokemon_name} not found. Did you mean: {suggestions}'}), 404

        for match in matches:
            logger.info(f"Found match: {match}")

        return jsonify(matches)

    except Exception as e:
        logger.error(f"Error occurred: {e}", exc_info=True)
        return jsonify({'error': 'An error occurred while processing your request.'}), 500

@app.route('/api/pokemon/stats', methods=['GET'])
async def get_pokemon_stats():
    return await get_pokemon_info()

@app.route('/api/pokemon/suggestions', methods=['GET'])
async def get_suggestions():
    query = request.args.get('query', '').lower()
    if not query:
        return jsonify({'suggestions': []})

    with open(get_resource_path(CACHE_FILE), 'r') as f:
        all_pokemon_data = json.load(f)

    suggestions = [pokemon['name'] for pokemon in all_pokemon_data['results'] if query in pokemon['name'].lower()]
    return jsonify({'suggestions': suggestions[:10]})

@app.route('/api/pokemon/evolutions', methods=['GET'])
async def get_pokemon_evolutions():
    try:
        pokemon_name = request.args.get('name')
        if not pokemon_name:
            return jsonify({'error': 'No Pokémon name provided'}), 400

        async with aiohttp.ClientSession() as session:
            species_url = f"https://pokeapi.co/api/v2/pokemon-species/{pokemon_name.lower()}"
            species_data = await fetch(session, species_url)
            if not species_data:
                return jsonify({'error': 'Failed to fetch species data.'}), 500

            evolution_chain_url = species_data['evolution_chain']['url']
            evolution_chain_data = await fetch(session, evolution_chain_url)
            if not evolution_chain_data:
                return jsonify({'error': 'Failed to fetch evolution chain data.'}), 500

            logger.info(f"Evolution chain data: {evolution_chain_data}")

            evolutions = parse_evolution_chain(evolution_chain_data['chain'], pokemon_name.lower())

        return jsonify(evolutions)
    except Exception as e:
        logger.error(f"Error occurred: {e}", exc_info=True)
        return jsonify({'error': 'An error occurred while processing your request.'}), 500

def capitalize_pokemon_name(name):
    return ' '.join([word.capitalize() for word in name.split('-')])

def get_evolution_conditions(evolution_details):
    conditions = []
    for detail in evolution_details:
        condition = {}
        if detail.get('item'):
            condition['Item'] = detail['item']['name']
        if detail.get('trigger'):
            condition['Trigger'] = detail['trigger']['name']
        if detail.get('min_level') is not None:
            condition['Min Level'] = detail['min_level']
        if detail.get('time_of_day'):
            condition['Time of Day'] = detail['time_of_day']
        if detail.get('location'):
            condition['Location'] = detail['location']['name']
        if detail.get('held_item'):
            condition['Held Item'] = detail['held_item']['name']
        if detail.get('known_move'):
            condition['Known Move'] = detail['known_move']['name']
        if detail.get('known_move_type'):
            condition['Known Move Type'] = detail['known_move_type']['name']
        if detail.get('min_happiness') is not None:
            condition['Min Happiness'] = detail['min_happiness']
        if detail.get('min_beauty') is not None:
            condition['Min Beauty'] = detail['min_beauty']
        if detail.get('min_affection') is not None:
            condition['Min Affection'] = detail['min_affection']
        if detail.get('party_species'):
            condition['Party Species'] = detail['party_species']['name']
        if detail.get('party_type'):
            condition['Party Type'] = detail['party_type']['name']
        if detail.get('relative_physical_stats') is not None:
            condition['Relative Physical Stats'] = detail['relative_physical_stats']
        if detail.get('trade_species'):
            condition['Trade Species'] = detail['trade_species']['name']
        
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
        if not os.path.exists(CACHE_FILE):
            logger.error("CACHE_FILE not found. Make sure the cache file exists and is correctly formatted.")
            return

        with open(CACHE_FILE, 'r') as f:
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
