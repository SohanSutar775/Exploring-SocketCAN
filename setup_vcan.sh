#!/usr/bin/env bash
# Create a virtual CAN interface (software-only CAN bus). Needs root.
# Usage: sudo ./setup_vcan.sh [iface]
set -euo pipefail
IFACE="${1:-vcan0}"
modprobe can
modprobe can_raw
modprobe vcan
ip link show "$IFACE" >/dev/null 2>&1 || ip link add dev "$IFACE" type vcan
ip link set "$IFACE" mtu 72        # 72 = CAN FD capable (classic CAN uses 16)
ip link set up "$IFACE"
echo "--- $IFACE is up ---"
ip -details link show "$IFACE"
