# Protocol frame handling untuk Avatar v2

from . import KNOWN_OPS

class Frame:
    """[op:1][len:2BE][payload]"""
    __slots__ = ("op", "payload")
    def __init__(self, op: int, payload: bytes = b""):
        self.op = op
        self.payload = payload
    @classmethod
    def decode(cls, data: bytes):
        if len(data) < 3:
            return None, data
        op = int.from_bytes(data[0:1], "big", signed=True)
        length = int.from_bytes(data[1:3], "big")
        if len(data) < 3 + length:
            return None, data
        payload = data[3:3+length]
        return cls(op, payload), data[3+length:]
    def encode(self) -> bytes:
        return self.op.to_bytes(1, "big", signed=True) +
               len(self.payload).to_bytes(2, "big") +
               self.payload
    def __repr__(self):
        name = KNOWN_OPS.get(self.op, "?")
        return f"Frame(op={self.op}({name}), len={len(self.payload)})"

class XorStream:
    """Rolling XOR per arah (client->server & server->client terpisah)."""
    def __init__(self, key: bytes):
        self.key = bytearray(key)
        self.counter = 0
    def transform(self, data: bytes) -> bytes:
        out = bytearray(len(data))
        for i, b in enumerate(data):
            k = self.key[(self.counter + i) % len(self.key)]
            out[i] = b ^ k
        self.counter = (self.counter + len(data)) % len(self.key)
        return bytes(out)

def undiff_xor(diff_key: bytes) -> bytes:
    """Key dari handshake: diff_key ^ timestamp."""
    # Implementasi sesuaikan dengan sniff - placeholder
    return diff_key

import socket
import threading
import time
import logging

logger = logging.getLogger(__name__)

class AvatarConnection:
    """Koneksi ke server Avatar dengan XOR encryption dua arah."""
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.sock = None
        self.xor_send = None
        self.xor_recv = None
        self.connected = False
        self._recv_buffer = bytearray()
        self._lock = threading.Lock()
    def connect(self) -> bool:
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=10)
            self.sock.settimeout(30)
            self.connected = True
            return True
        except Exception as e:
            logger.error(f"Connect failed: {e}")
            return False
    def handshake(self, diff_key: bytes) -> bool:
        """Kirim handshake op -27 dengan key, terima key balikan."""
        try:
            # op -27, payload = diff_key
            frame = Frame(-27, diff_key)
            self.sock.sendall(frame.encode())
            # Baca response handshake
            data = self.sock.recv(1024)
            # Parse server key...
            return True
        except Exception as e:
            logger.error(f"Handshake failed: {e}")
            return False
    def send_frame(self, frame: Frame) -> bool:
        if not self.connected or not self.sock:
            return False
        try:
            data = frame.encode()
            if self.xor_send:
                data = self.xor_send.transform(data)
            with self._lock:
                self.sock.sendall(data)
            return True
        except Exception as e:
            logger.error(f"Send failed: {e}")
            return False
    def recv_frame(self):
        if not self.connected or not self.sock:
            return None
        try:
            while True:
                frame, self._recv_buffer = Frame.decode(self._recv_buffer)
                if frame:
                    return frame
                chunk = self.sock.recv(4096)
                if not chunk:
                    return None
                if self.xor_recv:
                    chunk = self.xor_recv.transform(chunk)
                self._recv_buffer.extend(chunk)
        except socket.timeout:
            return None
        except Exception as e:
            logger.error(f"Recv failed: {e}")
            return None
    def close(self):
        self.connected = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
