# Evolution Method Display Overrides

`verify_evolutions.py` checks whether evolution edges exist. This file/script pair handles a different problem: evolution **method display**.

The app's preferred display policy is:

1. Prefer general/current methods that are most useful while playing.
2. Use modern/common item methods when they exist.
3. Avoid showing older location-specific methods as the primary method.
4. Preserve older or game-specific methods as notes.
5. Do not guess. Region-only and special-mechanic evolutions are kept as notes unless a clear general method exists.

## Current curated override examples

The override file now covers more than just Leafeon/Glaceon. Examples:

- Eevee → Leafeon: primary method is `Leaf Stone`; Moss Rock remains a note.
- Eevee → Glaceon: primary method is `Ice Stone`; Ice Rock remains a note.
- Magneton → Magnezone: primary method is `Thunder Stone`; magnetic-field locations remain a note.
- Nosepass → Probopass: primary method is `Thunder Stone`; magnetic-field locations remain a note.
- Charjabug → Vikavolt: primary method is `Thunder Stone`; older magnetic-field methods remain a note.
- Crabrawler → Crabominable: primary method is `Ice Stone`; Mount Lanakila remains a note.
- Alolan Sandshrew → Alolan Sandslash: primary method is `Ice Stone`, with no fake level requirement.
- Galarian Slowpoke → Galarian Slowbro: primary method is `Galarica Cuff`, with no fake level requirement.
- Hisuian Voltorb → Hisuian Electrode: primary method is `Leaf Stone`, with no fake level requirement.

The file also adds clearer notes for special mechanic evolutions such as Kingambit, Annihilape, Gholdengo, Pawmot, Rabsca, Sirfetch'd, Overqwil, Wyrdeer, Alcremie, and Runerigus.

## Check current state

```bash
python data/verify_evolution_methods.py
```

This prints a compact summary. It separates:

- `unresolved_review_items_count`: methods that still look wrong or need curation.
- `intentional_specific_cases_count`: regional/special mechanics that are expected to remain as notes.

## Apply overrides

Run this after regenerating evolution data:

```bash
python data/verify_evolution_methods.py --apply
```

## Write a full audit report

```bash
python data/verify_evolution_methods.py --report
```

This writes:

```text
data/evolution_method_audit_report.json
```

## Full JSON output

```bash
python data/verify_evolution_methods.py --json
```
