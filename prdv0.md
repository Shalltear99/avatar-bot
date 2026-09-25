PRD — Avatar Bot CLI



Versi: V1.0

Platform: Windows / Linux

Interface: CLI

Bahasa: Python 3.12+

Status: Development



1\. Product Overview



Avatar Bot CLI adalah aplikasi automation berbasis Python yang dikendalikan melalui terminal.



Aplikasi memiliki dua bagian utama:



┌───────────────────────────┐

│       CLI Interface       │

│ Typer + Questionary+Rich  │

└─────────────┬─────────────┘

&#x20;             │

&#x20;             ▼

┌───────────────────────────┐

│       Bot Engine           │

│ Python                     │

├───────────────────────────┤

│ Scheduler                 │

│ State Manager             │

│ Task Manager              │

│ Bot Modules               │

└───────────────────────────┘



CLI bertanggung jawab terhadap interaksi dan visualisasi, sedangkan Bot Engine bertanggung jawab terhadap logic automation.



2\. Tujuan Produk

Primary Goal



Membuat bot yang:



mudah dijalankan

mudah dikonfigurasi

mudah dimonitor

memiliki CLI yang modern

memiliki sistem module

memiliki logging yang jelas

dapat di-pause/resume

dapat menangani error

mudah dikembangkan

Non-Goals V1



V1 tidak mencakup:



Web App

Android APK

cloud server

multi-user

authentication

PostgreSQL

Redis

remote control

3\. Target User



Pengguna yang menjalankan bot dari komputer dan membutuhkan:



automation

monitoring

konfigurasi

statistik

log

kontrol bot melalui terminal

4\. Tech Stack

Core

Python 3.12+

CLI

Typer

Questionary

Rich

Configuration

Pydantic Settings

Networking

httpx

websockets



Dipakai jika bot membutuhkan komunikasi HTTP/WebSocket.



Testing

pytest

Package Management

uv

5\. Struktur Project

avatar-bot/

│

├── src/

│   └── avatar\_bot/

│       │

│       ├── main.py

│       │

│       ├── cli/

│       │   ├── commands.py

│       │   └── menu.py

│       │

│       ├── ui/

│       │   ├── console.py

│       │   ├── banner.py

│       │   ├── dashboard.py

│       │   ├── tables.py

│       │   ├── panels.py

│       │   └── progress.py

│       │

│       ├── bot/

│       │   ├── engine.py

│       │   ├── state.py

│       │   ├── scheduler.py

│       │   └── events.py

│       │

│       ├── modules/

│       │   ├── fishing.py

│       │   ├── farming.py

│       │   └── inventory.py

│       │

│       ├── config/

│       │   ├── settings.py

│       │   └── defaults.py

│       │

│       └── utils/

│           ├── helpers.py

│           └── logger.py

│

├── tests/

│

├── logs/

│

├── .env

├── pyproject.toml

├── README.md

└── LICENSE

6\. CLI Design



CLI memiliki dua mode.



Mode 1 — Interactive

python -m avatar\_bot



Menampilkan:



╭─────────────────────────────────────╮

│          🎣 AVATAR BOT              │

│              v0.1.0                 │

╰─────────────────────────────────────╯



? Select action:



❯ 🎣 Start Fishing

&#x20; 🌾 Start Farming

&#x20; 📊 Statistics

&#x20; 📜 Logs

&#x20; ⚙️ Configuration

&#x20; 🔧 Tools

&#x20; ❌ Exit



Menggunakan Questionary.



Mode 2 — Command



Contoh:



python -m avatar\_bot start

python -m avatar\_bot stop

python -m avatar\_bot status

python -m avatar\_bot config



Menggunakan Typer.



7\. Bot Lifecycle



Bot memiliki state:



STOPPED

&#x20;  │

&#x20;  │ start

&#x20;  ▼

STARTING

&#x20;  │

&#x20;  ▼

RUNNING

&#x20;  │

&#x20;  ├──── pause ────► PAUSED

&#x20;  │                    │

&#x20;  │                  resume

&#x20;  │                    │

&#x20;  │                    ▼

&#x20;  │                 RUNNING

&#x20;  │

&#x20;  └──── stop ─────► STOPPED



State tambahan:



ERROR



Jika terjadi error fatal:



RUNNING

&#x20;  ↓

ERROR

