#!/usr/bin/env python3
"""
dashboard.py — TUI Dashboard Avatar Bot (Textual + Rich) v0.0.2
===============================================================
Menampilkan DASHBOARD SAJA: log & hasil sniff TIDAK ditampilkan di layar
(semua di-redirect ke file logs/dashboard_*.log).

Perubahan v0.0.2:
  - Multi-akun PARALEL (login + farming bersamaan, bukan bergantian)
  - Track jumlah mancing & ikan didapat per akun
  - Parse op 91 FISH_RESULT (simpan PNG ikan ke logs/fish_catch/)
  - Track gold/coin dari op -33 COIN_UPDATE
  - Extract info dari op -22 (stat update)
  - Fish result detail di tabel (nama file PNG + ukuran)

Jalankan:
    .venv/bin/python dashboard.py

Tombol:
    f = mulai/stop auto-fish   |  m = mulai/stop auto-farm
    a = mulai/stop ALL (farm+fish semua akun, PARALEL)
    s = snapshot statistik     |  x = export sesi sniff (JSON)
    q = keluar
"""
from __future__ import annotations

import io
import os
import sys
import time
import struct
import contextlib
import threading
import traceback
from datetime import datetime

# =====================================================================
# SUPPRESS OUTPUT — log/sniff tidak boleh muncul di layar dashboard.
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


sys.stdout = _Tee(_log_file)
sys.stderr = _Tee(_log_file)

# sekarang aman import bot (print-nya akan masuk file)
from bot import (  # noqa: E402
    AvatarBot,
    load_accounts,
    KNOWN_OPS,
    run_proxy_sniff,
    HOST,
    PORT,
)

from textual.app import App, ComposeResult  # noqa: E402
from textual.containers import Horizontal  # noqa: E402
from textual.widgets import (  # noqa: E402
    Header,
    Footer,
    DataTable,
    Static,
    RichLog,
    Button,
)
from textual.binding import Binding  # noqa: E402

VERSION = "0.0.2"


class AccountWorker:
    """Satu worker per akun, jalan di thread terpisah (PARALEL)."""

    def __init__(self, user: str, pwd: str, label: str, bridge):
        self.user = user
        self.pwd = pwd
        self.label = label
        self.bridge = bridge
        self.bot = AvatarBot(user, pwd, label)
        self.thread = None
        self.fished = 0          # jumlah casting/man'sik
        self.caught = 0          # jumlah ikan tertangkap
        self.gold = None         # gold/coin terakhir
        self.last_catch = None   # (file_png, size_bytes, timestamp)
        self.status = "menunggu"
        self.error = None
        self._patched = False

    # ---------- patch on_frame ----------
    def _make_cb(self):
        bridge = self.bridge
        label = self.label

        def cb(frame):
            op = frame.opcode
            payload = frame.payload

            # op82 CAST_ROD → increase mancing count
            if op == 82:
                self.fished += 1
                bridge._evt(f"[{label}] 🎣 Casting #{self.fished} len={len(payload)}")

            # op91 FISH_RESULT → ikan tertangkap + simpan PNG
            elif op == 91:
                self.caught += 1
                png_path = self._save_fish_png(payload)
                size = len(payload)
                self.last_catch = (png_path, size, time.time())
                bridge._evt(
                    f"[{label}] 🐟 IKAN #{self.caught}! "
                    f"PNG={os.path.basename(png_path) if png_path else '-'} "
                    f"({size} bytes)"
                )

            # op -33 COIN_UPDATE → parse gold
            elif op == -33:
                gold = self._parse_gold(payload)
                if gold is not None and gold != self.gold:
                    self.gold = gold
                    bridge._evt(f"[{label}] 💰 Gold/coin: {gold}")

            # op -22 STAT_UPDATE → extract fish count
            elif op == -22:
                stat = self._parse_stat(payload)
                if stat:
                    bridge._evt(f"[{label}] 📊 Stat update: {stat}")

            # op -8 WELCOME
            elif op == -8:
                bridge._evt(f"[{label}] ✅ Login OK (welcome)")

            # op -4 ZONE_INFO
            elif op == -4 and len(payload) >= 4:
                uid = struct.unpack(">i", payload[:4])[0]
                self.bot.user_id = uid
                bridge._evt(f"[{label}] 📍 UID: {uid}")

            # op -63 MAP_CONFIRM
            elif op == -63:
                bridge._evt(f"[{label}] 🗺️ Map confirm")

            # op 66 FARM_HARVEST
            elif op == 66:
                self.caught += 1
                bridge._evt(f"[{label}] 🌾 Farm harvest response")

            # unknown op
            elif op not in KNOWN_OPS:
                bridge._evt(f"[{label}] ⚠️ UNKNOWN op {op} len={len(payload)}")

        return cb

    def _parse_gold(self, payload: bytes):
        """Parse op -33 COIN_UPDATE: [int0][short0][short gold][...]"""
        if len(payload) >= 8:
            try:
                return struct.unpack(">H", payload[6:8])[0]
            except Exception:
                return None
        return None

    def _parse_stat(self, payload: bytes):
        """Parse op -22 STAT_UPDATE: extract key fields"""
        if len(payload) >= 8:
            try:
                uid = struct.unpack(">i", payload[:4])[0]
                fish = struct.unpack(">H", payload[4:6])[0]
                return f"uid={uid} stat={fish}"
            except Exception:
                return None
        return None

    def _save_fish_png(self, payload: bytes):
        """Cari PNG signature di payload, simpan ke logs/fish_catch/"""
        try:
            idx = payload.find(b"\x89PNG")
            if idx == -1:
                return None
            png = payload[idx:]
            fname = f"{self.label}_{int(time.time())}_{self.caught}.png"
            fpath = os.path.join(LOGS_DIR, "fish_catch", fname)
            with open(fpath, "wb") as f:
                f.write(png)
            return fpath
        except Exception:
            return None

    # ---------- worker ----------
    def _wrap_login(self):
        """Pastikan on_frame terpasang setiap do_login_sequence."""
        bridge = self.bridge
        orig = self.bot.do_login_sequence
        self.bot.sniffer = None

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
                    ok = self.bot.run_fish(cycles=9999)
                elif action == "farm":
                    ok = self.bot.run_farm(cycles=9999)
                elif action == "all":
                    ok = self.bot.run_farm_and_fish(farm_cycles=9999, fish_cycles=9999)
                else:
                    return
                if not ok:
                    self.error = "connect/login gagal"
                    self.status = "error"
            except Exception as e:
                self.error = str(e)
                self.status = "error"
                self.bridge._evt(f"[{self.label}] ❌ Error: {e}")
                _log_file.write(traceback.format_exc())
            finally:
                self.bot.close()

    def info(self) -> dict:
        d = self.bot.info()
        d.update({
            "fished": self.fished,
            "caught": self.caught,
            "gold": self.gold,
            "last_catch": self.last_catch,
            "status": self.status,
            "error": self.error,
        })
        return d


