# Evolution audit

Run the offline audit:

```bash
python data/verify_evolutions.py
```

Run the online audit against live PokéAPI data:

```bash
python data/verify_evolutions.py --online
```

Useful version when you want a starter file for missing edges:

```bash
python data/verify_evolutions.py --online --write-missing-template data/missing_evolutions_template.json
```

## Count meanings

- `local_form_level_edges`: entries in `data/evolutions.json`, including form-specific edges.
- `local_species_level_edges`: local edges collapsed to PokéAPI species names.
- `pokeapi_evolution_chain_count`: family trees in PokéAPI. This includes single-stage families and is **not** the same as direct evolution count.
- `pokeapi_direct_species_edges`: direct parent → child evolution links extracted from the live PokéAPI chain data.
- `pokeapi_direct_species_edges_compared`: PokéAPI direct edges after excluding known non-evolution quirks.
- `ignored_pokeapi_edges`: PokéAPI edges intentionally excluded from failure counts.

The number to compare for app completeness is usually:

```text
local_species_level_edges vs pokeapi_direct_species_edges_compared
```

`phione -> manaphy` is ignored by default. PokéAPI represents it in an evolution chain, but core-game references treat Phione and Manaphy as not evolving into or from one another. Keep that relationship out of `data/evolutions.json` unless you intentionally want strict PokéAPI parity rather than game-accurate evolution behavior.

A reported `missing_vs_pokeapi` entry means the app is probably missing a real species-level evolution. An `extra_vs_pokeapi` entry usually means the app is tracking form-specific/regional/game-specific evolutions more granularly than PokéAPI's species-level tree.


## Evolution display collapse notes

Some evolution outcomes are represented by a specific form key in the local cache because no plain base-form sprite exists, but the evolution page intentionally displays the species-level name:

- `darumaka -> darmanitan-standard` displays as **Darumaka → Darmanitan**.
- `darumaka-galar -> darmanitan-galar-standard` displays as **Galarian Darumaka → Galarian Darmanitan**.
- `finizen -> palafin-zero` displays as **Finizen → Palafin**.
- `lechonk -> oinkologne-male` displays as **Lechonk → Oinkologne**. Gender-specific Oinkologne forms are collapsed unless separate sprites are intentionally shown later.
- `tandemaus -> maushold-family-of-four` displays as **Tandemaus → Maushold**. Family of Three is noted as rare rather than rendered as a separate card by default.

`phione -> manaphy` remains excluded as an intentional PokéAPI exception.
