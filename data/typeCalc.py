import os, requests, json

# Ensure the data/ directory exists
os.makedirs("data", exist_ok=True)

types = [
    "normal","fire","water","electric","grass","ice","fighting",
    "poison","ground","flying","psychic","bug","rock","ghost",
    "dragon","dark","steel","fairy"
]

chart = {}
for t in types:
    r = requests.get(f"https://pokeapi.co/api/v2/type/{t}")
    r.raise_for_status()
    chart[t] = r.json()["damage_relations"]

with open("data/typechart.json", "w", encoding="utf-8") as f:
    json.dump(chart, f, indent=2)