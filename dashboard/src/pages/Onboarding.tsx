import React, { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  useSourceConfigs,
  useUpdateNativeSource,
  useDeleteNativeSource,
  useTestNativeSource,
  useUpdateGithubSource,
  useTestGithub,
  useAuthUser,
  useApiKey,
} from '../api';
import { useToast } from '../components/Toast';

interface ConnectorDef {
  kind: string;
  label: string;
  icon: string;
  blurb: string;
  placeholder: string;
  requiresBaseUrl: boolean;
  fields: Array<{
    key: string;
    label: string;
    placeholder: string;
    type?: 'text' | 'password' | 'list';
  }>;
}

const CONNECTORS: ConnectorDef[] = [
  {
    kind: 'github',
    label: 'GitHub',
    icon: 'GH',
    blurb: 'Commits, pull requests & releases from GitHub.',
    placeholder: 'https://github.com',
    requiresBaseUrl: false,
    fields: [
      { key: 'token', label: 'Personal access token', placeholder: 'ghp_... (repo scope)', type: 'password' },
      { key: 'repositories', label: 'Repositories', placeholder: 'owner/repo, owner/repo2', type: 'list' },
      { key: 'organizations', label: 'Organizations', placeholder: 'acme (optional)', type: 'list' },
    ],
  },
  {
    kind: 'gitlab',
    label: 'GitLab',
    icon: 'GL',
    blurb: 'Commits, MRs, releases & pipelines from GitLab.',
    placeholder: 'https://gitlab.com',
    requiresBaseUrl: true,
    fields: [
      { key: 'base_url', label: 'Base URL', placeholder: 'https://gitlab.com', type: 'text' },
      { key: 'token', label: 'Access token', placeholder: 'glpat-...', type: 'password' },
      { key: 'username', label: 'Username', placeholder: 'Optional' },
      { key: 'groups', label: 'Groups', placeholder: 'my-group (comma-separated)', type: 'list' },
      { key: 'projects', label: 'Projects', placeholder: 'my-group/my-project (comma-separated)', type: 'list' },
    ],
  },
  {
    kind: 'jenkins',
    label: 'Jenkins',
    icon: 'JK',
    blurb: 'Build jobs & pipeline runs from Jenkins CI.',
    placeholder: 'https://jenkins.example.com',
    requiresBaseUrl: true,
    fields: [
      { key: 'base_url', label: 'Base URL', placeholder: 'https://jenkins.example.com', type: 'text' },
      { key: 'token', label: 'API token', placeholder: 'Jenkins API token', type: 'password' },
      { key: 'username', label: 'Username', placeholder: 'Jenkins user' },
      { key: 'jobs', label: 'Jobs', placeholder: 'my-job (comma-separated)', type: 'list' },
    ],
  },
  {
    kind: 'argocd',
    label: 'ArgoCD',
    icon: 'AC',
    blurb: 'Application syncs & rollouts from ArgoCD.',
    placeholder: 'https://argocd.example.com',
    requiresBaseUrl: true,
    fields: [
      { key: 'base_url', label: 'Base URL', placeholder: 'https://argocd.example.com', type: 'text' },
      { key: 'username', label: 'Username', placeholder: 'admin' },
      { key: 'password', label: 'Password / token', placeholder: 'ArgoCD password', type: 'password' },
      { key: 'applications', label: 'Applications', placeholder: 'app1, app2 (comma-separated)', type: 'list' },
    ],
  },
  {
    kind: 'terraform',
    label: 'Terraform Cloud',
    icon: 'TF',
    blurb: 'Plan & apply runs from Terraform Cloud.',
    placeholder: 'https://app.terraform.io',
    requiresBaseUrl: false,
    fields: [
      { key: 'token', label: 'API token', placeholder: 'TFE token', type: 'password' },
      { key: 'organization', label: 'Organization', placeholder: 'acme' },
      { key: 'workspaces', label: 'Workspaces', placeholder: 'prod, staging (comma-separated)', type: 'list' },
    ],
  },
];

