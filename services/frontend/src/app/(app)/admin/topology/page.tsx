"use client"
import { useCallback, useEffect, useState } from "react"
import { toast } from "sonner"
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type Connection,
  type Node,
  type Edge,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import dagre from "dagre"
import { Button } from "@/components/ui/button"
import { apiJson } from "@/lib/api"
import type { TopologyNode, TopologyEdge } from "@/types/api"

const DAGRE_GRAPH_W = 200
const DAGRE_GRAPH_H = 60

function applyDagreLayout(nodes: Node[], edges: Edge[]): Node[] {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: "LR", nodesep: 80, ranksep: 120 })
  g.setDefaultEdgeLabel(() => ({}))
  nodes.forEach((n) => g.setNode(n.id, { width: DAGRE_GRAPH_W, height: DAGRE_GRAPH_H }))
  edges.forEach((e) => g.setEdge(e.source, e.target))
  dagre.layout(g)
  return nodes.map((n) => {
    const pos = g.node(n.id)
    return { ...n, position: { x: pos.x - DAGRE_GRAPH_W / 2, y: pos.y - DAGRE_GRAPH_H / 2 } }
  })
}

function toFlow(tnodes: TopologyNode[], tedges: TopologyEdge[]): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = tnodes.map((n) => ({
    id: n.id,
    data: { label: n.label ?? n.id },
    position: { x: n.position_x ?? 0, y: n.position_y ?? 0 },
    type: "default",
  }))
  const edges: Edge[] = tedges.map((e) => ({
    id: e.id,
    source: e.source_node_id,
    target: e.target_node_id,
    label: e.label,
    animated: true,
  }))
  return { nodes, edges }
}

export default function TopologyPage() {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [saving, setSaving] = useState(false)
  const [appId] = useState("all")

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams()
      if (appId !== "all") params.set("app_id", appId)
      const data = await apiJson<{ nodes: TopologyNode[]; edges: TopologyEdge[] }>(`/api/v1/topology?${params}`)
      const { nodes: fn, edges: fe } = toFlow(data.nodes ?? [], data.edges ?? [])
      const hasPositions = fn.every((n) => n.position.x !== 0 || n.position.y !== 0)
      setNodes(hasPositions ? fn : applyDagreLayout(fn, fe))
      setEdges(fe)
    } catch (err: unknown) { toast.error(err instanceof Error ? err.message : "Lỗi tải topology") }
  }, [appId, setNodes, setEdges])

  useEffect(() => { load() }, [load])

  const onConnect = useCallback((conn: Connection) => {
    setEdges((eds) => addEdge({ ...conn, animated: true }, eds))
  }, [setEdges])

  async function handleAutoLayout() {
    setNodes((ns) => applyDagreLayout(ns, edges))
  }

  async function handleSave() {
    setSaving(true)
    try {
      const payload = {
        nodes: nodes.map((n) => ({
          id: n.id,
          label: (n.data as { label: string }).label,
          position_x: Math.round(n.position.x),
          position_y: Math.round(n.position.y),
          app_id: appId !== "all" ? appId : undefined,
        })),
        edges: edges.map((e) => ({
          id: e.id,
          source_node_id: e.source,
          target_node_id: e.target,
          label: e.label as string | undefined,
        })),
      }
      await apiJson("/api/v1/topology", { method: "PUT", body: JSON.stringify(payload) })
      toast.success("Đã lưu topology")
    } catch (err: unknown) { toast.error(err instanceof Error ? err.message : "Lỗi lưu") }
    finally { setSaving(false) }
  }

  return (
    <div className="flex flex-col h-full p-4 gap-3">
      <div className="flex items-center gap-2">
        <h1 className="text-xl font-bold flex-1">Topology</h1>
        <Button size="sm" variant="outline" onClick={handleAutoLayout}>Auto Layout</Button>
        <Button size="sm" onClick={handleSave} disabled={saving}>{saving ? "Đang lưu..." : "Lưu"}</Button>
      </div>
      <div className="flex-1 rounded-md border overflow-hidden" style={{ minHeight: 500 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          fitView
        >
          <Background />
          <Controls />
          <MiniMap />
        </ReactFlow>
      </div>
    </div>
  )
}
