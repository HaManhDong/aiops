from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import CurrentUser, get_current_user, require_admin
from app.models.topology import TopologyEdge, TopologyNode, TopologyVersion
from app.services.audit import audit_log
from app.services.topology_service import GraphEdge, GraphNode, TopologyService

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/topology", tags=["topology"])


# ── Schemas ──────────────────────────────────────────────────────────


class NodeCreate(BaseModel):
    node_key: str
    label: str
    node_type: Literal[
        "service", "database", "queue", "server", "external", "loadbalancer"
    ] = "service"
    ip: str | None = None
    hostname: str | None = None
    position_x: float = 0.0
    position_y: float = 0.0
    metadata: dict | None = None


class NodeUpdate(BaseModel):
    label: str | None = None
    node_type: str | None = None
    ip: str | None = None
    hostname: str | None = None
    position_x: float | None = None
    position_y: float | None = None
    metadata: dict | None = None
    health_status: str | None = None


class EdgeCreate(BaseModel):
    source_node_key: str
    target_node_key: str
    relation_type: Literal[
        "calls", "depends_on", "replicates", "proxies", "feeds", "monitors"
    ] = "calls"
    propagation_prob: float = 0.5
    weight: float = 1.0
    label: str | None = None


class NodeRead(BaseModel):
    id: str
    node_key: str
    label: str
    node_type: str
    health_status: str
    ip: str | None
    hostname: str | None
    position_x: float
    position_y: float
    metadata: dict | None


class EdgeRead(BaseModel):
    id: str
    source_node_id: str
    target_node_id: str
    relation_type: str
    propagation_prob: float
    weight: float
    label: str | None


class GraphRead(BaseModel):
    version_id: str
    app_id: str
    version_name: str
    nodes: list[NodeRead]
    edges: list[EdgeRead]


class VersionRead(BaseModel):
    id: str
    app_id: str
    version_name: str
    description: str | None
    is_active: bool
    created_at: str


class ParseTopologyRequest(BaseModel):
    app_id: str
    text: str


class BlastRadiusRead(BaseModel):
    origin_node_id: str
    origin_label: str
    total_impacted: int
    impacted_nodes: list[dict]


# ── Helpers ──────────────────────────────────────────────────────────


def _gnode_to_read(n: GraphNode) -> NodeRead:
    return NodeRead(
        id=n.id,
        node_key=n.node_key,
        label=n.label,
        node_type=n.node_type,
        health_status=n.health_status,
        ip=n.ip,
        hostname=n.hostname,
        position_x=n.position_x,
        position_y=n.position_y,
        metadata=n.metadata,
    )


def _gedge_to_read(e: GraphEdge) -> EdgeRead:
    return EdgeRead(
        id=e.id,
        source_node_id=e.source_node_id,
        target_node_id=e.target_node_id,
        relation_type=e.relation_type,
        propagation_prob=e.propagation_prob,
        weight=e.weight,
        label=e.label,
    )


async def _require_version(db: AsyncSession, version_id: str) -> TopologyVersion:
    v = await db.get(TopologyVersion, version_id)
    if not v:
        raise HTTPException(status_code=404, detail={"title": "Version không tồn tại"})
    return v


async def _resolve_node(db: AsyncSession, version_id: str, node_key: str) -> TopologyNode:
    n = (
        await db.execute(
            select(TopologyNode).where(
                TopologyNode.version_id == version_id,
                TopologyNode.node_key == node_key,
            )
        )
    ).scalar_one_or_none()
    if not n:
        raise HTTPException(
            status_code=404, detail={"title": f"Node '{node_key}' không tồn tại"}
        )
    return n


# ── Version endpoints ─────────────────────────────────────────────────


