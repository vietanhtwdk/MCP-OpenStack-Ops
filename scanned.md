# Security Scan Summary — openstack-mcp

**Date:** 2026-05-27
**Audited path:** `src/mcp_openstack_ops/`
**Files scanned:** 70 Python source files
**Audit type:** A — MCP Server Source Code

---

## Result Overview

| Severity | Count |
|----------|-------|
| Critical | 5 |
| High | 11 |
| Medium | 9 |
| Low | 7 |
| **Total** | **32** |

Full report: [SECURITY_AUDIT.md](SECURITY_AUDIT.md) · [SECURITY_AUDIT.json](SECURITY_AUDIT.json)

---

## Critical Findings

| ID | File | Issue |
|----|------|-------|
| F-001 | `connection.py:118` | Keystone token prefix logged at INFO level on every connection |
| F-002 | `connection.py:74,79` | `verify=False` is the default — all HTTP deployments run with no TLS validation |
| F-003 | `services/core.py:106` | Live `X-Auth-Token` sent over hardcoded `http://` via raw `requests` calls (4 sites) |
| F-004 | `services/identity.py:718` | `set_project` action=delete has no `confirm` gate — irreversible |
| F-005 | `services/compute.py:591` | `set_instance` action=delete/force_delete has no `confirm` gate |

## High Findings

| ID | File | Issue |
|----|------|-------|
| F-006 | `services/identity.py:420` | SSH private key returned in MCP tool response (injected into LLM context) |
| F-007 | `services/storage.py:147` | `set_volume` delete/force_delete — no confirm gate |
| F-008 | `services/network.py:194` | `set_networks` delete — no confirm gate, supports bulk filter |
| F-009 | `tools/set_heat_stack.py` | `set_heat_stack` delete — no confirm gate, cascades to all stack resources |
| F-010 | `tools/set_image.py` | `set_image` delete — no confirm gate, bulk operation |
| F-011 | `tools/set_keypair.py` | `set_keypair` bulk delete — no confirm gate, revokes SSH access |
| F-012 | `services/compute.py:1937` | `set_instance` evacuate — no confirm gate |
| F-013 | `mcp_main.py:375` | HTTP transport starts unauthenticated when `REMOTE_AUTH_ENABLE` is unset |
| F-014 | `connection.py:230` | `validate_resource_ownership` swallows 401/403 exceptions silently |
| F-015 | `services/identity.py:297` | User emails (PII) returned in bulk to LLM context |
| F-016 | `services/identity.py:74` | System-scope admin role assignments exposed to LLM context |

## Medium Findings

| ID | File | Issue |
|----|------|-------|
| F-017 | `services/core.py:106` | Hardcoded `http://` in Heat/LB probe URLs ignores configured protocol |
| F-018 | Multiple `tools/set_*.py` | No UUID validation on `*_id` tool inputs before SDK calls |
| F-019 | `services/core.py:166` | Unbounded resource enumeration — no pagination, risk of control-plane DoS |
| F-020 | `services/identity.py:690` | `set_project` create/update exposed without admin-scope guard |
| F-021 | `services/identity.py:283` | `set_roles` create — role name unvalidated |
| F-022 | `tools/set_quota.py` | Quota changes have no upper-bound validation |
| F-023 | `connection.py:218` | Resources missing `project_id` granted access (fail-open) |
| F-024 | `functions.py:887` | Orphaned `except` block outside `try` — exceptions not caught |
| F-025 | `pyproject.toml:10` | `openstacksdk` range too broad; `requests` unpinned |

## Low Findings

| ID | File | Issue |
|----|------|-------|
| F-026 | `mcp_main.py:239` | `ALLOW_MODIFY_OPERATIONS` read at import time; runtime changes ignored |
| F-027 | `tools/set_instance.py:36` | Imperative instructions in tool docstring — prompt injection surface |
| F-028 | `services/identity.py:88` | Garbled code fragment in `set_domains` docstring |
| F-029 | `functions.py:24,951` | `get_service_status` defined twice, shadows import |
| F-030 | `tools/set_keypair.py:243` | Unreachable code after `return` — silent log loss |
| F-031 | `connection.py:156` | Token acquired into unused variable — unnecessary exposure |
| F-032 | `tools/set_server_dump.py` | Crash dump trigger (NMI) — no confirm gate |

---

## Top Recommended Fixes

1. **Remove** `{token[:20]}` from `connection.py:118` — one-line fix
2. **Add `confirm: bool = False`** to every destructive `set_*` action (delete, force_delete, evacuate, trigger_crash_dump)
3. **Migrate** raw `requests.get()` in `services/core.py` to the OpenStack SDK transport
4. **Default to HTTPS** — require `ALLOW_INSECURE_HTTP=true` as explicit opt-in
5. **Remove `private_key`** from `set_keypair` create response
6. **Default `REMOTE_AUTH_ENABLE=true`** for HTTP transport
