#!/usr/bin/env bash
# ==============================================================================
# Script: Baremetal IPMI Inlet Temperature Audit & CSV Exporter
# Description: Queries server inlet temperatures via IPMI and exports CSV report
# ==============================================================================

set -euo pipefail

LOG_FILE="/var/log/ipmi_temp_audit.log"
exec >> "$LOG_FILE" 2>&1
echo "=== Script execution started at $(date -u '+%Y-%m-%d %H:%M:%S UTC') ==="

IPMI_PASS_FILE="${HOME}/.ipmi_password"
CSV_INPUT="${1:-/var/tmp/ipmi_nodes.csv}"
OUTPUT_DIR="${HOME}/HealthCheckFiles"

if [[ ! -f "$IPMI_PASS_FILE" ]]; then
    echo "Error: IPMI password file not found at $IPMI_PASS_FILE" >&2
    exit 1
fi

if [[ ! -f "$CSV_INPUT" ]]; then
    echo "Error: Input CSV file not found at $CSV_INPUT (Format: IP,HOSTNAME)" >&2
    exit 1
fi

mkdir -p "$OUTPUT_DIR"
IPMI_PASSWORD=$(cat "$IPMI_PASS_FILE")
TIMESTAMP=$(date '+%Y%m%d-%H%M00')
OUTPUT_FILE="${OUTPUT_DIR}/cluster-temperature-${TIMESTAMP}.csv"

echo "TIMESTAMP,IPMI_IP,HOSTNAME,RACK,INLET_TEMP_C" > "$OUTPUT_FILE"

while IFS=',' read -r ip hostname; do
    ip="${ip//[[:space:]]/}"
    hostname="${hostname//[[:space:]]/}"
    [[ -z "$ip" || -z "$hostname" ]] && continue

    rack=$(echo "$hostname" | grep -oP 'R\K\d+' || echo "UNKNOWN_RACK")
    temperature=$(sudo ipmitool -I lanplus -H "$ip" -U root -P "$IPMI_PASSWORD" sdr type 'Temperature' 2>/dev/null | \
                  grep -i 'Inlet' | awk -F '|' '{print $5}' | tr -d 'degrees C ' || echo "N/A")

    echo "$(date '+%Y-%m-%d %H:%M:00'),$ip,$hostname,$rack,$temperature" >> "$OUTPUT_FILE"
done < "$CSV_INPUT"

echo "✅ Temperature report generated successfully at: $OUTPUT_FILE"
