# Repository Improvement Plan

## Goal

Transform this repository from an internal engineering project into a flagship open-source AI systems repository that can be understood, trusted, and evaluated quickly by international judges, maintainers, operators, and technical investors.

The codebase already contains meaningful backend implementation. The missing layer is the open-source product shell: documentation, reproducibility, demo assets, benchmarks, security posture, contribution workflow, and evidence.

## Documentation Roadmap

| Document | Purpose | Target Audience | Table of Contents | Important Diagrams | Key Messages | Estimated Length |
|---|---|---|---|---|---|---:|
| `README.md` | First five-minute judge entry point. Explain what this is, why it matters, what is implemented, and how to run it. | Judges, new users, maintainers, investors | Pitch, problem, demo, implemented status, architecture, quick start, examples, docs map, benchmarks, limitations, roadmap, license | System architecture, AI pipeline | This is an on-prem language-agnostic AIOps platform, not a generic chatbot. It has real integrations and a credible architecture. | 1500-2500 words |
| `docs/architecture/overview.md` | Explain the whole system at technical depth. | Architects, senior engineers, reviewers | Goals, non-goals, layers, services, data stores, provider model, chat pipeline, prediction pipeline, worker, deployment modes | System architecture, component diagram, deployment diagram, data flow | The design is modular, provider-driven, async, and production-oriented. | 3000-5000 words |
| `docs/architecture/ai-pipeline.md` | Explain exactly how AI is used and where grounding happens. | AI judges, LLM evaluators, ML engineers | Intent classification, fast paths, query execution, context shaping, synthesis, ExpertAgent, prompts, hallucination controls, eval plan | AI agent workflow, sequence diagram, prompt/context flow | AI adds routing, planning, synthesis, and operational memory; it is grounded in runtime evidence. | 2500-4000 words |
| `docs/architecture/data-flow.md` | Show how data moves through MariaDB, Redis, ES, Prometheus, Kibana, and LLM providers. | Backend engineers, SREs | Data sources, config cache, conversation state, query cache, incidents, prediction alerts, worker offsets | Data flow, storage layout | Operational data stays local; metadata is structured and cache-aware. | 2000-3500 words |
| `docs/architecture/prediction-engine.md` | Explain prediction design and signal groups. | SREs, ML/AI reviewers, operators | Scheduler, quality gate, baselines, novelty, recurrence, composite, suppression, alert lifecycle, evaluation | Scheduling workflow, prediction workflow, alert state flow | Prediction is multi-signal and evidence-backed, not just static thresholds. | 2500-4500 words |
| `docs/architecture/worker.md` | Explain TXT log collector behavior. | Operators, backend engineers | Watch dirs, parsing, offset tracking, rotation detection, bulk indexing, error classification, scaling | Worker workflow, storage layout, failure recovery flow | Legacy log files can be ingested without replacing existing infrastructure. | 1500-2500 words |
| `docs/design/design-philosophy.md` | State design principles and tradeoffs. | Maintainers, architects, judges | On-prem first, evidence over hallucination, config as data, provider abstraction, graceful degradation, language-agnostic UX, async everywhere | Principle map | This project has a coherent engineering philosophy. | 1500-2500 words |
| `docs/concepts/core-concepts.md` | Define domain concepts. | New contributors, users | App ID, datasource, server registry, conversation context, intent, provider, incident, topology, prediction alert, worker state | Concept map | Readers can understand the vocabulary before reading code. | 1500-2500 words |
| `docs/getting-started/quick-start.md` | Reproducible local path from clone to first API call. | Judges, developers | Prereqs, env setup, compose up, health check, login, create datasource, chat call, troubleshooting | Quick start flow | A reviewer can run the project without guessing. | 1200-2000 words |
| `docs/getting-started/installation.md` | Installation variants. | Operators, contributors | Docker Compose, manual Python, LLM setup, DB setup, Redis setup, worker startup | Installation matrix | The project can be installed in multiple environments. | 2000-3500 words |
| `docs/getting-started/configuration.md` | Explain all config surfaces. | Operators, admins | `.env`, Pydantic settings, datasource configs, credentials, thresholds, provider selection, Redis cache behavior | Config lifecycle | Runtime configuration is data-driven and secure by design. | 2500-4000 words |
| `docs/usage/chat.md` | Show operator-facing chat usage. | Operators, demo reviewers | Common questions, SSE events, session handling, server input flow, root cause flow, limitations | Chat request sequence, chat state machine | The chat interface is operational, stateful, and evidence-grounded. | 1800-3000 words |
| `docs/usage/incidents.md` | Explain incident workflows. | Operators, managers | Create/update incident, timeline, similar incidents, chat drafts, prediction source | Incident lifecycle | Incident memory turns one-off troubleshooting into reusable knowledge. | 1500-2500 words |
| `docs/usage/topology.md` | Explain topology graph APIs. | SREs, architects | Versions, nodes, edges, graph expansion, blast radius, LLM parsing | Topology component graph, blast-radius flow | Topology helps root-cause and impact analysis. | 1500-2500 words |
| `docs/developer-guide.md` | Contributor engineering guide. | Developers, maintainers | Repo layout, local setup, coding standards, async rules, adding routes, adding providers, adding prediction extractors, testing | Development workflow | Contributors can make changes safely and consistently. | 3000-5000 words |
| `docs/api-reference.md` | Human-readable API reference. | API consumers, frontend developers | Auth, health, chat, users, servers, config, incidents, topology, predictions, errors | Request lifecycle | API contracts are discoverable without reading source. | 4000-7000 words |
| `docs/examples.md` | Concrete examples and recipes. | Judges, developers, operators | Login, create datasource, add server, chat, create incident, topology import, trigger scan, worker run | Example flow | The project is usable, not just architectural. | 2000-3500 words |
| `docs/deployment/dev.md` | Dev deployment guide. | Developers, judges | Compose services, ports, env, startup, logs, reset, troubleshooting | Dev deployment diagram | Local demo can be reproduced reliably. | 1500-2500 words |
| `docs/deployment/production.md` | Production deployment reference. | Platform teams, SREs | API replicas, scheduler strategy, MariaDB, Redis Sentinel, LLM, ES/Prom/Kibana, secrets, backups, upgrades | Production deployment diagram, failure recovery flow | The architecture can become production-grade with clear operational controls. | 3000-5000 words |
| `docs/benchmarks/plan.md` | Benchmark methodology. | Judges, performance engineers | Goals, datasets, hardware, metrics, scripts, reporting format | Benchmark matrix | Performance claims are measured and reproducible. | 2000-3500 words |
| `docs/benchmarks/results.md` | Actual benchmark results. | Judges, maintainers | Environment, latency, throughput, scalability, recovery, cost, analysis | Charts | Evidence supports the project claims. | 1500-3000 words |
| `docs/performance.md` | Explain expected performance behavior. | SREs, backend engineers | Hot paths, bottlenecks, caching, LLM latency, DB pools, ES query cost, SSE behavior | Request latency budget | Performance is understood and tunable. | 2000-3500 words |
| `docs/scalability.md` | Explain scale model. | Architects, SREs | Stateless API, Redis state, DB pooling, scheduler locks, worker sharding, ES query limits, multi-app isolation | Scalability model | Scaling is designed around stateless APIs and externalized state. | 2000-3500 words |
| `docs/security.md` | Security model and practices. | Security reviewers, operators | Threat model, auth, RBAC, secrets, encryption, network isolation, logs, dependency scanning, disclosure | Threat model, auth flow | On-prem does not mean insecure; the project has an explicit security posture. | 2500-4500 words |
| `docs/observability.md` | Explain how to observe the platform itself. | SREs, operators | Logs, metrics, traces, request IDs, health checks, dashboards, alerting, runbooks | Observability flow | The AIOps platform should itself be operable. | 2000-3500 words |
| `docs/roadmap.md` | Public roadmap. | Users, contributors, judges | Current status, P0/P1/P2, milestones, non-goals, release targets | Roadmap timeline | The project has direction and honest scope control. | 1200-2000 words |
| `docs/known-limitations.md` | Build trust through honesty. | Judges, users, maintainers | Missing frontend, tests, CI, benchmarks, production deploy, migrations, known risks | None required | The repo distinguishes implemented from planned work. | 800-1500 words |
| `docs/future-work.md` | Research and advanced roadmap. | AI reviewers, researchers | Better evals, causal learning, topology learning, multi-agent plans, UI, OpenTelemetry, Kubernetes | Future architecture | The idea has a credible growth path. | 1200-2500 words |
| `CONTRIBUTING.md` | Contribution workflow. | External contributors | Setup, branch flow, code style, tests, docs, PR checklist, issue labels | Contribution workflow | The project welcomes contributors professionally. | 1200-2000 words |
| `LICENSE` | Legal permission to use/modify/distribute. | Everyone | Standard license text | None | Without this, the repo is not open-source. | Standard |
| `docs/faq.md` | Answer predictable questions. | Judges, users, operators | Why on-prem? Why language-agnostic? Is there frontend? Which LLMs? Can I use OpenAI? What data leaves network? | None | Reduce uncertainty and reviewer friction. | 1000-2000 words |
| `docs/glossary.md` | Define terminology. | Everyone | AIOps, app_id, datasource, SSE, ExpertAgent, prediction alert, topology, provider, baseline | None | Shared vocabulary makes docs easier to navigate. | 1000-2000 words |

