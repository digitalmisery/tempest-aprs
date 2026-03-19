# rain_tracker.py
"""
Tracks rain accumulation with:
  - Per-observation history for last-hour and 24h calculations
  - Since-midnight total sourced directly from Tempest's local_day_accum
  - Persistent state saved to disk so reboots don't lose data

History storage: deque of (epoch_float, local_day_accum_mm) tuples,
one entry per obs_st, pruned to 25 hours.

All three accumulators derive from the same history deque:

  since_midnight -- directly from Tempest's local_day_accum (resets at
                    local midnight on the device; we mirror that reset)

  last_hour      -- max(local_day_accum in last 60 min)
                    minus the entry just before the 60-min window opened.
                    Falls back to max - min if no pre-window entry exists.
                    Handles midnight resets by detecting drops in the series.

  last_24h       -- sums incremental deltas across the full 25h history,
                    treating any drop in the series as a midnight reset
                    (adds the post-reset value directly instead of a negative).
"""

import json
import os
import time
import logging
from collections import deque
from datetime import datetime
import config

logger = logging.getLogger("tempest_aprs.rain")

# -- Internal state ------------------------------------------------------------
# deque of (epoch_float, local_day_accum_mm) -- one entry per obs_st
_history: deque = deque()
_since_midnight_mm: float = 0.0   # mirrors Tempest's local_day_accum
_last_reset_date:   str   = ""    # "YYYY-MM-DD" of last midnight reset
_last_day_accum:    float = 0.0   # last known local_day_accum from Tempest


def load():
    """Load persisted rain state from disk on startup."""
    global _since_midnight_mm, _last_reset_date, _last_day_accum

    path = config.RAIN_STATE_FILE
    if not os.path.exists(path):
        logger.info("No rain state file found -- starting fresh")
        _last_reset_date = _today_str()
        return

    try:
        with open(path) as f:
            state = json.load(f)
        _since_midnight_mm = state.get("since_midnight_mm", 0.0)
        _last_reset_date   = state.get("last_reset_date", _today_str())
        _last_day_accum    = state.get("last_day_accum", 0.0)

        for entry in state.get("history", []):
            _history.append((entry[0], entry[1]))

        logger.info(
            f"Rain state loaded: {_since_midnight_mm:.2f}mm since midnight "
            f"on {_last_reset_date}, {len(_history)} history entries"
        )
    except Exception as e:
        logger.error(f"Failed to load rain state: {e} -- starting fresh")
        _last_reset_date = _today_str()


def save():
    """Persist rain state to disk."""
    path = config.RAIN_STATE_FILE
    dir_ = os.path.dirname(path)
    if dir_:
        os.makedirs(dir_, exist_ok=True)
    try:
        state = {
            "since_midnight_mm": _since_midnight_mm,
            "last_reset_date":   _last_reset_date,
            "last_day_accum":    _last_day_accum,
            "history":           list(_history),
            "saved_at":          time.time(),
        }
        with open(path, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save rain state: {e}")


def update(local_day_accum_mm: float):
    """
    Called on every obs_st with the Tempest's local_day_accum value (mm).
    The Tempest resets this counter at local midnight automatically.
    """
    global _since_midnight_mm, _last_reset_date, _last_day_accum

    today = _today_str()

    # -- Host-clock midnight rollover ------------------------------------------
    if today != _last_reset_date:
        logger.info(
            f"Midnight rollover: resetting rain counter "
            f"({_last_reset_date} -> {today})"
        )
        _since_midnight_mm = 0.0
        _last_reset_date   = today
        _last_day_accum    = 0.0

    # -- Tempest device midnight reset -----------------------------------------
    # Tempest resets local_day_accum to 0 at midnight. If the value drops
    # more than 0.5mm it's a reset, not a measurement correction.
    if local_day_accum_mm < _last_day_accum - 0.5:
        logger.info(
            f"Tempest local_day_accum reset detected "
            f"({_last_day_accum:.2f} -> {local_day_accum_mm:.2f}mm)"
        )

    _since_midnight_mm = local_day_accum_mm
    _last_day_accum    = local_day_accum_mm

    # -- Append to rolling history ---------------------------------------------
    epoch = time.time()
    _history.append((epoch, local_day_accum_mm))

    # Trim entries older than 25 hours
    cutoff_25h = epoch - (25 * 3600)
    while _history and _history[0][0] < cutoff_25h:
        _history.popleft()

    save()


def get_since_midnight_mm() -> float:
    """Rain accumulated since local midnight (mm)."""
    return _since_midnight_mm


def get_last_hour_mm() -> float:
    """
    Rain accumulated in the last 60 minutes (mm).

    Strategy: find the entry immediately before the 60-min window opened
    and subtract it from the cumulative total gained inside the window.
    This correctly handles the cumulative nature of local_day_accum.

    If no pre-window baseline exists (history covers < 1 hour), fall back
    to accumulation from the oldest available entry.

    Midnight resets are detected as a drop in the series; the post-reset
    portion is added as new accumulation rather than subtracted.
    """
    if not _history:
        return 0.0

    now    = time.time()
    cutoff = now - 3600

    before_window = [(ts, mm) for (ts, mm) in _history if ts < cutoff]
    in_window     = [(ts, mm) for (ts, mm) in _history if ts >= cutoff]

    if not in_window:
        return 0.0

    # Baseline: last reading before window, or first reading inside window
    baseline = before_window[-1][1] if before_window else in_window[0][1]

    total   = 0.0
    prev_mm = baseline
    for (_, mm) in in_window:
        if mm >= prev_mm:
            total += mm - prev_mm
        else:
            # Midnight reset inside the window -- post-reset value is new rain
            total += mm
        prev_mm = mm

    return max(0.0, total)


def get_last_24h_mm() -> float:
    """
    Rain accumulated in the last 24 hours (mm). Spans midnight correctly.

    Sums incremental deltas across all history entries in the 24h window,
    treating any drop in the series as a midnight reset.
    """
    if not _history:
        return 0.0

    now    = time.time()
    cutoff = now - 86400

    before_window = [(ts, mm) for (ts, mm) in _history if ts < cutoff]
    in_window     = [(ts, mm) for (ts, mm) in _history if ts >= cutoff]

    if not in_window:
        return 0.0

    baseline = before_window[-1][1] if before_window else in_window[0][1]

    total   = 0.0
    prev_mm = baseline
    for (_, mm) in in_window:
        if mm >= prev_mm:
            total += mm - prev_mm
        else:
            total += mm
        prev_mm = mm

    return max(0.0, total)


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")
