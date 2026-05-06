import pytest
from discord_app.services.transmission import TransmissionClient


class TestTransmissionHumanStatus:
    @pytest.mark.parametrize(
        "status_code,expected",
        [
            (0, "stopped"),
            (1, "check_wait"),
            (2, "check"),
            (3, "download"),
            (4, "seed"),
            (5, "isolated"),
            (6, "stalled"),
            (99, "unknown"),
        ],
    )
    def test_status_mapping(self, status_code, expected):
        assert TransmissionClient.human_status({"status": status_code}) == expected

    def test_handles_missing_status(self):
        assert TransmissionClient.human_status({}) == "unknown"


class TestTransmissionClient:
    def test_client_init(self):
        client = TransmissionClient("http://localhost:9091/transmission/rpc")
        assert client.url == "http://localhost:9091/transmission/rpc"

    def test_client_with_auth(self):
        client = TransmissionClient(
            "http://localhost:9091/transmission/rpc",
            user="testuser",
            password="testpass",
        )
        assert client.user == "testuser"
        assert client.password == "testpass"