from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.topology import TopologyEdge, TopologyNode, TopologyVersion

log = structlog.get_logger()


@dataclass
class GraphNode:
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


@dataclass
class GraphEdge:
    id: str
    source_node_id: str
    target_node_id: str
    relation_type: str
    propagation_prob: float
    weight: float
    label: str | None


@dataclass
class TopologyGraph:
    version_id: str
    app_id: str
    version_name: str
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)


class TopologyService:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def get_active_version(self, app_id: str) -> TopologyVersion | None:
        """Lấy active version của app_id."""
        return (
            await self._db.execute(
                select(TopologyVersion)
                .where(TopologyVersion.app_id == app_id, TopologyVersion.is_active == True)  # noqa: E712
                .order_by(TopologyVersion.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def get_graph(
        self, app_id: str, version_id: str | None = None
    ) -> TopologyGraph | None:
        """Lấy toàn bộ graph cho app_id."""
        if version_id:
            version = await self._db.get(TopologyVersion, version_id)
        else:
            version = await self.get_active_version(app_id)

        if not version:
            return None

        nodes_rows = (
            await self._db.execute(
                select(TopologyNode).where(TopologyNode.version_id == version.id)
            )
        ).scalars().all()

        edges_rows = (
            await self._db.execute(
                select(TopologyEdge).where(TopologyEdge.version_id == version.id)
            )
        ).scalars().all()

        return TopologyGraph(
            version_id=version.id,
            app_id=app_id,
            version_name=version.version_name,
            nodes=[_node_to_graph(n) for n in nodes_rows],
            edges=[_edge_to_graph(e) for e in edges_rows],
        )

    async def bfs_expand(
        self, node_id: str, max_hops: int = 2
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        """
        BFS từ node_id ra tối đa max_hops bước.
        Trả về (nodes, edges) của subgraph.
        """
        visited_nodes: set[str] = {node_id}
        visited_edges: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(node_id, 0)])

        result_nodes: list[TopologyNode] = []
        result_edges: list[TopologyEdge] = []

        start_node = await self._db.get(TopologyNode, node_id)
        if not start_node:
            return [], []
        result_nodes.append(start_node)

        while queue:
            current_id, depth = queue.popleft()
            if depth >= max_hops:
                continue

            # Outgoing edges
            out_edges = (
                await self._db.execute(
                    select(TopologyEdge).where(TopologyEdge.source_node_id == current_id)
                )
            ).scalars().all()

            # Incoming edges
            in_edges = (
                await self._db.execute(
                    select(TopologyEdge).where(TopologyEdge.target_node_id == current_id)
                )
            ).scalars().all()

            for edge in list(out_edges) + list(in_edges):
                if edge.id not in visited_edges:
                    visited_edges.add(edge.id)
                    result_edges.append(edge)

                neighbor_id = (
                    edge.target_node_id
                    if edge.source_node_id == current_id
                    else edge.source_node_id
                )
                if neighbor_id not in visited_nodes:
                    visited_nodes.add(neighbor_id)
                    neighbor = await self._db.get(TopologyNode, neighbor_id)
                    if neighbor:
                        result_nodes.append(neighbor)
                    queue.append((neighbor_id, depth + 1))

        return [_node_to_graph(n) for n in result_nodes], [_edge_to_graph(e) for e in result_edges]

    async def update_node_health(self, node_id: str, health_status: str) -> None:
        """Cập nhật health_status của node (gọi từ health writer)."""
        node = await self._db.get(TopologyNode, node_id)
        if node:
            node.health_status = health_status
            await self._db.commit()


def _node_to_graph(n: TopologyNode) -> GraphNode:
    return GraphNode(
        id=n.id,
        node_key=n.node_key,
        label=n.label,
        node_type=n.node_type,
        health_status=n.health_status,
        ip=n.ip,
        hostname=n.hostname,
        position_x=n.position_x,
        position_y=n.position_y,
        metadata=n.metadata_,
    )


def _edge_to_graph(e: TopologyEdge) -> GraphEdge:
    return GraphEdge(
        id=e.id,
        source_node_id=e.source_node_id,
        target_node_id=e.target_node_id,
        relation_type=e.relation_type,
        propagation_prob=e.propagation_prob,
        weight=e.weight,
        label=e.label,
    )
