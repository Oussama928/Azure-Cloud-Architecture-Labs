import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import * as d3 from 'd3';
import './DependencyGraph.css';

interface ServiceNode extends d3.SimulationNodeDatum {
  id: string;
  name: string;
  namespace?: string;
  criticality: string;
  slo_target?: number;
  current_slo?: number;
  error_budget_remaining?: number;
  incident_count_24h: number;
  deployment_count_24h: number;
}

interface DependencyEdge {
  source: string;
  target: string;
  type: string;
  latency_p99?: number;
  error_rate?: number;
  request_volume?: number;
}

interface DependencyGraphData {
  nodes: ServiceNode[];
  edges: DependencyEdge[];
  updated_at: string;
}

interface DependencyGraphProps {
  data?: DependencyGraphData;
  onNodeClick?: (node: ServiceNode) => void;
  highlightedNodes?: string[];
  width?: number;
  height?: number;
  isLoading?: boolean;
  sourceUrls?: Record<string, string>;
  showDetailPanel?: boolean;
}

const NODE_W = 190;
const NODE_H = 96;
const H_STEP = 300;
const V_STEP = 180;
const PAD = 56;
const DEFAULT_SIZE = { width: 1200, height: 600 };

interface LayoutResult {
  positions: Map<string, { x: number; y: number }>;
  layers: string[][];
}

function dataSignature(data: DependencyGraphData | null | undefined): string {
  if (!data) return 'empty';
  const nodeIds = data.nodes.map(n => n.id).sort().join('|');
  const edgeIds = data.edges.map(e => `${e.source}->${e.target}`).sort().join('|');
  return `${data.updated_at}|${data.nodes.length}|${data.edges.length}|${nodeIds}|${edgeIds}`;
}

/** Compute a structured, layered layout from the dependency topology. */
function computeLayout(nodes: ServiceNode[], edges: DependencyEdge[], size: { width: number; height: number }): LayoutResult {
  const adj = new Map<string, string[]>();
  const inDeg = new Map<string, number>();
  nodes.forEach(n => {
    adj.set(n.id, []);
    inDeg.set(n.id, 0);
  });

  const validEdges = edges.filter(e => adj.has(e.source) && adj.has(e.target) && e.source !== e.target);
  validEdges.forEach(e => {
    adj.get(e.source)!.push(e.target);
    inDeg.set(e.target, inDeg.get(e.target)! + 1);
  });

  const hasAnyEdge = new Set<string>();
  validEdges.forEach(e => {
    hasAnyEdge.add(e.source);
    hasAnyEdge.add(e.target);
  });
  const isolated = nodes.filter(n => !hasAnyEdge.has(n.id));

  const depth = new Map<string, number>();
  const inStack = new Set<string>();
  const dfs = (id: string): number => {
    if (depth.has(id)) return depth.get(id)!;
    if (inStack.has(id)) return 0; // back-edge in a cycle: break recursion
    inStack.add(id);
    let d = 0;
    for (const t of adj.get(id)!) d = Math.max(d, dfs(t) + 1);
    inStack.delete(id);
    depth.set(id, d);
    return d;
  };
  nodes.forEach(n => {
    if (!depth.has(n.id)) dfs(n.id);
  });

  const maxDepth = Math.max(0, ...nodes.map(n => depth.get(n.id) ?? 0));
  const layers: string[][] = [];
  for (let d = 0; d <= maxDepth; d++) {
    const layer = nodes.filter(n => !isolated.includes(n) && (depth.get(n.id) ?? 0) === d).map(n => n.id);
    if (layer.length) layers.push(layer);
  }
  if (isolated.length) layers.push(isolated.map(n => n.id));

  const ordered: string[][] = [];
  const xOf = new Map<string, number>();
  layers.forEach((layer, li) => {
    if (li === 0) {
      ordered.push(layer.slice());
    } else {
      const withBary = layer.map(id => {
        const preds = validEdges.filter(e => e.target === id).map(e => e.source);
        const xs = preds.filter(p => xOf.has(p)).map(p => xOf.get(p)!);
        const bary = xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : Infinity;
        return { id, bary };
      });
      withBary.sort((a, b) => {
        if (a.bary === Infinity && b.bary === Infinity) return 0;
        if (a.bary === Infinity) return 1;
        if (b.bary === Infinity) return -1;
        return a.bary - b.bary;
      });
      ordered.push(withBary.map(o => o.id));
    }
    layer.forEach((id, idx) => xOf.set(id, idx));
  });

  const positions = new Map<string, { x: number; y: number }>();
  const layerCount = ordered.length;
  const totalW = layerCount * H_STEP - (H_STEP - NODE_W);
  const xOffset = Math.max(0, (size.width - totalW) / 2);

  ordered.forEach((layer, li) => {
    const count = layer.length;
    const totalH = count * V_STEP - (V_STEP - NODE_H);
    const yStart = Math.max(PAD, (size.height - totalH) / 2);
    layer.forEach((id, idx) => {
      positions.set(id, { x: PAD + li * H_STEP + xOffset, y: yStart + idx * V_STEP });
    });
  });

  return { positions, layers: ordered };
}

