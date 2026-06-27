from unittest import IsolatedAsyncioTestCase

from app.providers.log_storage.elasticsearch import ElasticsearchProvider


class FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, head_status: int = 404, wildcard_status: int = 200, wildcard_payload=None):
        self.head_status = head_status
        self.wildcard_status = wildcard_status
        self.wildcard_payload = wildcard_payload if wildcard_payload is not None else [{"index": "flog-2026.06.27"}]
        self.calls = []

    async def head(self, url, headers=None):
        self.calls.append(("HEAD", url, headers, None))
        return FakeResponse(self.head_status)

    async def get(self, url, headers=None, params=None):
        self.calls.append(("GET", url, headers, params))
        return FakeResponse(self.wildcard_status, self.wildcard_payload)


class ElasticsearchProviderIndexResolveTests(IsolatedAsyncioTestCase):
    async def test_resolve_index_keeps_existing_literal_index(self):
        provider = ElasticsearchProvider("http://es.local/")
        client = FakeClient(head_status=200)

        resolved = await provider._resolve_index(client, "flog")

        self.assertEqual(resolved, "flog")
        self.assertEqual(client.calls[0][0], "HEAD")

    async def test_resolve_index_falls_back_to_dash_wildcard(self):
        provider = ElasticsearchProvider("http://es.local/")
        client = FakeClient(head_status=404, wildcard_payload=[{"index": "flog-2026.06.27"}])

        resolved = await provider._resolve_index(client, "flog")

        self.assertEqual(resolved, "flog-*")
        self.assertEqual(client.calls[1][0], "GET")
        self.assertIn("_cat/indices/flog-*", client.calls[1][1])

    async def test_resolve_index_keeps_index_when_no_wildcard_match(self):
        provider = ElasticsearchProvider("http://es.local/")
        client = FakeClient(head_status=404, wildcard_payload=[])

        resolved = await provider._resolve_index(client, "missing")

        self.assertEqual(resolved, "missing")

    async def test_resolve_index_does_not_probe_existing_wildcard(self):
        provider = ElasticsearchProvider("http://es.local/")
        client = FakeClient()

        resolved = await provider._resolve_index(client, "flog-*")

        self.assertEqual(resolved, "flog-*")
        self.assertEqual(client.calls, [])
