# V-Core Terminal

A command-line interface tool for Valorant utilizing the local Riot Client API.

Unlike traditional third-party applications, V-Core Terminal operates strictly via the command line and interfaces exclusively with the official Local Riot Client API endpoints. It does not utilize memory reading, memory writing, screen scraping, or code injection.

## Features

- **Agent Auto-Locker**: A lightweight waterfall auto-selection tool. If the primary agent is taken, it automatically attempts to lock the secondary agent.
- **Match Dashboard**: Interfaces with local endpoints to display hidden MMR, exact rank points, unmask hidden player names in Agent Select, and identify pre-made party stacks (Duo, Trio, 5-stack).
- **Stealth Mode**: Configures temporary outbound Windows Firewall rules to block the XMPP chat port (TCP 5222, 5223), dropping presence packets and making the client appear offline to the friends list. Includes an in-game global hotkey (F8) to toggle this state dynamically.
- **Store Interface**: Fetches and displays the current Daily Store and Night Market rotations directly within the terminal interface.

## Usage

Valorant or the Riot Client must be running prior to execution to generate the local authentication lockfile.

**Run with default auto-locker:**
```cmd
python vcore.py
```

**Run with specific target agents:**
```cmd
python vcore.py --lock "Jett, Reyna, Omen"
```

**Run in Stealth Mode (Appear Offline):**
*(Requires Administrator privileges to modify Windows Firewall)*
```cmd
python vcore.py --stealth
```

**View Daily Store & Night Market:**
```cmd
python vcore.py --store
```

## Directory Structure
- `vcore.py`: Main executable script.
- `docs/`: API audits and reference documentation.
- `logs/`: Diagnostic logs.
- `tools/`: Extracted JSON schemas and endpoint probing scripts.
