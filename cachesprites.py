# download_sprites.py (corrected to use pokemon_cache.json)
import os
import json
import requests

SPRITE_DIR = "sprites"
CACHE_FILE = "pokemon_cache.json"
BASE_URL = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/"

os.makedirs(SPRITE_DIR, exist_ok=True)

with open(CACHE_FILE, "r") as f:
    pokemon_data = json.load(f)
    pokemon_list = pokemon_data["results"]

for pokemon in pokemon_list:
    name = pokemon["name"]
    url = pokemon["url"]  # e.g., "https://pokeapi.co/api/v2/pokemon/1/"
    
    try:
        poke_id = url.strip("/").split("/")[-1]
        sprite_url = f"{BASE_URL}{poke_id}.png"
        dest_path = os.path.join(SPRITE_DIR, f"{name}.png")

        if os.path.exists(dest_path):
            continue

        resp = requests.get(sprite_url)
        if resp.status_code == 200:
            with open(dest_path, "wb") as f_out:
                f_out.write(resp.content)
            print(f"Saved: {name} ({poke_id})")
        else:
            print(f"Failed to fetch sprite for {name} (HTTP {resp.status_code})")
    except Exception as e:
        print(f"Error downloading {name}: {e}")
