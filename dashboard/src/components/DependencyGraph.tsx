import React, { useEffect, useRef, useState } from 'react';
import * as d3 from 'd3';
import './DependencyGraph.css';

interface ServiceNode {
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
}

const DependencyGraph: React.FC<DependencyGraphProps> = ({
  data,
  onNodeClick,
  highlightedNodes = [],
  width = 800,
  height = 600,
}) => {
  const svgRef = useRef<SVGSVGElement>(null);
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 });
  const [selectedNode, setSelectedNode] = useState<ServiceNode | null>(null);

  useEffect(() => {
    if (!svgRef.current || !data) return;

    const svg = d3.select(svgRef.current);
    const g = svg.select<SVGGElement>('g.graph-group');

    // Clear previous render
    g.selectAll('*').remove();

    // Create simulation
    const simulation = d3.forceSimulation<ServiceNode, DependencyEdge>(data.nodes)
      .force('link', d3.forceLink<ServiceNode, DependencyEdge>(data.edges)
        .id(d => d.id)
        .distance(150)
        .strength(0.7))
      .force('charge', d3.forceManyBody().strength(-400))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(60))
      .force('x', d3.forceX(width / 2).strength(0.1))
      .force('y', d3.forceY(height / 2).strength(0.1));

    // Draw edges
    const link = g.append('g')
      .attr('class', 'links')
      .selectAll('line')
      .data(data.edges)
      .join('line')
      .attr('class', 'link')
      .attr('stroke', d => d.error_rate && d.error_rate > 0.05 ? '#ef4444' : '#94a3b8')
      .attr('stroke-width', d => d.error_rate && d.error_rate > 0.05 ? 3 : 1.5)
      .attr('stroke-dasharray', d => d.type === 'depends_on' ? 'none' : '5,5')
      .attr('marker-end', 'url(#arrowhead)');

    // Draw nodes
    const node = g.append('g')
      .attr('class', 'nodes')
      .selectAll('g')
      .data(data.nodes)
      .join('g')
      .attr('class', d => `node ${highlightedNodes.includes(d.id) ? 'highlighted' : ''}`)
      .call(drag(simulation))
      .on('click', (event, d) => {
        event.stopPropagation();
        setSelectedNode(d);
        onNodeClick?.(d);
      });

    // Node circle
    node.append('circle')
      .attr('r', 30)
      .attr('fill', d => getCriticalityColor(d.criticality))
      .attr('stroke', d => highlightedNodes.includes(d.id) ? '#f59e0b' : '#1e293b')
      .attr('stroke-width', d => highlightedNodes.includes(d.id) ? 3 : 1.5)
      .attr('filter', 'drop-shadow(0 2px 4px rgba(0,0,0,0.1))');

    // Service name
    node.append('text')
      .attr('class', 'node-label')
      .attr('text-anchor', 'middle')
      .attr('dy', -40)
      .text(d => d.name)
      .style('font-size', '12px')
      .style('font-weight', '600')
      .style('fill', '#1e293b');

    // Namespace
    node.append('text')
      .attr('class', 'node-namespace')
      .attr('text-anchor', 'middle')
      .attr('dy', -26)
      .text(d => d.namespace ? `[${d.namespace}]` : '')
      .style('font-size', '10px')
      .style('fill', '#64748b');

    // SLO indicator
    node.append('text')
      .attr('class', 'node-slo')
      .attr('text-anchor', 'middle')
      .attr('dy', 45)
      .text(d => d.current_slo !== undefined ? `${d.current_slo.toFixed(2)}%` : '')
      .style('font-size', '11px')
      .style('fill', d => d.current_slo !== undefined && d.slo_target !== undefined && d.current_slo < d.slo_target ? '#ef4444' : '#22c55e')
      .style('font-weight', '600');

    // Error budget
    node.append('text')
      .attr('class', 'node-budget')
      .attr('text-anchor', 'middle')
      .attr('dy', 60)
      .text(d => d.error_budget_remaining !== undefined ? `Budget: ${d.error_budget_remaining.toFixed(1)}%` : '')
      .style('font-size', '9px')
      .style('fill', '#64748b');

    // Incident/deployment badges
    node.append('text')
      .attr('class', 'node-badges')
      .attr('text-anchor', 'middle')
      .attr('dy', 75)
      .text(d => {
        const parts = [];
        if (d.incident_count_24h > 0) parts.push(`🚨 ${d.incident_count_24h}`);
        if (d.deployment_count_24h > 0) parts.push(`🚀 ${d.deployment_count_24h}`);
        return parts.join('  ');
      })
      .style('font-size', '9px');

    // Update positions on tick
    simulation.on('tick', () => {
      link
        .attr('x1', d => (d.source as ServiceNode).x!)
        .attr('y1', d => (d.source as ServiceNode).y!)
        .attr('x2', d => (d.target as ServiceNode).x!)
        .attr('y2', d => (d.target as ServiceNode).y!);

      node.attr('transform', d => `translate(${d.x},${d.y})`);
    });

    // Add arrowhead marker
    const defs = svg.select('defs').empty() ? svg.append('defs') : svg.select('defs');
    defs.selectAll('marker').remove();
    defs.append('marker')
      .attr('id', 'arrowhead')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 30)
      .attr('refY', 0)
      .attr('orient', 'auto')
      .attr('markerWidth', 8)
      .attr('markerHeight', 8)
      .append('path')
      .attr('d', 'M0,-5L10,0L0,5')
      .attr('fill', '#94a3b8');

    // Cleanup
    return () => {
      simulation.stop();
    };
  }, [data, highlightedNodes, width, height, onNodeClick]);

  // Zoom behavior
  useEffect(() => {
    if (!svgRef.current) return;

    const svg = d3.select(svgRef.current);
    const g = svg.select<SVGGElement>('g.graph-group');

    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 4])
      .on('zoom', (event) => {
        setTransform(event.transform);
        g.attr('transform', event.transform);
      });

    svg.call(zoom);

    return () => {
      svg.on('.zoom', null);
    };
  }, []);

  // Reset zoom
  const resetZoom = () => {
    if (!svgRef.current) return;
    const svg = d3.select(svgRef.current);
    svg.transition().duration(300).call(
      d3.zoom<SVGSVGElement, unknown>().transform,
      d3.zoomIdentity
    );
  };

  if (!data) {
    return (
      <div className="dependency-graph-loading">
        <div className="spinner"></div>
        <p>Loading dependency graph...</p>
      </div>
    );
  }

  return (
    <div className="dependency-graph-container">
      <div className="graph-header">
        <h3>Service Dependency Graph</h3>
        <div className="graph-controls">
          <button onClick={resetZoom} className="btn btn-secondary" title="Reset zoom">
            🔍 Reset View
          </button>
          <span className="node-count">{data.nodes.length} services, {data.edges.length} dependencies</span>
        </div>
      </div>
      <div className="graph-legend">
        <div className="legend-item">
          <span className="legend-color" style={{ backgroundColor: '#22c55e' }}></span>
          <span>Low Criticality</span>
        </div>
        <div className="legend-item">
          <span className="legend-color" style={{ backgroundColor: '#f59e0b' }}></span>
          <span>Medium Criticality</span>
        </div>
        <div className="legend-item">
          <span className="legend-color" style={{ backgroundColor: '#ef4444' }}></span>
          <span>High Criticality</span>
        </div>
        <div className="legend-item">
          <span className="legend-color" style={{ backgroundColor: '#f59e0b', border: '2px solid #f59e0b' }}></span>
          <span>Highlighted</span>
        </div>
        <div className="legend-item">
          <svg width="20" height="10"><line x1="0" y1="5" x2="20" y2="5" stroke="#94a3b8" strokeWidth="1.5" markerEnd="url(#arrowhead)" /></svg>
          <span>Depends On</span>
        </div>
        <div className="legend-item">
          <svg width="20" height="10"><line x1="0" y1="5" x2="20" y2="5" stroke="#ef4444" strokeWidth="3" markerEnd="url(#arrowhead)" /></svg>
          <span>High Error Rate</span>
        </div>
      </div>
      <svg
        ref={svgRef}
        width={width}
        height={height}
        className="dependency-graph-svg"
        style={{ transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.k})`, transformOrigin: '0 0' }}
      >
        <g className="graph-group" />
      </svg>
      {selectedNode && (
        <div className="node-detail-panel">
          <h4>{selectedNode.name}</h4>
          <p>Namespace: {selectedNode.namespace || 'N/A'}</p>
          <p>Criticality: {selectedNode.criticality}</p>
          {selectedNode.slo_target && selectedNode.current_slo !== undefined && (
            <p>SLO: {selectedNode.current_slo.toFixed(2)}% / {selectedNode.slo_target}%</p>
          )}
          {selectedNode.error_budget_remaining !== undefined && (
            <p>Error Budget: {selectedNode.error_budget_remaining.toFixed(1)}%</p>
          )}
          <p>Incidents (24h): {selectedNode.incident_count_24h}</p>
          <p>Deployments (24h): {selectedNode.deployment_count_24h}</p>
          <button onClick={() => setSelectedNode(null)} className="btn btn-secondary">Close</button>
        </div>
      )}
    </div>
  );
};

// Drag behavior
function drag(simulation: d3.Simulation<ServiceNode, DependencyEdge>) {
  return d3.drag<SVGGElement, ServiceNode>()
    .on('start', (event, d) => {
      if (!event.active) simulation.alphaTarget(0.3).restart();
      d.fx = d.x;
      d.fy = d.y;
    })
    .on('drag', (event, d) => {
      d.fx = event.x;
      d.fy = event.y;
    })
    .on('end', (event, d) => {
      if (!event.active) simulation.alphaTarget(0);
      d.fx = null;
      d.fy = null;
    });
}

function getCriticalityColor(criticality: string): string {
  switch (criticality.toLowerCase()) {
    case 'high':
    case 'critical':
      return '#ef4444';
    case 'medium':
      return '#f59e0b';
    case 'low':
      return '#22c55e';
    default:
      return '#64748b';
  }
}

export default DependencyGraph;