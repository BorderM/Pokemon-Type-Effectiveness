#!/usr/bin/env python3
import os, json, asyncio, ssl
import aiohttp
from aiohttp import ClientTimeout

# ── CONFIG ────────────────────────────────────────────────────────────────
SCRIPT_DIR      = os.path.dirname(__file__)
MASTER_CACHE_IN = os.path.join(SCRIPT_DIR, 'pokemon_cache.json')
CACHE_OUT       = os.path.join(SCRIPT_DIR, 'processed_pokemon_cache.json')
POKEAPI_BASE    = 'https://pokeapi.co/api/v2'

async def fetch_json(session, url):
    async with session.get(url) as r:
        r.raise_for_status()
        return await r.json()

def calculate_type_effectiveness(type_data_list):
    damage = {}
    for td in type_data_list:
        for rel, arr in td['damage_relations'].items():
            mult = {'double_damage_from':2, 'half_damage_from':0.5, 'no_damage_from':0}.get(rel,1)
            for o in arr:
                damage[o['name']] = damage.get(o['name'],1) * mult

    eff = {k:[] for k in [
      'four_times_effective','super_effective','normal_effective',
      'two_times_resistant','four_times_resistant','immune'
    ]}
    all_types = {
      'normal','fire','water','electric','grass','ice','fighting','poison',
      'ground','flying','psychic','bug','rock','ghost','dragon','dark','steel','fairy'
    }
    for t,m in damage.items():
        if   m==4:   eff['four_times_effective'].append(t)
        elif m==2:   eff['super_effective'].append(t)
        elif m==0.5: eff['two_times_resistant'].append(t)
        elif m==0.25:eff['four_times_resistant'].append(t)
        elif m==0:   eff['immune'].append(t)
    eff['normal_effective'] = list(all_types - set().union(*eff.values()))
    return eff

async def main():
    # ── 1) load or fetch the master list (/pokemon?limit) ──────────────────
    if os.path.exists(MASTER_CACHE_IN):
        master = json.load(open(MASTER_CACHE_IN, encoding='utf-8'))
        poke_list = master.get('results', [])
        print(f"[DEBUG] Loaded {len(poke_list)} entries from local cache")
    else:
        sslctx   = ssl.create_default_context()
        timeout  = ClientTimeout(total=60)
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=sslctx),
                                         timeout=timeout) as sess:
            print("[DEBUG] Fetching /pokemon?limit=10000 from PokeAPI…")
            master = await fetch_json(sess, f"{POKEAPI_BASE}/pokemon?limit=10000")
            poke_list = master.get('results', [])
            print(f"[DEBUG] Fetched {len(poke_list)} entries from PokeAPI")
            with open(MASTER_CACHE_IN, 'w', encoding='utf-8') as wf:
                json.dump(master, wf, indent=2)
                print(f"[DEBUG] Saved → {MASTER_CACHE_IN}")

    # show PokeAPI’s reported total vs your cache length
    live_count  = master.get('count', len(poke_list))
    local_count = len(poke_list)
    print(f"[CHECK] PokeAPI says {live_count} total; your cache has {local_count}")

    # ── 2) now fetch each form individually ────────────────────────────────
    sslctx  = ssl.create_default_context()
    timeout = ClientTimeout(total=120)
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=sslctx),
                                     timeout=timeout) as sess:

        out = []
        for idx, p in enumerate(poke_list, 1):
            raw_name, url = p['name'], p['url']
            # keep every form intact
            name = raw_name
            # derive species and form_name
            if '-' in raw_name:
                species, form_name = raw_name.split('-',1)
            else:
                species, form_name = raw_name, ''
            sprite_url = f"/static/sprites/{raw_name}.png"

            try:
                v = await fetch_json(sess, url)
            except Exception as e:
                print(f"[ERROR] fetch {raw_name} failed: {e}")
                continue

            # gather stats
            stats = { s['stat']['name'].replace('-','_'): s['base_stat']
                      for s in v['stats'] }
            stats['total'] = sum(stats.values())

            # gather types & effectiveness
            type_data = await asyncio.gather(
                *(fetch_json(sess, t['type']['url']) for t in v['types'])
            )
            eff = calculate_type_effectiveness(type_data)

            # human-friendly display
            disp = name.replace('-', ' ').title()
            species   = v['species']['name']
            form_name = raw_name.split('-',1)[1] if '-' in raw_name else ''
            sprite_url = f"/static/sprites/{raw_name}.png"

            out.append({
                "name":          name,
                "display_name":  disp,
                "species":       species,
                "form_name":     form_name,
                "sprite_url":    sprite_url,
                "form":          v['name'],
                "id":            v['id'],
                "types":         [t['type']['name'] for t in v['types']],
                "effectiveness": eff,
                "stats":         stats
            })

            if idx % 200 == 0:
                print(f"[DEBUG] Processed {idx}/{local_count}…")

        print(f"[DEBUG] Built {len(out)} entries")

    # ── 3) write processed cache & compare counts ─────────────────────
    with open(CACHE_OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2)
    print(f"[DEBUG] Wrote {len(out)} → {CACHE_OUT}")
    print(f"[CHECK] Raw cache: {local_count}, Processed cache: {len(out)} — should match!")

if __name__ == '__main__':
    asyncio.run(main())
