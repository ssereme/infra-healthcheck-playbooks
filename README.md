# Infrastructure Pre/Post-Maintenance Healthchecks

Automated verification playbooks and scripts designed to validate cluster readiness prior to executing Methods of Procedure (MOPs) and confirm service restoration post-intervention.

---

## 📋 1. Ansible Playbook: Pre-Maintenance Cluster Audit (`pre_check.yml`)

This playbook verifies time synchronization (NTP/Chrony), disk capacity on critical mounts, Ceph cluster health, and Pacemaker/Galera state across control and storage nodes.

```yaml
---
- name: Carrier-Grade Cloud Pre-Maintenance Healthcheck
  hosts: cloud_nodes
  become: true
  gather_facts: true

  tasks:
    - name: 1. Check Root and Var Filesystem Capacity (< 80% threshold)
      ansible.builtin.shell: |
        df -h / /var | awk 'NR>1 {gsub("%","",$5); if ($5 > 80) exit 1}'
      register: disk_check
      changed_when: false
      failed_when: disk_check.rc != 0

    - name: 2. Verify Chrony NTP Synchronization
      ansible.builtin.command: chronyc tracking
      register: ntp_status
      changed_when: false
      failed_when: "'Leap status     : Normal' not in ntp_status.stdout"

    - name: 3. Validate Ceph Storage Cluster Health (Monitors Only)
      ansible.builtin.command: ceph health
      register: ceph_health
      changed_when: false
      when: "'ceph_mons' in group_names"
      failed_when: "'HEALTH_ERR' in ceph_health.stdout"

    - name: 4. Summary Report
      ansible.builtin.debug:
        msg: "Node {{ inventory_hostname }} passed pre-maintenance checks successfully."
```

---

## ☸️ 2. Kubernetes / NCS CNF Readiness Check (`k8s_cnf_audit.sh`)

Quick assessment script before performing worker node drain or upgrade operations:

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "=== [1/4] Checking Node Readiness ==="
kubectl get nodes -o wide | grep -v " Ready " && echo "WARNING: Non-ready nodes detected!" || echo "All nodes Ready."

echo "=== [2/4] Identifying Non-Running Pods across all Namespaces ==="
kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded

echo "=== [3/4] Checking PersistentVolumeClaims (PVC) Status ==="
kubectl get pvc -A | grep -v "Bound" || echo "All PVCs are Bound."

echo "=== [4/4] Checking PodDisruptionBudgets (PDB) before Drain ==="
kubectl get pdb -A
```
