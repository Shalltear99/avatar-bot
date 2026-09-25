#!/usr/bin/env python3
"""
Avatar Smart Fish Pro Plus — Python Bot
Reverse engineered dari JAR: 1788339992416-avatar-art-gaming-auto-fish.jar

Protokol:
  - Server: avatar-prod.ayomabar.com:19126
  - Handshake: client kirim frame opcode -27 (0xE5) len=0 plaintext
  - Server balas frame -27 dengan payload: [keyLen][key diff-XOR]
  - Un-diff: key[i] ^= key[i-1] untuk i=1..len-1
  - Frame format: [opcode:1][len:2 BE][payload:len]
  - Setelah key di-inject: SEMUA byte (opcode, len, payload) di-XOR rolling per-arah
    - outbound: encodeWrite(byte) = key[idx] ^ byte; idx = (idx+1) % keyLen
    - inbound:  decodeRead(byte) = key[idx] ^ byte; idx = (idx+1) % keyLen

Login sequence (dari B.class + ay.class):
  1. deviceInfo      opcode -1  [writeInt(0)]
  2. clientInit1     opcode -17 [writeByte(0), writeInt(memKB), writeUTF(platform), writeInt(rmsKB),
                               writeInt(w), writeInt(h), writeBoolean(true), writeByte(0),
                               writeUTF("2.5.8"), writeUTF(""), writeUTF(""), writeUTF("")]
  3. clientInit2     opcode -79 [writeUTF("")]
  4. sessionHash     opcode -52 [writeInt(username.hashCode())]
  5. LOGIN           opcode -2  [writeUTF(user), writeUTF(pass), writeUTF("2.5.8")]

Setelah login: joinArea(25) + finishFishing(1) + doCauCaXong() untuk auto-fish.

Usage:
  python3 bot.py sniff      -> connect + handshake + sniff 10 detik (default)
  python3 bot.py login      -> connect + handshake + login + sniff 20 detik
  python3 bot.py fish       -> connect + handshake + login + auto-fish loop + sniff
  python3 bot.py patch      -> patch JAR host ke 127.0.0.1 (untuk sniff via proxy HP)
"""

import sys
import socket
import struct
import time
import threading
import queue
import os
import json
from collections import deque
from datetime import datetime
from frame_decoder import decode_payload, KNOWN_OPS, format_frame, format_frame_hex

# root project = satu level di atas source-code/
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")
AKUN_PATH = os.path.join(PROJECT_ROOT, "source-code", "akun.txt")
from dataclasses import dataclass
from typing import Optional, List, Tuple

# =====================================================================
# KONSTANTA PROTOKOL
# =====================================================================
HOST = "avatar-prod.ayomabar.com"
PORT = 19126
VERSION = "2.5.8"
OP_HANDSHAKE = -27          # 0xE5
OP_DEVICE_INFO = -1
OP_CLIENT_INIT1 = -17
OP_CLIENT_INIT2 = -79
OP_SESSION_HASH = -52
OP_LOGIN = -2
OP_JOIN_AREA = 54
OP_FINISH_FISHING = 84
OP_DO_CAU_CA_XONG = 85
OP_IDLE = 96
# --- Opcode dari sniff v2 ---
OP_MOVE_MAP = 50
OP_GIFTCODE = 51
OP_ACTION_BASIC = 55
OP_ACTION_BASIC2 = 56
OP_AREA_NPC = 57
OP_AREA_EVENT = 60
OP_BUY_ITEM = 61
OP_GIVE_ITEM = 62
OP_REQUEST_INFO = 64
OP_FARM_ACTION = 65
OP_FARM_HARVEST = 66
OP_HARVEST = 71
OP_SELL_FISH = 74
OP_QUEST_INFO = 78
OP_QUEST_UPDATE = 79
OP_CAST_ROD = 82
OP_BUY_BAIT = 86
OP_FISH_RESULT = 91
OP_NCP_INTERACT = -61
OP_NPC_MENU = -59
OP_SHOP_BUY = -24
OP_NOTIF_MSG = -10
OP_COIN_UPDATE = -33
OP_STAT_UPDATE = -22

# =====================================================================
# FRAME & XOR CIPHER
# =====================================================================
@dataclass
class Frame:
    opcode: int
    payload: bytes
    
    def __repr__(self):
        return f"Frame(op={self.opcode:4d} (0x{self.opcode & 0xFF:02x}), len={len(self.payload)}, payload={self.payload.hex()[:80]}{'...' if len(self.payload)>40 else ''})"

class XorStream:
    """Rolling XOR cipher — replikasi dM.class"""
    def __init__(self, key: bytes):
        self.key = key
        self.key_len = len(key)
        self.enc_idx = 0
        self.dec_idx = 0
        
    def encode_write(self, b: int) -> int:
        """Encode outbound byte"""
        out = (self.key[self.enc_idx] ^ b) & 0xFF
        self.enc_idx = (self.enc_idx + 1) % self.key_len
        return out
    
    def decode_read(self, b: int) -> int:
        """Decode inbound byte"""
        out = (self.key[self.dec_idx] ^ b) & 0xFF
        self.dec_idx = (self.dec_idx + 1) % self.key_len
        return out
    
    def reset_indices(self):
        self.enc_idx = 0
        self.dec_idx = 0

def undiff_xor(diff_key: bytes) -> bytes:
    """Reverse differential XOR: key[i] ^= key[i-1]"""
    key = bytearray(diff_key)
    for i in range(1, len(key)):
        key[i] ^= key[i-1]
    return bytes(key)

# =====================================================================
# CONNECTION MANAGER
# =====================================================================
class AvatarConnection:
    def __init__(self, host=HOST, port=PORT, timeout=10):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self.crypto: Optional[XorStream] = None
        self._recv_buf = bytearray()
        self.connected = False
        
    def connect(self) -> bool:
        """Buka TCP socket"""
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            self.sock.settimeout(self.timeout)
            self.connected = True
            print(f"[+] TCP terhubung ke {self.host}:{self.port}")
            return True
        except Exception as e:
            print(f"[!] Koneksi gagal: {e}")
            return False
    
    def _send_raw(self, data: bytes):
        """Kirim bytes mentah (plaintext, pre-cipher)"""
        if not self.sock:
            raise RuntimeError("Belum connect")
        self.sock.sendall(data)
    
    def _recv_exact(self, n: int) -> bytes:
        """Baca tepat n bytes dari socket"""
        while len(self._recv_buf) < n:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("Socket closed by server")
            self._recv_buf.extend(chunk)
        data = bytes(self._recv_buf[:n])
        del self._recv_buf[:n]
        return data
    
    def send_plain_frame(self, opcode: int, payload: bytes = b""):
        """Kirim frame plaintext (pre-handshake)"""
        length = len(payload)
        frame = bytes([opcode & 0xFF]) + struct.pack(">H", length) + payload
        self._send_raw(frame)
    
    def read_plain_frame(self) -> Frame:
        """Baca frame plaintext"""
        op = self._recv_exact(1)[0]
        if op >= 128:
            op = op - 256
        length = struct.unpack(">H", self._recv_exact(2))[0]
        payload = self._recv_exact(length)
        return Frame(op, payload)
    
    def inject_key(self, raw_key: bytes):
        """Inject key dari handshake server (sudah un-diff)"""
        self.crypto = XorStream(raw_key)
        print(f"[+] Cipher XOR AKTIF (key {len(raw_key)} bytes: {raw_key.hex()})")
    
    def send_encrypted(self, opcode: int, payload: bytes = b""):
        """Kirim frame TERENKRIPSI"""
        if not self.crypto:
            raise RuntimeError("Belum injectKey — cipher belum aktif")
        length = len(payload)
        # encode opcode
        self._send_raw(bytes([self.crypto.encode_write(opcode & 0xFF)]))
        # encode length (2 bytes)
        self._send_raw(bytes([self.crypto.encode_write((length >> 8) & 0xFF)]))
        self._send_raw(bytes([self.crypto.encode_write(length & 0xFF)]))
        # encode payload
        if length > 0:
            encoded = bytearray(length)
            for i, b in enumerate(payload):
                encoded[i] = self.crypto.encode_write(b)
            self._send_raw(encoded)
    
    def read_encrypted_frame(self) -> Frame:
        """Baca frame TERENKRIPSI"""
        if not self.crypto:
            raise RuntimeError("Belum injectKey")
        # decode opcode
        op = self.crypto.decode_read(self._recv_exact(1)[0])
        if op >= 128:
            op = op - 256
        # decode length
        hi = self.crypto.decode_read(self._recv_exact(1)[0])
        lo = self.crypto.decode_read(self._recv_exact(1)[0])
        length = (hi << 8) | lo
        # decode payload
        payload = bytearray(length)
        for i in range(length):
            payload[i] = self.crypto.decode_read(self._recv_exact(1)[0])
        return Frame(op, bytes(payload))
    
    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None
            self.connected = False

