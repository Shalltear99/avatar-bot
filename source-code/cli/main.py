#!/usr/bin/env python3
"""Avatar Bot CLI — entrypoint Typer + Questionary interactive."""
import sys
from pathlib import Path

# Pastikan source-code di path
sys.path.insert(0, str(Path(__file__).parent.parent))

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from bot import (  # from bot.py module
    AvatarBot,
    load_accounts,
    run_multi_account,
    cmd_info,
    KNOWN_OPS,
    HOST,
    PORT,
)


def resolve_accounts(path: str) -> str:
    """Resolve path file akun relatif terhadap source-code/."""
    p = Path(path)
    if not p.is_absolute() and not p.exists():
        # coba relatif terhadap source-code/
        p2 = Path(__file__).parent.parent / path
        if p2.exists():
            return str(p2)
    return str(p)


app = typer.Typer(
    name="avatar-bot",
    help="🎣 Avatar Art Gaming v2 — Auto Fish/Farm CLI",
    add_completion=False,
)

console = Console()
VERSION = "0.1.0"

def print_banner():
    console.print(Panel.fit(
        f"[bold cyan]🎣 AVATAR BOT[/bold cyan]\n[dim]v{VERSION}[/dim]",
        border_style="cyan"
    ))

@app.command()
def start(
    action: str = typer.Argument("fish", help="Aksi: fish | farm | all"),
    accounts: str = typer.Option("akun.txt", "--accounts", "-a", help="File akun"),
    zone: int = typer.Option(4, "--zone", "-z", help="Zona mancing (1-39)"),
    cycles: int = typer.Option(1, "--cycles", "-c", help="Jumlah siklus"),
):
    """Jalankan bot (mode command)."""
    print_banner()
    accs = load_accounts(resolve_accounts(accounts))
    console.print(f"[green]Loaded {len(accs)} akun[/green] | action=[yellow]{action}[/yellow] | zone=[yellow]{zone}[/yellow] | cycles=[yellow]{cycles}[/yellow]")
    run_multi_account(accs, action, zone=zone, cycles=cycles)

@app.command()
def info(
    accounts: str = typer.Option("akun.txt", "--accounts", "-a"),
    live: int = typer.Option(20, "--live", "-l"),
):
    """Tampilkan info akun (live stats)."""
    from bot import cmd_info  # from bot.py module
    accs = load_accounts(resolve_accounts(accounts))
    cmd_info(accs, live_seconds=live)

@app.command()
def version():
    """Versi CLI."""
    console.print(f"avatar-bot v{VERSION}")

@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """Tanpa subcommand → mode interaktif."""
    if ctx.invoked_subcommand is None:
        print_banner()
        # Defer import agar Questionary optional
        from cli.interactive import run_interactive
        run_interactive()

if __name__ == "__main__":
    app()
