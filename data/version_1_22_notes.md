# Pokemon typing version 1.22

## Evolution method display policy

This version expands the evolution-method override system so the app prefers the most useful general/current evolution method where possible.

The app now avoids showing older game/location-specific methods as the primary method when a modern/common item method exists.

## Main method updates

- Eevee → Leafeon: Leaf Stone primary; Moss Rock kept as note.
- Eevee → Glaceon: Ice Stone primary; Ice Rock kept as note.
- Magneton → Magnezone: Thunder Stone primary; magnetic-field locations kept as note.
- Nosepass → Probopass: Thunder Stone primary; magnetic-field locations kept as note.
- Charjabug → Vikavolt: Thunder Stone primary; older magnetic-field methods kept as note.
- Crabrawler → Crabominable: Ice Stone primary; Mount Lanakila kept as note.
- Alolan Sandshrew → Alolan Sandslash: corrected to Ice Stone item method.
- Galarian Slowpoke → Galarian Slowbro: corrected to Galarica Cuff item method.
- Hisuian Voltorb → Hisuian Electrode: corrected to Leaf Stone item method.

## Special method notes added

Added clearer notes for special/non-standard evolutions such as Kingambit, Brambleghast, Gholdengo, Pawmot, Annihilape, Rabsca, Alcremie, Sirfetch'd, Overqwil, Wyrdeer, and Runerigus.

## Maintenance commands

Check evolution methods:

```bash
python data/verify_evolution_methods.py
```

Apply curated overrides after a data rebuild:

```bash
python data/verify_evolution_methods.py --apply
```

Write a full audit report:

```bash
python data/verify_evolution_methods.py --report
```

`data/rebuild_all.py` now applies/checks method overrides automatically.