# =====================================================================
# PACKET FACTORY (replikasi cI.class + B.class)
# =====================================================================
class PacketFactory:
    @staticmethod
    def _utf(s: str) -> bytes:
        """WriteUTF: length (2 bytes BE) + UTF-8 bytes"""
        data = s.encode('utf-8')
        return struct.pack(">H", len(data)) + data
    
    @staticmethod
    def _int(n: int) -> bytes:
        return struct.pack(">I", n & 0xFFFFFFFF)
    
    @staticmethod
    def _short(n: int) -> bytes:
        return struct.pack(">H", n & 0xFFFF)
    
    @staticmethod
    def _byte(n: int) -> bytes:
        return bytes([n & 0xFF])
    
    @staticmethod
    def _bool(b: bool) -> bytes:
        return bytes([1 if b else 0])

    # --- LOGIN SEQUENCE ---
    def device_info(self) -> Frame:
        # B.d(int): opcode -1, writeInt(0)
        return Frame(OP_DEVICE_INFO, self._int(0))
    
    def client_init1(self) -> Frame:
        # B.a(): opcode -17
        # writeByte(0), writeInt(memKB), writeUTF(platform),
        # writeInt(rmsKB), writeInt(w), writeInt(h), writeBoolean(true),
        # writeByte(0), writeUTF("2.5.8"), writeUTF(""), writeUTF(""), writeUTF("")
        ba = bytearray()
        ba.extend(self._byte(0))                    # random id
        ba.extend(self._int(65536))                 # mem KB (64MB)
        ba.extend(self._utf("Nokia6233"))           # platform
        ba.extend(self._int(64))                    # rms size KB
        ba.extend(self._int(176))                   # screen w (eE.f)
        ba.extend(self._int(220))                   # screen h (eE.g)
        ba.extend(self._bool(True))                 # eE.g (bool)
        ba.extend(self._byte(0))                    # bJ.l - 1
        ba.extend(self._utf(VERSION))               # version
        ba.extend(self._utf(""))                    # aV.a
        ba.extend(self._utf(""))                    # bh.a
        ba.extend(self._utf(""))                    # eV.a
        return Frame(OP_CLIENT_INIT1, bytes(ba))
    
    def client_init2(self) -> Frame:
        # B.a() terakhir: opcode -79, writeUTF(GameMidlet.a) — agent string
        return Frame(OP_CLIENT_INIT2, self._utf("0"))  # agent.txt = "0"
    
    def session_hash(self, username: str) -> Frame:
        # B.f(int): opcode -52, writeInt(username.hashCode())
        # Java String.hashCode() = s[0]*31^(n-1) + s[1]*31^(n-2) + ...
        h = 0
        for ch in username:
            h = (h * 31 + ord(ch)) & 0xFFFFFFFF
        # convert to signed 32-bit for Java compatibility
        if h >= 0x80000000:
            h -= 0x100000000
        return Frame(OP_SESSION_HASH, self._int(h))
    
    def login(self, username: str, password: str) -> Frame:
        # B.a(String, String, String): opcode -2
        # writeUTF(user), writeUTF(pass), writeUTF("2.5.8")
        ba = bytearray()
        ba.extend(self._utf(username))
        ba.extend(self._utf(password))
        ba.extend(self._utf(VERSION))
        return Frame(OP_LOGIN, bytes(ba))

    # --- GAME ACTIONS ---
    def join_area(self, x: int, y: int, direction: int = 2, unk: int = 0) -> Frame:
        """Op 54 (7 byte, dari sniff live HP): [short X][short Y][byte dir][short unk]"""
        p = self._short(x & 0xFFFF) + self._short(y & 0xFFFF) + self._byte(direction) + self._short(unk & 0xFFFF)
        return Frame(OP_JOIN_AREA, p)

    def move_map(self, area: int, sub: int = 255, pos_x: int = -1, pos_y: int = -1) -> Frame:
        """Op 50 MOVE_MAP — dari sniff v2: [byte area][byte sub][short posX][short posY]
        Contoh live: 0d ff ff ff ff ff → area=13 sub=255 pos=(-1,-1) [pindah map kota]
                     19 00 ff ff ff ff → area=25 sub=0 pos=(-1,-1) [pindah ke farm 25]
                     10 04 ff ff ff ff → area=16 sub=4 pos=(-1,-1) [sub-area 16.4]
        sub=255 = main map, sub lain = sub-area"""
        p = self._byte(area) + self._byte(sub) + self._short(pos_x & 0xFFFF) + self._short(pos_y & 0xFFFF)
        return Frame(50, p)

    def action_82(self, kind: int = 0, sprite_id: int = 0) -> Frame:
        """Op 82 CAST_ROD — dari sniff v2: [byte kind][byte spriteId]
        kind: 0=avatar/sprite, 1=item/npc
        Contoh live: 0003 (kind=0,sprite=3), 014a (kind=1,sprite=74)"""
        p = self._byte(kind) + self._byte(sprite_id)
        return Frame(OP_CAST_ROD, p)
    
    def avatar_img(self, img_id: int) -> Frame:
        """Op -80 AVATAR_IMG — minta gambar sprite
        Payload: [short imgId LITTLE-endian]
        Contoh live: 0347 → imgId=0x4703"""
        p = struct.pack('<h', img_id)
        return Frame(-80, p)
    
    def sprite_req(self, sprite_id: int) -> Frame:
        """Op -98 SPRITE_REQ — minta sprite NPC/costume"""
        p = struct.pack('<h', sprite_id)
        return Frame(-98, p)

    def op55(self, data: bytes) -> Frame:
        """Op 55 action basic"""
        return Frame(55, data)
    
    def move_to_area(self, map_id: int, sub: int = 0, pos_x: int = 0, pos_y: int = 0) -> Frame:
        """eJ.a().a(int,int) — opcode 50: pindah map
        Payload: byte(map_id), byte(sub), short(posX), short(posY)"""
        ba = bytearray()
        ba.extend(self._byte(map_id))
        ba.extend(self._byte(sub))
        ba.extend(self._short(pos_x))
        ba.extend(self._short(pos_y))
        return Frame(50, bytes(ba))
    
    def move_to_area_short(self, map_id: int, sub: int, dx: int, dy: int) -> Frame:
        """eJ.a(int,int,int,int) — opcode 54 (juga dipakai pindah map dengan delta pos):
        payload: short(n), short(n2), byte(n3), short(n4)"""
        ba = bytearray()
        ba.extend(self._short(map_id))
        ba.extend(self._short(sub))
        ba.extend(self._byte(dx))
        ba.extend(self._short(dy))
        return Frame(54, bytes(ba))
    
    def request_info(self, n: int, n2: int, n3: int) -> Frame:
        """Op 64 REQUEST_INFO — dari sniff v2: 6 byte [int n][byte n2][byte n3]
        Contoh live: n=112(0x70), n2=3, n3=1 → info area farm"""
        ba = bytearray()
        ba.extend(self._int(n))
        ba.extend(self._byte(n2))
        ba.extend(self._byte(n3))
        return Frame(OP_REQUEST_INFO, bytes(ba))
    
    def join_farm(self, user_id: int, slot: int, action: int) -> Frame:
        """Op 65 FARM_ACTION — dari sniff v2: 7 byte [int userId][byte slot][short action]
        Contoh live: 00000132 00 0064 → userId=306 slot=0 action=100
        slot: 0..7 (8 slot farm), action: 0x64=rawat, 0x7c=? """
        ba = bytearray()
        ba.extend(self._int(user_id))
        ba.extend(self._byte(slot))
        ba.extend(self._short(action))
        return Frame(OP_FARM_ACTION, bytes(ba))
    
    def tend_object(self, user_id: int, slot: int, action: int) -> Frame:
        """Alias: rawat objek farm (op 65)"""
        return self.join_farm(user_id, slot, action)
    
    def farm_harvest(self, user_id: int, plot_id: int) -> Frame:
        """Op 66 FARM_HARVEST — panen tanaman
        Format: [int userId][byte plotId] (5 byte)
        Contoh live: 0000013222 → uid=306, plot=0x22=34"""
        ba = bytearray()
        ba.extend(self._int(user_id))
        ba.extend(self._byte(plot_id))
        return Frame(OP_FARM_HARVEST, bytes(ba))
    
    def buy_item(self, item_id: int, qty: int = 1) -> Frame:
        """Op 61 BUY_ITEM — dari sniff v2: [int itemId][byte qty]
        Contoh live: 00000132 00 → itemId=306, qty=0
                     00000132 01 → itemId=306, qty=1"""
        ba = bytearray()
        ba.extend(self._int(item_id))
        ba.extend(self._byte(qty))
        return Frame(OP_BUY_ITEM, bytes(ba))
    
    def sell_item(self, area_id: int, slot: int) -> Frame:
        """cI.c(int,int) — opcode 74: jual ikan — writeInt(area), writeByte(slot)"""
        ba = bytearray()
        ba.extend(self._int(area_id))
        ba.extend(self._byte(slot))
        return Frame(OP_SELL_FISH, bytes(ba))
    
    def harvest(self, item_type: int, count: int) -> Frame:
        """cI.a(eU,int) — opcode 71: panen — writeByte(type), writeByte(count)"""
        ba = bytearray()
        ba.extend(self._byte(item_type))
        ba.extend(self._byte(count))
        return Frame(OP_HARVEST, bytes(ba))
    
    def buy_fish_bait(self, n: int) -> Frame:
        """cI.d(int) — opcode 86: beli umpan — writeByte(n)"""
        return Frame(OP_BUY_BAIT, self._byte(n))
    
    def give_item(self, n1: int, n2: int) -> Frame:
        """Op 62 GIVE_ITEM — dari sniff v2: 4 byte [int n1][byte n2]
        Contoh live: 00000101, 00000102 → n1=257/258, n2=0"""
        ba = bytearray()
        ba.extend(self._int(n1))
        ba.extend(self._byte(n2))
        return Frame(OP_GIVE_ITEM, bytes(ba))
    
    def npc_interact(self, npc_id: int) -> Frame:
        """Op -61 NPC_INTERACT — dari sniff v2: 4 byte [int npcId]
        Contoh live: 773595ae → npcId=0x773595ae"""
        return Frame(OP_NCP_INTERACT, self._int(npc_id))
    
    def npc_menu_select(self, npc_id: int, option: int) -> Frame:
        """Op -59 NPC_MENU — dari sniff v2: 6 byte [int npcId][short option]
        Contoh live: 773595ae0000 → npcId=0x773595ae, option=0"""
        ba = bytearray()
        ba.extend(self._int(npc_id))
        ba.extend(self._short(option))
        return Frame(OP_NPC_MENU, bytes(ba))
    
    def shop_buy(self, item_id: int, qty: int = 1) -> Frame:
        """Op -24 SHOP_BUY — dari sniff v2: 3 byte [short itemId][byte qty]
        Contoh live: 01c001 → itemId=0x01c0, qty=0x01"""
        ba = bytearray()
        ba.extend(self._short(item_id))
        ba.extend(self._byte(qty))
        return Frame(OP_SHOP_BUY, bytes(ba))
    
    def giftcode(self, code: str) -> Frame:
        """Op 51 GIFTCODE — redeem kode hadiah"""
        return Frame(OP_GIFTCODE, self._utf(code))
    
    def area_event(self, data: bytes = b'') -> Frame:
        """Op 60 AREA_EVENT"""
        return Frame(OP_AREA_EVENT, data)
    
    def action_basic(self) -> Frame:
        """cI.a() — opcode 55"""
        return Frame(55, b"")
    
    def action_basic_2(self) -> Frame:
        """cI.b() — opcode 56"""
        return Frame(56, b"")
    
    def finish_fishing(self, data: bytes = None) -> Frame:
        """Op 84 (8 byte dari sniff): default 01 06 03 01 03 01 03 02"""
        if data is None:
            data = bytes([0x01, 0x06, 0x03, 0x01, 0x03, 0x01, 0x03, 0x02])
        return Frame(OP_FINISH_FISHING, data)
    
    def do_cau_ca_xong(self) -> Frame:
        # opcode 85: raw, no payload
        return Frame(OP_DO_CAU_CA_XONG, b"")

    def buy_bait(self) -> Frame:
        """Op 86: buy bait — empty payload (0 byte), server balas byte=1"""
        return Frame(86, b"")
    
    def idle(self) -> Frame:
        # opcode 96: writeByte(0)
        return Frame(OP_IDLE, self._byte(0))

