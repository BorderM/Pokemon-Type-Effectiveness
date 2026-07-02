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
import traceback

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

TYPECHART_PATH = get_resource_path("static","typechart.json")
with open(TYPECHART_PATH, encoding="utf-8") as f:
    TYPE_CHART = json.load(f)

FORM_REFERENCE_PATHS = [
    get_resource_path("data", "form_reference.json"),
    get_resource_path("static", "form_reference.json"),
]
FORM_REFERENCE = {}
for _path in FORM_REFERENCE_PATHS:
    if os.path.exists(_path):
        with open(_path, encoding="utf-8") as f:
            FORM_REFERENCE = json.load(f)
        break

def _slug_alias(value: str) -> str:
    return (value or "").strip().lower().replace("_", "-").replace(".", "").replace(":", "").replace("'", "").replace("♀", "-f").replace("♂", "-m").replace(" ", "-")

def _display_alias(value: str) -> str:
    return (value or "").strip().lower().replace("_", " ").replace("-", " ").replace(".", "").replace(":", "").replace("'", "").replace("♀", " f").replace("♂", " m")

def _expanded_alias_values(value, species_display=None):
    if not value:
        return set()
    vals = {value}
    # A display such as "Pumpkaboo Average Size / Medium Variety" should also
    # resolve from "Pumpkaboo Average Size" and "Pumpkaboo Medium Variety".
    if "/" in value:
        parts = [p.strip() for p in value.split("/") if p.strip()]
        vals.update(parts)
        if species_display:
            for part in parts:
                if not part.lower().startswith(species_display.lower()):
                    vals.add(f"{species_display} {part}")
    return vals

def _build_aliases():
    aliases = {"types": {}, "stats": {}, "evolutions": {}}
    for key, meta in FORM_REFERENCE.items():
        p = FORM_BY_KEY.get(key, {})
        base_values = {
            key,
            key.replace("-", " "),
            meta.get("raw_display"),
            meta.get("form_display"),
            meta.get("species_display"),
            p.get("display_name"),
        }
        species_display = meta.get("species_display")
        values = set()
        for value in base_values:
            values.update(_expanded_alias_values(value, species_display))

        for context, key_field, display_field in (
            ("types", "type_key", "type_display"),
            ("stats", "stats_key", "stats_display"),
        ):
            target = meta.get(key_field) or key
            context_values = set(values)
            context_values.update(_expanded_alias_values(meta.get(display_field), species_display))
            for value in context_values:
                if not value:
                    continue
                aliases[context].setdefault(_slug_alias(value), target)
                aliases[context].setdefault(_display_alias(value), target)
        for value in values:
            if not value:
                continue
            aliases["evolutions"].setdefault(_slug_alias(value), key)
            aliases["evolutions"].setdefault(_display_alias(value), key)
    return aliases

FORM_ALIASES = _build_aliases()


# ─── PROFILE / POKÉDEX DETAIL HELPERS ─────────────────────────────────
# Runtime profile pages are intentionally offline/local-file only.
# To refresh abilities and moves, run:
#   python data/build_profile_details_cache.py --online
# or:
#   python data/rebuild_all.py --online-profile-details
PROFILE_DETAILS_INDEX_PATH = get_resource_path('data', 'pokemon_profile_details_index.json')
PROFILE_DETAILS_SHARDS_DIR = get_resource_path('data', 'profile_details_shards')
PROFILE_DETAILS_CACHE_PATHS = [
    get_resource_path('data', 'pokemon_profile_details.json'),
    get_resource_path('data', 'pokemon_details_cache.json'),  # legacy fallback
]

