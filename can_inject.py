#!/usr/bin/env python3
"""
can_inject.py - send arbitrary frames (Challenge 3: unknown message; extended IDs; CAN FD).

Examples
  ./can_inject.py --id 0x3A0 --data DEADBEEF                  # unknown standard frame
  ./can_inject.py --id 0x3A0 --data 0102 --count 20 --period-ms 100
  ./can_inject.py --id 0x18FEF100 --extended --data 1122334455667788   # 29-bit ID
  ./can_inject.py --id 0x3B0 --fd --data 00112233445566778899AABB      # 12-byte CAN FD
"""
import argparse
import time

from can_common import open_can_socket, send_frame


def main():
    ap = argparse.ArgumentParser(description="Inject a CAN / CAN FD frame")
    ap.add_argument("--iface", default="vcan0")
    ap.add_argument("--id", required=True, help="CAN id, e.g. 0x3A0")
    ap.add_argument("--data", default="", help="payload as hex string, e.g. DEADBEEF")
    ap.add_argument("--extended", action="store_true", help="use 29-bit extended identifier")
    ap.add_argument("--fd", action="store_true", help="send as CAN FD frame")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--period-ms", type=float, default=100)
    args = ap.parse_args()

    sock = open_can_socket(args.iface, fd=args.fd)
    payload = bytes.fromhex(args.data)
    can_id = int(args.id, 0)
    for i in range(args.count):
        send_frame(sock, can_id, payload, fd=args.fd, extended=args.extended)
        if i + 1 < args.count:
            time.sleep(args.period_ms / 1000.0)
    print("sent %d frame(s): id=0x%X %s len=%d" %
          (args.count, can_id, "EXT" if args.extended else "STD", len(payload)))


if __name__ == "__main__":
    main()