@router.get("/{app_id}/versions", response_model=list[VersionRead])
async def list_versions(
    app_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.can_access(app_id):
        raise HTTPException(status_code=403, detail={"title": "Không có quyền"})
    rows = (
        await db.execute(
            select(TopologyVersion)
            .where(TopologyVersion.app_id == app_id)
            .order_by(TopologyVersion.created_at.desc())
        )
    ).scalars().all()
    return [
        VersionRead(
            id=r.id,
            app_id=r.app_id,
            version_name=r.version_name,
            description=r.description,
            is_active=r.is_active,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]


@router.post("/{app_id}/versions", response_model=VersionRead, status_code=201)
async def create_version(
    app_id: str,
    body: dict,
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.can_access(app_id):
        raise HTTPException(status_code=403, detail={"title": "Không có quyền"})

    version = TopologyVersion(
        app_id=app_id,
        version_name=body.get("version_name", "v1"),
        description=body.get("description"),
        created_by=current_user.user_id,
    )
    db.add(version)
    await db.flush()
    await audit_log(
        db=db,
        user_id=current_user.user_id,
        action="CREATE_TOPOLOGY_VERSION",
        entity_type="topology_versions",
        entity_id=version.id,
        new_value={"app_id": app_id, "version_name": version.version_name},
        ip=request.client.host if request.client else None,
    )
    await db.commit()
    await db.refresh(version)
    return VersionRead(
        id=version.id,
        app_id=version.app_id,
        version_name=version.version_name,
        description=version.description,
        is_active=version.is_active,
        created_at=version.created_at.isoformat() if version.created_at else "",
    )


@router.post("/{app_id}/versions/{version_id}/activate", response_model=VersionRead)
async def activate_version(
    app_id: str,
    version_id: str,
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    version = await _require_version(db, version_id)
    if version.app_id != app_id:
        raise HTTPException(
            status_code=404, detail={"title": "Version không thuộc app_id này"}
        )

    # Deactivate all other versions for this app
    all_versions = (
        await db.execute(
            select(TopologyVersion).where(TopologyVersion.app_id == app_id)
        )
    ).scalars().all()
    for v in all_versions:
        v.is_active = v.id == version_id

    await db.commit()
    await db.refresh(version)
    return VersionRead(
        id=version.id,
        app_id=version.app_id,
        version_name=version.version_name,
        description=version.description,
        is_active=version.is_active,
        created_at=version.created_at.isoformat() if version.created_at else "",
    )


# ── Graph endpoints ───────────────────────────────────────────────────


@router.get("/{app_id}/graph", response_model=GraphRead)
async def get_graph(
    app_id: str,
    version_id: str | None = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.can_access(app_id):
        raise HTTPException(status_code=403, detail={"title": "Không có quyền"})

    svc = TopologyService(db)
    graph = await svc.get_graph(app_id, version_id)
    if not graph:
        return GraphRead(
            version_id="",
            app_id=app_id,
            version_name="Chưa có topology",
            nodes=[],
            edges=[],
        )

    return GraphRead(
        version_id=graph.version_id,
        app_id=graph.app_id,
        version_name=graph.version_name,
        nodes=[_gnode_to_read(n) for n in graph.nodes],
        edges=[_gedge_to_read(e) for e in graph.edges],
    )


# ── Node endpoints ────────────────────────────────────────────────────


@router.post(
    "/{app_id}/versions/{version_id}/nodes", response_model=NodeRead, status_code=201
)
async def add_node(
    app_id: str,
    version_id: str,
    body: NodeCreate,
    current_user: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    version = await _require_version(db, version_id)
    if version.app_id != app_id:
        raise HTTPException(
            status_code=404, detail={"title": "Version không thuộc app_id này"}
        )

    node = TopologyNode(
        version_id=version_id,
        app_id=app_id,
        node_key=body.node_key,
        label=body.label,
        node_type=body.node_type,
        ip=body.ip,
        hostname=body.hostname,
        position_x=body.position_x,
        position_y=body.position_y,
        metadata_=body.metadata,
    )
    db.add(node)
    try:
        await db.commit()
        await db.refresh(node)
    except Exception:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"title": f"Node key '{body.node_key}' đã tồn tại trong version này"},
        )

    return NodeRead(
        id=node.id,
        node_key=node.node_key,
        label=node.label,
        node_type=node.node_type,
        health_status=node.health_status,
        ip=node.ip,
        hostname=node.hostname,
        position_x=node.position_x,
        position_y=node.position_y,
        metadata=node.metadata_,
    )


@router.patch(
    "/{app_id}/versions/{version_id}/nodes/{node_id}", response_model=NodeRead
)
async def update_node(
    app_id: str,
    version_id: str,
    node_id: str,
    body: NodeUpdate,
    current_user: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    node = await db.get(TopologyNode, node_id)
    if not node or node.version_id != version_id:
        raise HTTPException(status_code=404, detail={"title": "Node không tồn tại"})

    if body.label is not None:
        node.label = body.label
    if body.node_type is not None:
        node.node_type = body.node_type
    if body.ip is not None:
        node.ip = body.ip
    if body.hostname is not None:
        node.hostname = body.hostname
    if body.position_x is not None:
        node.position_x = body.position_x
    if body.position_y is not None:
        node.position_y = body.position_y
    if body.metadata is not None:
        node.metadata_ = body.metadata
    if body.health_status is not None:
        node.health_status = body.health_status

    await db.commit()
    await db.refresh(node)
    return NodeRead(
        id=node.id,
        node_key=node.node_key,
        label=node.label,
        node_type=node.node_type,
        health_status=node.health_status,
        ip=node.ip,
        hostname=node.hostname,
        position_x=node.position_x,
        position_y=node.position_y,
        metadata=node.metadata_,
    )


@router.delete(
    "/{app_id}/versions/{version_id}/nodes/{node_id}", status_code=204
)
async def delete_node(
    app_id: str,
    version_id: str,
    node_id: str,
    current_user: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    node = await db.get(TopologyNode, node_id)
    if not node or node.version_id != version_id:
        raise HTTPException(status_code=404, detail={"title": "Node không tồn tại"})
    await db.delete(node)
    await db.commit()


# ── Edge endpoints ────────────────────────────────────────────────────


@router.post(
    "/{app_id}/versions/{version_id}/edges", response_model=EdgeRead, status_code=201
)
async def add_edge(
    app_id: str,
    version_id: str,
    body: EdgeCreate,
    current_user: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    version = await _require_version(db, version_id)
    if version.app_id != app_id:
        raise HTTPException(
            status_code=404, detail={"title": "Version không thuộc app_id này"}
        )

    source = await _resolve_node(db, version_id, body.source_node_key)
    target = await _resolve_node(db, version_id, body.target_node_key)

    edge = TopologyEdge(
        version_id=version_id,
        app_id=app_id,
        source_node_id=source.id,
        target_node_id=target.id,
        relation_type=body.relation_type,
        propagation_prob=body.propagation_prob,
        weight=body.weight,
        label=body.label,
    )
    db.add(edge)
    try:
        await db.commit()
        await db.refresh(edge)
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=409, detail={"title": "Edge đã tồn tại"})

    return EdgeRead(
        id=edge.id,
        source_node_id=edge.source_node_id,
        target_node_id=edge.target_node_id,
        relation_type=edge.relation_type,
        propagation_prob=edge.propagation_prob,
        weight=edge.weight,
        label=edge.label,
    )


@router.delete(
    "/{app_id}/versions/{version_id}/edges/{edge_id}", status_code=204
)
async def delete_edge(
    app_id: str,
    version_id: str,
    edge_id: str,
    current_user: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    edge = await db.get(TopologyEdge, edge_id)
    if not edge or edge.version_id != version_id:
        raise HTTPException(status_code=404, detail={"title": "Edge không tồn tại"})
    await db.delete(edge)
    await db.commit()


# ── Blast Radius ──────────────────────────────────────────────────────


@router.get("/{app_id}/blast-radius/{node_id}", response_model=BlastRadiusRead)
async def get_blast_radius(
    app_id: str,
    node_id: str,
    max_hops: int = Query(3, ge=1, le=5),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.can_access(app_id):
        raise HTTPException(status_code=403, detail={"title": "Không có quyền"})

    from app.prediction.blast_radius import compute_blast_radius

    result = await compute_blast_radius(node_id, db, max_hops=max_hops)

    return BlastRadiusRead(
        origin_node_id=result.origin_node_id,
        origin_label=result.origin_label,
        total_impacted=result.total_impacted,
        impacted_nodes=[
            {
                "node_id": n.node_id,
                "node_key": n.node_key,
                "label": n.label,
                "node_type": n.node_type,
                "hop": n.hop,
                "cumulative_prob": n.cumulative_prob,
            }
            for n in result.impacted_nodes
        ],
    )


# ── BFS Expand ────────────────────────────────────────────────────────


@router.get("/{app_id}/nodes/{node_id}/expand", response_model=GraphRead)
async def expand_node(
    app_id: str,
    node_id: str,
    hops: int = Query(2, ge=1, le=4),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.can_access(app_id):
        raise HTTPException(status_code=403, detail={"title": "Không có quyền"})

    node = await db.get(TopologyNode, node_id)
    if not node:
        raise HTTPException(status_code=404, detail={"title": "Node không tồn tại"})

    version = await db.get(TopologyVersion, node.version_id)

    svc = TopologyService(db)
    nodes, edges = await svc.bfs_expand(node_id, max_hops=hops)

    return GraphRead(
        version_id=node.version_id,
        app_id=app_id,
        version_name=version.version_name if version else "unknown",
        nodes=[_gnode_to_read(n) for n in nodes],
        edges=[_gedge_to_read(e) for e in edges],
    )


# ── LLM Parse endpoint ────────────────────────────────────────────────


@router.post("/{app_id}/parse", response_model=dict)
async def parse_topology_from_text(
    app_id: str,
    body: ParseTopologyRequest,
    current_user: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    LLM parse text mô tả topology → nodes + edges JSON.
    Ví dụ input: "Web LB → API Server → Oracle DB, API Server → Redis Cache"
    """
    from app.providers import get_llm_provider

    prompt_file = Path(__file__).parent.parent / "prompts" / "topology_parse_user.txt"
    if prompt_file.exists():
        template = prompt_file.read_text(encoding="utf-8")
        prompt = template.format(app_id=app_id, text=body.text)
    else:
        prompt = (
            f'Parse mô tả topology sau thành JSON:\n"{body.text}"\n\n'
            'Trả về JSON:\n'
            '{\n'
            '  "nodes": [\n'
            '    {"key": "web-lb", "label": "Web Load Balancer", "type": "loadbalancer"}\n'
            '  ],\n'
            '  "edges": [\n'
            '    {"source": "web-lb", "target": "api-server", "relation": "calls", "propagation_prob": 0.8}\n'
            '  ]\n'
            '}\n\nChỉ trả về JSON thuần, không markdown.'
        )

    try:
        llm = await get_llm_provider()
        raw = await llm.generate_json(prompt, temperature=0.0)
        data = _json.loads(raw)
    except Exception as e:
        raise HTTPException(
            status_code=502, detail={"title": f"LLM parse failed: {str(e)}"}
        )

    return {"app_id": app_id, "parsed": data, "raw_input": body.text}


# ── Bulk import ───────────────────────────────────────────────────────


@router.post("/{app_id}/versions/{version_id}/bulk-import", response_model=dict)
async def bulk_import(
    app_id: str,
    version_id: str,
    body: dict,
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Bulk import nodes + edges từ parsed JSON.
    body: {"nodes": [...], "edges": [...]}
    """
    version = await _require_version(db, version_id)
    if version.app_id != app_id:
        raise HTTPException(
            status_code=404, detail={"title": "Version không thuộc app_id này"}
        )

    nodes_data = body.get("nodes", [])
    edges_data = body.get("edges", [])

    node_key_to_id: dict[str, str] = {}
    nodes_created = 0

    for n in nodes_data:
        key = n.get("key", n.get("node_key", ""))
        existing = (
            await db.execute(
                select(TopologyNode).where(
                    TopologyNode.version_id == version_id,
                    TopologyNode.node_key == key,
                )
            )
        ).scalar_one_or_none()

        if existing:
            node_key_to_id[key] = existing.id
        else:
            node = TopologyNode(
                version_id=version_id,
                app_id=app_id,
                node_key=key,
                label=n.get("label", key),
                node_type=n.get("type", n.get("node_type", "service")),
                ip=n.get("ip"),
                hostname=n.get("hostname"),
            )
            db.add(node)
            await db.flush()
            node_key_to_id[key] = node.id
            nodes_created += 1

    edges_created = 0
    for e in edges_data:
        src_key = e.get("source", e.get("source_node_key", ""))
        tgt_key = e.get("target", e.get("target_node_key", ""))
        src_id = node_key_to_id.get(src_key)
        tgt_id = node_key_to_id.get(tgt_key)
        if not src_id or not tgt_id:
            continue

        existing_edge = (
            await db.execute(
                select(TopologyEdge).where(
                    TopologyEdge.version_id == version_id,
                    TopologyEdge.source_node_id == src_id,
                    TopologyEdge.target_node_id == tgt_id,
                )
            )
        ).scalar_one_or_none()

        if not existing_edge:
            edge = TopologyEdge(
                version_id=version_id,
                app_id=app_id,
                source_node_id=src_id,
                target_node_id=tgt_id,
                relation_type=e.get("relation", e.get("relation_type", "calls")),
                propagation_prob=float(e.get("propagation_prob", 0.5)),
                weight=float(e.get("weight", 1.0)),
                label=e.get("label"),
            )
            db.add(edge)
            edges_created += 1

    await db.commit()
    log.info(
        "topology_bulk_import",
        app_id=app_id,
        nodes=nodes_created,
        edges=edges_created,
    )

    return {
        "version_id": version_id,
        "nodes_created": nodes_created,
        "edges_created": edges_created,
        "total_nodes": len(nodes_data),
        "total_edges": len(edges_data),
    }
