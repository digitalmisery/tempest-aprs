#!/usr/bin/env python3
"""
tempest_aprs.py
Listens for Weatherflow Tempest UDP broadcasts on LAN,
converts weather data to APRS packets, and sends them to Direwolf.

Two independent TX loops run as separate threads:

  Weather loop  (TRANSMIT_INTERVAL, default 10 min)
    - Sends a weather packet on schedule
    - Triggered immediately on rain onset
    - After an immediate TX, the interval resets (no double-transmit)

  Status loop   (STATUS_INTERVAL, default 5 min)
    - Active only while currently raining
    - Sends a rain-intensity status packet
    - Suppressed entirely when not raining
    - Also triggered immediately on rain onset alongside weather TX

Both loops share a single DirewolfClient connection. Access is serialised
with a transmit lock so packets don't interleave.
"""

import socket
import json
import time
import threading
import logging
import logging.handlers
from datetime import datetime, timezone
import config
import rain_tracker
import aprs_formatter
import direwolf_client

# ── Logging ───────────────────────────────────────────────────────────────────
logger = logging.getLogger("tempest_aprs")

def setup_logging():
    logger.setLevel(logging.DEBUG)
    fh = logging.handlers.RotatingFileHandler(
        config.LOG_FILE, maxBytes=1_000_000, backupCount=3
    )
    fh.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)


# ── Shared state ──────────────────────────────────────────────────────────────
latest_weather = {}
latest_lock    = threading.Lock()

# Onset trigger events — set by UDP listener, cleared by TX loops
wx_onset_event     = threading.Event()   # rain onset → weather TX
status_onset_event = threading.Event()   # rain onset → status TX
onset_reasons      = []                  # human-readable log strings

# Serialises access to the Direwolf connection so both loops can share it
tx_lock = threading.Lock()


# ── UDP Listener ──────────────────────────────────────────────────────────────

