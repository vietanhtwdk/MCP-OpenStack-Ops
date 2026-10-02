"""Tool implementation for get_flavor_list."""

import json
from datetime import datetime

from ..functions import get_flavor_list as _get_flavor_list
from ..mcp_main import (
    logger,
    mcp,
)


@mcp.tool()
async def get_flavor_list() -> str:
    """
    Get list of available compute flavors with detailed specifications.

    Functions:
    - Query flavors (vCPUs, RAM, disk, ephemeral, swap, extra specs)
    - Show public/private flavor visibility

    Use when user requests flavor information or VM/instance creation planning
    (e.g. matching flavor disk size against volume size, sizing a new server).

    Returns:
        List of flavors with detailed specifications in JSON format.
    """
    try:
        logger.info("Fetching flavor list")
        flavors = _get_flavor_list()

        result = {
            "timestamp": datetime.now().isoformat(),
            "total_flavors": len(flavors),
            "flavors": flavors
        }

        return json.dumps(result, indent=2, ensure_ascii=False)

    except Exception as e:
        error_msg = f"Error: Failed to fetch flavor list - {e!s}"
        logger.error(error_msg)
        return error_msg
