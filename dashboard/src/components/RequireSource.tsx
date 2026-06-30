import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useSourceConfigs, useDependencyGraph } from '../api';

/** Blocks access until the tenant is wired (connected source or graph data); otherwise routes to /onboarding. */
const RequireSource: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const location = useLocation();
  const { data, isLoading, isError } = useSourceConfigs();
  const { data: graphData, isLoading: graphLoading } = useDependencyGraph();

  if (isLoading || graphLoading) {
    return (
      <div className="page-loading" role="status" aria-label="Checking sources">
        <div className="loading-spinner" aria-hidden="true"></div>
        <p>Setting up your workspace…</p>
      </div>
    );
  }

  const hasSource = !!data && Object.values(data.sources ?? {}).some(
    (c) => c?.has_token || c?.status === 'connected'
  );
  // A tenant that has wired an app via API key has graph nodes even with no source.
  const hasGraph = !!graphData && (graphData.nodes?.length ?? 0) > 0;
  const isWired = hasSource || hasGraph;

  if (!isWired) {
    return <Navigate to="/onboarding" state={{ from: location }} replace />;
  }

  return <>{children}</>;
};

export default RequireSource;
