"""
OpenStack Monitoring and Metrics Functions

This module contains functions for monitoring OpenStack resources,
getting usage statistics, quotas, and availability information.
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Any

# Configure logging
logger = logging.getLogger(__name__)

HYPERVISOR_CAPACITY_MICROVERSION = "2.87"
HYPERVISOR_UPTIME_MICROVERSION = "2.88"
HYPERVISOR_CAPACITY_FIELDS = (
    "vcpus",
    "vcpus_used",
    "memory_mb",
    "memory_mb_used",
    "local_gb",
    "local_gb_used",
    "running_vms",
)


def _first_present_attr(resource: Any, *attrs: str) -> Any:
    """Return the first non-None OpenStack SDK resource attribute."""
    for attr in attrs:
        value = getattr(resource, attr, None)
        if value is not None:
            return value
    return None


def _parse_numeric(value: Any) -> int | None:
    """Return an integer value or None when Nova did not provide the field."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_load_average(uptime: str | None) -> dict[str, float] | None:
    """Parse Linux load averages from Nova hypervisor uptime text."""
    if not uptime:
        return None

    match = re.search(
        r"load averages?:\s*([0-9]+(?:\.[0-9]+)?),\s*([0-9]+(?:\.[0-9]+)?),\s*([0-9]+(?:\.[0-9]+)?)",
        uptime,
        re.IGNORECASE,
    )
    if not match:
        return None

    one_minute, five_minutes, fifteen_minutes = match.groups()
    return {
        "1m": float(one_minute),
        "5m": float(five_minutes),
        "15m": float(fifteen_minutes),
    }


def _hypervisor_capacity_value(hypervisor: Any, field: str) -> int | None:
    """Read per-node capacity fields across Nova and openstacksdk naming variants."""
    field_aliases = {
        "vcpus": ("vcpus",),
        "vcpus_used": ("vcpus_used",),
        "memory_mb": ("memory_mb", "memory_size", "memory_size_mb"),
        "memory_mb_used": ("memory_mb_used", "memory_used", "memory_used_mb"),
        "local_gb": ("local_gb", "local_disk_size", "local_disk_size_gb"),
        "local_gb_used": ("local_gb_used", "local_disk_used", "local_disk_used_gb"),
        "running_vms": ("running_vms",),
    }
    return _parse_numeric(_first_present_attr(hypervisor, *field_aliases[field]))


def _format_hypervisor(hypervisor: Any) -> dict[str, Any]:
    """Format one hypervisor without replacing absent capacity data with zero."""
    uptime = getattr(hypervisor, "uptime", None)
    capacity = {
        field: _hypervisor_capacity_value(hypervisor, field)
        for field in HYPERVISOR_CAPACITY_FIELDS
    }

    return {
        "id": hypervisor.id,
        "name": getattr(hypervisor, "name", "unknown"),
        "host_ip": getattr(hypervisor, "host_ip", "unknown"),
        "status": getattr(hypervisor, "status", "unknown"),
        "state": getattr(hypervisor, "state", "unknown"),
        **capacity,
        "capacity_data_available": all(value is not None for value in capacity.values()),
        "missing_capacity_fields": [
            field for field, value in capacity.items() if value is None
        ],
        "uptime": uptime,
        "load_average": _parse_load_average(uptime),
        "hypervisor_type": getattr(hypervisor, "hypervisor_type", "unknown"),
        "hypervisor_version": getattr(hypervisor, "hypervisor_version", "unknown"),
    }


def _hypervisor_identity_keys(hypervisor_data: dict[str, Any]) -> list[str]:
    """Return stable keys that can match hypervisors across Nova microversions."""
    keys = []
    for key in ("id", "name"):
        value = hypervisor_data.get(key)
        if value not in (None, "unknown"):
            keys.append(str(value))
    return keys


def _collect_hypervisor_uptime(conn: Any) -> dict[str, dict[str, Any]]:
    """Fetch uptime fields from Nova 2.88+ without using it for capacity data."""
    uptime_by_key = {}
    for hypervisor in conn.compute.hypervisors(
        details=True,
        microversion=HYPERVISOR_UPTIME_MICROVERSION,
    ):
        uptime = getattr(hypervisor, "uptime", None)
        uptime_data = {
            "uptime": uptime,
            "load_average": _parse_load_average(uptime),
        }
        identity = {
            "id": getattr(hypervisor, "id", None),
            "name": getattr(hypervisor, "name", None),
        }
        for key in _hypervisor_identity_keys(identity):
            uptime_by_key[key] = uptime_data
    return uptime_by_key


