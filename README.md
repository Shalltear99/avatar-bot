# Avatar Bot — Auto Fish & Farm (Avatar Art Gaming v2)

Bot CLI untuk game J2ME **Avatar Art Gaming** (`avatar-prod.ayomabar.com:19126`).
Protokol direverse-engineering dari JAR + sniff trafik live.

![version](https://img.shields.io/badge/version-0.1.0-blue)

## Struktur Folder

```text
avatar-bot/
├── source-code/        # kode bot + CLI + akun.txt (credential, tidak di-commit)
│   ├── bot.py          # core engine (login, fish, farm)
│   ├── frame_decoder.py# dekoder payload
│   ├── cli/            # CLI Typer + Questionary
│   │   ├── main.py     # entrypoint command mode
│   │   └── interactive.py  # menu interaktif
│   └── protocol/       # frame, opcodes, XOR cipher
├── sniff-tools/        # tool sniffing/analisa — TIDAK di-commit (dev only)
├── logs/               # output log, snapshot, PNG ikan — TIDAK di-commit
├── prdv0.md            # PRD (product requirements)
├── README.md
└── .venv/              # virtualenv (tidak di-commit)
```

## Fitur (v0.1.0)

- **Login + handshake live** terverifikasi (XOR rolling cipher per arah)
- **Auto-fish** — pindah map → duduk spot → beli umpan → pancing → hasil
- **Auto-farm** — rawat 40 plot (interleaved op65+op64) → deteksi siap → panen
- **Multi-akun** — semua akun diproses berurutan (aman dari rate-limit)
- **CLI modern** — Typer (command mode) + Questionary (interactive mode) + Rich
- **Pilih zona mancing** — zona 1–39 via flag `--zone` atau menu config

## Instalasi

```bash
# butuh Python 3.10+ (uv disarankan)
uv venv .venv
uv pip install --python .venv/bin/python typer questionary rich
# atau: pip install typer questionary rich
```

## Menjalankan

### Mode Interaktif (menu)

**Windows (PowerShell/cmd):**

```powershell
.\\.venv\\Scripts\\python.exe source-code\cli\main.py
```

**Linux / macOS / WSL:**

```bash
.venv/bin/python source-code/cli/main.py
```

Menu:

```text
🎣 Start Fishing
🌾 Start Farming
⚡ Start All (Fish + Farm)
📊 Live Statistics
🔧 Configuration
📜 View Logs
❌ Exit
```

### Mode Command (langsung)

Jalankan dari root folder (Windows: ganti `python3` → `.\\.venv\\Scripts\\python.exe`):

```bash
python3 source-code/cli/main.py start fish --cycles 3 --zone 4
python3 source-code/cli/main.py start farm --cycles 2
python3 source-code/cli/main.py start all --cycles 1 --zone 16
python3 source-code/cli/main.py info
python3 source-code/cli/main.py version
```

Flag:

| Flag | Fungsi |
|------|--------|
| `--cycles`/`-c` | Jumlah siklus (default 1) |
| `--zone`/`-z` | Zona mancing 1–39 (default 4) |
| `--accounts`/`-a` | File akun (default `akun.txt`) |

### Mode lama (bot.py langsung)

```bash
python3 source-code/bot.py login          # tes login semua akun
python3 source-code/bot.py fish -c 3      # 3 siklus mancing
python3 source-code/bot.py farm -c 2      # 2 siklus farm
python3 source-code/bot.py all -c 1       # semua akun: farm+fish
python3 source-code/bot.py info -t 20     # panel informasi (CLI sederhana)
python3 source-code/bot.py proxy          # proxy untuk HP
```

## Multi-akun (`source-code/akun.txt` — tidak di-commit!)

Format:

```text
username:password:label
```

Satu baris = satu akun.

## Keamanan

- `akun.txt` di-gitignore — credential tidak pernah masuk repo/log.
- `sniff-tools/` di-gitignore — tool internal tidak dirilis.
- Log/log payload hex hanya untuk debugging — `logs/`.

## Roadmap

Lihat [prdv0.md](prdv0.md) — PRD V1.0 (engine modular, scheduler, state management).