function healthColor(node: ServiceNode): string {
  if (node.current_slo != null && node.slo_target != null && node.current_slo < node.slo_target) {
    return 'var(--color-error)';
  }
  return 'var(--color-success)';
}

function edgePath(e: { source: string; target: string }, pos: Map<string, { x: number; y: number }>): string {
  const s = pos.get(e.source);
  const t = pos.get(e.target);
  if (!s || !t) return '';
  const x1 = s.x;
  const y1 = s.y + NODE_H / 2;
  const x2 = t.x;
  const y2 = t.y - NODE_H / 2;
  const my = (y1 + y2) / 2;
  return `M${x1},${y1} C${x1},${my} ${x2},${my} ${x2},${y2}`;
}

const DependencyGraph: React.FC<DependencyGraphProps> = ({
  data,
  onNodeClick,
  highlightedNodes = [],
  width = DEFAULT_SIZE.width,
  height = DEFAULT_SIZE.height,
  isLoading = false,
  sourceUrls = {},
  showDetailPanel = true,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const fitTransformRef = useRef<d3.ZoomTransform | null>(null);
  const [size, setSize] = useState({ width, height });
  const [selectedNode, setSelectedNode] = useState<ServiceNode | null>(null);
  const [query, setQuery] = useState('');

  const draggedPos = useRef<Map<string, { x: number; y: number }>>(new Map());
  const dragActiveRef = useRef(false);

  const onNodeClickRef = useRef(onNodeClick);
  useEffect(() => {
    onNodeClickRef.current = onNodeClick;
  }, [onNodeClick]);

  const getCriticalityColor = useCallback((criticality?: string): string => {
    switch ((criticality ?? '').toLowerCase()) {
      case 'high':
      case 'critical':
        return 'var(--color-criticality-high)';
      case 'medium':
        return 'var(--color-criticality-medium)';
      case 'low':
        return 'var(--color-criticality-low)';
      default:
        return 'var(--color-text-quaternary)';
    }
  }, []);

  const getEdgeColor = useCallback((errorRate?: number): string => {
    return errorRate && errorRate > 0.05 ? 'var(--color-error)' : 'var(--color-border-secondary)';
  }, []);

  const getEdgeWidth = useCallback((errorRate?: number): number => {
    return errorRate && errorRate > 0.05 ? 3.5 : 1.5;
  }, []);

  // Track rendered container size so the SVG never distorts.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const updateSize = () => {
      const rect = container.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        setSize({ width: Math.round(rect.width), height: Math.round(rect.height) });
      }
    };

    updateSize();
    const observer = new ResizeObserver(updateSize);
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  const signature = useMemo(() => dataSignature(data), [data]);
  const layout = useMemo<LayoutResult | null>(() => {
    if (!data || data.nodes.length === 0) return null;
    return computeLayout(data.nodes, data.edges, size);
    // Recompute when data changes, not on every resize (positions are relative to center).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, signature]);

  const searchActive = query.trim().length > 0;
  const normalizedQuery = query.trim().toLowerCase();
  const matchesQuery = useCallback(
    (node: ServiceNode) => !searchActive || node.name.toLowerCase().includes(normalizedQuery),
    [searchActive, normalizedQuery],
  );

  const prevSignature = useRef<string | null>(null);

  useEffect(() => {
    if (!svgRef.current || !data || !layout) return;

    if (prevSignature.current === signature) return;
    const isFirstBuild = prevSignature.current === null;
    prevSignature.current = signature;

    const svg = d3.select(svgRef.current);
    const g = svg.select<SVGGElement>('g.graph-group');
    g.selectAll('*').remove();

    const pos = layout.positions;

    const edgeData = data.edges
      .filter(e => pos.has(e.source) && pos.has(e.target))
      .map(e => ({
        ...e,
        _dimmed: searchActive && !matchesQuery(data.nodes.find(n => n.id === e.source)!) && !matchesQuery(data.nodes.find(n => n.id === e.target)!),
      }));

    const nodeData = data.nodes.map(n => {
      const p = draggedPos.current.get(n.id) ?? pos.get(n.id);
      return { ...n, x: p?.x ?? 0, y: p?.y ?? 0 };
    }) as ServiceNode[];

    const link = g.append('g')
      .attr('class', 'links')
      .selectAll<SVGPathElement, typeof edgeData[number]>('path')
      .data(edgeData)
      .join('path')
      .attr('class', d => `link${d._dimmed ? ' dimmed' : ''}`)
      .attr('d', d => edgePath(d, pos))
      .attr('stroke', d => getEdgeColor(d.error_rate))
      .attr('stroke-width', d => getEdgeWidth(d.error_rate))
      .attr('stroke-dasharray', d => d.type === 'depends_on' ? 'none' : '5,5')
      .attr('marker-end', 'url(#arrowhead)');

    link.append('title')
      .text(d => `${d.source} \u2192 ${d.target}${d.latency_p99 ? ` \u00b7 ${d.latency_p99}ms p99` : ''}${d.error_rate ? ` \u00b7 ${(d.error_rate * 100).toFixed(1)}% err` : ''}`);

    const node = g.append('g')
      .attr('class', 'nodes')
      .selectAll<SVGGElement, ServiceNode>('g')
      .data(nodeData)
      .join('g')
      .attr('class', d => `node${matchesQuery(d) ? '' : ' dimmed'}`)
      .attr('transform', d => `translate(${d.x},${d.y})`)
      .on('click', (event, d) => {
        if (dragActiveRef.current) {
          dragActiveRef.current = false;
          return;
        }
        event.stopPropagation();
        setSelectedNode(d);
        onNodeClickRef.current?.(d);
      });

    node.append('rect')
      .attr('class', 'node-card')
      .attr('x', -NODE_W / 2)
      .attr('y', -NODE_H / 2)
      .attr('width', NODE_W)
      .attr('height', NODE_H)
      .attr('rx', 14);

    node.append('rect')
      .attr('class', 'node-accent')
      .attr('x', -NODE_W / 2)
      .attr('y', -NODE_H / 2)
      .attr('width', 6)
      .attr('height', NODE_H)
      .attr('rx', 3)
      .attr('fill', d => getCriticalityColor(d.criticality));

    node.append('circle')
      .attr('class', 'node-status')
      .attr('cx', NODE_W / 2 - 14)
      .attr('cy', -NODE_H / 2 + 14)
      .attr('r', 4.5)
      .attr('fill', d => healthColor(d));

    node.append('text')
      .attr('class', 'node-name')
      .attr('x', -NODE_W / 2 + 18)
      .attr('y', -NODE_H / 2 + 24)
      .text(d => d.name);

    node.append('text')
      .attr('class', 'node-criticality')
      .attr('x', -NODE_W / 2 + 18)
      .attr('y', -NODE_H / 2 + 41)
      .text(d => (d.criticality ?? 'unknown').toUpperCase());

    node.append('text')
      .attr('class', 'node-slo-label')
      .attr('x', NODE_W / 2 - 16)
      .attr('y', -NODE_H / 2 + 20)
      .text('SLO');

    node.append('text')
      .attr('class', 'node-slo-value')
      .attr('x', NODE_W / 2 - 16)
      .attr('y', -NODE_H / 2 + 37)
      .attr('fill', d => healthColor(d))
      .text(d => (d.current_slo != null ? `${d.current_slo.toFixed(2)}%` : '\u2014'));

    node.append('text')
      .attr('class', 'node-badges')
      .attr('x', -NODE_W / 2 + 18)
      .attr('y', NODE_H / 2 - 16)
      .text(d => {
        const parts = [];
        if (d.incident_count_24h > 0) parts.push(`\u26A0 ${d.incident_count_24h}`);
        if (d.deployment_count_24h > 0) parts.push(`\u25B2 ${d.deployment_count_24h}`);
        if (d.error_budget_remaining != null) parts.push(`\u20AC ${d.error_budget_remaining.toFixed(0)}%`);
        return parts.join('  ');
      });

    const updateEdgePaths = (id: string) => {
      link
        .filter((d: { source: string; target: string }) => d.source === id || d.target === id)
        .attr('d', d => edgePath(d, pos));
    };

    // Drag: coordinates are relative to the graph group (unaffected by zoom).
    const drag = d3.drag<SVGGElement, ServiceNode>()
      .on('start', function (this: SVGGElement, event, d) {
        dragActiveRef.current = false;
        d.fx = d.x;
        d.fy = d.y;
        d3.select(this).raise();
      })
      .on('drag', function (this: SVGGElement, event, d) {
        dragActiveRef.current = true;
        d.fx = event.x;
        d.fy = event.y;
        d.x = event.x;
        d.y = event.y;
        pos.set(d.id, { x: event.x, y: event.y });
        d3.select(this).attr('transform', `translate(${event.x},${event.y})`);
        updateEdgePaths(d.id);
      })
      .on('end', function (this: SVGGElement, event, d) {
        d.fx = null;
        d.fy = null;
        const x = d.x ?? event.x;
        const y = d.y ?? event.y;
        draggedPos.current.set(d.id, { x, y });
        pos.set(d.id, { x, y });
        window.setTimeout(() => {
          dragActiveRef.current = false;
        }, 0);
      });

    node.call(drag as unknown as (selection: d3.Selection<SVGGElement, ServiceNode, SVGGElement, unknown>) => void);

    // Attach zoom only now that the SVG exists (svgRef is null while the
    // loading skeleton is shown), and fit the view once on first build.
    attachZoom();
    if (isFirstBuild) {
      fitGraph();
    }

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, signature, layout, getEdgeColor, getEdgeWidth, getCriticalityColor]);

  // Highlight updates (no full re-render)
  useEffect(() => {
    if (!svgRef.current || !data) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll<SVGGElement, ServiceNode>('g.node')
      .classed('highlighted', d => highlightedNodes.includes(d.id))
      .select('rect.node-card')
      .attr('stroke', d => highlightedNodes.includes(d.id) ? 'var(--color-warning)' : null)
      .attr('stroke-width', d => highlightedNodes.includes(d.id) ? 3 : null);
  }, [highlightedNodes, data]);

  useEffect(() => {
    if (!showDetailPanel) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelectedNode(null);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [showDetailPanel]);

  const attachZoom = useCallback(() => {
    if (!svgRef.current) return;
    const svg = d3.select(svgRef.current);
    const g = svg.select<SVGGElement>('g.graph-group');

    if (zoomRef.current) {
      svg.on('.zoom', null);
    }
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 4])
      .filter((event) => {
        if (event.type === 'wheel') return true;
        return !(event.target as Element).closest?.('.node');
      })
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
      });

    zoomRef.current = zoom;
    svg.call(zoom);
  }, []);

  const fitGraph = useCallback(() => {
    if (!svgRef.current || !layout || !zoomRef.current) return;
    const svg = d3.select(svgRef.current);
    const positions = layout.positions;
    if (positions.size === 0) return;

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    positions.forEach(p => {
      minX = Math.min(minX, p.x);
      minY = Math.min(minY, p.y);
      maxX = Math.max(maxX, p.x);
      maxY = Math.max(maxY, p.y);
    });

    const bw = (maxX - minX) + NODE_W;
    const bh = (maxY - minY) + NODE_H;
    const pad = 48;
    const scale = Math.min((size.width - pad * 2) / bw, (size.height - pad * 2) / bh, 1.1);
    const tx = (size.width - bw * scale) / 2 - minX * scale;
    const ty = (size.height - bh * scale) / 2 - minY * scale;
    const t = d3.zoomIdentity.translate(tx, ty).scale(scale);
    fitTransformRef.current = t;
    svg.call(zoomRef.current.transform, t);
  }, [layout, size]);

  const resetZoom = useCallback(() => {
    if (!svgRef.current || !zoomRef.current) return;
    const svg = d3.select(svgRef.current);
    if (fitTransformRef.current) {
      svg.transition().duration(300).call(zoomRef.current.transform, fitTransformRef.current);
    } else {
      svg.transition().duration(300).call(zoomRef.current.transform, d3.zoomIdentity);
    }
  }, []);

  if (isLoading) {
    return (
      <div className="dependency-graph skeleton-loading" aria-busy="true">
        <div className="skeleton" style={{ height: '24px', width: '30%' }} />
        <div className="skeleton" style={{ height: '100%', minHeight: '400px', marginTop: '16px', borderRadius: 'var(--radius-md)' }} />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="dependency-graph empty" role="status">
        <svg className="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
          <circle cx="12" cy="12" r="10" />
          <line x1="2" y1="12" x2="22" y2="12" />
          <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
        </svg>
        <p className="empty-text">No dependency data available</p>
        <p className="empty-subtext">Service topology will appear here when data is loaded</p>
      </div>
    );
  }

  return (
    <div className="dependency-graph">
      <div className="graph-header">
        <div className="header-content">
          <h2 className="graph-title">Service Dependency Graph</h2>
          <p className="graph-subtitle">Structured topology by dependency depth, built from live OpenTelemetry traces. Drag nodes, scroll to zoom, click a service for details.</p>
        </div>
        <div className="graph-controls">
          <div className="graph-search">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              type="text"
              className="graph-search-input"
              placeholder="Filter services..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Filter services"
            />
          </div>
          <button onClick={resetZoom} className="btn btn-secondary btn-sm" title="Fit graph to view" aria-label="Fit graph to view">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M8 3H5a2 2 0 0 0-2 2v3" />
              <path d="M21 8V5a2 2 0 0 0-2-2h-3" />
              <path d="M3 16v3a2 2 0 0 0 2 2h3" />
              <path d="M16 21h3a2 2 0 0 0 2-2v-3" />
            </svg>
            <span>Fit View</span>
          </button>
          <span className="node-count">{data.nodes.length} services, {data.edges.length} dependencies</span>
        </div>
      </div>

      <div className="graph-legend" role="group" aria-label="Graph legend">
        <div className="legend-group">
          <span className="legend-group-title">Criticality</span>
          <div className="legend-items">
            <div className="legend-item">
              <span className="legend-color" style={{ backgroundColor: 'var(--color-criticality-low)' }}></span>
              <span>Low</span>
            </div>
            <div className="legend-item">
              <span className="legend-color" style={{ backgroundColor: 'var(--color-criticality-medium)' }}></span>
              <span>Medium</span>
            </div>
            <div className="legend-item">
              <span className="legend-color" style={{ backgroundColor: 'var(--color-criticality-high)' }}></span>
              <span>High / Critical</span>
            </div>
          </div>
        </div>
        <div className="legend-divider" aria-hidden="true"></div>
        <div className="legend-group">
          <span className="legend-group-title">Dependencies</span>
          <div className="legend-items">
            <div className="legend-item">
              <svg width="20" height="10" aria-hidden="true"><line x1="0" y1="5" x2="20" y2="5" stroke="var(--color-border-secondary)" strokeWidth="1.5" markerEnd="url(#arrowhead)" /></svg>
              <span>Depends On</span>
            </div>
            <div className="legend-item">
              <svg width="20" height="10" aria-hidden="true"><line x1="0" y1="5" x2="20" y2="5" stroke="var(--color-error)" strokeWidth="3.5" markerEnd="url(#arrowhead)" /></svg>
              <span>High Error Rate</span>
            </div>
            <div className="legend-item">
              <span className="legend-color highlighted" style={{ backgroundColor: 'var(--color-bg-secondary)', border: '2px solid var(--color-warning)' }}></span>
              <span>Highlighted</span>
            </div>
          </div>
        </div>
        <div className="legend-divider" aria-hidden="true"></div>
        <div className="legend-group">
          <span className="legend-group-title">SLO Health</span>
          <div className="legend-items">
            <div className="legend-item">
              <span className="legend-color" style={{ backgroundColor: 'var(--color-success)' }}></span>
              <span>Healthy</span>
            </div>
            <div className="legend-item">
              <span className="legend-color" style={{ backgroundColor: 'var(--color-error)' }}></span>
              <span>Degraded</span>
            </div>
          </div>
        </div>
      </div>

      <div className="graph-container" ref={containerRef}>
        <svg
          ref={svgRef}
          width={size.width}
          height={size.height}
          className="dependency-graph-svg"
          role="img"
          aria-label="Structured service dependency graph showing layered service relationships"
        >
          <defs>
            <marker
              id="arrowhead"
              viewBox="0 -5 10 10"
              refX={28}
              refY={0}
              orient="auto"
              markerWidth={7}
              markerHeight={7}
            >
              <path d="M0,-5L10,0L0,5" fill="var(--color-border-secondary)" />
            </marker>
          </defs>
          <g className="graph-group" />
        </svg>
      </div>

      {showDetailPanel && selectedNode && (
        <div className="node-detail-panel" role="dialog" aria-labelledby="node-detail-title" aria-modal="true">
          <div className="detail-header">
            <div className="detail-title-wrap">
              <span className="detail-status-dot" style={{ backgroundColor: healthColor(selectedNode) }}></span>
              <h3 id="node-detail-title" className="detail-title">{selectedNode.name}</h3>
            </div>
            <button className="detail-close" onClick={() => setSelectedNode(null)} aria-label="Close details">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
          <div className="detail-slo">
            <div className="detail-slo-ring" style={{ borderColor: healthColor(selectedNode) }}>
              <span>{selectedNode.current_slo != null ? selectedNode.current_slo.toFixed(2) : '\u2014'}</span>
              <small>% SLO</small>
            </div>
            <div className="detail-slo-meta">
              <div className="detail-row">
                <span className="detail-label">Target</span>
                <span className="detail-value">{selectedNode.slo_target != null ? `${selectedNode.slo_target}%` : 'N/A'}</span>
              </div>
              <div className="detail-row">
                <span className="detail-label">Error Budget</span>
                <span className="detail-value">{selectedNode.error_budget_remaining != null ? `${selectedNode.error_budget_remaining.toFixed(1)}%` : 'N/A'}</span>
              </div>
            </div>
          </div>
          <div className="detail-content">
            <div className="detail-row">
              <span className="detail-label">Namespace</span>
              <span className="detail-value">{selectedNode.namespace || 'N/A'}</span>
            </div>
            <div className="detail-row">
              <span className="detail-label">Criticality</span>
              <span className="detail-value criticality-badge" style={{ backgroundColor: getCriticalityColor(selectedNode.criticality) }}>
                {selectedNode.criticality}
              </span>
            </div>
            <div className="detail-row">
              <span className="detail-label">Incidents (24h)</span>
              <span className="detail-value">{selectedNode.incident_count_24h}</span>
            </div>
            <div className="detail-row">
              <span className="detail-label">Deployments (24h)</span>
              <span className="detail-value">{selectedNode.deployment_count_24h}</span>
            </div>
            {Object.entries(sourceUrls)
              .filter(([k, url]) => ['kubernetes', 'argocd'].includes(k) && url && url.trim())
              .map(([key, url]) => {
              const cleanUrl = url.replace(/\/+$/, '');
              const link = key === 'kubernetes'
                ? `${cleanUrl}/api/v1/namespaces/${selectedNode.namespace || 'default'}/services/${selectedNode.name}`
                : `${cleanUrl}/applications/${selectedNode.name}`;
              return (
                <div className="detail-row" key={key}>
                  <span className="detail-label">{key}</span>
                  <a href={link} target="_blank" rel="noopener noreferrer" className="detail-value detail-link">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                      <polyline points="15 3 21 3 21 9" />
                      <line x1="10" y1="14" x2="21" y2="3" />
                    </svg>
                    Open
                  </a>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

export default DependencyGraph;
