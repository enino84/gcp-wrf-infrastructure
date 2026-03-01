#!/bin/bash
# extract_vtable.sh
# Extracts a Vtable from the wps-compiled container and places it in the case directory.
# Vtables map GRIB2 variable codes to WPS field names — they come bundled with WPS source code.
#
# Usage: ./scripts/extract_vtable.sh <case_name> [vtable_name] [data_root]
#
# Arguments:
#   case_name    : simulation case name (e.g. test001)
#   vtable_name  : name of the Vtable to extract (default: Vtable.GFS)
#   data_root    : base data path (default: /mnt/data)
#
# Available Vtables (inside the container at /wrf/WPS/ungrib/Variable_Tables/):
#   Vtable.GFS         — NCEP GFS  ← use this for download_gfs.sh data
#   Vtable.ERA-interim — ECMWF ERA-Interim
#   Vtable.ERA5        — ECMWF ERA5
#   Vtable.NARR        — NCEP NARR
#   Vtable.NAM         — NCEP NAM
#   (and many more — run with --list to see all)
#
# Examples:
#   ./scripts/extract_vtable.sh test001
#   ./scripts/extract_vtable.sh test001 Vtable.GFS
#   ./scripts/extract_vtable.sh test001 Vtable.ERA5
#   ./scripts/extract_vtable.sh test001 Vtable.GFS /data/wrf
#   ./scripts/extract_vtable.sh --list

set -e

if [ "$1" = "--list" ]; then
    echo "Available Vtables inside wps-compiled container:"
    echo ""
    docker run --rm wps-compiled:latest \
        ls /wrf/WPS/ungrib/Variable_Tables/
    exit 0
fi

if [ -z "$1" ]; then
    echo "Usage: $0 <case_name> [vtable_name] [data_root]"
    echo "       $0 --list   (show all available Vtables)"
    echo ""
    echo "  case_name   : simulation case name (e.g. test001)"
    echo "  vtable_name : Vtable to extract (default: Vtable.GFS)"
    echo "  data_root   : base data path    (default: /mnt/data)"
    echo ""
    echo "Example: $0 test001"
    echo "Example: $0 test001 Vtable.ERA5"
    exit 1
fi

CASE_NAME="$1"
VTABLE_NAME="${2:-Vtable.GFS}"
PROJECT_ROOT="${3:-/mnt/data}"
CASE_DIR="$PROJECT_ROOT/cases/$CASE_NAME"
DEST="$CASE_DIR/Vtable"

echo "Extracting $VTABLE_NAME from wps-compiled container..."
docker run --rm wps-compiled:latest \
    cat "/wrf/WPS/ungrib/Variable_Tables/$VTABLE_NAME" \
    > "$DEST"

echo "Vtable written to: $DEST"