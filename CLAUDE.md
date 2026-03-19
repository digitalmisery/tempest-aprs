# CLAUDE.md — tempest-aprs project memory

## Project Overview
Python gateway that receives Weatherflow Tempest weather station data over LAN (UDP) and transmits APRS packets over 2m ham radio via Direwolf software TNC.

**Callsign:** W9PEM-13 (SSID -13 = weather station convention)
**Station:** Milwaukee, WI area (43.1937°N, 87.5909°W)

---

## Architecture

### Two independent TX threads
- **Weather TX loop** — sends weather packet every `TRANSMIT_INTERVAL` (600s default); wakes early on rain/lightning onset
- **Status TX loop** — sends rain + lightning status packet every `STATUS_INTERVAL` (300s default); **active only** when raining or lightning detected in last 3hr; otherwise dormant (polls every 30s)
- Both share one `DirewolfClient` instance, serialised with `tx_lock`
- 1-second sleep between packets when both fire simultaneously

### Thread/event model
- `wx_onset_event` (threading.Event) — set by UDP listener on rain onset or lightning onset; wakes weather TX loop early
- `status_onset_event` (threading.Event) — same triggers; wakes status TX loop early
- `latest_lock` (threading.Lock) — guards `latest_weather` dict and `lightning_state` dict
- `tx_lock` (threading.Lock) — serialises Direwolf sends

---

## File Structure

| File | Role |
|---|---|
| `tempest_aprs.py` | Entry point; UDP listener thread + two TX loop threads |
| `config.py` | All user-editable settings |
| `aprs_formatter.py` | Builds APRS weather and status packet strings |
| `direwolf_client.py` | KISS TCP client; AX.25 UI frame encoder |
| `rain_tracker.py` | Rain accumulation, midnight reset, disk persistence |
| `tempest_aprs.service` | systemd unit for Raspberry Pi |

---

## Key Implementation Details

### Tempest UDP (obs_st array indices)
```
[0]  epoch
[1]  wind lull m/s      [2]  wind avg m/s       [3]  wind gust m/s
[4]  wind direction °
[6]  pressure mbar      [7]  temp °C             [8]  humidity %
[11] solar radiation W/m²
[12] rain interval mm   [13] precip type (0=none,1=rain,2=hail,3=mix)
[14] lightning dist km  [15] lightning count (per interval)
[17] report interval min
[18] local day rain accum mm  ← Tempest resets at local midnight
```
Also handles `evt_strike` (real-time, fires at each detected strike) and `rapid_wind`.

### Rain rate
`rain_interval_mm × (60 / report_interval_min)` → mm/hr

### Rain intensity labels (WMO thresholds)
- None: 0, Light: <2.5, Moderate: <7.6, Heavy: <50.0, Very Heavy: ≥50.0 mm/hr

### Lightning onset
- Gap from `last_strike_epoch` ≥ `LIGHTNING_GAP_THRESHOLD` (10800s = 3hr default)
- Triggers immediate weather + status TX
- `strike_history` is a list of epoch floats; pruned to rolling 3hr window

### Rain onset
- Detected when `prev_rain_zero=True` and new `rain_accum_local_day > 0`
- Triggers immediate weather TX only (status loop handles its own onset)

---

## APRS Packet Formats

### Weather packet destination: `APTEMP`
```
W9PEM-13>APTEMP,WIDE1-1:@101851z4311.62N/08735.45W_270/004g008t071r005p021P012h55b10132L735
```
- `_ddd/sss` wind dir/speed (mph), `gGGG` gust, `tTTT` temp °F
- `rRRR` rain last hour, `pPPP` rain last 24h, `PPPP` rain since midnight (all hundredths inch)
- `hHH` humidity (00 = 100%), `bBBBBB` pressure (tenths mbar)
- `LLLL` luminosity 0–999 W/m² (capital L) | `lLLL` 1000–1999 W/m² (lowercase l, leading 1 dropped)

### Status packet
```
W9PEM-13>APTEMP,WIDE1-1:>Rain: Moderate (0.18in/hr) | Lightning: 8.3mi, 14min ago, 7 strikes/3hr
```
Suppressed entirely when neither rain nor lightning is active.

---

## Direwolf / KISS TCP

- Protocol: **KISS TCP** on port 8001 (NOT AGW port 8000 — AGW 'T' frame is rejected by Direwolf for unproto UI frames)
- KISS frame: `0xC0 | 0x00 | <escaped AX.25 bytes> | 0xC0`
- AX.25 UI frame: dest (7B) + src (7B) + via addrs (7B each) + 0x03 (UI control) + 0xF0 (no L3) + info
- Each address byte = ASCII char << 1; padded to 6 chars; E-bit set on last address in field

---

## Hardware

| Environment | PTT | Audio device |
|---|---|---|
| Raspberry Pi (prod) | `PTT GPIO 25` via 2N2222A transistor | `plughw:1,0` (CM108 USB dongle) |
| Windows (testing) | `PTT CM108` | `"Digirig" "Digirig"` |

**Radio:** Alinco DR-135 MKIII, DB-9 data port
- Pin 1 = PKD audio out (RX), Pin 4 = PTT, Pin 5 = PKI audio in (TX)
- Pin 3 tied to GND = 1200 baud mode

**Interface (Windows/testing):** Digirig Lite (CM108B chipset, USB-C, TRRS)

---

## Config Paths

| Setting | Windows (testing) | Raspberry Pi (prod) |
|---|---|---|
| `LOG_FILE` | `C:/tempest_aprs/tempest_aprs.log` | `/var/log/tempest_aprs.log` |
| `RAIN_STATE_FILE` | `C:/tempest_aprs/rain_state.json` | `/var/lib/tempest_aprs/rain_state.json` |

---

## rain_tracker.py Notes
- Stores `(epoch, cumulative_mm)` tuples in a deque, pruned to 25hr
- `get_last_hour_mm()` — max of recent readings minus oldest in 60min window
- `get_last_24h_mm()` — sums deltas, handles midnight resets (drops in series)
- `get_since_midnight_mm()` — directly from Tempest's `local_day_accum`
- Detects Tempest's own midnight reset when `local_day_accum` drops > 0.5mm
- State persisted to `rain_state.json` on every update

---

## Known Constraints / Decisions
- No third-party Python packages — stdlib only
- Python must run **natively on Windows** for testing (WSL2 on Win10 cannot receive LAN UDP broadcasts)
- `APTEMP` is a custom APRS destination tocall (not in the official APRS tocall registry) — acceptable for a personal station
- Solar radiation clamped at 1999 W/m² (physically unreachable at Earth's surface)
- Temperature formatted as `t{int:03d}` — Python handles negative correctly (e.g. `t-07`)
- Humidity 100% encoded as `h00` per APRS spec
