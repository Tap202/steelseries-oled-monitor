# SteelSeries Arctis Nova / GameDAC OLED Hardware Monitor

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D6.svg)](https://www.microsoft.com/windows/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A lightweight, zero-dependency background utility for Windows that streams real-time PC hardware metrics directly to the OLED display on **SteelSeries Arctis Nova Pro / Elite** base stations and **GameDAC** controllers via the official SteelSeries GameSense SDK.

```
┌──────────────────────────────────────┐
│  C78° G52°     ╭──────╮              │  <- Line 1: CPU & GPU Temperatures
│  15.6/32G      │ VOL  │              │  <- Line 2: RAM Usage (Used / Total)
│                ╰──────╯              │     (Fits next to native volume dial)
└──────────────────────────────────────┘
```

---

## ✨ Features

- **Real-Time CPU & GPU Temperatures**: Supports modern Intel and AMD hardware (tested on 12th Gen Intel Core and AMD Radeon RX 6000/7000 series) via local [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) integration.
- **Tailored 9-Character Nova Pro HUD**: Text is formatted compactly (`C85° G53°` and `15.6/32G`) to sit cleanly to the left of the hardware `VOL` dial without being obscured or clipped.
- **Anti-Caching Volume Auto-Recovery**: Uses monotonically incrementing frame sequence counters and `value_optional: true` so adjusting volume or navigating menus automatically snaps back to PC metrics within 1–2 seconds.
- **Zero External Python Dependencies**: Built entirely using Python's standard library and native Windows `ctypes` (`GlobalMemoryStatusEx`, `GetSystemTimes`, `GetLastInputInfo`). No `pip install` required.
- **🛡️ 3-Layer OLED Burn-in Protection**:
  1. **Horizontal Pixel Shifting (Jitter)**: Automatically shifts text coordinates every 60 seconds to rest static phosphor/OLED subpixels.
  2. **Periodic Row Swapping**: Exchanges Row 1 and Row 2 every 3 minutes so top and bottom screen phosphors wear evenly.
  3. **Inactivity Sleep (True Black)**: Detects when you step away from your PC using Windows idle timers. After 5 minutes of inactivity, the screen blanks to 100% true black (powering off all OLED emitters). Wakes up instantly on mouse or keyboard movement.
- **Resilient Background Execution**: Runs windowless via `pythonw.exe`, automatically detects dynamic GameSense ports, handles SteelSeries GG restarts cleanly, and restores default DAC audio screens upon exit.

---

## 📋 Requirements

1. **Windows 10 / 11**
2. **Python 3.10+** (ensure Python is added to your Windows PATH)
3. **[SteelSeries GG](https://steelseries.com/gg)** (with Engine installed and running)
4. **[LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases)** (free, portable hardware sensor tool for live CPU/GPU temps)

---

## 🚀 Quick Start

1. Clone or download this repository:
   ```bash
   git clone https://github.com/Tap202/steelseries-oled-monitor.git
   cd steelseries-oled-monitor
   ```
2. Ensure **SteelSeries GG** is running.
3. Launch the monitor:
   - **Interactive Console**: Double-click `start.bat`
   - **Silent Background**: Double-click `start_silent.vbs`
4. Check your controller's OLED screen — your live metrics will appear immediately!

---

## 🎧 Arctis Nova Pro / GameDAC Base Station Setup

To ensure GameSense text displays properly on the Arctis Nova Pro Wireless Base Station / GameDAC Gen 2:

1. **Set Home Screen to "Preset"**:
   - Press and hold the main volume wheel on the base station until you enter **Settings**.
   - Navigate to **Display** ➔ **Home Screen** (or **Home Screen Options**).
   - Scroll to **Preset** and **press the wheel in** to confirm the selection.
   - Tap the **`○` (Back)** circle button to exit to the home screen.
   *(Note: `Stereo` mode displays audio sample rate and L/R sound meters; `Meters` displays 4 stream mix bars. `Preset` activates the 2 custom text lines where this monitor renders).*
2. **Volume Adjustments & Menu Navigation**:
   - Turning the dial temporarily displays hardware volume.
   - Entering settings temporarily pauses app display.
   - Once you let go or exit back to the home screen, the monitor **automatically snaps back within 1–2 seconds**.

---

## 🌡️ Enabling Live Temperatures (Intel & AMD)

Windows restricts direct user-mode access to ring-0 hardware sensor registers. To stream exact junction/package temperatures:

1. Download the portable zip of **[LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases)** and extract it (e.g. to `C:\Program Files\LibreHardwareMonitor\`).
2. Run `LibreHardwareMonitor.exe`.
3. In the top menu, click **Options** and enable:
   - ✅ **Remote Web Server** → click **Run** (serves sensor data locally on `http://localhost:8085/data.json`).
   - ✅ **Start Minimized**
   - ✅ **Minimize To Tray**
   - ✅ **Run On Windows Startup** *(creates an elevated Windows Task Scheduler task that bypasses UAC prompts on login)*.

*Note: If LibreHardwareMonitor is not open, the app gracefully falls back to displaying live CPU utilization percentage (`CPU: %`) and RAM usage.*

---

## ⚙️ Configuration (`config.json`)

All features can be customized in `config.json`:

```json
{
    "refresh_interval_sec": 1.5,
    "lhm_url": "http://localhost:8085/data.json",
    "lhm_exe_path": "C:\\Program Files\\LibreHardwareMonitor\\LibreHardwareMonitor.exe",
    "autostart_lhm": false,
    "ram_show_decimal": true,
    "burn_in_protection": {
        "enabled": true,
        "pixel_shift_enabled": true,
        "pixel_shift_interval_sec": 60,
        "swap_lines_enabled": true,
        "swap_lines_interval_sec": 180,
        "idle_sleep_enabled": true,
        "idle_sleep_minutes": 5
    }
}
```

| Setting | Default | Description |
|---|---|---|
| `refresh_interval_sec` | `1.5` | OLED screen refresh rate in seconds |
| `ram_show_decimal` | `true` | Show `15.6/32G` (`true`) or integer `16/32G` (`false`) |
| `pixel_shift_interval_sec` | `60` | Frequency of subpixel horizontal shifting (burn-in prevention) |
| `swap_lines_interval_sec` | `180` | Frequency of swapping Line 1 and Line 2 |
| `idle_sleep_minutes` | `5` | Minutes of user inactivity before screen blanks to black |

---

## 🔄 Auto-Start with Windows

To have the monitor launch automatically and silently on system boot without any command prompt popups:

1. Press `Win + R`, type `shell:startup`, and press Enter.
2. Create a shortcut in that folder pointing to:
   - **Target:** `C:\Python315\pythonw.exe "C:\Path\To\steelseries-oled-monitor\app.py"`
   - **Start in:** `C:\Path\To\steelseries-oled-monitor`
3. The app will launch via `pythonw.exe` completely in the background on every login.

---

## 🛠️ Architecture

1. **Port Discovery**: On startup, the client reads `C:\ProgramData\SteelSeries\SteelSeries Engine 3\coreProps.json` to find the local HTTP port dynamically assigned by SteelSeries GG.
2. **Metadata Registration**: Registers `PC_SYS_MONITOR` with SteelSeries GameSense (`POST /game_metadata`). The app appears under **GG → Engine → Apps**.
3. **Screen Handler Binding**: Binds an OLED handler for `device-type: "screened"`, registering a 2-line text frame with dynamic keys `line1` and `line2`.
4. **Heartbeat & Telemetry**: Streams data every 1.5s via `POST /game_event` and sends keep-alive pings (`POST /game_heartbeat`) every 10 seconds.
5. **Clean Release**: Listens for termination signals (`SIGINT`, `SIGTERM`) and calls `POST /stop_game` to return the DAC OLED to its default audio control interface.

---

## 📄 License

Licensed under the [MIT License](LICENSE).
