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

usage() {
    echo "Usage:"
    echo "  $0 [options]"
    echo ""
    echo "Options:"
    echo "  --case-prefix           Prefix for case name                     (default: colombia-27km)"
    echo "  --namelist-wps          Path to namelist.wps                     (default: namelist_examples/colombia/namelist.wps)"
    echo "  --namelist-wrf          Path to namelist.input                   (default: namelist_examples/colombia/namelist.input)"
    echo "  --app-id                App ID for postprocess/GCS               (default: wrf-colombia-27km)"
    echo "  --context               Context label                            (default: WRF Colombia 27km)"
    echo "  --config-json           Config JSON for postprocess              (default: colombia.json)"
    echo "  --data-root             Base data path                           (default: /mnt/data)"
    echo "  --gcs-bucket            GCS bucket name                          (default: learn-da-data)"
    echo "  --service-account-json  Path to service account JSON             (default: ./sa-learn-da.json)"
    echo "  --num-procs             MPI processes                            (default: 4)"
    echo "  --start-hour            GFS cycle and WRF start hour UTC         (default: 00)"
    echo "  --help                  Show this help"
    exit 1
}

CASE_PREFIX="colombia-27km"
NAMELIST_WPS="namelist_examples/colombia/namelist.wps"
NAMELIST_WRF="namelist_examples/colombia/namelist.input"
APP_ID="wrf-colombia-27km"
CONTEXT="WRF Colombia 27km"
CONFIG_JSON="colombia.json"
DATA_ROOT="/mnt/data"
GCS_BUCKET="learn-da-data"
SERVICE_ACCOUNT_JSON="./sa-learn-da.json"
NUM_PROCS=4
START_HOUR="00"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --case-prefix)
            CASE_PREFIX="$2"
            shift 2
            ;;
        --namelist-wps)
            NAMELIST_WPS="$2"
            shift 2
            ;;
        --namelist-wrf)
            NAMELIST_WRF="$2"
            shift 2
            ;;
        --app-id)
            APP_ID="$2"
            shift 2
            ;;
        --context)
            CONTEXT="$2"
            shift 2
            ;;
        --config-json)
            CONFIG_JSON="$2"
            shift 2
            ;;
        --data-root)
            DATA_ROOT="$2"
            shift 2
            ;;
        --gcs-bucket)
            GCS_BUCKET="$2"
            shift 2
            ;;
        --service-account-json)
            SERVICE_ACCOUNT_JSON="$2"
            shift 2
            ;;
        --num-procs)
            NUM_PROCS="$2"
            shift 2
            ;;
        --start-hour)
            START_HOUR="$2"
            shift 2
            ;;
        --help)
            usage
            ;;
        *)
            echo "ERROR: Unknown argument: $1"
            usage
            ;;
    esac
done

TODAY_COMPACT=$(TZ=America/Bogota date +%Y%m%d)
TODAY=$(TZ=America/Bogota date +%Y-%m-%d)
TOMORROW=$(TZ=America/Bogota date -d "+1 day" +%Y-%m-%d)

CASE_NAME="${CASE_PREFIX}-${TODAY_COMPACT}"
CASE_DIR="$DATA_ROOT/cases/$CASE_NAME"
LOG_FILE="$CASE_DIR/simulation.log"

mkdir -p "$CASE_DIR"

echo "=================================================="
echo "RUN CYCLE START"
echo "Case        : $CASE_NAME"
echo "Today       : $TODAY"
echo "Tomorrow    : $TOMORROW"
echo "Data root   : $DATA_ROOT"
echo "App ID      : $APP_ID"
echo "Context     : $CONTEXT"
echo "Config      : $CONFIG_JSON"
echo "GCS Bucket  : $GCS_BUCKET"
echo "SA JSON     : $SERVICE_ACCOUNT_JSON"
echo "MPI Procs   : $NUM_PROCS"
echo "Start Hour  : ${START_HOUR}Z"
echo "=================================================="
echo ""

echo "[Phase 1/6] Updating namelist.wps ..."
sed -i -E "s|^[[:space:]]*start_date[[:space:]]*=.*| start_date = '${TODAY}_${START_HOUR}:00:00',|" "$NAMELIST_WPS"
sed -i -E "s|^[[:space:]]*end_date[[:space:]]*=.*| end_date   = '${TOMORROW}_${START_HOUR}:00:00',|" "$NAMELIST_WPS"

