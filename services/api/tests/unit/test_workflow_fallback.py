from dataclasses import dataclass
from unittest import TestCase

from app.agents.intent import QueryIntent
from app.orchestrator.workflow import _fallback_answer_from_context


@dataclass
class FakeIntent:
    intent: QueryIntent = QueryIntent.HEALTH_CHECK
    app_ids: list[str] | None = None

    @property
    def app_id(self):
        return (self.app_ids or [None])[0]


class WorkflowFallbackAnswerTests(TestCase):
    def test_fallback_answer_summarizes_openstack_context(self):
        context = {
            "registry": {
                "servers": [
                    {"hostname": "aio", "ip": "192.168.1.111"},
                ],
            },
            "es_logs": {"index": "flog-*", "total": 413011},
            "es_log_stats": {
                "by_level": [
                    {"level": "INFO", "count": 235821},
                    {"level": "ERROR", "count": 3034},
                ],
            },
            "es_top_errors": {
                "buckets": [
                    {"payload": "AMQP server on 192.168.1.111:5672 is unreachable", "count": 179},
                ],
            },
            "server_metrics": {
                "cpu_pct": {"192.168.1.111:9100": 18.9},
                "ram_pct": {"192.168.1.111:9100": 70.0},
                "disk_pct": {"192.168.1.111:9100": 92.2},
            },
        }

        answer = _fallback_answer_from_context(context, FakeIntent(app_ids=["openstack"]))

        self.assertIn("openstack", answer)
        self.assertIn("aio (192.168.1.111)", answer)
        self.assertIn("flog-*", answer)
        self.assertIn("ERROR=3034", answer)
        self.assertIn("AMQP server", answer)
        self.assertIn("disk_pct", answer)
