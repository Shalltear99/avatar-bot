#!/usr/bin/env python3
"""
dashboard.py — TUI Dashboard Avatar Bot (Textual + Rich)
=========================================================
Menampilkan DASHBOARD SAJA: log & hasil sniff TIDAK ditampilkan di layar
(semua di-redirect ke file logs/dashboard_*.log).

Jalankan:
    .venv/bin/python dashboard.py

Tombol:
    f = mulai/stop auto-fish   |  m = mulai/stop auto-farm
    a = mulai/stop ALL (farm+fish semua akun)
    s = snapshot statistik     |  x = export sesi sniff (JSON)
    q = keluar
"""
from __future__ import annotations

import io
import os
import sys
import time
import contextlib
import traceback
from datetime import datetime

# =====================================================================
# SUPPRESS OUTPUT — log/sniff tidak boleh muncul di layar dashboard.
# bot.py memakai print() di banyak tempat; kita redirect stdout/stderr
# global ke file log sebelum import bot.
# =====================================================================
os.makedirs("logs", exist_ok=True)
_TS = datetime.now().strftime("%Y%m%d_%H%M%S")
_LOG_PATH = f"logs/dashboard_{_TS}.log"
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
    InfoPanel,
    load_accounts,
    KNOWN_OPS,
    run_proxy_sniff,
)

from textual.app import App, ComposeResult  # noqa: E402
from textual.containers import Horizontal, Vertical  # noqa: E402
from textual.widgets import (  # noqa: E402
    Header,
    Footer,
    DataTable,
    Static,
    RichLog,
    Button,
)
from textual.binding import Binding  # noqa: E402

VERSION = "0.0.1"


class WorkerBridge:
    """Menjalankan AvatarBot di thread + menampung event ringkas utk dashboard.
    Output print() dari bot TIDAK ditampilkan (sudah di-redirect global)."""

    def __init__(self):
        self.bots: list[AvatarBot] = []
        self.threads: list = []
        self.running: dict[str, bool] = {}
        self.events: list[str] = []          # event ringkas (op penting saja)
        self.fish_total = 0
        self.farm_total = 0
        self.harvest_events = 0
        self._lock = __import__("threading").Lock()

    # ---- event filter: hanya yang penting untuk dashboard ----
    def _interesting(self, op: int, name: str) -> str | None:
        if op == -8:
            return "login OK (welcome)"
        if op == -4:
            return "ZONE_INFO (userId)"
        if op == 91:
            return "FISH_RESULT (dapat ikan!)"
        if op == -33:
            return "coin/xu update"
        if op == -63:
            return "map confirm"
        if op == 66:
            return "farm harvest response"
        if op not in KNOWN_OPS:
            return f"UNKNOWN OPCODE {op} (game update?)"
        return None

    def start(self, action: str, accounts):
        import threading

        if self.is_busy():
            return
        self.running[action] = True
        t = threading.Thread(target=self._run_action, args=(action, accounts), daemon=True)
        self.threads.append(t)
        t.start()

    def is_busy(self) -> bool:
        return any(t.is_alive() for t in self.threads)

    def _patch_login_events(self, bot):
        """Pasang on_frame ke sniffer SEDINI mungkin (do_login_sequence membuat
        Sniffer baru) dengan wrapping do_login_sequence agar callback ikut."""
        bridge = self
        orig = bot.do_login_sequence

        def patched():
            bot.sniffer = None  # reset; do_login_sequence membuat yang baru
            ok = orig()
            if bot.sniffer is not None:
                bot.sniffer.on_frame = bridge._make_cb(bot.label)
            return ok

        bot.do_login_sequence = patched

    def _run_action(self, action: str, accounts):
        try:
            if action == "proxy":
                # proxy jalan blocking di worker (bukan thread sniffer per bot)
                with contextlib.redirect_stdout(_Tee(_log_file)):
                    run_proxy_sniff("0.0.0.0", 19126,
                                    __import__("bot").HOST,
                                    __import__("bot").PORT,
                                    "logs/proxy_sniff.log")
                return

            for idx, (user, pwd, label) in enumerate(accounts, 1):
                if not self.running.get(action):
                    break
                bot = AvatarBot(user, pwd, label)
                self._patch_login_events(bot)
                with contextlib.redirect_stdout(_Tee(_log_file)), \
                     contextlib.redirect_stderr(_Tee(_log_file)):
                    try:
                        self.bots.append(bot)
                        # run_fish/run_farm melakukan connect+login sendiri;
                        # patched wrapper memasang on_frame tiap login.
                        ok = False
                        if action == "fish":
                            ok = bool(bot.run_fish(cycles=9999))
                        elif action == "farm":
                            ok = bool(bot.run_farm(cycles=9999))
                        elif action == "all":
                            ok = bool(bot.run_farm_and_fish(farm_cycles=9999, fish_cycles=9999))
                        if not ok:
                            self._evt(f"[{label}] connect/login GAGAL")
                    except Exception as e:
                        self._evt(f"[{label}] error: {e}")
                        _log_file.write(traceback.format_exc())
                    finally:
                        bot.close()
        finally:
            self.running[action] = False

    def _make_cb(self, label: str):
        def cb(frame):
            msg = self._interesting(frame.opcode,
                                    KNOWN_OPS.get(frame.opcode, "?"))
            if msg:
                self._evt(f"[{label}] {msg} len={len(frame.payload)}")
        return cb

    def _evt(self, text: str):
        ts = time.strftime("%H:%M:%S")
        with self._lock:
            self.events.append(f"{ts} {text}")
            self.events[:] = self.events[-200:]

    def stop(self):
        for k in list(self.running):
            self.running[k] = False
        # sniff_loop cek conn.connected; tutup socket bot utk hentikan loop
        for b in self.bots:
            try:
                b.close()
            except Exception:
                pass

    def snapshot(self) -> dict:
        with self._lock:
            evs = list(self.events[-12:])
        per_bot = []
        fish = farm = 0
        fin = fout = 0
        unk = set()
        for b in self.bots:
            d = b.info()
            sn = d.get("sniffer") or {}
            per_bot.append(d)
            fish += d.get("fish_count", 0)
            farm += d.get("farm_count", 0)
            fin += sn.get("frames_in", 0)
            fout += sn.get("frames_out", 0)
            unk.update(sn.get("unknown_ops", []))
        return {
            "per_bot": per_bot,
            "fish": fish,
            "farm": farm,
            "frames_in": fin,
            "frames_out": fout,
            "unknown": sorted(unk),
            "events": evs,
            "busy": self.is_busy(),
        }


