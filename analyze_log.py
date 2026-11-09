#!/usr/bin/env python3
"""
analyze_log.py - summarise a CSV written by logger_ecu.py (Challenges 1, 4 and 5).

Prints, per CAN id: count, mean period, min/max period, jitter (std-dev) and the longest
gap between frames. Also prints total duration, overall frame rate, and file size.

  ./analyze_log.py can_log.csv
"""
import csv
import os
import statistics
import sys
from collections import defaultdict


def main(path):
    times = defaultdict(list)
    types = {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            times[row["can_id"]].append(float(row["epoch"]))
            types[row["can_id"]] = "%s/%s" % (row["id_type"], row["frame_type"])
    if not times:
        print("log is empty")
        return
    all_t = [t for v in times.values() for t in v]
    dur = max(all_t) - min(all_t)
    total = len(all_t)
    print("File: %s  (%.1f KiB)" % (path, os.path.getsize(path) / 1024))
    print("Frames: %d   Duration: %.2f s   Overall rate: %.1f frames/s   Bytes/frame in file: %.1f\n" %
          (total, dur, total / dur if dur else 0, os.path.getsize(path) / total))
    print("%-12s %-9s %7s %10s %10s %10s %10s %10s" %
          ("CAN id", "type", "count", "mean ms", "min ms", "max ms", "jitter ms", "max gap ms"))
    for cid in sorted(times):
        t = sorted(times[cid])
        d = [(b - a) * 1000 for a, b in zip(t, t[1:])]
        if d:
            print("%-12s %-9s %7d %10.2f %10.2f %10.2f %10.2f %10.2f" %
                  (cid, types[cid], len(t), statistics.mean(d), min(d), max(d),
                   statistics.pstdev(d), max(d)))
        else:
            print("%-12s %-9s %7d %10s" % (cid, types[cid], len(t), "n/a"))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "can_log.csv")
