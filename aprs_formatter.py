# aprs_formatter.py
"""
Builds APRS weather and status packets per the APRS Protocol Reference v1.0.1

Weather packet example:
  W9PEM-13>APTEMP,WIDE1-1:@221345z4319.37N/08759.09W_270/004g007t072r000p031P031h50b09900

Status packet example:
  W9PEM-13>APTEMP,WIDE1-1:>Rain: Moderate (0.18in/hr)

Weather field reference:
  _ddd/sss  wind direction (degrees) / wind speed (mph, 3 digits)
  gGGG      wind gust (mph, 3 digits)
  tTTT      temperature (°F, 3 digits, may be negative: t-07)
  rRRR      rainfall last hour (hundredths of inch, 3 digits)
  pPPP      rainfall last 24h (hundredths of inch, 3 digits)
  PPPP      rainfall since midnight (hundredths of inch, 3 digits)
  hHH       humidity (%, 2 digits; 00 = 100%)
  bBBBBB    barometric pressure (tenths of mbar, 5 digits)
  LLLL      luminosity 0–999 W/m² (capital L)
  lLLL      luminosity 1000–1999 W/m² (lowercase l, leading 1 dropped)

Rain intensity thresholds (mm/hr) — WMO standard:
  None        0
  Light     < 2.5
  Moderate  < 7.6
  Heavy     < 50.0
  Very Heavy  >= 50.0
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger("tempest_aprs.formatter")

# APRS destination — APTEMP identifies this as a Tempest weather station
APRS_DEST = "APTEMP"

# Quiet-period heartbeat — sent when not raining,
# then every 24 hours while conditions remain quiet
HEARTBEAT_TEXT = "Tempest Weather Station to APRS - made in Python using Claude AI"


# ── Weather packet ────────────────────────────────────────────────────────────

def build_weather_packet(
    callsign: str,
    ssid: str,
    lat: float,
    lon: float,
    wx: dict,
    rain_hour_mm: float,
    rain_24h_mm: float,
    rain_midnight_mm: float,
) -> str:
    """
    Returns a complete APRS weather packet string ready to send to Direwolf.
    All Tempest values are metric; this function converts to APRS units.
    Destination is APTEMP to identify Tempest-sourced weather data.

    Luminosity encoding per APRS spec:
      L = solar radiation 0–999 W/m²    (capital L, 3 digits)
      l = solar radiation 1000–1999 W/m² (lowercase l, 3 digits with leading 1 dropped)
      Values >= 2000 W/m² are physically impossible at Earth's surface and clamped to l999.
    """
    source = f"{callsign}-{ssid}"

    # Timestamp (DHM zulu format)
    now_utc   = datetime.now(timezone.utc)
    timestamp = now_utc.strftime("%d%H%Mz")

    # Position encoding
    lat_str = _encode_lat(lat)
    lon_str = _encode_lon(lon)

    # Unit conversions
    wind_dir      = int(round(wx.get("wind_direction", 0)))
    wind_speed    = _ms_to_mph(wx.get("wind_avg",  0.0))
    wind_gust     = _ms_to_mph(wx.get("wind_gust", 0.0))
    temp_f        = _c_to_f(wx.get("temperature", 0.0))
    humidity      = int(round(wx.get("humidity", 0.0)))
    pressure      = wx.get("pressure", 0.0)
    solar_wm2     = int(round(wx.get("solar_radiation", 0) or 0))

    rain_hour_in     = _mm_to_hundredths_inch(rain_hour_mm)
    rain_24h_in      = _mm_to_hundredths_inch(rain_24h_mm)
    rain_midnight_in = _mm_to_hundredths_inch(rain_midnight_mm)

    # Clamp values
    wind_dir   = max(0, min(360, wind_dir))
    wind_speed = max(0, min(999, wind_speed))
    wind_gust  = max(0, min(999, wind_gust))

    # Temperature (Python's :03d correctly handles negative values e.g. -07)
    temp_str = f"t{int(temp_f):03d}"

    # Humidity: APRS encodes 100% as "00"
    hum_str = "h00" if humidity >= 100 else f"h{humidity:02d}"

    # Pressure in tenths of mbar
    baro_str = f"b{int(round(pressure * 10)):05d}"

    # Luminosity per APRS spec:
    #   L = 0–999 W/m²  (capital L + 3 digits)
    #   l = 1000–1999 W/m² (lowercase l + 3 digits, leading 1 dropped)
    #   Values >= 2000 are clamped to l999 (physically unreachable at surface)
    solar_wm2 = max(0, min(1999, solar_wm2))
    if solar_wm2 >= 1000:
        lum_str = f"l{solar_wm2 - 1000:03d}"
    else:
        lum_str = f"L{solar_wm2:03d}"

    wx_str = (
        f"_{wind_dir:03d}/{wind_speed:03d}"
        f"g{wind_gust:03d}"
        f"{temp_str}"
        f"r{rain_hour_in:03d}"
        f"p{rain_24h_in:03d}"
        f"P{rain_midnight_in:03d}"
        f"{hum_str}"
        f"{baro_str}"
        f"{lum_str}"
    )

    packet = f"{source}>{APRS_DEST},WIDE1-1:@{timestamp}{lat_str}/{lon_str}{wx_str}"
    logger.debug(f"Built weather packet: {packet}")
    return packet


# ── Status packet ─────────────────────────────────────────────────────────────

def build_status_packet(
    callsign: str,
    ssid: str,
    rain_rate_mm_per_hr: float,
) -> str:
    """
    Returns an APRS Status packet ('>') with rain intensity.

    Rain must be active before calling this function —
    the caller (tempest_aprs.py) is responsible for that gate.
    """
    source = f"{callsign}-{ssid}"

    if rain_rate_mm_per_hr > 0:
        intensity = _rain_intensity_label(rain_rate_mm_per_hr)
        rate_iph  = rain_rate_mm_per_hr / 25.4          # mm/hr → inches/hr
        status_text = f"Rain: {intensity} ({rate_iph:.2f}in/hr)"
    else:
        status_text = "No active wx events"

    packet = f"{source}>{APRS_DEST},WIDE1-1:>{status_text}"
    logger.debug(f"Built status packet: {packet}")
    return packet


# ── Heartbeat packet ──────────────────────────────────────────────────────────

def build_heartbeat_packet(callsign: str, ssid: str) -> str:
    """
    Returns a quiet-period APRS Status packet sent when not raining,
    and every 24 hours thereafter while conditions remain quiet.
    Identifies the station and software.
    """
    source = f"{callsign}-{ssid}"
    packet = f"{source}>{APRS_DEST},WIDE1-1:>{HEARTBEAT_TEXT}"
    logger.debug(f"Built heartbeat packet: {packet}")
    return packet


# ── Rain intensity classification ─────────────────────────────────────────────

def _rain_intensity_label(rate_mm_per_hr: float) -> str:
    """
    Classify rain rate into a human-readable intensity label.
    Thresholds follow WMO / NWS standard definitions:
      None        = 0
      Light       < 2.5  mm/hr   (< 0.10 in/hr)
      Moderate    < 7.6  mm/hr   (< 0.30 in/hr)
      Heavy       < 50.0 mm/hr   (< 1.97 in/hr)
      Very Heavy  >= 50.0 mm/hr
    """
    if rate_mm_per_hr <= 0:
        return "None"
    elif rate_mm_per_hr < 2.5:
        return "Light"
    elif rate_mm_per_hr < 7.6:
        return "Moderate"
    elif rate_mm_per_hr < 50.0:
        return "Heavy"
    else:
        return "Very Heavy"


# ── Coordinate encoding ───────────────────────────────────────────────────────

def _encode_lat(lat: float) -> str:
    """Encode decimal latitude to APRS DDMM.MMN/S format."""
    hemi = "N" if lat >= 0 else "S"
    lat  = abs(lat)
    deg  = int(lat)
    mins = (lat - deg) * 60
    return f"{deg:02d}{mins:05.2f}{hemi}"


def _encode_lon(lon: float) -> str:
    """Encode decimal longitude to APRS DDDMM.MME/W format."""
    hemi = "E" if lon >= 0 else "W"
    lon  = abs(lon)
    deg  = int(lon)
    mins = (lon - deg) * 60
    return f"{deg:03d}{mins:05.2f}{hemi}"


# ── Unit conversions ──────────────────────────────────────────────────────────

def _ms_to_mph(ms: float) -> int:
    return int(round(ms * 2.23694))

def _c_to_f(c: float) -> float:
    return (c * 9 / 5) + 32

def _mm_to_hundredths_inch(mm: float) -> int:
    """mm → hundredths of an inch, clamped 0–999."""
    return max(0, min(999, int(round(mm * 3.93701))))
