#!/usr/bin/env python3
"""
Dashboard ECU - receives CAN messages, decodes them and shows a continuously
updating dashboard. Includes message filtering (Challenge 2), unknown-message
handling (Challenge 3), CAN FD reception (Challenge 6) and a loss-of-communication
diagnostic (Challenges 5 and 7).

Filtering modes (--mode), applied by the KERNEL via CAN_RAW_FILTER:
  all    receive every frame
  speed  receive only 0x100
  rpm    receive only 0x101

Examples
  ./dashboard_ecu.py
  ./dashboard_ecu.py --mode speed
  ./dashboard_ecu.py --mode rpm --timeout 2
  ./dashboard_ecu.py --fd --show-unknown
"""
import argparse
import select
import signal
import sys
import time

from can_common import (ID_SPEED, ID_RPM, ID_TEMP, ID_FD_VEHICLE, KNOWN_IDS,
                        decode_speed, decode_rpm, decode_temp, decode_fd_vehicle,
                        exact_filter, open_can_socket, recv_frame)

LINE = "-" * 32


class DashboardState:
    def __init__(self, mode, timeout):
        self.mode = mode
        self.timeout = timeout
        self.start = time.monotonic()
        self.values = {"speed": None, "rpm": None, "temp": None}
        self.last_rx = {}                 # can_id -> monotonic time of last reception
        self.counts = {"classic": 0, "fd": 0, "unknown": 0}
        self.unknown_ids = {}             # can_id -> count
        self.was_offline = False
        self.events = []                  # recent diagnostic events (strings)
        # Which message proves that the Vehicle ECU is alive?
        self.watchdog_id = ID_RPM if mode == "rpm" else ID_SPEED

    def note(self, text):
        stamp = time.strftime("%H:%M:%S")
        self.events.append("[%s] %s" % (stamp, text))
        self.events = self.events[-3:]

    def on_frame(self, f, now, show_unknown):
        self.counts["fd" if f.fd else "classic"] += 1
        self.last_rx[f.can_id] = now
        if f.can_id == ID_SPEED and not f.extended:
            self.values["speed"] = decode_speed(f.data)
        elif f.can_id == ID_RPM and not f.extended:
            self.values["rpm"] = decode_rpm(f.data)
        elif f.can_id == ID_TEMP and not f.extended:
            self.values["temp"] = decode_temp(f.data)
        elif f.can_id == ID_FD_VEHICLE and f.fd and f.length >= 8:
            d = decode_fd_vehicle(f.data)
            self.values.update(speed=d["speed"], rpm=d["rpm"], temp=d["temp"])
            self.last_rx[ID_SPEED] = now          # FD frame also proves ECU is alive
        else:                                      # NOT in the message database
            self.counts["unknown"] += 1
            self.unknown_ids[f.can_id] = self.unknown_ids.get(f.can_id, 0) + 1
            if show_unknown:
                self.note("UNKNOWN frame ID=0x%X len=%d data=%s" %
                          (f.can_id, f.length, f.data.hex(" ")))

    def is_offline(self, now):
        last = self.last_rx.get(self.watchdog_id)
        ref = last if last is not None else self.start
        return (now - ref) > self.timeout

    def render(self, now):
        def fmt(key, unit, can_id):
            filtered_out = (self.mode == "speed" and can_id != ID_SPEED) or \
                           (self.mode == "rpm" and can_id != ID_RPM)
            if filtered_out:
                return "-- (filtered out)"
            v = self.values[key]
            return "--" if v is None else "%d %s" % (round(v), unit)

        lines = [LINE, "Vehicle Dashboard", LINE,
                 "Speed       : " + fmt("speed", "km/h", ID_SPEED),
                 "Engine RPM  : " + fmt("rpm", "rpm", ID_RPM),
                 "Temperature : " + fmt("temp", "\u00b0C", ID_TEMP),
                 LINE]
        if self.is_offline(now):
            lines.append("WARNING: Vehicle ECU Offline")
            lines.append(LINE)
        lines.append("Mode: %s | rx classic=%d fd=%d unknown=%d" %
                     (self.mode, self.counts["classic"], self.counts["fd"], self.counts["unknown"]))
        if self.unknown_ids:
            lines.append("Unknown IDs seen: " + ", ".join(
                "0x%X(x%d)" % (k, v) for k, v in sorted(self.unknown_ids.items())))
        lines += self.events
        return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Dashboard ECU (CAN receiver)")
    ap.add_argument("--iface", default="vcan0")
    ap.add_argument("--mode", choices=["all", "speed", "rpm"], default="all",
                    help="kernel-level receive filter")
    ap.add_argument("--timeout", type=float, default=1.0,
                    help="seconds without the watchdog message before WARNING (default 1.0)")
    ap.add_argument("--refresh", type=float, default=0.1, help="screen refresh period (s)")
    ap.add_argument("--fd", action="store_true", help="enable CAN FD reception")
    ap.add_argument("--show-unknown", action="store_true",
                    help="print an event line for every unknown frame")
    ap.add_argument("--plain", action="store_true",
                    help="no screen clearing; print one status line per refresh (good for log files)")
    args = ap.parse_args()

    filters = {"all": None,
               "speed": [exact_filter(ID_SPEED)],
               "rpm": [exact_filter(ID_RPM)]}[args.mode]
    sock = open_can_socket(args.iface, fd=args.fd, filters=filters)
    sock.setblocking(False)

    st = DashboardState(args.mode, args.timeout)
    running = True

    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    next_draw = time.monotonic()
    while running:
        now = time.monotonic()
        try:
            ready, _, _ = select.select([sock], [], [], max(0.0, next_draw - now))
        except InterruptedError:
            continue
        if ready:
            for _ in range(2000):                     # drain, but never starve the display
                try:
                    f = recv_frame(sock)
                except BlockingIOError:
                    break
                st.on_frame(f, time.monotonic(), args.show_unknown)
        now = time.monotonic()
        offline = st.is_offline(now)
        if offline and not st.was_offline:
            st.note("WARNING: Vehicle ECU Offline (no 0x%X for >%.1fs)" % (st.watchdog_id, args.timeout))
        elif not offline and st.was_offline:
            st.note("Vehicle ECU back online")
        st.was_offline = offline
        if now >= next_draw:
            text = st.render(now)
            if args.plain:
                v = st.values
                print("%s speed=%s rpm=%s temp=%s offline=%s rx=%s" %
                      (time.strftime("%H:%M:%S"), v["speed"], v["rpm"], v["temp"], offline, st.counts))
            else:
                sys.stdout.write("\033[H\033[J" + text + "\n")
                sys.stdout.flush()
            next_draw = now + args.refresh
    print("\n[DashboardECU] stopped. rx=%s unknown ids=%s" % (st.counts, st.unknown_ids))


if __name__ == "__main__":
    main()