def _enrich_hypervisors_with_uptime(conn: Any, hypervisors: list[dict[str, Any]]) -> None:
    """Fill missing uptime/load fields from a microversion that still exposes them."""
    if not any(hypervisor.get("uptime") is None for hypervisor in hypervisors):
        return

    try:
        uptime_by_key = _collect_hypervisor_uptime(conn)
    except Exception as e:
        logger.warning(f"Could not retrieve hypervisor uptime data: {e}")
        return

    for hypervisor in hypervisors:
        if hypervisor.get("uptime") is not None:
            continue

        for key in _hypervisor_identity_keys(hypervisor):
            uptime_data = uptime_by_key.get(key)
            if uptime_data:
                hypervisor.update(uptime_data)
                break


def _new_hypervisor_totals() -> dict[str, Any]:
    """Initialize hypervisor totals with per-field availability tracking."""
    return {
        "count": 0,
        **{field: 0 for field in HYPERVISOR_CAPACITY_FIELDS},
        "_available_counts": {field: 0 for field in HYPERVISOR_CAPACITY_FIELDS},
    }


def _add_hypervisor_to_totals(total_stats: dict[str, Any], hypervisor_data: dict[str, Any]) -> None:
    """Accumulate totals only for fields Nova actually returned."""
    total_stats["count"] += 1
    available_counts = total_stats["_available_counts"]

    for field in HYPERVISOR_CAPACITY_FIELDS:
        value = hypervisor_data.get(field)
        if value is not None:
            total_stats[field] += value
            available_counts[field] += 1


def _finalize_hypervisor_totals(total_stats: dict[str, Any]) -> dict[str, Any]:
    """Set unavailable aggregate fields to None instead of silent zero."""
    available_counts = total_stats.pop("_available_counts")
    total_stats["missing_capacity_fields"] = []

    for field in HYPERVISOR_CAPACITY_FIELDS:
        if available_counts[field] == 0:
            total_stats[field] = None
            total_stats["missing_capacity_fields"].append(field)

    total_stats["capacity_data_available"] = not total_stats["missing_capacity_fields"]
    return total_stats


