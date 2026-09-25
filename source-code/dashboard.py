#!/usr/bin/env python3
"""
dashboard.py — TUI Dashboard Avatar Bot (Textual + Rich) v0.0.3
===============================================================
DASHBOARD BERSIH (PRD v0.0.3):
  - Hanya ringkasan status di layar: tabel akun + stats bar + alert card.
  - TIDAK tampil: payload, hex, opcode, frame counter, unknown-op, stack trace.
  - Semua detail teknis → logs/dashboard_*.log
  - Kolom Gold & Stat tampil "?" sampai terverifikasi lewat analisis payload.
  - Alert card (maks 5): LOGIN_OK / LOGIN_GAGAL / PUTUS / IKAN_DAPAT / SELESAI.

Jalankan (Windows): .\\.venv\\Scripts\\python.exe source-code\\dashboard.py
Jalankan (Linux):   .venv/bin/python source-code/dashboard.py

Tombol: f fish · m farm · a all · p proxy · s snapshot · x export · q keluar
"""
from __future__ import annotations

import os
import sys
import time
import struct
import contextlib
import threading
import traceback
from datetime import datetime

# =====================================================================
# LOG KE FILE — output teknis TIDAK boleh muncul di layar dashboard.
# =====================================================================
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(os.path.join(LOGS_DIR, "fish_catch"), exist_ok=True)
_TS = datetime.now().strftime("%Y%m%d_%H%M%S")
_LOG_PATH = os.path.join(LOGS_DIR, f"dashboard_{_TS}.log")
_log_file = open(_LOG_PATH, "w", buffering=1, encoding="utf-8")


class _Tee:
    """Tulis ke file, jangan ke layar."""

    def __init__(self, f):
        self.f = f

    def write(self, s):
        try:
            self.f.write(s)
        except Exception:
            pass
        return len(s)

    def flush(self):
        try:
            self.f.flush()
        except Exception:
            pass

    def isatty(self):
        return False


# Import dependency DULU dengan error yang TERLIHAT di layar.
# (Sebelumnya import gagal = traceback masuk file log diam-diam → user lihat
#  program "keluar sendiri" tanpa pesan. Itu yang bikin "gabisa dibuka".)
try:
    from textual.app import App, ComposeResult  # noqa: E402
    from textual.containers import Horizontal, Vertical  # noqa: E402
    from textual.widgets import (  # noqa: E402
        Header,
        Footer,
        DataTable,
        Static,
        Button,
        Input,
    )
    from textual.binding import Binding  # noqa: E402
except ImportError as e:
    print("=" * 60)
    print("DEPENDENSI BELUM TERINSTALL!")
    print(f"  {e}")
    print()
    print("Jalankan salah satu dari folder avatar-bot:")
    print("  Windows : .\\.venv\\Scripts\\python.exe -m pip install textual rich")
    print("  Linux   : .venv/bin/python -m pip install textual rich")
    print("=" * 60)
    input("Tekan ENTER untuk keluar...")
    sys.exit(1)

sys.stdout = _Tee(_log_file)
sys.stderr = _Tee(_log_file)

from bot import (  # noqa: E402
    AvatarBot,
    load_accounts,
    KNOWN_OPS,
    HOST,
    PORT,
)

VERSION = "0.0.3"
MAX_ALERTS = 5

# =====================================================================
# DAFTAR ZONA MANCING — area ID dari sniff live (op 50 move_map).
# Tambahkan zona baru di sini setelah di-sniff dari HP.
# =====================================================================
# Zona mancing = SUB di area 16 (op 50: [area=16][sub=zona][x][y]).
# USER KONFIRMASI: zona 1-39 valid (semua bisa dipakai mancing).
# sub 4 = terverifikasi dari sniff live (x1684 pakai zona ini).
MAX_FISH_ZONE = 39
FISHING_ZONES = {}
for _z in range(1, MAX_FISH_ZONE + 1):
    FISHING_ZONES[f"zona{_z}"] = {
        "area": 16, "sub": _z, "spot": (284, 141),
        "desc": f"Zona memancing #{_z}",
    }
DEFAULT_ZONE = "zona4"   # sub 4 = terverifikasi dari sniff

