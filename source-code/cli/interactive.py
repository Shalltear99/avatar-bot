#!/usr/bin/env python3
"""Interactive menu menggunakan Questionary + Rich."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import questionary
from questionary import Style
from rich.console import Console
from rich.table import Table

from bot import (  # from bot.py module
    AvatarBot,
    load_accounts,
    run_multi_account,
    cmd_info,
    KNOWN_OPS,
    HOST,
    PORT,
)

console = Console()

CUSTOM_STYLE = Style([
    ('qmark', 'fg:#00ffff bold'),
    ('question', 'bold'),
    ('answer', 'fg:#00ff00 bold'),
    ('pointer', 'fg:#00ffff bold'),
    ('highlighted', 'fg:#00ffff bold'),
    ('selected', 'fg:#00ff00'),
    ('separator', 'fg:#666'),
    ('instruction', 'fg:#888'),
])


def resolve_accounts(path: str) -> str:
    """Resolve path file akun relatif terhadap source-code/."""
    p = Path(path)
    if not p.is_absolute() and not p.exists():
        p2 = Path(__file__).parent.parent / path
        if p2.exists():
            return str(p2)
    return str(p)

def run_interactive():
    """Loop menu interaktif."""
    accounts_file = "akun.txt"
    current_zone = 4
    
    while True:
        console.clear()
        console.print("[bold cyan]🎣 AVATAR BOT v0.1.0[/bold cyan]")
        console.print(f"[dim]Server: {HOST}:{PORT} | Zone: {current_zone}[/dim]\n")
        
        action = questionary.select(
            "Pilih aksi:",
            choices=[
                "🎣 Start Fishing",
                "🌾 Start Farming", 
                "⚡ Start All (Fish + Farm)",
                "📊 Live Statistics",
                "🔧 Configuration",
                "📜 View Logs",
                "❌ Exit",
            ],
            style=CUSTOM_STYLE,
        ).ask()
        
        if action is None or action.startswith("❌"):
            console.print("[yellow]Keluar...[/yellow]")
            break
            
        elif action.startswith("🎣"):
            accs = load_accounts(resolve_accounts(accounts_file))
            run_multi_account(accs, "fish", zone=current_zone)
            
        elif action.startswith("🌾"):
            accs = load_accounts(resolve_accounts(accounts_file))
            run_multi_account(accs, "farm", zone=current_zone)
            
        elif action.startswith("⚡"):
            accs = load_accounts(resolve_accounts(accounts_file))
            run_multi_account(accs, "all", zone=current_zone)
            
        elif action.startswith("📊"):
            accs = load_accounts(resolve_accounts(accounts_file))
            cmd_info(accs, live_seconds=30)
            
        elif action.startswith("🔧"):
            config_menu()
            
        elif action.startswith("📜"):
            view_logs()

def config_menu():
    """Sub-menu konfigurasi."""
    global current_zone
    while True:
        choice = questionary.select(
            "Konfigurasi:",
            choices=[
                f"🌊 Set Zone (current: {current_zone})",
                "📁 Set Accounts File",
                "⬅️ Back",
            ],
            style=CUSTOM_STYLE,
        ).ask()
        
        if choice is None or choice.startswith("⬅️"):
            break
        elif choice.startswith("🌊"):
            zone_str = questionary.text(
                "Zona mancing (1-39):",
                default=str(current_zone),
                validate=lambda x: x.isdigit() and 1 <= int(x) <= 39,
            ).ask()
            if zone_str:
                current_zone = int(zone_str)
                console.print(f"[green]Zone set to {current_zone}[/green]")
        elif choice.startswith("📁"):
            fname = questionary.text("Accounts file:", default="akun.txt").ask()
            if fname:
                accounts_file = fname
                console.print(f"[green]Accounts file: {accounts_file}[/green]")

def view_logs():
    """Lihat file log terbaru."""
    import glob, os
    log_dir = Path(__file__).parent.parent.parent / "logs"
    logs = sorted(glob.glob(str(log_dir / "*.log")), key=os.path.getmtime, reverse=True)
    if not logs:
        console.print("[yellow]Tidak ada log[/yellow]")
        return
    choice = questionary.select(
        "Pilih log:",
        choices=[os.path.basename(f) for f in logs[:10]] + ["⬅️ Back"],
        style=CUSTOM_STYLE,
    ).ask()
    if choice and not choice.startswith("⬅️"):
        log_path = log_dir / choice
        console.print(f"[dim]--- {choice} ---[/dim]")
        console.print(log_path.read_text(errors='replace')[-2000:])

if __name__ == "__main__":
    run_interactive()