VERSION_GROUP_GENERATIONS = {
    'red-blue': 'Generation I', 'yellow': 'Generation I',
    'gold-silver': 'Generation II', 'crystal': 'Generation II',
    'ruby-sapphire': 'Generation III', 'emerald': 'Generation III',
    'firered-leafgreen': 'Generation III', 'colosseum': 'Generation III', 'xd': 'Generation III',
    'diamond-pearl': 'Generation IV', 'platinum': 'Generation IV', 'heartgold-soulsilver': 'Generation IV',
    'black-white': 'Generation V', 'black-2-white-2': 'Generation V',
    'x-y': 'Generation VI', 'omega-ruby-alpha-sapphire': 'Generation VI',
    'sun-moon': 'Generation VII', 'ultra-sun-ultra-moon': 'Generation VII', 'lets-go-pikachu-lets-go-eevee': 'Generation VII',
    'sword-shield': 'Generation VIII', 'brilliant-diamond-and-shining-pearl': 'Generation VIII', 'legends-arceus': 'Generation VIII',
    'scarlet-violet': 'Generation IX',
}
GENERATION_ORDER = [
    'Generation IX', 'Generation VIII', 'Generation VII', 'Generation VI', 'Generation V',
    'Generation IV', 'Generation III', 'Generation II', 'Generation I', 'Other'
]
METHOD_DISPLAY = {
    'level-up': 'Level Up', 'machine': 'TM/TR/HM', 'egg': 'Egg', 'tutor': 'Tutor',
    'stadium-surfing-pikachu': 'Special', 'light-ball-egg': 'Egg', 'colosseum-purification': 'Purification',
    'xd-shadow': 'XD Shadow', 'xd-purification': 'Purification', 'form-change': 'Form Change',
    'zygarde-cube': 'Zygarde Cube'
}

_PROFILE_DETAILS_CACHE = None
_PROFILE_DETAILS_CACHE_PATH = None
_PROFILE_DETAILS_SHARD_CACHE = {}


def _profile_shard_id(key):
    value = (key or '').strip().lower()
    if not value:
        return 'other'
    first = value[0]
    return first if first.isalnum() else 'other'


