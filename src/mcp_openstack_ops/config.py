"""Runtime configuration helpers for the MCP server."""

import argparse
import os
from collections.abc import Sequence
from dataclasses import dataclass

TRUTHY_VALUES = ("true", "1", "yes", "on")


@dataclass(frozen=True)
class ServerConfig:
    """Resolved server configuration from CLI arguments and environment."""

    log_level: str
    log_level_source: str
    transport_type: str
    host: str
    port: int
    auth_enable: bool
    secret_key: str


def parse_bool_env(value: str | None, default: bool = False) -> bool:
    """Parse common truthy strings from environment variables."""
    if value is None:
        return default
    return value.strip().lower() in TRUTHY_VALUES


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the MCP server argument parser."""
    parser = argparse.ArgumentParser(
        prog="mcp-openstack-ops",
        description="MCP OpenStack Operations Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--log-level",
        dest="log_level",
        help="Logging level override (DEBUG, INFO, WARNING, ERROR, CRITICAL). Overrides MCP_LOG_LEVEL env if provided.",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    )
    parser.add_argument(
        "--type",
        dest="transport_type",
        help="Transport type (stdio or streamable-http). Default: env FASTMCP_TYPE or stdio",
        choices=["stdio", "streamable-http"],
        default=None,
    )
    parser.add_argument(
        "--host",
        dest="host",
        help="Host address for streamable-http transport. Default: 127.0.0.1",
    )
    parser.add_argument(
        "--port",
        dest="port",
        type=int,
        help="Port number for streamable-http transport. Default: 8080",
    )

    auth_group = parser.add_mutually_exclusive_group()
    auth_group.add_argument(
        "--auth-enable",
        dest="auth_enable",
        action="store_true",
        default=None,
        help="Enable Bearer token authentication for streamable-http mode.",
    )
    auth_group.add_argument(
        "--auth-disable",
        dest="auth_enable",
        action="store_false",
        default=None,
        help="Disable Bearer token authentication for streamable-http mode.",
    )
    parser.add_argument(
        "--secret-key",
        dest="secret_key",
        help="Secret key for Bearer token authentication. Required when auth is enabled.",
    )

    return parser


def load_server_config(argv: Sequence[str] | None = None) -> ServerConfig:
    """Resolve runtime config using CLI args first, then environment, then defaults."""
    args = build_arg_parser().parse_args(argv)

    if args.log_level:
        log_level = args.log_level
        log_level_source = "cli"
    elif os.getenv("MCP_LOG_LEVEL"):
        log_level = os.getenv("MCP_LOG_LEVEL", "INFO")
        log_level_source = "environment"
    else:
        log_level = "INFO"
        log_level_source = "default"

    transport_type = args.transport_type or os.getenv("FASTMCP_TYPE", "stdio")
    host = args.host or os.getenv("FASTMCP_HOST", "127.0.0.1")

    if args.port is not None:
        port = args.port
    else:
        raw_port = os.getenv("FASTMCP_PORT", "8080")
        try:
            port = int(raw_port)
        except ValueError as exc:
            raise ValueError(f"FASTMCP_PORT must be an integer, got: {raw_port}") from exc

    if args.auth_enable is None:
        auth_enable = parse_bool_env(os.getenv("REMOTE_AUTH_ENABLE"), default=False)
    else:
        auth_enable = args.auth_enable

    config = ServerConfig(
        log_level=log_level,
        log_level_source=log_level_source,
        transport_type=transport_type,
        host=host,
        port=port,
        auth_enable=auth_enable,
        secret_key=args.secret_key or os.getenv("REMOTE_SECRET_KEY", ""),
    )
    validate_config(config)
    return config


def validate_config(config: ServerConfig) -> None:
    """Validate resolved runtime configuration."""
    if config.transport_type not in ["stdio", "streamable-http"]:
        raise ValueError(f"Invalid transport type: {config.transport_type}")

    if config.transport_type == "streamable-http":
        if not config.host:
            raise ValueError("Host is required for streamable-http transport")
        if not (1 <= config.port <= 65535):
            raise ValueError(f"Port must be between 1-65535, got: {config.port}")
