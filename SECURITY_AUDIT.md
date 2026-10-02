# Security Audit — openstack-mcp

**Audited path:** `src/mcp_openstack_ops/`
**Artifact type:** A: MCP source
**Date:** 2026-05-27
**Files scanned:** 70

---

## Summary

| Severity | Count |
|---|---|
| Critical | 5 |
| High | 11 |
| Medium | 9 |
| Low | 7 |

---

## Findings

### [CRITICAL] F-001 — Plaintext Keystone token fragment logged on every connection

**Category:** logging-hygiene / token-handling
**Location:** `src/mcp_openstack_ops/connection.py:118`
**Evidence:** `logger.info(f"OpenStack connection successful. Token acquired: {token[:20]}...")`
**Why it matters:** A 20-character Keystone token prefix is emitted to the application log at INFO level on every successful connection. Anyone with log-read access can harvest this prefix, which reveals the token format and may be sufficient for correlation or timing attacks. Log aggregation systems (ELK, Loki, CloudWatch) store these indefinitely.
**Confidence:** high
**Suggested fix:**
```python
# Before
logger.info(f"OpenStack connection successful. Token acquired: {token[:20]}...")
# After
logger.info("OpenStack connection successful. Token acquired.")
```

---

### [CRITICAL] F-002 — SSL verification silently disabled for all HTTP connections (default configuration)

**Category:** insecure-transport
**Location:** `src/mcp_openstack_ops/connection.py:74`, `connection.py:79`
**Evidence:**
```
verify_ssl = False  # line 74 — HTTPS without OS_CACERT
verify_ssl = False  # line 79 — HTTP mode (the default)
```
**Why it matters:** `OS_AUTH_PROTOCOL` defaults to `"http"` (line 57). Every deployment that has not explicitly set `OS_AUTH_PROTOCOL=https` AND `OS_CACERT` runs with `verify=False` on all service endpoints (Keystone, Nova, Neutron, Cinder, Glance, Heat, Octavia). An MITM attacker on the same network can intercept credentials and tokens in transit with zero detection.
**Confidence:** high
**Suggested fix:** Default the protocol to `https`. Require `ALLOW_INSECURE_HTTP=true` as an explicit env-var opt-in for HTTP mode. Refuse to start without `OS_CACERT` set when using HTTPS (or add `OS_INSECURE=true` opt-out). Never set `verify=False` silently.

---

### [CRITICAL] F-003 — Live Keystone token sent over hardcoded `http://` via raw `requests` calls

**Category:** insecure-transport / token-handling
**Location:** `src/mcp_openstack_ops/services/core.py:106–119`, `core.py:374`, `core.py:1019`, `core.py:1158–1172`
**Evidence:**
```python
token = conn.identity.get_token()
heat_url = f"http://{auth_host}:{heat_port}/v1/{project_id}/stacks"
headers = {'X-Auth-Token': token}
response = requests.get(heat_url, headers=headers, timeout=5)
```
**Why it matters:** Raw `requests.get()` calls bypass the SDK transport layer and unconditionally use `http://`. The live `X-Auth-Token` is transmitted in cleartext regardless of the operator's `OS_AUTH_PROTOCOL` setting. This occurs in four separate call sites covering Heat and Load Balancer service probes.
**Confidence:** high
**Suggested fix:** Use the SDK: `conn.orchestration.stacks()` instead of raw requests. If bypassing the SDK is unavoidable, construct the URL using `os_auth_protocol` and validate the TLS certificate.

---

### [CRITICAL] F-004 — `set_project` action=delete has no confirmation gate

**Category:** openstack-admin-scope / destructive-delete-no-confirm
**Location:** `src/mcp_openstack_ops/services/identity.py:718–742`
**Evidence:** `conn.identity.delete_project(project)` — no `confirm: bool` parameter or second-factor check exists.
**Why it matters:** An LLM misinterpretation or prompt-injection attack can permanently delete an entire OpenStack project and all associated resources with a single tool call. This action is irreversible.
**Confidence:** high
**Suggested fix:**
```python
def set_project(project_name: str, action: str, confirm: bool = False, ...):
    if action == "delete" and not confirm:
        return {"dry_run": True, "target": project_name,
                "message": "Re-call with confirm=True to permanently delete this project."}
    conn.identity.delete_project(project)
```

---

### [CRITICAL] F-005 — `set_instance` action=delete/force_delete has no confirmation gate

