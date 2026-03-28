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
HEARTBEAT_DELAY    = 3600   # delay after conditions clear before first heartbeat
HEARTBEAT_INTERVAL = 10800   # interval between heartbeats during quiet periods

# ── Tempest settings ──────────────────────────────────────────────────────────
TEMPEST_UDP_PORT = 50222    # Tempest hub broadcasts on this port — do not change

# ── Direwolf settings ─────────────────────────────────────────────────────────
DIREWOLF_HOST = "127.0.0.1"
DIREWOLF_PORT = 8001          # KISS TCP port (default Direwolf)

# ── File paths ────────────────────────────────────────────────────────────────
# Windows paths for testing — change to /var/log/... and /var/lib/... on the Pi
LOG_FILE        = "C:/tempest_aprs/tempest_aprs.log"
RAIN_STATE_FILE = "C:/tempest_aprs/rain_state.json"