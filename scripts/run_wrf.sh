#!/bin/bash
# run_wrf.sh
# Runs real.exe (initial/boundary condition prep) and wrf.exe (simulation).
# Launched with nohup so it survives terminal disconnects.
# Usage: ./run_wrf.sh <case_name>

if [ -z "$1" ]; then
    echo "Usage: $0 <case_name>"
    echo "Example: $0 my_experiment"
    exit 1
fi

CASE_NAME="$1"
CASE_DIR="/mnt/data/cases/$CASE_NAME"
LOG_FILE="$CASE_DIR/simulation.log"

echo "--- Starting WRF simulation ---"
echo "Case directory : $CASE_DIR"
echo "Log file       : $LOG_FILE"
echo ""

# Validate required inputs
if [ ! -f "$CASE_DIR/namelist.input" ]; then
    echo "ERROR: Required file not found: $CASE_DIR/namelist.input"
    exit 1
fi

if [ ! -f "$CASE_DIR/output/met_em.d01."* 2>/dev/null ]; then
    echo "WARNING: No met_em files found in $CASE_DIR/output/ — did you run run_wps.sh first?"
fi

echo "Launching WRF in background. Monitor with:"
echo "  tail -f $LOG_FILE"
echo ""

nohup docker run --rm \
    -v "$CASE_DIR":/experimento \
    wrf-compiled:latest \
    bash -c "
        cd /wrf/WRF/test/em_real && \
        rm -f rsl.* && \
        cp /experimento/namelist.input . && \
        cp /experimento/output/met_em.d01.* . && \
        echo '--- Step 1: real.exe (generating initial and boundary conditions) ---' && \
        ./real.exe && \
        cp wrfinput_d01 wrfbdy_d01 /experimento/output/ && \
        echo '--- Step 2: wrf.exe (running numerical simulation) ---' && \
        ./wrf.exe && \
        cp wrfout_d01* /experimento/output/ && \
        echo '--- SIMULATION COMPLETE ---'
    " > "$LOG_FILE" 2>&1 &

echo "WRF is running (PID: $!)"
