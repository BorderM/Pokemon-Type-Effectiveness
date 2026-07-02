#!/usr/bin/env python3
"""Run local data maintenance tasks.

Default mode is offline-safe. It regenerates local form maps, verifies sprites,
and runs the offline evolution audit. Use --online-profile-details when you
intentionally want to refresh abilities and move learnsets from PokéAPI.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import List

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))


def run(label: str, cmd: List[str]) -> int:
    print(f"\n=== {label} ===")
    print(" ".join(cmd))
    return subprocess.call(cmd, cwd=ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild and audit local Pokémon app data.")
    parser.add_argument("--online-profile-details", action="store_true", help="Fetch abilities/moves from PokéAPI into data/pokemon_profile_details.json.")
    parser.add_argument("--online-evolutions", action="store_true", help="Compare local evolution data against live PokéAPI.")
    parser.add_argument("--profile-limit", type=int, default=0, help="Optional test limit for profile detail fetching.")
    parser.add_argument("--profile-strip-raw", action="store_true", help="Strip raw ability cache after profile build to reduce file size.")
    parser.add_argument("--profile-write-shards", action="store_true", default=True, help="Write PythonAnywhere-friendly profile shards after profile build. Enabled by default.")
    parser.add_argument("--profile-keep-single", action="store_true", help="Keep the large single profile JSON instead of replacing it with a stub after sharding.")
    args = parser.parse_args()

    py = sys.executable
    steps = [
        ("Generate form reference", [py, os.path.join("data", "generate_form_reference.py")]),
        ("Verify and repair sprites", [py, os.path.join("data", "verify_sprites.py"), "--fix"]),
        ("Verify evolutions", [py, os.path.join("data", "verify_evolutions.py")] + (["--online"] if args.online_evolutions else [])),
        ("Apply/check evolution method display overrides", [py, os.path.join("data", "verify_evolution_methods.py"), "--apply", "--report"]),
    ]

    if args.online_profile_details:
        cmd = [py, os.path.join("data", "build_profile_details_cache.py"), "--online"]
        if args.profile_limit:
            cmd.extend(["--limit", str(args.profile_limit)])
        if args.profile_strip_raw:
            cmd.append("--strip-raw")
        if args.profile_write_shards:
            cmd.append("--write-shards")
            if not args.profile_keep_single:
                cmd.append("--strip-single-after-shards")
        steps.append(("Build offline profile details cache", cmd))
    else:
        print("Skipping ability/move cache rebuild. Add --online-profile-details to fetch from PokéAPI.")

    failed = []
    for label, cmd in steps:
        code = run(label, cmd)
        if code != 0:
            failed.append((label, code))

    if failed:
        print("\nSome steps failed:")
        for label, code in failed:
            print(f"- {label}: exit code {code}")
        return 1

    print("\nAll requested rebuild/audit steps completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Evolution method display overrides are applied automatically by rebuild_all.
