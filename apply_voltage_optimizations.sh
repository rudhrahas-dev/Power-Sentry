#!/usr/bin/env bash
#
# Power Sentry - System Voltage Stabilization Setup Script
# Installs kernel dirty-memory smoothing rules and CPU power management permissions.
#

set -e

if [ "$(id -u)" -ne 0 ]; then
    echo "[-] This script requires root privileges to apply kernel sysctl rules."
    echo "[*] Please run with: sudo $0"
    exit 1
fi

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
CONF_FILE="$DIR/99-power-sentry.conf"

echo "[*] 1. Installing kernel sysctl rules to /etc/sysctl.d/99-power-sentry.conf..."
cp "$CONF_FILE" /etc/sysctl.d/99-power-sentry.conf
chmod 644 /etc/sysctl.d/99-power-sentry.conf

echo "[*] 2. Activating sysctl parameters immediately..."
sysctl -p /etc/sysctl.d/99-power-sentry.conf

echo "[*] 3. Configuring CPU frequency scaling permissions for real-time stabilization..."
# Make scaling_max_freq writable by logged-in users so widget can clamp transients without passwords
cat << "EOF" > /etc/udev/rules.d/99-power-sentry-cpufreq.rules
SUBSYSTEM=="cpu", KERNEL=="cpu*", ACTION=="add", ATTR{cpufreq/scaling_max_freq}="3400000", RUN+="/bin/chmod 0666 /sys/devices/system/cpu/cpu*/cpufreq/scaling_max_freq"
EOF

# Apply immediate permissions across all current CPU cores
chmod 0666 /sys/devices/system/cpu/cpu*/cpufreq/scaling_max_freq 2>/dev/null || true

echo ""
echo "==========================================================================="
echo " [✓] SUCCESS: Voltage Stabilization Profile Installed & Activated!"
echo "     - vm.dirty_background_bytes = 32 MB (Continuous smooth disk writeback)"
echo "     - vm.dirty_bytes            = 64 MB (Hard cap on dirty buffer spikes)"
echo "     - vm.swappiness             = 10    (Swap storm prevention)"
echo "     - CPU Frequency Clamping    = Permissions granted for 0ms watchdog"
echo "==========================================================================="
