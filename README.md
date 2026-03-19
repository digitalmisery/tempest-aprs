# Tempest APRS Weather Gateway

A Python gateway that receives [WeatherFlow Tempest](https://weatherflow.com/tempest-weather-system/) weather station data over your local network and transmits [APRS](http://www.aprs.org/) weather packets over 2-meter ham radio using [Direwolf](https://github.com/wb2osz/direwolf) as a software TNC.

No third-party Python packages required -- uses only the Python standard library.

---

## What It Does

Your Tempest weather station hub broadcasts observation data via UDP on your LAN every minute. This software listens for those broadcasts, converts the meteorological data into properly formatted APRS weather packets, and sends them to Direwolf over a KISS TCP connection. Direwolf modulates the packets into 1200-baud AX.25 audio and keys your radio via PTT.

The result: your personal weather station data appears on the APRS network (visible on sites like [aprs.fi](https://aprs.fi)) and can be received by any APRS-capable station in radio range.

### Packet Types

**Weather packets** are transmitted on a regular schedule (default: every 10 minutes) and include:
- Wind direction, speed, and gust
- Temperature
- Rainfall (last hour, last 24 hours, since midnight)
- Humidity
- Barometric pressure
- Solar radiation (luminosity)

**Status packets** are transmitted during active precipitation (default: every 5 minutes) and report:
- Rain intensity classification (Light / Moderate / Heavy / Very Heavy) using WMO thresholds
- Current rain rate in inches per hour

**Heartbeat packets** are sent during quiet periods (no precipitation) to keep the station visible on the APRS network.

### Smart Transmit Behavior

- **Rain onset** triggers an immediate weather + status packet (no waiting for the next scheduled interval)
- **Status packets are suppressed** when it's not raining, keeping the frequency clear
- **Heartbeat packets** are sent periodically during quiet weather so the station remains visible
- Rain accumulation state is **persisted to disk** so reboots don't lose rainfall totals

---

## Hardware Requirements

| Component | Description |
|---|---|
| **Tempest Weather Station** | [WeatherFlow Tempest](https://weatherflow.com/tempest-weather-system/) with hub on the same LAN |
| **Computer** | Raspberry Pi (production) or Windows PC (development/testing) |
| **Radio** | Any 2m FM radio with a data port (e.g., Alinco DR-135 MK III) |
| **Audio/PTT Interface** | [Digirig Lite](https://digirig.net/product/digirig-lite/) (CM108B USB sound card with PTT via GPIO) |
| **Cable** | Digirig cable appropriate for your radio's data port |

### Tested Hardware

This software was developed and tested with:
- **Radio:** Alinco DR-135 MK III (DB-9 data port)
  - Pin 1 = PKD audio out (RX from radio)
  - Pin 4 = PTT
  - Pin 5 = PKI audio in (TX to radio)
  - Pin 3 tied to GND = 1200 baud mode
- **Interface:** Digirig Lite (USB-C, TRRS connector, CM108B chipset)
- **Computer:** Raspberry Pi (production), Windows 10 PC (development)

---

## Software Requirements

- **Python 3.8+** (no third-party packages needed)
- **Direwolf** ([download/install](https://github.com/wb2osz/direwolf)) -- software TNC / soundcard modem
- A valid **amateur radio license** (Technician class or above in the US)

---

## File Structure

```
tempest_aprs/
├── tempest_aprs.py          # Main application entry point
├── config.py                # All user-editable settings (callsign, location, intervals)
├── aprs_formatter.py        # Builds APRS weather and status packet strings
├── direwolf_client.py       # KISS TCP client and AX.25 UI frame encoder
├── rain_tracker.py          # Rain accumulation with midnight reset and disk persistence
├── tempest_aprs.service     # systemd unit file for Raspberry Pi auto-start
└── README.md                # This file
```

---

## Setup Guide

### Step 1: Clone the Repository

```bash
# Linux / Raspberry Pi
cd /home/pi
git clone https://github.com/digitalmisery/tempest-aprs.git tempest_aprs

# Windows
cd C:\
git clone https://github.com/digitalmisery/tempest-aprs.git tempest_aprs
```

### Step 2: Install Dependencies

#### Linux / Raspberry Pi

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3 direwolf -y
```

That's it. No `pip install` needed -- the code uses only the Python standard library.

#### Windows

1. Install [Python 3.8+](https://www.python.org/downloads/) (check "Add to PATH" during install)
2. Install [Direwolf for Windows](https://github.com/wb2osz/direwolf/releases) -- download the latest release ZIP and extract it

No additional Python packages are needed.

### Step 3: Configure Your Station (`config.py`)

Open `config.py` in a text editor and set these values for your station:

```python
# ── Your callsign ────────────────────────────────────────────────────────────
CALLSIGN = "W9PEM"      # Your FCC callsign
SSID     = "13"          # SSID -13 is the convention for weather stations

# ── Station position (decimal degrees) ───────────────────────────────────────
# Find yours at: https://www.latlong.net/
LATITUDE  =  43.3228     # Positive = North, negative = South
LONGITUDE = -87.9849     # Positive = East,  negative = West

# ── Transmit intervals (seconds) ────────────────────────────────────────────
TRANSMIT_INTERVAL  = 600    # Weather packet: 600 = every 10 min
STATUS_INTERVAL    = 300    # Status packet (rain active only): 300 = every 5 min
HEARTBEAT_DELAY    = 3600   # Seconds after conditions clear before first heartbeat
HEARTBEAT_INTERVAL = 86400  # Seconds between heartbeats during quiet periods

# ── Direwolf connection ─────────────────────────────────────────────────────
DIREWOLF_HOST = "127.0.0.1"
DIREWOLF_PORT = 8001        # KISS TCP port (Direwolf default)

# ── File paths ──────────────────────────────────────────────────────────────
# Windows:
LOG_FILE        = "C:/tempest_aprs/tempest_aprs.log"
RAIN_STATE_FILE = "C:/tempest_aprs/rain_state.json"

# Linux / Raspberry Pi (uncomment these, comment out the Windows paths):
# LOG_FILE        = "/var/log/tempest_aprs.log"
# RAIN_STATE_FILE = "/var/lib/tempest_aprs/rain_state.json"
```

#### Configuration Notes

| Setting | What It Controls | Recommended |
|---|---|---|
| `CALLSIGN` | Your amateur radio callsign | Required |
| `SSID` | APRS SSID (appended as `-13`) | `13` (weather station convention) |
| `LATITUDE` / `LONGITUDE` | Station position on the APRS map | Your exact location |
| `TRANSMIT_INTERVAL` | How often weather packets are sent | `600` (10 min) for RF, `300` (5 min) if low traffic |
| `STATUS_INTERVAL` | How often rain status packets are sent during precipitation | `300` (5 min) |
| `DIREWOLF_PORT` | Must match `KISSPORT` in your Direwolf config | `8001` (default) |

### Step 4: Configure Direwolf

Direwolf needs its own configuration file. The key settings are the audio device, PTT method, and the KISS TCP port.

#### Linux / Raspberry Pi (Digirig Lite + GPIO PTT)

Create or edit `~/direwolf.conf`:

```
# ── Station ID ──────────────────────────────────────────────────────────────
MYCALL YOURCALL-13

# ── Audio device ────────────────────────────────────────────────────────────
# Find your Digirig with: aplay -l
# Look for "USB Audio Device" or "CM108" -- note the card number
ADEVICE plughw:1,0
ACHANNELS 1

# ── Channel 0 ──────────────────────────────────────────────────────────────
CHANNEL 0
MODEM 1200

# ── PTT ─────────────────────────────────────────────────────────────────────
# Option A: CM108 GPIO on the Digirig Lite (recommended -- no GPIO wiring needed)
PTT CM108

# Option B: Raspberry Pi GPIO pin (if wired to radio PTT via transistor)
# PTT GPIO 25

# ── KISS TCP port (must match DIREWOLF_PORT in config.py) ──────────────────
KISSPORT 8001
```

**Finding your audio device:**
```bash
aplay -l
# Example output:
# card 1: Device [USB Audio Device], device 0: USB Audio [USB Audio]
# → Use: ADEVICE plughw:1,0
```

**Adjusting TX audio level:**
```bash
alsamixer -c 1    # Replace 1 with your card number
# Adjust Speaker/PCM level -- start around 50%, fine-tune for clean decode
```

#### Windows (Digirig Lite)

Create or edit `direwolf.conf` in your Direwolf installation directory:

```
# ── Station ID ──────────────────────────────────────────────────────────────
MYCALL YOURCALL-13

# ── Audio device ────────────────────────────────────────────────────────────
# Use the Digirig's audio device name (find it in Windows Sound settings)
ADEVICE "Digirig" "Digirig"
ACHANNELS 1

# ── Channel 0 ──────────────────────────────────────────────────────────────
CHANNEL 0
MODEM 1200

# ── PTT via CM108 GPIO (Digirig Lite) ──────────────────────────────────────
PTT CM108

# ── KISS TCP port ──────────────────────────────────────────────────────────
KISSPORT 8001
```

**Finding the audio device name on Windows:**
1. Open **Settings > System > Sound**
2. Look for the Digirig device under Input and Output
3. The name shown (e.g., `"Digirig"` or `"USB Audio Device"`) goes in the `ADEVICE` line
4. Format: `ADEVICE "output-device-name" "input-device-name"`

### Step 5: Create Required Directories (Linux Only)

```bash
sudo mkdir -p /var/lib/tempest_aprs
sudo chown pi:pi /var/lib/tempest_aprs
sudo touch /var/log/tempest_aprs.log
sudo chown pi:pi /var/log/tempest_aprs.log
```

On Windows, the default paths write to the project directory (`C:/tempest_aprs/`) and no setup is needed.

---

## Running the Software

### Quick Start (Both Platforms)

1. **Start Direwolf first** (in its own terminal window)
2. **Then start tempest_aprs** (in a second terminal)
3. Wait for the first Tempest observation (~1 minute)
4. The first weather packet will transmit as soon as data arrives

### Windows

**Terminal 1 -- Direwolf:**
```powershell
cd "C:\path\to\direwolf"
direwolf -c direwolf.conf
```

**Terminal 2 -- Tempest APRS:**
```powershell
cd C:\tempest_aprs
python tempest_aprs.py
```

> **Note:** On Windows, do not click inside the PowerShell window while the software is running. Windows "QuickEdit" mode pauses the process when the console is clicked, which can freeze a packet mid-transmit. The software automatically disables QuickEdit on startup, but avoid clicking in the terminal as a precaution.

### Linux / Raspberry Pi (Manual)

**Terminal 1 -- Direwolf:**
```bash
direwolf -c ~/direwolf.conf
```

**Terminal 2 -- Tempest APRS:**
```bash
cd /home/pi/tempest_aprs
python3 tempest_aprs.py
```

### Linux / Raspberry Pi (Auto-Start with systemd)

For unattended operation (e.g., headless Raspberry Pi), install both Direwolf and tempest_aprs as systemd services.

**First, create a Direwolf service** (`/etc/systemd/system/direwolf.service`):
```ini
[Unit]
Description=Direwolf Software TNC
After=sound.target

[Service]
Type=simple
User=pi
ExecStart=/usr/bin/direwolf -c /home/pi/direwolf.conf
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Then install the tempest_aprs service:**
```bash
sudo cp /home/pi/tempest_aprs/tempest_aprs.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable direwolf
sudo systemctl enable tempest_aprs
sudo systemctl start direwolf
sudo systemctl start tempest_aprs
```

**Checking status:**
```bash
sudo systemctl status tempest_aprs
sudo systemctl status direwolf
journalctl -u tempest_aprs -f     # live log tail
```

**Restarting after config changes:**
```bash
sudo systemctl restart tempest_aprs
```

---

## Verifying It Works

1. **Console output** -- You should see log lines like:
   ```
   Listening for Tempest data on UDP port 50222
   Connected to Direwolf KISS TCP at 127.0.0.1:8001
   First obs_st received -- TX loops will transmit immediately
   Sending weather packet: W9PEM-13>APTEMP,WIDE1-1:@191435z4319.37N/08759.09W_180/003g005t048...
   ```

2. **Direwolf window** -- You should see the packet being transmitted and your radio keying up

3. **APRS.fi** -- If there's an iGate in range, search for your callsign at [aprs.fi](https://aprs.fi) within a few minutes of the first transmission

4. **Local APRS receiver** -- Any nearby APRS-capable radio should decode your packets

---

## APRS Packet Format Reference

### Weather Packet

```
W9PEM-13>APTEMP,WIDE1-1:@191435z4319.37N/08759.09W_180/003g005t048r000p012P012h72b10201L342
```

| Field | Meaning | Units |
|---|---|---|
| `@191435z` | Timestamp (19th, 14:35 UTC) | Day + HHMMZ |
| `4319.37N/08759.09W` | Position | DDMM.MM N/S / DDDMM.MM E/W |
| `_180/003` | Wind direction / speed | Degrees / mph |
| `g005` | Wind gust | mph |
| `t048` | Temperature | Fahrenheit |
| `r000` | Rain, last hour | Hundredths of inch |
| `p012` | Rain, last 24 hours | Hundredths of inch |
| `P012` | Rain, since midnight | Hundredths of inch |
| `h72` | Humidity (00 = 100%) | Percent |
| `b10201` | Barometric pressure | Tenths of millibar |
| `L342` | Luminosity 0-999 W/m² | W/m² (lowercase `l` = 1000-1999) |

### Status Packet (During Rain)

```
W9PEM-13>APTEMP,WIDE1-1:>Rain: Moderate (0.18in/hr)
```

### Heartbeat Packet (Quiet Weather)

```
W9PEM-13>APTEMP,WIDE1-1:>Tempest Weather Station to APRS - made in Python using Claude AI
```

---

## How It Works (Architecture)

```
┌──────────────┐    UDP broadcast    ┌────────────────┐
│   Tempest    │ ──────────────────> │  UDP Listener  │
│  Hub (LAN)   │    port 50222       │    Thread       │
└──────────────┘                     └───────┬────────┘
                                             │
                                    updates shared state
                                             │
                              ┌──────────────┼──────────────┐
                              │              │              │
                     ┌────────▼───────┐  ┌───▼────────┐  ┌─▼──────────┐
                     │  Weather TX    │  │ Status TX  │  │   Rain     │
                     │  Loop Thread   │  │ Loop Thread│  │  Tracker   │
                     │  (10 min)      │  │ (5 min)    │  │            │
                     └────────┬───────┘  └───┬────────┘  └────────────┘
                              │              │
                         tx_lock serializes sends
                              │              │
                     ┌────────▼──────────────▼────────┐
                     │      Direwolf Client           │
                     │   (KISS TCP → AX.25 frames)    │
                     └────────────────┬───────────────┘
                                      │
                              KISS TCP port 8001
                                      │
                     ┌────────────────▼───────────────┐
                     │         Direwolf               │
                     │   (software TNC / modem)       │
                     └────────────────┬───────────────┘
                                      │
                              audio + PTT (Digirig Lite)
                                      │
                     ┌────────────────▼───────────────┐
                     │        2m FM Radio             │
                     │    (e.g., Alinco DR-135)       │
                     └────────────────────────────────┘
```

### Thread Model

- **UDP Listener** -- Receives Tempest broadcasts, parses observation data, updates shared state, detects rain onset
- **Weather TX Loop** -- Sends a weather packet every `TRANSMIT_INTERVAL` seconds; wakes immediately on rain onset
- **Status TX Loop** -- Active only during precipitation; sends rain intensity every `STATUS_INTERVAL` seconds; sends periodic heartbeats during quiet weather
- All threads share one Direwolf connection, serialized with a transmit lock

### Rain Tracking

The `rain_tracker` module maintains a rolling 25-hour history of rain observations:
- **Since midnight** -- Sourced directly from the Tempest's own `local_day_accum` field, which resets at local midnight
- **Last hour** -- Computed from the rolling history, handling midnight resets
- **Last 24 hours** -- Summed from incremental deltas across the full history window
- State is **persisted to `rain_state.json`** on every observation so reboots don't lose data

---

## Troubleshooting

| Symptom | What to Check |
|---|---|
| No Tempest data (`No obs_st received`) | Is the Tempest hub on the same LAN/subnet? Try: `sudo tcpdump -i eth0 udp port 50222` (Linux) or check Windows Firewall |
| `Failed to connect to Direwolf KISS port` | Is Direwolf running? Is `KISSPORT 8001` in your direwolf.conf? |
| Radio not keying | Check PTT config in direwolf.conf (`PTT CM108` for Digirig Lite) |
| Garbled audio / poor decode | Adjust TX audio level (`alsamixer -c 1` on Linux, or Windows Sound mixer) |
| Rain totals wrong after reboot | Check that `RAIN_STATE_FILE` path is writable |
| `No Tempest data received in Xs` warning | Hub may be powered off or network issue -- the software will resume automatically when data returns |
| Windows terminal freezes | Don't click in the PowerShell window (QuickEdit mode) -- the software disables this on startup but avoid clicking as a precaution |
| WSL2 doesn't receive Tempest data | WSL2 cannot receive LAN UDP broadcasts -- run Python natively on Windows for testing |

### Checking Tempest UDP Traffic

**Linux:**
```bash
sudo tcpdump -i eth0 udp port 50222
# You should see a packet arrive approximately every minute
```

**Windows (PowerShell):**
```powershell
# Quick Python one-liner to verify Tempest broadcasts
python -c "import socket; s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(('',50222)); print(s.recvfrom(4096)[0].decode())"
```

---

## Network Notes

- The Tempest hub broadcasts UDP on port **50222** to the LAN broadcast address
- The computer running this software must be on the **same subnet** as the Tempest hub
- **No internet connection is required** -- all communication is local (Tempest UDP) and RF (APRS)
- On Windows, ensure the **Windows Firewall** allows inbound UDP on port 50222 for Python
- **WSL2 cannot receive LAN UDP broadcasts** due to its virtual network adapter -- run Python natively on Windows

---

## License

This project is released under the [MIT License](LICENSE).

---

## Acknowledgments

- [WeatherFlow](https://weatherflow.com/) for the Tempest weather station and its open UDP API
- [Direwolf](https://github.com/wb2osz/direwolf) by WB2OSZ for the excellent software TNC
- [Digirig](https://digirig.net/) for the compact USB audio/PTT interface
- Built with the assistance of [Claude AI](https://claude.ai/) by Anthropic
