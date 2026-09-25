#!/usr/bin/env python3
"""
frame_decoder.py — Decoder frame Avatar Smart Fish v2
Update dari proxy_sniff_v2.log (1243 paket, 292 detik gameplay)

Opcodes dikenal (dari dF.java + cI.class + sniff v1+v2):
  Negatif (system):
    -27 HANDSHAKE       -17 CLIENT_INIT1     -14 LOAD_SPRITE
    -11 SKILL_DATA      -10 NOTIF_MSG         -8 WELCOME_MSG
     -6 CHAT_MSG         -4 ZONE_INFO         -2 LOGIN_REQ
     -1 DEVICE_INFO
  Negatif (fitur):
    -98 SPRITE_REQ      -97 COSTUME_DATA     -84 PET_DATA
    -80 AVATAR_IMG      -79 CLIENT_INIT2     -70 PLAYER_ID
    -63 MAP_CONFIRM     -61 NPC_INTERACT     -59 NPC_MENU
    -52 SESSION_HASH    -49 NPC_SHOP_LIST    -48 PET_SPAWN
    -33 COIN_UPDATE     -24 SHOP_BUY         -22 STAT_UPDATE
  Positif (game action):
     50 MOVE_MAP         51 GIFTCODE          53 GIFTCODE_RESP
     54 JOIN_AREA        55 ACTION_BASIC      56 ACTION_BASIC2
     57 AREA_NPC         60 AREA_EVENT        61 BUY_ITEM
     62 GIVE_ITEM        64 REQUEST_INFO      65 FARM_ACTION
     66 FARM_HARVEST     71 HARVEST           74 SELL_FISH
     78 QUEST_INFO       79 QUEST_UPDATE      82 CAST_ROD
     84 FINISH_FISHING   85 DO_CAU_CA_XONG    86 BUY_BAIT
     91 FISH_RESULT      96 IDLE
"""

import struct
from typing import Optional, Tuple, List

# =====================================================================
# OPCODE MAP — semua opcode dari sniff v1 + v2
# =====================================================================
KNOWN_OPS = {
    # system / login
    -27: "HANDSHAKE",
    -17: "CLIENT_INIT1",
    -14: "LOAD_SPRITE",
    -11: "SKILL_DATA",
    -10: "NOTIF_MSG",
     -9: "VERIFY_PIN",
     -8: "WELCOME_MSG",
     -6: "CHAT_MSG",
     -4: "ZONE_INFO",
     -2: "LOGIN_REQ",
     -1: "DEVICE_INFO",
    # fitur
    -98: "SPRITE_REQ",
    -97: "COSTUME_DATA",
    -84: "PET_DATA",
    -80: "AVATAR_IMG",
    -79: "CLIENT_INIT2",
    -70: "PLAYER_ID",
    -63: "MAP_CONFIRM",
    -61: "NPC_INTERACT",
    -59: "NPC_MENU",
    -52: "SESSION_HASH",
    -49: "NPC_SHOP_LIST",
    -48: "PET_SPAWN",
    -33: "COIN_UPDATE",
    -24: "SHOP_BUY",
    -22: "STAT_UPDATE",
    # game action
     50: "MOVE_MAP",
     51: "GIFTCODE",
     53: "GIFTCODE_RESP",
     54: "JOIN_AREA",
     55: "ACTION_BASIC",
     56: "ACTION_BASIC2",
     57: "AREA_NPC",
     60: "AREA_EVENT",
     61: "BUY_ITEM",
     62: "GIVE_ITEM",
     64: "REQUEST_INFO",
     65: "FARM_ACTION",
     66: "FARM_HARVEST",
     71: "HARVEST",
     74: "SELL_FISH",
     78: "QUEST_INFO",
     79: "QUEST_UPDATE",
     82: "CAST_ROD",
     84: "FINISH_FISHING",
     85: "DO_CAU_CA_XONG",
     86: "BUY_BAIT",
     91: "FISH_RESULT",
     96: "IDLE",
}

# =====================================================================
# HELPERS
# =====================================================================
def read_utf(buf: bytes, offset: int) -> Tuple[Optional[str], int]:
    """Baca writeUTF: [len:2BE][data]"""
    if offset + 2 > len(buf):
        return None, offset
    ln = struct.unpack(">H", buf[offset:offset+2])[0]
    offset += 2
    if offset + ln > len(buf):
        return None, offset
    try:
        s = buf[offset:offset+ln].decode('utf-8', errors='replace')
    except:
        s = buf[offset:offset+ln].hex()
    return s, offset + ln

def read_int(buf: bytes, offset: int) -> Tuple[Optional[int], int]:
    if offset + 4 > len(buf):
        return None, offset
    v = struct.unpack(">i", buf[offset:offset+4])[0]
    return v, offset + 4

