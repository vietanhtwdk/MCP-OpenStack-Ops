import json
import logging
import os
import sys
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier

from .config import ServerConfig, load_server_config

# Add the current directory to sys.path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def handle_operation_result(result: dict[str, Any], operation_name: str, details: dict[str, str] = None) -> str:
    """
    Handle operation results consistently across all MCP tools.
    
    Args:
        result: Result dictionary from core function
        operation_name: Name of the operation (e.g., "Instance Management", "Network Creation")
        details: Additional details to include in error message (optional)
    
    Returns:
        Success JSON or clear error message
    """
    # Check if result is None or empty
    if not result:
        error_response = f"❌ **{operation_name} Failed**\n\n**Error**: No response received from OpenStack API. The operation may have failed or timed out."
        
        if details:
            details_str = '\n'.join([f"**{k}**: {v}" for k, v in details.items()])
            error_response += f"\n\n{details_str}"
            error_response += "\n\n**Recommendation**: Please verify the operation status and try again if needed."
            
        return error_response
    
    # Check if operation failed and return clear error message
    if isinstance(result, dict) and result.get('success') is False:
        error_message = result.get('message', 'Unknown error occurred')
        
        error_response = f"❌ **{operation_name} Failed**\n\n**Error**: {error_message}"
        
        if details:
            details_str = '\n'.join([f"**{k}**: {v}" for k, v in details.items()])
            error_response += f"\n\n{details_str}"
            
        return error_response
    
    # Enhanced handling for successful operations with tool-specific async guidance
    if isinstance(result, dict) and result.get('success') is True:
        # Extract operation details from various parameter structures
        action = details.get('Action', 'operation') if details else 'operation'
        resource_name = (details.get('Instance') or details.get('Volume') or 
                        details.get('Network') or details.get('Stack') or 
                        details.get('Image') or details.get('Keypair') or 'resource') if details else 'resource'
        
        # Tool-specific async handling and verification commands
        async_operations = {
            "Instance Management": {
                "async_actions": ["start", "stop", "restart", "reboot", "create", "delete", "resize", "rebuild"],
                "timing": "30-60 seconds",
                "verify_cmd": f"Show instance status for {resource_name}"
            },
            "Volume Management": {
                "async_actions": ["create", "delete", "extend", "attach", "detach"],
                "timing": "10-30 seconds", 
                "verify_cmd": "List all volumes"
            },
            "Network Management": {
                "async_actions": ["create", "delete"],
                "timing": "5-15 seconds",
                "verify_cmd": "Show all networks"
            },
            "Heat Stack Management": {
                "async_actions": ["create", "update", "delete"],
                "timing": "2-10 minutes",
                "verify_cmd": "List all Heat stacks"
            },
            "Image Management": {
                "async_actions": ["create", "delete", "update"],
                "timing": "1-5 minutes",
                "verify_cmd": "List available images"
            },
            "Quota Management": {
                "async_actions": [],  # Usually synchronous
                "timing": "immediate",
                "verify_cmd": "Show quota usage and limits"
            },
            "Keypair Management": {
                "async_actions": [],  # Usually synchronous
                "timing": "immediate", 
                "verify_cmd": "List all keypairs"
            }
        }
        
        tool_config = async_operations.get(operation_name, {
            "async_actions": ["create", "delete", "update"],
            "timing": "variable",
            "verify_cmd": f"Check {operation_name.lower()} status"
        })
        
        # Only add async note for operations that are actually asynchronous
        if action.lower() in tool_config.get("async_actions", []):
            if "message" in result:
                timing = tool_config.get("timing", "variable")
                verify_cmd = tool_config.get("verify_cmd", f"Check {operation_name.lower()} status")
                
                result["message"] += f"\n\n📋 Note: This is an asynchronous operation. The {action} command has been initiated successfully (expected completion: {timing}). You can verify the status using '{verify_cmd}'."
            
            result["operation_type"] = "asynchronous"
            result["verification_needed"] = True
        else:
            # For synchronous operations, just mark as completed
            result["operation_type"] = "synchronous"
            result["verification_needed"] = False
    
    if isinstance(result, dict):
        try:
            return json.dumps(result, indent=2, ensure_ascii=False)
        except Exception as e:
            return f"Operation completed but response formatting failed: {e!s}"

    # Return string and non-dict results as-is.
    return str(result)

from .functions import (
    get_image_detail_list as _get_image_detail_list,
)
from .functions import (
    get_instance_by_name as _get_instance_by_name,
)
from .functions import (
    get_keypair_list as _get_keypair_list,
)
from .functions import (
    get_network_details as _get_network_details,
)
from .functions import (
    get_volume_list as _get_volume_list,
)

