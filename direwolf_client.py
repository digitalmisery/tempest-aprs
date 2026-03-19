# direwolf_client.py
"""
Sends APRS packets to Direwolf via KISS TCP (port 8001).

KISS is a far simpler and more reliable protocol than AGW for sending
unproto UI frames like APRS weather beacons. Direwolf supports KISS TCP
on port 8001 by default (set with KISSPORT in direwolf.conf).

KISS frame format:
  0xC0          FEND  - frame start
  0x00          CMD   - data frame, channel 0
  <AX.25 frame bytes>
  0xC0          FEND  - frame end

Special byte escaping:
  0xC0 in data → 0xDB 0xDC
  0xDB in data → 0xDB 0xDD

AX.25 UI frame structure (for APRS):
  Destination address  (7 bytes)
  Source address       (7 bytes)
  Via address(es)      (7 bytes each)
  Control byte         0x03  (UI frame)
  PID byte             0xF0  (no layer 3)
  Information field    (the APRS payload string)

AX.25 address encoding:
  Each callsign character is shifted left 1 bit.
  Padded with spaces to 6 characters.
  SSID byte encodes SSID number and E-bit (end of address field).
"""

import socket
import logging
import time

logger = logging.getLogger("tempest_aprs.direwolf")

# KISS special bytes
FEND  = 0xC0
FESC  = 0xDB
TFEND = 0xDC
TFESC = 0xDD


class DirewolfClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 8001):
        self.host = host
        self.port = port
        self._sock = None
        self._connect()

    # ── Connection management ─────────────────────────────────────────────────

    def _connect(self):
        """Establish TCP connection to Direwolf KISS port."""
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(10)
            self._sock.connect((self.host, self.port))
            logger.info(f"Connected to Direwolf KISS TCP at {self.host}:{self.port}")
        except Exception as e:
            logger.error(f"Failed to connect to Direwolf KISS port: {e}")
            self._sock = None

    def _ensure_connected(self):
        """Reconnect if socket is lost."""
        if self._sock is None:
            logger.info("Reconnecting to Direwolf KISS port...")
            time.sleep(2)
            self._connect()

    # ── AX.25 address encoding ────────────────────────────────────────────────

    def _encode_ax25_address(self, callsign: str, ssid: int, is_last: bool) -> bytes:
        """
        Encode a callsign + SSID into 7 bytes of AX.25 address field.
        Each character ASCII value is shifted left by 1 bit.
        Padded to 6 chars with spaces. 7th byte encodes SSID and flags.
        """
        call = callsign.upper()[:6].ljust(6)
        addr = bytes([ord(c) << 1 for c in call])

        # SSID byte: bits 1-4 = SSID, bits 5-6 = reserved (set 1), bit 0 = E-bit
        ssid_byte = ((ssid & 0x0F) << 1) | 0b01100000
        if is_last:
            ssid_byte |= 0x01   # E-bit: marks end of address field

        return addr + bytes([ssid_byte])

    def _parse_callsign_ssid(self, call_str: str) -> tuple:
        """Parse 'W9PEM-13' into ('W9PEM', 13). Returns (call, 0) if no SSID."""
        if '-' in call_str:
            call, ssid_str = call_str.split('-', 1)
            return call.strip(), int(ssid_str)
        return call_str.strip(), 0

    # ── AX.25 frame building ──────────────────────────────────────────────────

    def _build_ax25_ui_frame(self, source: str, dest: str,
                              via_list: list, info: str) -> bytes:
        """
        Build a raw AX.25 UI frame.
        Address order: destination, source, via digipeaters.
        The last address in the list has its E-bit set.
        """
        dest_call, dest_ssid = self._parse_callsign_ssid(dest)
        src_call,  src_ssid  = self._parse_callsign_ssid(source)

        has_via = len(via_list) > 0

        dest_bytes = self._encode_ax25_address(dest_call, dest_ssid, is_last=False)
        src_bytes  = self._encode_ax25_address(src_call,  src_ssid,  is_last=not has_via)

        via_bytes = b""
        for i, via in enumerate(via_list):
            via_call, via_ssid = self._parse_callsign_ssid(via)
            is_last_addr = (i == len(via_list) - 1)
            via_bytes += self._encode_ax25_address(via_call, via_ssid, is_last=is_last_addr)

        control    = bytes([0x03])   # UI frame
        pid        = bytes([0xF0])   # No layer 3
        info_bytes = info.encode("ascii", errors="replace")

        return dest_bytes + src_bytes + via_bytes + control + pid + info_bytes

    # ── KISS framing ──────────────────────────────────────────────────────────

    def _kiss_escape(self, data: bytes) -> bytes:
        """Escape FEND and FESC bytes within the data payload."""
        out = bytearray()
        for byte in data:
            if byte == FEND:
                out += bytes([FESC, TFEND])
            elif byte == FESC:
                out += bytes([FESC, TFESC])
            else:
                out.append(byte)
        return bytes(out)

    def _build_kiss_frame(self, ax25_frame: bytes, channel: int = 0) -> bytes:
        """Wrap an AX.25 frame in a KISS TCP envelope."""
        cmd_byte = (channel & 0x0F) << 4   # 0x00 for channel 0, data frame
        return bytes([FEND, cmd_byte]) + self._kiss_escape(ax25_frame) + bytes([FEND])

    # ── Public send method ────────────────────────────────────────────────────

    def send_packet(self, packet_str: str):
        """
        Send a TNC2-format APRS packet string to Direwolf via KISS TCP.
        Format: SOURCE>DEST,VIA1,VIA2:payload
        Example: W9PEM-13>APRS,WIDE1-1:@101511z4319.37N/...
        """
        self._ensure_connected()
        if self._sock is None:
            logger.error("Cannot send — no connection to Direwolf KISS port")
            return

        try:
            # Parse TNC2 packet string
            header_part, info = packet_str.split(":", 1)
            source_str, dest_path = header_part.split(">", 1)
            path_parts = dest_path.split(",")
            dest_str   = path_parts[0]
            via_list   = path_parts[1:] if len(path_parts) > 1 else []

            # Build AX.25 UI frame and wrap in KISS
            ax25 = self._build_ax25_ui_frame(
                source   = source_str.strip(),
                dest     = dest_str.strip(),
                via_list = [v.strip() for v in via_list],
                info     = info,
            )
            kiss_frame = self._build_kiss_frame(ax25)
            self._sock.sendall(kiss_frame)
            logger.info(f"Packet sent via KISS: {packet_str}")

        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            logger.error(f"Socket error sending packet: {e} — will reconnect")
            self._sock = None
        except Exception as e:
            logger.error(f"Unexpected error sending packet: {e}", exc_info=True)