This folder is where the sharded offline Pokédex profile cache belongs.

For a fully offline/local repository, copy your generated shard files here:

  data/profile_details_shards/*.json

and copy the shard index here:

  data/pokemon_profile_details_index.json

These files are generated from the large data/pokemon_profile_details.json using:

  python data/build_profile_details_cache.py --split-shards --strip-single-after-shards

The large 201 MB pokemon_profile_details.json is intentionally not included in this bundle.
The current pokemon_profile_details.json is only a tiny stub/fallback.
