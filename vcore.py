#!/usr/bin/env python3
"""
V-Core Terminal - Local API Client v1.0.0

Hooks into the local client API to auto-lock agents and display a live
dashboard of match info. Uses local HTTP endpoints exclusively.
inputs — just raw HTTP calls that Vanguard won't flag.

Features:
- Continuous state tracking: Menus → Queue → Agent Select → In-Game → repeat
- Instant agent auto-lock with human-like delay
- Real competitive rank lookup via the MMR endpoint (works in ALL modes)
- Full player name unmasking via name-service (bypasses incognito)
- Party stack detection (duo, trio, 4-stack, 5-stack) via coregame PartyID
- Match info persists through the entire game, not just agent select
- Automatic recovery between matches — never needs a restart
"""

import sys
import os
import time
import random
import copy
import logging
import argparse
import ctypes
import atexit
import subprocess
import json
from typing import Optional, Dict, List, Any

# Fix Windows console encoding so special characters in names don't crash us
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    os.system("chcp 65001 >nul 2>&1")

try:
    import keyboard
except ImportError:
    keyboard = None

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box
from rich.align import Align

from valclient.client import Client
from valclient.exceptions import HandshakeError, ResponseError, PhaseError

# ======================== CONFIGURATION ========================
VERSION = "1.0.0"
DEFAULT_TARGET_AGENTS = "Sage,Jett,Clove,Raze,Reyna"  # Change this to your main
POLL_INTERVAL_IDLE = 2.0       # Seconds between checks when idle/in menus
POLL_INTERVAL_QUEUE = 0.3      # Seconds between checks when in queue (fast for timer)
POLL_INTERVAL_PREGAME = 0.8    # Seconds between checks during agent select
POLL_INTERVAL_INGAME = 5.0     # Seconds between checks during a live game

# ======================== LOGGING SETUP ========================
def setup_logging() -> None:
    os.makedirs("logs", exist_ok=True)
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler("logs/vcore.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

setup_logging()
log = logging.getLogger(__name__)

# ======================== RANK MAP ========================
RANK_MAP = {
    0: "Unranked",
    3: "Iron 1",     4: "Iron 2",      5: "Iron 3",
    6: "Bronze 1",   7: "Bronze 2",    8: "Bronze 3",
    9: "Silver 1",   10: "Silver 2",   11: "Silver 3",
    12: "Gold 1",    13: "Gold 2",     14: "Gold 3",
    15: "Plat 1",    16: "Plat 2",     17: "Plat 3",
    18: "Diamond 1", 19: "Diamond 2",  20: "Diamond 3",
    21: "Ascendant 1", 22: "Ascendant 2", 23: "Ascendant 3",
    24: "Immortal 1",  25: "Immortal 2",  26: "Immortal 3",
    27: "Radiant",
}

RANK_COLORS = {
    0: "grey53",
    3: "grey53",     4: "grey53",      5: "grey53",
    6: "orange4",    7: "orange4",     8: "orange4",
    9: "silver",     10: "silver",     11: "silver",
    12: "gold1",     13: "gold1",      14: "gold1",
    15: "cyan2",     16: "cyan2",      17: "cyan2",
    18: "medium_purple1", 19: "medium_purple1", 20: "medium_purple1",
    21: "green3",    22: "green3",     23: "green3",
    24: "red1",      25: "red1",       26: "red1",
    27: "yellow1",
}

PARTY_LABELS = {2: "DUO", 3: "TRIO", 4: "4-STACK", 5: "5-STACK"}

# ======================== PLATFORM HELPERS ========================
def detect_region() -> str:
    """Read the region from VALORANT's lockfile."""
    try:
        lock_path = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Riot Games", "VALORANT", "lockfile")
        if not os.path.exists(lock_path):
            lock_path = os.path.join(os.environ.get("PROGRAMDATA", ""), "Riot Games", "VALORANT", "lockfile")
        if os.path.exists(lock_path):
            with open(lock_path, "r") as f:
                parts = f.read().strip().split(":")
                if len(parts) >= 4:
                    return parts[3]  # region is the 4th field (0-indexed)
    except Exception:
        pass
    return "ap"  # fallback

def is_admin() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def elevate():
    if sys.platform != "win32":
        print("Elevation not supported on this OS.")
        sys.exit(1)
    # Properly quote arguments to handle spaces in paths
    cmd = subprocess.list2cmdline(sys.argv)
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, cmd, None, 1)
    sys.exit()

