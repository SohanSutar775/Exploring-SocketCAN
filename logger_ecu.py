#!/usr/bin/env python3
"""
Logger ECU - records ALL observed CAN / CAN FD traffic to a CSV file.

CSV columns
  timestamp   local time, ISO-8601 with microseconds
  epoch       seconds since 1970 (6 decimals) - used by analyze_log.py
  can_id      identifier in hex (e.g. 0x100)
  id_type     STD (11-bit) or EXT (29-bit)
  frame_type  CAN or CAN_FD
  length      payload length in bytes
  data_hex    payload bytes in hex

The logger never transmits, so it cannot disturb the other nodes. It also reports when the
bus goes silent (Challenge 5) and prints throughput / file-size statistics (Challenge 4).

Examples
  ./logger_ecu.py                       # -> can_log.csv
  ./logger_ecu.py --out run1.csv --fd
"""
import argparse
import csv
import datetime as dt
import os
import select
import signal
import sys
import time

from can_common import open_can_socket, recv_frame

HEADER = ["timestamp", "epoch", "can_id", "id_type", "frame_type", "length", "data_hex"]


def frame_to_row(f, ts=None):
    """Convert a Frame into a CSV row (separate function so it can be unit-tested)."""
    ts = time.time() if ts is None else ts
    iso = dt.datetime.fromtimestamp(ts).isoformat(timespec="microseconds")
    return [iso, "%.6f" % ts,
            "0x%08X" % f.can_id if f.extended else "0x%03X" % f.can_id,
            "EXT" if f.extended else "STD",
            "CAN_FD" if f.fd else "CAN",
            f.length, f.data.hex()]


def main():
    ap = argparse.ArgumentParser(description="Logger ECU (CAN traffic recorder)")
    ap.add_argument("--iface", default="vcan0")
    ap.add_argument("--out", default="can_log.csv")
    ap.add_argument("--append", action="store_true", help="append instead of overwrite")
    ap.add_argument("--fd", action="store_true", help="enable CAN FD reception")
    ap.add_argument("--flush-s", type=float, default=0.5, help="flush file every N seconds")
    ap.add_argument("--silence-s", type=float, default=2.0,
                    help="report 'bus silent' after N seconds without any frame")
    ap.add_argument("--stats-s", type=float, default=5.0, help="print statistics every N seconds")
    args = ap.parse_args()

    sock = open_can_socket(args.iface, fd=args.fd)      # no filter: log EVERYTHING
    sock.setblocking(False)

    new_file = args.append is False or not os.path.exists(args.out)
    fh = open(args.out, "w" if not args.append else "a", newline="")
    writer = csv.writer(fh)
    if new_file:
        writer.writerow(HEADER)

    running = True

    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    total = 0
    last_frame = time.monotonic()
    silent = False
    t0 = last_flush = last_stats = time.monotonic()
    total_at_last_stats = 0
    print("[LoggerECU] logging %s -> %s  (Ctrl+C to stop)" % (args.iface, args.out), file=sys.stderr)

    while running:
        try:
            ready, _, _ = select.select([sock], [], [], 0.1)
        except InterruptedError:
            continue
        now = time.monotonic()
        if ready:
            for _ in range(5000):
                try:
                    f = recv_frame(sock)
                except BlockingIOError:
                    break
                writer.writerow(frame_to_row(f))
                total += 1
                last_frame = time.monotonic()
            if silent:
                print("[LoggerECU] traffic resumed", file=sys.stderr)
                silent = False
        if not silent and now - last_frame > args.silence_s:
            print("[LoggerECU] bus silent for >%.1fs (no frames observed)" % args.silence_s, file=sys.stderr)
            silent = True
        if now - last_flush >= args.flush_s:
            fh.flush()
            last_flush = now
        if now - last_stats >= args.stats_s:
            fh.flush()
            rate = (total - total_at_last_stats) / (now - last_stats)
            print("[LoggerECU] frames=%d  rate=%.0f frames/s  file=%.1f KiB" %
                  (total, rate, os.path.getsize(args.out) / 1024.0), file=sys.stderr)
            total_at_last_stats, last_stats = total, now

    fh.close()
    print("[LoggerECU] stopped. %d frames in %.1fs, file %s (%.1f KiB)" %
          (total, time.monotonic() - t0, args.out, os.path.getsize(args.out) / 1024.0), file=sys.stderr)


if __name__ == "__main__":
    main()
