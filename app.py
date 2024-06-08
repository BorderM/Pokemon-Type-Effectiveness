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

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

app = Flask(__name__, template_folder='templates')

CACHE_FILE = 'pokemon_cache.json'
PROCESSED_CACHE_FILE = 'processed_pokemon_cache.json'
REQUEST_TIMEOUT = 10  # seconds

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
    return render_template('Pokemon Type Effectiveness.html')

@app.route('/api/pokemon', methods=['GET'])
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
                    suggestions = ', '.join([f'<a href="#" onclick="suggestPokemon(\'{match}\')">{match.capitalize()}</a>' for match in closest_matches])
                    return jsonify({'error': f'Pokémon {pokemon_name} not found. Did you mean: {suggestions}'}), 404

        for match in matches:
            logger.info(f"Found match: {match}")

        return jsonify(matches)

    except Exception as e:
        logger.error(f"Error occurred: {e}", exc_info=True)
        return jsonify({'error': 'An error occurred while processing your request.'}), 500

@app.route('/api/suggestions', methods=['GET'])
async def get_suggestions():
    query = request.args.get('query', '').lower()
    if not query:
        return jsonify({'suggestions': []})

    with open(CACHE_FILE, 'r') as f:
        all_pokemon_data = json.load(f)

    suggestions = [pokemon['name'] for pokemon in all_pokemon_data['results'] if query in pokemon['name'].lower()]
    return jsonify({'suggestions': suggestions[:10]})

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

                processed_data.append({
                    'name': variety_data['name'],
                    'display_name': variety['pokemon']['name'].capitalize(),
                    'form': variety['pokemon']['name'],
                    'id': variety_data['id'],
                    'types': type_names,
                    'effectiveness': effectiveness
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

if __name__ == '__main__':
    try:
        logger.info("Starting Flask server...")
        app.run(debug=True)
    except Exception as e:
        logger.error(f"Fatal error occurred: {e}", exc_info=True)
        input("Press Enter to exit...")
