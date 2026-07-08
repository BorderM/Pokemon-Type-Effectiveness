# Pokédex Expansion Roadmap

Goal: grow the app from type/stats/evolution lookup into a practical in-game companion.

## Useful play-focused sections

1. **Overview card**
   - Types, abilities, base stats, evolution family, form notes, sprite.
   - Links to Type Effectiveness, Stats, Evolutions, Bulbapedia.

2. **Battle helper**
   - Weaknesses/resistances/immunities.
   - Fast speed comparison.
   - Ability warnings such as Levitate, Flash Fire, Water Absorb, Sap Sipper.

3. **Moves**
   - Level-up moves.
   - TM/TR/Tutor moves.
   - Egg moves.
   - Filter by game/version where possible.

4. **Encounter/location data**
   - Where to find the Pokémon by game.
   - Evolution item/source reminders.

5. **Forms and variants**
   - Keep the generated form_reference.json as the source of truth.
   - Show form differences only when they affect the selected page.

6. **Data maintenance tools**
   - `python data/verify_evolutions.py --online`
   - `python data/verify_sprites.py --fix`
   - Future: `python data/verify_moves.py --online`

## Suggested architecture

Add one new page first:

- `/pokemon/<key>` or `/pokedex?name=<key>`

This page can reuse existing app data instead of duplicating work:

- `processed_pokemon_cache.json` for types, stats, sprite, form metadata.
- `data/evolutions.json` for evolution family.
- `static/typechart.json` for matchup data.
- Future move/encounter caches can be generated separately.

Keep each data category as a generated JSON cache plus a small manual override file.
This keeps the app reliable without hand-maintaining hundreds of special cases.
