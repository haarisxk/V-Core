"""
Run this DURING a live match (after agent select, when you're actually in-game).
It will dump all the important API data to a file so we can inspect it.
"""
import sys, json, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from valclient.client import Client
from valclient.exceptions import PhaseError

c = Client(region='ap')
c.activate()
print(f"Connected as {c.player_name}#{c.player_tag}\n")

dump = {}

# 1. CoreGame match data
print("Fetching coregame data...")
try:
    cg_player = c.coregame_fetch_player()
    if cg_player and "MatchID" in cg_player:
        cg_match = c.coregame_fetch_match(cg_player["MatchID"])
        dump["coregame_match"] = cg_match
        
        players = cg_match.get("Players", [])
        print(f"  Players found: {len(players)}")
        print(f"  Match keys: {list(cg_match.keys())}")
        print(f"  Mode: {cg_match.get('Mode')}")
        print(f"  MapID: {cg_match.get('MapID')}")
        
        # Check PartyID
        has_party = any("PartyID" in p.get("PlayerIdentity", {}) for p in players)
        print(f"  PartyID available: {has_party}")
        
        # 2. Try resolving ALL player names
        puuids = [p.get("Subject") for p in players if p.get("Subject")]
        print(f"\nResolving {len(puuids)} player names...")
        names = c.put("/name-service/v2/players", endpoint_type="pd", json_data=puuids)
        dump["name_service"] = names
        
        resolved = 0
        for entry in names:
            gn = entry.get("GameName", "")
            subj = entry.get("Subject", "")[:8]
            if gn:
                resolved += 1
                print(f"  {subj}... -> {gn}#{entry.get('TagLine','')}")
            else:
                print(f"  {subj}... -> [EMPTY - could not resolve]")
        print(f"\n  Resolved: {resolved}/{len(puuids)}")
    else:
        print("  Not in coregame!")
        dump["coregame_match"] = None
except PhaseError:
    print("  Not in coregame (PhaseError)")
    dump["coregame_match"] = None
except Exception as e:
    print(f"  Error: {e}")
    dump["coregame_match"] = str(e)

# Save everything to a file
output_path = os.path.join(os.path.dirname(__file__), "match_dump.json")
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(dump, f, indent=2, ensure_ascii=False, default=str)

print(f"\nFull data saved to: {output_path}")
print("Done! Send me the output above, or I'll read the JSON file.")