## Documentation Tree

```text
.
├── README.md
├── LICENSE
├── CONTRIBUTING.md
├── SECURITY.md
├── CODE_OF_CONDUCT.md
├── CHANGELOG.md
├── docs/
│   ├── index.md
│   ├── architecture/
│   │   ├── overview.md
│   │   ├── ai-pipeline.md
│   │   ├── data-flow.md
│   │   ├── prediction-engine.md
│   │   ├── worker.md
│   │   └── diagrams.md
│   ├── concepts/
│   │   └── core-concepts.md
│   ├── design/
│   │   └── design-philosophy.md
│   ├── getting-started/
│   │   ├── quick-start.md
│   │   ├── installation.md
│   │   └── configuration.md
│   ├── usage/
│   │   ├── chat.md
│   │   ├── incidents.md
│   │   ├── topology.md
│   │   └── predictions.md
│   ├── deployment/
│   │   ├── dev.md
│   │   └── production.md
│   ├── benchmarks/
│   │   ├── plan.md
│   │   ├── results.md
│   │   └── datasets.md
│   ├── api-reference.md
│   ├── developer-guide.md
│   ├── examples.md
│   ├── performance.md
│   ├── scalability.md
│   ├── security.md
│   ├── observability.md
│   ├── roadmap.md
│   ├── known-limitations.md
│   ├── future-work.md
│   ├── faq.md
│   ├── glossary.md
│   ├── images/
│   └── adr/
├── examples/
│   ├── curl/
│   ├── sample-logs/
│   ├── sample-topology/
│   └── sample-datasources/
├── demo/
│   ├── README.md
│   ├── script.md
│   ├── screenshots/
│   ├── gifs/
│   └── transcripts/
├── benchmark/
│   ├── README.md
│   ├── intent-eval/
│   ├── load/
│   ├── ingestion/
│   └── failure-injection/
├── scripts/
│   ├── dev-up.sh
│   ├── seed-demo-data.sh
│   ├── run-chat-demo.sh
│   └── run-benchmarks.sh
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
└── .github/
    ├── workflows/
    │   ├── ci.yml
    │   ├── docs.yml
    │   └── security.yml
    ├── ISSUE_TEMPLATE/
    └── pull_request_template.md
```

