import json
from collections import defaultdict

# load your forms & evolutions
forms      = json.load(open('data/forms.json'))
evols      = json.load(open('data/evolutions.json'))

# group all your form-keys by their base species
forms_by_base = defaultdict(list)
for f in forms:
    forms_by_base[f['species']].append(f['key'])

# collect which form-keys actually appear as "from" in evolutions
evolved_from = set(e['from'] for e in evols)

# now sanity-check each species group that should evolve
for species, keys in forms_by_base.items():
    # skip truly non-evolving species
    # (you could maintain a list of known single-stage species)
    # or just warn for any group ≥1 that has no evolved form:
    if any(k in evolved_from for k in keys):
        # good: at least one form of this species actually evolves
        continue
    # warn if you expect it should evolve
    # e.g. you might have a list of bases you know to be multi-stage:
    # if species in ["basculin", "pikachu", ...]:
    print(f"⚠️  No evolution found for any form of '{species}', forms={keys}")