def udp_listener():
    """Receive Tempest UDP broadcasts and update shared state."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", config.TEMPEST_UDP_PORT))
    logger.info(f"Listening for Tempest data on UDP port {config.TEMPEST_UDP_PORT}")

    prev_rain_zero = True

    while True:
        try:
            data, _ = sock.recvfrom(4096)
            msg      = json.loads(data.decode("utf-8"))
            msg_type = msg.get("type", "")

            if msg_type == "obs_st":
                parsed = parse_obs_st(msg)
                if not parsed:
                    continue

                # ── Rain onset ────────────────────────────────────────────────
                # Use obs[12] (rain_interval_mm) — the per-interval delta —
                # NOT obs[18] (rain_accum_local_day).  obs[18] is produced by
                # WeatherFlow's Rain Check algorithm and can remain 0 during
                # active rain, causing all accumulation to report zero while
                # status packets correctly show a non-zero rate.
                rain_mm           = parsed.get("rain_interval_mm", 0.0) or 0.0
                rain_just_started = prev_rain_zero and rain_mm > 0
                prev_rain_zero    = (rain_mm == 0)
                rain_tracker.update(rain_mm)

                with latest_lock:
                    latest_weather.update(parsed)

                # ── Trigger immediate TX if needed ────────────────────────────
                if rain_just_started:
                    logger.info("Rain onset — triggering immediate TX")
                    onset_reasons.append("rain onset")
                    wx_onset_event.set()
                    status_onset_event.set()

                logger.debug(f"obs_st: {parsed}")

            elif msg_type == "rapid_wind":
                obs = msg.get("ob", [])
                if len(obs) >= 3:
                    with latest_lock:
                        latest_weather["wind_speed"]     = obs[1]
                        latest_weather["wind_direction"] = obs[2]

        except json.JSONDecodeError as e:
            logger.warning(f"JSON decode error: {e}")
        except Exception as e:
            logger.error(f"UDP listener error: {e}", exc_info=True)


def parse_obs_st(msg: dict):
    """
    Parse obs_st message. Returns dict or None.
    Key Tempest obs_st array indices (UDP API v171):
      0  Epoch
      1  Wind Lull m/s        2  Wind Avg m/s         3  Wind Gust m/s
      4  Wind Dir °           6  Pressure MB           7  Temp C
      8  Humidity %          11  Solar Radiation W/m²  12  Rain interval mm
      13 Precip type         17  Report interval min   18 Rain local day mm
    """
    try:
        obs = msg["obs"][0]
        result = {
            "timestamp":            obs[0],
            "wind_lull":            obs[1],
            "wind_avg":             obs[2],
            "wind_gust":            obs[3],
            "wind_direction":       obs[4],
            "pressure":             obs[6],
            "temperature":          obs[7],
            "humidity":             obs[8],
            # Solar radiation W/m² (obs index 11)
            "solar_radiation":      obs[11] if len(obs) > 11 and obs[11] is not None else 0,
            # Interval rain (mm) — used to compute rain rate
            "rain_interval_mm":     obs[12] if obs[12] is not None else 0.0,
            # Precipitation type: 0=none, 1=rain, 2=hail, 3=mix
            "precip_type":          int(obs[13]) if len(obs) > 13 and obs[13] is not None else 0,
            "report_interval":      int(obs[17]) if len(obs) > 17 and obs[17] is not None else 1,
            "rain_accum_local_day": obs[18] if len(obs) > 18 and obs[18] is not None else 0.0,
        }
        return result
    except (IndexError, KeyError, TypeError) as e:
        logger.warning(f"parse_obs_st failed: {e}")
        return None


# ── Rain rate calculation ─────────────────────────────────────────────────────

def _current_rain_rate_mm_per_hr() -> float:
    """
    Compute current rain rate in mm/hr from the most recent obs_st interval rain.
    The Tempest reports interval rain in mm over its report interval (default 1 min).
    We scale to mm/hr.
    """
    with latest_lock:
        interval_mm   = latest_weather.get("rain_interval_mm", 0.0) or 0.0
        report_interval_min = latest_weather.get("report_interval", 1) or 1

    # obs index 17 is report interval in minutes — capture it in parse
    # (we fall back to 1 min if not available, which is the Tempest default)
    if interval_mm <= 0:
        return 0.0
    return interval_mm * (60.0 / report_interval_min)


def _is_raining() -> bool:
    """Return True if the station is currently detecting precipitation."""
    with latest_lock:
        return (latest_weather.get("rain_interval_mm", 0.0) or 0.0) > 0


# ── Packet builders ───────────────────────────────────────────────────────────

def _build_weather_packet() -> str:
    with latest_lock:
        wx = dict(latest_weather)
    rain_hour     = rain_tracker.get_last_hour_mm()
    rain_midnight = rain_tracker.get_since_midnight_mm()
    rain_24h      = rain_tracker.get_last_24h_mm()
    return aprs_formatter.build_weather_packet(
        callsign         = config.CALLSIGN,
        ssid             = config.SSID,
        lat              = config.LATITUDE,
        lon              = config.LONGITUDE,
        wx               = wx,
        rain_hour_mm     = rain_hour,
        rain_24h_mm      = rain_24h,
        rain_midnight_mm = rain_midnight,
    )


def _build_status_packet() -> str:
    return aprs_formatter.build_status_packet(
        callsign            = config.CALLSIGN,
        ssid                = config.SSID,
        rain_rate_mm_per_hr = _current_rain_rate_mm_per_hr(),
    )


# ── Weather TX loop ───────────────────────────────────────────────────────────

def weather_tx_loop(dw: direwolf_client.DirewolfClient):
    """
    Sends a weather packet every TRANSMIT_INTERVAL seconds.
    Wakes early on wx_onset_event (rain onset).
    Interval resets after every transmit, scheduled or triggered.
    """
    next_tx = time.time() + config.TRANSMIT_INTERVAL

    while True:
        wait      = max(0, next_tx - time.time())
        triggered = wx_onset_event.wait(timeout=wait)

        if triggered:
            reasons = ", ".join(onset_reasons) if onset_reasons else "onset"
            logger.info(f"Weather TX triggered by: {reasons}")
            wx_onset_event.clear()
        else:
            logger.debug("Scheduled weather TX")

        with latest_lock:
            wx = dict(latest_weather)

        if not wx:
            logger.warning("No weather data yet — skipping weather TX")
            next_tx = time.time() + config.TRANSMIT_INTERVAL
            continue

        try:
            packet = _build_weather_packet()
            logger.info(f"Sending weather packet: {packet}")
            with tx_lock:
                dw.send_packet(packet)
        except Exception as e:
            logger.error(f"Weather TX error: {e}", exc_info=True)

        next_tx = time.time() + config.TRANSMIT_INTERVAL


# ── Status TX loop ────────────────────────────────────────────────────────────

def status_tx_loop(dw: direwolf_client.DirewolfClient):
    """
    Sends a status packet every STATUS_INTERVAL seconds, BUT ONLY while raining.

    When not raining, the loop sleeps in 30-second polling increments waiting for
    conditions to become active again (or an onset event to fire).

    On an onset event the loop wakes immediately and sends right away,
    then resumes the normal STATUS_INTERVAL cadence.
    """
    POLL_INTERVAL = 30   # how often to recheck active state when idle (seconds)
    next_tx = time.time() + config.STATUS_INTERVAL

    while True:
        active = _is_raining()

        if not active:
            # Nothing to report — poll every 30s for conditions to change,
            # but also wake immediately if an onset event fires
            triggered = status_onset_event.wait(timeout=POLL_INTERVAL)
            if triggered:
                status_onset_event.clear()
                logger.info("Status loop woken by onset event — sending immediately")
                # Fall through to transmit below (active will now be True)
            else:
                continue   # still inactive, keep polling

        # Active — wait until next_tx or an onset trigger, whichever is sooner
        wait      = max(0, next_tx - time.time())
        triggered = status_onset_event.wait(timeout=wait)

        if triggered:
            status_onset_event.clear()
            logger.info("Status TX triggered immediately by onset event")

        # Confirm still active before transmitting (conditions may have just cleared)
        if not _is_raining():
            logger.debug("Status TX skipped — conditions cleared before transmit")
            next_tx = time.time() + config.STATUS_INTERVAL
            continue

        try:
            packet = _build_status_packet()
            logger.info(f"Sending status packet: {packet}")
            with tx_lock:
                # Small gap after weather packet if both fire simultaneously
                time.sleep(1)
                dw.send_packet(packet)
        except Exception as e:
            logger.error(f"Status TX error: {e}", exc_info=True)

        next_tx = time.time() + config.STATUS_INTERVAL


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    setup_logging()
    logger.info("=== Tempest APRS starting up ===")
    logger.info(f"Callsign:              {config.CALLSIGN}-{config.SSID}")
    logger.info(f"Weather TX interval:   {config.TRANSMIT_INTERVAL}s")
    logger.info(f"Status TX interval:    {config.STATUS_INTERVAL}s (active only)")

    rain_tracker.load()

    dw = direwolf_client.DirewolfClient(
        host=config.DIREWOLF_HOST,
        port=config.DIREWOLF_PORT
    )

    t_udp    = threading.Thread(target=udp_listener,                  daemon=True, name="udp_listener")
    t_wx     = threading.Thread(target=weather_tx_loop, args=(dw,),   daemon=True, name="wx_tx")
    t_status = threading.Thread(target=status_tx_loop,  args=(dw,),   daemon=True, name="status_tx")

    t_udp.start()
    t_wx.start()
    t_status.start()

    try:
        while True:
            time.sleep(60)
            with latest_lock:
                ts = latest_weather.get("timestamp", 0)
            age = time.time() - ts
            if age > 300:
                logger.warning(
                    f"No Tempest data received in {age:.0f}s — check hub connectivity"
                )
    except KeyboardInterrupt:
        logger.info("Shutting down.")
        rain_tracker.save()


if __name__ == "__main__":
    main()
