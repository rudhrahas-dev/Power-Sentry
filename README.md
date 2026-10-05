# Power Sentry (Hardware & Memory Crash Diagnostic)

A high-frequency, zero-overhead telemetry logger and floating desktop widget designed specifically for diagnosing sudden, abrupt hardware power-off / reboot events on **Linux and Windows 10 Laptops & Desktops**.

---

## ⚡ How It Works

1. **Abrupt Shutdown Protection (`fdatasync` / `FlushFileBuffers` per second)**:
   - When an SMPS capacitor, laptop battery, or power rail collapses, the system instantly powers off with zero seconds of OS warning. Standard logs held in RAM buffer cache are lost.
   - This utility samples metrics every 1.0s, packs them into a 64-byte binary record, and immediately executes physical disk flush operations (`os.fdatasync()` on Linux, `kernel32.FlushFileBuffers()` on Windows) to commit the bytes to non-volatile physical storage.
   - Telemetry right up to the final second before power collapse is preserved.

2. **Ultra-Low Memory & Storage Footprint**:
   - Built natively without heavy frameworks:
     - **Linux**: Direct sysfs `/sys/class/hwmon`, `/proc/meminfo`, `/proc/pressure`, `/proc/stat`.
     - **Windows 10**: Native Win32 `ctypes` (`GlobalMemoryStatusEx`, `GetSystemTimes`, `GetSystemPowerStatus`).
   - Record size: **64 bytes**.
   - Storage usage: ~5.5 MB per 24 hours.
   - CPU usage: < 0.05% (no subprocess forks).

3. **Floating Desktop Widget**:
   - Modern, sleek dark UI showing live RAM utilization, CPU load, thermals, and power rails (plus laptop battery & AC status on Windows).
   - Draggable header, pinned / unpinned (`📌` Always-on-Top), and minimizable to a mini "pill" (`[ ⚡ RAM: 72% | 42°C | 🔌 AC ]`).

4. **Multi-Platform Support**:
   - **Linux**: Root directory scripts (`collector.py`, `widget.py`, `analyze.py`, `launch.sh`).
   - **Windows 10**: Ported standalone package in [`windows/`](windows/) directory (with `launch.vbs`, `launch.bat`, `install_startup.bat`).

---

## 💻 Windows 10 Laptop Edition

For Windows 10 and 11 laptops:
- **Pre-packaged ZIP**: Download [`power_monitor_windows10.zip`](https://github.com/rudhrahas-dev/Power-Sentry/releases/download/v1.0.0/power_monitor_windows10.zip) (or via [raw link](https://github.com/rudhrahas-dev/Power-Sentry/raw/main/power_monitor_windows10.zip)).
- **Documentation**: See [`windows/README.md`](windows/README.md) for complete setup, battery telemetry details, and auto-start guide.

---

## 🚀 Linux Quick Commands

### Run Widget Manually:
```bash
./launch.sh
```

### Run Pure Headless Daemon (No GUI Window):
```bash
python3 collector.py
```

### Analyze Logs & View Pre-Crash Telemetry:
```bash
python3 analyze.py
```
Or click the **📊 Analyze Logs** button directly on the floating widget!

---

## 📋 Tracked Metrics in Each 64-Byte Record

| Metric | Source (Linux) | Source (Windows 10) | Significance |
|---|---|---|---|
| RAM Used / Avail | `/proc/meminfo` | `GlobalMemoryStatusEx` | Memory pressure & leak detection |
| Committed Memory | `/proc/meminfo` | `GlobalMemoryStatusEx` | Commit limit exhaustion |
| CPU Utilization | `/proc/stat` delta | `GetSystemTimes` delta | System processor load |
| Battery & AC Status | — | `GetSystemPowerStatus` | Laptop battery collapse vs AC disconnect |
| Temperatures | `coretemp`, `nct6683` | ACPI ThermalZone / LHM | Thermal throttle / shutdown boundary |
| Power Rails / Voltages | `nct6683/in*` | Hardware / WMI | SMPS & VRM voltage drop detection |

---

## 🔍 Pre-Crash Analysis & Diagnostics

Run:
```bash
python3 analyze.py
```
This will:
1. Detect any power loss events and print the **final 15–30 seconds** leading to the power cut.
2. Cross-correlate whether memory spikes caused:
   - A drop in power rail voltages.
   - Sudden battery cutoff or AC adapter disconnection.
   - High thermal load (> 80°C).
   - Commit limit / memory exhaustion.

---

## 📄 License
Copyright (c) 2026 Rudhrahas (acegamerprotech@gmail.com). All rights reserved.