**Category:** openstack-admin-scope / destructive-delete-no-confirm
**Location:** `src/mcp_openstack_ops/services/compute.py:591–604`
**Evidence:**
```python
elif action.lower() in ['delete', 'terminate']:
    force = kwargs.get('force', False)
    if force:
        conn.compute.force_delete_server(server)
    else:
        conn.compute.delete_server(server)
```
**Why it matters:** Both `delete_server` and `force_delete_server` are exposed as MCP tool actions with no confirmation parameter. An LLM misinterpretation can immediately destroy production instances.
**Confidence:** high
**Suggested fix:** Add `confirm: bool = False` parameter. Gate both delete paths on `confirm=True`. Return dry-run details (instance name, ID, status) when `confirm=False`.

---

### [HIGH] F-006 — SSH private key returned in MCP tool response

**Category:** data-exfil-to-llm
**Location:** `src/mcp_openstack_ops/services/identity.py:420`
**Evidence:** `'private_key': getattr(keypair, 'private_key', None),  # Only available on creation`
**Why it matters:** When Nova generates a keypair, the private key is placed directly in the tool's JSON response, injecting it into the LLM's context window. It may then appear in conversation logs, session transcripts, or be exfiltrated via prompt injection.
**Confidence:** high
**Suggested fix:** Remove `private_key` from the response entirely. Inform the user that the key was generated and must be downloaded through a secure out-of-band channel. Never pass private key material through the LLM context.

---

### [HIGH] F-007 — `set_volume` action=delete (including force) has no confirmation gate

**Category:** destructive-delete-no-confirm
**Location:** `src/mcp_openstack_ops/services/storage.py:147–178`
**Evidence:** `conn.volume.delete_volume(volume, force=kwargs.get('force', False))` — exposed via MCP tool with no `confirm` parameter.
**Why it matters:** Volume deletion is irreversible. Force-deleting an attached volume can corrupt the guest filesystem. Bulk deletion via name filters makes it trivially easy to wipe multiple volumes.
**Confidence:** high
**Suggested fix:** Add `confirm: bool = False` gate to the tool. Gate both normal and force-delete paths on `confirm=True`.

---

### [HIGH] F-008 — `set_networks` action=delete has no confirmation gate

**Category:** destructive-delete-no-confirm
**Location:** `src/mcp_openstack_ops/services/network.py:194–217`
**Evidence:** `conn.network.delete_network(network)` — callable via bulk filter-based MCP tool with no confirm parameter.
**Why it matters:** Network deletion cascades to subnets, ports, and floating-IP associations. Filter-based bulk deletion (e.g., `name_contains="prod"`) can wipe all networks matching a broad pattern with a single call.
**Confidence:** high
**Suggested fix:** Add `confirm: bool = False` and add `dry_run: bool = True` as default for filter-based operations that lists targets before acting.

---

### [HIGH] F-009 — `set_heat_stack` action=delete has no confirmation gate

**Category:** destructive-delete-no-confirm
**Location:** `src/mcp_openstack_ops/tools/set_heat_stack.py`
**Evidence:** `set_heat_stack(stack_names="...", action="delete")` — no `confirm` parameter in the tool definition.
**Why it matters:** Heat stack deletion recursively deletes all managed resources (instances, networks, volumes, etc.). This is irreversible.
**Confidence:** high
**Suggested fix:** Add `confirm: bool = False` gate.

---

### [HIGH] F-010 — `set_image` action=delete has no confirmation gate

**Category:** destructive-delete-no-confirm
**Location:** `src/mcp_openstack_ops/tools/set_image.py`
**Evidence:** `set_image(image_names="...", action="delete")` — bulk operation, no confirm parameter.
**Why it matters:** Image deletion is irreversible. A single misclassified pattern like `name_contains="ubuntu"` could wipe all base images needed for instance provisioning.
**Confidence:** high
**Suggested fix:** Add `confirm: bool = False` gate, especially for bulk/filter-based operations.

---

### [HIGH] F-011 — `set_keypair` bulk delete has no confirmation gate

**Category:** destructive-delete-no-confirm
**Location:** `src/mcp_openstack_ops/tools/set_keypair.py`
**Evidence:** `set_keypair(action="delete", name_contains="...")` — deletes all matching keypairs with no confirmation.
**Why it matters:** Keypair deletion revokes SSH access to all instances using those keys. Bulk deletion via `name_contains` with no gate could lock out all operators from running instances.
**Confidence:** high
**Suggested fix:** Add `confirm: bool = False` gate.

---

