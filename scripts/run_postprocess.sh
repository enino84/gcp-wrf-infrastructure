#!/bin/bash
# run_postprocess.sh
# Runs the WRF post-processor inside the postprocess container.
# Generates static images, animations, and an HTML report.
#
# Usage: ./scripts/run_postprocess.sh <case_name> [context] [data_root]
#
# Arguments:
#   case_name : simulation case name (e.g. test001)
#   context   : label for titles and report (default: "WRF Simulation")
#   data_root : base data path (default: /mnt/data)
#
# Examples:
#   ./scripts/run_postprocess.sh test001
#   ./scripts/run_postprocess.sh test001 "Colombia"
#   ./scripts/run_postprocess.sh test001 "Barranquilla — 3 km" /data/wrf

set -e

if [ -z "$1" ]; then
    echo "Usage: $0 <case_name> [context] [data_root]"
    echo ""
    echo "  case_name : simulation case name (e.g. test001)"
    echo "  context   : label for report titles (default: 'WRF Simulation')"
    echo "  data_root : base data path (default: /mnt/data)"
    echo ""
    echo "Example: $0 test001 'Colombia'"
    exit 1
fi

CASE_NAME="${1}"
CONTEXT="${2:-WRF Simulation}"
PROJECT_ROOT="${3:-/mnt/data}"
CASE_DIR="$PROJECT_ROOT/cases/$CASE_NAME"
INPUT_DIR="$CASE_DIR/output"
OUTPUT_DIR="$CASE_DIR/plots"

echo "--- Starting post-processing ---"
echo "Case       : $CASE_NAME"
echo "Context    : $CONTEXT"
echo "Input      : $INPUT_DIR"
echo "Output     : $OUTPUT_DIR"
echo ""

# Validate wrfout files exist
if [ -z "$(ls "$INPUT_DIR"/wrfout_d01_* 2>/dev/null)" ]; then
    echo "ERROR: No wrfout_d01_* files found in $INPUT_DIR"
    echo "Did you run run_wrf.sh first?"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

docker run --rm \
    -v "$INPUT_DIR":/data \
    -v "$OUTPUT_DIR":/output \
    postprocess:latest \
    bash -c "
        cd /data && \
        python /postprocess/post_processor.py \
            --input  /data \
            --output /output \
            --context '$CONTEXT'
    "

echo ""
echo "--- Post-processing complete ---"
echo "Products : $OUTPUT_DIR"
echo "Report   : $OUTPUT_DIR/report.html"