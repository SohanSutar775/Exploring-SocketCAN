#!/usr/bin/env bash
# Start Vehicle, Dashboard and Logger ECUs side by side in one tmux window.
# Usage: ./run_all_tmux.sh [extra vehicle args, e.g. --fd]
set -e
cd "$(dirname "$0")/../src"
S=socketcan_demo
tmux kill-session -t $S 2>/dev/null || true
tmux new-session -d -s $S -n ECUs "python3 dashboard_ecu.py --fd"
tmux split-window -h -t $S "python3 logger_ecu.py --fd --out ../can_log.csv"
tmux split-window -v -t $S "python3 vehicle_ecu.py $*"
tmux select-layout -t $S tiled
tmux attach -t $S
