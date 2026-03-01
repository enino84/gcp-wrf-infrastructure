#!/bin/bash
# run_wrf.sh
# Runs real.exe + wrf.exe inside the wrf-compiled container.
# Uses nohup so the simulation survives terminal disconnects and SSH drops.
#
# Usage: ./scripts/run_wrf.sh <case_name> [namelist_input] [data_root]
#
# Arguments:
#   case_name      : name of the simulation case (e.g. test001)
#   namelist_input : path to namelist.input (default: namelist_examples/colombia/namelist.input)
#   data_root      : base data path         (default: /mnt/data)
#
# Examples:
#   ./scripts/run_wrf.sh test001
#   ./scripts/run_wrf.sh test001 namelist_examples/barranquilla/namelist.input
#   ./scripts/run_wrf.sh test001 namelist_examples/barranquilla/namelist.input /data/wrf

if [ -z "$1" ]; then
    echo "Usage: $0 <case_name> [namelist_input] [data_root]"
    echo ""
    echo "  case_name      : simulation case name (e.g. test001)"
    echo "  namelist_input : path to namelist.input (default: namelist_examples/colombia/namelist.input)"
    echo "  data_root      : base data path         (default: /mnt/data)"
    exit 1
fi

CASE_NAME="$1"
NAMELIST_INPUT="${2:-namelist_examples/colombia/namelist.input}"
PROJECT_ROOT="${3:-/mnt/data}"
CASE_DIR="$PROJECT_ROOT/cases/$CASE_NAME"
LOG_FILE="$CASE_DIR/simulation.log"

echo "--- Starting WRF simulation ---"
echo "Case directory : $CASE_DIR"
echo "namelist.input : $NAMELIST_INPUT"
echo "Log file       : $LOG_FILE"
echo ""

# --- Validate and copy namelist.input ---
if [ ! -f "$NAMELIST_INPUT" ]; then
    echo "ERROR: namelist.input not found: $NAMELIST_INPUT"
    exit 1
fi
echo "Copying $NAMELIST_INPUT -> $CASE_DIR/namelist.input"
cp "$NAMELIST_INPUT" "$CASE_DIR/namelist.input"

# --- Validate met_em files ---
if [ -z "$(ls "$CASE_DIR/output"/met_em.d01.* 2>/dev/null)" ]; then
    echo "WARNING: No met_em files found in $CASE_DIR/output/"
    echo "Did you run run_wps.sh first?"
fi

echo ""
echo "Launching WRF in background with nohup."
echo "Monitor with:  tail -f $LOG_FILE"
echo "Ctrl+C stops monitoring — the simulation keeps running."
echo ""

nohup docker run --rm \
    -v "$CASE_DIR":/experimento \
    wrf-compiled:latest \
    bash -c "
        cd /wrf/WRF/test/em_real && \
        rm -f rsl.* && \
        cp /experimento/namelist.input . && \
        cp /experimento/output/met_em.d01.* . && \
        echo '--- Step 1: real.exe ---' && \
        ./real.exe && \
        cp wrfinput_d01 wrfbdy_d01 /experimento/output/ && \
        echo '--- Step 2: wrf.exe ---' && \
        ./wrf.exe && \
        cp wrfout_d01* /experimento/output/ && \
        echo '--- SIMULATION COMPLETE ---'
    " > "$LOG_FILE" 2>&1 &

echo "WRF is running (PID: $!)"