class WorkerBridge:
    """Mengelola semua worker (satu per akun) — PARALEL."""

    def __init__(self):
        self.workers: list[AccountWorker] = []
        self.running: dict[str, bool] = {}
        self.events: list[str] = []
        self._lock = threading.Lock()
        self._action = None

    def start(self, action: str, accounts: list):
        if self.is_busy():
            return
        self._action = action
        self.running[action] = True
        # buat worker untuk setiap akun — semua dalam thread sendiri (PARALEL)
        self.workers = [
            AccountWorker(u, p, l, self) for u, p, l in accounts
        ]
        # start SEMUA worker sekaligus (paralel)
        for w in self.workers:
            w.status = "starting"
            w.start(action)
        self._evt(f"[SYSTEM] ▶ {action} start untuk {len(accounts)} akun (PARALEL)")

    def is_busy(self):
        return any(w.thread and w.thread.is_alive() for w in self.workers)

    def stop(self):
        self.running[self._action or ""] = False
        for w in self.workers:
            w.stop()
        self._evt("[SYSTEM] ⏹ Stop diminta ke semua worker")

    def _evt(self, text: str):
        ts = time.strftime("%H:%M:%S")
        with self._lock:
            self.events.append(f"{ts} {text}")
            self.events[:] = self.events[-200:]

    def snapshot(self) -> dict:
        with self._lock:
            evs = list(self.events[-15:])
        per_bot = [w.info() for w in self.workers]
        total_fished = sum(w.fished for w in self.workers)
        total_caught = sum(w.caught for w in self.workers)
        gold_vals = [w.gold for w in self.workers if w.gold is not None]
        return {
            "per_bot": per_bot,
            "total_fished": total_fished,
            "total_caught": total_caught,
            "total_gold": sum(gold_vals) if gold_vals else None,
            "events": evs,
            "busy": self.is_busy(),
        }


