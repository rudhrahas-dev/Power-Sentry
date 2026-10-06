"""
Crash Prediction & Hardware Failure Imminence Detector.
Cross-references real-time hardware telemetry against historical crash sessions
to detect and alert before abrupt power-loss or system shutdown occurs.
"""

import os
import sys
import time
import collections
import ctypes
import gc
from typing import Dict, List, Tuple, Any, Optional

from record_format import RECORD_SIZE
from analyze import TelemetryAnalyzer, DEFAULT_LOG_PATH


class CrashProfile:
    """Historical crash statistics and thresholds extracted from telemetry logs."""
    def __init__(self):
        self.total_crashes = 0
        self.min_vcc_observed = 3.30
        self.max_dirty_observed = 0
        self.max_ram_pct_observed = 0
        self.max_psi_observed = 0.0
        self.crash_sessions_summary = []

    def populate_from_analyzer(self, analyzer: TelemetryAnalyzer):
        crashes = [s for s in analyzer.sessions if s['crashed']]
        self.total_crashes = len(crashes)
        
        all_min_vcc = []
        all_max_dirty = []
        all_max_ram_pct = []
        all_max_psi = []

        for idx, s in enumerate(crashes, 1):
            recs = s.get('records', [])
            if not recs:
                continue
            
            tot_mem = max(1, recs[0].get('mem_total_mb', 1))
            vccs = [r['v_vcc_mv']/1000.0 for r in recs if r.get('v_vcc_mv', 0) > 0]
            dirties = [r.get('dirty_mb', 0) for r in recs]
            rams = [r.get('mem_used_mb', 0) for r in recs]
            psis = [r.get('psi_some_10', 0)/100.0 for r in recs]

            s_min_vcc = min(vccs) if vccs else 3.30
            s_max_dirty = max(dirties) if dirties else 0
            s_max_ram = max(rams) if rams else 0
            s_max_psi = max(psis) if psis else 0.0
            s_max_ram_pct = int((s_max_ram / tot_mem) * 100)

            all_min_vcc.append(s_min_vcc)
            all_max_dirty.append(s_max_dirty)
            all_max_ram_pct.append(s_max_ram_pct)
            all_max_psi.append(s_max_psi)

            self.crash_sessions_summary.append({
                'session_num': idx,
                'min_vcc': s_min_vcc,
                'max_dirty': s_max_dirty,
                'max_ram_pct': s_max_ram_pct,
                'max_psi': s_max_psi,
                'duration': s['end_time'] - s['start_time'],
                'samples': len(recs),
            })

        if all_min_vcc:
            self.min_vcc_observed = min(all_min_vcc)
        if all_max_dirty:
            self.max_dirty_observed = max(all_max_dirty)
        if all_max_ram_pct:
            self.max_ram_pct_observed = max(all_max_ram_pct)
        if all_max_psi:
            self.max_psi_observed = max(all_max_psi)


class CrashAssessment:
    """Result of an imminence risk evaluation."""
    def __init__(
        self,
        risk_score: int,
        level: str,
        headline: str,
        matched_signatures: List[str],
        color: str,
        is_flashing: bool,
        recommendation: str,
    ):
        self.risk_score = risk_score          # 0 to 100%
        self.level = level                    # 'STABLE', 'ELEVATED', 'HIGH', 'IMMINENT'
        self.headline = headline              # Short display headline
        self.matched_signatures = matched_signatures  # Explanations of matched crash conditions
        self.color = color                    # UI accent color
        self.is_flashing = is_flashing        # Alert pulsing indicator
        self.recommendation = recommendation  # Actionable advice