&#x20;  ↓

Recovery / STOPPED

8\. Bot Engine



engine.py merupakan pusat kontrol.



Interface minimal:



class BotEngine:



&#x20;   async def start():

&#x20;       ...



&#x20;   async def stop():

&#x20;       ...



&#x20;   async def pause():

&#x20;       ...



&#x20;   async def resume():

&#x20;       ...



&#x20;   def get\_status():

&#x20;       ...



Engine tidak boleh bergantung pada Rich.



Contoh:



Bot Engine

&#x20;    │

&#x20;    ├── tidak tahu Rich

&#x20;    ├── tidak tahu Questionary

&#x20;    └── tidak tahu Typer



Ini penting agar core bot dapat digunakan kembali nantinya.



9\. Bot Modules



Setiap automation dibuat sebagai module terpisah.



Contoh:



modules/

├── fishing.py

├── farming.py

└── inventory.py



Setiap module memiliki lifecycle sendiri.



class FishingModule:



&#x20;   async def start():

&#x20;       ...



&#x20;   async def stop():

&#x20;       ...



&#x20;   async def run():

&#x20;       ...

Prinsip



Satu module = satu tanggung jawab.



Jangan membuat:



bot.py



berisi ribuan baris logic fishing + farming + inventory.



10\. Scheduler



Scheduler bertanggung jawab menjalankan task berdasarkan kondisi/waktu.



Contoh:



Fishing

&#x20; ↓

Cooldown

&#x20; ↓

Fishing

&#x20; ↓

Inventory Full

&#x20; ↓

Sell

&#x20; ↓

Fishing



Nantinya scheduler dapat mendukung:



interval

delay

cooldown

retry

timeout

priority

11\. Rich Dashboard



Rich digunakan untuk membuat dashboard terminal.



Contoh:



╭────────────── AVATAR BOT ──────────────╮

│                                        │

│ Status       ● RUNNING                 │

│ Module       🎣 Fishing                │

│ Runtime      02:31:22                  │

│                                        │

├────────────────────────────────────────┤

│ Statistics                             │

│                                        │

│ Successful       127                   │

│ Failed           3                     │

│ Success Rate     97.7%                │

│                                        │

├──────────────────── LOG ───────────────┤

│ 14:22:01  Fishing started              │

│ 14:22:10  Target detected              │

│ 14:22:12  Action successful             │

╰────────────────────────────────────────╯



Memanfaatkan:



Panel

Table

Layout

Live

Progress

Console

RichHandler

12\. Realtime Dashboard



Dashboard harus bisa diperbarui tanpa restart CLI.



Contoh:



Runtime       02:31:22

&#x20;             ↓

Runtime       02:31:23

&#x20;             ↓

Runtime       02:31:24



Gunakan:



rich.live.Live



untuk UI realtime.



13\. Logging



Level:



DEBUG

INFO

SUCCESS

WARNING

ERROR

CRITICAL



Contoh:



14:22:01 INFO     Bot starting

14:22:03 INFO     Connecting...

14:22:05 SUCCESS  Connected

14:22:07 INFO     Fishing started

14:22:12 SUCCESS  Catch detected

14:22:15 WARNING  Timeout

14:22:16 INFO     Retrying



Log juga disimpan ke:



logs/

├── bot.log

└── error.log

14\. Configuration



Konfigurasi menggunakan .env + Pydantic Settings.



Contoh:



BOT\_NAME=AvatarBot

LOG\_LEVEL=INFO

DEFAULT\_DELAY=2

MAX\_RETRY=3



Kemudian konfigurasi module:



Fishing

├── delay

├── timeout

├── retry

└── target



Configuration harus bisa diakses melalui CLI.



python -m avatar\_bot config

15\. Statistics



V1 minimal menyediakan:



Runtime

Tasks executed

Successful tasks

Failed tasks

Retries

Errors



Contoh:



╭──────────── Statistics ────────────╮

│ Runtime          04:21:32          │

│ Tasks            1,241             │

│ Success          1,203             │

│ Failed           38                │

│ Retries          61                │

│ Success Rate     96.9%             │

╰────────────────────────────────────╯

16\. Error Handling



Bot tidak boleh langsung crash karena error module.



Contoh:



Module

&#x20;  ↓

Exception

&#x20;  ↓

Logger

