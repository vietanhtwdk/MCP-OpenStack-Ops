from types import SimpleNamespace

from mcp_openstack_ops.services import monitoring


def test_format_hypervisor_reads_capacity_and_load_average():
    hypervisor = SimpleNamespace(
        id="hv-1",
        name="compute-1",
        host_ip="192.0.2.10",
        status="enabled",
        state="up",
        vcpus=64,
        vcpus_used=12,
        memory_size=262144,
        memory_used=65536,
        local_disk_size=1000,
        local_disk_used=250,
        running_vms=8,
        hypervisor_type="QEMU",
        hypervisor_version=8002002,
        uptime="17:05:21 up 137 days, 20:28, 1 user, load average: 1.22, 1.32, 1.39",
    )

    result = monitoring._format_hypervisor(hypervisor)

    assert result["vcpus"] == 64
    assert result["memory_mb"] == 262144
    assert result["memory_mb_used"] == 65536
    assert result["local_gb"] == 1000
    assert result["local_gb_used"] == 250
    assert result["running_vms"] == 8
    assert result["capacity_data_available"] is True
    assert result["missing_capacity_fields"] == []
    assert result["load_average"] == {"1m": 1.22, "5m": 1.32, "15m": 1.39}


def test_format_hypervisor_does_not_zero_missing_capacity_fields():
    hypervisor = SimpleNamespace(
        id="hv-1",
        name="compute-1",
        host_ip="192.0.2.10",
        status="enabled",
        state="up",
        hypervisor_type="QEMU",
        hypervisor_version=8002002,
        uptime="17:05:21 up 137 days, 20:28, 1 user, load average: 1.22, 1.32, 1.39",
    )

    result = monitoring._format_hypervisor(hypervisor)

    assert result["vcpus"] is None
    assert result["memory_mb"] is None
    assert result["local_gb"] is None
    assert result["running_vms"] is None
    assert result["capacity_data_available"] is False
    assert "memory_mb" in result["missing_capacity_fields"]


def test_get_hypervisor_details_uses_capacity_microversion(monkeypatch):
    class FakeStatsResponse:
        status_code = 200

        def json(self):
            return {
                "hypervisor_statistics": {
                    "count": 1,
                    "vcpus": 64,
                    "vcpus_used": 12,
                    "memory_mb": 262144,
                    "memory_mb_used": 65536,
                    "local_gb": 1000,
                    "local_gb_used": 250,
                    "running_vms": 8,
                }
            }

    class FakeCompute:
        def __init__(self):
            self.hypervisor_microversion = None
            self.statistics_microversion = None

        def hypervisors(self, details=False, microversion=None):
            self.hypervisor_microversion = microversion
            assert details is True
            return [
                SimpleNamespace(
                    id="hv-1",
                    name="compute-1",
                    host_ip="192.0.2.10",
                    status="enabled",
                    state="up",
                    vcpus=64,
                    vcpus_used=12,
                    memory_size=262144,
                    memory_used=65536,
                    local_disk_size=1000,
                    local_disk_used=250,
                    running_vms=8,
                    hypervisor_type="QEMU",
                    hypervisor_version=8002002,
                    uptime="17:05:21 up 137 days, 20:28, 1 user, load average: 1.22, 1.32, 1.39",
                )
            ]

        def get(self, path, microversion=None):
            assert path == "/os-hypervisors/statistics"
            self.statistics_microversion = microversion
            return FakeStatsResponse()

    fake_compute = FakeCompute()
    fake_conn = SimpleNamespace(compute=fake_compute)
    monkeypatch.setattr(
        "mcp_openstack_ops.connection.get_openstack_connection",
        lambda: fake_conn,
    )

    result = monitoring.get_hypervisor_details()

    assert result["success"] is True
    assert result["microversion"] == "2.87"
    assert fake_compute.hypervisor_microversion == "2.87"
    assert fake_compute.statistics_microversion == "2.87"
    assert result["hypervisors"][0]["memory_mb"] == 262144
    assert result["total_stats"]["memory_mb"] == 262144
    assert result["total_stats"]["capacity_data_available"] is True


def test_get_hypervisor_details_enriches_missing_uptime_from_288(monkeypatch):
    class FakeStatsResponse:
        status_code = 200

        def json(self):
            return {"hypervisor_statistics": {}}

    class FakeCompute:
        def hypervisors(self, details=False, microversion=None):
            assert details is True
            if microversion == "2.87":
                return [
                    SimpleNamespace(
                        id="hv-1",
                        name="compute-1",
                        host_ip="192.0.2.10",
                        status="enabled",
                        state="up",
                        vcpus=64,
                        vcpus_used=12,
                        memory_size=262144,
                        memory_used=65536,
                        local_disk_size=1000,
                        local_disk_used=250,
                        running_vms=8,
                        hypervisor_type="QEMU",
                        hypervisor_version=8002002,
                    )
                ]
            if microversion == "2.88":
                return [
                    SimpleNamespace(
                        id="hv-1",
                        name="compute-1",
                        uptime="17:05:21 up 137 days, 20:28, 1 user, load average: 1.22, 1.32, 1.39",
                    )
                ]
            raise AssertionError(f"Unexpected microversion: {microversion}")

        def get(self, path, microversion=None):
            return FakeStatsResponse()

    fake_conn = SimpleNamespace(compute=FakeCompute())
    monkeypatch.setattr(
        "mcp_openstack_ops.connection.get_openstack_connection",
        lambda: fake_conn,
    )

    result = monitoring.get_hypervisor_details()

    assert result["hypervisors"][0]["uptime"] is not None
    assert result["hypervisors"][0]["load_average"] == {
        "1m": 1.22,
        "5m": 1.32,
        "15m": 1.39,
    }
