# PRD — Avatar Bot
Dokumen kebutuhan produk untuk bot Avatar Art Gaming v2 (J2ME).
Satu rilis = satu tema. Tidak mencampur banyak fitur besar dalam satu versi.

Status: v0.0.2 sudah rilis (multi-akun paralel + dashboard dasar).
Restrukturisasi folder sudah dilakukan: source di `source-code/`, tool sniffing di `sniff-tools/` (tidak di-commit), README mencakup cara run Windows & Linux.

---

## Aturan Umum
1. Satu versi = satu tema utama, maksimal 1 fitur besar + perbaikan kecil.
2. Fitur yang menyentuh server hanya boleh dibangun setelah opcode & payload terverifikasi lewat sniffer.
3. Dashboard tidak pernah menampilkan: packet mentah, hex dump, credential, stack trace.
4. Semua nilai yang belum terverifikasi ditampilkan sebagai `?` atau `belum terverifikasi`, bukan angka tebak-tebakan.
5. Credential (username/password) hanya hidup di `source-code/akun.txt` + memori proses. Tidak pernah masuk repo, log, atau screenshot.
6. Setiap versi wajib lulus smoke test live (minimal 1 akun, 5 menit) sebelum di-push.

## Struktur Repo (sejak restrukturisasi)
```text
avatar-bot/            # root repo & working dir
├── source-code/       # bot.py, dashboard.py, frame_decoder.py, akun.txt (ignored)
├── sniff-tools/       # tool sniffing internal — SELURUH folder ignored
├── logs/              # output — ignored
├── PRD.md, README.md, .gitignore
```
- Jalankan selalu dari root `avatar-bot/` (Windows: `.\.venv\Scripts\python.exe source-code\dashboard.py`).
- Path log/akun dihitung dari `PROJECT_ROOT` otomatis — relatif terhadap lokasi file source.

---

## Roadmap

| Versi | Tema                    | Status      |
|-------|-------------------------|-------------|
| 0.0.1 | Bot core + dashboard    | ✅ rilis    |
| 0.0.2 | Multi-akun paralel      | ✅ rilis    |
| 0.0.3 | Dashboard bersih        | 📝 PRD siap |
| 0.0.4 | Katalog ikan            | 📝 PRD siap |
| 0.0.5 | Statistik memancing     | 📝 PRD siap |
| 0.0.6 | Recovery koneksi        | 📝 PRD siap |
| 0.0.7 | Auto-jual ikan          | 📝 PRD siap |
| 0.0.8 | Export data             | 📝 PRD siap |

---

## v0.0.3 — Dashboard Bersih
**Tema:** dashboard hanya menampilkan status, bukan log.

### Masalah
- Panel event (`RichLog`) masih menampilkan baris teknis per frame/op.
- Beberapa nilai (gold, stat) belum terverifikasi tapi sudah tampil sebagai angka.

### Tujuan
Layar dashboard 100% ringkasan status. Semua detail teknis hanya di file log.

### Perubahan UI
Tampil (diizinkan):
- Baris ringkas per akun: label, UID, status (idle/login/jalan/error), jumlah casting, jumlah ikan.
- Bar total: total akun, total casting, total ikan.
- Kartu alert (maks 5 baris terakhir): LOGIN_OK, LOGIN_GAGAL, PUTUS, IKAN_DAPAT, SEMUA_SELESAI.
- Ikon: ✅ ⚠️ ❌ 🎣 🐟.

Tidak tampil (dilarang):
- Payload, opcode, hex, frame counter, unknown-op warning, stack trace.
- Username/password/UID sensitif lain (UID boleh, credential tidak).

### Aturan Data
- Field gold/coin: tampilkan `Gold: ?` sampai terverifikasi lewat analisis payload op -33.
- Field stat op -22: tampilkan `Stat: ?` sampai terverifikasi.

### Kriteria Selesai
- [ ] Jalankan 3 akun paralel 5 menit: layar tidak memunculkan satu pun payload/hex.
- [ ] Semua event teknis terverifikasi masuk ke `logs/dashboard_*.log`.
- [ ] Kolom Gold & Stat menampilkan `?` (bukan angka belum diverifikasi).
- [ ] Alert card muncul untuk: login sukses, login gagal, ikan dapat, koneksi putus.
- [ ] Smoke test 3 akun × 5 menit tanpa crash.

---

## v0.0.4 — Katalog Ikan
**Tema:** dashboard bisa menampilkan NAMA ikan, bukan hanya "dapat ikan".

### Masalah
- op 91 FISH_RESULT membawa ID ikan, tapi bot belum punya pemetaan ID → nama.

### Tujuan
Setiap tangkapan menampilkan nama ikan di dashboard dan di file `logs/fish_catch/`.

### Pekerjaan
1. Ekstrak resource JAR v2 (gambar/text database ikan).
2. Identifikasi struktur data katalog (id, nama, mungkin rarity/gold).
3. Simpan sebagai `fish_catalog.json` di repo.
4. Saat op 91 diterima: parse ID → lookup nama → simpan ke state akun.

### Aturan
- Jika ID tidak ada di katalog: tampilkan `Ikan #<id>` (bukan nama salah).
- Nama ikan tidak pernah di-hardcode di dashboard.py; selalu baca dari `fish_catalog.json`.

### Kriteria Selesai
- [ ] `fish_catalog.json` berisi minimal 10 ikan terverifikasi.
- [ ] Smoke test: 10 tangkapan, minimal 8 tampil dengan nama benar.
- [ ] Ukuran file katalog < 100 KB.
- [ ] ID tak dikenal tetap tidak membuat bot crash.