## Diagram Checklist

| Diagram | Purpose | Format | Target Location | Priority |
|---|---|---|---|---|
| System Architecture | Show the whole platform in one view. | Mermaid + PNG export | `README.md`, `docs/architecture/overview.md` | P0 |
| Component Diagram | Show API modules, worker, providers, services, DB/cache. | Mermaid | `docs/architecture/overview.md` | P0 |
| Deployment Diagram | Show dev and production topology. | Mermaid | `docs/deployment/dev.md`, `docs/deployment/production.md` | P0 |
| Chat Sequence Diagram | Show `/api/v1/chat` lifecycle. | Mermaid sequence | `README.md`, `docs/architecture/ai-pipeline.md` | P0 |
| AI Agent Workflow | Show fast path, classify, query, synthesize, persist. | Mermaid flowchart | `docs/architecture/ai-pipeline.md` | P0 |
| Data Flow Diagram | Show MariaDB, Redis, ES, Prometheus, Kibana, LLM movement. | Mermaid | `docs/architecture/data-flow.md` | P0 |
| Chat State Machine | Show `NORMAL`, `WAITING_SERVER_INPUT`, `CONFIRMING_SERVER`. | Mermaid state diagram | `docs/usage/chat.md` | P1 |
| Prediction Scheduling Workflow | Show scheduler, scan, quality gate, extractors, alert writer. | Mermaid flowchart | `docs/architecture/prediction-engine.md` | P1 |
| Prediction Alert Lifecycle | Show open, acknowledged, resolved, suppressed. | Mermaid state diagram | `docs/usage/predictions.md` | P1 |
| Worker Ingestion Workflow | Show watch dirs, parse, classify, bulk index, state update. | Mermaid flowchart | `docs/architecture/worker.md` | P1 |
| Storage Layout | Show core tables and relationships. | ERD/Mermaid | `docs/architecture/data-flow.md` | P1 |
| Auth/RBAC Flow | Show login, JWT, app permissions, route guard. | Mermaid sequence | `docs/security.md` | P1 |
| Failure Recovery Flow | Show ES/Prometheus/Redis/LLM degraded modes. | Mermaid flowchart | `docs/deployment/production.md` | P1 |
| Provider Abstraction Diagram | Show LLM/log/metrics provider interfaces and implementations. | Mermaid class/component | `docs/developer-guide.md` | P2 |
| Benchmark Pipeline | Show benchmark runner, target services, outputs. | Mermaid flowchart | `docs/benchmarks/plan.md` | P2 |

