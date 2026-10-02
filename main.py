"""Repository-level entry point for local development."""

import os
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from mcp_openstack_ops.mcp_main import main

if __name__ == "__main__":
    main()
