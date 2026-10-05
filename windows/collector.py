"""
Power and Memory Crash Collector Daemon (Windows 10 Edition).
Collects hardware & laptop battery telemetry every second and commits to disk
immediately using FlushFileBuffers / fsync to ensure zero telemetry loss during power cuts.
"""

import os
import sys
import time
import signal
import threading
import ctypes
from typing import Optional, Callable

from record_format import (
    pack_record,
    MAGIC_SAMPLE,
    MAGIC_START,
    MAGIC_STOP,
    RECORD_SIZE,
)
from sensors import WindowsHardwareSensors

DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
DEFAULT_LOG_PATH = os.path.join(DEFAULT_DATA_DIR, 'metrics.bin')


class WindowsCrashCollector:
    def __init__(
        self,
        log_path: str = DEFAULT_LOG_PATH,
        interval_sec: float = 1.0,
        sample_callback: Optional[Callable[[dict], None]] = None,
    ):
        self.log_path = log_path
        self.interval_sec = interval_sec
        self.sample_callback = sample_callback
        self.sensors = WindowsHardwareSensors()
        self.running = False
        self.seq = 0
        self.fd: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self.records_written = 0
        self.last_sample_data: dict = {}

        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        self.lock_path = os.path.join(os.path.dirname(self.log_path), 'collector.lock')
        self.lock_file = None
        self.is_writer = True

    def _acquire_lock(self) -> bool:
        """Cross-platform non-blocking file lock."""
        if os.name == 'nt':
            try:
                import msvcrt
                # Open or create lock file and lock first byte non-blocking
                self.lock_file = open(self.lock_path, 'a+')
                msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                self.is_writer = True
                return True
            except (IOError, OSError):
                if self.lock_file:
                    try:
                        self.lock_file.close()
                    except Exception:
                        pass
                    self.lock_file = None
                self.is_writer = False
                return False
        else:
            import fcntl
            try:
                self.lock_file = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o644)
                fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.is_writer = True
                return True
            except (IOError, BlockingIOError):
                self.is_writer = False
                return False

    def _open_file(self):
        if not self._acquire_lock():
            return
        # Open in append binary mode
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        if hasattr(os, 'O_BINARY'):
            flags |= os.O_BINARY

        self.fd = os.open(self.log_path, flags, 0o644)

    def _write_and_sync(self, raw_bytes: bytes):
        if self.is_writer and self.fd is not None:
            os.write(self.fd, raw_bytes)
            
            # CRITICAL FOR CRASH SURVIVAL:
            # 1. Flush Python / C runtime buffers
            if hasattr(os, 'fdatasync'):
                try:
                    os.fdatasync(self.fd)
                except Exception:
                    os.fsync(self.fd)
            else:
                os.fsync(self.fd)

            # 2. Windows: Flush physical storage controller write caches
            if os.name == 'nt':
                try:
                    import msvcrt
                    win_handle = msvcrt.get_osfhandle(self.fd)
                    ctypes.windll.kernel32.FlushFileBuffers(win_handle)
                except Exception:
                    pass

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
            except Exception:
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

        if self.lock_file is not None:
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                    self.lock_file.close()
                else:
                    import fcntl
                    fcntl.flock(self.lock_file, fcntl.LOCK_UN)
                    os.close(self.lock_file)
            except Exception:
                pass
            self.lock_file = None

        if self._thread and self._thread.is_alive() and threading.current_thread() != self._thread:
            self._thread.join(timeout=2.0)


def run_standalone():
    print(f"[Power & Memory Sentry - Windows Edition]")
    print(f"[*] Logging to: {DEFAULT_LOG_PATH}")
    collector = WindowsCrashCollector()

    def handle_exit(signum=None, frame=None):
        print(f"\n[*] Stopping collector gracefully...")
        collector.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, handle_exit)

    # Windows Console Ctrl Handler
    if os.name == 'nt':
        try:
            HANDLER_ROUTINE = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_ulong)
            def ctrl_handler(ctrl_type):
                handle_exit()
                return True
            global _win_handler
            _win_handler = HANDLER_ROUTINE(ctrl_handler)
            ctypes.windll.kernel32.SetConsoleCtrlHandler(_win_handler, True)
        except Exception:
            pass

    collector.start(run_in_background=False)


if __name__ == '__main__':
    run_standalone()
