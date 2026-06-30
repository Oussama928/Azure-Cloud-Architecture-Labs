import React, { useState } from 'react';
import type { SourceConfig } from '../api/client';
import { useUpdateNativeSource, useDeleteNativeSource } from '../api';
import { useToast } from '../components/Toast';

interface NativeConnectorFormProps {
  kind: string;
  label: string;
  config?: SourceConfig;
  placeholder: string;
  fields: Array<{
    key: string;
    label: string;
    placeholder: string;
    type?: 'text' | 'password' | 'list';
    listKey?: string;
  }>;
}

const NativeConnectorForm: React.FC<NativeConnectorFormProps> = ({ kind, label, config, placeholder, fields }) => {
  const updateNative = useUpdateNativeSource();
  const deleteNative = useDeleteNativeSource();
  const toast = useToast();

  const [values, setValues] = useState<Record<string, string>>({});
  const connected = !!config?.has_token;

  const getList = (key: string): string[] => {
    const v = config?.[key as keyof SourceConfig];
    return Array.isArray(v) ? (v as string[]) : [];
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    const baseUrl = (values.base_url ?? '').trim();
    const token = (values.token ?? '').trim();
    if (!baseUrl || !token) {
      toast.error(`${label} requires a base URL and token.`);
      return;
    }
    const payload: Record<string, unknown> = {
      base_url: baseUrl,
      token,
    };
    for (const f of fields) {
      if (f.key === 'base_url' || f.key === 'token') continue;
      const raw = values[f.key] ?? '';
      if (f.type === 'list') {
        payload[f.key] = raw.split(',').map((s) => s.trim()).filter(Boolean);
      } else if (f.key === 'webhook_secret' || f.key === 'password') {
        if (raw) payload[f.key] = raw;
      } else {
        payload[f.key] = raw;
      }
    }
    try {
      await updateNative.mutateAsync({ kind, cfg: payload });
      toast.success(`${label} connected`);
      setValues({});
    } catch {
      toast.error(`Failed to save the ${label} source`);
    }
  };

  const handleDelete = async () => {
    try {
      await deleteNative.mutateAsync(kind);
      toast.success(`${label} disconnected`);
    } catch {
      toast.error(`Failed to disconnect ${label}`);
    }
  };

  const initFromConfig = () => {
    const init: Record<string, string> = { base_url: config?.base_url ?? '' };
    for (const f of fields) {
      if (f.key === 'token' || f.key === 'webhook_secret') continue;
      if (f.type === 'list') {
        init[f.key] = getList(f.listKey ?? f.key).join(', ');
      } else {
        init[f.key] = (config?.[f.key as keyof SourceConfig] as string) ?? '';
      }
    }
    return init;
  };

  return (
    <section className="dashboard-section" aria-labelledby={`${kind}-connect-title`}>
      <div className="section-header">
        <h2 className="section-title" id={`${kind}-connect-title`}>Connect a {label} source</h2>
        {connected ? (
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
            connected
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
          Add a {label} source so ChangeTrace ingests real deployment events. Supply a base URL and an API token,
          then save. Events flow into the pipeline tagged to your workspace.
        </p>
        {config?.status && (
          <p style={{ fontSize: 'var(--text-xs)', margin: '0 0 var(--space-3)', color: config.status === 'connected' ? 'var(--color-success)' : 'var(--color-error)' }}>
            Status: {config.status}{config.last_error ? ` · ${config.last_error}` : ''}
          </p>
        )}
        <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
            <label style={{ minWidth: '160px', fontSize: 'var(--text-sm)', fontWeight: 'var(--font-weight-medium)', color: 'var(--color-text-secondary)' }}>
              Base URL
            </label>
            <input
              className="input"
              type="url"
              autoComplete="off"
              placeholder={placeholder}
              value={values.base_url ?? initFromConfig().base_url}
              onChange={(e) => setValues((p) => ({ ...p, base_url: e.target.value }))}
              style={{ flex: 1 }}
            />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
            <label style={{ minWidth: '160px', fontSize: 'var(--text-sm)', fontWeight: 'var(--font-weight-medium)', color: 'var(--color-text-secondary)' }}>
              Token
            </label>
            <input
              className="input"
              type="password"
              autoComplete="off"
              placeholder={connected ? '•••••••• (leave blank to keep existing)' : 'API token'}
              value={values.token ?? ''}
              onChange={(e) => setValues((p) => ({ ...p, token: e.target.value }))}
              style={{ flex: 1 }}
            />
          </div>
          {fields.filter((f) => f.key !== 'base_url' && f.key !== 'token').map((f) => (
            <div key={f.key} style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
              <label style={{ minWidth: '160px', fontSize: 'var(--text-sm)', fontWeight: 'var(--font-weight-medium)', color: 'var(--color-text-secondary)' }}>
                {f.label}
              </label>
              <input
                className="input"
                type={f.type === 'password' ? 'password' : 'text'}
                autoComplete="off"
                placeholder={f.placeholder}
                value={values[f.key] ?? initFromConfig()[f.key] ?? ''}
                onChange={(e) => setValues((p) => ({ ...p, [f.key]: e.target.value }))}
                style={{ flex: 1 }}
              />
            </div>
          ))}
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginTop: 'var(--space-2)' }}>
            <button type="submit" className="btn btn-primary" disabled={updateNative.isPending}>
              {updateNative.isPending ? 'Saving...' : connected ? 'Update' : 'Connect'}
            </button>
            {connected && (
              <button type="button" className="btn btn-secondary" onClick={handleDelete} disabled={deleteNative.isPending}>
                Disconnect
              </button>
            )}
          </div>
        </form>
      </div>
    </section>
  );
};

export default NativeConnectorForm;