class CrashPredictor:
    def __init__(self, log_path: str = DEFAULT_LOG_PATH, window_size: int = 30):
        self.log_path = log_path
        self.window_size = window_size
        self.history = collections.deque(maxlen=window_size)
        self.profile = CrashProfile()
        self.reload_historical_profile()

    def reload_historical_profile(self):
        """Analyze past logged sessions to calibrate crash thresholds."""
        try:
            analyzer = TelemetryAnalyzer(self.log_path)
            if analyzer.parse():
                self.profile.populate_from_analyzer(analyzer)
        except Exception:
            pass

    def add_sample(self, sample: dict):
        """Append a real-time sample to the sliding window."""
        self.history.append(sample)

    def evaluate(self, current_sample: Optional[dict] = None) -> CrashAssessment:
        """
        Evaluate real-time telemetry against historical crash signatures.
        Returns a CrashAssessment object.
        """
        if current_sample:
            self.history.append(current_sample)
        
        if not self.history:
            return CrashAssessment(
                risk_score=0,
                level='STABLE',
                headline='HEALTH: STABLE (0%)',
                matched_signatures=[],
                color='#2ecc71',
                is_flashing=False,
                recommendation='System operating within safe margins.',
            )

        curr = self.history[-1]
        window = list(self.history)

        mem_used = curr.get('mem_used_mb', 0)
        mem_tot = max(1, curr.get('mem_total_mb', 1))
        mem_pct = (mem_used / mem_tot) * 100.0
        dirty = curr.get('dirty_mb', 0)
        swap = curr.get('swap_used_mb', 0)
        psi = curr.get('psi_some_10', 0) / 100.0
        vcc_curr = curr.get('v_vcc_mv', 0) / 1000.0

        # Rolling window stats
        vccs = [r['v_vcc_mv']/1000.0 for r in window if r.get('v_vcc_mv', 0) > 0]
        min_vcc = min(vccs) if vccs else vcc_curr
        vcc_swing = (max(vccs) - min(vccs)) if vccs else 0.0

        dirties = [r.get('dirty_mb', 0) for r in window]
        max_dirty = max(dirties) if dirties else dirty
        dt = max(1, window[-1].get('timestamp', 0) - window[0].get('timestamp', 0))
        dirty_rate = (dirty - dirties[0]) / dt if len(dirties) > 1 else 0.0

        psis = [r.get('psi_some_10', 0)/100.0 for r in window]
        max_psi = max(psis) if psis else psi

        matched_signatures = []

        # --- 1. Dirty Buffer Pressure (Fingerprint of Session #8 & #9) ---
        # In Session #8, dirty reached 243 MB; in Session #9, dirty reached 220 MB.
        dirty_score = 0
        if dirty >= 200 or max_dirty >= 200:
            dirty_score = 45
            matched_signatures.append(
                f"Matches S8/S9 Crash Surge: Dirty buffer ({dirty}MB) exceeds 200MB critical threshold"
            )
        elif dirty >= 140 or (dirty >= 80 and dirty_rate >= 5.0):
            dirty_score = 35
            rate_str = f" (+{dirty_rate:.1f}MB/s)" if dirty_rate > 0 else ""
            matched_signatures.append(
                f"Rapid Dirty Buffer Accumulation: {dirty}MB{rate_str} nearing write-burst cutoff"
            )
        elif dirty >= 75:
            dirty_score = 20
            matched_signatures.append(
                f"Elevated Dirty Pages: {dirty}MB pending uncommitted disk writes"
            )
        elif dirty >= 30:
            dirty_score = 8

        # --- 2. 3.3V Rail Voltage Sag & Instability (Fingerprint of Session #7 & #10) ---
        # ATX spec minimum is 3.135V. In S7 it fell to 3.168V; in S10 it fell to 3.200V.
        vcc_score = 0
        if min_vcc > 0:
            if min_vcc <= 3.180:
                vcc_score = 42
                matched_signatures.append(
                    f"Matches S7 UVP Cutoff: 3.3V rail dropped to {min_vcc:.3f}V (under-voltage trip danger)"
                )
            elif min_vcc <= 3.232:
                vcc_score = 32
                matched_signatures.append(
                    f"Matches S10/S7 Rail Sag: 3.3V rail sagged to {min_vcc:.3f}V (nominal 3.30V)"
                )
            elif min_vcc <= 3.264:
                vcc_score = 22
                matched_signatures.append(
                    f"Matches S2/S3/S4 Rail Droop: 3.3V rail dipping to {min_vcc:.3f}V under load"
                )
            elif min_vcc <= 3.296:
                vcc_score = 10

        # Excessive ripple indicates degraded smoothing capacitor under sudden current draw
        if vcc_swing >= 0.120:
            vcc_score += 12
            matched_signatures.append(
                f"High Rail Voltage Ripple: {vcc_swing*1000:.0f}mV swing detected across 30s window"
            )

        # --- 3. RAM Saturation (Fingerprint of Session #7 & #10) ---
        # Peak RAM before crash in S10 was 78% (6,228 MB), in S7 was 76% (6,010 MB).
        ram_score = 0
        if mem_pct >= 75:
            ram_score = 25
            matched_signatures.append(
                f"Matches S10 Peak RAM: Memory usage at {mem_pct:.0f}% ({mem_used}MB / {mem_tot}MB)"
            )
        elif mem_pct >= 70:
            ram_score = 18
            matched_signatures.append(
                f"Matches S7 Pre-Crash Stress: Memory usage elevated at {mem_pct:.0f}% ({mem_used}MB)"
            )
        elif mem_pct >= 62:
            ram_score = 10

        # --- 4. System Thrash & Swap Penalties ---
        bonus = 0
        if max_psi >= 5.0:
            bonus += 12
            matched_signatures.append(
                f"Matches S7 Memory Thrashing: PSI pressure stall at {max_psi:.1f}%"
            )
        if swap >= 1500:
            bonus += 8
            matched_signatures.append(
                f"High Swap Paging Pressure: {swap}MB swap active, straining I/O bus"
            )

        # --- 5. Compound Multipliers (Multiple Correlated Stressors) ---
        total = dirty_score + vcc_score + ram_score + bonus
        if (dirty >= 140 or max_dirty >= 140) and min_vcc <= 3.264:
            # Matches exact trigger of sudden power collapse in S8/S9
            total = int(total * 1.25)
        elif mem_pct >= 70 and min_vcc <= 3.264:
            # Matches exact trigger of high-load collapse in S7/S10
            total = int(total * 1.20)

        risk_score = min(100, max(0, total))

        if risk_score >= 75:
            level = 'IMMINENT'
            headline = f"🚨 CRASH IMMINENT ({risk_score}%)"
            color = '#e74c3c'  # Vibrant Red
            is_flashing = True
            recommendation = "CRITICAL: Clear memory & flush dirty buffers now to prevent power cutoff!"
        elif risk_score >= 50:
            level = 'HIGH'
            headline = f"⚠ HIGH CRASH RISK ({risk_score}%)"
            color = '#e67e22'  # Orange
            is_flashing = False
            recommendation = "WARNING: System matching historical crash conditions. Relieve memory stress."
        elif risk_score >= 30:
            level = 'ELEVATED'
            headline = f"⚠ ELEVATED RISK ({risk_score}%)"
            color = '#f1c40f'  # Amber/Yellow
            is_flashing = False
            recommendation = "CAUTION: Voltage droop or dirty buffer accumulation detected."
        else:
            level = 'STABLE'
            headline = f"● SYSTEM STABLE ({risk_score}%)"
            color = '#2ecc71'  # Green
            is_flashing = False
            recommendation = "System operating within safe operating margins."

        return CrashAssessment(
            risk_score=risk_score,
            level=level,
            headline=headline,
            matched_signatures=matched_signatures,
            color=color,
            is_flashing=is_flashing,
            recommendation=recommendation,
        )