# Set up logging (initial level from env; may be overridden by --log-level)
logging.basicConfig(
    level=os.environ.get("MCP_LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("OpenStackService")

# =============================================================================
# Authentication Setup
# =============================================================================

def _build_static_token_auth(secret_key: str) -> StaticTokenVerifier:
    tokens = {
        secret_key: {
            "client_id": "openstack-ops-client",
            "scopes": ["read", "write"],
        }
    }
    return StaticTokenVerifier(tokens=tokens)


# Initialize MCP instance once for decorator registration.
# Runtime authentication is configured in main() before mcp.run().
logger.debug("Initializing MCP instance")
mcp = FastMCP("mcp-openstack-ops")

# =============================================================================
# Safety Control Functions
# =============================================================================

def _get_resource_status_by_name(resource_type: str, resource_name: str) -> str:
    """Helper function to get current status of a resource by name."""
    try:
        if resource_type == "instance":
            instance_info = _get_instance_by_name(resource_name.strip())
            return instance_info.get('status', 'Unknown') if instance_info else 'Not Found'
        
        elif resource_type == "volume":
            volumes = _get_volume_list()
            for volume in volumes:
                if volume.get('name') == resource_name.strip():
                    return volume.get('status', 'Unknown')
            return 'Not Found'
            
        elif resource_type == "image":
            images = _get_image_detail_list()
            if isinstance(images, list):
                for image in images:
                    if image.get('name') == resource_name.strip():
                        return image.get('status', 'Unknown')
            return 'Not Found'
        
        elif resource_type == "network":
            # Get network details from network listing
            network_info = _get_network_details(resource_name.strip())
            if isinstance(network_info, list) and network_info:
                return network_info[0].get('status', 'Unknown')
            return 'Not Found'
            
        elif resource_type == "keypair":
            keypairs = _get_keypair_list()
            if isinstance(keypairs, list):
                for keypair in keypairs:
                    if keypair.get('name') == resource_name.strip():
                        return 'Available'  # Keypairs don't have status, just exist or not
            return 'Not Found'
            
        else:
            return 'Unknown Resource Type'
            
    except Exception as e:
        return f'Status Check Failed: {e!s}'

def _is_modify_operation_allowed() -> bool:
    """Check if modify operations are allowed based on environment variable."""
    return os.environ.get("ALLOW_MODIFY_OPERATIONS", "false").lower() == "true"

def _check_modify_operation_permission() -> str:
    """Check and return error message if modify operations are not allowed."""
    if not _is_modify_operation_allowed():
        return """
❌ **MODIFY OPERATION BLOCKED**

This operation can modify or delete OpenStack resources and has been disabled for safety.

To enable modify operations, set the following in your .env file:
```
ALLOW_MODIFY_OPERATIONS=true
```

**⚠️  WARNING**: Only enable this in development or testing environments where data loss is acceptable.

**Read-only operations available:**
- get_cluster_status, get_service_status
- get_instance_details, search_instances
- get_network_details, get_project_info
- get_flavor_list, get_image_list, get_user_list
- get_keypair_list, get_security_groups
- get_floating_ips, get_routers, get_volume_types
- get_volume_snapshots, get_heat_stacks
- get_resource_monitoring, get_usage_statistics, get_quota
- get_volume_list, get_image_detail_list, get_project_details
"""
    return ""

def conditional_tool(func):
    """
    Decorator that conditionally registers tools based on ALLOW_MODIFY_OPERATIONS setting.
    Modify operations are only registered when explicitly enabled.
    """
    if _is_modify_operation_allowed():
        return mcp.tool()(func)
    else:
        # Return the function without registering it as a tool
        return func

from .tools import register_all_tools

# Register all MCP tool implementations
register_all_tools()

# =============================================================================
# Prompt Template Helper Functions
# =============================================================================

def read_prompt_template(file_path: str) -> str:
    """Read the prompt template file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        logger.warning(f"Prompt template file not found: {file_path}")
        return "# OpenStack Operations Guide\n\nPrompt template file not found."
    except Exception as e:
        logger.error(f"Error reading prompt template: {e}")
        return f"# Error\n\nFailed to read prompt template: {e!s}"


def parse_prompt_sections(template: str) -> tuple[list[str], list[str]]:
    """Parse the prompt template into sections."""
    lines = template.split('\n')
    headings = []
    sections = []
    current_section = []
    
    for line in lines:
        if line.startswith('## '):
            if current_section:
                sections.append('\n'.join(current_section))
                current_section = []
            heading = line[3:].strip()
            headings.append(heading)
            current_section.append(line)
        else:
            current_section.append(line)
    
    if current_section:
        sections.append('\n'.join(current_section))
    
    return headings, sections


# Define the prompt template path
PROMPT_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "prompt_template.md")


# =============================================================================
# MCP Prompts (for prompts/list exposure)
# =============================================================================

@mcp.prompt("prompt_template_full")
def prompt_template_full_prompt() -> str:
    """Return the full canonical prompt template."""
    return read_prompt_template(PROMPT_TEMPLATE_PATH)


@mcp.prompt("prompt_template_headings")
def prompt_template_headings_prompt() -> str:
    """Return compact list of section headings."""
    template = read_prompt_template(PROMPT_TEMPLATE_PATH)
    headings, _ = parse_prompt_sections(template)
    lines = ["Section Headings:"]
    for idx, title in enumerate(headings, 1):
        lines.append(f"{idx}. {title}")
    return "\n".join(lines)


@mcp.prompt("prompt_template_section")
def prompt_template_section_prompt(section: str | None = None) -> str:
    """Return a specific prompt template section by number or keyword."""
    if not section:
        template = read_prompt_template(PROMPT_TEMPLATE_PATH)
        headings, _ = parse_prompt_sections(template)
        lines = ["[HELP] Missing 'section' argument."]
        lines.append("Specify a section number or keyword.")
        lines.append("Examples: 1 | overview | tool map | usage")
        lines.append("")
        lines.append("Available sections:")
        for idx, title in enumerate(headings, 1):
            lines.append(f"{idx}. {title}")
        return "\n".join(lines)

    template = read_prompt_template(PROMPT_TEMPLATE_PATH)
    headings, sections = parse_prompt_sections(template)

    # Try by number
    try:
        idx = int(section) - 1
        if 0 <= idx < len(headings):
            return sections[idx + 1]  # +1 to skip the title section
    except Exception:
        pass

    # Try by keyword
    section_lower = section.strip().lower()
    for i, heading in enumerate(headings):
        if section_lower in heading.lower():
            return sections[i + 1]  # +1 to skip the title section

    return f"Section '{section}' not found."


# =============================================================================
# Main Function
# =============================================================================


def _configure_logging(config: ServerConfig) -> None:
    """Apply resolved logging configuration."""
    logging.getLogger().setLevel(config.log_level)
    logger.setLevel(config.log_level)
    logging.getLogger("aiohttp.client").setLevel("WARNING")

    if config.log_level_source == "cli":
        logger.info("Log level set via CLI to %s", config.log_level)
    elif config.log_level_source == "environment":
        logger.info("Log level set via environment variable to %s", config.log_level)
    else:
        logger.info("Using default log level: %s", config.log_level)


def _configure_auth(config: ServerConfig) -> bool:
    """Configure remote auth for the MCP server. Returns False when startup should stop."""
    if config.transport_type == "streamable-http":
        if config.auth_enable:
            if not config.secret_key:
                logger.error("ERROR: Authentication is enabled but no secret key provided.")
                logger.error("Please set REMOTE_SECRET_KEY environment variable or use --secret-key argument.")
                return False
            logger.info("Authentication enabled for streamable-http transport")
        else:
            logger.warning("WARNING: streamable-http mode without authentication enabled!")
            logger.warning("This server will accept requests without Bearer token verification.")
            logger.warning("Set REMOTE_AUTH_ENABLE=true and REMOTE_SECRET_KEY to enable authentication.")

    mcp.auth = _build_static_token_auth(config.secret_key) if config.auth_enable else None
    return True


def main(argv: list[str] | None = None) -> None:
    """Main entry point for the MCP server."""
    try:
        config = load_server_config(argv)
    except ValueError as exc:
        logger.error("Invalid configuration: %s", exc)
        return

    _configure_logging(config)
    if not _configure_auth(config):
        return

    # Execution based on transport mode
    if config.transport_type == "streamable-http":
        logger.info("Starting streamable-http server on %s:%s", config.host, config.port)
        mcp.run(transport="streamable-http", host=config.host, port=config.port)
    else:
        logger.info("Starting stdio transport for local usage")
        mcp.run(transport="stdio")

if __name__ == "__main__":
    """Entrypoint for MCP server.

    Supports optional CLI arguments while remaining backward-compatible 
    with stdio launcher expectations.
    """
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Server shutdown requested by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        sys.exit(1)
