# Pokemon typing version 1.20

## Cross-page search preservation

- Opening `/typeeffectiveness?name=...` now preserves the current type-effectiveness cards/history instead of clearing the page first.
- In 1v1 mode, the existing type card is moved into History when a profile link pushes a new Pokémon into the type page.
- In 2v2 mode, existing 2-card behavior is preserved: a new search replaces the older active card and pushes it to History.
- Opening `/stats?name=...` now preserves existing stats cards and appends the searched Pokémon if it is not already visible.

## Pokédex profile persistence

- The last viewed Pokédex profile is stored in localStorage.
- Opening `/pokedex` restores the last viewed profile automatically.
- The Clear button resets the stored profile and returns to the empty Pokédex state.

## Internal app navigation

- Pokémon names on Type Effectiveness cards now link to the local Pokédex profile instead of Bulbapedia.
- Pokémon names on Stats cards now link to the local Pokédex profile instead of Bulbapedia.
- Pokémon names on Evolution cards now link to the local Pokédex profile instead of Bulbapedia.
