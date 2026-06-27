from __future__ import annotations
import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator
import structlog

log = structlog.get_logger()

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


@dataclass
class HypothesisNode:
    id: str
    label: str
    confidence: float
    evidence: list[str]
    node_type: str = "cause"  # "cause" | "effect" | "trigger"


@dataclass
class HypothesisGraph:
    root_cause: str
    nodes: list[HypothesisNode] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    overall_confidence: float = 0.0


@dataclass
class InvestigationStep:
    step_id: int
    goal: str
    query_type: str  # "es_logs" | "prometheus" | "kibana"
    query: dict
    result: dict | None = None
    error: str | None = None


class ExpertAgent:
    """
    4-phase ROOT_CAUSE agentic loop:
    Phase 1: Plan   — LLM generates investigation steps
    Phase 2: Fetch  — Execute steps in parallel
    Phase 3: Stream — Stream answer with evidence
    Phase 4: Hypothesis — Generate causal graph
    """

    async def investigate(
        self,
        question: str,
        intent,
        context: dict,
        history: list[dict],
        session_id: str,
    ) -> AsyncGenerator[str, None]:
        from app.orchestrator.sse_emitter import (
            step_event, token_event, make_event, done_event, error_event
        )
        from app.config import settings

        start = time.monotonic()

        # ── Phase 1: Plan ────────────────────────────────────────────
        yield step_event("ExpertAgent: Đang lập kế hoạch điều tra...")

        plan = await self._generate_plan(question, context, intent)
        if not plan:
            yield error_event("expert_plan_failed", "Không thể tạo kế hoạch điều tra")
            return

        yield make_event("step", {"text": f"ExpertAgent: {len(plan)} bước điều tra", "steps": [s.goal for s in plan]})

        # ── Phase 2: Fetch ───────────────────────────────────────────
        yield step_event("ExpertAgent: Đang thu thập bằng chứng...")

        executed = await self._execute_plan(plan, intent)

        # ── Phase 3: Stream answer ───────────────────────────────────
        yield step_event("ExpertAgent: Đang phân tích và tổng hợp...")

        full_answer = ""
        async for token in self._stream_analysis(question, context, executed, intent, history):
            full_answer += token
            yield token_event(token)

        # ── Phase 4: Hypothesis graph ────────────────────────────────
        hypothesis = await self._build_hypothesis(full_answer, executed, intent)
        if hypothesis:
            yield make_event("hypothesis_graph", {
                "root_cause": hypothesis.root_cause,
                "overall_confidence": hypothesis.overall_confidence,
                "nodes": [
                    {
                        "id": n.id,
                        "label": n.label,
                        "confidence": n.confidence,
                        "evidence": n.evidence,
                        "type": n.node_type,
                    }
                    for n in hypothesis.nodes
                ],
                "edges": hypothesis.edges,
            })

        latency_ms = int((time.monotonic() - start) * 1000)
        yield done_event(
            session_id=session_id,
            intent="ROOT_CAUSE",
            latency_ms=latency_ms,
            sources_used=[s.query_type for s in executed if not s.error],
        )

    async def _generate_plan(self, question: str, context: dict, intent) -> list[InvestigationStep]:
        from app.providers import get_llm_provider
        from app.config import settings

        prompt_file = _PROMPTS_DIR / "system_expert_plan_vi.txt"
        if prompt_file.exists():
            system_prompt = prompt_file.read_text(encoding="utf-8")
        else:
            system_prompt = _DEFAULT_PLAN_PROMPT

        context_summary = json.dumps(
            {k: v for k, v in context.items() if k in ("registry", "es_logs", "es_log_stats")},
            ensure_ascii=False,
        )[:3000]

        prompt = f"""Câu hỏi cần điều tra: {question}

Context ban đầu: {context_summary}

App_id: {intent.app_id or 'unknown'}
Time range: {intent.time_range}

Tạo kế hoạch điều tra dạng JSON:
{{
  "steps": [
    {{
      "step_id": 1,
      "goal": "mục tiêu bước điều tra",
      "query_type": "es_logs|prometheus|kibana",
      "query": {{}}
    }}
  ]
}}

Tối đa {settings.expert_max_iterations} bước. Chỉ trả về JSON."""

        try:
            provider = await get_llm_provider()
            raw = await provider.generate_json(prompt, system=system_prompt, temperature=0.0)
            data = json.loads(raw)
            steps_data = data.get("steps", [])[:settings.expert_max_iterations]
            return [
                InvestigationStep(
                    step_id=s.get("step_id", i + 1),
                    goal=s.get("goal", ""),
                    query_type=s.get("query_type", "es_logs"),
                    query=s.get("query", {}),
                )
                for i, s in enumerate(steps_data)
            ]
        except Exception as e:
            log.warning("expert_plan_failed", error=str(e))
            # Fallback plan: query ES errors
            return [InvestigationStep(
                step_id=1,
                goal="Tìm lỗi gần nhất",
                query_type="es_logs",
                query={"time_range": intent.time_range, "level": "ERROR"},
            )]

    async def _execute_plan(self, plan: list[InvestigationStep], intent) -> list[InvestigationStep]:
        """Execute all steps in parallel."""
        tasks = [self._execute_step(step, intent) for step in plan]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for step, result in zip(plan, results):
            if isinstance(result, Exception):
                step.error = str(result)
            else:
                step.result = result
        return plan

    async def _execute_step(self, step: InvestigationStep, intent) -> dict:
        from app.services.config_service import ConfigService
        from app.database import get_db

        async for db in get_db():
            cfg_svc = ConfigService(db)
            cfg = await cfg_svc.get_datasource(intent.app_id or "")

            if step.query_type == "es_logs":
                from app.providers.log_storage.elasticsearch import ElasticsearchProvider
                provider = ElasticsearchProvider(
                    url=cfg.elasticsearch_url,
                    api_key=cfg.elasticsearch_api_key,
                )
                query = step.query.copy()
                body: dict = {
                    "query": {"bool": {"must": [
                        {"range": {"@timestamp": {"gte": query.get("time_range", intent.time_range)}}},
                    ]}},
                    "sort": [{"@timestamp": {"order": "desc"}}],
                }
                if query.get("level"):
                    body["query"]["bool"]["must"].append(
                        {"terms": {"log.level.keyword": [query["level"], query["level"].lower()]}}
                    )
                if query.get("keywords"):
                    body["query"]["bool"]["must"].append(
                        {"multi_match": {"query": query["keywords"], "fields": ["message", "noi_dung"]}}
                    )
                return await provider.search(cfg.app_log_index, body, size=20)

            elif step.query_type == "prometheus":
                if not cfg.prometheus_url:
                    return {"error": "Prometheus not configured"}
                from app.providers.metrics.prometheus import PrometheusProvider
                prom = PrometheusProvider(url=cfg.prometheus_url)
                q = step.query.get("query", "node_load1")
                return {"result": await prom.query_instant(q)}

            elif step.query_type == "kibana":
                if not cfg.kibana_url:
                    return {"error": "Kibana not configured"}
                from app.services.kibana_client import KibanaClient
                kb = KibanaClient(url=cfg.kibana_url, api_key=cfg.kibana_api_key)
                return {"alerts": await kb.get_active_alerts()}

            break
        return {}

    async def _stream_analysis(
        self,
        question: str,
        initial_context: dict,
        executed_steps: list[InvestigationStep],
        intent,
        history: list[dict],
    ) -> AsyncGenerator[str, None]:
        from app.providers import get_llm_provider
        from app.config import settings

        prompt_file = _PROMPTS_DIR / "system_expert_vi.txt"
        system_prompt = prompt_file.read_text(encoding="utf-8") if prompt_file.exists() else _DEFAULT_EXPERT_SYSTEM

        # Build evidence from executed steps
        evidence_parts = []
        for step in executed_steps:
            evidence_parts.append(f"=== Bước {step.step_id}: {step.goal} ===")
            if step.error:
                evidence_parts.append(f"Lỗi: {step.error}")
            elif step.result:
                result_str = json.dumps(step.result, ensure_ascii=False)[:2000]
                evidence_parts.append(result_str)

        evidence_text = "\n".join(evidence_parts)
        if len(evidence_text) > settings.llm_max_context_chars:
            evidence_text = evidence_text[:settings.llm_max_context_chars] + "\n...[truncated]"

        messages = [{"role": "system", "content": system_prompt}]
        for msg in history[-settings.llm_max_history_turns:]:
            content = msg.get("content", "")
            if msg.get("role") == "assistant" and len(content) > settings.llm_max_history_content_chars:
                content = content[:settings.llm_max_history_content_chars] + "..."
            messages.append({"role": msg["role"], "content": content})

        messages.append({"role": "user", "content": f"""Câu hỏi: {question}

Kết quả điều tra:
{evidence_text}

Hãy phân tích root cause dựa trên bằng chứng trên. Format:
\U0001f534 **Nguyên nhân gốc**: ...
\U0001f4ca **Bằng chứng**: ...
\U0001f527 **Đề xuất khắc phục**: ...
⚠️ **Mức độ ảnh hưởng**: ..."""})

        provider = await get_llm_provider()
        async for token in provider.generate_stream(messages, temperature=0.1):
            yield token

    async def _build_hypothesis(
        self,
        analysis_text: str,
        executed_steps: list[InvestigationStep],
        intent,
    ) -> HypothesisGraph | None:
        from app.config import settings
        if settings.expert_evidence_min_confidence <= 0:
            return None

        nodes = []
        edges = []

        # Extract root cause from analysis text
        root_match = re.search(r'\U0001f534[^:]*:\s*(.+?)(?:\n|$)', analysis_text)
        root_cause = root_match.group(1).strip() if root_match else "Chưa xác định được nguyên nhân gốc"

        # Build simple hypothesis graph from executed steps that had results
        for i, step in enumerate(executed_steps):
            if step.result and not step.error:
                node = HypothesisNode(
                    id=f"n{i}",
                    label=step.goal[:80],
                    confidence=0.75,
                    evidence=[f"Tìm thấy dữ liệu từ {step.query_type}"],
                    node_type="cause" if i == 0 else "effect",
                )
                nodes.append(node)
                if i > 0:
                    edges.append({"from": f"n{i-1}", "to": f"n{i}", "label": "dẫn đến"})

        return HypothesisGraph(
            root_cause=root_cause,
            nodes=nodes,
            edges=edges,
            overall_confidence=0.7 if nodes else 0.4,
        )


_DEFAULT_PLAN_PROMPT = """Bạn là chuyên gia phân tích sự cố hệ thống IT.
Dựa trên câu hỏi và context ban đầu, tạo kế hoạch điều tra có cấu trúc.
Mỗi bước phải rõ mục tiêu và loại query cần thực hiện."""

_DEFAULT_EXPERT_SYSTEM = """Bạn là chuyên gia phân tích sự cố (Root Cause Analysis) cho hệ thống IT của VST.
Phân tích bằng chứng được cung cấp và đưa ra:
1. Nguyên nhân gốc chính xác nhất (kèm bằng chứng cụ thể)
2. Chuỗi nguyên nhân → kết quả
3. Đề xuất khắc phục ưu tiên cao nhất
4. Mức độ ảnh hưởng lên dịch vụ

KHÔNG suy đoán khi không có bằng chứng. Nói rõ "Không đủ dữ liệu để kết luận" nếu cần."""
