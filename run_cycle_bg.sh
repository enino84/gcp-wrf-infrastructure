#!/bin/bash

set -euo pipefail

CASE_PREFIX="${1:-colombia-27km}"
CONFIG_JSON="${2:-colombia.json}"
APP_ID="${3:-wrf-colombia-27km}"
CONTEXT="${4:-WRF Colombia 27km Forecast}"
NAMELIST_WPS="${5:-namelist_examples/colombia/namelist.wps}"
NAMELIST_WRF="${6:-namelist_examples/colombia/namelist.input}"
SERVICE_ACCOUNT_JSON="${7:-./sa-learn-da.json}"
START_HOUR="${8:-00}"

TODAY=$(TZ=America/Bogota date +%Y%m%d)
TIMESTAMP=$(TZ=America/Bogota date +%Y%m%d_%H%M%S)

CASE_NAME="${CASE_PREFIX}-${TODAY}"
LOG_FILE="$HOME/run_cycle_${CASE_NAME}_${TIMESTAMP}.log"

echo "Launching WRF cycle..."
echo "Case      : $CASE_NAME"
echo "Start hour: ${START_HOUR}Z"
echo "Log       : $LOG_FILE"

nohup ./run_cycle.sh \
    --case-prefix "$CASE_PREFIX" \
    --config-json "$CONFIG_JSON" \
    --app-id "$APP_ID" \
    --context "$CONTEXT" \
    --namelist-wps "$NAMELIST_WPS" \
    --namelist-wrf "$NAMELIST_WRF" \
    --service-account-json "$SERVICE_ACCOUNT_JSON" \
    --start-hour "$START_HOUR" \
    > "$LOG_FILE" 2>&1 &

echo "Started in background (PID: $!)"