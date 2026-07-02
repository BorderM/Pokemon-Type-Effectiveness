# Version 1.24 notes

This patch keeps version 1.22 as the gameplay/data base and adds PythonAnywhere-friendly profile cache sharding.

## Added

- `data/pokemon_profile_details_index.json` support
- `data/profile_details_shards/*.json` support
- Lazy shard loading in `app.py`
- `python data/build_profile_details_cache.py --split-shards`
- `python data/build_profile_details_cache.py --write-shards`
- `python data/build_profile_details_cache.py --strip-single-after-shards`
- `data/profile_cache_shards_README.md`

## Why

The full abilities/moves cache can exceed 200 MB uncompressed. Sharding avoids PythonAnywhere's browser upload size issue and prevents Flask from loading the entire profile cache at startup.