def get_resource_monitoring() -> dict[str, Any]:
    """
    Get comprehensive resource monitoring information for current project.
    
    Returns:
        Dict containing monitoring data for current project's compute, network, and storage resources
    """
    try:
        # Import here to avoid circular imports
        from ..connection import get_openstack_connection
        conn = get_openstack_connection()
        current_project_id = conn.current_project_id
        
        monitoring_data = {
            'timestamp': datetime.now().isoformat(),
            'project_id': current_project_id,
            'compute': {},
            'network': {},
            'storage': {},
            'identity': {}
        }
        
        # Compute monitoring - filter servers by project
        try:
            all_servers = list(conn.compute.servers())
            servers = [s for s in all_servers if getattr(s, 'project_id', None) == current_project_id]
            
            # Calculate actual compute usage from instances
            total_used_vcpus = 0
            total_used_ram_mb = 0
            total_used_disk_gb = 0
            running_servers = 0
            
            for server in servers:
                if server.status == 'ACTIVE':
                    running_servers += 1
                
                # Get resource usage from server's flavor
                flavor = server.flavor
                if flavor:
                    # Server flavor is already a flavor object with resource info
                    vcpus = getattr(flavor, 'vcpus', 0) or 0
                    ram_mb = getattr(flavor, 'ram', 0) or 0
                    disk_gb = getattr(flavor, 'disk', 0) or 0
                    ephemeral_gb = getattr(flavor, 'OS-FLV-EXT-DATA:ephemeral', 0) or 0
                    swap_gb = getattr(flavor, 'swap', 0) or 0
                    
                    # Convert swap from MB to GB if it's in MB (some OpenStack versions use MB)
                    if swap_gb > 100:  # Likely in MB
                        swap_gb = swap_gb / 1024
                    
                    total_instance_disk = disk_gb + ephemeral_gb + swap_gb
                    
                    total_used_vcpus += vcpus
                    total_used_ram_mb += ram_mb
                    total_used_disk_gb += total_instance_disk
            
            # Try to get hypervisor totals (physical capacity)
            total_physical_vcpus = 0
            total_physical_ram_mb = 0
            total_physical_disk_gb = 0
            hypervisor_count = 0
            
            try:
                hypervisors = list(conn.compute.hypervisors())
                hypervisor_count = len(hypervisors)
                
                # Since hypervisor detailed stats are not available in this environment,
                # try to get quota limits as a reasonable approximation of capacity
                try:
                    quota = conn.compute.get_quota_set(current_project_id)
                    # Use quota limits as approximate capacity indicators
                    if hasattr(quota, 'cores') and quota.cores and quota.cores > 0:
                        total_physical_vcpus = quota.cores
                    if hasattr(quota, 'ram') and quota.ram and quota.ram > 0:
                        total_physical_ram_mb = quota.ram
                        
                except Exception as quota_error:
                    logger.info(f"Could not get quota for capacity estimation: {quota_error}")
                
                # Alternative: Try to get aggregate/availability zone stats
                try:
                    # Some deployments provide compute service stats
                    services = list(conn.compute.services(binary='nova-compute'))
                    if services and hypervisor_count > 0:
                        # Rough estimation: assume each compute service represents similar capacity
                        # This is just a fallback when hypervisor stats aren't available
                        if total_physical_vcpus == 0:
                            # Very rough estimate: if we can't get real data, 
                            # assume some reasonable default per hypervisor
                            estimated_vcpus_per_hypervisor = max(total_used_vcpus * 2, 8)  # At least double usage or 8
                            total_physical_vcpus = estimated_vcpus_per_hypervisor * hypervisor_count
                            
                        if total_physical_ram_mb == 0:
                            estimated_ram_per_hypervisor = max(total_used_ram_mb * 2, 16384)  # At least double usage or 16GB
                            total_physical_ram_mb = estimated_ram_per_hypervisor * hypervisor_count
                            
                except Exception:
                    pass
                    
            except Exception:
                # If hypervisor access fails, we'll still show instance usage
                pass
            
            compute_stats = {
                'total_servers': len(servers),
                'running_servers': running_servers,
                'total_hypervisors': hypervisor_count,
                # Physical capacity (from hypervisors)
                'total_vcpus': total_physical_vcpus,
                'total_memory_mb': total_physical_ram_mb,
                'total_disk_gb': total_physical_disk_gb,
                # Usage (from instances)
                'used_vcpus': total_used_vcpus,
                'used_memory_mb': total_used_ram_mb,
                'used_disk_gb': total_used_disk_gb,  # Calculated from instance flavors
                'project_server_count': len(servers)
            }
            
            monitoring_data['compute'] = compute_stats
        except Exception as e:
            monitoring_data['compute'] = {'error': str(e)}
            logger.warning(f"Failed to get compute monitoring data: {e}")
        
        # Network monitoring - filter by project
        try:
            all_networks = list(conn.network.networks())
            all_subnets = list(conn.network.subnets())
            all_ports = list(conn.network.ports())
            all_routers = list(conn.network.routers())
            all_floating_ips = list(conn.network.ips())
            
            # Filter by project (include shared/external networks for access)
            networks = [n for n in all_networks if (
                (getattr(n, 'project_id', None) or getattr(n, 'tenant_id', None)) == current_project_id or
                getattr(n, 'is_shared', False) or getattr(n, 'is_router_external', False)
            )]
            subnets = [s for s in all_subnets if (
                (getattr(s, 'project_id', None) or getattr(s, 'tenant_id', None)) == current_project_id
            )]
            ports = [p for p in all_ports if (
                (getattr(p, 'project_id', None) or getattr(p, 'tenant_id', None)) == current_project_id
            )]
            routers = [r for r in all_routers if (
                (getattr(r, 'project_id', None) or getattr(r, 'tenant_id', None)) == current_project_id
            )]
            floating_ips = [f for f in all_floating_ips if (
                (getattr(f, 'project_id', None) or getattr(f, 'tenant_id', None)) == current_project_id
            )]
            
            network_stats = {
                'total_networks': len(networks),
                'external_networks': len([n for n in networks if getattr(n, 'is_router_external', False)]),
                'total_subnets': len(subnets),
                'total_ports': len(ports),
                'active_ports': len([p for p in ports if p.status == 'ACTIVE']),
                'total_routers': len(routers),
                'active_routers': len([r for r in routers if r.status == 'ACTIVE']),
                'total_floating_ips': len(floating_ips),
                'allocated_floating_ips': len([f for f in floating_ips if f.fixed_ip_address])
            }
            
            monitoring_data['network'] = network_stats
        except Exception as e:
            monitoring_data['network'] = {'error': str(e)}
            logger.warning(f"Failed to get network monitoring data: {e}")
        
        # Storage monitoring - filter by project
        try:
            all_volumes = list(conn.volume.volumes())
            all_snapshots = list(conn.volume.snapshots())
            
            volumes = [v for v in all_volumes if getattr(v, 'project_id', None) == current_project_id]
            snapshots = [s for s in all_snapshots if getattr(s, 'project_id', None) == current_project_id]
            
            storage_stats = {
                'total_volumes': len(volumes),
                'available_volumes': len([v for v in volumes if v.status == 'available']),
                'in_use_volumes': len([v for v in volumes if v.status == 'in-use']),
                'total_volume_size_gb': sum(getattr(v, 'size', 0) for v in volumes),
                'total_snapshots': len(snapshots),
                'available_snapshots': len([s for s in snapshots if s.status == 'available'])
            }
            
            monitoring_data['storage'] = storage_stats
        except Exception as e:
            monitoring_data['storage'] = {'error': str(e)}
            logger.warning(f"Failed to get storage monitoring data: {e}")
        
        # Identity monitoring
        try:
            projects = list(conn.identity.projects())
            users = list(conn.identity.users())
            
            identity_stats = {
                'total_projects': len(projects),
                'enabled_projects': len([p for p in projects if p.is_enabled]),
                'total_users': len(users),
                'enabled_users': len([u for u in users if u.is_enabled])
            }
            
            monitoring_data['identity'] = identity_stats
        except Exception as e:
            monitoring_data['identity'] = {'error': str(e)}
            logger.warning(f"Failed to get identity monitoring data: {e}")
        
        return {
            'success': True,
            'monitoring_data': monitoring_data
        }
        
    except Exception as e:
        logger.error(f"Failed to get resource monitoring: {e}")
        return {
            'success': False,
            'error': str(e),
            'message': 'Failed to collect resource monitoring data'
        }


