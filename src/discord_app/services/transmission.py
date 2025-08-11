import httpx


class TransmissionClient:
    def __init__(self, url: str, user: str | None = None, password: str | None = None):
        self.url = url.rstrip("/")
        self.user = user
        self.password = password
        self._sid = None
        self._client = httpx.AsyncClient(
            timeout=10.0, auth=(user, password) if user and password else None
        )

    async def _rpc(self, method: str, arguments: dict | None = None):
        headers = {}
        if self._sid:
            headers["X-Transmission-Session-Id"] = self._sid
        body = {"method": method, "arguments": arguments or {}}
        r = await self._client.post(self.url, headers=headers, json=body)
        if r.status_code == 409:
            self._sid = r.headers.get("X-Transmission-Session-Id")
            r = await self._client.post(
                self.url, headers={"X-Transmission-Session-Id": self._sid}, json=body
            )
        r.raise_for_status()
        return r.json()

    async def get_by_hash(self, info_hash: str) -> dict | None:
        data = await self._rpc(
            "torrent-get",
            {
                "ids": [info_hash],
                "fields": [
                    "id",
                    "name",
                    "status",
                    "percentDone",
                    "rateDownload",
                    "eta",
                ],
            },
        )
        torrents = data.get("arguments", {}).get("torrents", [])
        return torrents[0] if torrents else None

    @staticmethod
    def human_status(t: dict) -> str:
        # Transmission status mapping
        mapping = {
            0: "stopped",
            1: "check_wait",
            2: "check",
            3: "download",
            4: "seed",
            5: "isolated",
            6: "stalled",
        }
        return mapping.get(t.get("status"), "unknown")
