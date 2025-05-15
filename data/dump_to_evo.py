import sqlite3, json, os

# 1) connect
conn = sqlite3.connect("pokebdb.sqlite")
c    = conn.cursor()

# 2) load your local forms.json keys
forms = json.load(open("data/forms.json"))
form_keys = {f["key"] for f in forms}

# 3) do the join
c.execute("""
SELECT
  ps.identifier        AS from_species,
  ps2.identifier       AS to_species,
  et.identifier        AS trigger,
  pe.minimum_level,
  i.identifier         AS item,
  pe.time_of_day,
  l.identifier         AS location,
  pe.held_item_id,
  pe.known_move_id,
  pe.known_move_type_id,
  pe.minimum_happiness,
  pe.minimum_beauty,
  pe.relative_physical_stats,
  pe.party_species_id,
  pe.party_type_id,
  pe.trade_species_id,
  pe.gender_id
FROM pokemon_evolution pe
JOIN pokemon_species ps  ON pe.species_id          = ps.id
JOIN pokemon_species ps2 ON pe.evolved_species_id  = ps2.id
LEFT JOIN evolution_triggers et ON pe.evolution_trigger_id = et.id
LEFT JOIN items           i  ON pe.trigger_item_id       = i.id
LEFT JOIN locations       l  ON pe.location_id           = l.id
""")

edges = []
for row in c.fetchall():
    (frm, to, trigger, lvl, item, tod, loc,
     held_item_id, known_move_id, known_move_type_id,
     min_hap, min_beauty, rps, party_sp_id,
     party_type_id, trade_sp_id, gender_id) = row

    # map IDs → identifiers for held_item, known_move, known_move_type, party_species, party_type, trade_species
    held_item   = None
    known_move  = None
    known_mtype = None
    party_sp    = None
    party_tp    = None
    trade_sp    = None

    if held_item_id:
        held_item = c.execute("SELECT identifier FROM items WHERE id=?", (held_item_id,)).fetchone()[0]
    if known_move_id:
        known_move = c.execute("SELECT identifier FROM moves WHERE id=?", (known_move_id,)).fetchone()[0]
    if known_move_type_id:
        known_mtype = c.execute("SELECT identifier FROM types WHERE id=?", (known_move_type_id,)).fetchone()[0]
    if party_sp_id:
        party_sp = c.execute("SELECT identifier FROM pokemon_species WHERE id=?", (party_sp_id,)).fetchone()[0]
    if party_type_id:
        party_tp = c.execute("SELECT identifier FROM types WHERE id=?", (party_type_id,)).fetchone()[0]
    if trade_sp_id:
        trade_sp = c.execute("SELECT identifier FROM pokemon_species WHERE id=?", (trade_sp_id,)).fetchone()[0]

    gender = {1:"male",2:"female"}.get(gender_id)

    edge = {
      "from": frm,
      "to":   to,
      "trigger": trigger,
      "min_level": lvl if lvl else None,
      "item":      item,
      "time_of_day": tod,
      "location":  loc,
      "held_item": held_item,
      "known_move": known_move,
      "known_move_type": known_mtype,
      "min_happiness": min_hap if min_hap else None,
      "min_beauty":    min_beauty if min_beauty else None,
      "relative_physical_stats": rps if rps is not None else None,
      "party_species": party_sp,
      "party_type":    party_tp,
      "trade_species": trade_sp,
      "gender":        gender,
      "note":          None
    }

    # only keep edges for forms you have locally
    if edge["from"] in form_keys and edge["to"] in form_keys:
        edges.append(edge)

conn.close()

# 4) write out evolutions.json
os.makedirs("data", exist_ok=True)
with open("data/evolutions.json","w") as f:
    json.dump(edges, f, indent=2)

print(f"Wrote {len(edges)} edges")
