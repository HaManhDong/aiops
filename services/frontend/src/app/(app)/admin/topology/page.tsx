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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { apiJson } from "@/lib/api"
import type { DatasourceConfig, TopologyNode, TopologyEdge } from "@/types/api"

const DAGRE_GRAPH_W = 200
const DAGRE_GRAPH_H = 60
type DatasourceResponse = DatasourceConfig[] | { datasources: DatasourceConfig[] }
type TopologyGraphResponse = {
  version_id: string
  app_id: string
  version_name: string
  nodes: TopologyNode[]
  edges: TopologyEdge[]
}

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
  const [apps, setApps] = useState<DatasourceConfig[]>([])
  const [appId, setAppId] = useState("")
  const [versionId, setVersionId] = useState("")
  const [versionName, setVersionName] = useState("")
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const datasourceData = await apiJson<DatasourceResponse>("/api/v1/admin/services")
      const datasources = Array.isArray(datasourceData) ? datasourceData : datasourceData.datasources ?? []
      const activeApps = datasources.filter((d) => d.is_active)
      setApps(activeApps)

      const appCandidates = appId
        ? [appId]
        : [...activeApps.map((app) => app.app_id), ...datasources.map((app) => app.app_id)]
            .filter((value, index, all) => value && all.indexOf(value) === index)
      if (!appCandidates.length) {
        setNodes([])
        setEdges([])
        setVersionId("")
        setVersionName("")
        return
      }

      let data: TopologyGraphResponse | null = null
      let selectedApp = appCandidates[0]
      for (const candidate of appCandidates) {
        try {
          data = await apiJson<TopologyGraphResponse>(`/api/v1/topology/${candidate}/graph`)
          selectedApp = candidate
          break
        } catch (err) {
          if (appId) throw err
        }
      }
      if (!data) {
        setNodes([])
        setEdges([])
        setVersionId("")
        setVersionName("")
        if (!appId) setAppId(selectedApp)
        return
      }
      if (!appId) setAppId(selectedApp)
      const { nodes: fn, edges: fe } = toFlow(data.nodes ?? [], data.edges ?? [])
      const hasPositions = fn.every((n) => n.position.x !== 0 || n.position.y !== 0)
      setNodes(hasPositions ? fn : applyDagreLayout(fn, fe))
      setEdges(fe)
      setVersionId(data.version_id)
      setVersionName(data.version_name)
    } catch (err: unknown) { toast.error(err instanceof Error ? err.message : "Lỗi tải topology") }
    finally { setLoading(false) }
  }, [appId, setNodes, setEdges])

  useEffect(() => { load() }, [load])

  const onConnect = useCallback((conn: Connection) => {
    setEdges((eds) => addEdge({ ...conn, animated: true }, eds))
  }, [setEdges])

  async function handleAutoLayout() {
    setNodes((ns) => applyDagreLayout(ns, edges))
  }

  async function handleSave() {
    if (!appId || !versionId) {
      toast.error("Chưa có topology version để lưu")
      return
    }
    setSaving(true)
    try {
      await Promise.all(nodes.map((node) => apiJson(
        `/api/v1/topology/${appId}/versions/${versionId}/nodes/${node.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            label: (node.data as { label: string }).label,
            position_x: Math.round(node.position.x),
            position_y: Math.round(node.position.y),
          }),
        }
      )))
      toast.success("Đã lưu topology")
    } catch (err: unknown) { toast.error(err instanceof Error ? err.message : "Lỗi lưu") }
    finally { setSaving(false) }
  }

  return (
    <div className="flex flex-col h-full p-4 gap-3">
      <div className="flex items-center gap-2">
        <h1 className="text-xl font-bold flex-1">Topology</h1>
        {versionName && <span className="text-xs text-muted-foreground">Version: {versionName}</span>}
        <Select value={appId} onValueChange={setAppId}>
          <SelectTrigger className="w-56">
            <SelectValue placeholder="Chọn app" />
          </SelectTrigger>
          <SelectContent>
            {apps.map((app) => (
              <SelectItem key={app.app_id} value={app.app_id}>{app.display_name} ({app.app_id})</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button size="sm" variant="outline" onClick={handleAutoLayout}>Auto Layout</Button>
        <Button size="sm" onClick={handleSave} disabled={saving}>{saving ? "Đang lưu..." : "Lưu"}</Button>
      </div>
      <div className="flex-1 rounded-md border overflow-hidden" style={{ minHeight: 500 }}>
        {loading ? (
          <div className="grid h-full min-h-[500px] place-items-center text-sm text-muted-foreground">Đang tải topology...</div>
        ) : nodes.length ? (
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
        ) : (
          <div className="grid h-full min-h-[500px] place-items-center text-sm text-muted-foreground">Chưa có topology cho app này.</div>
        )}
      </div>
    </div>
  )
}