def read_short(buf: bytes, offset: int) -> Tuple[Optional[int], int]:
    if offset + 2 > len(buf):
        return None, offset
    v = struct.unpack(">h", buf[offset:offset+2])[0]
    return v, offset + 2

def read_byte(buf: bytes, offset: int) -> Tuple[Optional[int], int]:
    if offset >= len(buf):
        return None, offset
    return buf[offset], offset + 1

# =====================================================================
# PAYLOAD DECODER
# =====================================================================
def decode_payload(opcode: int, payload: bytes) -> str:
    """Decode payload frame berdasarkan opcode — v2 enriched"""
    if not payload:
        return "(empty)"
    
    try:
        # --- SYSTEM ---
        if opcode == -8:
            msg, _ = read_utf(payload, 0)
            return f'msg="{msg}"'
        
        elif opcode == -6:
            off = 0
            sender_id, off = read_int(payload, off)
            sender, off = read_utf(payload, off)
            msg, off = read_utf(payload, off)
            return f"from='{sender}' ({sender_id}): '{msg}'"
        
        elif opcode == -4:
            # ZONE_INFO: [int userId][byte][short][short][int]...strings
            off = 0
            uid, off = read_int(payload, off)
            strings = []
            while off < len(payload) - 2:
                s, next_off = read_utf(payload, off)
                if s and 2 <= len(s) <= 64 and all(32 <= ord(c) < 127 for c in s):
                    strings.append(s)
                    off = next_off
                else:
                    off += 1
            return f'userId={uid}, strings={strings[:8]}'
        
        elif opcode == -10:
            # NOTIF_MSG: cari UTF strings
            strings = _extract_strings(payload)
            if strings:
                return f'{len(payload)}b strings={strings[:3]}'
            return f'{len(payload)}b raw={payload.hex()[:60]}'
        
        elif opcode == -33:
            # COIN_UPDATE: 17 bytes
            if len(payload) >= 17:
                off = 0
                v1, off = read_int(payload, off)
                v2, off = read_int(payload, off)
                coins, off = read_int(payload, off)
                v4, off = read_int(payload, off)
                return f'coins={coins} (v1={v1} v2={v2} v4={v4}) last={payload[off:]}'
            return f'{len(payload)}b raw={payload.hex()[:60]}'
        
        elif opcode == -24:
            # SHOP_BUY: [short itemId][byte qty]
            if len(payload) >= 3:
                item = struct.unpack('>H', payload[0:2])[0]
                qty = payload[2]
                return f'item=0x{item:04x}({item}) qty={qty}'
            return f'{len(payload)}b raw={payload.hex()[:60]}'
        
        elif opcode == -22:
            # STAT_UPDATE: 17 bytes
            if len(payload) >= 17:
                parts = []
                off = 0
                for name in ['uid', 'stat1', 'stat2', 'stat3']:
                    v, off = read_int(payload, off)
                    parts.append(f'{name}={v}')
                return ', '.join(parts) + f' last={payload[off:].hex()}'
            return f'{len(payload)}b raw={payload.hex()[:60]}'
        
        elif opcode == -59:
            # NPC_MENU: [int npcId][byte count][count x UTF]
            strings = _extract_strings(payload)
            return f'{len(payload)}b strings={strings[:6]}'
        
        elif opcode == -49:
            # NPC_SHOP_LIST
            strings = _extract_strings(payload)
            return f'{len(payload)}b strings={strings[:6]}'
        
        # --- GAME ACTIONS ---
        elif opcode == 50:
            # MOVE_MAP: [byte area][byte sub][short posX][short posY]...
            if len(payload) >= 6:
                area = payload[0]
                sub = payload[1]
                px = struct.unpack('>h', payload[2:4])[0]
                py = struct.unpack('>h', payload[4:6])[0]
                extra = ''
                if len(payload) > 6:
                    strings = _extract_strings(payload[6:])
                    if strings:
                        extra = f' strings={strings[:4]}'
                return f'area={area} sub={sub} pos=({px},{py}){extra}'
            return f'{len(payload)}b raw={payload.hex()[:60]}'
        
        elif opcode == 54:
            # JOIN_AREA: C>S 7 byte [short X][short Y][byte dir][short unk]
            #            S>C 9 byte [int userId][short X][short Y][byte dir]
            if len(payload) == 7:
                x = struct.unpack('>h', payload[0:2])[0]
                y = struct.unpack('>h', payload[2:4])[0]
                d = payload[4]
                u = struct.unpack('>h', payload[5:7])[0]
                return f'x={x} y={y} dir={d} unk={u}'
            elif len(payload) == 9:
                uid = struct.unpack('>i', payload[0:4])[0]
                x = struct.unpack('>h', payload[4:6])[0]
                y = struct.unpack('>h', payload[6:8])[0]
                d = payload[8]
                return f'uid={uid} x={x} y={y} dir={d}'
            return f'{len(payload)}b raw={payload.hex()[:60]}'
        
        elif opcode == 64:
            # REQUEST_INFO: [int n][byte n2][byte n3]
            if len(payload) == 6:
                n, off = read_int(payload, 0)
                n2, off = read_byte(payload, off)
                n3, off = read_byte(payload, off)
                return f'n={n} n2={n2} n3={n3}'
            return f'{len(payload)}b raw={payload.hex()[:60]}'
        
        elif opcode == 65:
            # FARM_ACTION: C>S [int userId][byte slot][short action]
            #              S>C [byte status][short ??]
            if len(payload) == 7:
                uid, off = read_int(payload, 0)
                slot, off = read_byte(payload, off)
                act = struct.unpack('>h', payload[off:off+2])[0]
                return f'uid={uid} slot={slot} action={act}'
            elif len(payload) == 3:
                return f'status={payload[0]} short={struct.unpack(">h", payload[1:3])[0]}'
            return f'{len(payload)}b raw={payload.hex()[:60]}'
        
        elif opcode == 82:
            # CAST_ROD: 0 atau 4 bytes
            if len(payload) == 4:
                v = struct.unpack('>i', payload)[0]
                return f'value={v}'
            elif len(payload) == 0:
                return '(cast)'
            return f'{len(payload)}b raw={payload.hex()[:60]}'
        
        elif opcode == 84:
            # FINISH_FISHING: C>S 8 byte, S>C 6 byte
            return f'{len(payload)}b raw={payload.hex()}'
        
        elif opcode == 86:
            # BUY_BAIT: C>S 0 byte, S>C 3 byte
            if len(payload) == 0:
                return '(buy)'
            elif len(payload) >= 1:
                return f'result={payload[0]} rest={payload[1:].hex()}'
            return f'{len(payload)}b raw={payload.hex()[:60]}'
        
        elif opcode == 55:
            # ACTION_BASIC: cari strings
            strings = _extract_strings(payload)
            if strings:
                return f'{len(payload)}b strings={strings[:2]}'
            return f'{len(payload)}b raw={payload.hex()[:60]}'
        
        elif opcode == 51:
            # GIFTCODE: string
            strings = _extract_strings(payload)
            if strings:
                return f'code={strings[0]}'
            return f'{len(payload)}b raw={payload.hex()[:60]}'
        
        elif opcode == 91:
            # FISH_RESULT
            return f'{len(payload)}b raw={payload.hex()[:60]}'
        
        elif opcode == 62:
            # GIVE_ITEM: [int n1][byte n2]
            if len(payload) == 4:
                v = struct.unpack('>i', payload)[0]
                return f'int={v} (0x{v:08x})'
            return f'{len(payload)}b raw={payload.hex()[:60]}'
        
        else:
            # Fallback: cari UTF strings
            strings = _extract_strings(payload)
            if strings:
                return f'{len(payload)}b strings={strings[:4]}'
            return f'{len(payload)}b raw={payload.hex()[:60]}'
    
    except Exception as e:
        return f'{len(payload)}b decode error: {e}'

