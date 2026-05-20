import { useState } from "react";
import TerraformFindingsTable from "../components/TerraformFindingsTable.jsx";

export default function Terraform() {
  const [planText, setPlanText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  async function handleAnalyze() {
    setError(null);
    setResult(null);
    if (!planText.trim()) {
      setError("Paste terraform show -json output first.");
      return;
    }
    setLoading(true);
    try {
      JSON.parse(planText);
    } catch {
      setLoading(false);
      setError("Invalid JSON — paste output from: terraform show -json planfile");
      return;
    }
    try {
      const response = await fetch("/api/terraform/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan_json: planText }),
      });
      const data = await response.json();
      if (!data.success) {
        setError(data.error || "Analysis failed");
        return;
      }
      setResult(data);
    } catch (exc) {
      setError(exc.message || "Request failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <header className="mb-6">
        <h1 className="text-xl font-semibold text-slate-100">Terraform plan review</h1>
        <p className="mt-1 text-sm text-slate-500">
          Paste <code className="text-slate-400">terraform show -json</code> output for risk
          scoring, destructive-change flags, and naming checks.
        </p>
      </header>

      <label className="block text-sm font-medium text-slate-400">
        Plan JSON
        <textarea
          className="mt-2 h-48 w-full rounded-lg border border-slate-800 bg-slate-900/60 p-3 font-mono text-xs text-slate-200 focus:border-sky-600 focus:outline-none"
          placeholder='{"format_version": "1.2", "resource_changes": [...]}'
          value={planText}
          onChange={(e) => setPlanText(e.target.value)}
        />
      </label>

      <div className="mt-4 flex items-center gap-3">
        <button
          type="button"
          onClick={handleAnalyze}
          disabled={loading}
          className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
        >
          {loading ? "Analysing…" : "Analyse plan"}
        </button>
        {error && <p className="text-sm text-red-400">{error}</p>}
      </div>

      {result && (
        <section className="mt-8 space-y-6">
          <div className="flex flex-wrap items-center gap-4 rounded-lg border border-slate-800 bg-slate-900/50 px-4 py-3">
            <div>
              <p className="text-xs text-slate-500">Overall risk</p>
              <p className="text-2xl font-semibold text-slate-100">
                {result.overall_risk_score}
                <span className="text-sm font-normal text-slate-500"> / 10</span>
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Changes</p>
              <p className="text-lg text-slate-200">{result.changes?.length ?? 0}</p>
            </div>
            {result.analysis_id && (
              <p className="text-xs text-slate-600">ID: {result.analysis_id}</p>
            )}
          </div>

          <TerraformFindingsTable
            changes={result.changes}
            flaggedDeletes={result.flagged_deletes}
          />

          {result.naming_violations?.length > 0 && (
            <div>
              <h2 className="mb-2 text-sm font-medium text-slate-300">Naming violations</h2>
              <ul className="list-inside list-disc text-sm text-amber-200/90">
                {result.naming_violations.map((v) => (
                  <li key={`${v.address}-${v.rule}`}>
                    <span className="font-mono text-xs">{v.address}</span>: {v.message}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {result.summary_markdown && (
            <div>
              <h2 className="mb-2 text-sm font-medium text-slate-300">Summary</h2>
              <pre className="whitespace-pre-wrap rounded-lg border border-slate-800 bg-slate-900/40 p-4 text-sm text-slate-300">
                {result.summary_markdown}
              </pre>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
