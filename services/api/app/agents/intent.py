from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

import structlog

log = structlog.get_logger()

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# Keyword mapping cho app_id detection
_SYSTEM_KW: list[tuple[str, list[str]]] = [
    ("erp", ["erp", "sap"]),
    ("openstack", ["openstack", "nova", "neutron", "cinder", "glance", "keystone"]),
    ("website", ["mvs", "website"]),
]
_FOLLOWUP_MARKERS = {"đó", "nó", "còn", "tiếp", "vẫn", "thêm", "nữa", "lại", "cũng"}
_GREETING_RE = re.compile(r"^(xin chào|hello|hi|chào|hey|good morning|good afternoon|alo)", re.I)
_WHOIS_RE = re.compile(r"(bạn là ai|who are you|giới thiệu|you are)", re.I)


class QueryIntent(str, Enum):
    HEALTH_CHECK = "HEALTH_CHECK"
    ERROR_LOOKUP = "ERROR_LOOKUP"
    METRIC_QUERY = "METRIC_QUERY"
    ALERT_STATUS = "ALERT_STATUS"
    ROOT_CAUSE = "ROOT_CAUSE"
    TREND_ANALYSIS = "TREND_ANALYSIS"
    SERVER_QUERY = "SERVER_QUERY"
    INCIDENT_ANALYSIS = "INCIDENT_ANALYSIS"
    HTTP_ANALYSIS = "HTTP_ANALYSIS"
    PASTE_ALERT = "PASTE_ALERT"
    CAPACITY_PLANNING = "CAPACITY_PLANNING"
    LOG_ANOMALY = "LOG_ANOMALY"
    SECURITY_AUDIT = "SECURITY_AUDIT"
    ALERT_MANAGEMENT = "ALERT_MANAGEMENT"
    VERIFY_FIX = "VERIFY_FIX"
    CLARIFICATION = "CLARIFICATION"
    THREAT_MODEL = "THREAT_MODEL"


@dataclass
class ClassifiedIntent:
    intent: QueryIntent
    app_ids: list[str]
    time_range: str = "now-24h"
    keywords: list[str] = field(default_factory=list)
    incident_time: str | None = None
    window_minutes: int = 60
    urgency: bool = False
    is_relevant: bool = True
    is_repeat: bool = False

    @property
    def app_id(self) -> str | None:
        return self.app_ids[0] if self.app_ids else None


def _detect_app_ids_from_text(text: str) -> list[str]:
    lower = text.lower()
    found = []
    for app_id, keywords in _SYSTEM_KW:
        if any(kw in lower for kw in keywords):
            found.append(app_id)
    return found


def _load_intent_prompt() -> str:
    p = _PROMPTS_DIR / "intent_classify.txt"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return _DEFAULT_INTENT_PROMPT


_DEFAULT_INTENT_PROMPT = """Phân tích câu hỏi về hệ thống IT và trả về JSON:
{{
  "intent": "<HEALTH_CHECK|ERROR_LOOKUP|METRIC_QUERY|ALERT_STATUS|ROOT_CAUSE|TREND_ANALYSIS|SERVER_QUERY|INCIDENT_ANALYSIS|HTTP_ANALYSIS|PASTE_ALERT|CAPACITY_PLANNING|LOG_ANOMALY|SECURITY_AUDIT|ALERT_MANAGEMENT|VERIFY_FIX|CLARIFICATION|THREAT_MODEL>",
  "app_ids": ["erp"|"openstack"|"website"],
  "time_range": "now-1h|now-6h|now-24h|now-7d",
  "keywords": ["từ khóa kỹ thuật"],
  "urgency": false,
  "is_relevant": true
}}

Ngày hiện tại: {current_date}

Câu hỏi: {question}

Chỉ trả về JSON, không giải thích."""


class IntentClassifier:
    async def classify(
        self,
        question: str,
        history: list[dict] | None = None,
        effective_app_id: str | None = None,
    ) -> ClassifiedIntent:
        """
        Classify intent. Ưu tiên:
        1. JWT-forced app_id (effective_app_id)
        2. Keyword scan trong câu hỏi
        3. LLM classification
        """
        from app.providers import get_llm_provider

        template = _load_intent_prompt()
        current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # History context prefix
        history_prefix = ""
        if history:
            recent = history[-5:]
            history_prefix = "[Lịch sử gần đây]\n" + "\n".join(
                f"- {m['role']}: {m['content'][:200]}" for m in recent
            ) + "\n\n"

        prompt = history_prefix + template.format(
            current_date=current_date, question=question
        )

        try:
            provider = await get_llm_provider()
            raw = await provider.generate_json(prompt, temperature=0.0)
            data = json.loads(raw)
        except Exception as e:
            log.warning("intent_classify_failed", error=str(e))
            data = {}

        # Parse intent
        intent_str = data.get("intent", "HEALTH_CHECK")
        try:
            intent = QueryIntent(intent_str)
        except ValueError:
            intent = QueryIntent.HEALTH_CHECK

        # App IDs — 2-layer resolution
        if effective_app_id:
            app_ids = [effective_app_id]
        else:
            keyword_app_ids = _detect_app_ids_from_text(question)
            if keyword_app_ids:
                app_ids = keyword_app_ids
            else:
                llm_app_ids = data.get("app_ids") or []
                is_followup = any(w in question.lower().split() for w in _FOLLOWUP_MARKERS)
                app_ids = llm_app_ids if is_followup else []

        return ClassifiedIntent(
            intent=intent,
            app_ids=app_ids,
            time_range=data.get("time_range", "now-24h"),
            keywords=data.get("keywords") or [],
            urgency=bool(data.get("urgency")),
            is_relevant=bool(data.get("is_relevant", True)),
        )


def is_greeting(message: str) -> bool:
    return bool(_GREETING_RE.search(message.strip()))


def is_whois(message: str) -> bool:
    return bool(_WHOIS_RE.search(message))
