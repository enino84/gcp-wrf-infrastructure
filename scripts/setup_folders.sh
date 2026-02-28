#!/bin/bash
# setup_folders.sh
# Creates the host directory skeleton for the WRF-Docker pipeline.
# Usage: ./setup_folders.sh <case_name>

set -e

if [ -z "$1" ]; then
    echo "Usage: $0 <case_name>"
    echo "Example: $0 my_experiment"
    exit 1
fi

CASE_NAME="$1"
PROJECT_ROOT="/mnt/data"
CASE_DIR="$PROJECT_ROOT/cases/$CASE_NAME"

echo "Creating WRF pipeline directory structure..."
echo "Case: $CASE_NAME"

mkdir -p "$CASE_DIR/gfs_data"
mkdir -p "$CASE_DIR/output"
mkdir -p "$PROJECT_ROOT/WPS_GEOG"

# Only chmod the newly created directories, not the entire /mnt/data tree
# chmod -R on a large directory (GFS data, WPS_GEOG, etc.) can take minutes
chmod 755 "$PROJECT_ROOT/WPS_GEOG"
chmod 755 "$PROJECT_ROOT/cases"
chmod 755 "$CASE_DIR"
chmod 755 "$CASE_DIR/gfs_data"
chmod 755 "$CASE_DIR/output"

echo ""
echo "Structure created:"
echo "  $CASE_DIR/gfs_data/      <- GFS GRIB2 files go here"
echo "  $CASE_DIR/output/        <- Pipeline outputs land here"
echo "  $PROJECT_ROOT/WPS_GEOG/  <- Place WPS_GEOG_FULL here manually"
echo ""
echo "You must also provide:"
echo "  $CASE_DIR/namelist.wps"
echo "  $CASE_DIR/namelist.input"
echo "  $CASE_DIR/Vtable"