### [HIGH] F-012 — `set_instance` action=evacuate has no confirmation gate

**Category:** destructive-delete-no-confirm
**Location:** `src/mcp_openstack_ops/services/compute.py:1937–1954`
**Evidence:** `conn.compute.evacuate_server(server, **evacuate_params)` — directly callable with no confirm gate.
**Why it matters:** Calling evacuate on a running instance on a healthy host can cause data corruption or unexpected VM restart.
**Confidence:** high
**Suggested fix:** Add `confirm: bool = False` gate.

---

### [HIGH] F-013 — HTTP transport starts without authentication when `REMOTE_AUTH_ENABLE` is unset

**Category:** auth-authz / mcp-transport
**Location:** `src/mcp_openstack_ops/mcp_main.py:375–389`
**Evidence:**
```python
if config.auth_enable:
    ...
else:
    logger.warning("WARNING: streamable-http mode without authentication enabled!")
    # mcp.auth = None — all requests accepted
```
**Why it matters:** The server accepts any connection (including all destructive tools) without a Bearer token when `REMOTE_AUTH_ENABLE` is not explicitly set to `true`. In any container or CI/CD deployment where the variable is not set, the server is fully open.
**Confidence:** high
**Suggested fix:** Default `auth_enable` to `True` for HTTP transport. Require `REMOTE_AUTH_ENABLE=false` for an explicit opt-out. Emit a CRITICAL-level log (not WARNING) and refuse to start unless `ALLOW_UNAUTHENTICATED_HTTP=true` is also set.

---

### [HIGH] F-014 — `validate_resource_ownership` swallows auth exceptions, hiding auth failures

**Category:** auth-authz / exception-swallowing
**Location:** `src/mcp_openstack_ops/connection.py:230–232`
**Evidence:**
```python
    except Exception as e:
        logger.error(f"Failed to validate resource ownership: {e}")
        return False
```
**Why it matters:** Any exception — including HTTP 401 Unauthorized, 403 Forbidden, and network timeout — causes the function to return `False`, silently blocking access without differentiating between a real cross-project denial and a broken auth service. Operators cannot diagnose auth failures.
**Confidence:** high
**Suggested fix:** Re-raise HTTP 401/403 exceptions. Return `False` only for genuine cross-project denials. Consider a custom `AuthCheckError` sentinel for auth failures.

---

### [HIGH] F-015 — `get_user_list` returns full user emails to LLM context (PII)

**Category:** data-exfil-to-llm / pii
**Location:** `src/mcp_openstack_ops/services/identity.py:293–303`, `tools/get_user_list.py`
**Evidence:** `'email': getattr(user, 'email', 'N/A')` — email addresses of all project users returned in bulk.
**Why it matters:** User emails are PII. Returning them in bulk to the LLM context means they can be captured in conversation logs, session transcripts, or exfiltrated via prompt injection.
**Confidence:** medium — email exposure is real, but severity depends on deployment context
**Suggested fix:** Omit `email` from the default response. Add `include_email: bool = False` opt-in parameter.

---

### [HIGH] F-016 — `get_role_assignments` returns system-scope admin assignments to LLM context

**Category:** data-exfil-to-llm / privilege-disclosure
**Location:** `src/mcp_openstack_ops/services/identity.py:74–85`
**Evidence:** `"system_scope": system_scope` — system-scoped role assignments (admin-level) included in the tool response.
**Why it matters:** Disclosing which users have system-scoped roles in LLM context exposes the privilege topology of the deployment. A prompt-injection attack can read this to identify high-value targets.
**Confidence:** medium
**Suggested fix:** Filter out `scope_type="system"` assignments from the default response, or redact `user_id` for system-scoped assignments.

---

### [MEDIUM] F-017 — Hardcoded `http://` URLs for Heat and LB probe calls bypass configured protocol

**Category:** insecure-transport
**Location:** `src/mcp_openstack_ops/services/core.py:106`, `core.py:119`, `core.py:374`, `core.py:1019`, `core.py:1158`, `core.py:1172`
**Evidence:** `heat_url = f"http://{auth_host}:{heat_port}/v1/{project_id}/stacks"`
**Why it matters:** Even if an operator configures `OS_AUTH_PROTOCOL=https`, these direct `requests.get()` calls hardcode `http://`, always sending tokens over plaintext. The configured protocol is ignored.
**Confidence:** high
**Suggested fix:** Use `os_auth_protocol` variable: `f"{os_auth_protocol}://{auth_host}:..."`. Better: remove all raw `requests` usage and use the SDK exclusively.

