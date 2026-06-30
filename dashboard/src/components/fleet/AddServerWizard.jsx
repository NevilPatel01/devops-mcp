import { useState } from "react";
import { fetchJson } from "../../api.js";

export default function AddServerWizard({ open, onClose, onSuccess }) {
  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [testResult, setTestResult] = useState(null);
  const [composeFiles, setComposeFiles] = useState([]);
  const [form, setForm] = useState({
    label: "",
    host: "",
    port: "22",
    user: "root",
    ssh_key_path: "~/.ssh/id_ed25519",
    ssh_private_key: "",
    useUpload: false,
  });

  if (!open) return null;

  const payload = () => ({
    label: form.label,
    host: form.host,
    port: Number(form.port) || 22,
    user: form.user,
    ...(form.useUpload && form.ssh_private_key
      ? { ssh_private_key: form.ssh_private_key }
      : { ssh_key_path: form.ssh_key_path }),
  });

  const runTest = async () => {
    setLoading(true);
    setError("");
    const res = await fetchJson("/api/fleet/servers/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload()),
    });
    setLoading(false);
    if (!res.ok) {
      setError(res.error || "Test failed");
      setTestResult(null);
      return;
    }
    setTestResult(res.data);
    if (res.data?.success) {
      const disc = await fetchJson("/api/fleet/servers/discover", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload()),
      });
      if (disc.ok && disc.data?.compose_files) {
        setComposeFiles(disc.data.compose_files);
      }
      setStep(2);
    } else {
      setError(res.data?.error || "Connection failed");
    }
  };

  const save = async () => {
    setLoading(true);
    setError("");
    const res = await fetchJson("/api/fleet/servers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload()),
    });
    setLoading(false);
    if (!res.ok || !res.data?.success) {
      setError(res.data?.error || res.error || "Save failed");
      return;
    }
    onSuccess?.(res.data.server);
    onClose();
    setStep(1);
    setForm({
      label: "",
      host: "",
      port: "22",
      user: "root",
      ssh_key_path: "~/.ssh/id_ed25519",
      ssh_private_key: "",
      useUpload: false,
    });
  };

  return (
    <Modal title="Add VPS server" onClose={onClose}>
      {step === 1 && (
        <div className="space-y-4">
          <Field label="Display name" value={form.label} onChange={(v) => setForm({ ...form, label: v })} placeholder="Linode production" />
          <Field label="Host / IP" value={form.host} onChange={(v) => setForm({ ...form, host: v })} placeholder="203.0.113.10" />
          <div className="grid grid-cols-2 gap-3">
            <Field label="SSH port" value={form.port} onChange={(v) => setForm({ ...form, port: v })} />
            <Field label="SSH user" value={form.user} onChange={(v) => setForm({ ...form, user: v })} />
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-400">
            <input
              type="checkbox"
              checked={form.useUpload}
              onChange={(e) => setForm({ ...form, useUpload: e.target.checked })}
              className="rounded border-surface-border"
            />
            Upload private key instead of path
          </label>
          {form.useUpload ? (
            <textarea
              className="input-field min-h-[100px] font-mono text-xs"
              placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
              value={form.ssh_private_key}
              onChange={(e) => setForm({ ...form, ssh_private_key: e.target.value })}
            />
          ) : (
            <Field
              label="SSH key path"
              value={form.ssh_key_path}
              onChange={(v) => setForm({ ...form, ssh_key_path: v })}
            />
          )}
          {error && <p className="text-sm text-red-400">{error}</p>}
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button type="button" className="btn-primary" disabled={loading || !form.host} onClick={runTest}>
              {loading ? "Testing…" : "Test connection"}
            </button>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="space-y-4">
          <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
            {testResult?.message || "SSH connection successful"}
            {testResult?.sample_containers?.length > 0 && (
              <p className="mt-1 text-xs text-emerald-300/80">
                Containers: {testResult.sample_containers.join(", ")}
              </p>
            )}
          </div>
          {composeFiles.length > 0 && (
            <div>
              <p className="mb-2 text-xs text-slate-500">
                Optional — compose files found (use when adding a site for deploy/rollback)
              </p>
              <ul className="max-h-32 overflow-y-auto rounded-xl border border-surface-border bg-surface/60 p-2 font-mono text-xs text-slate-400">
                {composeFiles.map((f) => (
                  <li key={f} className="py-0.5">
                    {f}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {error && <p className="text-sm text-red-400">{error}</p>}
          <div className="flex justify-between gap-2 pt-2">
            <button type="button" className="btn-ghost" onClick={() => setStep(1)}>
              Back
            </button>
            <button type="button" className="btn-primary" disabled={loading} onClick={save}>
              {loading ? "Saving…" : "Add server"}
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}

function Modal({ title, onClose, children }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button type="button" className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} aria-label="Close" />
      <div className="glass-panel relative z-10 w-full max-w-lg p-6">
        <h2 className="text-lg font-semibold tracking-tight text-white">{title}</h2>
        <div className="mt-5">{children}</div>
      </div>
    </div>
  );
}

function Field({ label, value, onChange, placeholder }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-medium text-slate-400">{label}</span>
      <input
        className="input-field"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}