class AvatarDash(App):
    CSS = """
    Screen { layout: vertical; }
    #stats { height: auto; padding: 0 1; }
    #table { height: 1fr; }
    #events { height: 30%; border: round $accent; padding: 0 1; }
    #buttons { height: auto; padding: 0 1; }
    Button { margin-right: 1; }
    """
    TITLE = f"Avatar Bot Dashboard v{VERSION}"
    SUB_TITLE = "multi-akun paralel · log ke file"

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
        self.accounts = load_accounts("akun.txt")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(id="stats")
        yield DataTable(id="table")
        with Horizontal(id="buttons"):
            yield Button("▶ Fish (f)", id="btn-fish")
            yield Button("▶ Farm (m)", id="btn-farm")
            yield Button("▶ All (a)", id="btn-all")
            yield Button("⏹ Stop", id="btn-stop")
            yield Button("💾 Export (x)", id="btn-export")
        yield RichLog(id="events", highlight=False, markup=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#table", DataTable)
        table.cursor_type = "row"
        for col in ("Akun", "UID", "Status", "Gold", "Mancing", "Ikan", "In", "Out", "Unk"):
            table.add_column(col)
        self.set_interval(1.0, self.refresh_data)
        self._log_evt(
            f"[dim]Dashboard v{VERSION} siap — "
            f"{len(self.accounts)} akun dimuat. Log: {_LOG_PATH}[/dim]"
        )

    def _log_evt(self, text: str):
        self.query_one("#events", RichLog).write(text)

    def refresh_data(self) -> None:
        snap = self.bridge.snapshot()
        st = snap["per_bot"]
        table = self.query_one("#table", DataTable)
        table.clear()
        if not st:
            table.add_row("(belum ada sesi — tekan f/m/a untuk mulai)",
                          "-", "-", "-", "-", "-", "-", "-", "-")
        for d in st:
            sn = d.get("sniffer") or {}
            status = d.get("status", "?")
            unk = len(sn.get("unknown_ops", []))
            table.add_row(
                d["label"],
                str(d.get("user_id") or "-"),
                status,
                str(d.get("gold") or "-"),
                str(d.get("fished", 0)),
                str(d.get("caught", 0)),
                str(sn.get("frames_in", 0)),
                str(sn.get("frames_out", 0)),
                str(unk),
            )
        # stats bar
        gold = snap["total_gold"]
        gold_s = f"{gold}" if gold is not None else "-"
        self.query_one("#stats", Static).update(
            f"🎣 Total Mancing: [b]{snap['total_fished']}[/b]   "
            f"🐟 Ikan: [b]{snap['total_caught']}[/b]   "
            f"💰 Gold: [b]{gold_s}[/b]   "
            f"Akun aktif: {len(snap['per_bot'])}   "
            f"Status: {'[green]BERJALAN[/green]' if snap['busy'] else '[yellow]idle[/yellow]'}"
        )
        # event baru dari bridge → RichLog
        evs = snap["events"]
        seen = getattr(self, "_seen_events", 0)
        if len(evs) > seen:
            for e in evs[seen:]:
                self._log_evt(e.replace("[", "\\[") if "\\[" not in e else e)
            self._seen_events = len(evs)

    def action_toggle(self, action: str) -> None:
        if self.bridge.is_busy():
            self._log_evt("[yellow]Sesi sedang berjalan — tekan Stop dulu.[/yellow]")
            return
        self.bridge.start(action, self.accounts)
        self._log_evt(
            f"[green]▶ Start {action} untuk {len(self.accounts)} akun "
            f"(PARALEL)[/green]"
        )

    def action_proxy(self) -> None:
        if self.bridge.is_busy():
            self._log_evt("[yellow]Sesi sedang berjalan — tekan Stop dulu.[/yellow]")
            return
        self._log_evt("[green]▶ Proxy aktif di :19126 (dump: logs/proxy_sniff.log)[/green]")
        self.bridge.start("proxy", [])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-fish":
            self.action_toggle("fish")
        elif bid == "btn-farm":
            self.action_toggle("farm")
        elif bid == "btn-all":
            self.action_toggle("all")
        elif bid == "btn-stop":
            self.bridge.stop()
            self._log_evt("[red]⏹ Stop diminta[/red]")
        elif bid == "btn-export":
            self.action_export()

    def action_snapshot(self) -> None:
        snap = self.bridge.snapshot()
        import json
        path = os.path.join(LOGS_DIR, f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        with open(path, "w") as f:
            json.dump(snap, f, indent=2, ensure_ascii=False, default=str)
        self._log_evt(f"[blue]Snapshot → {path}[/blue]")

    def action_export(self) -> None:
        n = 0
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        for w in self.bridge.workers:
            if w.bot.sniffer:
                w.bot.sniffer.export_json(os.path.join(LOGS_DIR, f"sniff_session_{w.label}_{ts}.json"))
                n += 1
        self._log_evt(f"[blue]Export {n} sesi sniff selesai[/blue]")

    def action_quit(self) -> None:
        self.bridge.stop()
        self.exit()


def main():
    app = AvatarDash()
    app.run()


if __name__ == "__main__":
    main()