---

### [MEDIUM] F-018 — No UUID validation on tool inputs used as OpenStack resource identifiers

**Category:** input-validation
**Location:** All `set_*` and `get_*` tools — e.g., `tools/set_instance.py`, `tools/set_volume.py`, `tools/set_project.py`, `services/compute.py:252`
**Evidence:** Parameters typed as `str` with no UUID format validation before passing to OpenStack SDK calls. Example: `get_instance_by_id(instance_id: str)` passes `instance_id` directly without UUID verification.
**Why it matters:** Unvalidated string inputs can cause unexpected behavior. In the MCP threat model, prompt-injection attacks could supply crafted strings to probe internal API behavior.
**Confidence:** medium
**Suggested fix:**
```python
import re
UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)

def validate_uuid(value: str, name: str) -> None:
    if not UUID_RE.match(value):
        raise ValueError(f"{name} must be a valid UUID, got: {value!r}")
```

---

### [MEDIUM] F-019 — Unbounded resource enumeration without pagination (DoS against control plane)

**Category:** openstack-api-misuse / no-pagination
**Location:** `src/mcp_openstack_ops/services/core.py:166–327`, `services/identity.py:293–303`, `services/network.py:34–75`
**Evidence:**
```python
all_servers = list(conn.compute.servers(details=True, all_projects=False))
for user in conn.identity.users():
for assignment in conn.identity.role_assignments():
```
**Why it matters:** A single `get_service_status` call fetches all instances, networks, subnets, routers, floating IPs, ports, and volumes in one sweep. In large deployments this causes memory exhaustion and API gateway timeouts, effectively a self-inflicted DoS on the control plane.
**Confidence:** medium
**Suggested fix:** Use `limit` and `marker` pagination. Define `MAX_RESOURCE_PAGE_SIZE = 200` and never call `list()` without a bound.

---

### [MEDIUM] F-020 — `set_project` create/update exposed without admin-scope guard

**Category:** excessive-tool-surface / admin-operation
**Location:** `src/mcp_openstack_ops/tools/set_project.py`, `services/identity.py:690–716`
**Evidence:** `conn.identity.create_project(...)` — gated only by `ALLOW_MODIFY_OPERATIONS` flag.
**Why it matters:** Project creation is a Keystone admin operation. If the MCP service account has the `admin` role, this tool allows the LLM to create arbitrary new projects, potentially used to silo resources or evade billing/audit controls.
**Confidence:** medium
**Suggested fix:** Require a separate `admin_confirm: str` parameter matching a server-side configured token for admin operations (create/delete project, create/delete domain).

---

### [MEDIUM] F-021 — `set_roles` action=create creates Keystone roles without name validation

**Category:** excessive-tool-surface / input-validation
**Location:** `src/mcp_openstack_ops/tools/set_roles.py:30–35`, `services/identity.py:283–309`
**Evidence:** `conn.identity.create_role(name=role_name, ...)` — `role_name` is unvalidated.
**Why it matters:** A prompt-injection could trigger creation of a role with a name colliding with a built-in role or exploiting string matching in third-party RBAC tooling.
**Confidence:** medium
**Suggested fix:** Validate `role_name` against a regex that prohibits special characters (e.g., `^[a-zA-Z0-9_-]{1,64}$`). Log role creation as a WARN-level security event.

---

### [MEDIUM] F-022 — `set_quota` allows raising limits for any project without bounds validation

**Category:** excessive-tool-surface / privilege-escalation
**Location:** `src/mcp_openstack_ops/tools/set_quota.py`
**Evidence:** `set_quota(project_name=..., action="set", cores=999, ram=9999999)` — no guard other than `ALLOW_MODIFY_OPERATIONS`.
**Why it matters:** Quota manipulation is an admin-level operation. Allowing the LLM to set arbitrary quota limits enables resource exhaustion attacks against other tenants.
**Confidence:** medium
**Suggested fix:** Add maximum bounds validation per parameter. Require `confirm=True` for quota changes that exceed current values by more than a configured percentage threshold.

---

### [MEDIUM] F-023 — `validate_resource_ownership` returns `True` for resources with no `project_id` (overly permissive fallback)