&#x20;  ↓

Retry

&#x20;  │

&#x20;  ├── berhasil → Continue

&#x20;  │

&#x20;  └── gagal → Recovery



Configuration:



MAX\_RETRY=3

RETRY\_DELAY=5

17\. Tools Menu



CLI menyediakan menu:



🔧 Tools



❯ Test Connection

&#x20; Test Module

&#x20; Clear Logs

&#x20; Export Logs

&#x20; System Information



Ini berguna untuk debugging.



18\. Command Specification

Command	Fungsi

run	Jalankan interactive mode

start	Start bot

stop	Stop bot

pause	Pause bot

resume	Resume bot

restart	Restart bot

status	Status bot

stats	Statistik

logs	Lihat log

config	Configuration

version	Version

doctor	System diagnostic



Contoh:



python -m avatar\_bot doctor



Output:



System Check



✓ Python

✓ Configuration

✓ Dependencies

✓ Bot Module

✓ Connection



System ready.

19\. Requirements V1

Must Have

&#x20;Python project structure

&#x20;Typer CLI

&#x20;Questionary menu

&#x20;Rich UI

&#x20;Bot Engine

&#x20;Start/Stop

&#x20;Pause/Resume

&#x20;State management

&#x20;Module architecture

&#x20;Logging

&#x20;Configuration

&#x20;Statistics

&#x20;Error handling

&#x20;Realtime dashboard

&#x20;Tests dasar

Should Have

&#x20;Scheduler

&#x20;Retry system

&#x20;Diagnostic command

&#x20;Log export

&#x20;System information

Could Have

&#x20;ASCII art

&#x20;Sound notification

&#x20;Multiple profiles

&#x20;Theme configuration

Tidak untuk V1

&#x20;Web App

&#x20;Android

&#x20;Cloud

&#x20;Multi-user

&#x20;Remote access

&#x20;PostgreSQL

&#x20;Redis

20\. Roadmap Implementasi

Milestone 1 — CLI Foundation

Python

&#x20; ↓

uv

&#x20; ↓

Typer

&#x20; ↓

Questionary

&#x20; ↓

Rich



Hasil:



python -m avatar\_bot



sudah menampilkan menu.



Milestone 2 — Bot Engine



Implementasi:



Engine

State

Events

Scheduler



Hasil:



START

STOP

PAUSE

RESUME



sudah berfungsi.



Milestone 3 — Rich Dashboard



Tambahkan:



Panel

Table

Layout

Live

Progress

Logging



Hasil:



CLI mulai terlihat seperti aplikasi, bukan sekadar terminal command.



Milestone 4 — Bot Modules

Fishing

Farming

Inventory



Setiap module independen.



Milestone 5 — Configuration

.env

Pydantic Settings

CLI configuration

Milestone 6 — Reliability



Tambahkan:



Retry

Timeout

Recovery

Error handling

Logging

Testing

21\. Definition of Done V1



V1 dianggap selesai apabila:



CLI bisa dijalankan dengan satu command.

User dapat memilih module melalui menu.

Bot dapat Start/Pause/Resume/Stop.

Status bot terlihat realtime.

Log muncul di terminal.

Log tersimpan ke file.

Statistik dasar tersedia.

Configuration dapat diubah tanpa mengedit source code.

Error tidak langsung menghentikan seluruh aplikasi.

Module bot dapat ditambah tanpa mengubah engine.py.

Core bot tidak bergantung pada Rich/Questionary.

Prinsip arsitektur paling penting

&#x20;            CLI

&#x20;             │

&#x20;      ┌──────┴──────┐

&#x20;      │             │

&#x20;   Typer       Questionary

&#x20;      │             │

&#x20;      └──────┬──────┘

&#x20;             │

&#x20;           Rich

&#x20;             │

&#x20;             ▼

&#x20;       ┌─────────────┐

&#x20;       │ Bot Engine  │

&#x20;       └──────┬──────┘

&#x20;              │

&#x20;      ┌───────┼────────┐

&#x20;      ▼       ▼        ▼

&#x20;   Fishing  Farming  Inventory



Rich hanya untuk UI. Bot Engine tetap murni Python. Ini akan membuat V1 lebih mudah dibangun sekarang sekaligus menjaga jalan untuk menambahkan Web App di masa depan tanpa perlu membongkar logic bot.

