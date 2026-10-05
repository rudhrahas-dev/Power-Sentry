#!/usr/bin/env python3
"""
Telemetry Analyzer for Power & Memory Crash Diagnostic.
Detects abrupt power cuts, parses pre-crash seconds, and diagnoses
whether hardware failure was triggered by memory spikes, voltage drops, or thermal load.
"""

import os
import sys
import time
from datetime import datetime
from typing import List, Dict, Any

from record_format import (
    unpack_record,
    MAGIC_SAMPLE,
    MAGIC_START,
    MAGIC_STOP,
    RECORD_SIZE,
)

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
                        # Previous session didn't cleanly stop!
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
            # Check if current session ended without stop
            # If the last record was more than 30 seconds ago, it is likely crashed
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

        print("=" * 75)
        print("          POWER & HARDWARE TELEMETRY ANALYSIS REPORT")
        print("=" * 75)
        print(f"Log File: {self.log_path}")
        print(f"Total Sessions: {len(self.sessions)}")
        print(f"Total Samples Logged: {total_samples:,}")
        print(f"Detected Abrupt Power-Cut Crashes: {len(crashes)}")
        print("-" * 75)

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

            # Summary stats for this session
            max_mem = max(r['mem_used_mb'] for r in recs)
            mem_tot = recs[0]['mem_total_mb']
            max_cpu = max(r['cpu_pct'] for r in recs)
            max_pkg_t = max(r['temp_cpu_pkg'] for r in recs)
            max_vrm_t = max(r['temp_vrm'] for r in recs)
            max_pch_t = max(r['temp_pch'] for r in recs)
            vcc_vals = [r['v_vcc_mv'] for r in recs if r['v_vcc_mv'] > 0]
            vcore_vals = [r['v_in0_mv'] for r in recs if r['v_in0_mv'] > 0]
            min_vcc = min(vcc_vals) if vcc_vals else 0
            min_vcore = min(vcore_vals) if vcore_vals else 0

            print(f"    Peak RAM : {max_mem:,} MB / {mem_tot:,} MB ({max_mem*100//max(1,mem_tot)}%)")
            print(f"    Temps    : CPU Max: {max_pkg_t}°C | VRM Max: {max_vrm_t}°C | PCH Max: {max_pch_t}°C")
            print(f"    Voltages : Min VCC 3.3V: {min_vcc/1000.0:.3f}V | Min VCore: {min_vcore/1000.0:.3f}V")

            if s['crashed']:
                self._print_crash_window(s)

        print("\n" + "=" * 75)
        self._print_overall_recommendations()
        print("=" * 75)

    def _print_crash_window(self, session: Dict[str, Any], seconds: int = 30):
        recs = session['records']
        if not recs:
            return

        window = recs[-seconds:]
        print(f"\n    \033[93m>>> CRITICAL: Pre-Crash Window (Final {len(window)} seconds before power died) <<<\033[0m")
        print(f"    {'Time':<8} | {'RAM Used':<10} | {'Dirty':<7} | {'PSI':<5} | {'CPU%':<5} | {'Pkg°C':<6} | {'VRM°C':<6} | {'3.3V Rail':<9} | {'VCore'}")
        print("    " + "-" * 75)

        for r in window[-15:]:  # show final 15 seconds line-by-line
            t_str = datetime.fromtimestamp(r['timestamp']).strftime('%H:%M:%S')
            ram_str = f"{r['mem_used_mb']} MB"
            dirty_str = f"{r['dirty_mb']} MB"
            psi_str = f"{r['psi_some_10']:.1f}%"
            cpu_str = f"{r['cpu_pct']}%"
            pkg_str = f"{r['temp_cpu_pkg']}°C"
            vrm_str = f"{r['temp_vrm']}°C"
            vcc_str = f"{r['v_vcc_mv']/1000.0:.3f}V"
            vcore_str = f"{r['v_in0_mv']/1000.0:.3f}V"
            print(f"    {t_str:<8} | {ram_str:<10} | {dirty_str:<7} | {psi_str:<5} | {cpu_str:<5} | {pkg_str:<6} | {vrm_str:<6} | {vcc_str:<9} | {vcore_str}")

        last_r = recs[-1]
        print(f"\n    \033[91m[!] EXACT FINAL SAMPLE RECORDED AT {fmt_time(last_r['timestamp'])}:\033[0m")
        print(f"        RAM: {last_r['mem_used_mb']} MB ({last_r['mem_used_mb']*100//max(1, last_r['mem_total_mb'])}%) | Free: {last_r['mem_avail_mb']} MB")
        print(f"        Dirty Buffer: {last_r['dirty_mb']} MB | Memory PSI: {last_r['psi_some_10']}%")
        print(f"        CPU Temp: {last_r['temp_cpu_pkg']}°C | VRM: {last_r['temp_vrm']}°C | PCH: {last_r['temp_pch']}°C")
        print(f"        VCC 3.3V Rail: {last_r['v_vcc_mv']/1000.0:.3f}V | VCore: {last_r['v_in0_mv']/1000.0:.3f}V")

    def _print_overall_recommendations(self):
        print("DIAGNOSTIC SUMMARY & PREDICTION SIGNALS:")
        print("1. Memory-Correlated Voltage Sag:")
        print("   When memory spikes, rapid memory bus activity + CPU turbo draw causes")
        print("   sudden current surges (di/dt) on the 3.3V and 12V SMPS lines.")
        print("   A degraded SMPS capacitor or motherboard VRM capacitor fails to smooth this drop,")
        print("   triggering the motherboard's UVP (Under-Voltage Protection) hardware cutoff.")
        print("2. Safe Thresholds for Early Warning:")
        print("   - RAM Utilization > 90% with rapid climb rate")
        print("   - VCC 3.3V rail dropping below 3.14V (ATX specification limit: 3.135V)")
        print("   - VRM temperature climbing above 75°C")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LOG_PATH
    analyzer = TelemetryAnalyzer(path)
    if analyzer.parse():
        analyzer.report()


if __name__ == '__main__':
    main()