**Category:** auth-authz / overly-permissive
**Location:** `src/mcp_openstack_ops/connection.py:218–220`
**Evidence:**
```python
if not resource_project_id:
    logger.debug(f"System {resource_type} ... with no project_id - allowing access")
    return True
```
**Why it matters:** Resources missing `project_id` due to an API version mismatch or SDK bug are unconditionally granted access instead of defaulting to deny. This is a fail-open security posture.
**Confidence:** medium
**Suggested fix:** Default to `return False` (deny) when `project_id` cannot be determined, unless the resource type is in an explicit allowlist (flavors, public images).

---

### [MEDIUM] F-024 — Dead exception handler in `functions.py` (orphaned `except` outside `try`)

**Category:** static-code / dead-code
**Location:** `src/mcp_openstack_ops/functions.py:887–893`
**Evidence:**
```python
    except Exception as e:
        logger.error(f"Failed to manage compute agents: {e}")
        return { 'success': False, ... }
```
This `except` block appears outside any `try` block — the function's `try` block ends at line 884. Genuine exceptions are not caught as intended.
**Confidence:** high
**Suggested fix:** Remove the duplicate `except` block and ensure the enclosing `try` covers all relevant statements.

---

### [MEDIUM] F-025 — `openstacksdk` dependency range too broad; `requests` unpinned

**Category:** dependency-risk
**Location:** `pyproject.toml:10`
**Evidence:** `"openstacksdk>=4.1.0,<=4.11.0"` — spans ~10 minor versions; `requests` is not a direct dependency.
**Why it matters:** Without a committed lock file and exact pin, a compromised mirror could serve a malicious in-range version. Versions between 4.1.0 and 4.11.0 may include unpatched CVEs.
**Confidence:** medium
**Suggested fix:** Pin to an exact tested version (e.g., `openstacksdk==4.11.0`). Add `requests` as a direct dependency with a pinned minimum. Commit `uv.lock` to source control.

---

### [LOW] F-026 — `ALLOW_MODIFY_OPERATIONS` flag read at import time; runtime changes ignored

**Category:** mcp-specific / tool-registration
**Location:** `src/mcp_openstack_ops/mcp_main.py:239–248`
**Evidence:** `if _is_modify_operation_allowed(): return mcp.tool()(func)` — evaluated once at module import.
**Why it matters:** If the environment variable changes at runtime (e.g., via a sidecar process), tool registration state is stale. This is not an immediate vulnerability, but should be documented.
**Confidence:** low
**Suggested fix:** Document the behavior clearly. Add a startup assertion that the variable is read exactly once and immutable after that.

---

### [LOW] F-027 — `set_instance` tool docstring contains imperative LLM-targeted instructions

**Category:** tool-description-hygiene
**Location:** `src/mcp_openstack_ops/tools/set_instance.py:36–91`
**Evidence:** Docstring contains "CRITICAL: For create action, both flavor AND image are REQUIRED." and prescriptive behavioral instructions.
**Why it matters:** Overly prescriptive imperative-tone docstrings can be exploited by prompt injection to embed conflicting instructions adjacent to operator-controlled text.
**Confidence:** low
**Suggested fix:** Keep tool descriptions focused on parameter documentation. Move validation guidance into runtime error messages, not the MCP tool description.

---

### [LOW] F-028 — Garbled code fragment embedded in `set_domains` docstring

**Category:** static-code / code-quality
**Location:** `src/mcp_openstack_ops/services/identity.py:88–114`
**Evidence:** Docstring contains a stray copy-paste fragment of compute-resource calculation code and a garbled `continueate)` token.
**Why it matters:** Indicates file corruption or incorrect generation. May mask logic errors and confuses static analysis.
**Confidence:** high
**Suggested fix:** Clean up the function docstring to remove all embedded code fragments.

---

### [LOW] F-029 — `get_service_status` defined twice in `functions.py`, shadowing the import

**Category:** static-code / shadow-import
**Location:** `src/mcp_openstack_ops/functions.py:24`, `functions.py:951`
**Evidence:**
```python
from .services.core import (get_service_status)  # line 17
def get_service_status() -> ...:  # line 24 — shadows the import
# ... and again at line 951
```
**Why it matters:** Python's last-definition-wins rule means security-relevant changes in one implementation may not propagate. Callers may invoke the wrong version silently.
**Confidence:** high
**Suggested fix:** Remove duplicate definitions. Use the `services.core` import exclusively.

---

### [LOW] F-030 — Unreachable code after `return` in `set_keypair.py`

