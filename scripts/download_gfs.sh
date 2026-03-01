#!/bin/bash
# download_gfs.sh
# Downloads GFS 0.25-degree GRIB2 files from NOAA NOMADS for a given date.
# Usage: ./scripts/download_gfs.sh <YYYYMMDD> <case_name> [data_root]
# Example: ./scripts/download_gfs.sh 20260227 test001
# Example: ./scripts/download_gfs.sh 20260227 test001 /data/wrf

set -e

CYCLE="12"

if [ -z "$1" ] || [ -z "$2" ]; then
    echo "Usage: $0 <YYYYMMDD> <case_name> [data_root]"
    echo "  YYYYMMDD  : date to download (e.g. 20260227)"
    echo "  case_name : name of the simulation case (e.g. test001)"
    echo "  data_root : optional base path (default: /mnt/data)"
    echo ""
    echo "Example: $0 20260227 test001"
    echo "Example: $0 20260227 test001 /data/wrf"
    exit 1
fi

DATE="$1"
CASE_NAME="$2"
PROJECT_ROOT="${3:-/mnt/data}"
DEST="$PROJECT_ROOT/cases/$CASE_NAME/gfs_data"

mkdir -p "$DEST"

echo "--- Downloading GFS data ---"
echo "Date      : $DATE"
echo "Cycle     : ${CYCLE}Z"
echo "Case      : $CASE_NAME"
echo "Dest      : $DEST"
echo ""

for fhr in 000 003 006 009 012 015 018 021 024; do
    FILE="gfs.t${CYCLE}z.pgrb2.0p25.f${fhr}"
    URL="https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/gfs.${DATE}/${CYCLE}/atmos/${FILE}"
    OUTPUT="${DEST}/gfs_${DATE}_${CYCLE}_${fhr}.grib2"
    echo "Downloading $FILE..."
    curl -L -C - "$URL" -o "$OUTPUT"
done

echo ""
echo "--- Download complete ---"
echo "Files written to: $DEST"
