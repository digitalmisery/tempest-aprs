# config.py
# ── Edit these values for your station ───────────────────────────────────────

# Your FCC callsign and SSID
# SSID -13 is conventional for weather stations
CALLSIGN = "W9PEM"
SSID     = "13"

# Station position — decimal degrees
# Find yours at: https://www.latlong.net/
LATITUDE  =  43.3228   # positive = North, negative = South
LONGITUDE = -87.9849   # positive = East,  negative = West

# ── Station Elevation & Calibration ───────────────────────────────────────────

# Pressure offset in millibars (mbar / hPa).
# The Tempest reports absolute station pressure. To send Altimeter or 
# Sea-Level pressure via APRS, calculate the offset for your current elevation 
# and enter it here. (e.g., if you are at 800ft, you might need around +29.5 mb)
PRESSURE_OFFSET_MB = 30.0

# ── Output Routing ────────────────────────────────────────────────────────────

# Select where to send the APRS packets. Options: "RF", "APRS-IS", or "BOTH"
OUTPUT_MODE = "RF"

# ── Transmit intervals ────────────────────────────────────────────────────────

# How often to send the APRS weather packet (seconds)
# 600 = every 10 minutes  |  300 = every 5 min  |  1200 = every 20 min
TRANSMIT_INTERVAL = 600

# How often to send the status packet WHILE ACTIVE (seconds)
# "Active" means: currently raining
# Status packets are suppressed entirely when not raining
# 300 = every 5 minutes  |  180 = every 3 min  |  600 = every 10 min
STATUS_INTERVAL = 300

# How long after conditions clear before sending a heartbeat status packet,
# and the interval between subsequent heartbeats during quiet periods (seconds)
# 10800 = 3 hours  |  86400 = 24 hours
HEARTBEAT_DELAY    = 60   # delay after conditions clear before first heartbeat
HEARTBEAT_INTERVAL = 10800   # interval between heartbeats during quiet periods

# ── Tempest settings ──────────────────────────────────────────────────────────
TEMPEST_UDP_PORT = 50222    # Tempest hub broadcasts on this port — do not change

# ── Direwolf settings ─────────────────────────────────────────────────────────
DIREWOLF_HOST = "127.0.0.1"
DIREWOLF_PORT = 8001          # KISS TCP port (default Direwolf)

# ── APRS-IS settings (Used if OUTPUT_MODE is "APRS-IS" or "BOTH") ─────────────
APRS_IS_SERVER = "rotate.aprs2.net"
APRS_IS_PORT   = 14580

# ── File paths ────────────────────────────────────────────────────────────────
# Windows paths for testing — change to /var/log/... and /var/lib/... on the Pi
LOG_FILE        = "/var/log/tempest_aprs.log"
RAIN_STATE_FILE = "/var/lib/tempest_aprs/rain_state.json"
