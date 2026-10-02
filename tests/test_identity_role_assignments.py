from types import SimpleNamespace

from mcp_openstack_ops.services import identity


def test_parse_project_group_assignment():
    assignment = {
        "group": {"id": "group-1"},
        "role": {"id": "role-1"},
        "scope": {"project": {"id": "project-1"}},
    }

    parsed = identity._parse_role_assignment(assignment, current_project_id="project-1")

    assert parsed["actor_type"] == "group"
    assert parsed["group_id"] == "group-1"
    assert parsed["user_id"] == "N/A"
    assert parsed["project_id"] == "project-1"
    assert parsed["scope_type"] == "project"
    assert parsed["in_current_project"] is True


def test_parse_system_user_assignment():
    assignment = {
        "user": {"id": "user-1"},
        "role": {"id": "role-1"},
        "scope": {"system": {"all": True}},
    }

    parsed = identity._parse_role_assignment(assignment, current_project_id="project-1")

    assert parsed["actor_type"] == "user"
    assert parsed["user_id"] == "user-1"
    assert parsed["scope_type"] == "system"
    assert parsed["system_scope"] is True
    assert parsed["in_current_project"] is False


def test_get_role_assignments_keeps_group_assignments(monkeypatch):
    class FakeIdentity:
        def role_assignments(self, include_names=False):
            return [
                SimpleNamespace(
                    group={"id": "group-1"},
                    role={"id": "role-1"},
                    scope={"project": {"id": "project-1"}},
                ),
                SimpleNamespace(
                    user={"id": "user-1"},
                    role={"id": "role-2"},
                    scope={"domain": {"id": "domain-1"}},
                ),
            ]

    fake_conn = SimpleNamespace(current_project_id="project-1", identity=FakeIdentity())
    monkeypatch.setattr(
        "mcp_openstack_ops.connection.get_openstack_connection",
        lambda: fake_conn,
    )

    assignments = identity.get_role_assignments()

    assert len(assignments) == 2
    assert assignments[0]["actor_type"] == "group"
    assert assignments[0]["group_id"] == "group-1"
    assert assignments[1]["scope_type"] == "domain"


def test_get_user_list_includes_users_from_project_groups(monkeypatch):
    class FakeIdentity:
        def role_assignments(self, include_names=False):
            return [
                SimpleNamespace(
                    group={"id": "group-1"},
                    role={"id": "role-1"},
                    scope={"project": {"id": "project-1"}},
                ),
                SimpleNamespace(
                    user={"id": "user-2"},
                    role={"id": "role-2"},
                    scope={"project": {"id": "project-1"}},
                ),
            ]

        def group_users(self, group_id):
            assert group_id == "group-1"
            return [SimpleNamespace(id="user-1")]

        def users(self):
            return [
                SimpleNamespace(id="user-1", name="group-user", is_enabled=True),
                SimpleNamespace(id="user-2", name="direct-user", is_enabled=True),
                SimpleNamespace(id="user-3", name="other-user", is_enabled=True),
            ]

    fake_conn = SimpleNamespace(current_project_id="project-1", identity=FakeIdentity())
    monkeypatch.setattr(
        "mcp_openstack_ops.connection.get_openstack_connection",
        lambda: fake_conn,
    )

    users = identity.get_user_list()

    assert {user["id"] for user in users} == {"user-1", "user-2"}
