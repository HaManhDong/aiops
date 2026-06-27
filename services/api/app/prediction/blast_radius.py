from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.topology import TopologyEdge, TopologyNode

log = structlog.get_logger()

_MAX_HOPS = 3
_MIN_PROPAGATION_PROB = 0.1


@dataclass
class BlastImpact:
    node_id: str
    node_key: str
    label: str
    node_type: str
    hop: int
    cumulative_prob: float


@dataclass
class BlastRadius:
    origin_node_id: str
    origin_label: str
    impacted_nodes: list[BlastImpact] = field(default_factory=list)
    total_impacted: int = 0


async def compute_blast_radius(
    origin_node_id: str,
    db: AsyncSession,
    max_hops: int = _MAX_HOPS,
) -> BlastRadius:
    """
    BFS từ origin node, lan truyền theo propagation_prob trên edges.
    Chỉ tiếp tục BFS khi cumulative_prob >= MIN_PROPAGATION_PROB.
    """
    origin = await db.get(TopologyNode, origin_node_id)
    if not origin:
        return BlastRadius(
            origin_node_id=origin_node_id,
            origin_label="unknown",
            impacted_nodes=[],
            total_impacted=0,
        )

    visited: dict[str, float] = {origin_node_id: 1.0}  # node_id → cumulative_prob
    queue: deque[tuple[str, int, float]] = deque([(origin_node_id, 0, 1.0)])
    impacts: list[BlastImpact] = []

    while queue:
        current_id, depth, current_prob = queue.popleft()
        if depth >= max_hops:
            continue

        # Follow outgoing edges (downstream impact)
        out_edges = (
            await db.execute(
                select(TopologyEdge).where(TopologyEdge.source_node_id == current_id)
            )
        ).scalars().all()

        for edge in out_edges:
            neighbor_id = edge.target_node_id
            new_prob = current_prob * edge.propagation_prob

            if new_prob < _MIN_PROPAGATION_PROB:
                continue

            if neighbor_id not in visited or visited[neighbor_id] < new_prob:
                visited[neighbor_id] = new_prob
                neighbor = await db.get(TopologyNode, neighbor_id)
                if neighbor:
                    impacts.append(
                        BlastImpact(
                            node_id=neighbor_id,
                            node_key=neighbor.node_key,
                            label=neighbor.label,
                            node_type=neighbor.node_type,
                            hop=depth + 1,
                            cumulative_prob=round(new_prob, 4),
                        )
                    )
                queue.append((neighbor_id, depth + 1, new_prob))

    # Sort by cumulative_prob descending
    impacts.sort(key=lambda x: x.cumulative_prob, reverse=True)

    return BlastRadius(
        origin_node_id=origin_node_id,
        origin_label=origin.label,
        impacted_nodes=impacts,
        total_impacted=len(impacts),
    )
