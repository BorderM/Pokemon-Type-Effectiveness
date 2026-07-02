# Pokemon typing version 1.29 - full project bundle

This bundle contains the full app code and normal local JSON/assets available in patch 1.29.

## Important: profile details shards

The app supports the offline sharded profile cache introduced in version 1.24. The actual generated shard data is not included here unless you copy it in from your local/PythonAnywhere deployment.

For a complete offline repository, make sure these exist:

```text
data/pokemon_profile_details_index.json
data/profile_details_shards/*.json
```

If you still have the large `data/pokemon_profile_details.json`, generate shards with:

```bash
python data/build_profile_details_cache.py --split-shards --strip-single-after-shards
```

Then check:

```bash
python data/build_profile_details_cache.py --status
```

Expected output should include:

```text
cache_format sharded
cached 1302
missing 0
```

The tiny `data/pokemon_profile_details.json` stub can stay in the repository.
