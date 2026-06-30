import { useState, useCallback } from 'react';
import DependencyGraph from '../components/DependencyGraph';
import { useDependencyGraph, useBlastRadius, useSourceUrls, type ServiceNode } from '../api';

const Dependencies: React.FC = () => {
  const { data: graphData, isLoading } = useDependencyGraph();
  const { data: sourceUrlsData } = useSourceUrls();
  const sourceUrls = sourceUrlsData?.sources ?? {};
  const [selectedNode, setSelectedNode] = useState<ServiceNode | null>(null);
  const [highlightedNodes, setHighlightedNodes] = useState<string[]>([]);

  const { data: blastRadius } = useBlastRadius(
    selectedNode?.name ?? '',
    selectedNode?.namespace,
  );

  const handleNodeClick = useCallback((node: ServiceNode) => {
    setSelectedNode(node);
    setHighlightedNodes([node.id]);
  }, []);

  return (
    <div className="dashboard-page">
      <div className="page-header">
        <div className="header-content">
          <h1 className="page-title">Service Dependencies</h1>
          <p className="page-subtitle">Interactive topology map of service relationships and blast radius</p>
        </div>
      </div>

      <section className="dashboard-section" aria-labelledby="graph-title">
        <DependencyGraph
          data={graphData ?? undefined}
          onNodeClick={handleNodeClick}
          highlightedNodes={highlightedNodes}
          width={1200}
          height={600}
          isLoading={isLoading}
          sourceUrls={sourceUrls}
        />
      </section>

      {selectedNode && blastRadius && (
        <section className="dashboard-section" aria-labelledby="blast-radius-title">
          <div className="section-header">
            <h2 className="section-title">Blast Radius: {selectedNode.name}</h2>
            <p className="section-description">
              {blastRadius.total_affected} services affected within {blastRadius.hop_count} hops
            </p>
          </div>
          <div style={{ padding: 'var(--space-4) var(--space-6) var(--space-6)' }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-2)' }}>
              {blastRadius.affected_services.map((svc) => (
                <span key={svc} className="criticality-badge" style={{ background: 'var(--color-info-bg)', color: 'var(--color-info-text)', border: '1px solid var(--color-info-border)' }}>
                  {svc}
                </span>
              ))}
              {blastRadius.affected_services.length === 0 && (
                <p style={{ color: 'var(--color-text-tertiary)', margin: 0 }}>No downstream services affected</p>
              )}
            </div>
          </div>
        </section>
      )}
    </div>
  );
};

export default Dependencies;
