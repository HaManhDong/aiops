from __future__ import annotations

from app.providers.log_storage.elasticsearch import ElasticsearchProvider


class OpenSearchProvider(ElasticsearchProvider):
    """OpenSearch uses same API as Elasticsearch."""
    pass
