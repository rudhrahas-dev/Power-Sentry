"""
Zero-overhead hardware sensor reader for Linux.
Reads directly from /sys/class/hwmon, /proc/meminfo, /proc/stat, /proc/pressure
and libnvidia-ml.so without spawning any subprocesses.
"""

import os
import glob
import ctypes
from typing import Dict, Any, Tuple


class HardwareSensors:
    def __init__(self):
        self.last_cpu_idle = 0
        self.last_cpu_total = 0
        self.hwmon_devices: Dict[str, str] = {}
        self._discover_hwmon()
        self._init_nvml()

    def _discover_hwmon(self):
        """Map hwmon driver names to their sysfs directory paths."""
        self.hwmon_devices.clear()
        for dev_path in glob.glob('/sys/class/hwmon/hwmon*'):
            name_file = os.path.join(dev_path, 'name')
            if os.path.exists(name_file):
                try:
                    with open(name_file, 'r', encoding='utf-8') as f:
                        name = f.read().strip()
                        self.hwmon_devices[name] = dev_path
                except Exception:
                    pass

    def _init_nvml(self):
        """Optional initialization of NVML via ctypes for low-latency GPU telemetry."""
        self.nvml = None
        self.nvml_handle = None
        try:
            self.nvml = ctypes.CDLL('libnvidia-ml.so.1')
            if self.nvml.nvmlInit_v2() == 0:
                handle = ctypes.c_void_p()
                if self.nvml.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(handle)) == 0:
                    self.nvml_handle = handle
        except Exception:
            self.nvml = None
            self.nvml_handle = None

    @staticmethod
    def _read_int(path: str, default: int = 0) -> int:
        try:
            with open(path, 'r', encoding='ascii') as f:
                return int(f.read().strip())
        except Exception:
            return default

    def read_meminfo(self) -> Dict[str, int]:
        """Read /proc/meminfo in a single pass."""
        mem = {}
        try:
            with open('/proc/meminfo', 'r', encoding='ascii') as f:
                for line in f:
                    parts = line.split(':')
                    if len(parts) == 2:
                        k = parts[0].strip()
                        val_str = parts[1].strip().split()[0]
                        mem[k] = int(val_str) // 1024  # convert kB to MB
        except Exception:
            pass

        total = mem.get('MemTotal', 0)
        avail = mem.get('MemAvailable', 0)
        used = max(0, total - avail)
        swap_total = mem.get('SwapTotal', 0)
        swap_free = mem.get('SwapFree', 0)
        swap_used = max(0, swap_total - swap_free)
        dirty = mem.get('Dirty', 0)
        committed = mem.get('Committed_AS', 0)

        return {
            'total': total,
            'used': used,
            'avail': avail,
            'swap_used': swap_used,
            'dirty': dirty,
            'committed': committed,
        }

    def read_psi_memory(self) -> Tuple[int, int]:
        """Read Memory Pressure Stall Information (some avg10 * 100, full avg10 * 100)."""
        some_10 = 0
        full_10 = 0
        try:
            with open('/proc/pressure/memory', 'r', encoding='ascii') as f:
                for line in f:
                    if line.startswith('some'):
                        for part in line.split():
                            if part.startswith('avg10='):
                                some_10 = int(float(part.split('=')[1]) * 100)
                    elif line.startswith('full'):
                        for part in line.split():
                            if part.startswith('avg10='):
                                full_10 = int(float(part.split('=')[1]) * 100)
        except Exception:
            pass
        return some_10, full_10

    def read_cpu_load(self) -> int:
        """Calculate overall CPU utilization percentage (0-100) using /proc/stat delta."""
        try:
            with open('/proc/stat', 'r', encoding='ascii') as f:
                line = f.readline()
                if line.startswith('cpu '):
                    fields = [int(x) for x in line.split()[1:]]
                    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
                    total = sum(fields)
                    
                    diff_idle = idle - self.last_cpu_idle
                    diff_total = total - self.last_cpu_total
                    self.last_cpu_idle = idle
                    self.last_cpu_total = total
                    
                    if diff_total > 0:
                        pct = int(100.0 * (1.0 - (diff_idle / diff_total)))
                        return max(0, min(100, pct))
        except Exception:
            pass
        return 0

    def read_load1(self) -> int:
        """Read 1m load average * 100 from /proc/loadavg."""
        try:
            with open('/proc/loadavg', 'r', encoding='ascii') as f:
                val = float(f.read().split()[0])
                return int(val * 100)
        except Exception:
            return 0

    def sample(self) -> Dict[str, Any]:
        """Collect a complete snapshot of system metrics."""
        mem = self.read_meminfo()
        psi_some_10, psi_full_10 = self.read_psi_memory()
        cpu_pct = self.read_cpu_load()
        load1_x100 = self.read_load1()

        # hwmon devices
        core_dir = self.hwmon_devices.get('coretemp')
        nct_dir = self.hwmon_devices.get('nct6683')

        temp_pkg = 0
        temp_max_core = 0
        if core_dir:
            temp_pkg = self._read_int(f'{core_dir}/temp1_input') // 1000
            for i in range(2, 6):
                c_temp = self._read_int(f'{core_dir}/temp{i}_input') // 1000
                if c_temp > temp_max_core:
                    temp_max_core = c_temp

        temp_pch = 0
        temp_vrm = 0
        fan_cpu = 0
        fan_sys = 0
        v_vcc = 0
        v_vsb = 0
        v_in0 = 0
        v_in1 = 0
        v_in3 = 0
        v_in7 = 0
        v_in14 = 0

        if nct_dir:
            # Temperatures
            temp_pch = self._read_int(f'{nct_dir}/temp2_input') // 1000
            temp_vrm = self._read_int(f'{nct_dir}/temp3_input') // 1000
            
            # Fans
            fan_cpu = self._read_int(f'{nct_dir}/fan1_input')
            fan_sys = self._read_int(f'{nct_dir}/fan3_input')
            
            # Voltages (in millivolts)
            v_in0 = self._read_int(f'{nct_dir}/in0_input')   # VCore / VIN0
            v_in1 = self._read_int(f'{nct_dir}/in1_input')   # VIN1
            v_vcc = self._read_int(f'{nct_dir}/in2_input')   # VCC 3.3V
            v_vsb = self._read_int(f'{nct_dir}/in3_input')   # VSB 3.3V standby
            v_in14 = self._read_int(f'{nct_dir}/in4_input')  # VIN14
            v_in3 = self._read_int(f'{nct_dir}/in5_input')   # VIN3 (RAM / VTT)
            v_in7 = self._read_int(f'{nct_dir}/in6_input')   # VIN7

        # GPU metrics
        temp_gpu = 0
        gpu_pwr_w_x10 = 0
        gpu_mem_mb = 0

        if self.nvml_handle:
            try:
                t = ctypes.c_uint()
                p = ctypes.c_uint()
                if self.nvml.nvmlDeviceGetTemperature(self.nvml_handle, 0, ctypes.byref(t)) == 0:
                    temp_gpu = t.value
                if self.nvml.nvmlDeviceGetPowerUsage(self.nvml_handle, ctypes.byref(p)) == 0:
                    gpu_pwr_w_x10 = p.value // 100  # mW to W*10
            except Exception:
                pass

        return {
            'mem_total_mb': mem['total'],
            'mem_used_mb': mem['used'],
            'mem_avail_mb': mem['avail'],
            'swap_used_mb': mem['swap_used'],
            'dirty_mb': mem['dirty'],
            'committed_mb': mem['committed'],
            'psi_some_10': psi_some_10,
            'psi_full_10': psi_full_10,
            'cpu_pct': cpu_pct,
            'load1_x100': load1_x100,
            'temp_cpu_pkg': temp_pkg,
            'temp_cpu_max_core': temp_max_core,
            'temp_pch': temp_pch,
            'temp_vrm': temp_vrm,
            'temp_gpu': temp_gpu,
            'gpu_pwr_w_x10': gpu_pwr_w_x10,
            'gpu_mem_mb': gpu_mem_mb,
            'fan_cpu_rpm': fan_cpu,
            'fan_sys_rpm': fan_sys,
            'v_vcc_mv': v_vcc,
            'v_vsb_mv': v_vsb,
            'v_in0_mv': v_in0,
            'v_in1_mv': v_in1,
            'v_in3_mv': v_in3,
            'v_in7_mv': v_in7,
            'v_in14_mv': v_in14,
        }
