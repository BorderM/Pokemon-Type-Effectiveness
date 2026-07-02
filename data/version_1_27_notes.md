# Pokemon typing version 1.27

Profile page polish patch.

## Changes

- Pokédex profile moves now use exact-form profile details only, so alternate forms do not inherit another form's learnset by accident.
- Abilities can still fall back to the species/base profile when an alternate form has no cached ability data.
- Removed the “loaded from local cache” note from the overview card.
- Moves by Generation is more compact on desktop and mobile.
- Move rows now show version-group subtext only when a move has multiple different learn rows inside the same generation, such as Generation I Pikachu differences between Red/Blue and Yellow.
- Move filtering now also searches version labels.

## Deployment notes

If updating from version 1.26 manually, replace:

- app.py
- templates/pokemonprofile.html
- data/version_1_27_notes.md

No cache rebuild is required for the UI changes. A future cache rebuild will continue to work with the existing offline/sharded cache system.
