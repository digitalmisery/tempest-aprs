# aprs_is_client.py
"""
Sends APRS packets directly to the APRS-IS internet backbone.
Generates the necessary passcode based on the callsign and manages the TCP socket.
"""

import socket
import logging
import time

logger = logging.getLogger("tempest_aprs.aprs_is")

class APRSISClient:
    def __init__(self, callsign: str, server: str = "rotate.aprs2.net", port: int = 14580):
        self.callsign = callsign.upper()
        self.server = server
        self.port = port
        self.passcode = self._generate_passcode(self.callsign)
        self._sock = None
        self._connect()

    def _generate_passcode(self, callsign: str) -> str:
        """Generates the APRS-IS passcode for a given callsign (ignores SSID)."""
        base_call = callsign.split('-')[0].upper()
        hash_val = 0x73e2
        for i, char in enumerate(base_call):
            if i % 2 == 0:
                hash_val ^= ord(char) << 8
            else:
                hash_val ^= ord(char)
        return str(hash_val & 0x7fff)

    def _connect(self):
        """Establish TCP connection to the APRS-IS server and authenticate."""
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(10)
            self._sock.connect((self.server, self.port))
            
            # Send login string (APRS-IS requires \r\n at the end of strings)
            # We append the -13 SSID to the login if it wasn't provided, but the base config uses CALLSIGN and SSID separately.
            # We'll use the raw callsign string passed in from config.
            login_str = f"user {self.callsign} pass {self.passcode} vers TempestAPRS 1.1\r\n"
            self._sock.sendall(login_str.encode('utf-8'))
            
            # Read the server's acknowledgement 
            response = self._sock.recv(1024).decode('utf-8').strip()
            logger.debug(f"APRS-IS Status: Connected successfully to {self.server}:{self.port}. Server responded: {response}")
            
        except Exception as e:
            logger.debug(f"APRS-IS Status: Connection failed - {e}")
            self._sock = None

    def _ensure_connected(self):
        """Reconnect if socket is lost."""
        if self._sock is None:
            logger.info(f"Reconnecting to APRS-IS server {self.server}...")
            time.sleep(2)
            self._connect()

    def send_packet(self, packet_str: str):
        """Sends an APRS packet string to the APRS-IS server."""
        self._ensure_connected()
        if self._sock is None:
            logger.error("Cannot send — no connection to APRS-IS")
            return

        try:
            # Ensure the packet ends with \r\n before sending
            if not packet_str.endswith("\r\n"):
                packet_str += "\r\n"
                
            self._sock.sendall(packet_str.encode('utf-8'))
            logger.info(f"Packet sent via APRS-IS: {packet_str.strip()}")
            
        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            logger.debug(f"APRS-IS Status: Socket error sending packet - {e} — will reconnect")
            self._sock = None
        except Exception as e:
            logger.error(f"Unexpected error sending packet to APRS-IS: {e}", exc_info=True)