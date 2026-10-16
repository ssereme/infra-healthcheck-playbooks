#!/usr/bin/env bash
# ==============================================================================
# Script: Kubernetes / NCS & CNF Pre-Maintenance Audit
# Author: Soumaila Sereme
# Description: Validates node states, Pod health, PVCs, and PDBs prior to MOP
# ==============================================================================

set -euo pipefail

echo "================================================================="
echo " Starting Kubernetes / NCS Cluster Pre-Maintenance Healthcheck"
echo " Timestamp: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "================================================================="

echo -e "\n[1/5] Checking Worker & Master Node Readiness..."
if kubectl get nodes | grep -qE "NotReady|SchedulingDisabled"; then
    echo "⚠️  WARNING: Nodes in NotReady or Cordoned state detected:"
    kubectl get nodes -o wide | grep -E "NAME|NotReady|SchedulingDisabled"
else
    echo "✅ All cluster nodes are Ready and schedulable."
fi

echo -e "\n[2/5] Auditing Non-Running Pods across all Namespaces..."
NON_RUNNING=$(kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded --no-headers 2>/dev/null | wc -l | tr -d ' ')
if [ "$NON_RUNNING" -gt 0 ]; then
    echo "⚠️  WARNING: Found $NON_RUNNING non-running pod(s):"
    kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded
else
    echo "✅ All active pods are in Running or Succeeded state."
fi

echo -e "\n[3/5] Validating PersistentVolumeClaims (PVC)..."
UNBOUND_PVC=$(kubectl get pvc -A --no-headers 2>/dev/null | grep -v "Bound" | wc -l | tr -d ' ')
if [ "$UNBOUND_PVC" -gt 0 ]; then
    echo "⚠️  WARNING: Unbound PVCs detected:"
    kubectl get pvc -A | grep -v "Bound"
else
    echo "✅ All PersistentVolumeClaims are Bound."
fi

echo -e "\n[4/5] Inspecting PodDisruptionBudgets (PDB) before Node Drain..."
kubectl get pdb -A

echo -e "\n[5/5] Checking Ceph / Rook Storage Class Availability..."
kubectl get sc

echo -e "\n================================================================="
echo " Pre-Maintenance Audit Completed."
echo "================================================================="