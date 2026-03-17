#!/bin/bash
# run_wrf_nohup.sh
# Runs real.exe + wrf.exe inside the wrf-compiled container.
# NO nohup → blocking execution (recommended for pipelines).
# Automatically detects serial vs dmpar (MPI) compilation mode.

if [ -z "$1" ]; then
    echo "Usage: $0 <case_name> [namelist_input] [data_root] [num_procs]"
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

# --- Validate namelist ---
if [ ! -f "$NAMELIST_INPUT" ]; then
    echo "ERROR: namelist.input not found: $NAMELIST_INPUT"
    exit 1
fi

mkdir -p "$CASE_DIR/output"
cp "$NAMELIST_INPUT" "$CASE_DIR/namelist.input"

# --- Validate met_em ---
if [ -z "$(ls "$CASE_DIR/output"/met_em.d01.* 2>/dev/null)" ]; then
    echo "WARNING: No met_em files found in $CASE_DIR/output/"
fi

# --- Detect WRF mode ---
WRF_MODE=$(docker run --rm wrf-compiled:latest cat /wrf/WRF/.wrf_mode 2>/dev/null || echo "serial")
echo "WRF build mode : $WRF_MODE"

if [ "$WRF_MODE" = "dmpar" ]; then
    if [ "$NUM_PROCS" -eq 0 ]; then
        NUM_PROCS=$(docker run --rm wrf-compiled:latest nproc)
    fi
else
    NUM_PROCS=1
fi

echo "MPI processes  : $NUM_PROCS"
echo ""

echo "Running WRF in FOREGROUND (pipeline-friendly)"
echo "Logs: $LOG_FILE"
echo ""

# --- Run container (NO nohup) ---
docker run --rm \
    --name "wrf_${CASE_NAME}" \
    -v "$CASE_DIR":/experimento \
    wrf-compiled:latest \
    bash -c "
        set -e

        export OMP_NUM_THREADS=1
        export OMP_PROC_BIND=true

        START_TIME=\$(date '+%Y-%m-%d %H:%M:%S')
        echo \"=== Simulation started at: \$START_TIME ===\"

        cd /wrf/WRF/test/em_real
        rm -f rsl.*

        mkdir -p /experimento/output
        cp /experimento/namelist.input .
        cp /experimento/output/met_em.d01.* .

        echo '--- Step 1: real.exe ---'
        ./real.exe

        cp wrfinput_d01 wrfbdy_d01 /experimento/output/

        echo '--- Step 2: wrf.exe ---'

        if [ \"$WRF_MODE\" = \"dmpar\" ] && [ $NUM_PROCS -gt 1 ]; then
            mpirun -np $NUM_PROCS ./wrf.exe
        else
            ./wrf.exe
        fi

        cp wrfout_d01* /experimento/output/

        END_TIME=\$(date '+%Y-%m-%d %H:%M:%S')
        echo \"=== Simulation ended at: \$END_TIME ===\"
        echo '--- SIMULATION COMPLETE ---'
    " 2>&1 | tee "$LOG_FILE"

echo ""
echo "WRF finished successfully for case: $CASE_NAME"