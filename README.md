# Avatar Bot — Auto Fish & Farm (Avatar Art Gaming v2)

Bot + dashboard TUI untuk game J2ME **Avatar Art Gaming** (`avatar-prod.ayomabar.com:19126`).
Protokol direverse-engineering dari JAR + sniff trafik live.

![version](https://img.shields.io/badge/version-0.0.1-blue)

## Fitur (v0.0.1)

- **Login + handshake live** terverifikasi (XOR rolling cipher per arah)
- **Auto-fish** — pindah map → duduk spot → beli umpan → pancing → hasil
- **Auto-farm** — rawat 40 plot (interleaved op65+op64) → deteksi siap → panen
- **Multi-akun** — sequential semua akun, filter per akun/label
- **Sniffer v2** — statistik frame in/out, history, **deteksi opcode tidak dikenal** (future-update alert), export JSON
- **Dashboard TUI** (Textual + Rich) — tampilan dashboard saja; log & sniff ke file
- **Proxy transparan** — sniff aksi dari HP (J2ME Loader)
- **JAR patcher** — ganti host via constant-pool (aman, class valid)

## Instalasi

```bash
# butuh Python 3.10+ (uv disarankan)
uv venv .venv
uv pip install --python .venv/bin/python textual rich
# atau: pip install textual rich
```

## Menjalankan Dashboard (TUI)

```bash
.venv/bin/python dashboard.py
```

Tombol: `f` fish · `m` farm · `a` all (farm+fish) · `p` proxy · `s` snapshot · `x` export JSON · `q` keluar.
Log & hasil sniff **tidak** ditampilkan di layar — semua masuk `logs/dashboard_*.log`.

## CLI mode (tanpa TUI)

```bash
python3 bot.py login          # tes login
python3 bot.py fish -c 3      # 3 siklus mancing
python3 bot.py farm -c 2      # 2 siklus farm
python3 bot.py all -c 1       # semua akun: farm+fish
python3 bot.py info -t 20     # panel informasi (CLI sederhana)
python3 bot.py proxy          # proxy untuk HP
python3 bot.py patch          # patch JAR → 127.0.0.1
```

## Multi-akun (`akun.txt` — tidak di-commit!)

```
# format baru:
username1:password1
username2:password2:LabelKustom

# format lama:
id : username3
password : password3
```

## Struktur

```
bot.py            core: protokol, PacketFactory, Sniffer v2, multi-akun, CLI
dashboard.py      TUI dashboard (Textual) — v0.0.1
frame_decoder.py  decoder opcode + payload (60+ opcode)
akun.txt          kredensial (gitignored)
logs/             log & export sniff (gitignored)
```

## Roadmap

- [ ] v0.1: auto-sell hasil panen (op 74), scheduler
- [ ] v0.2: panel web (akses dari HP)
- [ ] v0.3: deteksi event khusus (giftcode, quest)

## Disclaimer

Proyek edukasi reverse-engineering. Gunakan dengan tanggung jawab sendiri —
bot melanggar ToS game; risiko banned ditanggung pengguna.