## Benchmark Checklist

### Latency

| Benchmark | Metric | Method | Required Evidence |
|---|---|---|---|
| Health endpoint latency | p50/p95/p99 | Run 1k requests against `/health`. | Table and command. |
| Readiness latency | p50/p95/p99 | Run with DB/Redis healthy and degraded. | Table and failure notes. |
| Chat first-token latency | p50/p95/p99 | Send fixed health-check prompts with ES/Prom enabled. | SSE transcript and chart. |
| Full chat completion latency | p50/p95/p99 | Measure from request start to `done` event. | Table by LLM provider. |
| ES query latency | p50/p95 | Query 1h/24h/7d windows with fixed log volume. | Result table. |
| Prediction scan latency | seconds/app | Scan 10, 50, 100 servers. | Chart. |

### Throughput

| Benchmark | Metric | Method | Required Evidence |
|---|---|---|---|
| Concurrent SSE chat | successful streams/min | 10, 25, 50 concurrent users. | Completion rate and error rate. |
| API CRUD throughput | requests/sec | Users, servers, incidents, topology CRUD. | Table. |
| Worker ingestion | records/sec and MB/sec | Index sample TXT logs of 100MB, 1GB, 10GB. | Table and ES bulk error rate. |
| Prediction alert writes | alerts/sec | Synthetic signals. | Table. |

### Scalability

| Benchmark | Metric | Method | Required Evidence |
|---|---|---|---|
| Multi-app scaling | scan duration/app | 1, 5, 20 app_ids. | Chart. |
| Server registry scale | query time | 100, 1k, 10k servers. | Table. |
| Redis cache impact | latency reduction | Compare cold vs warm query cache. | Chart. |
| DB pool behavior | saturation point | Concurrent API requests with DB access. | Table. |