def _extract_strings(payload: bytes) -> List[str]:
    """Scan payload untuk UTF strings"""
    strings = []
    off = 0
    while off < len(payload) - 2:
        s, next_off = read_utf(payload, off)
        if s and 2 <= len(s) <= 100 and all(32 <= ord(c) < 127 or c in '\n\r\t' for c in s):
            strings.append(s)
            off = next_off
        else:
            off += 1
    return strings

# =====================================================================
# FORMAT HELPERS
# =====================================================================
def format_frame(opcode: int, payload: bytes, direction: str = "<") -> str:
    """Format satu frame untuk log"""
    op_name = KNOWN_OPS.get(opcode, "?")
    desc = decode_payload(opcode, payload)
    return f"[{direction}] op={opcode:4d} ({op_name:16s}) len={len(payload):4d} {desc}"

def format_frame_hex(opcode: int, payload: bytes, direction: str = "<") -> str:
    """Format frame dengan full hex"""
    op_name = KNOWN_OPS.get(opcode, "?")
    hex_str = payload.hex()
    readable = decode_payload(opcode, payload)
    return (f"[{direction}] op={opcode} (0x{opcode & 0xFF:02x}, {op_name}) len={len(payload)}\n"
            f"        hex={hex_str}\n"
            f"        decoded: {readable}")
