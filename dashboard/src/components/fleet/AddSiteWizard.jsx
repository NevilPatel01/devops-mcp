import { useEffect, useState } from "react";
import { fetchJson } from "../../api.js";

export default function AddSiteWizard({ open, onClose, onSuccess, servers }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [containers, setContainers] = useState([]);
  const [form, setForm] = useState({
    client_name: "",
    name: "",
    url: "",
    server_id: "",
    compose_file: "",
    service_name: "",
    environment: "production",
    sensitive: false,
  });

  useEffect(() => {
    if (!open || !form.server_id) {
      setContainers([]);
      return;
    }
    fetchJson(`/api/fleet/servers/${form.server_id}/containers`).then((res) => {
      if (res.ok && res.data?.containers) {
        setContainers(res.data.containers);
      }
    });
  }, [open, form.server_id]);

  if (!open) return null;

  const save = async () => {
    setLoading(true);
    setError("");
    const payload = {
      ...form,
      compose_file: form.compose_file.trim() || null,
      service_name: form.service_name.trim() || null,
    };
    const res = await fetchJson("/api/fleet/sites", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    setLoading(false);
    if (!res.ok || !res.data?.success) {
      setError(res.data?.error || res.error || "Failed to add site");
      return;
    }
    onSuccess?.(res.data.site);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button type="button" className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} aria-label="Close" />
      <div className="glass-panel relative z-10 w-full max-w-lg p-6">
        <h2 className="text-lg font-semibold tracking-tight text-white">Add client site</h2>
        <div className="mt-5 space-y-4">
          <Field label="Client name" value={form.client_name} onChange={(v) => setForm({ ...form, client_name: v })} placeholder="Acme Bakery" />
          <Field label="Site name" value={form.name} onChange={(v) => setForm({ ...form, name: v })} placeholder="acme.com" />
          <Field label="URL (uptime check)" value={form.url} onChange={(v) => setForm({ ...form, url: v })} placeholder="https://acme.com" />

          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-slate-400">Server</span>
            <select
              className="input-field"
              value={form.server_id}
              onChange={(e) => setForm({ ...form, server_id: e.target.value })}
            >
              <option value="">Select server…</option>
              {(servers || []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label} ({s.host})
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-slate-400">
              Compose file <span className="text-slate-600">(optional)</span>
            </span>
            <input
              className="input-field"
              value={form.compose_file}
              placeholder="/home/deploy/app/docker-compose.yml"
              onChange={(e) => setForm({ ...form, compose_file: e.target.value })}
            />
            <p className="mt-1.5 text-xs text-slate-600">
              Only for compose deploy/rollback. Uptime, logs, and restart use the container name via SSH.
            </p>
          </label>

          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-slate-400">Container / service</span>
            <select
              className="input-field"
              value={form.service_name}
              onChange={(e) => setForm({ ...form, service_name: e.target.value })}
            >
              <option value="">Select or type below…</option>
              {containers.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name} — {c.status}
                </option>
              ))}
            </select>
            <input
              className="input-field mt-2"
              placeholder="Or type service name"
              value={form.service_name}
              onChange={(e) => setForm({ ...form, service_name: e.target.value })}
            />
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="mb-1.5 block text-xs font-medium text-slate-400">Environment</span>
              <select
                className="input-field"
                value={form.environment}
                onChange={(e) => setForm({ ...form, environment: e.target.value })}
              >
                <option value="production">Production</option>
                <option value="staging">Staging</option>
              </select>
            </label>
            <label className="flex items-end gap-2 pb-2 text-sm text-slate-400">
              <input
                type="checkbox"
                checked={form.sensitive}
                onChange={(e) => setForm({ ...form, sensitive: e.target.checked })}
              />
              Sensitive (no auto-fix)
            </label>
          </div>

          {error && <p className="text-sm text-red-400">{error}</p>}

          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button
              type="button"
              className="btn-primary"
              disabled={loading || !form.name || !form.server_id}
              onClick={save}
            >
              {loading ? "Saving…" : "Add site"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({ label, value, onChange, placeholder }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-medium text-slate-400">{label}</span>
      <input className="input-field" value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}