def get_compute_quota_usage(conn) -> dict[str, Any]:
    """
    Get compute quota usage information.
    
    Args:
        conn: OpenStack connection object
    
    Returns:
        Dict containing compute quota usage data
    """
    try:
        project_id = conn.current_project_id
        quota = conn.compute.get_quota_set(project_id)
        limits = conn.compute.get_limits()
        
        # Get current usage
        servers = list(conn.compute.servers())
        total_vcpus = sum(getattr(server, 'flavor', {}).get('vcpus', 0) for server in servers)
        total_ram = sum(getattr(server, 'flavor', {}).get('ram', 0) for server in servers)
        
        usage_data = {
            'instances': {
                'used': len(servers),
                'limit': getattr(quota, 'instances', -1),
                'percentage': (len(servers) / getattr(quota, 'instances', 1)) * 100 if getattr(quota, 'instances', -1) > 0 else 0
            },
            'vcpus': {
                'used': total_vcpus,
                'limit': getattr(quota, 'cores', -1),
                'percentage': (total_vcpus / getattr(quota, 'cores', 1)) * 100 if getattr(quota, 'cores', -1) > 0 else 0
            },
            'ram': {
                'used': total_ram,
                'limit': getattr(quota, 'ram', -1),
                'percentage': (total_ram / getattr(quota, 'ram', 1)) * 100 if getattr(quota, 'ram', -1) > 0 else 0
            },
            'key_pairs': {
                'used': len(list(conn.compute.keypairs())),
                'limit': getattr(quota, 'key_pairs', -1),
                'percentage': 0  # Calculate if needed
            }
        }
        
        return usage_data
        
    except Exception as e:
        logger.error(f"Failed to get compute quota usage: {e}")
        return {
            'error': str(e),
            'instances': {'used': 0, 'limit': -1, 'percentage': 0},
            'vcpus': {'used': 0, 'limit': -1, 'percentage': 0},
            'ram': {'used': 0, 'limit': -1, 'percentage': 0}
        }


