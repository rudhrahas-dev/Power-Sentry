#!/usr/bin/env python3
"""
Floating System & Power Crash Monitor Widget.
Lightweight Tkinter floating widget with live memory, voltage, and thermal gauges.
Integrates with CrashCollector to ensure zero telemetry loss.
"""

import os
import sys
import time
import subprocess
import tkinter as tk
from tkinter import ttk
from typing import Optional

from collector import CrashCollector, DEFAULT_LOG_PATH
from analyze import TelemetryAnalyzer

BG_DARK = "#151518"
BG_CARD = "#1f1f26"
BG_HEADER = "#282832"
ACCENT_GREEN = "#2ecc71"
ACCENT_BLUE = "#3498db"
ACCENT_YELLOW = "#f1c40f"
ACCENT_RED = "#e74c3c"
ACCENT_CYAN = "#00cec9"
TEXT_WHITE = "#f5f6fa"
TEXT_MUTED = "#8e9297"


class FloatingMonitorWidget:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Power & Memory Health Monitor")
        
        # Dimensions & position
        self.width = 330
        self.height = 360
        self.pill_width = 285
        self.pill_height = 36
        self.is_minimized_to_pill = False
        self.is_always_on_top = True

        # Position at top-right corner of screen
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        start_x = max(20, screen_w - self.width - 40)
        start_y = 60
        self.root.geometry(f"{self.width}x{self.height}+{start_x}+{start_y}")
        self.root.overrideredirect(True)  # Frameless for modern look
        self.root.wm_attributes("-topmost", True)
        self.root.configure(bg=BG_DARK)

        # Variables for window dragging
        self._drag_data = {"x": 0, "y": 0}

        # Initialize Background Collector
        self.collector = CrashCollector(
            log_path=DEFAULT_LOG_PATH,
            interval_sec=1.0,
            sample_callback=self._on_sample_received
        )
        self.latest_sample = {}
        self.records_count = 0
        self.alerts_triggered = 0

        self._build_ui()
        self.collector.start(run_in_background=True)
        self.root.after(1000, self._periodic_ui_update)

    def _build_ui(self):
        # Container
        self.main_frame = tk.Frame(self.root, bg=BG_DARK, highlightthickness=1, highlightbackground="#3d3d4d")
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # Header Bar (Draggable)
        self.header = tk.Frame(self.main_frame, bg=BG_HEADER, height=32)
        self.header.pack(fill=tk.X)
        self.header.pack_propagate(False)

        self.lbl_title = tk.Label(
            self.header,
            text="⚡ POWER & MEMORY SENTRY",
            font=("DejaVu Sans", 9, "bold"),
            bg=BG_HEADER,
            fg=ACCENT_CYAN,
            padx=8
        )
        self.lbl_title.pack(side=tk.LEFT)

        # Header Control Buttons
        btn_close = tk.Label(
            self.header, text="✕", font=("DejaVu Sans", 10), bg=BG_HEADER, fg=TEXT_MUTED, padx=8, cursor="hand2"
        )
        btn_close.pack(side=tk.RIGHT)
        btn_close.bind("<Button-1>", lambda e: self.on_close())
        btn_close.bind("<Enter>", lambda e: btn_close.config(fg=ACCENT_RED))
        btn_close.bind("<Leave>", lambda e: btn_close.config(fg=TEXT_MUTED))

        self.btn_min = tk.Label(
            self.header, text="─", font=("DejaVu Sans", 10, "bold"), bg=BG_HEADER, fg=TEXT_MUTED, padx=8, cursor="hand2"
        )
        self.btn_min.pack(side=tk.RIGHT)
        self.btn_min.bind("<Button-1>", lambda e: self.toggle_minimize_pill())
        self.btn_min.bind("<Enter>", lambda e: self.btn_min.config(fg=TEXT_WHITE))
        self.btn_min.bind("<Leave>", lambda e: self.btn_min.config(fg=TEXT_MUTED))

        self.btn_pin = tk.Label(
            self.header, text="📌", font=("DejaVu Sans", 9), bg=BG_HEADER, fg=ACCENT_CYAN, padx=6, cursor="hand2"
        )
        self.btn_pin.pack(side=tk.RIGHT)
        self.btn_pin.bind("<Button-1>", lambda e: self.toggle_pin())

        # Enable dragging from header and title
        for widget in (self.header, self.lbl_title):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._on_drag)
            widget.bind("<Double-Button-1>", self.reset_position)

        # Global hotkeys to rescue the window if offscreen
        self.root.bind("<Escape>", self.reset_position)
        self.root.bind("<F8>", self.reset_position)
        self.root.bind("<Home>", self.reset_position)
        self.root.bind("<Button-3>", self._show_context_menu)

        # Body Frame
        self.body = tk.Frame(self.main_frame, bg=BG_DARK, padx=12, pady=10)
        self.body.pack(fill=tk.BOTH, expand=True)

        # --- 1. Memory Gauge ---
        lbl_mem_hdr = tk.Label(self.body, text="RAM UTILIZATION", font=("DejaVu Sans", 8, "bold"), bg=BG_DARK, fg=TEXT_MUTED)
        lbl_mem_hdr.pack(anchor=tk.W)

        self.mem_bar_bg = tk.Canvas(self.body, height=12, bg="#2a2a35", highlightthickness=0)
        self.mem_bar_bg.pack(fill=tk.X, pady=(2, 4))
        self.mem_bar_fill = self.mem_bar_bg.create_rectangle(0, 0, 0, 12, fill=ACCENT_GREEN, width=0)

        self.lbl_mem_val = tk.Label(
            self.body,
            text="RAM: Initializing... / 8.0 GB (0%)",
            font=("DejaVu Sans Mono", 8),
            bg=BG_DARK,
            fg=TEXT_WHITE
        )
        self.lbl_mem_val.pack(anchor=tk.W)

        # --- 2. CPU & Temperatures Card ---
        card_thermal = tk.Frame(self.body, bg=BG_CARD, padx=8, pady=6, highlightthickness=1, highlightbackground="#2e2e3a")
        card_thermal.pack(fill=tk.X, pady=8)

        lbl_therm_hdr = tk.Label(card_thermal, text="CPU & THERMAL LOAD", font=("DejaVu Sans", 8, "bold"), bg=BG_CARD, fg=TEXT_MUTED)
        lbl_therm_hdr.pack(anchor=tk.W)

        self.lbl_cpu_load = tk.Label(
            card_thermal,
            text="CPU Load: 0%  |  Package: --°C",
            font=("DejaVu Sans Mono", 8),
            bg=BG_CARD,
            fg=TEXT_WHITE
        )
        self.lbl_cpu_load.pack(anchor=tk.W, pady=(2, 0))

        self.lbl_mb_temps = tk.Label(
            card_thermal,
            text="VRM Temp: --°C  |  PCH: --°C",
            font=("DejaVu Sans Mono", 8),
            bg=BG_CARD,
            fg=TEXT_WHITE
        )
        self.lbl_mb_temps.pack(anchor=tk.W)

        # --- 3. Power Supply Voltages (SMPS & VRM) ---
        card_volt = tk.Frame(self.body, bg=BG_CARD, padx=8, pady=6, highlightthickness=1, highlightbackground="#2e2e3a")
        card_volt.pack(fill=tk.X, pady=(0, 8))

        lbl_volt_hdr = tk.Label(card_volt, text="POWER RAILS (SMPS / VRM HEALTH)", font=("DejaVu Sans", 8, "bold"), bg=BG_CARD, fg=TEXT_MUTED)
        lbl_volt_hdr.pack(anchor=tk.W)

        self.lbl_vcc = tk.Label(
            card_volt,
            text="3.3V ATX Rail: -- V (Nominal: 3.30V)",
            font=("DejaVu Sans Mono", 8),
            bg=BG_CARD,
            fg=ACCENT_YELLOW
        )
        self.lbl_vcc.pack(anchor=tk.W, pady=(2, 0))

        self.lbl_vcore = tk.Label(
            card_volt,
            text="VCore: -- V  |  RAM Rail: -- V",
            font=("DejaVu Sans Mono", 8),
            bg=BG_CARD,
            fg=TEXT_WHITE
        )
        self.lbl_vcore.pack(anchor=tk.W)

        # --- 4. Logging & Disk Sync Status ---
        self.lbl_status = tk.Label(
            self.body,
            text="● SYNCED LOGGING ACTIVE (0 samples)",
            font=("DejaVu Sans", 8, "bold"),
            bg=BG_DARK,
            fg=ACCENT_GREEN
        )
        self.lbl_status.pack(anchor=tk.W, pady=(2, 4))

        # --- 5. Action Buttons ---
        btn_frame = tk.Frame(self.body, bg=BG_DARK)
        btn_frame.pack(fill=tk.X, pady=(4, 0))

        btn_analyze = tk.Button(
            btn_frame,
            text="📊 Analyze Logs",
            font=("DejaVu Sans", 8, "bold"),
            bg="#2c3e50",
            fg=TEXT_WHITE,
            activebackground="#34495e",
            activeforeground=TEXT_WHITE,
            relief=tk.FLAT,
            padx=8,
            pady=3,
            cursor="hand2",
            command=self.open_analysis_window
        )
        btn_analyze.pack(side=tk.LEFT)

        btn_hide = tk.Button(
            btn_frame,
            text="Minimize to Pill",
            font=("DejaVu Sans", 8),
            bg="#24242d",
            fg=TEXT_MUTED,
            activebackground="#30303b",
            activeforeground=TEXT_WHITE,
            relief=tk.FLAT,
            padx=8,
            pady=3,
            cursor="hand2",
            command=self.toggle_minimize_pill
        )
        btn_hide.pack(side=tk.RIGHT)

        # Mini Pill Widget (hidden by default)
        self.pill_frame = tk.Frame(self.root, bg=BG_HEADER, highlightthickness=1, highlightbackground=ACCENT_CYAN)
        self.lbl_pill_text = tk.Label(
            self.pill_frame,
            text="⚡ RAM: --% | --°C | --V",
            font=("DejaVu Sans Mono", 8, "bold"),
            bg=BG_HEADER,
            fg=TEXT_WHITE,
            padx=8,
            cursor="hand2"
        )
        self.lbl_pill_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.lbl_pill_text.bind("<ButtonPress-1>", self._start_drag_pill)
        self.lbl_pill_text.bind("<B1-Motion>", self._on_drag_pill)
        self.lbl_pill_text.bind("<ButtonRelease-1>", self._on_release_pill)
        self.lbl_pill_text.bind("<Double-Button-1>", lambda e: self.toggle_minimize_pill())
        self.lbl_pill_text.bind("<Button-3>", self._show_context_menu)
        self.pill_frame.bind("<Button-3>", self._show_context_menu)

        self.btn_pill_restore = tk.Label(
            self.pill_frame,
            text=" ⤢ Expand ",
            font=("DejaVu Sans", 8, "bold"),
            bg="#2c3e50",
            fg=ACCENT_CYAN,
            padx=4,
            pady=2,
            cursor="hand2",
            relief=tk.FLAT
        )
        self.btn_pill_restore.pack(side=tk.RIGHT, padx=4, pady=3)
        self.btn_pill_restore.bind("<Button-1>", lambda e: self.toggle_minimize_pill())
        self.btn_pill_restore.bind("<Enter>", lambda e: self.btn_pill_restore.config(bg="#34495e", fg=TEXT_WHITE))
        self.btn_pill_restore.bind("<Leave>", lambda e: self.btn_pill_restore.config(bg="#2c3e50", fg=ACCENT_CYAN))

    def _clamp_position(self, x: int, y: int, width: int, height: int):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        # Ubuntu GNOME top bar is ~32px. Keep window strictly below it.
        top_bar_margin = 36
        bottom_margin = 10
        clamped_x = max(5, min(x, sw - width - 5))
        clamped_y = max(top_bar_margin, min(y, sh - height - bottom_margin))
        return clamped_x, clamped_y

    def reset_position(self, event=None):
        """Reset window to a safe, visible top-right position below the top bar."""
        sw = self.root.winfo_screenwidth()
        w = self.pill_width if self.is_minimized_to_pill else self.width
        h = self.pill_height if self.is_minimized_to_pill else self.height
        safe_x = max(10, sw - w - 25)
        safe_y = 45
        self.root.geometry(f"{w}x{h}+{safe_x}+{safe_y}")

    def _show_context_menu(self, event):
        """Context menu available on right-click anywhere."""
        menu = tk.Menu(self.root, tearoff=0, bg=BG_HEADER, fg=TEXT_WHITE, activebackground="#34495e", activeforeground=ACCENT_CYAN)
        if self.is_minimized_to_pill:
            menu.add_command(label="⤢ Expand to Full View", command=self.toggle_minimize_pill)
        else:
            menu.add_command(label="─ Minimize to Pill", command=self.toggle_minimize_pill)
        menu.add_command(label="🎯 Reset Position (Top-Right)", command=self.reset_position)
        menu.add_command(label="📌 Toggle Always-on-Top", command=self.toggle_pin)
        menu.add_separator()
        menu.add_command(label="📊 View Analysis Report", command=self.open_analysis_window)
        menu.add_command(label="✕ Close Monitor", command=self.on_close)
        menu.tk_popup(event.x_root, event.y_root)

    def _start_drag(self, event):
        self._drag_data["x"] = event.x_root - self.root.winfo_x()
        self._drag_data["y"] = event.y_root - self.root.winfo_y()

    def _on_drag(self, event):
        new_x = event.x_root - self._drag_data["x"]
        new_y = event.y_root - self._drag_data["y"]
        cx, cy = self._clamp_position(new_x, new_y, self.width, self.height)
        self.root.geometry(f"+{cx}+{cy}")

    def _start_drag_pill(self, event):
        self._drag_data["x"] = event.x_root - self.root.winfo_x()
        self._drag_data["y"] = event.y_root - self.root.winfo_y()
        self._drag_data["start_x"] = event.x_root
        self._drag_data["start_y"] = event.y_root
        self._drag_data["moved"] = False

    def _on_drag_pill(self, event):
        if abs(event.x_root - self._drag_data.get("start_x", 0)) > 3 or abs(event.y_root - self._drag_data.get("start_y", 0)) > 3:
            self._drag_data["moved"] = True
        new_x = event.x_root - self._drag_data["x"]
        new_y = event.y_root - self._drag_data["y"]
        cx, cy = self._clamp_position(new_x, new_y, self.pill_width, self.pill_height)
        self.root.geometry(f"+{cx}+{cy}")

    def _on_release_pill(self, event):
        # If clicked without dragging, restore full view immediately!
        if not self._drag_data.get("moved", False):
            self.toggle_minimize_pill()

    def toggle_pin(self):
        self.is_always_on_top = not self.is_always_on_top
        self.root.wm_attributes("-topmost", self.is_always_on_top)
        self.btn_pin.config(fg=ACCENT_CYAN if self.is_always_on_top else TEXT_MUTED)

    def toggle_minimize_pill(self):
        cur_x = self.root.winfo_x()
        cur_y = self.root.winfo_y()
        if not self.is_minimized_to_pill:
            self.is_minimized_to_pill = True
            self.main_frame.pack_forget()
            self.pill_frame.pack(fill=tk.BOTH, expand=True)
            cx, cy = self._clamp_position(cur_x, cur_y, self.pill_width, self.pill_height)
            self.root.geometry(f"{self.pill_width}x{self.pill_height}+{cx}+{cy}")
        else:
            self.is_minimized_to_pill = False
            self.pill_frame.pack_forget()
            self.main_frame.pack(fill=tk.BOTH, expand=True)
            cx, cy = self._clamp_position(cur_x, cur_y, self.width, self.height)
            self.root.geometry(f"{self.width}x{self.height}+{cx}+{cy}")

    def _on_sample_received(self, data: dict):
        self.latest_sample = data
        self.records_count = self.collector.records_written

    def _periodic_ui_update(self):
        if self.latest_sample:
            s = self.latest_sample
            m_used = s.get('mem_used_mb', 0)
            m_tot = s.get('mem_total_mb', 1)
            pct = int((m_used / max(1, m_tot)) * 100)

            cpu_pct = s.get('cpu_pct', 0)
            pkg_t = s.get('temp_cpu_pkg', 0)
            vrm_t = s.get('temp_vrm', 0)
            pch_t = s.get('temp_pch', 0)
            v_vcc = s.get('v_vcc_mv', 0) / 1000.0
            v_in0 = s.get('v_in0_mv', 0) / 1000.0
            v_in3 = s.get('v_in3_mv', 0) / 1000.0
            dirty = s.get('dirty_mb', 0)

            # Update RAM bar
            bar_color = ACCENT_GREEN
            if pct > 90:
                bar_color = ACCENT_RED
            elif pct > 75:
                bar_color = ACCENT_YELLOW

            canvas_w = self.mem_bar_bg.winfo_width()
            fill_w = int((pct / 100.0) * max(1, canvas_w))
            self.mem_bar_bg.coords(self.mem_bar_fill, 0, 0, fill_w, 12)
            self.mem_bar_bg.itemconfig(self.mem_bar_fill, fill=bar_color)

            self.lbl_mem_val.config(
                text=f"RAM: {m_used/1024:.1f} / {m_tot/1024:.1f} GB ({pct}%) | Dirty: {dirty}MB"
            )

            # Update CPU & Temps
            cpu_color = TEXT_WHITE
            if pkg_t > 78 or vrm_t > 72:
                cpu_color = ACCENT_RED
            elif pkg_t > 65:
                cpu_color = ACCENT_YELLOW
            self.lbl_cpu_load.config(
                text=f"CPU: {cpu_pct}%  |  Package: {pkg_t}°C",
                fg=cpu_color
            )
            self.lbl_mb_temps.config(
                text=f"VRM: {vrm_t}°C  |  PCH: {pch_t}°C"
            )

            # Update Voltages
            vcc_color = ACCENT_YELLOW
            if v_vcc < 3.14:  # Voltage sag danger zone!
                vcc_color = ACCENT_RED
                vcc_text = f"3.3V ATX Rail: {v_vcc:.2f}V ⚠ UNDER-VOLTAGE!"
            else:
                vcc_text = f"3.3V ATX Rail: {v_vcc:.3f}V (Normal)"

            self.lbl_vcc.config(text=vcc_text, fg=vcc_color)
            self.lbl_vcore.config(text=f"VCore: {v_in0:.3f}V  |  RAM: {v_in3:.3f}V")

            # Update Status
            self.lbl_status.config(
                text=f"● COMMITTED: {self.records_count:,} samples ({self.records_count*64//1024} KB)"
            )

            # Mini Pill text
            self.lbl_pill_text.config(
                text=f"⚡ RAM: {pct}% | CPU: {pkg_t}°C | 3.3V: {v_vcc:.2f}V"
            )

        self.root.after(1000, self._periodic_ui_update)

    def open_analysis_window(self):
        """Open a detailed telemetry report window."""
        win = tk.Toplevel(self.root)
        win.title("Hardware Crash & Telemetry Inspection")
        win.geometry("620x450")
        win.configure(bg=BG_DARK)
        win.wm_attributes("-topmost", True)

        txt = tk.Text(win, bg="#111116", fg=TEXT_WHITE, font=("DejaVu Sans Mono", 9), padx=10, pady=10)
        txt.pack(fill=tk.BOTH, expand=True)

        analyzer = TelemetryAnalyzer(DEFAULT_LOG_PATH)
        if analyzer.parse():
            import io
            from contextlib import redirect_stdout
            f = io.StringIO()
            with redirect_stdout(f):
                analyzer.report()
            txt.insert(tk.END, f.getvalue())
        else:
            txt.insert(tk.END, "Log file is currently empty or starting up.\nPlease check back after a few minutes of logging.")
        txt.config(state=tk.DISABLED)

    def on_close(self):
        self.collector.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = FloatingMonitorWidget(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == '__main__':
    main()
