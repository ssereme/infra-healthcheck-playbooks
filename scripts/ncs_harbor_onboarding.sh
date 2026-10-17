#!/usr/bin/env bash
# ==============================================================================
# Script: NCS Harbor/BCMT Automated Image & Chart Onboarding
# Description: Untars and uploads images/charts to local BCMT or Harbor registry
# Usage: ./ncs_harbor_onboarding.sh [local|local_chart|harbor_chart] <tenant_name>
# ==============================================================================

set -euo pipefail

NOW=$(date "+%y-%m-%d_%H-%M-%S")
LOG_FILE="ncm_onboarding_$NOW.log"
ERR_FILE="ncm_onboarding_${NOW}_err.log"
RETRY_LIMIT=3
WAIT_SECONDS=5

DIR_IMAGES="../IMAGES"
DIR_CHARTS="../CHARTS"

logmsg() {
    echo -e "$(date '+%Y/%m/%d %H:%M:%S'): $1" | tee -a "$LOG_FILE"
}

print_usage() {
    echo "Usage Examples:"
    echo "  1. Onboard images to default registry:  $0 <tenant_name>"
    echo "  2. Onboard charts to Harbor registry:   $0 harbor_chart <tenant_name>"
    echo "  3. Onboard charts to BCMT local:        $0 local_chart"
}

if [[ "$#" -eq 0 || "$1" == "-h" || "$1" == "--help" ]]; then
    print_usage
    exit 0
fi

# Directory checks
[[ -d "$DIR_IMAGES" ]] || { logmsg "ERROR: $DIR_IMAGES does not exist"; exit 1; }
[[ -d "$DIR_CHARTS" ]] || { logmsg "ERROR: $DIR_CHARTS does not exist"; exit 1; }

# Untar logic (Skip for charts)
if [[ "$1" != "local_chart" && "$1" != "harbor_chart" ]]; then
    IMAGE_COUNT=$(ls -1 "$DIR_IMAGES"/*.tar.gz 2>/dev/null | wc -l || echo 0)
    if [[ "$IMAGE_COUNT" -gt 0 ]]; then
        logmsg "Found $IMAGE_COUNT images. Starting extraction..."
        for img in "$DIR_IMAGES"/*.tar.gz; do
            logmsg "Untarring $img..."
            tar -zxvf "$img" -C "$DIR_IMAGES" 2>> "$ERR_FILE" || { logmsg "Failed to extract $img"; exit 1; }
        done
    else
        logmsg "No .tar.gz images found in $DIR_IMAGES."
    fi
fi

# Upload Logic
if [[ "$1" == "local_chart" ]]; then
    logmsg "Starting Chart Onboarding to STABLE repo..."
    for chart in "$DIR_CHARTS"/*.tgz; do
        logmsg "Uploading $chart..."
        ncm app-resource chart add --file_name "$chart" 2>> "$ERR_FILE" || { logmsg "Failed to upload $chart"; exit 1; }
    done
    logmsg "Successfully uploaded charts to STABLE repo."

elif [[ "$1" == "harbor_chart" ]]; then
    if [[ "$#" -ne 2 ]]; then
        logmsg "ERROR: Tenant name required for harbor_chart."
        print_usage
        exit 1
    fi
    TENANT_NAME="$2"
    logmsg "Starting Chart Onboarding to HARBOR repo for tenant: $TENANT_NAME"
    for chart in "$DIR_CHARTS"/*.tgz; do
        logmsg "Uploading $chart..."
        ncs tenant-app-resource chart add --tenant_name "$TENANT_NAME" --file_path "$chart" 2>> "$ERR_FILE" || { logmsg "Failed to upload $chart"; exit 1; }
    done
    logmsg "Successfully uploaded charts to HARBOR repo."

else
    TENANT_NAME="$1"
    logmsg "Starting Image Onboarding to Harbor repo for tenant: $TENANT_NAME"
    RETRY_COUNT=0

    while [[ "$RETRY_COUNT" -le "$RETRY_LIMIT" ]]; do
        for img in "$DIR_IMAGES"/*.tar; do
            logmsg "Uploading $img..."
            if ncs tenant-app-resource image add --tenant_name "$TENANT_NAME" --file_path "$img" 2>> "$ERR_FILE"; then
                logmsg "Successfully uploaded $img."
            else
                if [[ "$RETRY_COUNT" -eq "$RETRY_LIMIT" ]]; then
                    logmsg "ERROR: Failed to upload $img after $RETRY_LIMIT attempts."
                    exit 1
                else
                    ((RETRY_COUNT++))
                    logmsg "Upload failed. Retrying in $WAIT_SECONDS seconds (Attempt $RETRY_COUNT/$RETRY_LIMIT)..."
                    sleep "$WAIT_SECONDS"
                fi
            fi
        done
        break
    done
    
    # Cleanup extracted tars
    rm -f "$DIR_IMAGES"/*.tar
    logmsg "Onboarding complete. Extracted .tar images deleted."
fi
