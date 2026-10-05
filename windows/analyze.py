#!/usr/bin/env python3
"""
Telemetry Analyzer for Power & Memory Crash Diagnostic (Windows 10 Edition).
Detects abrupt power cuts, parses pre-crash seconds, and diagnoses
whether hardware failure was triggered by battery collapse, memory spikes, or thermal load.
"""

import os
import sys
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

from record_format import (
    unpack_record,
    MAGIC_SAMPLE,
    MAGIC_START,
    MAGIC_STOP,
    RECORD_SIZE,
)

# Enable ANSI escape colors on Windows 10 CMD & PowerShell
if os.name == 'nt':
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            mode.value |= 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            kernel32.SetConsoleMode(handle, mode)
    except Exception:
        pass

DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
DEFAULT_LOG_PATH = os.path.join(DEFAULT_DATA_DIR, 'metrics.bin')


def fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')


def fmt_duration(seconds: float) -> str:
    mins, sec = divmod(int(seconds), 60)
    hrs, mins = divmod(mins, 60)
    days, hrs = divmod(hrs, 24)
    parts = []
    if days > 0: parts.append(f"{days}d")
    if hrs > 0: parts.append(f"{hrs}h")
    if mins > 0: parts.append(f"{mins}m")
    parts.append(f"{sec}s")
    return " ".join(parts)


