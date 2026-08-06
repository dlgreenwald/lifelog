import json
import socket
import struct

from lifelog.config import settings


class WyomingClient:
    """Wyoming protocol client for Whisper STT."""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port

    def transcribe(self, audio_bytes: bytes, sample_rate: int = 16000) -> dict:
        """Send audio via Wyoming protocol, receive transcript."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(300)
            sock.connect((self.host, self.port))

            # Send audio request
            request = {
                "type": "transcribe",
                "format": "opus",
                "sample_rate": sample_rate,
            }

            request_bytes = json.dumps(request).encode()
            sock.send(struct.pack("!I", len(request_bytes)))
            sock.send(request_bytes)
            sock.send(audio_bytes)

            # Receive response
            response_len = struct.unpack("!I", sock.recv(4))[0]
            response_bytes = sock.recv(response_len)
            response = json.loads(response_bytes)

            return {
                "text": response["text"],
                "segments": response.get("segments", []),
            }


wyoming = WyomingClient(settings.wyoming_host, settings.wyoming_port)


def transcribe(audio_bytes: bytes) -> dict:
    return wyoming.transcribe(audio_bytes)
