# Avatar Bot — Auto Fish & Farm (Avatar Art Gaming v2)

Bot + dashboard TUI untuk game J2ME **Avatar Art Gaming** (`avatar-prod.ayomabar.com:19126`).
Protokol direverse-engineering dari JAR + sniff trafik live.

![version](https://img.shields.io/badge/version-0.0.2-blue)

## Struktur Folder

```text
avatar-bot/
├── source-code/     # kode bot + dashboard + akun.txt (credential, tidak di-commit)
├── sniff-tools/     # tool sniffing/analisa — TIDAK di-commit (dev only)
├── logs/            # output log, snapshot, PNG ikan — TIDAK di-commit
├── PRD.md           # product requirements + roadmap
├── README.md
└── .venv/           # virtualenv (tidak di-commit)
```

## Fitur (v0.0.2)

- **Login + handshake live** terverifikasi (XOR rolling cipher per arah)
- **Auto-fish** — pindah map → duduk spot → beli umpan → pancing → hasil
- **Auto-farm** — rawat 40 plot (interleaved op65+op64) → deteksi siap → panen
- **Multi-akun PARALEL** — semua akun login & auto bersamaan (satu thread per akun)
- **Statistik per akun** — jumlah mancing, ikan tertangkap, gold (kolom tabel)
- **Simpan PNG ikan** setiap tangkapan → `logs/fish_catch/`
- **Sniffer v2** — statistik frame in/out, deteksi opcode tak dikenal, export JSON
- **Dashboard TUI** (Textual + Rich) — tampilan dashboard saja; log & sniff ke file

## Instalasi

```bash
# butuh Python 3.10+ (uv disarankan)
uv venv .venv
uv pip install --python .venv/bin/python textual rich
# atau: pip install textual rich
```

## Menjalankan Dashboard (TUI)

**Windows (PowerShell/cmd):**

```powershell
.\.venv\Scripts\python.exe source-code\dashboard.py
```

**Linux / macOS / WSL:**

```bash
.venv/bin/python source-code/dashboard.py
```

> Jalankan dari root folder `avatar-bot/` — log otomatis masuk `logs/`.

Tombol: `f` fish · `m` farm · `a` all (farm+fish, paralel semua akun) · `p` proxy · `s` snapshot · `x` export JSON · `q` keluar.
Log & hasil sniff **tidak** ditampilkan di layar — semua masuk `logs/dashboard_*.log`.

## CLI mode (tanpa TUI)

Jalankan dari root folder (Windows: ganti `python3` → `.\.venv\Scripts\python.exe`):

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

Satu baris = satu akun. Semua akun diproses **paralel** oleh dashboard.

## Keamanan

- `akun.txt` di-gitignore — credential tidak pernah masuk repo/log.
- `sniff-tools/` di-gitignore — tool internal tidak dirilis.
- Dashboard tidak pernah menampilkan payload/hex/credential.

## Roadmap

Lihat [PRD.md](PRD.md) — v0.0.3 dashboard bersih, v0.0.4 katalog ikan, dst.