def _read_json_file(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def load_profile_details_cache(force=False):
    """Load summarized local ability/move metadata. Never performs network calls.

    Preferred runtime format is a small index file plus profile shard JSON files
    under data/profile_details_shards/. This avoids loading a 200MB details file
    at Flask startup on PythonAnywhere.
    """
    global _PROFILE_DETAILS_CACHE, _PROFILE_DETAILS_CACHE_PATH, _PROFILE_DETAILS_SHARD_CACHE
    if force:
        _PROFILE_DETAILS_CACHE = None
        _PROFILE_DETAILS_CACHE_PATH = None
        _PROFILE_DETAILS_SHARD_CACHE = {}
    if _PROFILE_DETAILS_CACHE is not None:
        return _PROFILE_DETAILS_CACHE

    # Preferred v1.24 sharded runtime cache.
    if os.path.exists(PROFILE_DETAILS_INDEX_PATH):
        index_data = _read_json_file(PROFILE_DETAILS_INDEX_PATH)
        if isinstance(index_data, dict) and isinstance(index_data.get('key_to_shard'), dict):
            _PROFILE_DETAILS_CACHE = index_data
            _PROFILE_DETAILS_CACHE['sharded'] = True
            _PROFILE_DETAILS_CACHE_PATH = PROFILE_DETAILS_INDEX_PATH
            return _PROFILE_DETAILS_CACHE

    # Legacy/single-file cache fallback.
    for path in PROFILE_DETAILS_CACHE_PATHS:
        if not os.path.exists(path):
            continue
        data = _read_json_file(path)
        if not isinstance(data, dict):
            continue
        # Preferred v1.16-v1.23 schema.
        if isinstance(data.get('profiles'), dict):
            _PROFILE_DETAILS_CACHE = data
            _PROFILE_DETAILS_CACHE['sharded'] = False
            _PROFILE_DETAILS_CACHE_PATH = path
            return data
        # Legacy cache format was raw PokéAPI buckets. Do not use it at runtime,
        # but keep metadata so the UI can explain that a rebuild is needed.
        if 'pokemon' in data or 'ability' in data:
            _PROFILE_DETAILS_CACHE = {
                'schema_version': 'legacy-raw-pokeapi-cache',
                'profiles': {},
                'legacy_buckets_present': sorted(data.keys()),
                'source_path': path,
                'sharded': False,
            }
            _PROFILE_DETAILS_CACHE_PATH = path
            return _PROFILE_DETAILS_CACHE

    _PROFILE_DETAILS_CACHE = {'schema_version': 'missing', 'profiles': {}, 'sharded': False}
    _PROFILE_DETAILS_CACHE_PATH = None
    return _PROFILE_DETAILS_CACHE


def _load_profile_details_shard(shard_id):
    shard_id = shard_id or 'other'
    if shard_id in _PROFILE_DETAILS_SHARD_CACHE:
        return _PROFILE_DETAILS_SHARD_CACHE[shard_id]
    path = os.path.join(PROFILE_DETAILS_SHARDS_DIR, f'{shard_id}.json')
    data = _read_json_file(path)
    profiles = data.get('profiles', {}) if isinstance(data, dict) else {}
    if not isinstance(profiles, dict):
        profiles = {}
    _PROFILE_DETAILS_SHARD_CACHE[shard_id] = profiles
    return profiles


def get_local_profile_details(key, species=None):
    cache = load_profile_details_cache()
    lookup_keys = []
    for candidate in (key, species):
        if candidate and candidate not in lookup_keys:
            lookup_keys.append(candidate)
    meta = FORM_REFERENCE.get(key, {})
    for candidate in (meta.get('stats_key'), meta.get('type_key')):
        if candidate and candidate not in lookup_keys:
            lookup_keys.append(candidate)

    # Sharded runtime cache: load only the small shard needed for the requested Pokémon.
    if isinstance(cache, dict) and cache.get('sharded'):
        key_to_shard = cache.get('key_to_shard') or {}
        for candidate in lookup_keys:
            shard_id = key_to_shard.get(candidate) or _profile_shard_id(candidate)
            profiles = _load_profile_details_shard(shard_id)
            details = profiles.get(candidate)
            if details:
                return details, cache
        return {}, cache

    profiles = cache.get('profiles') if isinstance(cache, dict) else {}
    if not isinstance(profiles, dict):
        return {}, cache

    for candidate in lookup_keys:
        details = profiles.get(candidate)
        if details:
            return details, cache
    return {}, cache


def get_local_profile_details_exact(key):
    """Return profile details for an exact app key only.

    The Pokédex profile page uses this for move lists so alternate forms do not
    accidentally inherit another form's learnset. Ability display can still use
    the broader fallback helper because many alternate forms intentionally share
    base-form abilities.
    """
    cache = load_profile_details_cache()
    candidate = (key or '').strip().lower()
    if not candidate:
        return {}, cache

    if isinstance(cache, dict) and cache.get('sharded'):
        key_to_shard = cache.get('key_to_shard') or {}
        shard_id = key_to_shard.get(candidate) or _profile_shard_id(candidate)
        profiles = _load_profile_details_shard(shard_id)
        return profiles.get(candidate) or {}, cache

    profiles = cache.get('profiles') if isinstance(cache, dict) else {}
    if not isinstance(profiles, dict):
        return {}, cache
    return profiles.get(candidate) or {}, cache


def _abilities_signature(abilities):
    if not abilities:
        return tuple()
    return tuple(sorted((a.get('key') or a.get('name') or '').lower() for a in abilities if isinstance(a, dict)))


def choose_profile_abilities(key, species, exact_details):
    """Use exact-form abilities when present, otherwise fall back to base species.

    This is helpful for alternate forms whose PokéAPI endpoint is missing from an
    older local cache or whose form-specific ability data was intentionally
    collapsed. Moves remain exact-form only.
    """
    exact_abilities = exact_details.get('abilities', []) if isinstance(exact_details, dict) else []
    if exact_abilities:
        return exact_abilities

    fallback_details, _meta = get_local_profile_details(species or key, species)
    fallback_abilities = fallback_details.get('abilities', []) if isinstance(fallback_details, dict) else []
    return fallback_abilities or []

def clean_label(value):
    return (value or '').replace('-', ' ').replace('_', ' ').title()


def get_species_forms(species):
    forms = []
    seen = set()
    for form_key in FORMS_BY_BASE.get(species, []):
        form = FORM_BY_KEY.get(form_key, {})
        meta = FORM_REFERENCE.get(form_key, {})
        display = meta.get('raw_display') or form.get('display_name') or clean_label(form_key)
        if display in seen:
            continue
        seen.add(display)
        forms.append({
            'key': form_key,
            'display_name': display,
            'types': form.get('types', []),
            'stats': form.get('stats', {}),
            'sprite_url': get_available_sprite_url(form_key),
            'sprite_candidates': get_sprite_candidates(form_key),
        })
    return sorted(forms, key=lambda x: (x['display_name'].lower(), x['key']))


def build_evolution_chain(root_key):
    key = resolve_form_key(root_key, context='evolutions') or root_key
    if key not in FORM_BY_KEY:
        return []

    def find_chain_root(name):
        candidate = resolve_form_key(name, context='evolutions') or name
        guard = 0
        while guard < 30:
            parent = next((e for e in EVOLUTIONS if e['to'] == candidate), None)
            if not parent:
                return candidate
            candidate = resolve_form_key(parent['from'], context='evolutions') or parent['from']
            guard += 1
        return candidate

    root = find_chain_root(key)
    chain = []

    def trav(name, frm=None):
        if name not in FORM_BY_KEY:
            return
        meta = FORM_REFERENCE.get(name, {})
        node = {
            'name': name,
            'parent_key': frm,
            'display_name': get_evolution_display_name(name),
            'sprite_url': get_available_sprite_url(name),
            'sprite_candidates': get_sprite_candidates(name),
            'evolves_from': get_evolution_display_name(frm) if frm else None,
            'bulbapedia_page': meta.get('bulbapedia_page'),
            'bulbapedia_url': meta.get('bulbapedia_url'),
            'evolution_conditions': []
        }
        if frm:
            edge = next((e for e in EVOLUTIONS if e['from'] == frm and e['to'] == name), None)
            notes = []
            if edge:
                node['evolution_conditions'] = get_evolution_conditions([edge])
                if edge.get('note'):
                    notes.append(edge['note'])
            if name in EVOLUTION_FORM_NOTES:
                notes.append(EVOLUTION_FORM_NOTES[name])
            if notes:
                node['note'] = ' '.join(notes)
        elif name in EVOLUTION_FORM_NOTES:
            node['note'] = EVOLUTION_FORM_NOTES[name]
        chain.append(node)
        for e in get_direct_evolutions(name):
            child = resolve_form_key(e['to'], context='evolutions') or e['to']
            trav(child, name)

    trav(root)
    return chain


def load_form_notes():
    path = get_resource_path('data', 'form_notes.json')
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def get_profile_payload(raw_name):
    raw_slug = _slug_alias(raw_name)
    raw_lower = (raw_name or '').strip().lower()
    # A profile page should preserve an exact form when the URL/search gives one.
    # Context pages can collapse forms, but the Pokédex should still allow deep links
    # such as /pokemon/toxtricity-low-key or /pokemon/pumpkaboo-small.
    if raw_lower in FORM_BY_KEY:
        key = raw_lower
    elif raw_slug in FORM_BY_KEY:
        key = raw_slug
    else:
        key = resolve_form_key(raw_name, context='stats') or resolve_form_key(raw_name, context='types') or resolve_form_key(raw_name, context='evolutions') or raw_slug
    if key not in FORM_BY_KEY:
        return None
    p = FORM_BY_KEY[key]
    species = p.get('species') or key
    meta = FORM_REFERENCE.get(key, {})
    display_name = meta.get('raw_display') or p.get('display_name') or clean_label(key)
    type_meta = get_form_meta(key, context='types')
    stats_meta = get_form_meta(key, context='stats')
    form_notes = load_form_notes()
    notes = []
    for note_key in (key, species):
        note = form_notes.get(note_key)
        if note:
            if isinstance(note, list):
                notes.extend(note)
            else:
                notes.append(note)

    exact_profile_details, profile_cache_meta = get_local_profile_details_exact(key)
    fallback_profile_details, fallback_profile_cache_meta = get_local_profile_details(key, species)
    if not isinstance(profile_cache_meta, dict) or not profile_cache_meta.get('schema_version'):
        profile_cache_meta = fallback_profile_cache_meta

    # Abilities are allowed to fall back to the base/collapsed species if an
    # alternate form has no specific cached ability data. Moves are intentionally
    # exact-form only so forms do not inherit variant learnsets by accident.
    abilities = choose_profile_abilities(key, species, exact_profile_details)
    moves_by_generation = exact_profile_details.get('moves_by_generation', {}) if isinstance(exact_profile_details, dict) else {}

    return {
        'key': key,
        'species': species,
        'display_name': display_name,
        'species_display': meta.get('species_display') or clean_label(species),
        'sprite_url': get_available_sprite_url(key),
        'sprite_candidates': get_sprite_candidates(key),
        'types': p.get('types', []),
        'effectiveness': p.get('effectiveness', {}),
        'stats': p.get('stats', {}),
        'type_lookup_key': type_meta.get('context_key'),
        'stats_lookup_key': stats_meta.get('context_key'),
        'bulbapedia_page': meta.get('bulbapedia_page'),
        'bulbapedia_url': meta.get('bulbapedia_url'),
        'forms': get_species_forms(species),
        'form_notes': notes,
        'abilities': abilities,
        'moves_by_generation': moves_by_generation,
        'move_generations': [g for g in GENERATION_ORDER if g in moves_by_generation] + sorted([g for g in moves_by_generation if g not in GENERATION_ORDER]),
        'evolution_family': build_evolution_chain(key),
        'data_sources': {
            'local_cache': True,
            'offline_profile_details': bool(exact_profile_details or fallback_profile_details),
            'exact_profile_details': bool(exact_profile_details),
            'ability_fallback_used': bool(abilities and not (exact_profile_details.get('abilities') if isinstance(exact_profile_details, dict) else [])),
            'profile_details_schema': profile_cache_meta.get('schema_version') if isinstance(profile_cache_meta, dict) else None,
            'profile_details_generated_at': profile_cache_meta.get('generated_at') if isinstance(profile_cache_meta, dict) else None,
            'profile_details_path': os.path.basename(_PROFILE_DETAILS_CACHE_PATH) if _PROFILE_DETAILS_CACHE_PATH else None,
        }
    }

# ─── FORM RESOLUTION ───────────────────────────────────────────────────
def resolve_form_key(raw, context=None):
    if not raw:
        return None
    context = context if context in {"types", "stats", "evolutions"} else None
    k = raw.strip().lower()

    if context and k in FORM_REFERENCE:
        meta = FORM_REFERENCE[k]
        prefix = 'type' if context == 'types' else 'stats' if context == 'stats' else context
        return meta.get(f"{prefix}_key") or k

    if k in FORM_BY_KEY:
        return k

    if context:
        alias_map = FORM_ALIASES.get(context, {})
        resolved = alias_map.get(_slug_alias(k)) or alias_map.get(_display_alias(k))
        if resolved:
            return resolved

    if k in FORM_COLLAPSE_MAP:
        return FORM_COLLAPSE_MAP[k][0]
    if '-' in k:
        base, suf = k.split('-',1)
        if base in FORMS_BY_BASE and suf in SUFFIXES:
            return base
    return None


EVOLUTION_DISPLAY_OVERRIDES = {
    "darmanitan-standard": "Darmanitan",
    "darmanitan-zen": "Darmanitan",
    "darmanitan-galar-standard": "Galarian Darmanitan",
    "darmanitan-galar-zen": "Galarian Darmanitan",
    "darumaka-galar": "Galarian Darumaka",
    # Palafin evolves into its default/Zero Form. Hero Form is an in-battle
    # transformation via Zero to Hero, so the evolution card should display
    # the species name rather than treating Hero Form as a separate evolution.
    "palafin-zero": "Palafin",
    "palafin-hero": "Palafin",
    "oinkologne-male": "Oinkologne",
    "oinkologne-female": "Oinkologne",
    "maushold-family-of-four": "Maushold",
    "maushold-family-of-three": "Maushold",
}

EVOLUTION_FORM_NOTES = {
    "palafin-zero": "Hero Form is activated in battle via Zero to Hero; it is not a separate evolution.",
}

EVOLUTION_DEDUPE_KEYS = {
    "oinkologne-female": "oinkologne",
    "oinkologne-male": "oinkologne",
    "maushold-family-of-three": "maushold",
    "maushold-family-of-four": "maushold",
}

def get_evolution_display_name(key: str) -> str:
    if not key:
        return ""
    if key in EVOLUTION_DISPLAY_OVERRIDES:
        return EVOLUTION_DISPLAY_OVERRIDES[key]
    meta = FORM_REFERENCE.get(key, {})
    form = FORM_BY_KEY.get(key, {})
    return meta.get('raw_display') or form.get('display_name') or key.replace('-', ' ').title()

def get_evolution_dedupe_key(edge: dict) -> str:
    target = edge.get('to')
    return EVOLUTION_DEDUPE_KEYS.get(target, target)

def static_sprite_exists(sprite_url: str) -> bool:
    if not sprite_url or not sprite_url.startswith('/static/sprites/'):
        return False
    filename = os.path.basename(sprite_url)
    return os.path.exists(get_resource_path('static', 'sprites', filename))

def get_sprite_candidates(key: str) -> list:
    """Return ordered local sprite URLs for a Pokémon form.

    The first value is the best display sprite. Later values are safe browser-side
    fallbacks. This protects niche form keys whose cache sprite URL may not exist
    in a local sprite export, such as palafin-zero -> palafin.png.
    """
    form = FORM_BY_KEY.get(key, {})
    species = form.get('species') or (key.split('-', 1)[0] if key else '')

    candidates = []
    if form.get('sprite_url'):
        candidates.append(form['sprite_url'])
    if key:
        candidates.append(f'/static/sprites/{key}.png')
    if species:
        candidates.append(f'/static/sprites/{species}.png')
        sibling_keys = sorted(
            FORMS_BY_BASE.get(species, []),
            key=lambda k: (
                'gmax' in k,
                'totem' in k,
                'starter' in k,
                len(k),
                k,
            )
        )
        for sibling in sibling_keys:
            sibling_sprite = FORM_BY_KEY.get(sibling, {}).get('sprite_url')
            if sibling_sprite:
                candidates.append(sibling_sprite)
            candidates.append(f'/static/sprites/{sibling}.png')

    existing = []
    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        if static_sprite_exists(candidate):
            existing.append(candidate)

    if existing:
        return existing

    # Last-resort fallback: keep a deterministic URL so deployments with a
    # different sprite set still have a chance to resolve the image.
    fallback = form.get('sprite_url') or (f'/static/sprites/{key}.png' if key else '')
    return [fallback] if fallback else []

def get_available_sprite_url(key: str) -> str:
    candidates = get_sprite_candidates(key)
    return candidates[0] if candidates else ''

def get_form_meta(key: str, context: str = "types"):
    meta = FORM_REFERENCE.get(key, {})
    prefix = "type" if context == "types" else "stats" if context == "stats" else "type"
    return {
        "context": context,
        "context_key": meta.get(f"{prefix}_key", key),
        "context_display": meta.get(f"{prefix}_display") or meta.get("raw_display") or FORM_BY_KEY.get(key, {}).get("display_name", key),
        "bulbapedia_page": meta.get("bulbapedia_page"),
        "bulbapedia_url": meta.get("bulbapedia_url"),
    }

def normalize_form(name):
    # Kept for compatibility with older evolution/template code.
    if name.startswith('wormadam-'):
        return 'wormadam'
    if name.startswith('gourgeist-'):
        return 'gourgeist'
    if name.startswith('pumpkaboo-'):
        return 'pumpkaboo'
    if name.startswith('basculin-'):
        return 'basculin'
    return name

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
    seen_dedupe_keys = set()
    for lst in by_sp.values():
        # For the evolution page, cosmetic same-species outcomes such as
        # Oinkologne gender and Maushold family size should remain one card,
        # while truly different evolution branches like Urshifu forms remain split.
        if len(lst) == 1:
            result.append(lst[0])
            continue
        for edge in lst:
            dedupe_key = get_evolution_dedupe_key(edge)
            if dedupe_key in seen_dedupe_keys:
                continue
            seen_dedupe_keys.add(dedupe_key)
            result.append(edge)
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


@app.route('/pokedex')
@app.route('/pokemon')
def page_pokedex():
    return render_template('pokemonprofile.html', initial_name=request.args.get('name', ''))

@app.route('/pokemon/<name>')
def page_pokemon_profile(name):
    return render_template('pokemonprofile.html', initial_name=name)

@app.route('/typeeffectiveness')
def page_type_effectiveness():
    return render_template('pokemontypeeffectiveness.html',
        collapse_map=json.dumps(FORM_COLLAPSE_MAP),
        forms_by_base_json=json.dumps(FORMS_BY_BASE),
        initial_name=request.args.get('name', '')
    )

@app.route('/stats')
def page_stats():
    return render_template('pokemonstats.html',
        collapse_map=json.dumps(FORM_COLLAPSE_MAP),
        forms_by_base_json=json.dumps(FORMS_BY_BASE),
        initial_name=request.args.get('name', '')
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
    context = request.args.get('context')
    if context not in {'types', 'stats'}:
        context = 'stats' if request.path.endswith('/stats') else 'types'

    real = resolve_form_key(raw, context=context)
    if not real:
        return jsonify({'error': 'Pokémon not found. Please check the name or select a suggestion.'}), 404

    proc = get_resource_path('processed_pokemon_cache.json')
    processed = json.load(open(proc))
    if real not in {p['name'] for p in processed}:
        await process_pokemon_data([real], processed)
        json.dump(processed, open(proc,'w'), indent=2)

    p = next((x for x in processed if x['name']==real),None)
    if not p:
        return jsonify({'error':'Not found'}),404

    result = dict(p)
    result.update(get_form_meta(real, context=context))
    result['lookup_key'] = result['context_key']
    result['display_name'] = result['context_display']
    return jsonify([result])

@app.route('/api/pokemon/suggestions')
def suggestions():
    q = request.args.get('query','').strip()
    context = request.args.get('context', '').lower()
    limit = int(request.args.get('limit', 15) or 15)

    if context in {'types', 'stats'} and FORM_REFERENCE:
        prefix = 'type' if context == 'types' else 'stats'
        q_slug = _slug_alias(q)
        q_display = _display_alias(q)
        seen = set()
        matches = []

        for raw_key, meta in FORM_REFERENCE.items():
            if not meta.get('searchable', True):
                continue
            p = FORM_BY_KEY.get(raw_key, {})
            key = meta.get(f'{prefix}_key') or raw_key
            display = meta.get(f'{prefix}_display') or p.get('display_name') or raw_key
            haystacks = [
                raw_key, raw_key.replace('-', ' '),
                p.get('display_name', ''),
                meta.get('raw_display', ''),
                meta.get('form_display', ''),
                meta.get('species_display', ''),
                display, key,
            ]
            if q_slug and not any(q_slug in _slug_alias(h) or q_display in _display_alias(h) for h in haystacks):
                continue
            unique = (key, display)
            if unique in seen:
                continue
            seen.add(unique)
            rank = (
                0 if _slug_alias(display) == q_slug or _display_alias(display) == q_display else
                1 if _slug_alias(display).startswith(q_slug) or _display_alias(display).startswith(q_display) else
                2 if _slug_alias(key).startswith(q_slug) else
                3
            )
            matches.append((rank, display, {
                'display': display,
                'key': key,
                'bulbapedia_page': meta.get('bulbapedia_page'),
                'bulbapedia_url': meta.get('bulbapedia_url'),
            }))

        matches.sort(key=lambda item: (item[0], item[1]))
        return jsonify(suggestions=[m[2] for m in matches[:limit]])

    # Legacy/default path, used by the evolutions page.
    q_lower = q.lower()
    raw = [k for k,v in FORM_BY_KEY.items()
           if q_lower in v['display_name'].lower() or q_lower in k]

    buckets = defaultdict(list)
    for form_key in raw:
        base = resolve_form_key(form_key) or form_key
        buckets[base].append(form_key)

    suggestions = []
    for base, forms in buckets.items():
        rep = next((f for f in forms if get_direct_evolutions(f)), forms[0])
        meta = FORM_REFERENCE.get(rep, {})
        suggestions.append({
            'display': meta.get('species_display') or FORM_BY_KEY[rep]['display_name'],
            'key': rep,
            'bulbapedia_page': meta.get('bulbapedia_page'),
            'bulbapedia_url': meta.get('bulbapedia_url'),
        })

    return jsonify(suggestions=suggestions[:limit])

@app.route('/api/pokemon/evolutions')
def api_evo():
    raw = request.args.get('name','').lower().strip()
    return jsonify(build_evolution_chain(raw))

@app.route('/api/pokemon/profile')
def api_pokemon_profile():
    raw = request.args.get('name','').strip()
    if not raw:
        return jsonify({'error': 'name is required'}), 400
    payload = get_profile_payload(raw)
    if not payload:
        return jsonify({'error': 'Pokémon not found. Please check the name or select a suggestion.'}), 404
    return jsonify(payload)

@app.route('/api/typeeffectiveness')
def api_typeeffectiveness():
    t1 = request.args.get('type1', '').lower().strip()
    t2 = request.args.get('type2', '').lower().strip()

    if not t1:
        return jsonify({ 'error': 'type1 is required' }), 400

    try:
        data_list = [TYPE_CHART[t1]]
        if t2:
            data_list.append(TYPE_CHART[t2])

        result = calculate_type_effectiveness(data_list)
        return jsonify(result)

    except KeyError as e:
        return jsonify({ 'error': f'Unknown type: {e.args[0].capitalize()}.' }), 404

    except Exception as e:
        # Log the traceback to help debug
        print(traceback.format_exc())
        return jsonify({ 'error': 'Internal server error' }), 500


asgi_app = WsgiToAsgi(app)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
