#!/bin/bash
# run_postprocess_gcs.sh
# Runs the WRF GCS post-processor — generates images/animations and uploads to GCS.
#
# Usage:
#   ./scripts/run_postprocess_gcs.sh <case_name> <app_id> [context] [config] [data_root] [gcs_bucket] [sa_key]
#
# Arguments:
#   case_name  : simulation case name         (e.g. colombia-27km-20260314)
#   app_id     : GCS app identifier           (e.g. wrf-colombia-27km)
#   context    : label for plot titles        (default: "WRF Simulation")
#   config     : config JSON filename         (default: colombia.json)
#   data_root  : base data path               (default: /mnt/data)
#   gcs_bucket : GCS bucket name              (default: learn-da-data)
#   sa_key     : path to service account key  (default: none — uses ADC/Workload Identity)
#
# Examples:
#   ./scripts/run_postprocess_gcs.sh colombia-27km-20260314 wrf-colombia-27km "WRF Colombia 27km"
#   ./scripts/run_postprocess_gcs.sh colombia-27km-20260314 wrf-colombia-27km "WRF Colombia 27km" colombia.json
#   ./scripts/run_postprocess_gcs.sh baq-3km-20260314 wrf-barranquilla-3km "WRF Baq 3km" barranquilla.json /mnt/data learn-da-data /secrets/sa.json

set -euo pipefail

if [ $# -lt 2 ]; then
    echo "Usage: $0 <case_name> <app_id> [context] [config] [data_root] [gcs_bucket] [sa_key]"
    echo ""
    echo "  case_name  : e.g. colombia-27km-20260314"
    echo "  app_id     : e.g. wrf-colombia-27km | wrf-caribe-9km | wrf-barranquilla-3km"
    echo "  context    : label for titles (default: 'WRF Simulation')"
    echo "  config     : config JSON filename (default: colombia.json)"
    echo "  data_root  : base data path (default: /mnt/data)"
    echo "  gcs_bucket : GCS bucket (default: learn-da-data)"
    echo "  sa_key     : /path/to/sa.json (optional, uses Workload Identity if omitted)"
    exit 1
fi

CASE_NAME="$1"
APP_ID="$2"
CONTEXT="${3:-WRF Simulation}"
CONFIG="${4:-colombia.json}"
PROJECT_ROOT="${5:-/mnt/data}"
GCS_BUCKET="${6:-learn-da-data}"
SA_KEY="${7:-}"

CASE_DIR="$PROJECT_ROOT/cases/$CASE_NAME"
INPUT_DIR="$CASE_DIR/output"
OUTPUT_DIR="$CASE_DIR/plots_gcs"

echo "========================================"
echo "  WRF GCS Post-processor"
echo "  Case     : $CASE_NAME"
echo "  App ID   : $APP_ID"
echo "  Context  : $CONTEXT"
echo "  Config   : $CONFIG"
echo "  Input    : $INPUT_DIR"
echo "  Output   : $OUTPUT_DIR"
echo "  Bucket   : gs://$GCS_BUCKET"
echo "  GCS path : apps/$APP_ID/runs/..."
echo "========================================"
echo ""

if [ ! -d "$INPUT_DIR" ]; then
    echo "ERROR: Input directory does not exist: $INPUT_DIR"
    exit 1
fi

if ! ls "$INPUT_DIR"/wrfout_d01_* >/dev/null 2>&1; then
    echo "ERROR: No wrfout_d01_* files found in $INPUT_DIR"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

DOCKER_ARGS=(
    "--rm"
    "--mount" "type=bind,source=$INPUT_DIR,target=/data"
    "--mount" "type=bind,source=$OUTPUT_DIR,target=/output"
)

if [ -n "$SA_KEY" ]; then
    if [ ! -f "$SA_KEY" ]; then
        echo "ERROR: Service account key file not found: $SA_KEY"
        exit 1
    fi

    echo "Auth: service account key -> $SA_KEY"
    DOCKER_ARGS+=("-v" "$SA_KEY:/secrets/sa.json:ro")
    DOCKER_ARGS+=("-e" "GOOGLE_APPLICATION_CREDENTIALS=/secrets/sa.json")
else
    echo "Auth: Application Default Credentials (Workload Identity or gcloud ADC)"
    if [ -f "$HOME/.config/gcloud/application_default_credentials.json" ]; then
        DOCKER_ARGS+=("-v" "$HOME/.config/gcloud:/root/.config/gcloud:ro")
    fi
fi

docker run "${DOCKER_ARGS[@]}" \
    postprocess-gcs:latest \
    python /postprocess/post_processor_gcs.py \
        --input /data \
        --output /output \
        --app "$APP_ID" \
        --config "/postprocess/configs/$CONFIG" \
        --context "$CONTEXT" \
        --gcs-bucket "$GCS_BUCKET"

echo ""
echo "========================================"
echo "  Done!"
echo "  Local  : $OUTPUT_DIR"
echo "  GCS    : gs://$GCS_BUCKET/apps/$APP_ID/runs/"
echo "========================================"