# Kategori alert yang BOLEH tampil di dashboard (v0.0.3 + revisi user):
# utama: CASTING / CATCH / GET_FISH · status: LOGIN_OK / LOGIN_GAGAL / PUTUS / SELESAI
ALLOWED_ALERT_TAGS = {"LOGIN_OK", "LOGIN_GAGAL", "PUTUS", "SELESAI",
                      "CASTING", "CATCH", "GET_FISH"}


class AccountWorker:
    """Satu worker per akun, jalan di thread terpisah (PARALEL)."""

    def __init__(self, user: str, pwd: str, label: str, bridge,
                 zone: str = "default"):
        self.user = user
        self.pwd = pwd
        self.label = label
        self.bridge = bridge
        self.zone = zone
        z = FISHING_ZONES.get(zone, FISHING_ZONES[DEFAULT_ZONE])
        self.area = z["area"]
        self.sub = z["sub"]
        self.spot = z["spot"]
        self.bot = AvatarBot(user, pwd, label)
        self.thread = None
        self.fished = 0          # casting dikirim (op 82)
        self.caught = 0          # ikan tertangkap (op 91)
        self.coin = None         # coin = currency in-game (op -33, belum terverifikasi)
        self.gold = None         # gold = premium currency (belum terverifikasi)
        self.last_catch = None   # (file_png, size, ts)
        self.status = "menunggu"
        self.error = None

    # ---------- frame callback ----------
    def _make_cb(self):
        bridge = self.bridge
        label = self.label

        def cb(frame):
            op = frame.opcode
            payload = frame.payload

            if op == 82:                       # CAST_ROD → alert CASTING
                self.fished += 1
                bridge._alert(label, "CASTING",
                              f"🎣 casting #{self.fished}")
                bridge._log_tech(f"[{label}] op82 casting #{self.fished}")

            elif op == 91:                     # FISH_RESULT → CATCH + GET_FISH
                self.caught += 1
                png_path = self._save_fish_png(payload)
                self.last_catch = (png_path, len(payload), time.time())
                bridge._alert(label, "CATCH",
                              f"✅ catch #{self.caught}")
                bridge._alert(label, "GET_FISH",
                              f"🐟 get fish! ({os.path.basename(png_path) if png_path else 'no-png'})")
                bridge._log_tech(f"[{label}] op91 fish #{self.caught} "
                                 f"png={os.path.basename(png_path or '')}")

            elif op == -33:                    # CURRENCY_UPDATE (belum terverifikasi)
                coin, gold = self._parse_currency(payload)
                if coin is not None:
                    self.coin = coin
                if gold is not None:
                    self.gold = gold
                bridge._log_tech(f"[{label}] op-33 currency-update "
                                 f"(belum diverifikasi)")

            elif op == -22:                    # STAT_UPDATE (belum terverifikasi)
                bridge._log_tech(f"[{label}] op-22 stat-update (belum diverifikasi)")

            elif op == -8:                     # WELCOME → login sukses
                bridge._alert(label, "LOGIN_OK", "✅ login berhasil")

            elif op == -4 and len(payload) >= 4:   # ZONE_INFO → UID
                try:
                    uid = struct.unpack(">i", payload[:4])[0]
                    self.bot.user_id = uid
                    bridge._log_tech(f"[{label}] UID {uid}")
                except Exception:
                    pass

            elif op == 66:                     # FARM_HARVEST
                bridge._log_tech(f"[{label}] op66 farm harvest")

            elif op not in KNOWN_OPS:          # unknown → file log saja
                bridge._log_tech(
                    f"[{label}] UNKNOWN op {op} len={len(payload)}"
                )

        return cb

    def _parse_currency(self, payload: bytes):
        """
        PARIAL — struktur op -33 belum terverifikasi.
        Return (coin, gold); keduanya None kalau tidak bisa diparse.
        Coin = in-game currency, Gold = premium currency.
        """
        coin = gold = None
        if len(payload) >= 8:
            try:
                coin = struct.unpack(">H", payload[6:8])[0]
            except Exception:
                pass
        return coin, gold

    def _save_fish_png(self, payload: bytes):
        """Simpan PNG ikan (kalau ada) ke logs/fish_catch/."""
        try:
            idx = payload.find(b"\x89PNG")
            if idx == -1:
                return None
            fname = f"{self.label}_{int(time.time())}_{self.caught}.png"
            fpath = os.path.join(LOGS_DIR, "fish_catch", fname)
            with open(fpath, "wb") as f:
                f.write(payload[idx:])
            return fpath
        except Exception:
            return None

    # ---------- lifecycle ----------
    def _wrap_login(self):
        orig = self.bot.do_login_sequence

        def patched():
            ok = orig()
            if self.bot.sniffer is not None:
                self.bot.sniffer.on_frame = self._make_cb()
            return ok

        self.bot.do_login_sequence = patched

    def start(self, action: str):
        self._wrap_login()
        self.thread = threading.Thread(
            target=self._run_action, args=(action,), daemon=True)
        self.thread.start()

    def stop(self):
        self.status = "dihentikan"
        try:
            self.bot.close()
        except Exception:
            pass

    def _run_action(self, action: str):
        with contextlib.redirect_stdout(_Tee(_log_file)), \
             contextlib.redirect_stderr(_Tee(_log_file)):
            try:
                self.status = "login"
                if action == "fish":
                    ok = self.bot.run_fish(cycles=9999,
                                           area=self.area, sub=self.sub,
                                           spot=self.spot)
                elif action == "farm":
                    ok = self.bot.run_farm(cycles=9999)
                elif action == "all":
                    ok = self.bot.run_farm_and_fish(farm_cycles=9999, fish_cycles=9999,
                                                     area=self.area, sub=self.sub,
                                                     spot=self.spot)
                else:
                    return
                if not ok:
                    self.error = "connect/login gagal"
                    self.status = "error"
                    self.bridge._alert(self.label, "LOGIN_GAGAL",
                                       "❌ connect/login gagal")
            except Exception as e:
                self.error = str(e)
                self.status = "error"
                self.bridge._alert(self.label, "PUTUS", "❌ koneksi terputus")
                _log_file.write(traceback.format_exc())
            finally:
                self.bot.close()
                self.bridge._alert(self.label, "SELESAI", "worker selesai")

    def info(self) -> dict:
        d = self.bot.info()
        d.update({
            "fished": self.fished,
            "caught": self.caught,
            "coin": self.coin,          # UI tetap tampil "?" (belum terverifikasi)
            "gold": self.gold,          # UI tetap tampil "?" (belum terverifikasi)
            "last_catch": self.last_catch,
            "status": self.status,
            "error": self.error,
        })
        return d


