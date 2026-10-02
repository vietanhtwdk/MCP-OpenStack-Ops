# Release Notes

## 2026-05-26 Local Update

This local update focuses on read-only MCP information paths for OpenStack. No
`set_*`, create, update, delete, or other mutating tool paths were intentionally
changed.

### Local Startup Refactor

- Added `src/mcp_openstack_ops/config.py` for typed runtime configuration from
  CLI arguments and environment variables.
- Simplified MCP startup logging/auth/transport setup in
  `src/mcp_openstack_ops/mcp_main.py`.
- Changed repository-level `main.py` so `uv run python main.py` launches the
  real MCP server instead of the placeholder command.
- Removed noisy import-time info logging from the MCP server module.
- Adjusted `handle_operation_result` so non-dict results return as plain
  strings instead of being JSON-encoded unexpectedly.

### Refactor Safety Rule

- Added a project instruction in `.github/copilot-instructions.md`:
  future refactors should target read-only information paths first
  (`get_*`, `search_*`, monitoring, status, list/detail/query code).
- Mutating paths such as `set_*`, create, update, delete, attach, detach,
  failover, backup, restore, migration, and quota-changing code must not be
  touched unless explicitly requested.

### Identity Role Assignment Fix

Fixed a parser crash in `get_role_assignments` and related identity queries.

- Added safe Keystone role-assignment parsing for:
  - user-to-project assignments
  - group-to-project assignments
  - domain-scoped assignments
  - system-scoped assignments
- `get_role_assignments()` now preserves group assignments instead of crashing
  when `assignment.user` is absent.
- Per-entry parsing failures are skipped with warnings, so one malformed
  assignment no longer discards the full response.
- Removed dummy fallback records from `get_role_assignments()` and
  `get_user_list()`.
- `get_user_list()` now resolves users from project group assignments through
  Keystone `group_users()`.
- Added focused tests in `tests/test_identity_role_assignments.py`.

Live read-only check with `OS_PROJECT_NAME=nmaa`:

| Check | Result |
|---|---:|
| Users returned | 4 |
| Role assignments returned | 29 |
| Assignments in current project | 3 |
| Group assignment entries parsed | 1 |

Current project role assignment names resolved from Keystone:

| Actor Type | Name | Project | Role |
|---|---|---|---|
| user | admin | nmaa | admin |
| user | hoangnv | nmaa | member |
| group | hehe | nmaa | member |

### Hypervisor Capacity Fix

Fixed `get_hypervisor_details` returning fake zero values for per-node CPU,
RAM, disk, and running VM fields.

- Pins Nova hypervisor capacity calls to microversion `2.87`, where per-node
  capacity fields are still available.
- Reads the OpenStack SDK field aliases used for Nova capacity fields:
  - `memory_size` / `memory_used`
  - `local_disk_size` / `local_disk_used`
  - `vcpus`, `vcpus_used`, `running_vms`
- Missing capacity values now return `None` and list the missing fields instead
  of silently returning `0`.
- Adds uptime and load-average parsing from Nova hypervisor uptime text.
- Uses a read-only Nova `2.88` enrichment call for uptime/load data when the
  `2.87` capacity response does not include uptime.
- Added focused tests in `tests/test_hypervisor_details.py`.

Live read-only hypervisor check:

| Metric | Value |
|---|---:|
| Hypervisors | 3 |
| vCPUs total | 96 |
| vCPUs used | 36 |
| RAM total MB | 322,093 |
| RAM used MB | 62,976 |
| Local disk GB | 282 |
| Local disk used GB | 120 |
| Running VMs | 6 |

### Validation

Commands run locally:

```powershell
uv run python -m compileall src tests
uv run --extra dev python -m pytest tests\test_identity_role_assignments.py
uv run --extra dev python -m pytest tests\test_hypervisor_details.py tests\test_identity_role_assignments.py
```

Latest combined result:

```text
8 passed
```

### Operational Notes

- Local `.env` was created for testing and set to `OS_PROJECT_NAME=nmaa`.
- `ALLOW_MODIFY_OPERATIONS=false` remained enabled for all live checks.
- HTTPS connectivity works, but `OS_CACERT` is not configured, so the current
  connection code disables certificate verification and logs a warning. Configure
  `OS_CACERT` before using this against production environments.
- The upstream repository contains a Windows-invalid
  `img/screenshot-claude-desktop.png:Zone.Identifier` path, so Git status may be
  noisy on Windows even though the working files are usable.
