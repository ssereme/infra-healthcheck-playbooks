-- ==============================================================================
-- SQL Query: Comprehensive OpenStack VM & Hypervisor Capacity Report
-- Usage: sudo podman exec -i galera-bundle-podman-0 mysql < nova_capacity_report.sql > vm_report.csv
-- ==============================================================================

SELECT
    nova.instances.availability_zone AS AZ,
    nova.instances.host AS Host,
    keystone.project.name AS 'Project Name',
    nova.instances.uuid AS VM_UUID,
    nova.instances.display_name AS 'Instance Name',
    nova.instances.memory_mb AS 'VM RAM (MB)',
    nova.instances.vcpus AS 'VM vCPUs',
    nova_api.instance_group_member.id AS 'Anti-Affinity ID',
    nova_api.instance_groups.uuid AS 'Anti-Affinity UUID',
    nova_api.instance_groups.name AS 'Affinity Group Name',
    nova_api.flavors.name AS 'Flavor Name',
    glance.images.name AS 'Image Name',
    nova.compute_nodes.running_vms AS 'Host Running VMs',
    nova.compute_nodes.vcpus AS 'Host Total vCPUs',
    nova.compute_nodes.vcpus_used AS 'Host Used vCPUs',
    nova.compute_nodes.memory_mb / 1024 AS 'Host Total RAM (GB)',
    nova.compute_nodes.memory_mb_used / 1024 AS 'Host Used RAM (GB)',
    nova.compute_nodes.free_ram_mb / 1024 AS 'Host Free RAM (GB)',
    nova.compute_nodes.local_gb / 1024 AS 'Host Total Disk (TB)',
    nova.compute_nodes.local_gb_used / 1024 AS 'Host Used Disk (TB)',
    nova.compute_nodes.free_disk_gb / 1024 AS 'Host Free Disk (TB)'
FROM
    nova.instances
LEFT JOIN nova.compute_nodes
    ON nova.instances.host = nova.compute_nodes.hypervisor_hostname
LEFT JOIN nova_api.instance_group_member
    ON nova.instances.uuid = nova_api.instance_group_member.instance_uuid
LEFT JOIN nova_api.instance_groups
    ON nova_api.instance_group_member.group_id = nova_api.instance_groups.id
LEFT JOIN keystone.project
    ON nova.instances.project_id = keystone.project.id
LEFT JOIN glance.images
    ON nova.instances.image_ref = glance.images.id
LEFT JOIN nova_api.flavors
    ON nova.instances.instance_type_id = nova_api.flavors.id
WHERE
    nova.instances.vm_state = 'active';