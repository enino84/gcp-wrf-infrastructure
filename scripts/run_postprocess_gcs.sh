#!/bin/bash
# run_postprocess_gcs.sh
# Runs the WRF GCS post-processor — generates images/animations and uploads to GCS.
#
# Usage:
#   ./scripts/run_postprocess_gcs.sh <case_name> <app_id> [context] [data_root] [gcs_bucket] [sa_key]
#
# Arguments:
#   case_name  : simulation case name         (e.g. colombia-27km-20260314)
#   app_id     : GCS app identifier           (e.g. wrf-colombia-27km)
#   context    : label for plot titles        (default: "WRF Simulation")
#   data_root  : base data path               (default: /mnt/data)
#   gcs_bucket : GCS bucket name              (default: learn-da-data)
#   sa_key     : path to service account key  (default: none — uses ADC/Workload Identity)
#
# Examples:
#   ./scripts/run_postprocess_gcs.sh colombia-27km-20260314 wrf-colombia-27km "WRF Colombia 27km"
#   ./scripts/run_postprocess_gcs.sh colombia-27km-20260314 wrf-colombia-27km "WRF Colombia 27km" /mnt/data learn-da-data /secrets/sa.json
#   ./scripts/run_postprocess_gcs.sh test003 wrf-colombia-27km "Test 27km" /mnt/data learn-da-data

set -e

if [ -z "$1" ] || [ -z "$2" ]; then
    echo "Usage: $0 <case_name> <app_id> [context] [data_root] [gcs_bucket] [sa_key]"
    echo ""
    echo "  case_name  : e.g. colombia-27km-20260314"
    echo "  app_id     : e.g. wrf-colombia-27km | wrf-caribe-9km | wrf-barranquilla-3km"
    echo "  context    : label for titles (default: 'WRF Simulation')"
    echo "  data_root  : base data path (default: /mnt/data)"
    echo "  gcs_bucket : GCS bucket (default: learn-da-data)"
    echo "  sa_key     : /path/to/sa.json (optional, uses Workload Identity if omitted)"
    exit 1
fi

CASE_NAME="$1"
APP_ID="$2"
CONTEXT="${3:-WRF Simulation}"
PROJECT_ROOT="${4:-/mnt/data}"
GCS_BUCKET="${5:-learn-da-data}"
SA_KEY="${6:-}"

CASE_DIR="$PROJECT_ROOT/cases/$CASE_NAME"
INPUT_DIR="$CASE_DIR/output"
OUTPUT_DIR="$CASE_DIR/plots_gcs"

echo "========================================"
echo "  WRF GCS Post-processor"
echo "  Case     : $CASE_NAME"
echo "  App ID   : $APP_ID"
echo "  Context  : $CONTEXT"
echo "  Input    : $INPUT_DIR"
echo "  Output   : $OUTPUT_DIR"
echo "  Bucket   : gs://$GCS_BUCKET"
echo "  GCS path : apps/$APP_ID/runs/..."
echo "========================================"
echo ""

# Validate wrfout files
if [ -z "$(ls "$INPUT_DIR"/wrfout_d01_* 2>/dev/null)" ]; then
    echo "ERROR: No wrfout_d01_* files found in $INPUT_DIR"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

# Build docker run command
DOCKER_ARGS=(
    "--rm"
    "--mount" "type=bind,source=$INPUT_DIR,target=/data"
    "--mount" "type=bind,source=$OUTPUT_DIR,target=/output"
)

# Mount service account key if provided
if [ -n "$SA_KEY" ]; then
    echo "Auth: service account key → $SA_KEY"
    DOCKER_ARGS+=("-v" "$SA_KEY:/secrets/sa.json:ro")
    DOCKER_ARGS+=("-e" "GOOGLE_APPLICATION_CREDENTIALS=/secrets/sa.json")
else
    echo "Auth: Application Default Credentials (Workload Identity or gcloud ADC)"
    # Mount gcloud ADC if available locally
    if [ -f "$HOME/.config/gcloud/application_default_credentials.json" ]; then
        DOCKER_ARGS+=("-v" "$HOME/.config/gcloud:/root/.config/gcloud:ro")
    fi
fi

docker run "${DOCKER_ARGS[@]}" \
    postprocess-gcs:latest \
    python /postprocess/post_processor_gcs.py \
        --input   /data \
        --output  /output \
        --app     "$APP_ID" \
        --context "$CONTEXT" \
        --gcs-bucket "$GCS_BUCKET"

echo ""
echo "========================================"
echo "  Done!"
echo "  Local  : $OUTPUT_DIR"
echo "  GCS    : gs://$GCS_BUCKET/apps/$APP_ID/runs/"
echo "========================================"
