# SocketCAN Problem Statement 1 - Software-Only CAN / CAN FD on Linux

Three software ECUs (Vehicle, Dashboard, Logger) talking over a virtual CAN bus (`vcan0`).
Pure Python 3 standard library - no extra packages. Linux only (SocketCAN is a Linux kernel feature).

```
src/vehicle_ecu.py     Vehicle ECU   - transmits Speed, RPM, Coolant Temp (+ CAN FD frame with --fd)
src/dashboard_ecu.py   Dashboard ECU - receives, filters (--mode), decodes, displays, offline warning
src/logger_ecu.py      Logger ECU    - logs every frame to CSV, reports bus silence
src/can_inject.py      Helper        - inject unknown / extended / CAN FD frames (Challenge 3, 6)
src/analyze_log.py     Helper        - rates, jitter, gaps and file size from the CSV (Challenge 4)
src/can_common.py      Shared        - message IDs, encode/decode, frame pack/unpack, socket helpers
scripts/setup_vcan.sh  Creates vcan0 (MTU 72 so CAN FD works)
scripts/run_all_tmux.sh  Optional: all three ECUs in one tmux window
tests/test_offline.py  19 unit tests (run without any CAN interface)
```

## 0. Requirements
* Native Ubuntu/Debian Linux or a Linux VM (VirtualBox/VMware/Ubuntu on a USB). Python 3.8+.
* **WSL2 warning:** the default WSL2 kernel has no `vcan` module, so use a real Linux VM or build a custom WSL kernel.
* Optional tools: `sudo apt install can-utils tmux` (gives `candump`, `cansend`, `cangen`).

## 1. Create the virtual CAN bus
```bash
cd scripts
sudo ./setup_vcan.sh            # creates and brings up vcan0 with MTU 72
ip -details link show vcan0     # should show "vcan" and "mtu 72"
```
Quick check with can-utils: terminal A `candump vcan0`, terminal B `cansend vcan0 123#DEADBEEF`.

## 2. Run the three ECUs (three terminals)
```bash
cd src
python3 dashboard_ecu.py            # terminal 1
python3 logger_ecu.py               # terminal 2  -> can_log.csv
python3 vehicle_ecu.py              # terminal 3
```
Start order does not matter - CAN is broadcast, so receivers simply see what is sent after they start.

## 3. Demonstration script (all six required demo points)
| # | Demo item | What to do | What to show |
|---|-----------|-----------|--------------|
| 1 | Message transmission | Start `vehicle_ecu.py`; in another terminal `candump vcan0` | 0x100 / 0x101 / 0x102 frames on the bus; Vehicle ECU 1-second status line |
| 2 | Message reception | `dashboard_ecu.py` | Dashboard values update continuously (Speed, RPM, Temp) |
| 3 | Message filtering | Restart dashboard with `--mode speed`, then `--mode rpm`, then `--mode all` | Filtered signals show `-- (filtered out)`; counters of `rx` drop accordingly |
| 4 | Traffic logging | `logger_ecu.py`, then `head can_log.csv` and `python3 analyze_log.py can_log.csv` | CSV with timestamp, ID, length, payload; per-ID rates |
| 5 | Node failure detection | Press Ctrl+C in the Vehicle ECU terminal | Dashboard shows `WARNING: Vehicle ECU Offline` after `--timeout` s; logger prints `bus silent`; restart vehicle -> `back online` |
| 6 | CAN FD communication | Start dashboard/logger with `--fd`, vehicle with `--fd` (or `--fd-only`); `candump -d vcan0` | 16-byte frame 0x200 with BRS; dashboard `rx ... fd=N` counter increments |

## 4. Learning-challenge procedures
**Challenge 1 - Traffic observation.** Run Vehicle + Dashboard + Logger + `candump vcan0` together. Compare frame counts: dashboard `rx classic`, logger total (`wc -l can_log.csv`), candump. Expect identical delivery to every listener; the sender does not know how many receivers exist.

**Challenge 2 - Filtering.** `python3 dashboard_ecu.py --mode all|speed|rpm`. Filtering is done in the kernel (`CAN_RAW_FILTER`), so the application never even receives other IDs. Logger stays unfiltered and still records everything.

**Challenge 3 - Unknown message.** While everything runs: `python3 can_inject.py --id 0x3A0 --data DEADBEEF --count 5`. Check `grep 0x3A0 can_log.csv` (logged), dashboard counters (`unknown=5`, not shown as a signal). Add `--show-unknown` to the dashboard to see event lines. Try an extended ID: `--id 0x18FEF100 --extended`.

**Challenge 4 - Transmission rate.**
```bash
python3 vehicle_ecu.py --speed-ms 100 --rpm-ms 50  --temp-ms 500   # baseline (~32 frames/s)
python3 vehicle_ecu.py --speed-ms 10  --rpm-ms 10  --temp-ms 10    # ~300 frames/s (target)
python3 vehicle_ecu.py --speed-ms 1   --rpm-ms 1   --temp-ms 1     # ~3000 frames/s (target; Python may fall short)
```
For each run (about 60 s): `python3 analyze_log.py can_log.csv`, `ls -l can_log.csv`, and CPU/memory via `top -p $(pgrep -d, -f "_ecu.py")` or `pidstat -p ALL 5` (package `sysstat`). Fill the table in the report.

**Challenge 5 - Node failure.** Ctrl+C the Vehicle ECU. Dashboard: offline warning (no frames = no error from SocketCAN - the bus simply goes quiet). Logger: no new rows, prints `bus silent`. Detection = watchdog timeout on a periodic message (implemented in `DashboardState.is_offline`).

**Challenge 6 - CAN FD.** See demo item 6. The interface MTU must be 72, sockets enable `CAN_RAW_FD_FRAMES`, and receivers must read 72-byte `canfd_frame` structures (see `open_can_socket`, `pack_frame`, `unpack_frame`).

**Challenge 7 - Diagnostics.** Implemented as the Dashboard watchdog (`--timeout`, default 1.0 s): no Speed message (0x100, or any FD frame) -> `WARNING: Vehicle ECU Offline`.

## 5. Run the unit tests (no CAN needed)
```bash
python3 tests/test_offline.py
```

## 6. Troubleshooting
* `OSError: [Errno 19] No such device` - `vcan0` is not up: rerun `sudo scripts/setup_vcan.sh`.
* `OSError: [Errno 97] Address family not supported` - kernel has no CAN support (typical in WSL2 / containers).
* `OSError: [Errno 22] Invalid argument` when using `--fd` - interface MTU is not 72.
* Nothing on the dashboard - check all ECUs use the same `--iface`; check with `candump vcan0`.
* Clean up: `sudo scripts/teardown_vcan.sh`.
