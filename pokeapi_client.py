import requests
from pokebase import evolution_chain
from config import POKEAPI_BASE_URL

def fetch_form_metadata(form_name):
    """
    Fetch form metadata (form_name, sprite_url) via PokeAPI.
    Tries /pokemon-form; if 404, falls back to /pokemon; if still fails, returns defaults.
    """
    try:
        url = f"{POKEAPI_BASE_URL}/pokemon-form/{form_name}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return {
            'form_name': data.get('form_name') or '',
            'sprite_url': data.get('sprites', {}).get('front_default')
        }
    except Exception:
        pass
    try:
        url = f"{POKEAPI_BASE_URL}/pokemon/{form_name}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return {
            'form_name': '',
            'sprite_url': data.get('sprites', {}).get('front_default')
        }
    except Exception:
        return {'form_name': '', 'sprite_url': None}

def fetch_evolution_chain(chain_id):
    """Fetch an EvolutionChain by its ID."""
    return evolution_chain(chain_id)


def flatten_chain(chain_link):
    """
    Walk evolution chain recursively to produce a list of edges.
    Supports fields: trigger, min_level, item, min_happiness, min_beauty,
    gender, time_of_day, location, held_item, known_move, known_move_type,
    party_species, party_type, relative_physical_stats, trade_species.
    """
    edges = []
    base = chain_link.species.name
    gender_map = {1: 'female', 2: 'male'}
    for evo in chain_link.evolves_to:
        target = evo.species.name
        for d in evo.evolution_details:
            edges.append({
                'from': base,
                'to': target,
                'trigger': d.trigger.name if d.trigger else None,
                'min_level': d.min_level,
                'item': getattr(d.item, 'name', None),
                'min_happiness': d.min_happiness,
                'min_beauty': d.min_beauty,
                'gender': gender_map.get(d.gender),
                'time_of_day': d.time_of_day or None,
                'location': getattr(d.location, 'name', None),
                'held_item': getattr(d.held_item, 'name', None),
                'known_move': getattr(getattr(d, 'known_move', None), 'name', None),
                'known_move_type': getattr(getattr(d, 'known_move_type', None), 'name', None),
                'party_species': getattr(getattr(d, 'party_species', None), 'name', None),
                'party_type': getattr(getattr(d, 'party_type', None), 'name', None),
                'relative_physical_stats': d.relative_physical_stats,
                'trade_species': getattr(getattr(d, 'trade_species', None), 'name', None)
            })
        edges.extend(flatten_chain(evo))
    return edges