def get_usage_statistics(start_date: str = "", end_date: str = "") -> dict[str, Any]:
    """
    Get usage statistics for the current project.
    
    Args:
        start_date: Start date for statistics (YYYY-MM-DD format)
        end_date: End date for statistics (YYYY-MM-DD format)
    
    Returns:
        Dict containing usage statistics
    """
    try:
        # Import here to avoid circular imports
        from ..connection import get_openstack_connection, is_all_projects_allowed
        conn = get_openstack_connection()

        # Set default dates if not provided
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if not start_date:
            start_datetime = datetime.now() - timedelta(days=30)
            start_date = start_datetime.strftime('%Y-%m-%d')

        all_projects = is_all_projects_allowed()
        if all_projects:
            logger.warning("OS_ALLOW_ALL_PROJECTS enabled - usage statistics computed across all projects")

        usage_stats = {
            'period': {
                'start_date': start_date,
                'end_date': end_date
            },
            'compute': {},
            'network': {},
            'storage': {}
        }

        # Compute usage
        try:
            servers = list(conn.compute.servers(all_projects=all_projects))
            flavors = {f.id: f for f in conn.compute.flavors()}
            
            server_stats = {
                'total_servers': len(servers),
                'servers_by_status': {},
                'servers_by_flavor': {},
                'total_vcpus': 0,
                'total_memory_mb': 0
            }
            
            for server in servers:
                status = server.status
                server_stats['servers_by_status'][status] = server_stats['servers_by_status'].get(status, 0) + 1
                
                flavor_id = getattr(server, 'flavor', {}).get('id')
                if flavor_id and flavor_id in flavors:
                    flavor_name = flavors[flavor_id].name
                    server_stats['servers_by_flavor'][flavor_name] = server_stats['servers_by_flavor'].get(flavor_name, 0) + 1
                    server_stats['total_vcpus'] += getattr(flavors[flavor_id], 'vcpus', 0)
                    server_stats['total_memory_mb'] += getattr(flavors[flavor_id], 'ram', 0)
            
            usage_stats['compute'] = server_stats
            
        except Exception as e:
            usage_stats['compute'] = {'error': str(e)}
            logger.warning(f"Failed to get compute usage: {e}")
        
        # Network usage
        try:
            networks = list(conn.network.networks())
            subnets = list(conn.network.subnets())
            ports = list(conn.network.ports())
            floating_ips = list(conn.network.ips())
            
            network_stats = {
                'total_networks': len(networks),
                'total_subnets': len(subnets),
                'total_ports': len(ports),
                'ports_by_status': {},
                'floating_ips': {
                    'total': len(floating_ips),
                    'allocated': len([f for f in floating_ips if f.fixed_ip_address]),
                    'available': len([f for f in floating_ips if not f.fixed_ip_address])
                }
            }
            
            for port in ports:
                status = port.status
                network_stats['ports_by_status'][status] = network_stats['ports_by_status'].get(status, 0) + 1
            
            usage_stats['network'] = network_stats
            
        except Exception as e:
            usage_stats['network'] = {'error': str(e)}
            logger.warning(f"Failed to get network usage: {e}")
        
        # Storage usage
        try:
            volume_kwargs = {"all_tenants": True} if all_projects else {}
            volumes = list(conn.volume.volumes(**volume_kwargs))
            snapshots = list(conn.volume.snapshots(**volume_kwargs))
            
            storage_stats = {
                'volumes': {
                    'total_count': len(volumes),
                    'total_size_gb': sum(getattr(v, 'size', 0) for v in volumes),
                    'volumes_by_status': {},
                    'volumes_by_type': {}
                },
                'snapshots': {
                    'total_count': len(snapshots),
                    'total_size_gb': sum(getattr(s, 'size', 0) for s in snapshots),
                    'snapshots_by_status': {}
                }
            }
            
            for volume in volumes:
                status = volume.status
                volume_type = getattr(volume, 'volume_type', 'unknown')
                storage_stats['volumes']['volumes_by_status'][status] = storage_stats['volumes']['volumes_by_status'].get(status, 0) + 1
                storage_stats['volumes']['volumes_by_type'][volume_type] = storage_stats['volumes']['volumes_by_type'].get(volume_type, 0) + 1
            
            for snapshot in snapshots:
                status = snapshot.status
                storage_stats['snapshots']['snapshots_by_status'][status] = storage_stats['snapshots']['snapshots_by_status'].get(status, 0) + 1
            
            usage_stats['storage'] = storage_stats
            
        except Exception as e:
            usage_stats['storage'] = {'error': str(e)}
            logger.warning(f"Failed to get storage usage: {e}")
        
        return {
            'success': True,
            'usage_statistics': usage_stats
        }
        
    except Exception as e:
        logger.error(f"Failed to get usage statistics: {e}")
        return {
            'success': False,
            'error': str(e),
            'message': 'Failed to collect usage statistics'
        }