const Onboarding: React.FC = () => {
  const navigate = useNavigate();
  const toast = useToast();
  const authUser = useAuthUser();
  const { data: sourceConfigs } = useSourceConfigs();
  const { data: apiKeyData } = useApiKey();

  const [selected, setSelected] = useState<string>('github');
  const [values, setValues] = useState<Record<string, string>>({});
  const [testState, setTestState] = useState<{ status: 'idle' | 'testing' | 'ok' | 'fail'; msg?: string }>({ status: 'idle' });
  const [showHelp, setShowHelp] = useState(false);

  const testNative = useTestNativeSource();
  const testGithub = useTestGithub();
  const updateNative = useUpdateNativeSource();
  const updateGithub = useUpdateGithubSource();
  const deleteNative = useDeleteNativeSource();

  const connector = useMemo(() => CONNECTORS.find((c) => c.kind === selected)!, [selected]);

  const connectedKinds = useMemo(() => {
    const kinds = Object.entries(sourceConfigs?.sources ?? {}).filter(([, c]) => c?.has_token || c?.status === 'connected').map(([k]) => k);
    return new Set(kinds);
  }, [sourceConfigs]);

  const anyConnected = connectedKinds.size > 0;

  const field = (key: string) => (values[key] ?? '').trim();
  const requiredReady = (def: ConnectorDef) => {
    if (def.requiresBaseUrl && !field('base_url')) return false;
    if (!field('token') && !field('password')) return false;
    return true;
  };

  const buildTestPayload = (def: ConnectorDef) => {
    const payload: Record<string, unknown> = { base_url: field('base_url') || undefined, token: field('token') || field('password') };
    if (def.kind === 'jenkins' || def.kind === 'argocd') payload.username = field('username');
    if (def.kind === 'argocd') payload.password = field('password');
    if (def.kind === 'terraform') payload.organization = field('organization');
    return payload;
  };

  const buildSavePayload = (def: ConnectorDef) => {
    const payload: Record<string, unknown> = {};
    for (const f of def.fields) {
      if (f.type === 'list') {
        const list = field(f.key).split(',').map((s) => s.trim()).filter(Boolean);
        payload[f.key] = list;
      } else {
        payload[f.key] = field(f.key);
      }
    }
    if (def.kind === 'terraform') payload.base_url = field('base_url');
    return payload;
  };

  const handleTest = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!requiredReady(connector)) {
      toast.error('Fill in the required fields first.');
      return;
    }
    setTestState({ status: 'testing' });
    try {
      if (connector.kind === 'github') {
        const res = await testGithub.mutateAsync({ token: field('token') });
        if (res.ok) {
          setTestState({ status: 'ok', msg: `Connected as @${res.username}` });
        } else {
          setTestState({ status: 'fail', msg: res.error || 'GitHub rejected the token' });
        }
      } else {
        const res = await testNative.mutateAsync({ kind: connector.kind, cfg: buildTestPayload(connector) });
        if (res.ok) {
          const detail = res.username ? ` as ${res.username}` : res.organization ? ` · ${res.organization}` : res.applications !== undefined ? ` · ${res.applications} apps` : '';
          setTestState({ status: 'ok', msg: `${connector.label} is alive${detail}` });
        } else {
          setTestState({ status: 'fail', msg: res.error || `${connector.label} is not reachable` });
        }
      }
    } catch {
      setTestState({ status: 'fail', msg: 'Could not run connectivity test' });
    }
  };

  const handleSave = async () => {
    if (testState.status !== 'ok') {
      toast.error(`Test the ${connector.label} connection first — only reachable sources can be added.`);
      return;
    }
    try {
      if (connector.kind === 'github') {
        await updateGithub.mutateAsync({
          token: field('token'),
          repositories: field('repositories').split(',').map((s) => s.trim()).filter(Boolean),
          organizations: field('organizations').split(',').map((s) => s.trim()).filter(Boolean),
        });
      } else {
        await updateNative.mutateAsync({ kind: connector.kind, cfg: buildSavePayload(connector) });
      }
      toast.success(`${connector.label} connected`);
      setValues({});
      setTestState({ status: 'idle' });
    } catch {
      toast.error(`Failed to save the ${connector.label} source`);
    }
  };

  const handleDisconnect = async () => {
    try {
      if (connector.kind === 'github') {
        // GitHub has no delete endpoint; clear via empty token is not supported. Keep for others.
        toast.error('Use the Settings page to fully remove a GitHub source.');
        return;
      }
      await deleteNative.mutateAsync(connector.kind);
      toast.success(`${connector.label} disconnected`);
    } catch {
      toast.error(`Failed to disconnect ${connector.label}`);
    }
  };

  const setVal = (key: string, v: string) => {
    setValues((p) => ({ ...p, [key]: v }));
    if (testState.status !== 'idle') setTestState({ status: 'idle' });
  };

  return (
    <div className="dashboard-page" style={{ maxWidth: '960px' }}>
      <div className="page-header">
        <div className="header-content">
          <h1 className="page-title">Welcome to ChangeTrace</h1>
          <p className="page-subtitle">
            {anyConnected
              ? 'Connect another source, or head to your dashboard.'
              : `Let's connect your first source${authUser?.name ? `, ${authUser.name.split(' ')[0]}` : ''}. We only add sources that are actually reachable.`}
          </p>
        </div>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => setShowHelp(true)}
          aria-haspopup="dialog"
        >
          Help
        </button>
      </div>

      {showHelp && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="onboarding-help-title"
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 1000,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'rgba(0,0,0,0.5)',
            padding: 'var(--space-4)',
          }}
          onClick={() => setShowHelp(false)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              maxWidth: '560px',
              width: '100%',
              background: 'var(--color-bg-secondary)',
              borderRadius: 'var(--radius-lg)',
              border: '1px solid var(--color-border-primary)',
              boxShadow: '0 12px 40px rgba(0,0,0,0.25)',
            }}
          >
            <div className="section-header" style={{ padding: 'var(--space-4) var(--space-6)' }}>
              <h2 className="section-title" id="onboarding-help-title">How to connect your first source</h2>
              <button className="btn btn-ghost btn-sm" onClick={() => setShowHelp(false)} aria-label="Close help">
                Close
              </button>
            </div>
            <div style={{ padding: '0 var(--space-6) var(--space-5)' }}>
              <ol style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)', paddingLeft: 'var(--space-5)', fontSize: 'var(--text-sm)', color: 'var(--color-text-secondary)' }}>
                <li>
                  <strong style={{ color: 'var(--color-text-primary)' }}>Pick a source</strong> from the cards above
                  (GitHub, GitLab, Jenkins, ArgoCD, or Terraform Cloud).
                </li>
                <li>
                  <strong style={{ color: 'var(--color-text-primary)' }}>Enter your credentials</strong> — base URL,
                  token, and any optional filters like repositories, groups, or projects.
                </li>
                <li>
                  <strong style={{ color: 'var(--color-text-primary)' }}>Click “Test connection”</strong> — ChangeTrace
                  pings the source to confirm it’s reachable and your token works.
                </li>
                <li>
                  <strong style={{ color: 'var(--color-text-primary)' }}>If it’s alive, click “Add source”</strong> —
                  only reachable sources can be added.
                </li>
                <li>
                  <strong style={{ color: 'var(--color-text-primary)' }}>Watch your dashboard light up</strong> — the
                  collector starts polling and your changes appear on the graph, risk, and incidents pages within a
                  minute.
                </li>
              </ol>
              <p style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)', marginTop: 'var(--space-4)' }}>
                Tip: for GitHub, create a fine-grained or classic personal access token with <code>repo</code> scope.
                You only need read access — the token is stored securely in Key Vault.
              </p>
            </div>
          </div>
        </div>
      )}

      <section className="dashboard-section" aria-labelledby="onboarding-connect-title">
        <div className="section-header">
          <h2 className="section-title" id="onboarding-connect-title">Choose a source</h2>
          {anyConnected && (
            <span
              style={{
                fontSize: '10px',
                padding: '1px 8px',
                borderRadius: 'var(--radius-full)',
                background: 'var(--color-success)18',
                border: '1px solid var(--color-success)',
                color: 'var(--color-success)',
                whiteSpace: 'nowrap',
              }}
            >
              {connectedKinds.size} connected
            </span>
          )}
        </div>

        <div style={{ padding: 'var(--space-4) var(--space-6) var(--space-6)' }}>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))',
              gap: 'var(--space-3)',
              marginBottom: 'var(--space-5)',
            }}
          >
            {CONNECTORS.map((c) => {
              const connected = connectedKinds.has(c.kind);
              const active = selected === c.kind;
              return (
                <button
                  key={c.kind}
                  type="button"
                  onClick={() => { setSelected(c.kind); setValues({}); setTestState({ status: 'idle' }); }}
                  aria-pressed={active}
                  style={{
                    textAlign: 'left',
                    padding: 'var(--space-3) var(--space-4)',
                    borderRadius: 'var(--radius-lg)',
                    cursor: 'pointer',
                    border: `1px solid ${active ? 'var(--color-brand-primary)' : 'var(--color-border-primary)'}`,
                    background: active ? 'var(--color-info-bg)' : 'var(--color-bg-secondary)',
                    color: active ? 'var(--color-brand-primary)' : 'var(--color-text-primary)',
                    boxShadow: active ? '0 0 0 1px var(--color-brand-primary)' : 'none',
                  }}
                >
                  <div style={{ fontSize: 'var(--text-2xl)', lineHeight: 1 }}>{c.icon}</div>
                  <div style={{ fontWeight: 'var(--font-weight-semibold)', marginTop: 'var(--space-2)' }}>{c.label}</div>
                  <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)', marginTop: 2 }}>{c.blurb}</div>
                  {connected && (
                    <div style={{ fontSize: '10px', color: 'var(--color-success)', marginTop: 'var(--space-2)' }}>● connected</div>
                  )}
                </button>
              );
            })}
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
            {connector.fields.map((f) => (
              <div key={f.key} style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
                <label
                  style={{
                    minWidth: '180px',
                    fontSize: 'var(--text-sm)',
                    fontWeight: 'var(--font-weight-medium)',
                    color: 'var(--color-text-secondary)',
                  }}
                >
                  {f.label}
                </label>
                <input
                  className="input"
                  type={f.type === 'password' ? 'password' : f.type === 'list' ? 'text' : 'text'}
                  autoComplete="off"
                  placeholder={f.placeholder}
                  value={values[f.key] ?? ''}
                  onChange={(e) => setVal(f.key, e.target.value)}
                  style={{ flex: 1 }}
                />
              </div>
            ))}
          </div>

          <div style={{ marginTop: 'var(--space-4)', display: 'flex', alignItems: 'center', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
            <button className="btn btn-secondary" onClick={handleTest} disabled={testState.status === 'testing'}>
              {testState.status === 'testing' ? 'Testing…' : 'Test connection'}
            </button>
            <button className="btn btn-primary" onClick={handleSave} disabled={updateNative.isPending || updateGithub.isPending}>
              {connectedKinds.has(connector.kind) ? 'Update source' : 'Add source'}
            </button>
            {connectedKinds.has(connector.kind) && (
              <button className="btn btn-ghost" onClick={handleDisconnect} disabled={deleteNative.isPending}>
                Disconnect
              </button>
            )}
            {anyConnected && (
              <button className="btn btn-ghost" onClick={() => navigate('/')}>
                Skip for now →
              </button>
            )}
          </div>

          {testState.status === 'ok' && (
            <p style={{ fontSize: 'var(--text-sm)', color: 'var(--color-success)', margin: 'var(--space-3) 0 0' }}>
              ✓ {testState.msg}
            </p>
          )}
          {testState.status === 'fail' && (
            <p style={{ fontSize: 'var(--text-sm)', color: 'var(--color-error)', margin: 'var(--space-3) 0 0' }}>
              ✗ {testState.msg}
            </p>
          )}
          {testState.status === 'idle' && (
            <p style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)', margin: 'var(--space-3) 0 0' }}>
              We verify the {connector.label} connection before saving, so you only add sources that are alive.
            </p>
          )}
        </div>
      </section>

      <section className="dashboard-section" aria-labelledby="onboarding-app-title">
        <div className="section-header">
          <h2 className="section-title" id="onboarding-app-title">Connect your application</h2>
          <p style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)', margin: 0 }}>
            Wire your own app&apos;s OpenTelemetry traces into your ChangeTrace graph.
          </p>
        </div>
        <div style={{ padding: 'var(--space-4) var(--space-6) var(--space-6)' }}>
          <ol style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)', paddingLeft: 'var(--space-5)', fontSize: 'var(--text-sm)', color: 'var(--color-text-secondary)' }}>
            <li>
              <strong style={{ color: 'var(--color-text-primary)' }}>Instrument your app</strong> with the OpenTelemetry
              SDK and point your trace exporter at the ChangeTrace endpoint.
            </li>
            <li>
              <strong style={{ color: 'var(--color-text-primary)' }}>Authenticate with your API key</strong> — it tells
              ChangeTrace which tenant your traces belong to. Any service can connect this way.
            </li>
            <li>
              <strong style={{ color: 'var(--color-text-primary)' }}>Generate traffic</strong> and your services appear
              in your graph, ready for change and fault correlation.
            </li>
          </ol>
          {apiKeyData?.api_key ? (
            <div
              className="code-block"
              style={{
                fontFamily: 'var(--font-mono, monospace)',
                fontSize: 'var(--text-xs)',
                background: 'var(--color-bg-secondary)',
                padding: 'var(--space-3) var(--space-4)',
                borderRadius: 'var(--radius-md)',
                overflowX: 'auto',
                marginTop: 'var(--space-4)',
                marginBottom: 0,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
              }}
            >
              {`OTLPSpanExporter(\n  endpoint="https://<changetrace>/v1/traces",\n  headers={"Authorization": "Bearer ${apiKeyData.api_key}"}\n)`}
            </div>
          ) : (
            <p style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)', marginTop: 'var(--space-4)', marginBottom: 0 }}>
              Loading API key…
            </p>
          )}
        </div>
      </section>
    </div>
  );
};

export default Onboarding;