def relieve_memory_stress() -> Dict[str, Any]:
    """
    Clears unwanted memory, flushes dirty pages, and reduces system stress.
    Directly counteracts the pre-crash triggers observed in telemetry logs:
      1. Flushes filesystem dirty buffers via os.sync() (prevents S8/S9 write bursts).
      2. Reclaims Python & C-heap fragmentation via malloc_trim(0) and gc.collect().
      3. Safely drops system caches where permissions permit.
    """
    t0 = time.time()
    if os.name == 'nt':

        try:
            psapi = ctypes.windll.psapi
            psapi.EmptyWorkingSet(-1)
        except Exception:
            pass
        gc.collect()
        return {
            'dirty_cleared_mb': 0,
            'avail_gained_mb': 0,
            'dirty_now_mb': 0,
            'avail_now_mb': 0,
            'caches_dropped': False,
            'elapsed_ms': (time.time() - t0) * 1000,
        }

    # Read initial memory state on Linux
    def get_mem():

        mem = {}
        try:
            with open('/proc/meminfo', 'r') as f:
                for line in f:
                    p = line.split(':')
                    if len(p) == 2:
                        mem[p[0].strip()] = int(p[1].strip().split()[0]) // 1024
        except Exception:
            pass
        return mem

    before = get_mem()
    
    # Action 1: Synchronize filesystem buffers immediately
    # Flushes dirty page cache to NVMe/SATA controller, resetting dirty_mb to 0
    try:
        os.sync()
    except Exception:
        pass

    # Action 2: glibc malloc_trim & garbage collection
    try:
        libc = ctypes.CDLL('libc.so.6')
        libc.malloc_trim(0)
    except Exception:
        pass
    gc.collect()

    # Action 3: Attempt drop_caches if running privileged or writable
    caches_dropped = False
    try:
        with open('/proc/sys/vm/drop_caches', 'w') as f:
            f.write('3\n')
        caches_dropped = True
    except Exception:
        caches_dropped = False

    after = get_mem()
    
    dirty_cleared = max(0, before.get('Dirty', 0) - after.get('Dirty', 0))
    avail_before = before.get('MemAvailable', 0)
    avail_after = after.get('MemAvailable', 0)
    avail_gained = max(0, avail_after - avail_before)
    elapsed_ms = (time.time() - t0) * 1000

    return {
        'dirty_cleared_mb': dirty_cleared,
        'avail_gained_mb': avail_gained,
        'dirty_now_mb': after.get('Dirty', 0),
        'avail_now_mb': avail_after,
        'caches_dropped': caches_dropped,
        'elapsed_ms': elapsed_ms,
    }