class AvatarDash(App):
    CSS = """
    Screen { layout: vertical; }
    #stats { height: auto; padding: 0 1; }
    #table { height: 45%; }
    #events { height: 1fr; border: round $accent; padding: 0 1; }
    #buttons { height: auto; padding: 0 1; }
    Button { margin-right: 1; }
    """
    TITLE = f"Avatar Bot Dashboard v{VERSION}"
    SUB_TITLE = "log & sniff → file (tidak tampil di layar)"

    BINDINGS = [
        Binding("f", "toggle('fish')", "Fish"),
        Binding("m", "toggle('farm')", "Farm"),
        Binding("a", "toggle('all')", "All"),
        Binding("p", "proxy", "Proxy"),
        Binding("s", "snapshot", "Snapshot"),
        Binding("x", "export", "Export JSON"),
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
        for col in ("Akun", "UID", "Status", "Fish", "Farm", "In", "Out", "Unk"):
            table.add_column(col)
        self.set_interval(1.0, self.refresh_data)
        self._log_evt(f"[dim]Dashboard siap — {len(self.accounts)} akun dimuat. Log: {_LOG_PATH}[/dim]")

    # ---------- helpers ----------
    def _log_evt(self, text: str):
        self.query_one("#events", RichLog).write(text)

    def refresh_data(self) -> None:
        # ambil bot yang aktif dari bridge (bridge.bots diisi saat run)
        snap = self.bridge.snapshot()
        st = snap["per_bot"]
        table = self.query_one("#table", DataTable)
        table.clear()
        if not st:
            table.add_row("(belum ada sesi — tekan f/m/a untuk mulai)", "-", "-", "-", "-", "-", "-", "-")
        for d in st:
            sn = d.get("sniffer") or {}
            status = "jalan" if snap["busy"] else "selesai"
            status = status if d["connected"] else "putus"
            table.add_row(
                d["label"], str(d["user_id"] or "-"), status,
                str(d["fish_count"]), str(d["farm_count"]),
                str(sn.get("frames_in", 0)), str(sn.get("frames_out", 0)),
                str(len(sn.get("unknown_ops", []))),
            )
        # stats bar
        self.query_one("#stats", Static).update(
            f"Fish: [b]{snap['fish']}[/b]   Farm: [b]{snap['farm']}[/b]   "
            f"Frames in: {snap['frames_in']}   out: {snap['frames_out']}   "
            f"Unk ops: {len(snap['unknown'])}   "
            f"Status: {'[green]BERJALAN[/green]' if snap['busy'] else '[yellow]idle[/yellow]'}"
        )
        # event baru dari bridge → RichLog
        evs = snap["events"]
        seen = getattr(self, "_seen_events", 0)
        if len(evs) > seen:
            for e in evs[seen:]:
                self._log_evt(e.replace("[", "\\[") if "\\[" not in e else e)
            self._seen_events = len(evs)

    # ---------- actions ----------
    def action_toggle(self, action: str) -> None:
        if self.bridge.is_busy():
            self._log_evt("[yellow]Sesi sedang berjalan — tekan Stop dulu.[/yellow]")
            return
        self.bridge.bots.clear()
        self.bridge.start(action, self.accounts)
        self._log_evt(f"[green]▶ Mulai {action} untuk {len(self.accounts)} akun[/green]")

    def action_proxy(self) -> None:
        if self.bridge.is_busy():
            self._log_evt("[yellow]Sesi sedang berjalan — tekan Stop dulu.[/yellow]")
            return
        self.bridge.start("proxy", [])
        self._log_evt("[green]▶ Proxy aktif di :19126 (dump: logs/proxy_sniff.log)[/green]")

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
        path = f"logs/snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(path, "w") as f:
            json.dump(snap, f, indent=2, ensure_ascii=False, default=str)
        self._log_evt(f"[blue]Snapshot → {path}[/blue]")

    def action_export(self) -> None:
        n = 0
        for b in self.bridge.bots:
            if b.sniffer:
                b.sniffer.export_json(
                    f"logs/sniff_session_{b.label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
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