# =====================================================================
# SNIFFER THREAD
# =====================================================================
class Sniffer:
    """
    Sniffer v2 — thread pembaca frame dengan statistik lengkap:
    - queue frame (konsumsi via get())
    - frekuensi opcode (in/outbound)
    - buffer frame terakhir (deque, untuk panel/export)
    - deteksi opcode TIDAK DIKENAL (future update alert)
    - export sesi ke JSON
    """
    def __init__(self, conn: AvatarConnection, encrypted: bool = False,
                 history_size: int = 500):
        self.conn = conn
        self.encrypted = encrypted
        self.queue = queue.Queue()
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.frame_count = 0
        # --- statistik ---
        self.op_freq_in: dict = {}      # op -> count (server → client)
        self.op_freq_out: dict = {}     # op -> count (client → server)
        self.unknown_ops: set = set()   # op yang belum ada di KNOWN_OPS
        self.history = deque(maxlen=history_size)  # frame terakhir
        self.bytes_in = 0
        self.bytes_out = 0
        self.started_at = 0.0
        self.on_frame = None  # callback(frame) untuk panel live
        self._lock = threading.Lock()

    def start(self):
        self.running = True
        self.started_at = time.time()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)

    def _run(self):
        while self.running and self.conn.connected:
            try:
                if self.encrypted:
                    frame = self.conn.read_encrypted_frame()
                else:
                    frame = self.conn.read_plain_frame()
                self.frame_count += 1
                with self._lock:
                    self.op_freq_in[frame.opcode] = self.op_freq_in.get(frame.opcode, 0) + 1
                    self.bytes_in += 3 + len(frame.payload)
                    if frame.opcode not in KNOWN_OPS:
                        self.unknown_ops.add(frame.opcode)
                    self.history.append({
                        "ts": time.time(),
                        "dir": "<",
                        "op": frame.opcode,
                        "op_name": KNOWN_OPS.get(frame.opcode, f"UNKNOWN_{frame.opcode}"),
                        "len": len(frame.payload),
                        "hex": frame.payload.hex(),
                    })
                self.queue.put(frame)
                if self.on_frame:
                    try:
                        self.on_frame(frame)
                    except Exception:
                        pass
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[sniffer] error: {e}")
                break

    def get(self, timeout=1.0) -> Optional[Frame]:
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return None

    # ---------- fitur baru ----------

    def track_outbound(self, opcode: int, payload: bytes):
        """Catat frame keluar (panggil setelah send_encrypted)"""
        with self._lock:
            self.op_freq_out[opcode] = self.op_freq_out.get(opcode, 0) + 1
            self.bytes_out += 3 + len(payload)
            self.history.append({
                "ts": time.time(),
                "dir": ">",
                "op": opcode,
                "op_name": KNOWN_OPS.get(opcode, f"UNKNOWN_{opcode}"),
                "len": len(payload),
                "hex": payload.hex(),
            })

    def stats(self) -> dict:
        """Snapshot statistik untuk panel"""
        with self._lock:
            uptime = time.time() - self.started_at if self.started_at else 0
            return {
                "uptime_s": round(uptime, 1),
                "frames_in": sum(self.op_freq_in.values()),
                "frames_out": sum(self.op_freq_out.values()),
                "bytes_in": self.bytes_in,
                "bytes_out": self.bytes_out,
                "ops_in": dict(sorted(self.op_freq_in.items())),
                "ops_out": dict(sorted(self.op_freq_out.items())),
                "unknown_ops": sorted(self.unknown_ops),
                "history_size": len(self.history),
            }

    def export_json(self, path: str):
        """Simpan sesi sniff lengkap ke JSON"""
        data = {
            "exported_at": datetime.now().isoformat(),
            "stats": self.stats(),
            "history": list(self.history),
        }
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[+] Sniff session exported: {path}")

    def unknown_alert(self):
        """Print peringatan opcode tidak dikenal (future update detector)"""
        with self._lock:
            unk = sorted(self.unknown_ops)
        if unk:
            print(f"\n[!] {len(unk)} OPCODE TIDAK DIKENAL terdeteksi (game update?): {unk}")
            print("[!] Cek hex di history — perlu analisa frame_decoder baru!")
        else:
            print("[+] Semua opcode dikenal — tidak ada update protokol.")

