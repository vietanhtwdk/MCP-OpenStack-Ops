"""
Load Balancer Service Module

Provides load balancer management functionality with comprehensive operations
including core load balancer management, listeners, pools, health monitors,
L7 policies, management operations, and amphora management.
"""

# Core load balancer operations
# Amphora management
from .amphorae import get_load_balancer_amphorae, set_load_balancer_amphora
from .core import get_load_balancer_details, get_load_balancer_list, set_load_balancer

# Health monitor management
from .health_monitors import (
    get_load_balancer_health_monitors,
    set_load_balancer_health_monitor,
)

# L7 policy and rule management
from .l7_policies import (
    get_load_balancer_l7_policies,
    get_load_balancer_l7_rules,
    set_load_balancer_l7_policy,
    set_load_balancer_l7_rule,
)

# Listener management
from .listeners import get_load_balancer_listeners, set_load_balancer_listener

# Advanced management (availability zones, flavors, quotas, providers)
from .management import (
    get_load_balancer_availability_zones,
    get_load_balancer_flavors,
    get_load_balancer_providers,
    get_load_balancer_quotas,
    set_load_balancer_availability_zone,
    set_load_balancer_flavor,
    set_load_balancer_quota,
)

# Pool and member management
from .pools import (
    get_load_balancer_pool_members,
    get_load_balancer_pools,
    set_load_balancer_pool,
    set_load_balancer_pool_member,
)

__all__ = [
    # Core operations
    'get_load_balancer_list',
    'get_load_balancer_details', 
    'set_load_balancer',
    
    # Listener operations
    'get_load_balancer_listeners',
    'set_load_balancer_listener',
    
    # Pool operations
    'get_load_balancer_pools',
    'set_load_balancer_pool',
    'get_load_balancer_pool_members',
    'set_load_balancer_pool_member',
    
    # Health monitor operations
    'get_load_balancer_health_monitors',
    'set_load_balancer_health_monitor',
    
    # L7 policy operations
    'get_load_balancer_l7_policies',
    'set_load_balancer_l7_policy',
    'get_load_balancer_l7_rules',
    'set_load_balancer_l7_rule',
    
    # Management operations
    'get_load_balancer_availability_zones',
    'set_load_balancer_availability_zone',
    'get_load_balancer_flavors',
    'set_load_balancer_flavor',
    'get_load_balancer_providers',
    'get_load_balancer_quotas',
    'set_load_balancer_quota',
    
    # Amphora operations
    'get_load_balancer_amphorae',
    'set_load_balancer_amphora',
    '_set_load_balancer_amphora'
]

# Core load balancer management

# Listener management

# Pool and member management

# Health monitoring

# L7 policies and rules

# Management and configuration

# Amphorae management
from .amphorae import _set_load_balancer_amphora

__all__ = [
    # Core
    'get_load_balancer_list',
    'get_load_balancer_details', 
    'set_load_balancer',
    
    # Listeners
    'get_load_balancer_listeners',
    'set_load_balancer_listener',
    
    # Pools and Members
    'get_load_balancer_pools',
    'set_load_balancer_pool',
    'get_load_balancer_pool_members',
    'set_load_balancer_pool_member',
    
    # Health Monitors
    'get_load_balancer_health_monitors',
    'set_load_balancer_health_monitor',
    
    # L7 Policies and Rules
    'get_load_balancer_l7_policies',
    'set_load_balancer_l7_policy',
    'get_load_balancer_l7_rules',
    'set_load_balancer_l7_rule',
    
    # Management
    'set_load_balancer_availability_zone',
    'get_load_balancer_availability_zones',
    'set_load_balancer_flavor',
    'get_load_balancer_flavors',
    'set_load_balancer_quota',
    'get_load_balancer_providers',
    
    # Amphorae
    'get_load_balancer_amphorae',
    'set_load_balancer_amphora'
]