### Recovery

| Scenario | Expected Behavior | Required Evidence |
|---|---|---|
| Elasticsearch down | Chat returns degraded answer, not API crash. | Transcript. |
| Prometheus down | Metrics unavailable message, logs still queried. | Transcript. |
| Redis down | DB fallback for session where possible; clear error otherwise. | Logs. |
| LLM timeout | SSE error event and `done` event. | Transcript. |
| MariaDB unavailable | `/ready` degraded, API health still alive. | Health output. |
| Worker file rotation | Offset resets safely and avoids duplicate explosion. | Worker logs. |

### Failure Injection

- Kill Redis during active chat.
- Stop Elasticsearch during query.
- Return invalid LLM JSON from mock provider.
- Simulate slow Prometheus response.
- Rotate log file mid-ingestion.
- Insert malformed datasource config.
- Create duplicate scheduler scenario and verify mitigation plan.

### Resource Usage

| Resource | Metric | Method |
|---|---|---|
| API CPU/RAM | CPU %, RSS | Run chat load test. |
| Worker CPU/RAM | CPU %, RSS | Run ingestion benchmark. |
| MariaDB | connections, query latency | Run CRUD and chat persistence tests. |
| Redis | ops/sec, memory | Run session/cache tests. |
| LLM | tokens/sec, VRAM/RAM | Compare Ollama/vLLM/OpenAI-compatible providers. |

### AI Inference Cost

| Metric | Method |
|---|---|
| Tokens per intent classification | Log prompt/completion token counts if provider supports it. |
| Tokens per synthesis | Measure context size and streamed completion. |
| Cost per chat | Estimate from local GPU time or external provider pricing. |
| Cache savings | Compare repeated queries with and without cached ES results. |
| Quality vs latency | Compare small/local model vs larger model on intent eval set. |

## Demo Checklist

### GIF Demo

- 45-60 seconds.
- Show terminal or UI opening.
- Health check passes.
- Login succeeds.
- Chat question in any supported natural language streams an answer.
- ES query/log stats event visible.
- Incident draft or prediction alert visible.

### Video Demo

- 3-5 minutes.
- Start with problem statement.
- Show architecture diagram.
- Run local stack.
- Ask "ERP hôm nay có lỗi nghiêm trọng không?"
- Show how datasource/server registry grounds the answer.
- Trigger prediction scan.
- Show incident/topology endpoint.
- End with roadmap and known limitations.

### Screenshots

- README architecture diagram.
- Swagger API docs.
- Login API response.
- SSE chat transcript.
- Datasource admin API.
- Server registry API.
- Incident timeline API.
- Topology graph JSON or rendered diagram.
- Prediction alerts response.
- Worker ingestion logs.

### CLI Demo

- `scripts/dev-up.sh`
- `scripts/seed-demo-data.sh`
- `scripts/run-chat-demo.sh`
- `scripts/run-prediction-demo.sh`
- `scripts/run-worker-demo.sh`

### Dashboard Demo

If frontend remains missing, do not imply a dashboard exists. Use Swagger, terminal transcripts, Mermaid diagrams, and API examples instead.

If frontend is later added:

- Chat page.
- Incident page.
- Topology graph.
- Prediction alert list.
- Admin datasource page.

### Logs Demo

- Include sample log files under `examples/sample-logs/`.
- Include expected parsed records.
- Include expected ES bulk payload sample.
- Include worker output transcript.

### Failure Simulation Demo

- ES unavailable.
- Prometheus unavailable.
- Invalid LLM JSON.
- Redis unavailable.
- Log file rotation.
- Duplicate server input flow.

## Repository Structure

### Current Strength

The current code layout is already service-oriented:

- `services/api/app`
- `services/worker/app`
- `infra`
- `docs`
- `docs/04_adr`

### Proposed World-Class Structure