---

## v0.0.5 — Statistik Memancing
**Tema:** metrik mancing yang bisa dipercaya.

### Masalah
- Angka "Mancing" sekarang hanya menghitung op 82 CAST_ROD dikirim, belum membedakan selesai/kosong/dapat.

### Tujuan
Setiap akun punya 5 angka yang benar: casting dikirim, mancing selesai, dapat ikan, kosong, success rate.

### Definisi Event
- `CAST_SENT`    : op 82 dikirim oleh bot.
- `CAST_DONE`    : respons server cast diterima (opcode ditentukan lewat sniffer di versi ini).
- `FISH_GOT`     : op 91 diterima.
- `FISH_EMPTY`   : CAST_DONE tanpa op 91 menyusul dalam window waktu (default 45 detik, bisa diatur).

### Metrik Baru per Akun
- casting dikirim
- mancing selesai
- dapat ikan
- kosong
- success rate (%) = dapat ÷ selesai × 100
- durasi rata-rata per cast (detik)

### Kriteria Selesai
- [ ] 5 metrik tampil per akun + 1 baris total.
- [ ] Success rate dihitung benar (manual cross-check 10 cast).
- [ ] Nilai `FISH_EMPTY` bisa diatur via config/env.
- [ ] Definisi opcode CAST_DONE didokumentasikan di README (hasil sniffer).

---

## v0.0.6 — Recovery Koneksi
**Tema:** bot tahan banting saat jaringan/server gangguan.

### Masalah
- Socket timeout/server drop = worker mati, harus start manual lagi.

### Tujuan
Worker bisa reconnect sendiri dengan backoff, tanpa kehilangan statistik sesi.

### Perilaku
1. Deteksi: socket timeout, EOF,Exception jaringan apa pun.
2. Tutup socket lama dengan rapi.
3. Tunggu backoff: 5s → 10s → 20s → 40s → maks 120s (reset setelah login sukses).
4. Login ulang, lanjut aksi sebelumnya (fish/farm/all).
5. Statistik akun (casting, ikan, dll) TIDAK di-reset saat reconnect.
6. Setelah 5 gagal berurutan: worker masuk status `error`, stop, alert di dashboard.

### Kriteria Selesai
- [ ] Simulasi drop (kill socket dari luar) → reconnect otomatis < 60 detik.
- [ ] Statistik tidak hilang setelah reconnect.
- [ ] Setelah 5 gagal: status error + alert muncul, worker berhenti bersih.
- [ ] Tidak ada koneksi zombie (verifikasi via netstat / counters `In`/`Out`).

---

## v0.0.7 — Auto-Jual Ikan
**Tema:** otomasi ekonomi pertama (fitur dengan dampak uang).

### Prasyarat
- v0.0.4 (katalog ikan) sudah rilis.
- op 74 (JUAL) + payload-nya sudah terverifikasi lewat sniffer.
- Field inventori (jumlah ikan per ID) sudah terverifikasi.

### Perilaku
1. Setiap N tangkapan (default 10), buka daftar ikan di inventori.
2. Jual ikan sesuai aturan: bisa `semua`, bisa `hanya ID tertentu`, bisa `kecuali ID favorit`.
3. Jeda acak 2–5 detik antar aksi jual.
4. Batas hard per sesi: maksimal 50 aksi jual (configurable).
5. Setiap aksi jual dicatat ke log file (ID, jumlah, waktu).

### Larangan
- Tidak jual ikan yang ada di daftar `keep_id` (config).
- Tidak jual jika respons op 74 sebelumnya gagal/error — stop dan alert.
- Tidak pernah jual saat user menekan tombol Stop (flush pending = dibatalkan).

### Kriteria Selesai
- [ ] Live test 1 akun: jual 3 batch @ 10 ikan, tidak ada ikan `keep_id` terjual.
- [ ] Tidak ada request jual ganda untuk batch yang sama.
- [ ] Counter penjualan muncul di dashboard (kolom baru: Jual).
- [ ] Smoke test 30 menit tanpa ban/captcha/error dari server.

---

## v0.0.8 — Export Data
**Tema:** data sesi bisa dianalisis di luar TUI.

### Deliverable
1. `snapshot.json` — seluruh state dashboard saat tombol Export ditekan.
2. `session_stats.csv` — 1 baris per akun:
   `account,uid,status,castings,catches,empty,sell_count,avg_cast_sec,started_at,ended_at`
3. `fish_log.csv` — 1 baris per tangkapan:
   `timestamp,account,fish_id,fish_name,image_path`

### Aturan
- Tidak ada credential di file export.
- Username akun diganti label (`akun1`, `akun2`, …) di CSV — kecuali user override via env.
- File ditulis ke `logs/export/<timestamp>/`.

### Kriteria Selesai
- [ ] Export 3 akun × 20 tangkapan: CSV valid, bisa dibuka LibreOffice/Excel.
- [ ] Tidak ada password/token di file export (grep manual).
- [ ] Snapshot JSON bisa di-load ulang tanpa error.

---

## di luar roadmap (penelitian, tidak dijadwalkan)
- Teks header op -33: verifikasi struktur coin/gold.
- Teks header op -22: verifikasi struktur stat.
- Deteksi captcha/ban otomatis.
- Proxy rotator.
- Panel web dari HP.
