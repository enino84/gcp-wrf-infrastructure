#!/bin/bash
# setup_folders.sh
# Creates the host directory skeleton for the WRF-Docker pipeline.
# Usage: ./scripts/setup_folders.sh <case_name> [data_root]
# Example: ./scripts/setup_folders.sh test001
# Example: ./scripts/setup_folders.sh test001 /data/wrf

set -e

if [ -z "$1" ]; then
    echo "Usage: $0 <case_name> [data_root]"
    echo "  case_name  : name for this simulation case (e.g. test001)"
    echo "  data_root  : optional base path (default: /mnt/data)"
    echo ""
    echo "Example: $0 test001"
    echo "Example: $0 test001 /data/wrf"
    exit 1
fi

CASE_NAME="$1"
PROJECT_ROOT="${2:-/mnt/data}"
CASE_DIR="$PROJECT_ROOT/cases/$CASE_NAME"

echo "Creating WRF pipeline directory structure..."
echo "Case      : $CASE_NAME"
echo "Data root : $PROJECT_ROOT"

mkdir -p "$CASE_DIR/gfs_data"
mkdir -p "$CASE_DIR/output"
mkdir -p "$PROJECT_ROOT/WPS_GEOG"

# Only chmod the newly created directories, not the entire data tree.
# Avoid chmod -R on /mnt/data — it can take minutes if the directory is large.
chmod 755 "$PROJECT_ROOT/WPS_GEOG"
chmod 755 "$PROJECT_ROOT/cases"
chmod 755 "$CASE_DIR"
chmod 755 "$CASE_DIR/gfs_data"
chmod 755 "$CASE_DIR/output"

# Make all pipeline scripts executable.
# This runs once here so you never have to chmod +x manually again.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
chmod +x "$SCRIPT_DIR"/*.sh
echo "All scripts in $SCRIPT_DIR/ are now executable."

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
