import { useEffect, useState } from "react";
import { fetchJson } from "../api.js";

export default function SettingsPage() {
  const [slack, setSlack] = useState("");
  const [email, setEmail] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetchJson("/api/fleet/settings").then((res) => {
      if (res.ok && res.data?.settings) {
        setSlack(res.data.settings.slack_webhook_url || "");
        setEmail(res.data.settings.alert_email || "");
      }
    });
  }, []);

  const save = async () => {
    const res = await fetchJson("/api/fleet/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slack_webhook_url: slack, alert_email: email }),
    });
    if (res.ok) {
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    }
  };

  return (
    <div className="mx-auto max-w-lg space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-white">Settings</h1>
        <p className="mt-0.5 text-sm text-zinc-500">Notifications and MCP integration.</p>
      </div>

      <section className="panel p-5">
        <h2 className="text-sm font-medium text-white">Alert delivery</h2>
        <p className="mt-1 text-xs text-zinc-500">Notify when a site goes down.</p>
        <div className="mt-4 space-y-4">
          <label className="block">
            <span className="text-xs text-zinc-500">Slack webhook</span>
            <input
              className="input-field mt-1.5"
              value={slack}
              onChange={(e) => setSlack(e.target.value)}
              placeholder="https://hooks.slack.com/services/…"
            />
          </label>
          <label className="block">
            <span className="text-xs text-zinc-500">Email</span>
            <input
              className="input-field mt-1.5"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
            />
          </label>
        </div>
        <div className="mt-4 flex items-center gap-3">
          <button type="button" className="btn-primary" onClick={save}>
            Save changes
          </button>
          {saved && <span className="text-sm text-mint">Saved</span>}
        </div>
      </section>

      <section className="panel p-5">
        <h2 className="text-sm font-medium text-white">MCP integration</h2>
        <p className="mt-2 text-sm leading-relaxed text-zinc-500">
          Connect Cursor or Claude Desktop to{" "}
          <code className="rounded bg-black/40 px-1.5 py-0.5 font-mono text-xs text-zinc-300">
            http://127.0.0.1:8080/mcp
          </code>{" "}
          for incident investigation and container logs.
        </p>
      </section>
    </div>
  );
}
