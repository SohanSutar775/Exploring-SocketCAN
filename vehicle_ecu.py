#!/usr/bin/env python3
"""
Vehicle ECU - transmits Speed, RPM and Coolant Temperature on a SocketCAN interface.

Values vary realistically (see VehicleModel): speed follows a random drive cycle with
limited acceleration, RPM depends on speed/gear/load, coolant warms up from 20 degC.

Examples
  ./vehicle_ecu.py                              # classic CAN on vcan0
  ./vehicle_ecu.py --speed-ms 10 --rpm-ms 10    # faster transmission (Challenge 4)
  ./vehicle_ecu.py --fd                         # classic + CAN FD frame 0x200 (Challenge 6)
  ./vehicle_ecu.py --fd-only                    # only the CAN FD frame
"""
import argparse
import random
import signal
import sys
import time

from can_common import (ID_SPEED, ID_RPM, ID_TEMP, ID_FD_VEHICLE, clamp,
                        encode_speed, encode_rpm, encode_temp, encode_fd_vehicle,
                        open_can_socket, send_frame)

# gear -> (upper speed limit km/h, rpm gained per km/h)
GEARS = [(15, 80.0), (30, 45.0), (50, 30.0), (75, 22.0), (100, 17.0), (999, 14.0)]


class VehicleModel:
    """Simple physical-ish model so the signals look like a real drive."""

    def __init__(self, seed=None, warmup_tau=40.0):
        self.rng = random.Random(seed)
        self.speed = 0.0
        self.rpm = 800.0
        self.temp = 20.0
        self.gear = 1
        self.odometer_m = 0.0
        self.warmup_tau = warmup_tau
        self._target = 0.0
        self._next_change = 0.0
        self._t = 0.0
        self._accel = 0.0

    def step(self, dt):
        self._t += dt
        if self._t >= self._next_change:                      # pick a new driving target
            self._target = self.rng.choice([0, 20, 35, 50, 65, 80, 95, 110, 120])
            self._next_change = self._t + self.rng.uniform(6, 14)
        # limited acceleration (6 km/h/s) and braking (10 km/h/s)
        diff = self._target - self.speed
        max_up, max_down = 6.0 * dt, 10.0 * dt
        delta = clamp(diff, -max_down, max_up)
        self._accel = delta / dt if dt > 0 else 0.0
        self.speed = clamp(self.speed + delta + self.rng.uniform(-0.05, 0.05), 0, 120)
        self.odometer_m += self.speed / 3.6 * dt
        # gear and rpm
        self.gear, k = next((i + 1, k) for i, (lim, k) in enumerate(GEARS) if self.speed <= lim)
        load = max(0.0, self._accel) * 120.0                  # extra rpm while accelerating
        rpm_target = clamp(800 + self.speed * k + load, 800, 5000)
        self.rpm += (rpm_target - self.rpm) * min(1.0, dt / 0.25)   # engine inertia
        self.rpm = clamp(self.rpm + self.rng.uniform(-8, 8), 800, 5000)
        # coolant: first-order warm-up toward a load dependent operating temperature
        temp_target = 88 + (self.rpm - 800) / 4200 * 20
        self.temp = clamp(self.temp + (temp_target - self.temp) * dt / self.warmup_tau, 20, 120)


def main():
    ap = argparse.ArgumentParser(description="Vehicle ECU (CAN transmitter)")
    ap.add_argument("--iface", default="vcan0")
    ap.add_argument("--speed-ms", type=float, default=100, help="Speed (0x100) period in ms")
    ap.add_argument("--rpm-ms", type=float, default=50, help="RPM (0x101) period in ms")
    ap.add_argument("--temp-ms", type=float, default=500, help="Temp (0x102) period in ms")
    ap.add_argument("--fd", action="store_true", help="also send CAN FD frame 0x200 (16 bytes, BRS)")
    ap.add_argument("--fd-only", action="store_true", help="send only the CAN FD frame 0x200")
    ap.add_argument("--fd-ms", type=float, default=100, help="CAN FD frame period in ms")
    ap.add_argument("--seed", type=int, default=None, help="random seed (repeatable runs)")
    ap.add_argument("--warmup-tau", type=float, default=40.0, help="coolant warm-up time constant (s)")
    args = ap.parse_args()

    use_fd = args.fd or args.fd_only
    sock = open_can_socket(args.iface, fd=use_fd)
    model = VehicleModel(args.seed, args.warmup_tau)

    jobs = []   # [name, period_s, next_due, sender]
    if not args.fd_only:
        jobs += [
            ["speed", args.speed_ms / 1000, 0, lambda: send_frame(sock, ID_SPEED, encode_speed(model.speed))],
            ["rpm", args.rpm_ms / 1000, 0, lambda: send_frame(sock, ID_RPM, encode_rpm(model.rpm))],
            ["temp", args.temp_ms / 1000, 0, lambda: send_frame(sock, ID_TEMP, encode_temp(model.temp))],
        ]
    if use_fd:
        jobs.append(["fd", args.fd_ms / 1000, 0, lambda: send_frame(
            sock, ID_FD_VEHICLE,
            encode_fd_vehicle(model.speed, model.rpm, model.temp, model.gear, model.odometer_m),
            fd=True, brs=True)])

    running = True

    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    sent = {j[0]: 0 for j in jobs}
    errors = 0
    t0 = last = time.monotonic()
    for j in jobs:
        j[2] = t0
    next_report = t0 + 1.0
    print("[VehicleECU] transmitting on %s (%s)  Ctrl+C to stop" %
          (args.iface, "CAN FD + classic" if args.fd else "CAN FD only" if args.fd_only else "classic CAN"),
          file=sys.stderr)

    while running:
        now = time.monotonic()
        model.step(now - last)
        last = now
        for j in jobs:
            if now >= j[2]:
                try:
                    j[3]()
                    sent[j[0]] += 1
                except OSError as e:                  # e.g. ENOBUFS when the TX queue is full
                    errors += 1
                j[2] += j[1]
                if j[2] < now:                        # we fell behind: do not burst to catch up
                    j[2] = now + j[1]
        if now >= next_report:
            print("[VehicleECU] t=%5.0fs speed=%5.1f km/h rpm=%4.0f temp=%3.0f C gear=%d | sent %s | tx errors %d" %
                  (now - t0, model.speed, model.rpm, model.temp, model.gear, sent, errors), file=sys.stderr)
            next_report += 1.0
        sleep = min(j[2] for j in jobs) - time.monotonic()
        if sleep > 0:
            time.sleep(min(sleep, 0.01))
    print("[VehicleECU] stopped. Frames sent: %s" % sent, file=sys.stderr)


if __name__ == "__main__":
    main()
