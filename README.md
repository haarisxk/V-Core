# V-Core Terminal: Local API Companion for Valorant

[![License: Custom](https://img.shields.io/badge/License-Custom-blue.svg)](LICENSE)
![Platform: Windows](https://img.shields.io/badge/Platform-Windows%2010%2F11-lightgrey.svg)
![Built With: Python](https://img.shields.io/badge/Built%20With-Python%203.10+-green.svg)

**V-Core Terminal** is a professional, lightweight command-line companion tool designed for Valorant. Operating exclusively via local Riot Client HTTP endpoints, V-Core Terminal provides advanced lobby insights and presence manipulation without utilizing traditional third-party methods. It is entirely free of memory reading, memory writing, screen scraping, or code injection, ensuring a secure and optimized experience.

---

## ✨ Overview & Core Features

- **Intelligent Agent Auto-Locker**: Features a high-speed, lightweight waterfall auto-selection algorithm. If your primary agent is locked by another player, the system instantly defaults to your pre-configured secondary agent to ensure you always secure a preferred role.
- **Advanced Match Dashboard**: Interfaces directly with local endpoints to extract and display hidden MMR, exact numerical rank points (RR), and unmasked player names during Agent Select. It also accurately identifies pre-made party stacks (Duos, Trios, 5-stacks) before the match begins.
- **Dynamic Stealth Mode (Presence Spoofing)**: Configures temporary, outbound Windows Firewall rules to strategically block the XMPP chat ports (TCP 5222, 5223). This drops your presence packets, allowing you to appear completely offline to your friends list. Includes an integrated, in-game global hotkey (`F8`) to dynamically toggle this state without tabbing out.
- **Terminal Storefront Integration**: Fetches and securely displays your current Daily Store and Night Market rotations directly within the command-line interface, eliminating the need to launch the heavy game client just to check skins.

---

## 🎯 Primary Use Cases

- **Content Creators & Streamers**: Utilize Stealth Mode to appear offline, preventing targeted stream sniping, unwanted friend requests, or lobby invites while recording or broadcasting.
- **Competitive Optimization**: Leverage the Match Dashboard to gain critical pre-game insights into the matchmaking lobby, identifying premade groups and assessing the MMR spread of both teammates and opponents.
- **Hardware-Constrained Environments**: Check daily shop rotations or Night Market drops instantly through a low-overhead terminal without stressing system resources by launching the full 3D game engine.

---

## ⚙️ System Requirements

- **Operating System**: Windows 10 or Windows 11
- **Environment**: Python 3.10 or higher
- **Dependencies**: Listed in `requirements.txt` (`valclient`, `rich`, `keyboard`)

---

## 🚀 Installation & Setup

> [!WARNING]
> **Important Notice:** V-Core Terminal requires an active local authentication lockfile. You must launch Valorant or the Riot Client *before* executing the script so the API endpoints can be successfully authenticated.

### Step 1: Install Python
Download and install [Python 3.10+](https://www.python.org/downloads/). 
*Crucial: During the installation process, ensure you check the box that says **"Add Python to PATH"**.*

### Step 2: Download the Release
Download the latest `V-Core-v1.0.0.zip` from the [Releases page](https://github.com/haarisxk/V-Core/releases) and extract the folder to your preferred location.

### Step 3: Install Dependencies
Open a Command Prompt inside the extracted folder and execute the following command to install the required Python libraries:
```cmd
pip install -r requirements.txt
```

---

## 💻 Usage Commands

**Run with default auto-locker:**
```cmd
python vcore.py
```

**Run with specific target agents:**
```cmd
python vcore.py --lock "Jett, Reyna, Omen"
```

**Run in Stealth Mode (Appear Offline):**
> [!NOTE]
> *Requires Administrator privileges to modify outbound Windows Firewall rules.*
```cmd
python vcore.py --stealth
```

**View Daily Store & Night Market:**
```cmd
python vcore.py --store
```

---

## 📁 Directory Structure

```text
V-Core/
├── vcore.py          # Main executable Python script
├── requirements.txt  # Dependency manifest
├── logs/             # Local diagnostic and error logs
├── tools/            # Developer tools for endpoint probing and JSON decoding
└── README.md         # Project documentation
```

---

## 🤝 Support & Feedback

If you encounter any bugs, crashes, or API handshake errors, please open a ticket on the [GitHub Issues tab](https://github.com/haarisxk/V-Core/issues). 

> [!TIP]
> When reporting an issue, please copy and paste your terminal output or any error tracebacks to expedite troubleshooting and fixes!

---

## ⚖️ Disclaimer

**Developer**: Haaris Khan

Users are free to utilize this software however they choose, but they do so entirely at their own risk. The developer assumes no liability for how this software is implemented or deployed. If this software is utilized in competitive video games or alongside anti-cheat systems and results in account penalties, that is solely the responsibility of the end user.
