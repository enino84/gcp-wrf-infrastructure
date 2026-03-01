#!/bin/bash
# run_wps.sh
# Runs the full WPS pre-processing pipeline inside the wps-compiled container.
# Usage: ./scripts/run_wps.sh <case_name> [namelist_wps] [vtable] [data_root]
#
# Arguments:
#   case_name    : name of the simulation case (e.g. test001)
#   namelist_wps : path to namelist.wps  (default: namelist_examples/colombia/namelist.wps)
#   vtable       : path to Vtable        (default: namelist_examples/colombia/Vtable)
#   data_root    : base data path        (default: /mnt/data)
#
# Examples:
#   ./scripts/run_wps.sh test001
#   ./scripts/run_wps.sh test001 namelist_examples/barranquilla/namelist.wps
#   ./scripts/run_wps.sh test001 namelist_examples/barranquilla/namelist.wps namelist_examples/barranquilla/Vtable
#   ./scripts/run_wps.sh test001 namelist_examples/barranquilla/namelist.wps namelist_examples/barranquilla/Vtable /data/wrf

set -e

if [ -z "$1" ]; then
    echo "Usage: $0 <case_name> [namelist_wps] [vtable] [data_root]"
    echo ""
    echo "  case_name    : simulation case name (e.g. test001)"
    echo "  namelist_wps : path to namelist.wps  (default: namelist_examples/colombia/namelist.wps)"
    echo "  vtable       : path to Vtable        (default: extract from container)"
    echo "  data_root    : base data path        (default: /mnt/data)"
    exit 1
fi

CASE_NAME="$1"
NAMELIST_WPS="${2:-namelist_examples/colombia/namelist.wps}"
VTABLE="${3:-}"
PROJECT_ROOT="${4:-/mnt/data}"
CASE_DIR="$PROJECT_ROOT/cases/$CASE_NAME"
GEOG_DIR="$PROJECT_ROOT/WPS_GEOG/WPS_GEOG_FULL"

echo "--- Starting WPS pipeline ---"
echo "Case directory : $CASE_DIR"
echo "GEOG directory : $GEOG_DIR"
echo "namelist.wps   : $NAMELIST_WPS"
echo ""

# --- Validate and copy namelist.wps ---
if [ ! -f "$NAMELIST_WPS" ]; then
    echo "ERROR: namelist.wps not found: $NAMELIST_WPS"
    exit 1
fi
echo "Copying $NAMELIST_WPS -> $CASE_DIR/namelist.wps"
cp "$NAMELIST_WPS" "$CASE_DIR/namelist.wps"

# --- Validate and copy Vtable ---
if [ -n "$VTABLE" ]; then
    if [ ! -f "$VTABLE" ]; then
        echo "ERROR: Vtable not found: $VTABLE"
        exit 1
    fi
    echo "Copying $VTABLE -> $CASE_DIR/Vtable"
    cp "$VTABLE" "$CASE_DIR/Vtable"
elif [ ! -f "$CASE_DIR/Vtable" ]; then
    echo "Vtable not provided — extracting Vtable.GFS from container..."
    docker run --rm wps-compiled:latest \
        cat /wrf/WPS/ungrib/Variable_Tables/Vtable.GFS \
        > "$CASE_DIR/Vtable"
    echo "Vtable.GFS extracted to $CASE_DIR/Vtable"
else
    echo "Using existing Vtable at $CASE_DIR/Vtable"
fi

# --- Validate GFS data ---
if [ -z "$(ls "$CASE_DIR/gfs_data"/*.grib2 2>/dev/null)" ]; then
    echo "ERROR: No GRIB2 files found in $CASE_DIR/gfs_data/"
    echo "Run download_gfs.sh first."
    exit 1
fi

echo ""
echo "--- Running WPS inside container ---"

docker run --rm \
    -v "$GEOG_DIR":/geog \
    -v "$CASE_DIR":/experimento \
    wps-compiled:latest \
    bash -c "
        cd /wrf/WPS && \
        cp /experimento/namelist.wps . && \
        cp /experimento/Vtable . && \
        echo '--- Step 1: geogrid.exe ---' && \
        ./geogrid.exe && \
        echo '--- Step 2: link_grib.csh ---' && \
        ./link_grib.csh /experimento/gfs_data/*.grib2 && \
        echo '--- Step 3: ungrib.exe ---' && \
        ./ungrib.exe && \
        echo '--- Step 4: metgrid.exe ---' && \
        ./metgrid.exe && \
        cp geo_em.d01.nc /experimento/output/ && \
        cp met_em.d01.* /experimento/output/ && \
        echo '--- WPS PIPELINE COMPLETE ---'
    "

echo ""
echo "Outputs written to: $CASE_DIR/output/"
