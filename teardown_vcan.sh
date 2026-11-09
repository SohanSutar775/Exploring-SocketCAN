#!/usr/bin/env bash
# Remove the virtual CAN interface. Usage: sudo ./teardown_vcan.sh [iface]
IFACE="${1:-vcan0}"
ip link set "$IFACE" down 2>/dev/null || true
ip link delete "$IFACE" 2>/dev/null || true
echo "$IFACE removed"