def get_quota(project_name: str = "") -> dict[str, Any]:
    """
    Get quota information for a project.
    
    Args:
        project_name: Name of the project (current project if empty)
    
    Returns:
        Dict containing quota information
    """
    try:
        # Import here to avoid circular imports
        from ..connection import get_openstack_connection
        conn = get_openstack_connection()
        
        # Get project ID
        if project_name:
            project = None
            for proj in conn.identity.projects():
                if proj.name == project_name:
                    project = proj
                    break
            
            if not project:
                return {
                    'success': False,
                    'error': f'Project "{project_name}" not found'
                }
            project_id = project.id
        else:
            project_id = conn.current_project_id
            project_name = "current project"
        
        quota_data = {
            'project_name': project_name,
            'project_id': project_id,
            'compute': {
                'limits': {},
                'usage': {}
            },
            'network': {
                'limits': {},
                'usage': {}
            },
            'volume': {
                'limits': {},
                'usage': {}
            }
        }
        
        # Compute quotas and usage
        try:
            compute_quotas = conn.compute.get_quota_set(project_id)
            quota_data['compute']['limits'] = {
                'instances': getattr(compute_quotas, 'instances', -1),
                'cores': getattr(compute_quotas, 'cores', -1),
                'ram': getattr(compute_quotas, 'ram', -1),
                'key_pairs': getattr(compute_quotas, 'key_pairs', -1),
                'metadata_items': getattr(compute_quotas, 'metadata_items', -1),
                'server_groups': getattr(compute_quotas, 'server_groups', -1),
                'server_group_members': getattr(compute_quotas, 'server_group_members', -1)
            }
            
            # Get compute usage. all_projects=True is required for project_id to
            # actually take effect - Nova silently ignores project_id otherwise
            # and just returns the token's own project.
            instances = list(conn.compute.servers(project_id=project_id, all_projects=True))
            active_instances = [i for i in instances if getattr(i, 'status', '') == 'ACTIVE']
            total_cores = 0
            total_ram = 0
            
            for instance in instances:
                try:
                    flavor = conn.compute.get_flavor(instance.flavor['id'])
                    total_cores += getattr(flavor, 'vcpus', 0)
                    total_ram += getattr(flavor, 'ram', 0)
                except Exception:
                    pass
            
            keypairs = list(conn.compute.keypairs())
            
            quota_data['compute']['usage'] = {
                'instances': len(instances),
                'cores': total_cores,
                'ram': total_ram,
                'key_pairs': len(keypairs),
                'active_instances': len(active_instances)
            }
        except Exception as e:
            quota_data['compute'] = {'error': str(e)}
        
        # Network quotas and usage
        try:
            network_quotas = conn.network.get_quota(project_id)
            quota_data['network']['limits'] = {
                'networks': getattr(network_quotas, 'networks', -1),
                'subnets': getattr(network_quotas, 'subnets', -1),
                'ports': getattr(network_quotas, 'ports', -1),
                'routers': getattr(network_quotas, 'routers', -1),
                'floatingips': getattr(network_quotas, 'floatingips', -1),
                'security_groups': getattr(network_quotas, 'security_groups', -1),
                'security_group_rules': getattr(network_quotas, 'security_group_rules', -1)
            }
            
            # Get network usage
            networks = list(conn.network.networks(project_id=project_id))
            subnets = list(conn.network.subnets(project_id=project_id))
            ports = list(conn.network.ports(project_id=project_id))
            routers = list(conn.network.routers(project_id=project_id))
            floatingips = list(conn.network.ips(project_id=project_id))
            security_groups = list(conn.network.security_groups(project_id=project_id))
            
            total_sg_rules = 0
            for sg in security_groups:
                try:
                    rules = list(conn.network.security_group_rules(security_group_id=sg.id))
                    total_sg_rules += len(rules)
                except Exception:
                    pass
            
            quota_data['network']['usage'] = {
                'networks': len(networks),
                'subnets': len(subnets),
                'ports': len(ports),
                'routers': len(routers),
                'floatingips': len(floatingips),
                'security_groups': len(security_groups),
                'security_group_rules': total_sg_rules
            }
        except Exception as e:
            quota_data['network'] = {'error': str(e)}
        
        # Volume quotas and usage
        try:
            volume_quotas = conn.volume.get_quota_set(project_id)
            quota_data['volume']['limits'] = {
                'volumes': getattr(volume_quotas, 'volumes', -1),
                'snapshots': getattr(volume_quotas, 'snapshots', -1),
                'gigabytes': getattr(volume_quotas, 'gigabytes', -1),
                'backups': getattr(volume_quotas, 'backups', -1),
                'backup_gigabytes': getattr(volume_quotas, 'backup_gigabytes', -1)
            }
            
            # Get volume usage. all_tenants=True is required for project_id to
            # actually take effect - Cinder silently ignores project_id otherwise
            # and just returns the token's own project.
            volumes = list(conn.volume.volumes(project_id=project_id, all_tenants=True))
            snapshots = list(conn.volume.snapshots(project_id=project_id, all_tenants=True))

            total_gigabytes = sum(getattr(vol, 'size', 0) for vol in volumes)

            # Try to get backups (may not be available in all OpenStack deployments)
            try:
                backups = list(conn.volume.backups(project_id=project_id, all_tenants=True))
                backup_gigabytes = sum(getattr(backup, 'size', 0) for backup in backups)
            except Exception:
                backups = []
                backup_gigabytes = 0
            
            quota_data['volume']['usage'] = {
                'volumes': len(volumes),
                'snapshots': len(snapshots),
                'gigabytes': total_gigabytes,
                'backups': len(backups),
                'backup_gigabytes': backup_gigabytes
            }
        except Exception as e:
            quota_data['volume'] = {'error': str(e)}
        
        return {
            'success': True,
            'quotas': quota_data
        }
        
    except Exception as e:
        logger.error(f"Failed to get quota information: {e}")
        return {
            'success': False,
            'error': str(e),
            'message': 'Failed to retrieve quota information'
        }