class WorkerBridge:
    """Kumpulan worker paralel + pemisahan alert (UI) vs log teknis (file)."""

    def __init__(self):
        self.workers: list[AccountWorker] = []
        self.alerts: list[dict] = []      # {label, tag, text, ts} — untuk UI
        self._lock = threading.Lock()
        self._action = None

    # ---- UI: hanya alert penting ----
    def _alert(self, label: str, tag: str, text: str):
        if tag not in ALLOWED_ALERT_TAGS:
            return
        with self._lock:
            self.alerts.append(
                {"label": label, "tag": tag, "text": text,
                 "ts": time.strftime("%H:%M:%S")}
            )
            self.alerts[:] = self.alerts[-MAX_ALERTS:]

    # ---- file: semua detail teknis ----
    def _log_tech(self, text: str):
        _log_file.write(f"{time.strftime('%H:%M:%S')} {text}\n")

    # ---- kontrol ----
    def start(self, action: str, accounts: list, zone: str = DEFAULT_ZONE):
        if self.is_busy():
            return
        self._action = action
        self.workers = [AccountWorker(u, p, l, self, zone=zone)
                        for u, p, l in accounts]
        for w in self.workers:
            w.status = "starting"
            w.start(action)
        self._log_tech(f"SYSTEM ▶ {action} start untuk {len(accounts)} akun (paralel)")

    def is_busy(self):
        return any(w.thread and w.thread.is_alive() for w in self.workers)

    def stop(self):
        for w in self.workers:
            w.stop()
        self._log_tech("SYSTEM ⏹ stop diminta ke semua worker")

    def snapshot(self) -> dict:
        with self._lock:
            alerts = list(self.alerts)
        per_bot = [w.info() for w in self.workers]
        return {
            "per_bot": per_bot,
            "total_fished": sum(w.fished for w in self.workers),
            "total_caught": sum(w.caught for w in self.workers),
            "alerts": alerts,
            "busy": self.is_busy(),
        }


