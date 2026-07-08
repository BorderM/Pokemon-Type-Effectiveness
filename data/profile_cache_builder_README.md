# Offline profile details cache

Runtime profile pages read `data/pokemon_profile_details.json` only. They do not call PokéAPI.

Build or refresh the full cache with:

```bash
python data/build_profile_details_cache.py --online
```

Check coverage without fetching:

```bash
python data/build_profile_details_cache.py --status
```

Retry only missing profiles:

```bash
python data/build_profile_details_cache.py --retry-missing
```

## Collapsed species with no base PokéAPI `/pokemon/{species}` endpoint

Some Pokémon are collapsed in this app for display but only exist as form/gender endpoints in PokéAPI. The builder now tries representative form endpoints automatically, for example:

- `frillish` -> `frillish-male`
- `jellicent` -> `jellicent-male`
- `pyroar` -> `pyroar-male`
- `meowstic` -> `meowstic-male`
- `mimikyu` -> `mimikyu-disguised`

It also has a dynamic fallback: if direct lookup fails, it checks `pokemon-species/{species}` and tries the varieties listed there.

The runtime app still displays the clean app name, such as `Frillish`, `Pyroar`, or `Mimikyu`.

## Move row deduplication

Moves are grouped by generation. Within a generation, rows are collapsed when the move name, learn method, and level are the same, even if PokéAPI lists the move in multiple version groups. The exact version group is intentionally treated as less important for the profile page.