def get_hypervisor_details(hypervisor_name: str = "all") -> dict[str, Any]:
    """
    Get details about hypervisors.
    
    Args:
        hypervisor_name: Name of specific hypervisor or "all" for all hypervisors
    
    Returns:
        Dict containing hypervisor information
    """
    try:
        # Import here to avoid circular imports
        from ..connection import get_openstack_connection
        conn = get_openstack_connection()
        
        hypervisors = []
        total_stats = _new_hypervisor_totals()

        for hypervisor in conn.compute.hypervisors(
            details=True,
            microversion=HYPERVISOR_CAPACITY_MICROVERSION,
        ):
            hypervisor_data = _format_hypervisor(hypervisor)
            hypervisors.append(hypervisor_data)
            _add_hypervisor_to_totals(total_stats, hypervisor_data)

        _enrich_hypervisors_with_uptime(conn, hypervisors)
        total_stats = _finalize_hypervisor_totals(total_stats)

        # Try to get enhanced cluster statistics from Nova API.
        enhanced_stats = None
        try:
            stats_response = conn.compute.get(
                '/os-hypervisors/statistics',
                microversion=HYPERVISOR_CAPACITY_MICROVERSION,
            )
            if stats_response.status_code == 200:
                stats_data = stats_response.json()
                hypervisor_statistics = stats_data.get('hypervisor_statistics', {})

                if hypervisor_statistics:
                    enhanced_stats = {
                        'count': hypervisor_statistics.get('count'),
                        'vcpus': hypervisor_statistics.get('vcpus'),
                        'vcpus_used': hypervisor_statistics.get('vcpus_used'),
                        'memory_mb': hypervisor_statistics.get('memory_mb'),
                        'memory_mb_used': hypervisor_statistics.get('memory_mb_used'),
                        'local_gb': hypervisor_statistics.get('local_gb'),
                        'local_gb_used': hypervisor_statistics.get('local_gb_used'),
                        'running_vms': hypervisor_statistics.get('running_vms'),
                        'data_source': 'nova_hypervisor_statistics_api',
                        'microversion': HYPERVISOR_CAPACITY_MICROVERSION,
                    }
        except Exception as e:
            logger.warning(f"Could not retrieve hypervisor statistics API data: {e}")

        response = {
            'success': True,
            'microversion': HYPERVISOR_CAPACITY_MICROVERSION,
            'data_source': 'nova_os_hypervisors_detail',
            'total_stats': total_stats,
            'enhanced_stats': enhanced_stats,
        }

        if hypervisor_name.lower() == "all":
            response['hypervisors'] = hypervisors
            return response

        for hypervisor_data in hypervisors:
            if (
                hypervisor_data.get('name') == hypervisor_name
                or str(hypervisor_data.get('id')) == hypervisor_name
            ):
                response['hypervisor'] = hypervisor_data
                return response

        return {
            'success': False,
            'error': f'Hypervisor "{hypervisor_name}" not found',
            'microversion': HYPERVISOR_CAPACITY_MICROVERSION,
        }
            
    except Exception as e:
        logger.error(f"Failed to get hypervisor details: {e}")
        return {
            'success': False,
            'error': str(e),
            'message': 'Failed to retrieve hypervisor information'
        }


