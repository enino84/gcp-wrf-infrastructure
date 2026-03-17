#!/bin/bash
# run_cycle.sh
# Full daily WRF cycle:
#   1) Update namelists
#   2) Download GFS
#   3) Run WPS
#   4) Run WRF
#   5) Wait for WRF completion
#   6) Run postprocess + upload to GCS

set -euo pipefail

# =========================
# Phase 0: Configuration
# =========================
TODAY_COMPACT=$(TZ=America/Bogota date +%Y%m%d)
TODAY=$(TZ=America/Bogota date +%Y-%m-%d)
TOMORROW=$(TZ=America/Bogota date -d "+1 day" +%Y-%m-%d)

CASE_NAME="colombia-27km-$TODAY_COMPACT"
NAMELIST_WPS="namelist_examples/colombia/namelist.wps"
NAMELIST_WRF="namelist_examples/colombia/namelist.input"

APP_ID="wrf-colombia-27km"
CONTEXT="WRF Colombia 27km"
CONFIG_JSON="colombia.json"
DATA_ROOT="/mnt/data"
GCS_BUCKET="learn-da-data"
NUM_PROCS=4

CASE_DIR="$DATA_ROOT/cases/$CASE_NAME"
LOG_FILE="$CASE_DIR/simulation.log"

echo "=================================================="
echo "RUN CYCLE START"
echo "Case        : $CASE_NAME"
echo "Today       : $TODAY"
echo "Tomorrow    : $TOMORROW"
echo "Data root   : $DATA_ROOT"
echo "App ID      : $APP_ID"
echo "Config      : $CONFIG_JSON"
echo "GCS Bucket  : $GCS_BUCKET"
echo "MPI Procs   : $NUM_PROCS"
echo "=================================================="
echo ""

# =========================
# Phase 1: Update namelist.wps
# =========================
echo "[Phase 1/6] Updating namelist.wps ..."
sed -i -E "s|^[[:space:]]*start_date[[:space:]]*=.*| start_date = '${TODAY}_12:00:00',|" "$NAMELIST_WPS"
sed -i -E "s|^[[:space:]]*end_date[[:space:]]*=.*| end_date   = '${TOMORROW}_12:00:00',|" "$NAMELIST_WPS"

echo "Updated $NAMELIST_WPS:"
grep -E "start_date|end_date" "$NAMELIST_WPS"
echo ""

# =========================
# Phase 2: Update namelist.input
# =========================
echo "[Phase 2/6] Updating namelist.input ..."
sed -i -E "s|^[[:space:]]*start_year[[:space:]]*=.*| start_year = $(TZ=America/Bogota date +%Y),|" "$NAMELIST_WRF"
sed -i -E "s|^[[:space:]]*start_month[[:space:]]*=.*| start_month = $(TZ=America/Bogota date +%m),|" "$NAMELIST_WRF"
sed -i -E "s|^[[:space:]]*start_day[[:space:]]*=.*| start_day = $(TZ=America/Bogota date +%d),|" "$NAMELIST_WRF"
sed -i -E "s|^[[:space:]]*start_hour[[:space:]]*=.*| start_hour = 12,|" "$NAMELIST_WRF"
sed -i -E "s|^[[:space:]]*start_minute[[:space:]]*=.*| start_minute = 00,|" "$NAMELIST_WRF"
sed -i -E "s|^[[:space:]]*start_second[[:space:]]*=.*| start_second = 00,|" "$NAMELIST_WRF"

sed -i -E "s|^[[:space:]]*end_year[[:space:]]*=.*| end_year = $(TZ=America/Bogota date -d '+1 day' +%Y),|" "$NAMELIST_WRF"
sed -i -E "s|^[[:space:]]*end_month[[:space:]]*=.*| end_month = $(TZ=America/Bogota date -d '+1 day' +%m),|" "$NAMELIST_WRF"
sed -i -E "s|^[[:space:]]*end_day[[:space:]]*=.*| end_day = $(TZ=America/Bogota date -d '+1 day' +%d),|" "$NAMELIST_WRF"
sed -i -E "s|^[[:space:]]*end_hour[[:space:]]*=.*| end_hour = 12,|" "$NAMELIST_WRF"
sed -i -E "s|^[[:space:]]*end_minute[[:space:]]*=.*| end_minute = 00,|" "$NAMELIST_WRF"
sed -i -E "s|^[[:space:]]*end_second[[:space:]]*=.*| end_second = 00,|" "$NAMELIST_WRF"

echo "Updated $NAMELIST_WRF:"
grep -E "start_year|start_month|start_day|start_hour|end_year|end_month|end_day|end_hour" "$NAMELIST_WRF"
echo ""

# =========================
# Phase 3: Download GFS
# =========================
echo "[Phase 3/6] Downloading GFS ..."
./scripts/download_gfs.sh "$TODAY_COMPACT" "$CASE_NAME" "$DATA_ROOT"

echo "Validating GFS files ..."
GFS_COUNT=$(find "$CASE_DIR/gfs_data" -maxdepth 1 -name "*.grib2" | wc -l)
echo "GFS files found: $GFS_COUNT"

if [ "$GFS_COUNT" -lt 9 ]; then
    echo "ERROR: Expected at least 9 GRIB2 files, found $GFS_COUNT"
    exit 1
fi
echo ""

# =========================
# Phase 4: Run WPS
# =========================
echo "[Phase 4/6] Running WPS ..."
./scripts/run_wps.sh "$CASE_NAME" "$NAMELIST_WPS" "" "$DATA_ROOT"

echo "Validating met_em files ..."
MET_COUNT=$(find "$CASE_DIR/output" -maxdepth 1 -name "met_em.d01.*" | wc -l)
echo "met_em files found: $MET_COUNT"

if [ "$MET_COUNT" -eq 0 ]; then
    echo "ERROR: No met_em files found after WPS"
    exit 1
fi
echo ""

# =========================
# Phase 5: Run WRF
# =========================
echo "[Phase 5/6] Running WRF ..."
./scripts/run_wrf_nohup.sh "$CASE_NAME" "$NAMELIST_WRF" "$DATA_ROOT" "$NUM_PROCS"

echo "WRF finished. Validating outputs ..."
WRFOUT_COUNT=$(find "$CASE_DIR/output" -maxdepth 1 -name "wrfout_d01_*" | wc -l)
echo "wrfout files found: $WRFOUT_COUNT"

if [ "$WRFOUT_COUNT" -eq 0 ]; then
    echo "ERROR: WRF completed but no wrfout_d01_* files were found"
    exit 1
fi
echo ""

# =========================
# Phase 6: Postprocess + GCS
# =========================
echo "[Phase 6/6] Running postprocess + GCS upload ..."
./scripts/run_postprocess_gcs.sh \
    "$CASE_NAME" \
    "$APP_ID" \
    "$CONTEXT" \
    "$CONFIG_JSON" \
    "$DATA_ROOT" \
    "$GCS_BUCKET"

echo ""
echo "=================================================="
echo "RUN CYCLE COMPLETE"
echo "Case         : $CASE_NAME"
echo "Case folder  : $CASE_DIR"
echo "Outputs      : $CASE_DIR/output"
echo "Plots        : $CASE_DIR/plots_gcs"
echo "Log          : $LOG_FILE"
echo "GCS          : gs://$GCS_BUCKET/apps/$APP_ID/runs/"
echo "=================================================="