# rain_tracker.py
"""
Tracks rain accumulation with:
  - Per-minute bucket history for last-hour and 24h calculations
  - Daily total that resets at local midnight
  - Persistent state saved to disk so reboots don't lose data

Data source: obs[12] (rain_interval_mm) — the per-observation-interval rain delta.
We do NOT use obs[18] (local_day_rain_accumulation) because that value is produced
by WeatherFlow's Rain Check algorithm and can lag or remain 0 during active rain,
causing the weather packet to report zero accumulation while rain is actually falling.
By accumulating obs[12] deltas ourselves we stay in sync with the same raw data
source used by the status packet's rain-rate calculation.

Schema version 2: history stores (epoch, delta_mm) tuples — NOT cumulative values.
"""

import json
import os
import time
import logging
from collections import deque
from datetime import datetime
import config

logger = logging.getLogger("tempest_aprs.rain")

STATE_SCHEMA_VERSION = 2

# ── Internal state ────────────────────────────────────────────────────────────
# Each entry is (epoch_float, delta_mm) for one obs_st observation interval.
# Only non-zero intervals are stored to keep history compact.
_history: deque = deque()       # deque of (epoch_float, delta_mm)
_since_midnight_mm: float = 0.0 # running sum of deltas since local midnight
_last_reset_date: str = ""      # "YYYY-MM-DD" of last midnight reset


def load():
    """Load persisted rain state from disk on startup."""
    global _since_midnight_mm, _last_reset_date

    path = config.RAIN_STATE_FILE
    if not os.path.exists(path):
        logger.info("No rain state file found — starting fresh")
        _last_reset_date = _today_str()
        return

    try:
        with open(path) as f:
            state = json.load(f)

        # Schema v1 stored cumulative values in history; discard that history
        # because it is incompatible with delta-based get_* functions.
        schema = state.get("schema_version", 1)
        if schema < STATE_SCHEMA_VERSION:
            logger.info(
                f"Rain state schema v{schema} detected — discarding old history "
                f"(since_midnight total is preserved)"
            )
            _history.clear()
        else:
            for entry in state.get("history", []):
                _history.append((entry[0], entry[1]))

        _since_midnight_mm = state.get("since_midnight_mm", 0.0)
        _last_reset_date   = state.get("last_reset_date", _today_str())

        logger.info(
            f"Rain state loaded: {_since_midnight_mm:.2f} mm since midnight "
            f"on {_last_reset_date}, {len(_history)} history entries"
        )
    except Exception as e:
        logger.error(f"Failed to load rain state: {e} — starting fresh")
        _last_reset_date = _today_str()


def save():
    """Persist rain state to disk."""
    path = config.RAIN_STATE_FILE
    dir_part = os.path.dirname(path)
    if dir_part:
        os.makedirs(dir_part, exist_ok=True)
    try:
        state = {
            "schema_version":    STATE_SCHEMA_VERSION,
            "since_midnight_mm": _since_midnight_mm,
            "last_reset_date":   _last_reset_date,
            "history":           list(_history),
            "saved_at":          time.time(),
        }
        with open(path, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save rain state: {e}")


def update(interval_mm: float):
    """
    Called on every obs_st packet with obs[12] — the rainfall delta for that
    observation interval (mm).  Accumulates into running totals and history.

    Args:
        interval_mm: Rain that fell during this observation interval (mm).
                     Must be non-negative.  Pass 0.0 when no rain occurred.
    """
    global _since_midnight_mm, _last_reset_date

    if interval_mm < 0:
        interval_mm = 0.0

    today = _today_str()

    # ── Midnight reset ────────────────────────────────────────────────────────
    if today != _last_reset_date:
        logger.info(
            f"Midnight rollover: resetting since-midnight counter "
            f"({_last_reset_date} -> {today})"
        )
        _since_midnight_mm = 0.0
        _last_reset_date   = today
        save()

    # ── Accumulate delta ──────────────────────────────────────────────────────
    _since_midnight_mm += interval_mm

    # Only store non-zero intervals so history stays compact
    epoch = time.time()
    if interval_mm > 0:
        _history.append((epoch, interval_mm))

    # Trim entries older than 25 hours
    cutoff_24h = epoch - (25 * 3600)
    while _history and _history[0][0] < cutoff_24h:
        _history.popleft()

    save()


def get_since_midnight_mm() -> float:
    """Rain accumulated since local midnight (mm)."""
    return _since_midnight_mm


def get_last_hour_mm() -> float:
    """Rain accumulated in the last 60 minutes (mm)."""
    if not _history:
        return 0.0
    cutoff = time.time() - 3600
    return sum(mm for (ts, mm) in _history if ts >= cutoff)


def get_last_24h_mm() -> float:
    """Rain accumulated in the last 24 hours (mm). Spans midnight correctly."""
    if not _history:
        return 0.0
    cutoff = time.time() - 86400
    return sum(mm for (ts, mm) in _history if ts >= cutoff)


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")
