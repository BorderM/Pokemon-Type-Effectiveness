# Pokédex Profile Data

The profile page is **offline-first**. Normal app requests do not call PokéAPI.

Runtime sources:

- `processed_pokemon_cache.json` for names, forms, sprites, stats, types, and type effectiveness
- `data/evolutions.json` for evolution families
- `data/form_reference.json` for display/collapse/link handling
- `data/form_notes.json` for manual form/gameplay notes
- `data/pokemon_profile_details.json` for abilities and moves by generation

## Building ability and move data

Run this manually when you want to refresh abilities and move learnsets:

```bash
python data/build_profile_details_cache.py --online
```

For a quick test:

```bash
python data/build_profile_details_cache.py --online --limit 25
```

For one or more Pokémon:

```bash
python data/build_profile_details_cache.py --online --only palafin-zero charizard pumpkaboo-average
```

After the script finishes, deploy the generated `data/pokemon_profile_details.json` with the rest of the app. PythonAnywhere will then serve profile pages from local JSON only.

## Full local maintenance workflow

```bash
python data/rebuild_all.py --online-profile-details
```

Offline-safe maintenance only:

```bash
python data/rebuild_all.py
```

This regenerates form references, repairs sprite aliases, and verifies local evolution data without fetching profile details.

## Why this is local-first

Fetching PokéAPI live during each profile view can be slow and unreliable on hosted environments. The local cache approach makes the app faster and lets it continue working even if external APIs are down.