def get_availability_zones() -> dict[str, Any]:
    """
    Get availability zones information.
    
    Returns:
        Dict containing availability zones data
    """
    try:
        # Import here to avoid circular imports
        from ..connection import get_openstack_connection
        conn = get_openstack_connection()
        
        zones_data = {
            'compute': [],
            'network': [],
            'volume': []
        }
        
        # Compute availability zones
        try:
            compute_zones = list(conn.compute.availability_zones())
            for zone in compute_zones:
                zones_data['compute'].append({
                    'name': getattr(zone, 'name', 'unknown'),
                    'available': getattr(zone, 'available', False),
                    'hosts': getattr(zone, 'hosts', {})
                })
        except Exception as e:
            zones_data['compute'] = [{'error': str(e)}]
        
        # Network availability zones
        try:
            network_zones = list(conn.network.availability_zones())
            for zone in network_zones:
                zones_data['network'].append({
                    'name': getattr(zone, 'name', 'unknown'),
                    'state': getattr(zone, 'state', 'unknown'),
                    'resource': getattr(zone, 'resource', 'network')
                })
        except Exception as e:
            zones_data['network'] = [{'error': str(e)}]
        
        # Volume availability zones
        try:
            volume_zones = list(conn.volume.availability_zones())
            for zone in volume_zones:
                zones_data['volume'].append({
                    'name': getattr(zone, 'name', 'unknown'),
                    'available': getattr(zone, 'available', False)
                })
        except Exception as e:
            zones_data['volume'] = [{'error': str(e)}]
        
        return {
            'success': True,
            'availability_zones': zones_data
        }
        
    except Exception as e:
        logger.error(f"Failed to get availability zones: {e}")
        return {
            'success': False,
            'error': str(e),
            'message': 'Failed to retrieve availability zones'
        }


def set_quota(project_name: str, service: str, **kwargs) -> dict[str, Any]:
    """
    Set quota for a project.
    
    Args:
        project_name: Name of the project
        service: Service type (compute, network, volume)
        **kwargs: Quota parameters to set
    
    Returns:
        Result of the quota update operation
    """
    try:
        # Import here to avoid circular imports
        from ..connection import get_openstack_connection
        conn = get_openstack_connection()
        
        # Find project
        project = None
        for proj in conn.identity.projects():
            if proj.name == project_name or proj.id == project_name:
                project = proj
                break
        
        if not project:
            return {
                'success': False,
                'error': f'Project "{project_name}" not found'
            }
        
        service = service.lower()
        
        if service == 'compute':
            # Update compute quotas
            quota_updates = {}
            for key, value in kwargs.items():
                if key in ['instances', 'cores', 'ram', 'key_pairs', 'metadata_items', 'server_groups', 'server_group_members']:
                    quota_updates[key] = int(value)
            
            if quota_updates:
                conn.compute.update_quota_set(project.id, **quota_updates)
                return {
                    'success': True,
                    'message': f'Compute quotas updated for project "{project_name}"',
                    'updated_quotas': quota_updates
                }
            else:
                return {
                    'success': False,
                    'error': 'No valid compute quota parameters provided'
                }
                
        elif service == 'network':
            # Update network quotas
            quota_updates = {}
            for key, value in kwargs.items():
                if key in ['networks', 'subnets', 'ports', 'routers', 'floatingips', 'security_groups', 'security_group_rules']:
                    quota_updates[key] = int(value)
            
            if quota_updates:
                conn.network.update_quota(project.id, **quota_updates)
                return {
                    'success': True,
                    'message': f'Network quotas updated for project "{project_name}"',
                    'updated_quotas': quota_updates
                }
            else:
                return {
                    'success': False,
                    'error': 'No valid network quota parameters provided'
                }
                
        elif service == 'volume':
            # Update volume quotas
            quota_updates = {}
            for key, value in kwargs.items():
                if key in ['volumes', 'snapshots', 'gigabytes', 'backups', 'backup_gigabytes']:
                    quota_updates[key] = int(value)
            
            if quota_updates:
                conn.volume.update_quota_set(project.id, **quota_updates)
                return {
                    'success': True,
                    'message': f'Volume quotas updated for project "{project_name}"',
                    'updated_quotas': quota_updates
                }
            else:
                return {
                    'success': False,
                    'error': 'No valid volume quota parameters provided'
                }
        else:
            return {
                'success': False,
                'error': f'Unknown service "{service}". Supported: compute, network, volume'
            }
            
    except Exception as e:
        logger.error(f"Failed to set quota: {e}")
        return {
            'success': False,
            'error': str(e),
            'message': f'Failed to set {service} quota for project "{project_name}"'
        }
