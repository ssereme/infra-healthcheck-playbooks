#!/usr/bin/env bash
# ==============================================================================
# Script: Distributed TCPDump Capture for NCS Edge Nodes
# Description: Initiates parallel packet captures across multiple worker nodes,
#              retrieves the PCAPs, and archives them locally.
# ==============================================================================

set -euo pipefail

# Configuration
CLUSTER_PREFIX="ncs-cluster"
EDGE_NODES=(
    "worker-edge-01.cluster.local"
    "worker-edge-02.cluster.local"
    "worker-edge-03.cluster.local"
    "worker-edge-04.cluster.local"
)
SSH_KEY="/usr/local/scripts/admin-keypair.pem"
SSH_USER="cloud-user"

REMOTE_DIR="/tmp/nrdpcaps"
LOCAL_DIR="/data0/core-admin/pcaps/nrdpcaps"
ARCHIVE_DIR="/data0/core-admin/pcaps/nrdarch"

# Helper functions
check_and_create_dir() {
    if [ ! -d "$1" ]; then
        mkdir -p "$1"
        chmod 755 "$1"
    fi
}

execute_remote() {
    local node="$1"
    local cmd="$2"
    ssh -q -o StrictHostKeyChecking=no -i "$SSH_KEY" "${SSH_USER}@${node}" "$cmd"
}

# 1. Setup Local Directories
check_and_create_dir "$LOCAL_DIR"
check_and_create_dir "$ARCHIVE_DIR"

# 2. Select Target Nodes
echo "Available Edge Nodes:"
for i in "${!EDGE_NODES[@]}"; do
    echo "$((i+1)). ${EDGE_NODES[$i]}"
done

read -p "Enter node numbers separated by space to capture traffic: " node_nums
SELECTED_NODES=()
for num in $node_nums; do
    SELECTED_NODES+=("${EDGE_NODES[$((num-1))]}")
done

# 3. Prepare Remote Directories
echo -e "\n[*] Preparing remote capture directories..."
for node in "${SELECTED_NODES[@]}"; do
    execute_remote "$node" "sudo mkdir -p $REMOTE_DIR && sudo rm -f $REMOTE_DIR/*.pcap"
done

# 4. Start Captures
echo -e "\n[*] Starting tcpdump on selected nodes (Any interface, size 0)..."
TIMESTAMP=$(date +'%Y-%m-%d_%H-%M')
for node in "${SELECTED_NODES[@]}"; do
    execute_remote "$node" "sudo nohup tcpdump -i any -v -s0 -G700 -w $REMOTE_DIR/${node}_${TIMESTAMP}.pcap > /dev/null 2>&1 &"
done

# 5. Wait for User Termination
echo -e "\n[!] Capturing traffic... Press [ENTER] to STOP captures."
read -r

# 6. Stop Captures & Change Permissions
echo -e "\n[*] Stopping tcpdump processes..."
for node in "${SELECTED_NODES[@]}"; do
    execute_remote "$node" "sudo pkill -f tcpdump || true"
    execute_remote "$node" "sudo chmod 644 $REMOTE_DIR/*.pcap"
done

# 7. Archive Old Local Traces
if ls "$LOCAL_DIR"/*.tar 1> /dev/null 2>&1; then
    mv "$LOCAL_DIR"/*.tar "$ARCHIVE_DIR/"
    find "$ARCHIVE_DIR" -type f -name "*.tar" -mtime +365 -exec rm -f {} \;
fi

# 8. Retrieve PCAPs
echo -e "\n[*] Downloading PCAPs to local directory..."
for node in "${SELECTED_NODES[@]}"; do
    scp -q -o StrictHostKeyChecking=no -i "$SSH_KEY" "${SSH_USER}@${node}:$REMOTE_DIR/*.pcap" "$LOCAL_DIR/"
    execute_remote "$node" "sudo rm -f $REMOTE_DIR/*.pcap"
done

# 9. Compress Downloads
echo -e "\n[*] Compressing PCAPs..."
tar -cf "${LOCAL_DIR}/${CLUSTER_PREFIX}_capture_${TIMESTAMP}.tar" -C "$LOCAL_DIR" ./*.pcap
find "$LOCAL_DIR" -type f -name "*.pcap" -exec rm -f {} \;

echo -e "\n✅ Done. Traces available in $LOCAL_DIR"
