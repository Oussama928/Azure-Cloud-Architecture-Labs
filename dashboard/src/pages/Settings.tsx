import { useState, useEffect } from 'react';
import { useTheme } from '../context/ThemeContext';
import { useToast } from '../components/Toast';
import { useHealth, useReadiness, useSourceUrls, useUpdateSourceUrls, useApiKey, useRotateApiKey, useAuthUser, useUpdateMe, useSourceConfigs, useUpdateGithubSource, useTestGithub, useUpdateNativeSource, useDeleteNativeSource, useSourceHealthHistory } from '../api';
import NativeConnectorForm from '../components/NativeConnectorForm';

const SOURCE_LABELS: Record<string, string> = {
  github: 'GitHub',
  gitlab: 'GitLab',
  terraform: 'Terraform',
  kubernetes: 'Kubernetes',
  argocd: 'ArgoCD',
  azure_resource_graph: 'Azure Resource Graph',
  jenkins: 'Jenkins',
};

const Settings: React.FC = () => {
  const { theme, setTheme } = useTheme();
  const { data: health } = useHealth();
  const { data: readiness } = useReadiness();
  const { data: sourceUrls } = useSourceUrls();
  const updateSourceUrls = useUpdateSourceUrls();
  const { data: sourceConfigs } = useSourceConfigs();
  const { data: healthHistory } = useSourceHealthHistory();
  const updateGithub = useUpdateGithubSource();
  const testGithub = useTestGithub();
  const { data: apiKeyData } = useApiKey();
  const rotateApiKey = useRotateApiKey();
  const authUser = useAuthUser();
  const updateMe = useUpdateMe();
  const toast = useToast();

  const [edits, setEdits] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState(false);
  const [name, setName] = useState(authUser?.name ?? '');
  const [nameSaving, setNameSaving] = useState(false);

  const [ghToken, setGhToken] = useState('');
  const [ghRepos, setGhRepos] = useState('');
  const [ghOrg, setGhOrg] = useState('');
  const [ghSecret, setGhSecret] = useState('');
  const [ghTestMsg, setGhTestMsg] = useState<string | null>(null);
  const [ghTestOk, setGhTestOk] = useState(false);

  const githubConfig = sourceConfigs?.sources?.github;

  useEffect(() => {
    if (githubConfig) {
      if (githubConfig.repositories?.length) {
        setGhRepos(githubConfig.repositories.join(', '));
      }
      if (githubConfig.organizations?.length) {
        setGhOrg(githubConfig.organizations.join(', '));
      }
    }
  }, [githubConfig]);

  useEffect(() => {
    setName(authUser?.name ?? '');
  }, [authUser?.name]);

  useEffect(() => {
    if (sourceUrls?.sources) {
      setEdits({ ...sourceUrls.sources });
    }
  }, [sourceUrls]);

  const handleTestGithub = async (e: React.MouseEvent) => {
    e.preventDefault();
    const token = ghToken.trim();
    if (!token) {
      setGhTestOk(false);
      setGhTestMsg('Enter a token to test.');
      return;
    }
    setGhTestMsg(null);
    try {
      const res = await testGithub.mutateAsync({ token, repo: ghRepos.split(',')[0]?.trim() || undefined });
      setGhTestOk(!!res.ok);
      if (res.ok) {
        setGhTestMsg(`Connected as @${res.username}${res.repo_check ? ` · repo ${res.repo_check}` : ''}`);
      } else {
        setGhTestMsg(res.error || 'Connection failed');
      }
    } catch {
      setGhTestOk(false);
      setGhTestMsg('Failed to reach the test endpoint');
    }
  };

  const handleSaveGithub = async (e: React.MouseEvent) => {
    e.preventDefault();
    const token = ghToken.trim();
    if (!token) {
      toast.error('A GitHub token is required to connect.');
      return;
    }
    try {
      await updateGithub.mutateAsync({
        token,
        repositories: ghRepos.split(',').map((s) => s.trim()).filter(Boolean),
        organizations: ghOrg.split(',').map((s) => s.trim()).filter(Boolean),
        webhook_secret: ghSecret.trim(),
      });
      toast.success('GitHub source connected');
      setGhToken('');
      setGhSecret('');
    } catch {
      toast.error('Failed to save the GitHub source');
    }
  };

  const handleSaveName = async () => {
    const trimmed = name.trim();
    if (!trimmed || trimmed === authUser?.name) return;
    try {
      setNameSaving(true);
      await updateMe.mutateAsync(trimmed);
      toast.success('Name updated');
    } catch {
      toast.error('Failed to update name');
    } finally {
      setNameSaving(false);
    }
  };

  const handleSave = async () => {
    try {
      await updateSourceUrls.mutateAsync(edits);
      setSaved(true);
      toast.success('Source URLs saved');
      setTimeout(() => setSaved(false), 2000);
    } catch {
      toast.error('Failed to save source URLs');
    }
  };

  const hasChanges = JSON.stringify(edits) !== JSON.stringify(sourceUrls?.sources ?? {});

  return (
    <div className="dashboard-page">
      <div className="page-header">
        <div className="header-content">
          <h1 className="page-title">Settings</h1>
          <p className="page-subtitle">Platform configuration and system health</p>
        </div>
      </div>

      <section className="dashboard-section" aria-labelledby="account-title">
        <div className="section-header">
          <h2 className="section-title" id="account-title">Account</h2>
        </div>
        <div style={{ padding: 'var(--space-4) var(--space-6) var(--space-6)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: 'var(--space-3) 0' }}>
            <div>
              <div style={{ fontSize: 'var(--text-sm)', fontWeight: 'var(--font-weight-semibold)', color: 'var(--color-text-primary)' }}>Email</div>
              <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)' }}>{authUser?.email || '—'}</div>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', padding: 'var(--space-3) 0' }}>
            <div style={{ minWidth: '160px' }}>
              <div style={{ fontSize: 'var(--text-sm)', fontWeight: 'var(--font-weight-semibold)', color: 'var(--color-text-primary)' }}>Display name</div>
              <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)' }}>Shown in incident &amp; deployment attribution</div>
            </div>
            <input
              className="input"
              type="text"
              maxLength={64}
              value={name}
              onChange={(e) => setName(e.target.value)}
              style={{ flex: 1, maxWidth: '320px' }}
              aria-label="Display name"
            />
            <button
              className="btn btn-primary"
              onClick={handleSaveName}
              disabled={!name.trim() || name.trim() === authUser?.name || updateMe.isPending}
            >
              {updateMe.isPending ? 'Saving...' : 'Save'}
            </button>
          </div>
        </div>
      </section>

      <section className="dashboard-section" aria-labelledby="appearance-title">
        <div className="section-header">
          <h2 className="section-title" id="appearance-title">Appearance</h2>
        </div>
        <div style={{ padding: 'var(--space-4) var(--space-6) var(--space-6)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: 'var(--space-3) 0' }}>
            <div>
              <div style={{ fontSize: 'var(--text-sm)', fontWeight: 'var(--font-weight-semibold)', color: 'var(--color-text-primary)' }}>Theme</div>
              <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)' }}>Choose between light and dark mode</div>
            </div>
            <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
              {(['light', 'dark'] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setTheme(t)}
                  style={{
                    padding: 'var(--space-2) var(--space-4)',
                    borderRadius: 'var(--radius-md)',
                    border: `1px solid ${theme === t ? 'var(--color-brand-primary)' : 'var(--color-border-primary)'}`,
                    background: theme === t ? 'var(--color-info-bg)' : 'var(--color-bg-secondary)',
                    color: theme === t ? 'var(--color-brand-primary)' : 'var(--color-text-tertiary)',
                    cursor: 'pointer',
                    fontSize: 'var(--text-sm)',
                    fontWeight: 'var(--font-weight-medium)',
                    textTransform: 'capitalize',
                  }}
                  aria-pressed={theme === t}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="dashboard-section" aria-labelledby="source-integrations-title">
        <div className="section-header">
          <h2 className="section-title" id="source-integrations-title">Source Integrations</h2>
          <p style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)', margin: 0 }}>
            Configure base URLs for the external systems that produce change events. These appear as clickable links
            on the Deployments page.
          </p>
        </div>
        <div style={{ padding: 'var(--space-4) var(--space-6) var(--space-6)' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
            {Object.entries(SOURCE_LABELS).map(([key, label]) => (
              <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
                <label style={{ minWidth: '160px', fontSize: 'var(--text-sm)', fontWeight: 'var(--font-weight-medium)', color: 'var(--color-text-secondary)' }}>
                  {label}
                </label>
                <input
                  className="input"
                  type="url"
                  placeholder={`https://${key}.example.com`}
                  value={edits[key] ?? ''}
                  onChange={(e) => setEdits(prev => ({ ...prev, [key]: e.target.value }))}
                  style={{ flex: 1 }}
                />
                <span style={{ fontSize: 'var(--text-xs)', color: sourceConfigs?.sources?.[key]?.status === 'connected' ? 'var(--color-success)' : 'var(--color-text-quaternary)' }}>
                  {sourceConfigs?.sources?.[key]?.status ?? 'not connected'}
                </span>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 'var(--space-4)', display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
            <button className="btn btn-primary" onClick={handleSave} disabled={!hasChanges || updateSourceUrls.isPending}>
              {updateSourceUrls.isPending ? 'Saving...' : 'Save'}
            </button>
            {saved && <span style={{ fontSize: 'var(--text-sm)', color: 'var(--color-success)' }}>Saved!</span>}
          </div>
          {healthHistory?.history?.length ? (
            <div style={{ marginTop: 'var(--space-4)', borderTop: '1px solid var(--color-border-primary)', paddingTop: 'var(--space-3)' }}>
              <div style={{ fontSize: 'var(--text-xs)', fontWeight: 'var(--font-weight-semibold)', color: 'var(--color-text-secondary)', marginBottom: 'var(--space-2)' }}>
                Integration health (recent)
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
                {healthHistory.history.slice(-10).reverse().map((s, i) => (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: 'var(--text-xs)' }}>
                    <span
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: '50%',
                        flexShrink: 0,
                        background: s.state === 'connected' ? 'var(--color-success)' : 'var(--color-error)',
                      }}
                    />
                    <span style={{ color: 'var(--color-text-secondary)', minWidth: 90 }}>
                      {new Date(s.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                    <span style={{ color: 'var(--color-text-tertiary)' }}>{s.state}</span>
                    <span style={{ color: 'var(--color-text-quaternary)' }}>{s.events > 0 ? `${s.events} events` : ''}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </section>

      <section className="dashboard-section" aria-labelledby="github-connect-title">
        <div className="section-header">
          <h2 className="section-title" id="github-connect-title">Connect a GitHub source</h2>
          {githubConfig?.has_token ? (
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
              connected{githubConfig.username ? ` as @${githubConfig.username}` : ''}
            </span>
          ) : (
            <span
              style={{
                fontSize: '10px',
                padding: '1px 8px',
                borderRadius: 'var(--radius-full)',
                background: 'var(--color-bg-tertiary)',
                border: '1px solid var(--color-border-primary)',
                color: 'var(--color-text-quaternary)',
                whiteSpace: 'nowrap',
              }}
            >
              not connected
            </span>
          )}
        </div>
        <div style={{ padding: 'var(--space-4) var(--space-6) var(--space-6)' }}>
          <p style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)', marginTop: 0 }}>
            Add a GitHub source so ChangeTrace ingests your real commits, pull requests and releases from GitHub.
            Supply a personal access token with <code>repo</code> scope, then save. Events flow into the pipeline
            tagged to your workspace.
          </p>
          {githubConfig?.repositories?.length ? (
            <p style={{ fontSize: 'var(--text-xs)', marginTop: 0, color: 'var(--color-brand-primary)' }}>
              Collecting from: {githubConfig.repositories.join(', ')}
            </p>
          ) : null}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
              <label style={{ minWidth: '160px', fontSize: 'var(--text-sm)', fontWeight: 'var(--font-weight-medium)', color: 'var(--color-text-secondary)' }}>
                Token
              </label>
              <input
                className="input"
                type="password"
                autoComplete="off"
                placeholder="ghp_... (personal access token, repo scope)"
                value={ghToken}
                onChange={(e) => setGhToken(e.target.value)}
                style={{ flex: 1 }}
              />
              <button className="btn btn-secondary" onClick={handleTestGithub} disabled={testGithub.isPending}>
                {testGithub.isPending ? 'Testing...' : 'Test'}
              </button>
            </div>
            {ghTestMsg && (
              <p style={{ fontSize: 'var(--text-xs)', margin: 0, color: ghTestOk ? 'var(--color-success)' : 'var(--color-error)' }}>
                {ghTestMsg}
              </p>
            )}
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
              <label style={{ minWidth: '160px', fontSize: 'var(--text-sm)', fontWeight: 'var(--font-weight-medium)', color: 'var(--color-text-secondary)' }}>
                Repositories
              </label>
              <input
                className="input"
                type="text"
                placeholder="owner/repo (comma-separated, e.g. acme/backend, acme/payments)"
                value={ghRepos}
                onChange={(e) => setGhRepos(e.target.value)}
                style={{ flex: 1 }}
              />
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
              <label style={{ minWidth: '160px', fontSize: 'var(--text-sm)', fontWeight: 'var(--font-weight-medium)', color: 'var(--color-text-secondary)' }}>
                Organizations
              </label>
              <input
                className="input"
                type="text"
                placeholder="acme (optional, comma-separated)"
                value={ghOrg}
                onChange={(e) => setGhOrg(e.target.value)}
                style={{ flex: 1 }}
              />
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
              <label style={{ minWidth: '160px', fontSize: 'var(--text-sm)', fontWeight: 'var(--font-weight-medium)', color: 'var(--color-text-secondary)' }}>
                Webhook secret
              </label>
              <input
                className="input"
                type="password"
                autoComplete="off"
                placeholder="Optional webhook secret"
                value={ghSecret}
                onChange={(e) => setGhSecret(e.target.value)}
                style={{ flex: 1 }}
              />
            </div>
          </div>
          <div style={{ marginTop: 'var(--space-4)', display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
            <button className="btn btn-primary" onClick={handleSaveGithub} disabled={updateGithub.isPending || !ghToken.trim()}>
              {updateGithub.isPending ? 'Connecting...' : 'Connect GitHub'}
            </button>
          </div>
        </div>
      </section>

      <NativeConnectorForm
        kind="gitlab"
        label="GitLab"
        config={sourceConfigs?.sources?.gitlab}
        placeholder="https://gitlab.com"
        fields={[
          { key: 'username', label: 'Username', placeholder: 'Optional account username' },
          { key: 'webhook_secret', label: 'Webhook secret', placeholder: 'Optional webhook secret token', type: 'password' },
          { key: 'groups', label: 'Groups', placeholder: 'my-group (comma-separated)', type: 'list' },
          { key: 'projects', label: 'Projects', placeholder: 'my-group/my-project (comma-separated)', type: 'list' },
          { key: 'branches', label: 'Branches', placeholder: 'main, master, production', type: 'list' },
        ]}
      />

      <NativeConnectorForm
        kind="jenkins"
        label="Jenkins"
        config={sourceConfigs?.sources?.jenkins}
        placeholder="https://jenkins.example.com"
        fields={[
          { key: 'username', label: 'Username', placeholder: 'Jenkins username' },
          { key: 'jobs', label: 'Jobs', placeholder: 'job names (comma-separated, optional)', type: 'list' },
          { key: 'job_folders', label: 'Folders', placeholder: 'folder paths (comma-separated, optional)', type: 'list' },
        ]}
      />

      <NativeConnectorForm
        kind="argocd"
        label="ArgoCD"
        config={sourceConfigs?.sources?.argocd}
        placeholder="https://argocd.example.com"
        fields={[
          { key: 'username', label: 'Username', placeholder: 'ArgoCD username' },
          { key: 'password', label: 'Password', placeholder: 'Optional password (if no token)', type: 'password' },
          { key: 'applications', label: 'Applications', placeholder: 'app names (comma-separated, optional)', type: 'list' },
          { key: 'app_projects', label: 'Projects', placeholder: 'app project names (comma-separated, optional)', type: 'list' },
        ]}
      />

      <NativeConnectorForm
        kind="terraform"
        label="Terraform Cloud"
        config={sourceConfigs?.sources?.terraform}
        placeholder="https://app.terraform.io"
        fields={[
          { key: 'organization', label: 'Organization', placeholder: 'Your TFC organization name' },
          { key: 'workspaces', label: 'Workspaces', placeholder: 'workspace names (comma-separated, optional)', type: 'list' },
        ]}
      />

      <section className="dashboard-section" aria-labelledby="api-key-title">
        <div className="section-header">
          <h2 className="section-title" id="api-key-title">API Key</h2>
          <p style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)', margin: 0 }}>
            Authenticate programmatic ingestion to ChangeTrace — both change events and your application&apos;s traces.
          </p>
        </div>
        <div style={{ padding: 'var(--space-4) var(--space-6) var(--space-6)' }}>
          {apiKeyData?.api_key ? (
            <div>
              <div
                className="code-block"
                style={{
                  fontFamily: 'var(--font-mono, monospace)',
                  fontSize: 'var(--text-sm)',
                  background: 'var(--color-bg-secondary)',
                  padding: 'var(--space-3) var(--space-4)',
                  borderRadius: 'var(--radius-md)',
                  overflowX: 'auto',
                  wordBreak: 'break-all',
                  userSelect: 'all',
                }}
              >
                {apiKeyData.api_key}
              </div>
              <p style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)', marginTop: 'var(--space-3)', marginBottom: 0 }}>
                Send it as <code>Authorization: Bearer &lt;api_key&gt;</code> when POSTing change events to the collector
                <code> /ingest</code>, or when exporting your application&apos;s OpenTelemetry traces to <code>/v1/traces</code>.
                Treat it like a password.
              </p>
              <div
                className="code-block"
                style={{
                  fontFamily: 'var(--font-mono, monospace)',
                  fontSize: 'var(--text-xs)',
                  background: 'var(--color-bg-secondary)',
                  padding: 'var(--space-3) var(--space-4)',
                  borderRadius: 'var(--radius-md)',
                  overflowX: 'auto',
                  marginTop: 'var(--space-3)',
                  marginBottom: 0,
                }}
              >
                {`OTLPSpanExporter(\n  endpoint="https://<changetrace>/v1/traces",\n  headers={"Authorization": "Bearer ${apiKeyData.api_key}"}\n)`}
              </div>
              <button
                className="btn btn-secondary"
                style={{ marginTop: 'var(--space-3)' }}
                onClick={() => rotateApiKey.mutate()}
                disabled={rotateApiKey.isPending}
              >
                {rotateApiKey.isPending ? 'Rotating...' : 'Rotate API key'}
              </button>
            </div>
          ) : (
            <p style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)', margin: 0 }}>Loading API key...</p>
          )}
        </div>
      </section>

      <section className="dashboard-section" aria-labelledby="health-title">
        <div className="section-header">
          <h2 className="section-title" id="health-title">System Health</h2>
        </div>
        <div style={{ padding: 'var(--space-4) var(--space-6) var(--space-6)' }}>
          <div className="summary-stats-bar" style={{ border: 'none', boxShadow: 'none', padding: 0, gap: 'var(--space-4)' }}>
            <div className="summary-stat">
              <div className="summary-stat-content">
                <span className="summary-stat-value" style={{ color: health?.status === 'healthy' ? 'var(--color-success)' : 'var(--color-error)' }}>
                  {health?.status ?? 'Unknown'}
                </span>
                <span className="summary-stat-label">Health Status</span>
              </div>
            </div>
            <div className="summary-stat">
              <div className="summary-stat-content">
                <span className="summary-stat-value" style={{ color: readiness?.status === 'ready' ? 'var(--color-success)' : 'var(--color-warning)' }}>
                  {readiness?.status ?? 'Unknown'}
                </span>
                <span className="summary-stat-label">Readiness</span>
              </div>
            </div>
          </div>
          {health && (
            <div style={{ marginTop: 'var(--space-4)', fontSize: 'var(--text-xs)', color: 'var(--color-text-quaternary)' }}>
              <div>Service: {health.service}</div>
              <div>Version: {health.version}</div>
              <div>Last checked: {new Date(health.timestamp).toLocaleString()}</div>
            </div>
          )}
        </div>
      </section>
    </div>
  );
};

export default Settings;
