# Hardware, Power & Memory Crash Sentry (Windows 10 Laptop Edition)

A high-frequency, zero-overhead telemetry logger and floating desktop widget ported specifically for **Windows 10 Laptops and Desktops** to diagnose sudden power-offs, battery drops, thermal shutdowns, and memory exhaustion crashes.

---

## ⚡ How It Works on Windows 10

1. **Abrupt Shutdown Protection (`FlushFileBuffers` & `fsync`)**:
   - When a laptop battery abruptly collapses or the DC barrel jack/USB-C charger slips out under high load, Windows powers down with zero warning. File buffers held in RAM are lost.
   - This sentry samples hardware telemetry every 1.0s, packs it into an aligned 64-byte binary record, and immediately executes `ctypes.windll.kernel32.FlushFileBuffers()` on physical storage.
   - Telemetry right up to the final second before power collapse is preserved on disk!

2. **Laptop Battery & Power Tracking**:
   - Queries `kernel32.GetSystemPowerStatus` directly via Win32 API.
   - Tracks AC Line status (Plugged In vs Battery), Battery percentage (0-100%), Charging status, and estimated remaining minutes.
   - Records whether a crash occurred while running on AC power or after a sudden battery voltage sag.

3. **Ultra-Low Overhead & Zero Mandatory Dependencies**:
   - Built 100% on native Windows APIs via `ctypes` (`kernel32.dll`, `psapi.dll`).
   - Uses `GlobalMemoryStatusEx` for physical RAM and commit limit tracking.
   - Uses `GetSystemTimes` for non-blocking CPU load calculation.
   - Optional NVML (`nvml.dll`) support for laptops with NVIDIA GeForce / RTX graphics.
   - CPU usage: < 0.05%, memory footprint: ~15 MB.

4. **Floating Windows 10 Dark Widget**:
   - Sleek frameless dark UI styled with Windows 10 `Segoe UI` and `Consolas`.
   - Header is draggable to reposition anywhere on screen.
   - Taskbar-aware screen clamping prevents window from hiding behind the Windows taskbar.
   - Pin button (`📌`) for Always-on-Top.
   - Minimize button (`─`) shrinks the widget to a compact mini-pill: `[ ⚡ RAM: 45% | CPU: 12% | 🔌 AC ]`.

---

## 🚀 Quick Start on Windows 10

### 1. Requirements
- **Windows 10** (or Windows 11), 64-bit or 32-bit.
- **Python 3.8+** installed from [python.org](https://www.python.org/downloads/).
  *(Make sure **"Add Python to PATH"** and **"tcl/tk and IDLE"** checkboxes were checked during Python installation).*

### 2. Launching the Floating Widget
- **Method A (Silent Background Run):** Double-click [`launch.vbs`](file:///home/pradeep/power-monitor/windows/launch.vbs).
  *(Launches the widget cleanly without any black CMD console window).*
- **Method B (Console Mode):** Double-click [`launch.bat`](file:///home/pradeep/power-monitor/windows/launch.bat).

### 3. Automatic Startup on Boot
- Double-click [`install_startup.bat`](file:///home/pradeep/power-monitor/windows/install_startup.bat).
- This creates an autostart runner in your Windows Startup folder (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`).
- The sentry will silently launch in the background every time you log into Windows!
- To remove: run [`uninstall_startup.bat`](file:///home/pradeep/power-monitor/windows/uninstall_startup.bat).

---

## 📊 Analyzing Crash Logs

When an unexpected shutdown occurs, reboot your laptop and:

1. Click the **📊 Analyze Logs** button directly on the floating widget.
   *OR*
2. Run from Command Prompt / PowerShell:
   ```cmd
   python analyze.py
   ```

### What You Will See:
- Total sessions recorded and clean vs abrupt stop detection.
- **Pre-Crash Window**: A second-by-second breakdown of the **final 15 to 30 seconds** before power was lost:
  - Exact timestamp of the final second.
  - RAM used and Committed Memory (detecting commit exhaustion / OOM).
  - CPU utilization % and package thermals (detecting thermal trips > 90°C).
  - AC status (Plugged In vs On Battery) and battery percentage.

---

## 📁 File Structure

```text
power-monitor-windows/
├── record_format.py      # Compact 64-byte binary telemetry packer & unpacker
├── sensors.py            # Win32 ctypes hardware, memory & battery telemetry reader
├── collector.py          # 1-second sampling daemon with FlushFileBuffers disk sync
├── widget.py             # Floating desktop Tkinter GUI widget for Windows 10
├── analyze.py            # Pre-crash diagnostic parser & analysis reporter
├── launch.vbs            # Silent launcher (no CMD window)
├── launch.bat            # Batch launcher with diagnostic outputs
├── install_startup.bat   # Installs autostart shortcut into Windows Startup
├── uninstall_startup.bat # Uninstalls autostart shortcut
├── requirements.txt      # Zero dependencies (optional wmi / psutil notes)
└── data/
    └── metrics.bin       # Binary telemetry log file
```