```text
.
├── README.md
├── LICENSE
├── CONTRIBUTING.md
├── SECURITY.md
├── CODE_OF_CONDUCT.md
├── CHANGELOG.md
├── .env.example
├── infra/
│   ├── docker-compose.dev.yml
│   ├── docker-compose.prod.yml
│   ├── init-db/
│   └── nginx/
├── services/
│   ├── api/
│   └── worker/
├── docs/
│   ├── index.md
│   ├── architecture/
│   ├── concepts/
│   ├── design/
│   ├── getting-started/
│   ├── usage/
│   ├── deployment/
│   ├── benchmarks/
│   ├── images/
│   └── adr/
├── examples/
│   ├── curl/
│   ├── sample-logs/
│   ├── sample-topology/
│   └── sample-datasources/
├── demo/
│   ├── README.md
│   ├── script.md
│   ├── screenshots/
│   ├── gifs/
│   └── transcripts/
├── benchmark/
│   ├── README.md
│   ├── intent-eval/
│   ├── load/
│   ├── ingestion/
│   └── failure-injection/
├── scripts/
├── tests/
└── .github/
```

## Improved README Outline

```markdown
# AIOps

One-line pitch:
Language-agnostic on-premise AIOps assistant that turns natural-language operations questions into evidence-grounded log, metric, incident, topology, and prediction workflows.

## Demo
- GIF
- 3-minute video
- One command quick start

## Why This Exists
- Operators waste time across Kibana, Grafana, SSH, and incident tickets.
- Existing tools often require query languages, rigid dashboard filters, and senior SRE skill.
- Sensitive logs cannot leave the internal network.

## What It Does
- Chat with observability data in natural language
- Query Elasticsearch/OpenSearch
- Query Prometheus/Metricbeat
- Stream answers over SSE
- Manage incidents and timeline
- Model topology and blast radius
- Detect prediction signals
- Ingest TXT logs

## Implemented vs Planned
Honest status table.

## Architecture
Mermaid system diagram.

## AI Pipeline
Mermaid sequence diagram.

## Quick Start
Clone, env, compose, health, login, chat.

## Example Output
SSE transcript.

## Documentation
Link map.

## Benchmarks
Summary table and reproduction link.

## Security
On-prem model, JWT, AES-GCM, app permissions.

## Known Limitations
Honest constraints.

## Roadmap
P0/P1/P2.

## Contributing
Link to CONTRIBUTING.

## License
```

## Execution Priority

### P0 — Must Finish Before Public Submission

1. Add `LICENSE`.
2. Add full `README.md` with demo, architecture, quick start, implemented/planned status.
3. Add `docs/known-limitations.md`.
4. Add `docs/getting-started/quick-start.md`.
5. Add `docs/architecture/overview.md`.
6. Add `docs/architecture/ai-pipeline.md`.
7. Add `demo/script.md` and terminal transcripts.
8. Add sample logs and sample curl examples.
9. Add minimal tests and CI workflow.
10. Align existing docs with current implementation and clearly label planned features.

### P1 — Strongly Recommended

1. Add benchmark plan and first baseline results.
2. Add deployment docs for dev and production.
3. Add security and observability docs.
4. Add diagrams for chat, prediction, worker, auth, and data flow.
5. Add CONTRIBUTING, SECURITY, CODE_OF_CONDUCT, and PR templates.
6. Add initial Alembic migration.
7. Add worker to dev compose or document separate startup.
8. Add failure injection demo.

### P2 — Nice To Have

1. Add full frontend or remove all frontend claims from public-facing docs.
2. Add comparison against Kibana/Grafana-only workflows and commercial AIOps.
3. Add research references.
4. Add public roadmap board.
5. Add release versioning and changelog automation.
6. Add docs site using MkDocs, Docusaurus, or VitePress.

## Final Standard

The repository should let a judge answer these questions in under five minutes:

- What problem does this solve?
- Why is it technically impressive?
- What is actually implemented?
- How do I run it?
- Where is the demo?
- What evidence supports the claims?
- What are the limitations?
- How would this become production-grade?

If those answers are not visible from the README and linked docs, the repository is not ready for an international AI competition.