class TelemetryAnalyzer:
    def __init__(self, log_path: str = DEFAULT_LOG_PATH):
        self.log_path = log_path
        self.sessions: List[Dict[str, Any]] = []

    def parse(self) -> bool:
        if not os.path.exists(self.log_path):
            print(f"[-] No log file found at {self.log_path}")
            return False

        file_size = os.path.getsize(self.log_path)
        if file_size < RECORD_SIZE:
            print(f"[-] Log file is empty or smaller than one record ({file_size} bytes).")
            return False

        current_session: Optional[Dict[str, Any]] = None
        self.sessions = []
        valid_records = 0
        corrupt_records = 0

        with open(self.log_path, 'rb') as f:
            while True:
                buf = f.read(RECORD_SIZE)
                if len(buf) < RECORD_SIZE:
                    break

                rec = unpack_record(buf)
                if rec is None:
                    corrupt_records += 1
                    continue

                valid_records += 1
                magic = rec['magic']

                if magic == MAGIC_START:
                    if current_session is not None:
                        current_session['crashed'] = not current_session['stopped_cleanly']
                        self.sessions.append(current_session)

                    current_session = {
                        'start_time': rec['timestamp'],
                        'end_time': rec['timestamp'],
                        'records': [],
                        'stopped_cleanly': False,
                        'crashed': False,
                    }
                elif magic == MAGIC_STOP:
                    if current_session is not None:
                        current_session['end_time'] = rec['timestamp']
                        current_session['stopped_cleanly'] = True
                        current_session['crashed'] = False
                        self.sessions.append(current_session)
                        current_session = None
                elif magic == MAGIC_SAMPLE:
                    if current_session is None:
                        current_session = {
                            'start_time': rec['timestamp'],
                            'end_time': rec['timestamp'],
                            'records': [],
                            'stopped_cleanly': False,
                            'crashed': False,
                        }
                    current_session['end_time'] = rec['timestamp']
                    current_session['records'].append(rec)

        if current_session is not None:
            time_since_last = time.time() - current_session['end_time']
            if not current_session['stopped_cleanly'] and time_since_last > 45:
                current_session['crashed'] = True
            self.sessions.append(current_session)

        return True

    def report(self):
        if not self.sessions:
            print("[*] No sessions recorded yet.")
            return

        total_samples = sum(len(s['records']) for s in self.sessions)
        crashes = [s for s in self.sessions if s['crashed']]

        print("=" * 80)
        print("          WINDOWS 10 POWER & TELEMETRY CRASH REPORT")
        print("=" * 80)
        print(f"Log File: {self.log_path}")
        print(f"Total Sessions: {len(self.sessions)}")
        print(f"Total Samples Logged: {total_samples:,}")
        print(f"Detected Abrupt Power-Off Crashes: {len(crashes)}")
        print("-" * 80)

        for idx, s in enumerate(self.sessions, 1):
            dur = s['end_time'] - s['start_time']
            status = "CRASH / UNEXPECTED POWER-OFF" if s['crashed'] else (
                "CLEAN STOP" if s['stopped_cleanly'] else "ACTIVE / IN PROGRESS"
            )
            color_prefix = "\033[91m[!]\033[0m" if s['crashed'] else "\033[92m[✓]\033[0m"
            print(f"\n{color_prefix} Session #{idx}: {status}")
            print(f"    Started : {fmt_time(s['start_time'])}")
            print(f"    Ended   : {fmt_time(s['end_time'])} ({fmt_duration(dur)})")
            print(f"    Samples : {len(s['records']):,}")

            recs = s['records']
            if not recs:
                continue

            max_mem = max(r['mem_used_mb'] for r in recs)
            mem_tot = recs[0]['mem_total_mb']
            max_cpu = max(r['cpu_pct'] for r in recs)
            max_pkg_t = max(r['temp_cpu_pkg'] for r in recs)
            
            # Check battery presence
            has_battery = any(r.get('battery_present', False) for r in recs)
            min_battery = min((r.get('battery_pct', 100) for r in recs if r.get('battery_present', False)), default=100)
            was_on_battery = any(not r.get('ac_online', True) for r in recs)

            print(f"    Peak RAM : {max_mem:,} MB / {mem_tot:,} MB ({max_mem*100//max(1,mem_tot)}%)")
            print(f"    CPU Peak : {max_cpu}% | Temp Peak: {max_pkg_t}°C" if max_pkg_t > 0 else f"    CPU Peak : {max_cpu}%")
            if has_battery:
                pwr_mode = "Discharged on Battery" if was_on_battery else "AC Connected"
                print(f"    Power    : {pwr_mode} | Min Battery: {min_battery}%")

            if s['crashed']:
                self._print_crash_window(s, has_battery)

        print("\n" + "=" * 80)
        self._print_overall_recommendations()
        print("=" * 80)

    def _print_crash_window(self, session: Dict[str, Any], has_battery: bool = True, seconds: int = 30):
        recs = session['records']
        if not recs:
            return

        window = recs[-seconds:]
        print(f"\n    \033[93m>>> PRE-CRASH WINDOW (Final {len(window)} seconds before power cut) <<<\033[0m")
        if has_battery:
            print(f"    {'Time':<8} | {'RAM Used':<10} | {'Commit':<8} | {'CPU%':<5} | {'Temp':<6} | {'Power Source':<15} | {'Battery%'}")
            print("    " + "-" * 75)
            for r in window[-15:]:
                t_str = datetime.fromtimestamp(r['timestamp']).strftime('%H:%M:%S')
                ram_str = f"{r['mem_used_mb']} MB"
                com_str = f"{r['committed_mb']//1024} GB"
                cpu_str = f"{r['cpu_pct']}%"
                tmp_str = f"{r['temp_cpu_pkg']}°C" if r['temp_cpu_pkg'] > 0 else "--"
                ac_str = "🔌 AC Power" if r.get('ac_online', True) else "🔋 Battery"
                bat_str = f"{r.get('battery_pct', 0)}%" if r.get('battery_present', False) else "N/A"
                print(f"    {t_str:<8} | {ram_str:<10} | {com_str:<8} | {cpu_str:<5} | {tmp_str:<6} | {ac_str:<15} | {bat_str}")
        else:
            print(f"    {'Time':<8} | {'RAM Used':<10} | {'Commit':<8} | {'CPU%':<5} | {'Temp':<6} | {'3.3V Rail'}")
            print("    " + "-" * 65)
            for r in window[-15:]:
                t_str = datetime.fromtimestamp(r['timestamp']).strftime('%H:%M:%S')
                ram_str = f"{r['mem_used_mb']} MB"
                com_str = f"{r['committed_mb']//1024} GB"
                cpu_str = f"{r['cpu_pct']}%"
                tmp_str = f"{r['temp_cpu_pkg']}°C" if r['temp_cpu_pkg'] > 0 else "--"
                vcc_str = f"{r['v_vcc_mv']/1000.0:.3f}V"
                print(f"    {t_str:<8} | {ram_str:<10} | {com_str:<8} | {cpu_str:<5} | {tmp_str:<6} | {vcc_str}")

        last_r = recs[-1]
        print(f"\n    \033[91m[!] EXACT FINAL SAMPLE RECORDED AT {fmt_time(last_r['timestamp'])}:\033[0m")
        print(f"        RAM: {last_r['mem_used_mb']} MB ({last_r['mem_used_mb']*100//max(1, last_r['mem_total_mb'])}%) | Free: {last_r['mem_avail_mb']} MB")
        print(f"        Committed Memory: {last_r['committed_mb']} MB")
        print(f"        CPU Utilization: {last_r['cpu_pct']}%")
        if last_r.get('battery_present', False):
            ac_word = "AC Plugged In" if last_r.get('ac_online', True) else "RUNNING ON BATTERY"
            print(f"        Power: {ac_word} | Battery: {last_r.get('battery_pct', 0)}%")

    def _print_overall_recommendations(self):
        print("WINDOWS 10 LAPTOP HARDWARE DIAGNOSTIC GUIDANCE:")
        print("1. Battery Cutoff vs AC Adapter Trip:")
        print("   If the final sample shows running on battery with low percentage, the laptop's")
        print("   battery BMS may have cut power due to cell undervoltage under sudden CPU burst draw.")
        print("   If on AC power, check for loose DC barrel / USB-C PD connection or thermal shutdown.")
        print("2. Memory-Induced Thrashing & Commit Limit Crash:")
        print("   If RAM utilization climbs > 90% and Committed Memory approaches Pagefile limit,")
        print("   Windows commits fail and the OS may freeze or trigger an emergency thermal/power trip.")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LOG_PATH
    analyzer = TelemetryAnalyzer(path)
    if analyzer.parse():
        analyzer.report()


if __name__ == '__main__':
    main()