# =====================================================================
# MAIN BOT
# =====================================================================
class AvatarBot:
    def __init__(self, username: str, password: str, label: str = ""):
        self.username = username
        self.password = password
        self.label = label or username
        self.conn = AvatarConnection()
        self.factory = PacketFactory()
        self.sniffer: Optional[Sniffer] = None
        self.logged_in = False
        self.keyed = False
        self.outbound_log: List[dict] = []
        self.user_id: Optional[int] = None
        self.fish_count = 0     # hasil panen ikan sesi ini
        self.farm_count = 0     # hasil panen farm sesi ini
        self.last_action = "-"
    
    def _send(self, opcode: int, payload: bytes):
        """Kirim frame + catat ke sniffer stats (track_outbound)"""
        self.conn.send_encrypted(opcode, payload)
        if self.sniffer is not None:
            self.sniffer.track_outbound(opcode, payload)
    
    def info(self) -> dict:
        """Info status bot untuk panel"""
        d = {
            "label": self.label,
            "username": self.username,
            "user_id": self.user_id,
            "connected": self.conn.connected,
            "logged_in": self.logged_in,
            "fish_count": self.fish_count,
            "farm_count": self.farm_count,
            "last_action": self.last_action,
            "sniffer": self.sniffer.stats() if self.sniffer else None,
        }
        return d
    
    def connect_and_handshake(self) -> bool:
        """Langkah 1: TCP connect + handshake + inject key"""
        if not self.conn.connect():
            return False
        
        # Kirim handshake request: opcode -27, len=0 (plaintext)
        print("[>] Kirim handshake request (opcode -27, len=0)")
        self.conn.send_plain_frame(OP_HANDSHAKE, b"")
        
        # Baca frame pertama (plaintext, belum cipher)
        try:
            first = self.conn.read_plain_frame()
            print(f"[sniff] frame pertama: {first}")
        except Exception as e:
            print(f"[!] Gagal baca handshake response: {e}")
            return False
        
        # Harus opcode -27 dengan payload key
        if first.opcode != OP_HANDSHAKE:
            print(f"[!] Frame pertama bukan handshake (-27), tapi {first.opcode}")
            return False
        
        if len(first.payload) < 1:
            print(f"[!] Payload handshake kosong")
            return False
        
        # Payload: [keyLen][diff-key...]
        key_len = first.payload[0]
        diff_key = first.payload[1:1+key_len]
        if len(diff_key) != key_len:
            print(f"[!] Key length mismatch: declared {key_len}, got {len(diff_key)}")
            return False
        
        # Un-diff
        real_key = undiff_xor(diff_key)
        print(f"[+] Key terdecode: {real_key.hex()} (len={len(real_key)})")
        
        # Inject key → cipher aktif
        self.conn.inject_key(real_key)
        self.keyed = True
        return True
    
    def do_login_sequence(self) -> bool:
        """Kirim urutan login lengkap + parse userId dari ZONE_INFO (-4)."""
        print("\n[login] Mulai urutan login (mengikuti B.class + ay.class)...")
        self.user_id = None
        
        # Mulai sniffer dulu agar ZONE_INFO tertangkap
        self.sniffer = Sniffer(self.conn, encrypted=True)
        self.sniffer.start()
        
        def send_frame(f: Frame, label: str):
            self._send(f.opcode, f.payload)
            print(f"[>] {label} → op={f.opcode} len={len(f.payload)} hex={f.payload.hex()}")
            # log juga frame outbound
            self.outbound_log.append({
                "ts": datetime.now().isoformat(),
                "op": f.opcode,
                "op_name": KNOWN_OPS.get(f.opcode, "?"),
                "hex": f.payload.hex(),
                "label": label,
            })
        
        self.outbound_log = []
        # 1. deviceInfo (-1)
        send_frame(self.factory.device_info(), "deviceInfo(-1)")
        time.sleep(0.15)
        
        # 2. clientInit1 (-17)
        send_frame(self.factory.client_init1(), "clientInit1(-17)")
        time.sleep(0.15)
        
        # 3. clientInit2 (-79)
        send_frame(self.factory.client_init2(), "clientInit2(-79)")
        time.sleep(0.15)
        
        # 4. sessionHash (-52)
        send_frame(self.factory.session_hash(self.username), "sessionHash(-52)")
        time.sleep(0.15)
        
        # 5. LOGIN (-2)
        send_frame(self.factory.login(self.username, self.password), f"LOGIN(-2) {self.username}")
        
        # 6. Tunggu ZONE_INFO (-4) untuk ambil userId
        end_wait = time.time() + 10
        while time.time() < end_wait and self.user_id is None:
            frame = self.sniffer.get(timeout=0.5)
            if frame and frame.opcode == -4 and len(frame.payload) >= 4:
                import struct as _s
                self.user_id = _s.unpack('>i', frame.payload[:4])[0]
                print(f"[+] userId dari ZONE_INFO: {self.user_id}")
        
        self.logged_in = True
        return True
    
    def auto_fish_cycle(self, area: int = 16, sub: int = 4, spot: tuple = (284, 141)):
        """Siklus auto-fish — urutan REAL dari sniff proxy HP (24 Sep, area fishing):
        1. op 50 move_map(area, sub, pos) — pindah ke area mancing (pilihan user)
        2. (tunggu server balas op 50 + op 54 confirm)
        3. op 54 joinArea(X,Y,dir=2) — duduk di spot mancing
        4. op 86 buyBait → op 82 → op 84 finishFishing(8 byte) → op 85 doCauCaXong
        """
        print(f"[fish] Siklus auto-fish (area={area}, sub={sub}, spot={spot})...")

        # 0. Pindah ke area fishing yang dipilih user
        print(f"[>] op50 move_map(area={area}, sub={sub}, -1, -1)")
        f = self.factory.move_map(area, sub, -1, -1)
        self._send(f.opcode, f.payload)
        self.outbound_log.append({'op': f.opcode, 'hex': f.payload.hex(), 'ts': time.time()})
        time.sleep(2.5)
        self._drain_responses(1.5)

        X, Y = spot  # posisi duduk mancing (default dari sniff idx 299-321)

        # 1. join area fishing (duduk di spot)
        f = self.factory.join_area(X, Y, direction=2)
        self._send(f.opcode, f.payload)
        self.outbound_log.append({'op': f.opcode, 'hex': f.payload.hex(), 'ts': time.time()})
        print(f"[>] op54 joinArea({X},{Y},dir=2) -> {f}")
        time.sleep(1.5)

        # 2. buy bait
        f = self.factory.buy_bait()
        self._send(f.opcode, f.payload)
        self.outbound_log.append({'op': f.opcode, 'hex': f.payload.hex(), 'ts': time.time()})
        print(f"[>] op86 buyBait() -> {f}")
        time.sleep(1.0)

        # 3. action 82 (cast / mulai pancing)
        f = self.factory.action_82()
        self._send(f.opcode, f.payload)
        self.outbound_log.append({'op': f.opcode, 'hex': f.payload.hex(), 'ts': time.time()})
        print(f"[>] op82 action() -> {f}")
        time.sleep(2.0)

        # 4. finish fishing (8 byte hasil tangkapan)
        f = self.factory.finish_fishing()
        self._send(f.opcode, f.payload)
        self.outbound_log.append({'op': f.opcode, 'hex': f.payload.hex(), 'ts': time.time()})
        print(f"[>] op84 finishFishing(01 06 03 01 03 01 03 02) -> {f}")
        time.sleep(1.0)

        # 5. doCauCaXong (selesai mancing)
        f = self.factory.do_cau_ca_xong()
        self._send(f.opcode, f.payload)
        self.outbound_log.append({'op': f.opcode, 'hex': f.payload.hex(), 'ts': time.time()})
        print(f"[>] op85 doCauCaXong() -> {f}")
        time.sleep(1.0)


    def sniff_loop(self, duration: int, label: str = "sniff", save_log: bool = True):
        """Loop sniffing frame dari server + simpan log hex"""
        print(f"\n[{label}] Mulai sniffing {duration} detik...")
        if self.sniffer is None or not getattr(self.sniffer, "running", False):
            self.sniffer = Sniffer(self.conn, encrypted=self.keyed)
            self.sniffer.start()
        else:
            print(f"[{label}] Sniffer sudah aktif — reuse.")
        
        log_entries = []
        end_time = time.time() + duration
        count = 0
        while time.time() < end_time and self.conn.connected:
            frame = self.sniffer.get(timeout=0.5)
            if frame:
                count += 1
                desc = decode_payload(frame.opcode, frame.payload)
                op_name = KNOWN_OPS.get(frame.opcode, "?")
                print(f"[{count:03d}] op={frame.opcode:4d} ({op_name:16s}) len={len(frame.payload):4d} {desc}")
                log_entries.append({
                    "n": count,
                    "ts": datetime.now().isoformat(),
                    "op": frame.opcode,
                    "op_name": op_name,
                    "len": len(frame.payload),
                    "hex": frame.payload.hex(),
                    "decoded": desc,
                })
        
        # JANGAN stop sniffer — biarkan jalan untuk cycle berikutnya (reuse).
        print(f"\n[{label}] Selesai — total {count} frame diterima")
        
        # Simpan log JSON + teks
        if save_log and log_entries:
            os.makedirs("logs", exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            json_path = f"{LOGS_DIR}/sniff_{label}_{ts}.json"
            with open(json_path, 'w') as f:
                json.dump({
                    "outbound": getattr(self, "outbound_log", []),
                    "inbound": log_entries,
                }, f, indent=2, ensure_ascii=False)
            
            txt_path = f"{LOGS_DIR}/sniff_{label}_{ts}.txt"
            with open(txt_path, 'w') as f:
                f.write(f"# Avatar Smart Fish sniff log — {label}\n")
                f.write(f"# {datetime.now().isoformat()} — {count} frames\n\n")
                for e in log_entries:
                    f.write(f"[{e['n']:03d}] op={e['op']} (0x{e['op']&0xFF:02x}, {e['op_name']}) len={e['len']}\n")
                    f.write(f"      hex={e['hex']}\n")
                    f.write(f"      decoded: {e['decoded']}\n\n")
            
            print(f"[+] Log disimpan: {json_path} + {txt_path}")
        return count
    
    def run_sniff(self, seconds: int = 10):
        """Mode sniff saja: connect + handshake + sniff"""
        if not self.connect_and_handshake():
            return False
        self.sniff_loop(seconds, "sniff")
        return True
    
    def run_login(self, seconds: int = 20):
        """Mode login: connect + handshake + login + sniff"""
        if not self.connect_and_handshake():
            return False
        if not self.do_login_sequence():
            return False
        # tunggu sebentar untuk response login
        time.sleep(2.0)
        self.sniff_loop(seconds, "login")
        return True
    
    def run_fish(self, cycles: int = 3, sniff_per_cycle: int = 10,
                 area: int = 16, sub: int = 4, spot: tuple = (284, 141)):
        """Mode auto-fish: connect + handshake + login + fish loop.
        area/sub/spot bisa diisi dari dashboard (menu pilih zona)."""
        if not self.connect_and_handshake():
            return False
        if not self.do_login_sequence():
            return False
        time.sleep(3.0)  # tunggu login response
        
        for i in range(cycles):
            print(f"\n=== FISH CYCLE {i+1}/{cycles} ===")
            self.auto_fish_cycle(area=area, sub=sub, spot=spot)
            self.sniff_loop(sniff_per_cycle, f"fish-{i+1}")
            time.sleep(2.0)
        return True
    
    def auto_farm_cycle(self, user_id: int = None, total_plots: int = 40):
        """Siklus auto-farm — URUTAN BENAR dari sniff v2 (idx 284-470):
        
        Urutan sniffing live (40 plot, 1 panen):
        1. op50 move_map(25,0)        → server: -63 MAP_CONFIRM, op50 echo, op55 notif
        2. op61 buy_item(uid,0)       → server: op50(53b), op55(19b), op55(28b)
        3. op82 cast_rod(0,3)         → server: op82(197b PNG), -80(2068b PNG)
        4. op-80 avatar_img(x)        → server: -80 PNG responses
        5. op82 cast_rod(0,46)         → server: op82(213b PNG), -80 PNG
        6. op65 tend(plotId, action=0x64=100) × 40 plot (slot 0..39)
        7. op64 request_info(n=uid, b1=plotId, b2=255) → info per plot
        8. op66 harvest(uid, plotId)   → HARVEST! (hanya plot yang siap)
        """
        uid = user_id if user_id is not None else (self.user_id or 0)
        print(f"[farm] Siklus auto-farm uid={uid}, {total_plots} plot...")

        # 0. Pindah ke map farm (area=25, sub=0) — dari sniff v2 idx 284
        print("[>] op50 move_map(area=25, sub=0, -1, -1)")
        f = self.factory.move_map(25, 0, -1, -1)
        self._send(f.opcode, f.payload)
        self.outbound_log.append({'op': f.opcode, 'hex': f.payload.hex(), 'ts': time.time()})
        time.sleep(2.5)
        self._drain_responses(1.5)

        # 1. buy_item(uid, 0) — inisialisasi area farm
        f = self.factory.buy_item(uid, 0)
        self._send(f.opcode, f.payload)
        self.outbound_log.append({'op': f.opcode, 'hex': f.payload.hex(), 'ts': time.time()})
        print(f"[>] op61 buy_item(uid={uid}, qty=0)")
        time.sleep(1.0)
        self._drain_responses(1.0)

        # 2. cast rod (op 82) untuk load sprite farm
        f = self.factory.action_82(0, 3)
        self._send(f.opcode, f.payload)
        self.outbound_log.append({'op': f.opcode, 'hex': f.payload.hex(), 'ts': time.time()})
        print(f"[>] op82 cast_rod(kind=0, sprite=3)")
        time.sleep(1.0)
        self._drain_responses(1.5)

        # 3. Load avatar sprites
        for img_id in [0x4703, 0x4e01, 0x2c01]:
            f = self.factory.avatar_img(img_id)
            self._send(f.opcode, f.payload)
            time.sleep(0.1)
        self._drain_responses(1.5)

        # 4. cast rod lagi untuk state
        f = self.factory.action_82(0, 46)
        self._send(f.opcode, f.payload)
        self.outbound_log.append({'op': f.opcode, 'hex': f.payload.hex(), 'ts': time.time()})
        print(f"[>] op82 cast_rod(kind=0, sprite=46)")
        time.sleep(1.0)
        self._drain_responses(1.5)

        # 5. TEND PER PLOT: op65(uid, plotId, action=100) + op64(112,3,1) INTERLEAVED
        # Dari sniff v2 idx 303-360: setiap plot adalah pasangan op65 → op64
        # Server balas op-10 (notifikasi) per plot
        print(f"[>] Tending {total_plots} farm plots (interleaved op65+op64)...")
        ready_plots = []
        for plot_id in range(total_plots):
            # a. tend plot
            f = self.factory.join_farm(uid, plot_id, 0x64)
            self._send(f.opcode, f.payload)
            self.outbound_log.append({'op': f.opcode, 'hex': f.payload.hex(), 'ts': time.time()})
            time.sleep(0.25)
            
            # b. request info (SELALU 112,3,1 — dari sniff)
            f = self.factory.request_info(112, 3, 1)
            self._send(f.opcode, f.payload)
            self.outbound_log.append({'op': f.opcode, 'hex': f.payload.hex(), 'ts': time.time()})
            time.sleep(0.25)
            
            # c. baca response — op-10 panjang 66/23 = status plot
            resp = self.sniffer.get(timeout=0.4)
            if resp:
                op_name = self._get_op_name(resp.opcode)
                if resp.opcode == -10:
                    # Cek jika mengandung "siap panen" atau status
                    txt = self._extract_text(resp.payload)
                    if 'panen' in txt.lower() or 'siap' in txt.lower():
                        ready_plots.append(plot_id)
                        print(f"  [!!!] Plot {plot_id} SIAP PANEN: {txt[:50]}")
                elif resp.opcode == 66:
                    print(f"  [>>>] Server push HARVEST plot {plot_id}: {resp.payload.hex()}")
                    ready_plots.append(plot_id)
            
            if plot_id % 8 == 7:
                print(f"  ... plot {plot_id+1}/{total_plots}")
        
        print(f"[farm] Plot siap panen: {ready_plots}")
        
        # 6. HARVEST: op66(uid, plotId) untuk plot yang siap
        # Jika ready_plots kosong, coba semua plot (bot proaktif)
        target_plots = ready_plots if ready_plots else list(range(total_plots))
        print(f"[>] Harvesting {len(target_plots)} plots...")
        harvest_count = 0
        for plot_id in target_plots:
            f = self.factory.farm_harvest(uid, plot_id)
            self._send(f.opcode, f.payload)
            self.outbound_log.append({'op': f.opcode, 'hex': f.payload.hex(), 'ts': time.time()})
            time.sleep(0.3)
            
            # Cek response
            resp = self.sniffer.get(timeout=0.4)
            if resp and resp.opcode == 66:
                # Server balas 22004b → [byte plot][byte status][byte reward]
                b = resp.payload
                if len(b) >= 3:
                    status = b[1]
                    reward = b[2]
                    print(f"  [>>>] HARVEST plot={b[0]} status={status} reward={reward}")
                    harvest_count += 1
            elif resp and resp.opcode == -33:
                # COIN_UPDATE — dapat koin dari panen
                txt = self._extract_text(resp.payload)
                print(f"  [<] COIN_UPDATE: {resp.payload.hex()[:20]}")
            elif resp:
                pass  # ignore other
        
        print(f"[farm] Total harvest: {harvest_count}")

    def _drain_responses(self, duration: float):
        """Ambil dan tampilkan semua response yang masuk dalam duration detik"""
        end = time.time() + duration
        while time.time() < end:
            frame = self.sniffer.get(timeout=0.2)
            if frame:
                desc = decode_payload(frame.opcode, frame.payload)
                op_name = KNOWN_OPS.get(frame.opcode, "?")
                print(f"[<] op={frame.opcode:4d} ({op_name:16s}) len={len(frame.payload):4d} {desc}")

    def run_farm(self, cycles: int = 3):
        """Mode auto-farm: connect + login + farm loop"""
        if not self.connect_and_handshake():
            return False
        if not self.do_login_sequence():
            return False
        time.sleep(3.0)

        for i in range(cycles):
            print(f"\n=== FARM CYCLE {i+1}/{cycles} ===")
            self.auto_farm_cycle(user_id=self.user_id, total_plots=40)
            time.sleep(5.0)
        return True

    def run_farm_and_fish(self, farm_cycles: int = 1, fish_cycles: int = 1,
                          area: int = 16, sub: int = 4, spot: tuple = (284, 141)):
        """Kombinasi: farm dulu, lalu fish (zona fish bisa dipilih)"""
        if not self.connect_and_handshake():
            return False
        if not self.do_login_sequence():
            return False
        time.sleep(3.0)

        for i in range(farm_cycles):
            print(f"\n=== FARM CYCLE {i+1}/{farm_cycles} ===")
            self.auto_farm_cycle(user_id=self.user_id)
            time.sleep(3.0)

        for i in range(fish_cycles):
            print(f"\n=== FISH CYCLE {i+1}/{fish_cycles} ===")
            self.auto_fish_cycle(area=area, sub=sub, spot=spot)
            self.sniff_loop(8, f"fish-{i+1}")
            time.sleep(2.0)
        return True

    def _get_op_name(self, op: int) -> str:
        return KNOWN_OPS.get(op, "?")
    
    def _extract_text(self, payload: bytes) -> str:
        """Extract UTF strings dari payload"""
        from frame_decoder import _extract_strings
        strings = _extract_strings(payload)
        return ' | '.join(strings) if strings else payload.hex()[:40]
    
    def close(self):
        self.conn.close()

# =====================================================================
# PROXY SNIFFER (untuk HP — tangkap aksi nyata saat bermain)
# =====================================================================
def run_proxy_sniff(listen_host: str, listen_port: int, real_host: str,
                    real_port: int, dump_file: str):
    """Proxy transparan: game -> proxy -> server asli.
    Semua paket didekripsi (rolling XOR) dan dicatat ke dump_file.
    Dipakai di HP (Termux) bersama J2ME Loader dengan JAR yang sudah dipatch ke 127.0.0.1.
    """
    import threading as _th
    
    dump = open(dump_file, "w", buffering=1)
    dump.write("# Avatar Smart Fish proxy sniff\n")
    dump.write("# format: idx\tts\tdir\top\top_name\tlen\tdecoded\thex\n")
    lock = _th.Lock()
    counter = [0]

    def pump(direction, src, dst, session, is_server_side):
        buf = bytearray()
        # Setiap arah punya stream cipher SENDIRI (index mulai 0) —
        # jangan share, karena counter per arah independen.
        my_crypto = None

        def recv_exact(n):
            while len(buf) < n:
                chunk = src.recv(4096)
                if not chunk:
                    raise ConnectionError("closed")
                buf.extend(chunk)
                dst.sendall(chunk)   # forward verbatim
            out = bytes(buf[:n])
            del buf[:n]
            return out

        def wait_crypto():
            nonlocal my_crypto
            while my_crypto is None:
                c = session.get("key")
                if c is not None:
                    # buat stream sendiri utk arah ini
                    my_crypto = XorStream(c)
                else:
                    time.sleep(0.05)
            return my_crypto

        first = True
        try:
            while True:
                raw_op = recv_exact(1)[0]
                if first:
                    op = raw_op - 256 if raw_op >= 128 else raw_op
                    length = struct.unpack(">H", recv_exact(2))[0]
                    payload = recv_exact(length) if length else b""
                    first = False
                    if is_server_side and session.get("key") is None:
                        try:
                            klen = payload[0]
                            diff = payload[1:1+klen]
                            key = undiff_xor(diff)
                            session["key"] = key
                            session["ready"] = True
                            print(f"\n[KEY] {key.hex()} ({len(key)} bytes)")
                        except Exception as e:
                            print(f"[KEY] gagal: {e!r}")
                else:
                    crypto = wait_crypto()
                    # decode dengan stream arah ini sendiri
                    op_b = crypto.decode_read(raw_op) if is_server_side else crypto.encode_write(raw_op)
                    hi_raw = recv_exact(1)[0]
                    lo_raw = recv_exact(1)[0]
                    if is_server_side:
                        hi = crypto.decode_read(hi_raw)
                        lo = crypto.decode_read(lo_raw)
                    else:
                        hi = crypto.encode_write(hi_raw)
                        lo = crypto.encode_write(lo_raw)
                    length = (hi << 8) | lo
                    raw = recv_exact(length) if length else b""
                    if is_server_side:
                        payload = bytes(crypto.decode_read(x) for x in raw)
                    else:
                        payload = bytes(crypto.encode_write(x) for x in raw)
                    op = op_b - 256 if op_b >= 128 else op_b

                with lock:
                    counter[0] += 1
                    n = counter[0]
                    name = KNOWN_OPS.get(op, "?")
                    dec = decode_payload(op, payload).replace("\t", " ")
                    dump.write(f"{n}\t{time.time():.3f}\t{direction}\t{op}\t{name}\t{len(payload)}\t{dec}\t{payload.hex()}\n")
                    print(f"[{n:03d}] {direction} op={op:4d} ({name:15s}) len={len(payload):4d} {dec[:100]}")
        except (ConnectionError, OSError):
            pass

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((listen_host, listen_port))
    srv.listen(5)
    print(f"[*] PROXY listening {listen_host}:{listen_port} -> {real_host}:{real_port}")
    print(f"[*] Dump: {dump_file}")
    print("[*] Buka game (JAR patch 127.0.0.1), login, lakukan aksi fishing.")

    try:
        while True:
            cs, addr = srv.accept()
            print(f"[*] client: {addr}")
            try:
                ss = socket.create_connection((real_host, real_port), timeout=10)
            except OSError as e:
                print(f"[!] gagal ke server asli: {e!r}")
                cs.close()
                continue
            session = {}
            t1 = _th.Thread(target=pump, args=("C>S", cs, ss, session, False), daemon=True)
            t2 = _th.Thread(target=pump, args=("S>C", ss, cs, session, True), daemon=True)
            t1.start(); t2.start()
            t1.join(); t2.join()
            cs.close(); ss.close()
    except KeyboardInterrupt:
        print(f"\n[*] stop. dump: {dump_file}")
    finally:
        srv.close(); dump.close()


# =====================================================================
# JAR PATCHER (untuk sniff via HP/J2ME Loader)
# =====================================================================
def patch_utf8(data: bytes, old: bytes, new: bytes) -> bytes:
    """Patch Utf8 constant-pool entry di class file (atur ulang panjangnya)."""
    if len(data) < 10 or data[:4] != b"\xCA\xFE\xBA\xBE":
        raise ValueError("bukan class file")
    pos = 10
    cp_count = struct.unpack(">H", data[8:10])[0]
    i = 1
    out = bytearray(data[:10])
    patched = False
    while i < cp_count:
        tag = data[pos]
        if tag == 1:
            ln = struct.unpack(">H", data[pos+1:pos+3])[0]
            s = data[pos+3:pos+3+ln]
            if s == old:
                out += struct.pack(">BH", tag, len(new)) + new
                patched = True
            else:
                out += data[pos:pos+3+ln]
            pos += 3 + ln
        elif tag in (7, 8, 16, 19, 20):
            out += data[pos:pos+3]; pos += 3
        elif tag in (3, 4, 9, 10, 11, 12, 17, 18):
            out += data[pos:pos+5]; pos += 5
        elif tag in (5, 6):
            out += data[pos:pos+9]; pos += 9; i += 1
        elif tag == 15:
            out += data[pos:pos+4]; pos += 4
        else:
            raise ValueError(f"tag konstan {tag} aneh di {pos}")
        i += 1
    out += data[pos:]
    if not patched:
        raise ValueError(f"{old!r} tidak ditemukan di class")
    return bytes(out)


def patch_jar_host(input_jar: str, output_jar: str, new_host: str = "127.0.0.1"):
    """Ganti hostname di JAR — patch constant pool dengan benar, repack sama persis."""
    import zipfile
    old_host = "avatar-prod.ayomabar.com"
    old_bytes = old_host.encode('utf-8')
    new_bytes = new_host.encode('utf-8')

    with zipfile.ZipFile(input_jar, 'r') as zin:
        with zipfile.ZipFile(output_jar, 'w', zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename.endswith(".class") and old_bytes in data:
                    data = patch_utf8(data, old_bytes, new_bytes)
                    print(f"[patch] {item.filename} constant-pool Utf8: {old_host} -> {new_host}")
                zi = zipfile.ZipInfo(item.filename, date_time=item.date_time)
                zi.compress_type = item.compress_type
                zi.external_attr = item.external_attr
                zi.internal_attr = item.internal_attr
                zi.create_system = item.create_system
                zout.writestr(zi, data)
    print(f"[+] JAR patched saved to {output_jar}")

# =====================================================================
# ENTRY POINT
# =====================================================================
def load_accounts(path: str = AKUN_PATH) -> List[Tuple[str, str, str]]:
    """
    Baca multi-akun. Format fleksibel per baris:
      user:pass              (label = user)
      user:pass:LABEL
      id : user  /  password : pass   (blok format lama)
    Baris kosong / # = skip. Return list (username, password, label).
    """
    accounts: List[Tuple[str, str, str]] = []
    try:
        with open(path, "r") as f:
            lines = [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]
        blk_user = blk_pwd = None

        def flush_block():
            nonlocal blk_user, blk_pwd
            if blk_user and blk_pwd:
                accounts.append((blk_user, blk_pwd, blk_user))
            blk_user = blk_pwd = None

        for ln in lines:
            # format blok lama
            if "id :" in ln:
                flush_block()
                blk_user = ln.split("id :")[-1].strip()
                continue
            if "password :" in ln:
                blk_pwd = ln.split("password :")[-1].strip()
                continue
            # format baru user:pass[:label]
            parts = ln.split(":")
            if len(parts) >= 2 and parts[0].strip() and parts[1].strip():
                flush_block()
                u = parts[0].strip()
                p = parts[1].strip()
                lbl = parts[2].strip() if len(parts) >= 3 else u
                accounts.append((u, p, lbl))
        flush_block()
    except FileNotFoundError:
        print(f"[!] File {path} tidak ada")
    except Exception as e:
        print(f"[!] Gagal baca {path}: {e}")
    # dedupe by username
    seen = set()
    uniq = []
    for u, p, l in accounts:
        if u and u not in seen:
            seen.add(u)
            uniq.append((u, p, l))
    return uniq


# =====================================================================
# INFO PANEL (CLI)
# =====================================================================
class InfoPanel:
    """Panel informasi CLI: status akun, statistik sniffer, event live."""

    def __init__(self, bots: List["AvatarBot"]):
        self.bots = bots
        self.events = deque(maxlen=12)          # event ringkas terakhir
        self.start_time = time.time()
        self._stop = False
        self._thread: Optional[threading.Thread] = None
        self._last_lines = 0
        # pasang callback live di tiap sniffer
        for b in bots:
            if b.sniffer is not None:
                b.sniffer.on_frame = (lambda fr, _b=b: self.push_event(
                    f"[{_b.label}] < op{fr.opcode} {KNOWN_OPS.get(fr.opcode, '?')} len={len(fr.payload)}"))

    def push_event(self, text: str):
        ts = time.strftime("%H:%M:%S")
        self.events.append(f"{ts} {text}")

    def render(self):
        """Print panel satu layar (refresh in-place via ANSI)."""
        lines = []
        W = 78
        up = int(time.time() - self.start_time)
        lines.append("╔" + "═" * (W - 2) + "╗")
        lines.append(f"║{'AVATAR BOT — INFO PANEL':^{W-2}}║")
        lines.append("╠" + "═" * (W - 2) + "╣")
        lines.append(f"║ Uptime: {up:>6}s   Akun aktif: {len(self.bots):<3}" + " " * (W - 41) + "║")
        lines.append("╠" + "═" * (W - 2) + "╣")
        # ringkasan per bot
        for b in self.bots:
            st = b.info()
            sn = st.get("sniffer") or {}
            conn = "✓" if st["connected"] else "✗"
            login = "✓" if st["logged_in"] else "✗"
            fi = sn.get("frames_in", 0)
            fo = sn.get("frames_out", 0)
            unk = len(sn.get("unknown_ops", []))
            lines.append(
                f"║ {b.label[:14]:<14} uid={str(st['user_id'] or '-'):>5} "
                f"conn={conn} login={login} fish={st['fish_count']} farm={st['farm_count']} "
                f"in={fi:<4} out={fo:<4} unk={unk}"
            )
            pad = W - 1 - len(lines[-1])
            lines[-1] += " " * max(0, pad) + "║"
        lines.append("╠" + "═" * (W - 2) + "╣")
        lines.append("║ EVENT TERAKHIR" + " " * (W - 17) + "║")
        evs = list(self.events)[-8:]
        for i in range(8):
            if i < len(evs):
                txt = _vw(evs[i], W - 4)
                pad = W - 4 - len(txt)
                lines.append("║ " + txt + " " * max(0, pad) + " ║")
            else:
                lines.append("║" + " " * (W - 2) + "║")
        lines.append("╚" + "═" * (W - 2) + "╝")
        out = "\n".join(lines)
        if self._last_lines:
            # geser kursor ke atas sebanyak baris sebelumnya
            sys.stdout.write(f"\x1b[{self._last_lines}A\r")
        sys.stdout.write(out + "\n")
        sys.stdout.flush()
        self._last_lines = len(lines)

    def start(self, interval: float = 1.0):
        def loop():
            while not self._stop:
                self.render()
                time.sleep(interval)
        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop = True
        if self._thread:
            self._thread.join(timeout=2)


def _vw(s: str, n: int) -> str:
    """Ambil n karakter visual pertama (colokan aman untuk unicode)."""
    return s[:n]



def print_account_table(bots: List["AvatarBot"]):
    """Tabel status ringkas semua akun (mode info)."""
    print(f"{'LABEL':<16}{'UID':>8}{'CONN':>6}{'LOGIN':>7}{'FISH':>6}{'FARM':>6}{'IN':>7}{'OUT':>7}{'UNK':>5}")
    print("-" * 68)
    for b in bots:
        st = b.info()
        sn = st.get("sniffer") or {}
        print(f"{b.label[:15]:<16}"
              f"{str(st['user_id'] or '-'):>8}"
              f"{'OK' if st['connected'] else '-':>6}"
              f"{'OK' if st['logged_in'] else '-':>7}"
              f"{st['fish_count']:>6}"
              f"{st['farm_count']:>6}"
              f"{sn.get('frames_in', 0):>7}"
              f"{sn.get('frames_out', 0):>7}"
              f"{len(sn.get('unknown_ops', [])):>5}")
    print()


def run_multi_account(accounts: List[Tuple[str, str, str]], action: str,
                      cycles: int = 1, use_panel: bool = True) -> List[AvatarBot]:
    """
    Jalankan aksi untuk SEMUA akun secara sequential (aman dari rate-limit).
    Satu sesi login per akun, lalu aksi, lalu logout/close.
    """
    bots: List[AvatarBot] = []
    for idx, (user, pwd, label) in enumerate(accounts, 1):
        print(f"\n{'='*60}")
        print(f"[{idx}/{len(accounts)}] AKUN: {label} ({user})")
        print(f"{'='*60}")
        bot = AvatarBot(user, pwd, label)
        try:
            ok = False
            if action == "fish":
                ok = bot.run_fish(cycles=cycles)
            elif action == "farm":
                ok = bot.run_farm(cycles=cycles)
            elif action == "farmfish":
                ok = bot.run_farm_and_fish(farm_cycles=cycles, fish_cycles=cycles)
            elif action == "login":
                if bot.connect_and_handshake() and bot.do_login_sequence():
                    time.sleep(2.0)
                    ok = bool(bot.sniff_loop(8, f"login-{label}") or True)
            if ok or bot.logged_in:
                bots.append(bot)
            else:
                print(f"[!] {label}: aksi gagal")
        except Exception as e:
            print(f"[!] {label}: error {e}")
        finally:
            if not use_panel:
                bot.close()
    return bots


def cmd_info(accounts: List[Tuple[str, str, str]], live_seconds: int = 20):
    """
    Mode panel informasi:
    - login semua akun
    - tampilkan tabel status
    - live panel N detik (event stream)
    - export sniff session
    """
    bots: List[AvatarBot] = []
    for user, pwd, label in accounts:
        bot = AvatarBot(user, pwd, label)
        try:
            if bot.connect_and_handshake() and bot.do_login_sequence():
                time.sleep(1.5)
                bots.append(bot)
            else:
                print(f"[!] {label}: gagal login")
        except Exception as e:
            print(f"[!] {label}: {e}")
    if not bots:
        print("[!] Tidak ada akun yang berhasil login")
        return

    print("\n")
    print_account_table(bots)

    panel = InfoPanel(bots)
    panel.start(interval=1.0)
    print(f"\n[panel] Live {live_seconds}s — Ctrl+C untuk stop\n")
    try:
        time.sleep(live_seconds)
    except KeyboardInterrupt:
        pass
    panel.stop()

    # export + unknown alert
    os.makedirs("logs", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    for b in bots:
        if b.sniffer:
            b.sniffer.export_json(f"{LOGS_DIR}/sniff_session_{b.label}_{ts}.json")
            b.sniffer.unknown_alert()
            print()
    for b in bots:
        b.close()


def main():
    import argparse
    ap = argparse.ArgumentParser(
        prog="bot.py",
        description="Avatar Art Gaming bot — fish/farm/multi-akun/panel/sniffer",
        epilog="Contoh: python3 bot.py fish -c 3  |  python3 bot.py all -c 2  |  python3 bot.py info")
    ap.add_argument("mode", choices=[
        "sniff", "login", "fish", "farm", "farmfish", "all",
        "info", "panel", "proxy", "patch"], help="mode eksekusi")
    ap.add_argument("-c", "--cycles", type=int, default=1,
                    help="jumlah siklus (default 1)")
    ap.add_argument("-a", "--account", type=str, default=None,
                    help="indeks/nama akun (1-based, atau label). Default: SEMUA")
    ap.add_argument("-t", "--time", type=int, default=20,
                    help="durasi sniff/info detik (default 20)")
    ap.add_argument("--no-panel", action="store_true",
                    help="matikan live panel pada mode all")
    args = ap.parse_args()

    mode = args.mode.lower()

    # --- patch mode: tidak butuh akun ---
    if mode == "patch":
        input_jar = "1788339992416-avatar-art-gaming-auto-fish.jar"
        output_jar = "game_patched_localhost.jar"
        patch_jar_host(input_jar, output_jar, "127.0.0.1")
        return

    # --- proxy mode: tidak butuh akun ---
    if mode == "proxy":
        run_proxy_sniff("0.0.0.0", 19126, HOST, PORT, os.path.join(LOGS_DIR, "proxy_sniff.log"))
        return

    # --- load akun (multi) ---
    accounts = load_accounts(AKUN_PATH)
    if not accounts:
        print("[!] Tidak ada akun valid di akun.txt")
        sys.exit(1)

    # filter akun jika -a dipakai
    if args.account:
        sel = []
        for spec in args.account.split(","):
            spec = spec.strip()
            if spec.isdigit():
                i = int(spec) - 1
                if 0 <= i < len(accounts):
                    sel.append(accounts[i])
                else:
                    print(f"[!] Index akun {spec} di luar range (1-{len(accounts)})")
            else:
                match = [a for a in accounts if a[2].lower() == spec.lower()
                         or a[0].lower() == spec.lower()]
                if match:
                    sel.extend(match)
                else:
                    print(f"[!] Akun '{spec}' tidak ditemukan")
        accounts = sel
        if not accounts:
            sys.exit(1)

    multi = len(accounts) > 1
    print(f"[+] Akun terpilih: {len(accounts)} → {[a[2] for a in accounts]}")

    # ---------------- MODE MULTI-ACCOUNT (all) ----------------
    if mode == "all":
        bots = run_multi_account(accounts, "farmfish", cycles=args.cycles,
                                 use_panel=not args.no_panel)
        print("\n=== RINGKASAN MULTI-AKUN ===")
        print_account_table(bots)
        return

    # ---------------- MODE PANEL INFO ----------------
    if mode in ("info", "panel"):
        cmd_info(accounts, live_seconds=max(args.time, 10))
        return

    # ---------------- MODE SATU-BAYAK SEQUENTIAL ----------------
    if multi:
        action = {"fish": "fish", "farm": "farm", "farmfish": "farmfish",
                  "login": "login"}.get(mode)
        bots = run_multi_account(accounts, action, cycles=args.cycles,
                                 use_panel=not args.no_panel)
        print("\n=== RINGKASAN MULTI-AKUN ===")
        print_account_table(bots)
        return

    # ---------------- MODE SINGLE ACCOUNT ----------------
    user, pwd, label = accounts[0]
    bot = AvatarBot(user, pwd, label)
    try:
        if mode == "sniff":
            if not bot.connect_and_handshake():
                return
            bot.sniff_loop(args.time, "sniff")
            if bot.sniffer:
                bot.sniffer.unknown_alert()
        elif mode == "login":
            if not bot.connect_and_handshake():
                return
            if not bot.do_login_sequence():
                return
            time.sleep(2.0)
            bot.sniff_loop(max(args.time, 20), "login")
        elif mode == "fish":
            bot.run_fish(cycles=args.cycles)
        elif mode == "farm":
            bot.run_farm(cycles=args.cycles)
        elif mode == "farmfish":
            bot.run_farm_and_fish(farm_cycles=args.cycles, fish_cycles=args.cycles)
        else:
            ap.print_help()
            return

        # export sesi + unknown alert
        if bot.sniffer:
            os.makedirs("logs", exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            bot.sniffer.export_json(f"{LOGS_DIR}/sniff_session_{label}_{ts}.json")
            bot.sniffer.unknown_alert()
    except KeyboardInterrupt:
        print("\n[!] Dihentikan user")
    except Exception as e:
        print(f"[!] Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        bot.close()


if __name__ == "__main__":
    main()