**Category:** static-code / dead-code
**Location:** `src/mcp_openstack_ops/tools/set_keypair.py:243–244`
**Evidence:**
```python
        return error_msg
        logger.error(error_msg)  # unreachable
        return error_msg          # unreachable
```
**Why it matters:** Copy-paste artifact. Unreachable logging means errors are silently dropped in this path, complicating incident debugging.
**Confidence:** high
**Suggested fix:** Remove the two unreachable lines after the first `return error_msg`.

---

### [LOW] F-031 — `get_current_project_id` acquires a token into a local variable that is never used

**Category:** static-code / unused-variable / minor-token-exposure
**Location:** `src/mcp_openstack_ops/connection.py:156`
**Evidence:** `token = conn.identity.get_token()` — `token` is never referenced after this line.
**Why it matters:** The token is acquired unnecessarily, increasing the token's exposure surface (it is now held in a local variable for the function's lifetime). Acquiring tokens without use is a minor hygiene violation.
**Confidence:** high
**Suggested fix:** Remove the `token = ...` line entirely. The project ID can be retrieved without explicitly acquiring a token object.

---

### [LOW] F-032 — `set_server_dump` tool exposes OS-level memory dump trigger without confirmation

**Category:** excessive-tool-surface
**Location:** `src/mcp_openstack_ops/tools/set_server_dump.py`
**Evidence:** Tool exposes `action=trigger_crash_dump` which forces an ACPI crash dump (NMI) on a live instance — no `confirm` parameter.
**Why it matters:** Triggering a crash dump immediately disrupts the instance and may corrupt in-flight transactions. No confirmation gate exists.
**Confidence:** high
**Suggested fix:** Add `confirm: bool = False` gate.

---

## Recommendations (non-findings)

### Immediate

- **F-001**: Remove token fragment from connection log. One-line fix, zero risk, immediate benefit.
- **F-003**: Migrate all raw `requests.get()` calls in `services/core.py` to the OpenStack SDK transport. This eliminates the `X-Auth-Token` cleartext exposure in four places.
- **F-004, F-005, F-007–F-012, F-032**: Add `confirm: bool = False` gates to all destructive MCP tool actions. This is the single highest-impact architectural change: it makes all irreversible actions require explicit user intent rather than LLM inference.

### Short-term

- **Transport hardening** (F-002): Reverse the `verify_ssl = False` default. Require `ALLOW_INSECURE_HTTP=true` as an opt-in. Add a startup check that refuses to run over HTTP without an explicit override.
- **Private key exfiltration** (F-006): Remove `private_key` from all tool responses. Implement a secure out-of-band delivery mechanism.
- **Auth for HTTP transport** (F-013): Default `REMOTE_AUTH_ENABLE=true`. Require explicit opt-out.
- **PII minimization** (F-015): Remove `email` from `get_user_list` default response. Add `include_email: bool = False` opt-in.
- **Auth error propagation** (F-014, F-023): Fix `validate_resource_ownership` to re-raise 401/403 and default to deny on unknown resource state.

### Medium-term

- **UUID input validation** (F-018): Add a `validate_uuid()` helper and apply it to all `*_id` tool parameters before they reach the SDK.
- **Pagination** (F-019): Add `MAX_PAGE_SIZE = 200` constant and paginate all list calls. Particularly critical for `get_service_status` which queries every resource type in one call.
- **Code-quality fixes** (F-024, F-028–F-031): Remove duplicate `get_service_status` definitions, orphaned `except` block, garbled `set_domains` docstring, dead code in `set_keypair.py`, unused token variable.
- **Dependency pinning** (F-025): Pin `openstacksdk` to an exact version; commit `uv.lock`.

### Architecture

- **Separate read-only and write MCP servers**: The current binary `ALLOW_MODIFY_OPERATIONS` flag is too coarse. Consider two distinct servers (read-only, admin) with different credentials and auth requirements, following the principle of least privilege.
- **Data minimization at the serialization layer**: Define a schema of fields that are never returned in tool responses (private keys, tokens, credential objects, system-scoped role assignments) and enforce it centrally — not at each individual call site.
- **Adopt HTTPS-first transport policy**: All production deployments should mandate HTTPS with certificate validation. HTTP should require two explicit env-var opt-ins and emit a CRITICAL startup log.
- **Add secrets audit pre-commit hook**: Install `gitleaks` or `detect-secrets` as a pre-commit hook to catch any future token/password logging before it reaches the repository.
- **Tool surface audit**: Review every `set_*` tool and classify each action as: read-safe / confirm-required / admin-only. Document the classification in the tool description so the LLM can surface it to the user before proceeding.