def enable_stealth(console: Console):
    if sys.platform != "win32":
        console.print("[yellow]Stealth mode is only supported on Windows. Skipping.[/yellow]")
        return
    console.print("[bold yellow]Configuring Windows Firewall to block Riot Chat (TCP 5222, 5223)...[/bold yellow]")
    subprocess.run('netsh advfirewall firewall delete rule name="VCore_Stealth"', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run('netsh advfirewall firewall add rule name="VCore_Stealth" dir=out action=block protocol=TCP remoteport=5222,5223', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    console.print("[bold purple]Stealth Mode activated. Outbound chat traffic blocked.[/bold purple]\n")

def disable_stealth():
    if sys.platform != "win32":
        return
    subprocess.run('netsh advfirewall firewall delete rule name="VCore_Stealth"', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class ValorantTerminal:
    def __init__(self, target_agents: List[str], auto_lock: bool = True, is_stealth: bool = False):
        self.target_agents = target_agents
        self.auto_lock = auto_lock
        self.is_stealth = is_stealth
        self.client: Optional[Client] = None
        self.player_name = ""
        self.player_tag = ""
        self.console = Console()
        self.lock_success = False  # <-- FIXED: initialized here

        # Game content caches (loaded once from valorant-api.com)
        self.name_to_uuid: Dict[str, str] = {}
        self.uuid_to_name: Dict[str, str] = {}
        self.map_lookup: Dict[str, str] = {}
        self.mode_lookup: Dict[str, str] = {}
        self.mode_uuid_lookup: Dict[str, str] = {}

        # Per-match caches (cleared between matches)
        self.name_cache: Dict[str, str] = {}
        self.rank_cache: Dict[str, int] = {}

        # State tracking
        self.cached_match_display: Optional[Dict[str, Any]] = None
        self._force_redraw = False
        self.queue_start_time: Optional[float] = None
        self.match_count = 0

    def toggle_stealth(self) -> None:
        self.is_stealth = not self.is_stealth
        if self.is_stealth:
            enable_stealth(self.console)
        else:
            self.console.print("\n[bold green]Stealth rules removed. Connection restored.[/bold green]")
            time.sleep(1)
        self._force_redraw = True

    # ================================================================
    #  SETUP
    # ================================================================

    def authenticate(self) -> None:
        region = detect_region()
        try:
            self.client = Client(region=region)
            self.client.activate()
            self.player_name = self.client.player_name
            self.player_tag = self.client.player_tag
            log.info(f"Authenticated as {self.player_name}#{self.player_tag} (region={region})")
        except HandshakeError as e:
            log.critical(f"Lockfile error: {e}")
            self._fatal(f"Couldn't grab the lockfile. Is VALORANT running?\n  Error: {e}")

    def fetch_content(self) -> None:
        import requests
        try:
            r = requests.get("https://valorant-api.com/v1/agents?isPlayableCharacter=true", timeout=10)
            r.raise_for_status()
            for a in r.json().get("data", []):
                self.name_to_uuid[a["displayName"]] = a["uuid"]
                self.uuid_to_name[a["uuid"]] = a["displayName"]
                self.uuid_to_name[a["uuid"].lower()] = a["displayName"]
                self.uuid_to_name[a["uuid"].upper()] = a["displayName"]

            r = requests.get("https://valorant-api.com/v1/maps", timeout=10)
            r.raise_for_status()
            for m in r.json().get("data", []):
                if "mapUrl" in m:
                    self.map_lookup[m["mapUrl"]] = m["displayName"]
                if "uuid" in m:
                    self.map_lookup[m["uuid"]] = m["displayName"]

            r = requests.get("https://valorant-api.com/v1/gamemodes", timeout=10)
            r.raise_for_status()
            for m in r.json().get("data", []):
                ap = m.get("assetPath", "")
                if "GameModes/" in ap:
                    key = ap.split("GameModes/")[1].split("/")[0]
                    self.mode_lookup[key] = m["displayName"]
                self.mode_lookup[ap] = m["displayName"]
                if "uuid" in m:
                    self.mode_uuid_lookup[m["uuid"]] = m["displayName"]
                    self.mode_uuid_lookup[m["uuid"].lower()] = m["displayName"]

            log.info(f"Loaded {len(self.name_to_uuid)} agents, {len(self.map_lookup)} maps")
        except requests.RequestException as e:
            self._fatal(f"Failed to fetch game content: {e}")

    # ================================================================
    #  STORE HELPERS (FIXED OFFERID MAPPING)
    # ================================================================

    def fetch_weapon_skins(self) -> Dict[str, str]:
        """Fetch all weapon skins and map Skin UUID -> Full Skin Name."""
        import requests
        lookup = {}
        try:
            r = requests.get("https://valorant-api.com/v1/weapons", timeout=10)
            r.raise_for_status()
            for weapon in r.json().get("data", []):
                weapon_name = weapon.get("displayName", "")
                for skin in weapon.get("skins", []):
                    skin_uuid = skin.get("uuid")
                    skin_name = skin.get("displayName", "")
                    if skin_name and skin_name != "Standard" and weapon_name:
                        full_name = f"{skin_name} {weapon_name}"
                    else:
                        full_name = skin_name or weapon_name
                    if skin_uuid:
                        lookup[skin_uuid] = full_name
                        lookup[skin_uuid.lower()] = full_name
        except Exception as e:
            log.warning(f"Failed to fetch weapon skins: {e}")
        return lookup

    def fetch_store_offers(self) -> Dict[str, str]:
        """Fetch store offers to map OfferID -> Reward ItemID (Skin UUID)."""
        import requests
        lookup = {}
        try:
            r = requests.get("https://valorant-api.com/v1/storeoffers", timeout=10)
            r.raise_for_status()
            for offer in r.json().get("data", []):
                offer_id = offer.get("offerId")
                rewards = offer.get("rewards", [])
                if rewards:
                    item_id = rewards[0].get("itemId")
                    if offer_id and item_id:
                        lookup[offer_id] = item_id
        except Exception as e:
            log.warning(f"Failed to fetch store offers: {e}")
        return lookup

    # ================================================================
    #  DATA RESOLVERS
    # ================================================================

    def resolve_names(self, puuids: List[str]) -> None:
        needed = [p for p in puuids if p and p not in self.name_cache]
        if not needed:
            return

        resolved_puuids = set()
        try:
            response = self.client.put("/name-service/v2/players", endpoint_type="pd", json_data=needed)
            for entry in response:
                puuid = entry.get("Subject") or entry.get("puuid") or ""
                if not puuid or puuid not in needed:
                    continue
                name = entry.get("GameName") or ""
                tag = entry.get("TagLine") or ""
                if name:
                    self.name_cache[puuid] = f"{name}#{tag}" if tag else name
                    resolved_puuids.add(puuid)
        except Exception as e:
            log.warning(f"Batch name resolution failed: {e}")

        still_needed = [p for p in needed if p not in resolved_puuids]
        for puuid in still_needed:
            try:
                response = self.client.put("/name-service/v2/players", endpoint_type="pd", json_data=[puuid])
                if response:
                    entry = response[0]
                    name = entry.get("GameName") or ""
                    tag = entry.get("TagLine") or ""
                    if name:
                        self.name_cache[puuid] = f"{name}#{tag}" if tag else name
                        continue
            except Exception:
                pass
            self.name_cache[puuid] = "Hidden Player"
            log.debug(f"Could not resolve name for {puuid[:8]} — likely privacy-locked")

    def resolve_rank(self, puuid: str) -> int:
        if puuid in self.rank_cache:
            return self.rank_cache[puuid]
        try:
            mmr = self.client.fetch_mmr(puuid)
            tier = mmr.get("LatestCompetitiveUpdate", {}).get("TierAfterUpdate")
            if tier and tier > 0:
                self.rank_cache[puuid] = tier
                return tier
            seasons = mmr.get("QueueSkills", {}).get("competitive", {}).get("SeasonalInfoBySeasonID", {})
            if seasons:
                latest = list(seasons.values())[-1]
                tier = latest.get("CompetitiveTier", 0)
                if tier > 0:
                    self.rank_cache[puuid] = tier
                    return tier
            self.rank_cache[puuid] = 0
            return 0
        except Exception as e:
            log.debug(f"MMR fetch failed for {puuid[:8]}: {e}")
            self.rank_cache[puuid] = 0
            return 0

    def resolve_ranks_batch(self, puuids: List[str]) -> None:
        for puuid in puuids:
            if puuid and puuid not in self.rank_cache:
                self.resolve_rank(puuid)

    # ================================================================
    #  STATE DETECTION
    # ================================================================

    def get_state(self) -> str:
        try:
            pd = self.client.pregame_fetch_player()
            if pd and "MatchID" in pd:
                return "PREGAME"
        except (PhaseError, ResponseError):
            pass
        except Exception as e:
            log.debug(f"Pregame probe error: {e}")

        try:
            cg = self.client.coregame_fetch_player()
            if cg and "MatchID" in cg:
                return "INGAME"
        except (PhaseError, ResponseError):
            pass
        except Exception as e:
            log.debug(f"Coregame probe error: {e}")

        try:
            pp = self.client.party_fetch_player()
            pid = pp.get("CurrentPartyID")
            if pid:
                party = self.client.fetch(f"/parties/v1/parties/{pid}", endpoint_type="glz")
                if party and party.get("State") == "MATCHMAKING":
                    return "MATCHMAKING"
        except Exception as e:
            log.debug(f"Party probe error: {e}")

        return "MENUS"

    def get_pregame_match(self) -> Optional[Dict[str, Any]]:
        try:
            pd = self.client.pregame_fetch_player()
            if pd and "MatchID" in pd:
                return self.client.pregame_fetch_match(pd["MatchID"])
        except Exception:
            pass
        return None

    def get_coregame_match(self) -> Optional[Dict[str, Any]]:
        try:
            cg = self.client.coregame_fetch_player()
            if cg and "MatchID" in cg:
                return self.client.coregame_fetch_match(cg["MatchID"])
        except Exception:
            pass
        return None

    # ================================================================
    #  MODE RESOLVER (FIXED PRIORITY)
    # ================================================================

    def _resolve_mode(self, match: Dict[str, Any]) -> str:
        raw_mode = match.get("Mode", "")
        mode_id = match.get("ModeID", "")

        # CHECK UUID first (CoreGame often gives UUID)
        if mode_id:
            name = self.mode_uuid_lookup.get(mode_id) or self.mode_uuid_lookup.get(mode_id.lower())
            if name:
                return name
        if raw_mode:
            name = self.mode_uuid_lookup.get(raw_mode) or self.mode_uuid_lookup.get(raw_mode.lower())
            if name:
                return name

        # Then try asset path parsing
        if "GameModes/" in raw_mode:
            identifier = raw_mode.split("GameModes/")[1].split("/")[0]
            name = self.mode_lookup.get(identifier)
            if name:
                return name

        # Full path fallback
        name = self.mode_lookup.get(raw_mode)
        if name:
            return name

        # ProvisioningFlowID hints
        prov = match.get("ProvisioningFlowID", "").lower()
        if "competitive" in prov:
            return "Competitive"
        if "spike" in prov or "quickbomb" in prov:
            return "Spike Rush"
        if "swift" in prov:
            return "Swiftplay"
        if "deathmatch" in prov:
            return "Deathmatch"

        # MatchmakingData queue hints
        mm = match.get("MatchmakingData", {})
        if mm:
            qid = mm.get("QueueID", "")
            queue_names = {
                "competitive": "Competitive", "unrated": "Unrated",
                "swiftplay": "Swiftplay", "deathmatch": "Deathmatch",
                "spikerush": "Spike Rush", "ggteam": "Escalation",
                "hurm": "Team Deathmatch", "onefa": "Replication",
                "fortcollins": "Retake",
            }
            if qid in queue_names:
                return queue_names[qid]

        return raw_mode if raw_mode else "Unknown Mode"

    # ================================================================
    #  PARTY DETECTION
    # ================================================================

    def _detect_parties(self, players: List[Dict]) -> Dict[str, str]:
        party_map: Dict[str, List[str]] = {}
        for player in players:
            puuid = player.get("Subject", "")
            identity = player.get("PlayerIdentity", {})
            party_id = identity.get("PartyID", "")
            if party_id and puuid:
                party_map.setdefault(party_id, []).append(puuid)

        labels: Dict[str, str] = {}
        letter = ord("A")
        for pid, members in party_map.items():
            if len(members) >= 2:
                tag = PARTY_LABELS.get(len(members), f"{len(members)}-STACK")
                char = chr(letter)
                letter += 1
                for puuid in members:
                    labels[puuid] = f"Party {char} ({tag})"
        return labels

    # ================================================================
    #  UI RENDERING
    # ================================================================

    def _clear(self) -> None:
        if os.name == "nt":
            os.system("cls")
        else:
            os.system("clear")

    def _draw_banner(self, is_store: bool = False) -> None:
        if is_store:
            content = f"[bold cyan]User: {self.player_name}#{self.player_tag}[/bold cyan]"
        else:
            targets_str = ", ".join(self.target_agents) if self.target_agents else "None"
            content = (
                f"[bold cyan]User: {self.player_name}#{self.player_tag}[/bold cyan]  |  "
                f"[bold green]Auto-Lock: {targets_str}[/bold green]  |  "
                f"[bold yellow]Games: {self.match_count}[/bold yellow]"
            )
            if self.is_stealth:
                content += "\n[bold purple]STEALTH MODE ACTIVE[/bold purple]"
        panel = Panel(Align.center(content), title="[bold white]V-CORE TERMINAL[/bold white]", border_style="cyan", expand=False)
        self.console.print(panel)

    def draw_menus(self) -> None:
        self._clear()
        self._draw_banner()
        self.console.print("\n[bold white]STATUS:[/bold white] [bold grey53]In Lobby[/bold grey53]")
        self.console.print("[dim]" + "-" * 40 + "[/dim]")
        self.console.print("[italic]Waiting for you to start matchmaking...[/italic]")
        self.console.print("[italic]The dashboard will update automatically when you queue up.[/italic]\n")
        self.console.print("[bold cyan]TIP:[/bold cyan] Just play normally. I'll handle the rest.\n")

    def draw_matchmaking(self, elapsed: float) -> None:
        self._clear()
        self._draw_banner()
        mins = int(elapsed) // 60
        secs = int(elapsed) % 60
        self.console.print(f"\n[bold white]STATUS:[/bold white] [bold yellow]Searching for Match  [{mins:02d}:{secs:02d}][/bold yellow]")
        self.console.print("[dim]" + "-" * 40 + "[/dim]")
        self.console.print("[italic]Scanning for a game... sit tight![/italic]\n")
        ticks = int(elapsed) % 4
        bar = "[cyan]" + "#" * (ticks + 1) + "[/cyan]" + "[dim]" + "." * (3 - ticks) + "[/dim]"
        self.console.print(f"  [{bar}]\n")

    def draw_match_info(self, match: Dict[str, Any], is_ingame: bool = False) -> None:
        self._clear()
        self._draw_banner()

        map_name = self.map_lookup.get(match.get("MapID", ""), "Unknown Map")
        mode_name = self._resolve_mode(match)

        if is_ingame:
            status_line = "[bold white]STATUS:[/bold white] [bold red]In Game[/bold red]"
        else:
            status_line = "[bold white]STATUS:[/bold white] [bold green]Agent Select - Match Found![/bold green]"

        self.console.print(f"\n{status_line}")
        self.console.print(f"[bold cyan]MAP: {map_name}[/bold cyan]  |  [bold magenta]MODE: {mode_name}[/bold magenta]\n")

        teams_raw = match.get("Teams", [])
        all_players: List[Dict] = []

        is_pregame_format = isinstance(teams_raw, list) and teams_raw and isinstance(teams_raw[0], dict) and "Players" in teams_raw[0]

        if is_pregame_format:
            for team in teams_raw:
                for p in team.get("Players", []):
                    all_players.append(p)
        else:
            all_players = match.get("Players", [])

        all_puuids = [p.get("Subject") for p in all_players if p.get("Subject")]

        self.resolve_names(all_puuids)
        self.resolve_ranks_batch(all_puuids)
        party_labels = self._detect_parties(all_players)

        our_puuid = self.client.puuid
        our_team_players: List[Dict] = []
        enemy_team_players: List[Dict] = []

        if is_pregame_format:
            our_team_obj = None
            for team in teams_raw:
                for p in team.get("Players", []):
                    if p.get("Subject") == our_puuid:
                        our_team_obj = team
                        break
                if our_team_obj:
                    break
            if our_team_obj:
                our_team_players = our_team_obj.get("Players", [])
                for team in teams_raw:
                    if team.get("TeamID") != our_team_obj.get("TeamID"):
                        enemy_team_players.extend(team.get("Players", []))
        else:
            our_team_id = None
            for p in all_players:
                if p.get("Subject") == our_puuid:
                    our_team_id = p.get("TeamID")
                    break
            for p in all_players:
                if p.get("TeamID") == our_team_id:
                    our_team_players.append(p)
                else:
                    enemy_team_players.append(p)

        self._print_team("YOUR TEAM", our_team_players, party_labels, our_puuid, style="green")

        if enemy_team_players:
            self._print_team("ENEMY TEAM", enemy_team_players, party_labels, our_puuid, style="red")
        elif not is_ingame:
            self.console.print(Panel("[italic]Enemy team will be revealed when the match starts.\nRiot hides enemy data during agent selection.[/italic]", title="ENEMY TEAM", border_style="red", expand=False))
        else:
            self.console.print("[dim]ENEMY TEAM: No data available[/dim]\n")

        if hasattr(self, 'lock_success') and self.lock_success:
            self.console.print(f"\n[bold green][+] Auto-locked successfully![/bold green]")
        self.console.print()

    def _print_team(self, label: str, players: List[Dict], party_labels: Dict[str, str], our_puuid: str, style: str) -> None:
        if not players:
            self.console.print(f"[dim]{label}: No data available[/dim]\n")
            return

        table = Table(title=label, title_style=f"bold {style}", title_justify="left", box=box.SQUARE, border_style=style, expand=False)
        table.add_column("Player", style="white")
        table.add_column("Lvl", justify="right", style="cyan")
        table.add_column("Rank")
        table.add_column("Agent", style="yellow")
        table.add_column("Party", style="magenta")

        for player in players:
            puuid = player.get("Subject", "")
            identity = player.get("PlayerIdentity", {})

            name = self.name_cache.get(puuid, "Hidden Player")
            if puuid == our_puuid:
                name = f"[bold white]{name} <[/bold white]"

            raw_level = identity.get("AccountLevel", 0)
            level_str = "[dim]?[/dim]" if raw_level == 0 else str(raw_level)

            tier = self.rank_cache.get(puuid, 0)
            rank_name = RANK_MAP.get(tier, "Unranked")
            rank_color = RANK_COLORS.get(tier, "white")
            rank_str = f"[{rank_color}]{rank_name}[/{rank_color}]"

            agent_id = player.get("CharacterID", "")
            agent_name = ""
            if agent_id:
                agent_name = self.uuid_to_name.get(agent_id, "") or self.uuid_to_name.get(agent_id.lower(), "") or self.uuid_to_name.get(agent_id.upper(), "")
            state = player.get("CharacterSelectionState", "")
            if agent_name:
                if state == "locked":
                    agent_str = f"[bold green][L] {agent_name}[/bold green]"
                elif state == "selected":
                    agent_str = f"[dim][-] {agent_name}[/dim]"
                else:
                    agent_str = agent_name
            else:
                agent_str = "[dim]...[/dim]"

            party_str = party_labels.get(puuid, "Solo")
            table.add_row(name, level_str, rank_str, agent_str, party_str)

        self.console.print(table)
        self.console.print()

    def draw_ingame_standby(self) -> None:
        self._clear()
        self._draw_banner()
        self.console.print("\n[bold white]STATUS:[/bold white] [bold red]In Game[/bold red]")
        self.console.print("[dim]" + "-" * 40 + "[/dim]")
        self.console.print("[italic]Match in progress.[/italic]")
        self.console.print("[italic]Dashboard will refresh when the match ends.[/italic]\n")

    # ================================================================
    #  AGENT LOCKING (RACE-CONDITION SAFE)
    # ================================================================

    def select_and_lock(self, match_id: str, agent_uuid: str, agent_name: str) -> bool:
        try:
            self.client.pregame_select_character(agent_uuid, match_id)
            time.sleep(random.uniform(0.15, 0.3))
            self.client.pregame_lock_character(agent_uuid, match_id)
            log.info(f"Locked in {agent_name}")
            return True
        except ResponseError as e:
            log.error(f"Lock failed for {agent_name}: {e}")
            return False

    # ================================================================
    #  MAIN LOOP
    # ================================================================

    def run(self) -> None:
        self.authenticate()
        self.fetch_content()

        # Register global hotkey if keyboard module is available
        if keyboard is not None:
            try:
                keyboard.add_hotkey('F8', self.toggle_stealth)
                log.info("F8 hotkey registered for stealth toggle")
            except Exception as e:
                log.warning(f"Could not register hotkey (may need admin on Windows): {e}")
        else:
            log.warning("keyboard module not installed; stealth toggle hotkey disabled")

        # Resolve UUIDs for target agents
        self.target_uuids = []
        for name in self.target_agents:
            uuid = None
            for k, v in self.name_to_uuid.items():
                if k.lower() == name.lower():
                    uuid = v
                    break
            if uuid:
                self.target_uuids.append((uuid, name.capitalize()))
            else:
                print(f"  [!] Agent '{name}' not found.")

        if not self.target_uuids:
            print(f"  [!] No valid agents provided. Auto-lock disabled.")
            self.auto_lock = False

        last_state = None
        last_teams_snapshot = None
        queue_timer_drawn = -1

        while True:
            try:
                state = self.get_state()
            except Exception as e:
                log.error(f"State detection error: {e}")
                time.sleep(2.0)
                continue

            if state != last_state or self._force_redraw:
                if state != last_state:
                    log.info(f"State: {last_state} -> {state}")
                self._force_redraw = False

                if state == "MENUS":
                    if last_state in ("PREGAME", "INGAME"):
                        self.match_count += 1
                        self.name_cache.clear()
                        self.rank_cache.clear()
                        self.lock_success = False
                        self.cached_match_display = None
                        last_teams_snapshot = None
                    self.draw_menus()

                elif state == "MATCHMAKING":
                    self.queue_start_time = time.time()
                    queue_timer_drawn = -1
                    self.draw_matchmaking(0)

                elif state == "PREGAME":
                    self.lock_success = False
                    self.name_cache.clear()
                    self.rank_cache.clear()
                    last_teams_snapshot = None

                    match = self.get_pregame_match()
                    if match:
                        self.cached_match_display = copy.deepcopy(match)
                        self.draw_match_info(match, is_ingame=False)

                        # ----- FIXED: RACE-CONDITION SAFE AUTO-LOCK -----
                        if self.auto_lock and self.target_uuids and not self.lock_success:
                            for agent_uuid, agent_name in self.target_uuids:
                                # 1) Fresh fetch every iteration
                                fresh_match = self.get_pregame_match()
                                if not fresh_match:
                                    break

                                # 2) Check if any teammate (other than us) has locked this agent
                                our_team = None
                                for team in fresh_match.get("Teams", []):
                                    for p in team.get("Players", []):
                                        if p.get("Subject") == self.client.puuid:
                                            our_team = team
                                            break
                                    if our_team:
                                        break

                                if our_team:
                                    locked_agents = {
                                        p.get("CharacterID", "").lower()
                                        for p in our_team.get("Players", [])
                                        if p.get("CharacterSelectionState") == "locked"
                                        and p.get("Subject") != self.client.puuid
                                    }
                                    if agent_uuid.lower() in locked_agents:
                                        continue  # taken, try next

                                # 3) Human-like delay before attempting
                                time.sleep(random.uniform(0.1, 0.3))

                                # 4) Attempt lock
                                success = self.select_and_lock(
                                    fresh_match.get("ID"),
                                    agent_uuid,
                                    agent_name
                                )
                                if success:
                                    self.lock_success = True
                                    # Refresh and redraw to show the lock
                                    match = self.get_pregame_match()
                                    if match:
                                        self.cached_match_display = copy.deepcopy(match)
                                        self.draw_match_info(match, is_ingame=False)
                                    break  # stop waterfall
                                else:
                                    # If it failed because agent was just taken, loop continues
                                    continue
                        # ------------------------------------------------

                elif state == "INGAME":
                    cg = self.get_coregame_match()
                    if cg:
                        self.cached_match_display = copy.deepcopy(cg)
                        self.draw_match_info(cg, is_ingame=True)
                    elif self.cached_match_display:
                        self.draw_match_info(self.cached_match_display, is_ingame=True)
                    else:
                        self.draw_ingame_standby()

                last_state = state

            # Per-state tick logic
            if state == "MENUS":
                time.sleep(POLL_INTERVAL_IDLE)
            elif state == "MATCHMAKING":
                elapsed = time.time() - (self.queue_start_time or time.time())
                current_sec = int(elapsed)
                if current_sec != queue_timer_drawn:
                    self.draw_matchmaking(elapsed)
                    queue_timer_drawn = current_sec
                time.sleep(POLL_INTERVAL_QUEUE)
            elif state == "PREGAME":
                match = self.get_pregame_match()
                if match:
                    teams_now = match.get("Teams")
                    if teams_now != last_teams_snapshot:
                        self.cached_match_display = copy.deepcopy(match)
                        self.draw_match_info(match, is_ingame=False)
                        last_teams_snapshot = copy.deepcopy(teams_now)
                time.sleep(POLL_INTERVAL_PREGAME)
            elif state == "INGAME":
                time.sleep(POLL_INTERVAL_INGAME)
            else:
                time.sleep(POLL_INTERVAL_IDLE)

    # ================================================================
    #  STORE CHECKER (FIXED)
    # ================================================================

    def print_store(self) -> None:
        self.authenticate()
        self._clear()
        self._draw_banner(is_store=True)
        self.console.print("\n[bold white]Fetching Daily Store and Night Market...[/bold white]\n")

        try:
            import requests
            url = f"{self.client.base_url}/store/v3/storefront/{self.client.puuid}"
            res = requests.post(url, headers=self.client.headers, json={})

            if res.status_code != 200:
                self.console.print(f"[bold red][!] API returned error {res.status_code}: {res.text[:100]}[/bold red]")
                return

            storefront = res.json()
            if not storefront:
                self.console.print("[bold red][!] Failed to parse storefront data.[/bold red]")
                return

            # Fetch mapping tables from valorant-api.com
            store_offer_map = self.fetch_store_offers()   # OfferID -> Skin UUID
            skin_name_map = self.fetch_weapon_skins()     # Skin UUID -> Full Name

            # Daily Store
            single_offers = storefront.get("SkinsPanelLayout", {}).get("SingleItemStoreOffers", [])
            if not single_offers:
                self.console.print("[dim]No daily offers found.[/dim]")
            else:
                table = Table(title="DAILY STORE", title_style="bold cyan", title_justify="left", box=box.SQUARE, border_style="cyan", expand=False)
                table.add_column("Cost", justify="right", style="cyan")
                table.add_column("Skin Name", style="white")
                for offer in single_offers:
                    offer_id = offer.get("OfferID")
                    cost = offer.get("Cost", {}).get("85ad13f7-3d1b-5128-9eb2-7cd8ee0b5741", 0)
                    skin_uuid = store_offer_map.get(offer_id)
                    name = skin_name_map.get(skin_uuid, "Unknown Skin") if skin_uuid else "Unknown Skin"
                    table.add_row(f"{cost} VP", name)
                self.console.print(table)
                self.console.print()

            # Night Market
            bonus_store = storefront.get("BonusStore")
            if bonus_store and bonus_store.get("BonusStoreOffers"):
                table = Table(title="NIGHT MARKET", title_style="bold magenta", title_justify="left", box=box.SQUARE, border_style="magenta", expand=False)
                table.add_column("Cost", justify="right", style="magenta")
                table.add_column("Original", justify="right", style="dim strike")
                table.add_column("Skin Name", style="white")

                offers = bonus_store.get("BonusStoreOffers", [])
                for offer in offers:
                    offer_info = offer.get("Offer", {})
                    offer_id = offer_info.get("OfferID")
                    cost_obj = offer.get("DiscountCosts", {}).get("85ad13f7-3d1b-5128-9eb2-7cd8ee0b5741", 0)
                    orig_cost_obj = offer_info.get("Cost", {}).get("85ad13f7-3d1b-5128-9eb2-7cd8ee0b5741", 0)
                    skin_uuid = store_offer_map.get(offer_id)
                    name = skin_name_map.get(skin_uuid, "Unknown Skin") if skin_uuid else "Unknown Skin"
                    table.add_row(f"{cost_obj} VP", f"{orig_cost_obj} VP", name)

                self.console.print(table)
                self.console.print()

            self.console.print("[dim]Done. Exiting...[/dim]")
        except Exception as e:
            self.console.print(f"[bold red][!] Error fetching store: {e}[/bold red]")

    # ================================================================
    #  UTILS
    # ================================================================

    def _fatal(self, msg: str) -> None:
        print(f"\n  {msg}\n")
        sys.exit(1)


# ================================================================
#  MAIN ENTRY
# ================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description=f"V-Core Terminal v{VERSION} - Local API Client")
    parser.add_argument("-l", "--lock", type=str, default=DEFAULT_TARGET_AGENTS, help="Comma-separated list of agents to auto-lock (e.g. 'Jett,Reyna,Omen')")
    parser.add_argument("--store", action="store_true", help="Print the daily store and night market, then exit")
    parser.add_argument("--stealth", action="store_true", help="Appear offline to friends (requires Admin on Windows)")
    parser.add_argument("--unstealth", action="store_true", help="Forcefully remove stealth firewall rules and exit")
    args = parser.parse_args()

    console = Console()

    if args.unstealth:
        if sys.platform == "win32":
            if not is_admin():
                console.print("[bold red]Admin privileges required to remove firewall rules. Requesting elevation...[/bold red]")
                elevate()
            disable_stealth()
            console.print("[bold green]Stealth rules removed. Connection restored.[/bold green]")
        else:
            console.print("[yellow]Unstealth is only supported on Windows. No action taken.[/yellow]")
        return

    if args.stealth:
        if sys.platform == "win32":
            if not is_admin():
                console.print("[bold red]Stealth mode requires Administrator privileges. Requesting elevation...[/bold red]")
                elevate()
            enable_stealth(console)
            atexit.register(disable_stealth)
        else:
            console.print("[yellow]Stealth mode is only supported on Windows. Continuing without stealth.[/yellow]")
            args.stealth = False  # disable flag so we don't try to unstealth later

    if args.store:
        comp = ValorantTerminal(target_agents=[], auto_lock=False, is_stealth=args.stealth)
        comp.print_store()
        return

    agents = [x.strip() for x in args.lock.split(",") if x.strip()]
    if not agents:
        console.print("[bold red]No valid target agents provided.[/bold red]")
        sys.exit(1)

    comp = ValorantTerminal(target_agents=agents, auto_lock=True, is_stealth=args.stealth)

    try:
        comp.run()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        log.critical(f"Unhandled: {e}", exc_info=True)
        print(f"\n  Fatal: {e}\n")
        sys.exit(1)
    finally:
        if keyboard is not None:
            try:
                keyboard.unhook_all()
            except:
                pass
        # Ensure we always clear stealth rules on normal exit if they were requested to be on
        if args.stealth:
            disable_stealth()
        print("\n\n  V-Core Terminal closed.\n")
        sys.exit(0)


if __name__ == "__main__":
    main()