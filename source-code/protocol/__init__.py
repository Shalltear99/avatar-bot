# Protocol constants & opcodes untuk Avatar Art Gaming v2

HOST = "avatar-prod.ayomabar.com"
PORT = 19126

AKUN_PATH = "akun.txt"
LOG_DIR = "logs"

# Opcode map (dari sniff + dekompilasi)
KNOWN_OPS = {
    -27: "HANDSHAKE",
    -22: "?",
    -17: "CLIENT_INIT",
    -1: "LOGIN_OK",
    -79: "AGENT",
    -52: "HASH_USER",
    -8: "WELCOME",
    -6: "CHAT",
    -33: "?",
    -4: "LOGIN_RESP",
    50: "MOVE_MAP",
    54: "JOIN",
    64: "REQ_INFO",
    65: "RAWAT",
    71: "PANEN",
    74: "JUAL",
    84: "FINISH",
    85: "DO_CAU_CA_XONG",
    86: "UMPAN",
    82: "CAST_ROD",
    91: "FISH_RESULT",
}

DEFAULT_ZONE = 4
MAX_ZONE = 39
