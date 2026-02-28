#!/bin/bash
# run_wps.sh
# Runs the full WPS pre-processing pipeline inside the wps-compiled container.
# Steps: geogrid.exe -> link_grib.csh -> ungrib.exe -> metgrid.exe
# Usage: ./run_wps.sh <case_name>

set -e

if [ -z "$1" ]; then
    echo "Usage: $0 <case_name>"
    echo "Example: $0 my_experiment"
    exit 1
fi

CASE_NAME="$1"
CASE_DIR="/mnt/data/cases/$CASE_NAME"
GEOG_DIR="/mnt/data/WPS_GEOG/WPS_GEOG_FULL"

echo "--- Starting WPS pipeline ---"
echo "Case directory : $CASE_DIR"
echo "GEOG directory : $GEOG_DIR"
echo ""

# Validate required inputs
for f in namelist.wps Vtable; do
    if [ ! -f "$CASE_DIR/$f" ]; then
        echo "ERROR: Required file not found: $CASE_DIR/$f"
        exit 1
    fi
done

if [ ! -d "$CASE_DIR/gfs_data" ] || [ -z "$(ls -A "$CASE_DIR/gfs_data"/*.grib2 2>/dev/null)" ]; then
    echo "ERROR: No GRIB2 files found in $CASE_DIR/gfs_data/"
    exit 1
fi

docker run --rm \
    -v "$GEOG_DIR":/geog \
    -v "$CASE_DIR":/experimento \
    wps-compiled:latest \
    bash -c "
        cd /wrf/WPS && \
        cp /experimento/namelist.wps . && \
        cp /experimento/Vtable . && \
        echo '--- Step 1: Geogrid (domain grid and static fields) ---' && \
        ./geogrid.exe && \
        echo '--- Step 2: Linking GRIB2 files ---' && \
        ./link_grib.csh /experimento/gfs_data/*.grib2 && \
        echo '--- Step 3: Ungrib (decode meteorological fields) ---' && \
        ./ungrib.exe && \
        echo '--- Step 4: Metgrid (horizontal interpolation) ---' && \
        ./metgrid.exe && \
        cp geo_em.d01.nc /experimento/output/ && \
        cp met_em.d01.* /experimento/output/ && \
        echo '--- WPS PIPELINE COMPLETE ---'
    "

echo ""
echo "Outputs written to: $CASE_DIR/output/"
