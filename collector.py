"""
Power and Memory Crash Collector Daemon.
Collects hardware telemetry every second and commits to disk immediately using fdatasync.
Resumes automatically after sudden reboot/power-off.
"""

import os
import sys
import time
import signal
import threading
from typing import Optional, Callable

from record_format import (
    pack_record,
    MAGIC_SAMPLE,
    MAGIC_START,
    MAGIC_STOP,
    RECORD_SIZE,
)
from sensors import HardwareSensors

DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
DEFAULT_LOG_PATH = os.path.join(DEFAULT_DATA_DIR, 'metrics.bin')


class CrashCollector:
    def __init__(
        self,
        log_path: str = DEFAULT_LOG_PATH,
        interval_sec: float = 1.0,
        sample_callback: Optional[Callable[[dict], None]] = None,
    ):
        self.log_path = log_path
        self.interval_sec = interval_sec
        self.sample_callback = sample_callback
        self.sensors = HardwareSensors()
        self.running = False
        self.seq = 0
        self.fd: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self.records_written = 0
        self.last_sample_data: dict = {}

        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        self.lock_path = os.path.join(os.path.dirname(self.log_path), 'collector.lock')
        self.lock_fd: Optional[int] = None
        self.is_writer = True

    def _acquire_lock(self) -> bool:
        import fcntl
        try:
            self.lock_fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o644)
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.is_writer = True
            return True
        except (IOError, BlockingIOError):
            # Another collector is already running and actively writing
            self.is_writer = False
            return False

    def _open_file(self):
        if not self._acquire_lock():
            return
        # Open in append binary mode
        self.fd = os.open(
            self.log_path,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o644
        )

    def _write_and_sync(self, raw_bytes: bytes):
        if self.is_writer and self.fd is not None:
            os.write(self.fd, raw_bytes)
            # CRITICAL: fdatasync flushes physical drive caches
            # so sudden SMPS power loss does NOT discard the last seconds of telemetry!
            os.fdatasync(self.fd)
            self.records_written += 1

    def start(self, run_in_background: bool = False):
        self.running = True
        self._open_file()
        
        # Write session start marker
        start_ts = time.time()
        start_rec = pack_record(
            magic=MAGIC_START,
            seq=self.seq,
            ts=start_ts,
        )
        self._write_and_sync(start_rec)
        self.seq += 1

        if run_in_background:
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
        else:
            self._run_loop()

    def _run_loop(self):
        while self.running:
            start_t = time.time()
            try:
                metrics = self.sensors.sample()
                rec = pack_record(
                    magic=MAGIC_SAMPLE,
                    seq=self.seq,
                    ts=start_t,
                    **metrics
                )
                self._write_and_sync(rec)
                self.seq += 1
                
                metrics['seq'] = self.seq
                metrics['timestamp'] = start_t
                self.last_sample_data = metrics
                
                if self.sample_callback:
                    self.sample_callback(metrics)
            except Exception as e:
                # Keep running even if a single sensor query had an issue
                pass

            elapsed = time.time() - start_t
            sleep_t = max(0.05, self.interval_sec - elapsed)
            time.sleep(sleep_t)

    def stop(self):
        if not self.running:
            return
        self.running = False
        try:
            # Write graceful stop record
            stop_rec = pack_record(
                magic=MAGIC_STOP,
                seq=self.seq,
                ts=time.time(),
            )
            self._write_and_sync(stop_rec)
        except Exception:
            pass

        if self.fd is not None:
            try:
                os.close(self.fd)
            except Exception:
                pass
            self.fd = None

        if self.lock_fd is not None:
            try:
                import fcntl
                fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
                os.close(self.lock_fd)
            except Exception:
                pass
            self.lock_fd = None

        if self._thread and self._thread.is_alive() and threading.current_thread() != self._thread:
            self._thread.join(timeout=2.0)


def run_standalone():
    print(f"[Power Crash Collector] Starting background monitor...")
    print(f"[Power Crash Collector] Logging to: {DEFAULT_LOG_PATH}")
    collector = CrashCollector()

    def handle_exit(signum, frame):
        print(f"\n[Power Crash Collector] Caught signal {signum}, stopping gracefully...")
        collector.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    collector.start(run_in_background=False)


if __name__ == '__main__':
    run_standalone()
