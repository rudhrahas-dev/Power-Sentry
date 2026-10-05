"""
Record format for Power & Memory Crash Telemetry (Windows & Cross-Platform).
Uses a 64-byte compact binary struct.
Guaranteed exact byte alignment, minimal CPU and disk footprint.
Supports Laptop Battery & AC Power telemetry in reserved fields.
"""

import struct
import time
from typing import Dict, Any, Optional

# 64-byte binary record layout
# Format:
# Byte 0: Magic (0xAA = sample, 0xFF = session start, 0xFE = clean stop)
# Byte 1: Format Version (1)
# Bytes 2-5: Sequence number (uint32)
# Bytes 6-9: Unix epoch timestamp (uint32)
# Bytes 10-11: Millisecond offset (uint16, 0-999)
# Bytes 12-13: Mem total MB (uint16)
# Bytes 14-15: Mem used MB (uint16)
# Bytes 16-17: Mem available MB (uint16)
# Bytes 18-19: Swap/Pagefile used MB (uint16)
# Bytes 20-21: Dirty/Modified pages MB (uint16)
# Bytes 22-23: Committed memory MB (uint16)
# Bytes 24-25: Memory PSI some avg10 * 100 (uint16)
# Bytes 26-27: Memory PSI full avg10 * 100 (uint16)
# Byte 28: CPU utilization % (uint8, 0-100)
# Bytes 29-30: Load average 1m * 100 (uint16)
# Byte 31: CPU Package temp C (int8)
# Byte 32: CPU Max Core temp C (int8)
# Byte 33: PCH / Chipset temp C (int8)
# Byte 34: VRM / Motherboard temp C (int8)
# Byte 35: GPU temp C (int8)
# Bytes 36-37: GPU power Watts * 10 (uint16)
# Bytes 38-39: GPU memory used MB (uint16)
# Bytes 40-41: CPU Fan RPM (uint16)
# Bytes 42-43: System / Chassis Fan RPM (uint16)
# Bytes 44-45: VCC 3.3V rail mV (uint16)
# Bytes 46-47: VSB 3.3V standby mV (uint16)
# Bytes 48-49: VCore / VIN0 mV (uint16)
# Bytes 50-51: VIN1 mV (uint16)
# Bytes 52-53: RAM / VIN3 mV (uint16)
# Bytes 54-55: VIN7 mV (uint16)
# Bytes 56-57: VIN14 mV (uint16)
# Bytes 58-59: Laptop Battery Status (uint16: bits 0-7=pct, bit 8=AC online, bit 9=charging, bit 10=battery present)
# Bytes 60-61: Laptop Battery Remaining Minutes (uint16)
# Bytes 62-63: Checksum (uint16, sum of previous 62 bytes mod 65536)

STRUCT_FMT = '<BBIIHHHHHHHHHBHbbbbbHHHHHHHHHHHHHH'
RECORD_SIZE = 64
FORMAT_VERSION = 1

MAGIC_SAMPLE = 0xAA
MAGIC_START = 0xFF
MAGIC_STOP = 0xFE

assert struct.calcsize(STRUCT_FMT) == RECORD_SIZE, f"Struct size is {struct.calcsize(STRUCT_FMT)}, expected 64"


def calculate_checksum(buffer: bytes) -> int:
    """Calculate 16-bit checksum over the first 62 bytes."""
    return sum(buffer[:62]) & 0xFFFF


