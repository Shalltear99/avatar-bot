# Decoded Opcodes — Avatar v2 (dari sniff proxy_sniff_v3.log + verifikasi)

Sumber: sniff-tools/proxy_sniff_v3.log (2675 frame, 24 Sep)
Decoder: source-code/frame_decoder.py (decode_payload / KNOWN_OPS)

## OPCODE LOGIN / SESI

| Opcode | Nama | Arah | Payload |
|---|---|---|---|
| -27 | HANDSHAKE | C→S / S→C | XOR key exchange (diff-XOR) |
| -1 | HEARTBEAT | C→S | int 0 |
| -17 | CLIENT_INIT | C→S | client init |
| -79 | AGENT_ID | C→S | UTF agent ('0') |
| -52 | USER_HASH | C→S | hash user |
| -2 | LOGIN | C→S | [UTF user][UTF pass][UTF ver] |
| -4 | SERVER_WELCOME | S→C | welcome |
| -8 | WELCOME_MSG | S→C | chat welcome |

## OPCODE GAME

| Opcode | Nama | Arah | Payload |
|---|---|---|---|
| 50 | MOVE_MAP | C→S | [byte area][byte sub][short X][short Y] (ffff=auto) |
| 50 echo | MAP_CONFIRM | S→C | echo + daftar player/NPC (UTF strings) |
| 54 | JOIN_AREA | C→S 7b | [short X][short Y][byte dir][short unk] |
| 54 resp | JOIN_AREA | S→C 9b | [int uid][short X][short Y][byte dir] |
| 55 | ACTION_BASIC | S→C | notifikasi (ada UTF string, mis. 'afk lagi kerja') |
| 57 | AREA_STATE | C→S 1b | byte 0x02 (kirim setelah join area mancing) |
| -6 | CHAT_MSG | C→S | [int senderId][UTF msg] — chat biasa, BUKAN untuk NPC |
| 82 | CAST_ROD | C→S | kosong (manching) / (0,3) dst (farm, load sprite) |
| 84 | FINISH_FISHING | C→S 8b | hasil tangkapan |
| 85 | DO_CAU_CA_XONG | C→S | kosong — selesai mancing |
| 86 | BUY_BAIT | C→S 0b / S→C 3b | C→S kosong; S→C [result=1][00][00] = sukses |
| 61 | BUY_ITEM (farm init) | C→S | [int uid][byte 0] |
| 64 | REQUEST_INFO | C→S | [int uid][byte plotId][byte 255] |
| 65 | TEND_PLOT | C→S | [int uid][byte plotId][short action] |
| 66 | HARVEST | C→S | [int uid][byte plotId] |
| 71 | HARVEST_ALT | C→S | panen (ver lain) |
| 74 | SELL_ITEM | C→S | jual item ke NPC |
| -22 | STAT_UPDATE | S→C 17b | update stat player |
| -98 | PNG_CHUNK | S→C | gambar/sprite (PNG bytes) |
| -59 | NPC_MENU | S→C | menu NPC muncul SAAT dekat NPC di map (pasif) |
| -61 | NCP_INTERACT | C→S | interaksi menu NPC — TIDAK DIPAKAI untuk beli umpan |

## ALUR AUTO-FISH TERVERIFIKASI (sniff idx 134-231)

1. `op50` MOVE_MAP area=0x10 (16) sub=0xff → masuk area mancing (server balas daftar player)
2. `op54` JOIN_AREA × 2 (duduk di spot)
3. `op57` kirim byte 0x02
4. **`op86` BUY_BAIT payload KOSONG** → server balas `01 00 00` (result=1 = sukses)
   - **TANPA chat "CaUa", TANPA menu NPC (-59/-61)** — beli umpan langsung via opcode!
5. `op82` cast (mulai pancing)
6. `op84` FINISH_FISHING (8 byte hasil)
7. `op85` DO_CAU_CA_XONG (selesai)

Catatan: beli umpan hanya SEKALI saat masuk area (idx 226), bukan per-cast.
"CaUa" yang muncul di log = chat pemain lain (dari op -6 S→C), bukan perintah beli.

## ALUR AUTO-FARM (sniff v2 idx 284-470, 40 plot)

1. `op50` MOVE_MAP area=25 sub=0 → area farm
2. `op61` buy_item(uid, 0) — inisialisasi farm
3. `op82` cast_rod(0,3)/(0,46) — load sprite (server balas PNG via -98/-80)
4. `op65` tend(uid, plotId, action=100) × 40 plot
5. `op64` request_info(uid, plotId, 255) — cek status per plot
6. `op66` harvest(uid, plotId) — panen plot yang siap
