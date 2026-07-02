# PythonAnywhere-friendly profile cache shards

`data/pokemon_profile_details.json` can become very large after abilities and moves are cached.
PythonAnywhere's browser uploader has a 100 MiB upload limit, and loading one 200+ MB JSON file at Flask startup is also inefficient.

Version 1.24 supports a sharded runtime cache:

- `data/pokemon_profile_details_index.json` — small index/metadata file
- `data/profile_details_shards/*.json` — small profile shard files grouped by first character
- `data/pokemon_profile_details.json` — can be replaced with a tiny stub after sharding

The Flask app prefers the sharded cache automatically when the index exists.

## If you already built the large JSON locally

From the project folder, run:

```bash
python data/build_profile_details_cache.py --split-shards --strip-single-after-shards
python data/build_profile_details_cache.py --status
```

Then upload/deploy the project folder. The large single JSON will be replaced with a tiny stub, while the shard files remain local JSON files.

## If you are rebuilding abilities/moves from PokéAPI

```bash
python data/build_profile_details_cache.py --online --write-shards --strip-single-after-shards
```

Or through the all-in-one maintenance script:

```bash
python data/rebuild_all.py --online-profile-details
```

## PythonAnywhere upload notes

Zip the folder after sharding. The ZIP should be much smaller than the uncompressed JSON.
If the ZIP is still over PythonAnywhere's upload limit, split the ZIP into chunks and rejoin it in a PythonAnywhere Bash console.