def pack_record(
    magic: int,
    seq: int,
    ts: float,
    mem_total_mb: int = 0,
    mem_used_mb: int = 0,
    mem_avail_mb: int = 0,
    swap_used_mb: int = 0,
    dirty_mb: int = 0,
    committed_mb: int = 0,
    psi_some_10: int = 0,
    psi_full_10: int = 0,
    cpu_pct: int = 0,
    load1_x100: int = 0,
    temp_cpu_pkg: int = 0,
    temp_cpu_max_core: int = 0,
    temp_pch: int = 0,
    temp_vrm: int = 0,
    temp_gpu: int = 0,
    gpu_pwr_w_x10: int = 0,
    gpu_mem_mb: int = 0,
    fan_cpu_rpm: int = 0,
    fan_sys_rpm: int = 0,
    v_vcc_mv: int = 0,
    v_vsb_mv: int = 0,
    v_in0_mv: int = 0,
    v_in1_mv: int = 0,
    v_in3_mv: int = 0,
    v_in7_mv: int = 0,
    v_in14_mv: int = 0,
    reserved1: int = 0,
    reserved2: int = 0,
    # Laptop specific helpers
    battery_pct: int = 0,
    ac_online: bool = True,
    is_charging: bool = False,
    battery_present: bool = False,
    battery_time_mins: int = 0,
) -> bytes:
    epoch_sec = int(ts)
    ms_offset = int((ts - epoch_sec) * 1000) & 0xFFFF

    # Encode laptop battery if provided and reserved1 was not manually set
    if reserved1 == 0 and (battery_present or battery_pct > 0 or not ac_online):
        reserved1 = (
            (int(battery_pct) & 0xFF) |
            ((1 if ac_online else 0) << 8) |
            ((1 if is_charging else 0) << 9) |
            ((1 if battery_present else 0) << 10)
        )
    if reserved2 == 0 and battery_time_mins > 0:
        reserved2 = min(65535, int(battery_time_mins))

    # Clamp fields to avoid pack overflow
    def u16(x): return max(0, min(65535, int(x)))
    def u8(x): return max(0, min(255, int(x)))
    def i8(x): return max(-128, min(127, int(x)))

    temp_buf = struct.pack(
        STRUCT_FMT,
        magic,
        FORMAT_VERSION,
        seq & 0xFFFFFFFF,
        epoch_sec & 0xFFFFFFFF,
        ms_offset,
        u16(mem_total_mb),
        u16(mem_used_mb),
        u16(mem_avail_mb),
        u16(swap_used_mb),
        u16(dirty_mb),
        u16(committed_mb),
        u16(psi_some_10),
        u16(psi_full_10),
        u8(cpu_pct),
        u16(load1_x100),
        i8(temp_cpu_pkg),
        i8(temp_cpu_max_core),
        i8(temp_pch),
        i8(temp_vrm),
        i8(temp_gpu),
        u16(gpu_pwr_w_x10),
        u16(gpu_mem_mb),
        u16(fan_cpu_rpm),
        u16(fan_sys_rpm),
        u16(v_vcc_mv),
        u16(v_vsb_mv),
        u16(v_in0_mv),
        u16(v_in1_mv),
        u16(v_in3_mv),
        u16(v_in7_mv),
        u16(v_in14_mv),
        u16(reserved1),
        u16(reserved2),
        0  # Temporary checksum placeholder
    )

    csum = calculate_checksum(temp_buf)
    # Re-pack with final checksum
    return temp_buf[:62] + struct.pack('<H', csum)


def unpack_record(buffer: bytes) -> Optional[Dict[str, Any]]:
    if len(buffer) != RECORD_SIZE:
        return None

    expected_csum = struct.unpack('<H', buffer[62:64])[0]
    actual_csum = calculate_checksum(buffer)
    if expected_csum != actual_csum:
        return None

    fields = struct.unpack(STRUCT_FMT, buffer)

    res1 = fields[31]
    res2 = fields[32]

    # Decode laptop battery from reserved fields if present
    battery_present = bool(res1 & (1 << 10))
    battery_pct = res1 & 0xFF if (battery_present or (res1 != 0)) else 0
    ac_online = bool(res1 & (1 << 8)) if (battery_present or (res1 != 0)) else True
    is_charging = bool(res1 & (1 << 9)) if (battery_present or (res1 != 0)) else False
    battery_time_mins = res2 if (battery_present or (res1 != 0)) else 0

    return {
        'magic': fields[0],
        'version': fields[1],
        'seq': fields[2],
        'timestamp': fields[3] + (fields[4] / 1000.0),
        'mem_total_mb': fields[5],
        'mem_used_mb': fields[6],
        'mem_avail_mb': fields[7],
        'swap_used_mb': fields[8],
        'dirty_mb': fields[9],
        'committed_mb': fields[10],
        'psi_some_10': fields[11] / 100.0,
        'psi_full_10': fields[12] / 100.0,
        'cpu_pct': fields[13],
        'load1': fields[14] / 100.0,
        'temp_cpu_pkg': fields[15],
        'temp_cpu_max_core': fields[16],
        'temp_pch': fields[17],
        'temp_vrm': fields[18],
        'temp_gpu': fields[19],
        'gpu_pwr_w': fields[20] / 10.0,
        'gpu_mem_mb': fields[21],
        'fan_cpu_rpm': fields[22],
        'fan_sys_rpm': fields[23],
        'v_vcc_mv': fields[24],
        'v_vsb_mv': fields[25],
        'v_in0_mv': fields[26],
        'v_in1_mv': fields[27],
        'v_in3_mv': fields[28],
        'v_in7_mv': fields[29],
        'v_in14_mv': fields[30],
        'reserved1': res1,
        'reserved2': res2,
        'checksum': fields[33],
        # Decoded laptop fields
        'battery_pct': battery_pct,
        'ac_online': ac_online,
        'is_charging': is_charging,
        'battery_present': battery_present,
        'battery_time_mins': battery_time_mins,
    }