echo "Updated $NAMELIST_WPS:"
grep -E "start_date|end_date" "$NAMELIST_WPS"
echo ""

echo "[Phase 2/6] Updating namelist.input ..."
sed -i -E "s|^[[:space:]]*start_year[[:space:]]*=.*| start_year = $(TZ=America/Bogota date +%Y),|" "$NAMELIST_WRF"
sed -i -E "s|^[[:space:]]*start_month[[:space:]]*=.*| start_month = $(TZ=America/Bogota date +%m),|" "$NAMELIST_WRF"
sed -i -E "s|^[[:space:]]*start_day[[:space:]]*=.*| start_day = $(TZ=America/Bogota date +%d),|" "$NAMELIST_WRF"
sed -i -E "s|^[[:space:]]*start_hour[[:space:]]*=.*| start_hour = ${START_HOUR},|" "$NAMELIST_WRF"
sed -i -E "s|^[[:space:]]*start_minute[[:space:]]*=.*| start_minute = 00,|" "$NAMELIST_WRF"
sed -i -E "s|^[[:space:]]*start_second[[:space:]]*=.*| start_second = 00,|" "$NAMELIST_WRF"

sed -i -E "s|^[[:space:]]*end_year[[:space:]]*=.*| end_year = $(TZ=America/Bogota date -d '+1 day' +%Y),|" "$NAMELIST_WRF"
sed -i -E "s|^[[:space:]]*end_month[[:space:]]*=.*| end_month = $(TZ=America/Bogota date -d '+1 day' +%m),|" "$NAMELIST_WRF"
sed -i -E "s|^[[:space:]]*end_day[[:space:]]*=.*| end_day = $(TZ=America/Bogota date -d '+1 day' +%d),|" "$NAMELIST_WRF"
sed -i -E "s|^[[:space:]]*end_hour[[:space:]]*=.*| end_hour = ${START_HOUR},|" "$NAMELIST_WRF"
sed -i -E "s|^[[:space:]]*end_minute[[:space:]]*=.*| end_minute = 00,|" "$NAMELIST_WRF"
sed -i -E "s|^[[:space:]]*end_second[[:space:]]*=.*| end_second = 00,|" "$NAMELIST_WRF"

echo "Updated $NAMELIST_WRF:"
grep -E "start_year|start_month|start_day|start_hour|end_year|end_month|end_day|end_hour" "$NAMELIST_WRF"
echo ""

echo "[Phase 3/6] Downloading GFS ..."
./scripts/download_gfs.sh "$TODAY_COMPACT" "$CASE_NAME" "$DATA_ROOT" "$START_HOUR"

echo "Validating GFS files ..."
GFS_COUNT=$(find "$CASE_DIR/gfs_data" -maxdepth 1 -name "*.grib2" | wc -l)
echo "GFS files found: $GFS_COUNT"

if [ "$GFS_COUNT" -lt 9 ]; then
    echo "ERROR: Expected at least 9 GRIB2 files, found $GFS_COUNT"
    exit 1
fi
echo ""

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

echo "[Phase 5/6] Running WRF ..."
./scripts/run_wrf.sh "$CASE_NAME" "$NAMELIST_WRF" "$DATA_ROOT" "$NUM_PROCS"

echo "WRF finished. Validating outputs ..."
WRFOUT_COUNT=$(find "$CASE_DIR/output" -maxdepth 1 -name "wrfout_d01_*" | wc -l)
echo "wrfout files found: $WRFOUT_COUNT"

if [ "$WRFOUT_COUNT" -eq 0 ]; then
    echo "ERROR: WRF completed but no wrfout_d01_* files were found"
    exit 1
fi
echo ""

echo "[Phase 6/6] Running postprocess + GCS upload ..."
./scripts/run_postprocess_gcs.sh \
    "$CASE_NAME" \
    "$APP_ID" \
    "$CONTEXT" \
    "$CONFIG_JSON" \
    "$DATA_ROOT" \
    "$GCS_BUCKET" \
    "$SERVICE_ACCOUNT_JSON"

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


echo ""
echo "[Cleanup] Cleaning case directory contents..."

rm -rf "${CASE_DIR:?}/"* "${CASE_DIR}/".[!.]* "${CASE_DIR}/"..?*

echo "Cleanup done (directory preserved): $CASE_DIR"