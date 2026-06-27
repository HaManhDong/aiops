from unittest import TestCase

from app.agents.query_executor import QueryExecutor


class QueryExecutorMetricMappingTests(TestCase):
    def test_find_metric_for_server_matches_ip_with_exporter_port(self):
        server = {"ip": "192.168.1.111", "hostname": "aio"}
        values = {
            "192.168.1.111:9100": 18.5,
            "10.0.0.8:9100": 44.0,
        }

        self.assertEqual(QueryExecutor._find_metric_for_server(values, server), 18.5)

    def test_find_metric_for_server_matches_hostname(self):
        server = {"ip": "10.20.30.40", "hostname": "control"}
        values = {
            "control:9100": 72.1,
            "worker-1:9100": 31.2,
        }

        self.assertEqual(QueryExecutor._find_metric_for_server(values, server), 72.1)

    def test_find_metric_for_server_returns_none_when_no_match(self):
        server = {"ip": "192.168.1.111", "hostname": "aio"}
        values = {"10.0.0.8:9100": 44.0}

        self.assertIsNone(QueryExecutor._find_metric_for_server(values, server))

    def test_attach_server_metrics_enriches_registry_rows(self):
        executor = QueryExecutor(config_svc=None, db=None)
        context = {
            "registry": {
                "servers": [
                    {"hostname": "aio", "ip": "192.168.1.111"},
                    {"hostname": "worker", "ip": "10.0.0.8"},
                ],
            },
            "server_metrics": {
                "cpu_pct": {"192.168.1.111:9100": 18.9, "10.0.0.8:9100": 44.2},
                "ram_pct": {"192.168.1.111:9100": 70.0, "10.0.0.8:9100": 55.5},
                "disk_pct": {"192.168.1.111:9100": 92.2},
            },
        }

        executor._attach_server_metrics(context)

        first, second = context["registry"]["servers"]
        self.assertEqual(first["cpu_pct"], 18.9)
        self.assertEqual(first["ram_pct"], 70.0)
        self.assertEqual(first["disk_pct"], 92.2)
        self.assertEqual(second["cpu_pct"], 44.2)
        self.assertEqual(second["ram_pct"], 55.5)
        self.assertIsNone(second["disk_pct"])
