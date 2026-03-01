#!/bin/bash
# run_wrf.sh
# Runs real.exe + wrf.exe inside the wrf-compiled container.
# Uses nohup so the simulation survives terminal disconnects and SSH drops.
# Automatically detects serial vs dmpar (MPI) compilation mode.
#
# Usage: ./scripts/run_wrf.sh <case_name> [namelist_input] [data_root] [num_procs]
#
# Arguments:
#   case_name      : name of the simulation case (e.g. test001)
#   namelist_input : path to namelist.input (default: namelist_examples/colombia/namelist.input)
#   data_root      : base data path         (default: /mnt/data)
#   num_procs      : number of MPI processes (default: all cores via nproc, dmpar only)
#
# Examples:
#   ./scripts/run_wrf.sh test001
#   ./scripts/run_wrf.sh test001 namelist_examples/barranquilla/namelist.input
#   ./scripts/run_wrf.sh test001 namelist_examples/barranquilla/namelist.input /data/wrf
#   ./scripts/run_wrf.sh test001 namelist_examples/barranquilla/namelist.input /mnt/data 8

if [ -z "$1" ]; then
    echo "Usage: $0 <case_name> [namelist_input] [data_root] [num_procs]"
    echo ""
    echo "  case_name      : simulation case name (e.g. test001)"
    echo "  namelist_input : path to namelist.input (default: namelist_examples/colombia/namelist.input)"
    echo "  data_root      : base data path         (default: /mnt/data)"
    echo "  num_procs      : MPI processes to use   (default: all cores, dmpar builds only)"
    exit 1
fi

CASE_NAME="$1"
NAMELIST_INPUT="${2:-namelist_examples/colombia/namelist.input}"
PROJECT_ROOT="${3:-/mnt/data}"
NUM_PROCS="${4:-0}"
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

# --- Detect serial vs dmpar from image ---
WRF_MODE=$(docker run --rm wrf-compiled:latest cat /wrf/WRF/.wrf_mode 2>/dev/null || echo "serial")
echo "WRF build mode : $WRF_MODE"

if [ "$WRF_MODE" = "dmpar" ]; then
    if [ "$NUM_PROCS" -eq 0 ]; then
        NUM_PROCS=$(docker run --rm wrf-compiled:latest nproc)
    fi
    echo "MPI processes  : $NUM_PROCS"
    WRF_RUN_CMD="mpirun -np $NUM_PROCS ./wrf.exe"
else
    echo "MPI processes  : 1 (serial build)"
    WRF_RUN_CMD="./wrf.exe"
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
        set -e
        cd /wrf/WRF/test/em_real && \
        rm -f rsl.* && \
        mkdir -p /experimento/output && \
        cp /experimento/namelist.input . && \
        cp /experimento/output/met_em.d01.* . && \
        echo '--- Step 1: real.exe ---' && \
        ./real.exe && \
        cp wrfinput_d01 wrfbdy_d01 /experimento/output/ && \
        echo '--- Step 2: wrf.exe (mode: $WRF_MODE) ---' && \
        $WRF_RUN_CMD && \
        cp wrfout_d01* /experimento/output/ && \
        echo '--- SIMULATION COMPLETE ---'
    " > "$LOG_FILE" 2>&1 &

echo "WRF is running (PID: $!)"