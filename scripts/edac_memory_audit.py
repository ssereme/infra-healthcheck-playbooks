#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
Script: Proactive EDAC/MCE Memory Error Auditor & OpenStack VM Mapper
Author: Soumaila Sereme
Compatibility: Python 3.6.8+ (RHEL / CentOS / Nokia CBIS Undercloud)
Description:
  - Collects EDAC & MCE memory error logs across Overcloud nodes via Ansible.
  - Extracts chronological timestamps, Hostname, Memory Controller (MC),
    Error Type (CE/UE), and physical DIMM slot (FRU).
  - Correlates degraded hosts with active OpenStack VMs via 'overcloudrc'.
  - Generates HTML (with KPI cards & visual slot bars), CSV, and TXT reports.
  - Enforces automated 3-day log/report rotation.
==============================================================================
"""

import csv
import datetime
import glob
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict

# ==============================================================================
# Configuration & Paths
# ==============================================================================
OUTPUT_DIR = os.environ.get("EDAC_REPORT_DIR", "/home/stack/edac_reports")
OVERCLOUDRC_PATH = os.environ.get("OVERCLOUDRC_PATH", "/home/stack/overcloudrc")
ANSIBLE_TARGET = os.environ.get("ANSIBLE_TARGET", "all")
RETENTION_DAYS = 3

# Regex patterns for Linux kernel EDAC / MCE log lines
# Example:
# Oct 18 14:22:01 overcloud-ovscompute-0 kernel: EDAC MC0: 1 CE memory read error on CPU_SrcID#0_Ha#0_Chan#1_DIMM#0 (channel:1 slot:0 page:0x123 offset:0x0 grain:32 syndrome:0x0 - area:DRAM err_code:0001:0091 socket:0 ha:0 channel_mask:2 rank:1)
EDAC_LINE_REGEX = re.compile(
    r"^(?P<month>[A-Z][a-z]{2})\s+(?P<day>\d+)\s+(?P<time>\d{2}:\d{2}:\d{2})\s+"
    r"(?P<host>\S+)\s+kernel:.*?"
    r"EDAC\s+(?P<mc>MC\d+):\s+(?P<count>\d+)\s+(?P<err_type>CE|UE)\s+"
    r"(?P<msg>.*?on\s+(?P<fru>[^\s\(]+).*)$"
)


def ensure_output_dir(directory):
    if not os.path.exists(directory):
        os.makedirs(directory, mode=0o755)


def cleanup_old_reports(directory, days=RETENTION_DAYS):
    """Deletes archived report files older than `days` days."""
    now = datetime.datetime.now().timestamp()
    cutoff = now - (days * 86400)
    patterns = ["*.html", "*.csv", "*.txt"]
    removed = 0
    for pattern in patterns:
        for filepath in glob.glob(os.path.join(directory, pattern)):
            try:
                if os.path.getmtime(filepath) < cutoff:
                    os.remove(filepath)
                    removed += 1
            except OSError:
                pass
    return removed


def run_ansible_edac_collect(target_group):
    """
    Executes a batch shell command across all nodes via Ansible (or Salt fallback)
    to retrieve EDAC memory error lines from /var/log/messages.
    """
    remote_cmd = (
        "grep -h 'EDAC MC' /var/log/messages* 2>/dev/null || "
        "journalctl -k --no-pager 2>/dev/null | grep 'EDAC MC' || true"
    )
    cmd = [
        "ansible",
        target_group,
        "-b",
        "-m",
        "shell",
        "-a",
        remote_cmd,
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=180,
        )
        return proc.stdout
    except Exception as exc:
        sys.stderr.write("[WARN] Ansible execution warning: {}\n".format(exc))
        return ""


def parse_edac_logs(raw_output):
    """
    Parses raw syslog lines into structured dictionaries sorted chronologically.
    Compatible with Python 3.6.8.
    """
    current_year = datetime.datetime.now().year
    records = []

    for line in raw_output.splitlines():
        line_str = line.strip()
        if "EDAC MC" not in line_str:
            continue

        match = EDAC_LINE_REGEX.search(line_str)
        if not match:
            continue

        data = match.groupdict()
        ts_str = "{} {} {} {}".format(
            current_year, data["month"], int(data["day"]), data["time"]
        )
        try:
            dt_obj = datetime.datetime.strptime(ts_str, "%Y %b %d %H:%M:%S")
        except ValueError:
            dt_obj = datetime.datetime.now()

        records.append(
            {
                "datetime": dt_obj,
                "timestamp": dt_obj.strftime("%Y-%m-%d %H:%M:%S"),
                "host": data["host"],
                "mc": data["mc"],
                "count": int(data["count"]),
                "err_type": data["err_type"],
                "fru": data["fru"],
                "details": data["msg"].strip(),
            }
        )

    # Sort chronologically (most recent first)
    records.sort(key=lambda x: x["datetime"], reverse=True)
    return records


def get_openstack_vms_by_host(affected_hosts):
    """
    Sources overcloudrc and queries OpenStack Nova for active VMs running
    on the affected compute hosts.
    """
    host_vm_map = defaultdict(list)
    if not affected_hosts or not os.path.exists(OVERCLOUDRC_PATH):
        return host_vm_map

    shell_cmd = (
        "source {} && "
        "openstack server list --all-projects --long "
        "-f csv -c ID -c Name -c Status -c 'Host'"
    ).format(OVERCLOUDRC_PATH)

    try:
        proc = subprocess.run(
            ["/bin/bash", "-c", shell_cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=60,
        )
        if proc.returncode != 0:
            return host_vm_map

        reader = csv.DictReader(proc.stdout.splitlines())
        for row in reader:
            vm_host = (row.get("Host") or "").strip()
            vm_host_short = vm_host.split(".")[0]
            for affected in affected_hosts:
                affected_short = affected.split(".")[0]
                if vm_host and (affected_short == vm_host_short or affected in vm_host):
                    host_vm_map[affected].append(
                        {
                            "id": row.get("ID", ""),
                            "name": row.get("Name", ""),
                            "status": row.get("Status", ""),
                        }
                    )
    except Exception as exc:
        sys.stderr.write("[WARN] OpenStack VM correlation skipped: {}\n".format(exc))

    return host_vm_map


def generate_reports(records, host_vm_map, timestamp_tag):
    """Generates CSV, TXT, and HTML reports with KPI cards and slot bars."""
    csv_path = os.path.join(OUTPUT_DIR, "edac_report_{}.csv".format(timestamp_tag))
    txt_path = os.path.join(OUTPUT_DIR, "edac_report_{}.txt".format(timestamp_tag))
    html_path = os.path.join(OUTPUT_DIR, "edac_report_{}.html".format(timestamp_tag))
    latest_html = os.path.join(OUTPUT_DIR, "edac_report_latest.html")

    # 1. Generate CSV Report
    with open(csv_path, mode="w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(
            ["TIMESTAMP", "HOSTNAME", "MEMORY_CONTROLLER", "ERROR_TYPE", "ERROR_COUNT", "FRU_SLOT", "DETAILS"]
        )
        for rec in records:
            writer.writerow(
                [
                    rec["timestamp"],
                    rec["host"],
                    rec["mc"],
                    rec["err_type"],
                    rec["count"],
                    rec["fru"],
                    rec["details"],
                ]
            )

    # Aggregations for KPI & Slot Visualization
    total_events = len(records)
    total_ce = sum(r["count"] for r in records if r["err_type"] == "CE")
    total_ue = sum(r["count"] for r in records if r["err_type"] == "UE")
    affected_hosts = sorted(list({r["host"] for r in records}))

    slot_counter = Counter()
    for r in records:
        key = "{} | {} ({})".format(r["host"], r["fru"], r["mc"])
        slot_counter[key] += r["count"]

    # 2. Generate Plain Text Report
    with open(txt_path, mode="w", encoding="utf-8") as txtfile:
        txtfile.write("========================================================================\n")
        txtfile.write(" EDAC / MCE MEMORY ERROR AUDIT REPORT - {}\n".format(timestamp_tag))
        txtfile.write("========================================================================\n")
        txtfile.write("Affected Hosts : {}\n".format(len(affected_hosts)))
        txtfile.write("Total CE Count : {}\n".format(total_ce))
        txtfile.write("Total UE Count : {}\n\n".format(total_ue))

        txtfile.write("--- TOP AFFECTED DIMM SLOTS (FRU) ---\n")
        for slot_key, cnt in slot_counter.most_common():
            txtfile.write("  {:55s} : {} errors\n".format(slot_key, cnt))

        txtfile.write("\n--- IMPACTED OPENSTACK VMs PER HOST ---\n")
        for h in affected_hosts:
            vms = host_vm_map.get(h, [])
            txtfile.write("  Host: {} ({} running VMs)\n".format(h, len(vms)))
            for vm in vms:
                txtfile.write("    - {} | {} [{}]\n".format(vm["id"], vm["name"], vm["status"]))

        txtfile.write("\n--- CHRONOLOGICAL EVENT LOG ---\n")
        for r in records:
            txtfile.write(
                "[{}] {:30s} | {:4s} | {:2s} (x{}) | {:30s}\n".format(
                    r["timestamp"], r["host"], r["mc"], r["err_type"], r["count"], r["fru"]
                )
            )

    # 3. Generate HTML Dashboard Report
    max_slot_val = max(slot_counter.values()) if slot_counter else 1
    slot_bars_html = ""
    for slot_key, cnt in slot_counter.most_common(15):
        pct = int((float(cnt) / float(max_slot_val)) * 100)
        slot_bars_html += """
        <div class="bar-row">
          <div class="bar-label">{label}</div>
          <div class="bar-track">
            <div class="bar-fill" style="width: {pct}%;">{cnt}</div>
          </div>
        </div>
        """.format(label=slot_key, pct=max(pct, 8), cnt=cnt)

    vm_rows_html = ""
    for h in affected_hosts:
        vms = host_vm_map.get(h, [])
        if not vms:
            vm_rows_html += "<tr><td><b>{}</b></td><td colspan='3'>No active OpenStack VMs found (or non-compute node)</td></tr>".format(h)
        else:
            for vm in vms:
                vm_rows_html += "<tr><td><b>{}</b></td><td><code>{}</code></td><td>{}</td><td>{}</td></tr>".format(
                    h, vm["id"], vm["name"], vm["status"]
                )

    log_rows_html = ""
    for r in records[:500]:
        badge_class = "badge-ue" if r["err_type"] == "UE" else "badge-ce"
        log_rows_html += """
        <tr>
          <td>{ts}</td>
          <td><b>{host}</b></td>
          <td>{mc}</td>
          <td><span class="badge {bclass}">{etype}</span></td>
          <td>{cnt}</td>
          <td><code>{fru}</code></td>
          <td>{details}</td>
        </tr>
        """.format(
            ts=r["timestamp"],
            host=r["host"],
            mc=r["mc"],
            bclass=badge_class,
            etype=r["err_type"],
            cnt=r["count"],
            fru=r["fru"],
            details=r["details"],
        )

    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>EDAC Memory Error Audit Report</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; background: #f4f6f9; color: #1e293b; margin: 24px; }}
  h1, h2 {{ color: #0f172a; }}
  .kpi-grid {{ display: flex; gap: 16px; margin-bottom: 24px; }}
  .kpi-card {{ background: #fff; padding: 16px 24px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); flex: 1; border-left: 5px solid #3b82f6; }}
  .kpi-card.warn {{ border-left-color: #f59e0b; }}
  .kpi-card.crit {{ border-left-color: #ef4444; }}
  .kpi-title {{ font-size: 12px; text-transform: uppercase; color: #64748b; font-weight: 600; }}
  .kpi-value {{ font-size: 28px; font-weight: 700; margin-top: 4px; }}
  .panel {{ background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); margin-bottom: 24px; }}
  .bar-row {{ display: flex; align-items: center; margin-bottom: 10px; font-size: 13px; }}
  .bar-label {{ width: 340px; font-family: monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .bar-track {{ flex: 1; background: #e2e8f0; border-radius: 4px; overflow: hidden; height: 22px; }}
  .bar-fill {{ background: #2563eb; color: #fff; font-weight: 600; font-size: 12px; line-height: 22px; padding-left: 8px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ background: #1e293b; color: #fff; text-align: left; padding: 10px; }}
  td {{ padding: 8px 10px; border-bottom: 1px solid #e2e8f0; }}
  tr:nth-child(even) {{ background: #f8fafc; }}
  .badge {{ padding: 2px 8px; border-radius: 4px; font-weight: 700; font-size: 11px; }}
  .badge-ce {{ background: #fef3c7; color: #b45309; }}
  .badge-ue {{ background: #fee2e2; color: #b91c1c; }}
</style>
</head>
<body>
  <h1>Telco Cloud — EDAC / DIMM Memory Error Audit</h1>
  <p>Generated: <b>{ts_now}</b> | Retention Policy: <b>{ret} Days</b></p>

  <div class="kpi-grid">
    <div class="kpi-card">
      <div class="kpi-title">Affected Nodes</div>
      <div class="kpi-value">{hosts_cnt}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-title">Total Log Events</div>
      <div class="kpi-value">{events_cnt}</div>
    </div>
    <div class="kpi-card warn">
      <div class="kpi-title">Corrected Errors (CE)</div>
      <div class="kpi-value">{ce_cnt}</div>
    </div>
    <div class="kpi-card crit">
      <div class="kpi-title">Uncorrected Errors (UE)</div>
      <div class="kpi-value">{ue_cnt}</div>
    </div>
  </div>

  <div class="panel">
    <h2>Error Occurrences by Physical DIMM Slot (FRU)</h2>
    {slot_bars}
  </div>

  <div class="panel">
    <h2>Impacted OpenStack VMs on Degraded Hosts</h2>
    <table>
      <thead><tr><th>Host</th><th>Instance UUID</th><th>VM Name</th><th>Status</th></tr></thead>
      <tbody>{vm_rows}</tbody>
    </table>
  </div>

  <div class="panel">
    <h2>Chronological EDAC Kernel Events (Latest 500)</h2>
    <table>
      <thead><tr><th>Timestamp</th><th>Host</th><th>MC</th><th>Type</th><th>Count</th><th>FRU / Slot</th><th>Kernel Message</th></tr></thead>
      <tbody>{log_rows}</tbody>
    </table>
  </div>
</body>
</html>
""".format(
        ts_now=timestamp_tag,
        ret=RETENTION_DAYS,
        hosts_cnt=len(affected_hosts),
        events_cnt=total_events,
        ce_cnt=total_ce,
        ue_cnt=total_ue,
        slot_bars=slot_bars_html or "<p>No EDAC errors detected across the cluster.</p>",
        vm_rows=vm_rows_html or "<tr><td colspan='4'>No affected compute hosts.</td></tr>",
        log_rows=log_rows_html or "<tr><td colspan='7'>No EDAC events recorded.</td></tr>",
    )

    with open(html_path, mode="w", encoding="utf-8") as hfile:
        hfile.write(html_content)
    with open(latest_html, mode="w", encoding="utf-8") as lfile:
        lfile.write(html_content)

    return csv_path, txt_path, html_path


def main():
    ensure_output_dir(OUTPUT_DIR)
    timestamp_tag = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    raw_logs = run_ansible_edac_collect(ANSIBLE_TARGET)
    records = parse_edac_logs(raw_logs)

    affected_hosts = sorted(list({r["host"] for r in records}))
    host_vm_map = get_openstack_vms_by_host(affected_hosts)

    csv_p, txt_p, html_p = generate_reports(records, host_vm_map, timestamp_tag)
    purged = cleanup_old_reports(OUTPUT_DIR, days=RETENTION_DAYS)

    print("[OK] EDAC Audit completed. Events={} | Hosts={}".format(len(records), len(affected_hosts)))
    print("  -> HTML : {}".format(html_p))
    print("  -> CSV  : {}".format(csv_p))
    print("  -> TXT  : {}".format(txt_p))
    print("  -> Purged old archives (>{}d): {}".format(RETENTION_DAYS, purged))


if __name__ == "__main__":
    main()