class AvatarDash(App):
    CSS = """
    Screen { layout: vertical; }
    #stats { height: auto; padding: 0 1; }
    #table { height: 1fr; }
    #alerts { height: 8; border: round $accent; padding: 0 1; }
    #alert-list { padding: 0 1; }
    #buttons { height: auto; padding: 0 1; }
    #zone-bar { height: auto; padding: 0 1; }
    #zone-bar > Static { padding: 0 1; width: auto; }
    #zone-bar > Button { margin-right: 1; min-width: 5; height: 3; }
    .zone-input { width: 8; margin-right: 1; }
    Button { margin-right: 1; }
    """
    TITLE = f"Avatar Bot Dashboard v{VERSION}"
    SUB_TITLE = "dashboard bersih · detail teknis hanya di logs/"

    BINDINGS = [
        Binding("f", "toggle('fish')", "Fish"),
        Binding("m", "toggle('farm')", "Farm"),
        Binding("a", "toggle('all')", "All"),
        Binding("p", "proxy", "Proxy"),
        Binding("s", "snapshot", "Snapshot"),
        Binding("x", "export", "Export"),
        Binding("q", "quit", "Keluar"),
    ]

    def __init__(self):
        super().__init__()
        self.bridge = WorkerBridge()
        self.accounts = load_accounts(
            os.path.join(PROJECT_ROOT, "source-code", "akun.txt"))

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(id="stats")
        yield DataTable(id="table")
        with Vertical(id="alerts"):
            yield Static("[b]Alert[/b] (maks 5)", id="alert-title")
            yield Static("(belum ada)", id="alert-list")
        with Horizontal(id="buttons"):
            yield Button("▶ Fish (f)", id="btn-fish")
            yield Button("▶ Farm (m)", id="btn-farm")
            yield Button("▶ All (a)", id="btn-all")
            yield Button("⏹ Stop", id="btn-stop")
            yield Button("💾 Export (x)", id="btn-export")
        with Horizontal(id="zone-bar"):
            yield Static("[b]Zona:[/b]", id="zone-label")
            yield Button("◀", id="zone-prev", classes="zone-btn")
            yield Input(value="4", placeholder="1-39",
                        id="zone-input", type="integer", classes="zone-input")
            yield Button("▶", id="zone-next", classes="zone-btn")
            yield Button("Set", id="zone-set", variant="primary", classes="zone-btn")
            yield Static("", id="zone-desc")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#table", DataTable)
        table.cursor_type = "row"
        for col in ("Akun", "UID", "Status", "Coin", "Gold",
                    "Casting", "Catch", "Get Fish"):
            table.add_column(col)
        self.set_interval(1.0, self.refresh_data)
        self._refresh_zone_highlight()

    def _refresh_zone_highlight(self):
        """Tampilkan zona aktif + koordinatnya di bar zona."""
        z = FISHING_ZONES[self.zone]
        self.query_one("#zone-label", Static).update(
            f"[b]Zona:[/b] [cyan]{self.zone}[/cyan]"
        )
        self.query_one("#zone-desc", Static).update(
            f"[dim]area={z['area']} sub={z['sub']} spot={z['spot']}[/dim]"
        )
        inp = self.query_one("#zone-input", Input)
        if str(z["sub"]) != inp.value:
            inp.value = str(z["sub"])

    def _zone_step(self, delta: int) -> None:
        """◀ / ▶ — pindah zona +/-1 dalam rentang 1..39."""
        cur = FISHING_ZONES[self.zone]["sub"]
        nxt = min(MAX_FISH_ZONE, max(1, cur + delta))
        self._set_zone(f"zona{nxt}")

    def _zone_from_input(self) -> None:
        """Ambil angka dari Input, validasi 1..39, set zona."""
        raw = self.query_one("#zone-input", Input).value.strip()
        try:
            n = int(raw)
        except ValueError:
            self.bridge._log_tech(f"SYSTEM zona '{raw}' bukan angka")
            return
        if not 1 <= n <= MAX_FISH_ZONE:
            self.bridge._log_tech(
                f"SYSTEM zona {n} di luar rentang 1..{MAX_FISH_ZONE}")
            return
        self._set_zone(f"zona{n}")

    def _set_zone(self, zname: str) -> None:
        """Ganti zona mancing (tolak jika sesi sedang berjalan)."""
        if self.bridge.is_busy():
            self.bridge._log_tech(f"SYSTEM zona '{zname}' DITOLAK — sesi berjalan")
            return
        if zname in FISHING_ZONES:
            self.zone = zname
            self._refresh_zone_highlight()
            self.bridge._log_tech(f"SYSTEM zona → {zname} "
                                  f"(area={FISHING_ZONES[zname]['area']})")

    def refresh_data(self) -> None:
        snap = self.bridge.snapshot()
        table = self.query_one("#table", DataTable)
        table.clear()
        if not snap["per_bot"]:
            table.add_row("(tekan f / m / a untuk mulai)",
                          "-", "-", "?", "?", "-", "-", "-")
        for d in snap["per_bot"]:
            # Coin & Gold → selalu "?" (belum terverifikasi, PRD v0.0.3)
            table.add_row(
                d["label"],
                str(d.get("user_id") or "-"),
                d.get("status", "?"),
                "?",   # coin  (in-game, belum terverifikasi)
                "?",   # gold  (premium, belum terverifikasi)
                str(d.get("fished", 0)),
                str(d.get("caught", 0)),
                str(d.get("caught", 0)),
            )
        self.query_one("#stats", Static).update(
            f"🎣 Casting: [b]{snap['total_fished']}[/b]   "
            f"✅ Catch: [b]{snap['total_caught']}[/b]   "
            f"🐟 Get Fish: [b]{snap['total_caught']}[/b]   "
            f"🪙 Coin: [b]?[/b] · 💰 Gold: [b]?[/b] (belum terverifikasi)   "
            f"Akun: {len(snap['per_bot'])}   "
            f"Status: {'[green]BERJALAN[/green]' if snap['busy'] else '[yellow]idle[/yellow]'}"
        )
        alerts = snap["alerts"]
        if alerts:
            lines = [
                f"[dim]{a['ts']}[/dim] [{a['label']}] {a['text']}"
                for a in alerts[-MAX_ALERTS:]
            ]
            self.query_one("#alert-list", Static).update("\n".join(lines))

    # ---------- actions ----------
    def action_toggle(self, action: str) -> None:
        if self.bridge.is_busy():
            return
        self.bridge.start(action, self.accounts, zone=self.zone)

    def action_proxy(self) -> None:
        if self.bridge.is_busy():
            return
        self.bridge._log_tech("SYSTEM ▶ proxy mode (dashboard tidak menampilkan sniff)")
        from bot import run_proxy_sniff
        threading.Thread(
            target=run_proxy_sniff,
            args=("0.0.0.0", 19126, HOST, PORT,
                  os.path.join(LOGS_DIR, "proxy_sniff.log")),
            daemon=True,
        ).start()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "zone-input":
            self._zone_from_input()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "zone-prev":
            self._zone_step(-1)
        elif bid == "zone-next":
            self._zone_step(+1)
        elif bid == "zone-set":
            self._zone_from_input()
        elif bid == "btn-fish":
            self.action_toggle("fish")
        elif bid == "btn-farm":
            self.action_toggle("farm")
        elif bid == "btn-all":
            self.action_toggle("all")
        elif bid == "btn-stop":
            self.bridge.stop()
        elif bid == "btn-export":
            self.action_export()

    def action_snapshot(self) -> None:
        import json
        path = os.path.join(
            LOGS_DIR,
            f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        with open(path, "w") as f:
            json.dump(self.bridge.snapshot(), f, indent=2,
                      ensure_ascii=False, default=str)
        self.bridge._log_tech(f"SYSTEM snapshot → {path}")

    def action_export(self) -> None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        for w in self.bridge.workers:
            if w.bot.sniffer:
                w.bot.sniffer.export_json(os.path.join(
                    LOGS_DIR, f"sniff_session_{w.label}_{ts}.json"))
        self.bridge._log_tech("SYSTEM export sniff selesai")

    def action_quit(self) -> None:
        self.bridge.stop()
        self.exit()


def main():
    try:
        AvatarDash().run()
    except Exception:
        # Kembalikan stdout asli supaya traceback TERLIHAT di layar
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        traceback.print_exc()
        print()
        input("Terjadi error. Tekan ENTER untuk keluar...")


if __name__ == "__main__":
    main()
