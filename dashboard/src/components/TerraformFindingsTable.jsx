function riskClass(score) {
  if (score >= 8) return "bg-red-500/20 text-red-300";
  if (score >= 5) return "bg-amber-500/20 text-amber-300";
  return "bg-emerald-500/20 text-emerald-300";
}

export default function TerraformFindingsTable({ changes = [], flaggedDeletes = [] }) {
  const flaggedSet = new Set(flaggedDeletes.map((c) => c.address));

  if (!changes.length) {
    return (
      <p className="text-sm text-slate-500">No resource changes in this plan.</p>
    );
  }

  return (
    <div className="w-full overflow-x-auto rounded-lg border border-slate-800">
      <table className="w-full text-left text-sm">
        <thead className="bg-slate-900/80 text-slate-400">
          <tr>
            <th className="px-3 py-2 font-medium">Resource</th>
            <th className="px-3 py-2 font-medium">Action</th>
            <th className="px-3 py-2 font-medium">Risk</th>
            <th className="px-3 py-2 font-medium">Flags</th>
          </tr>
        </thead>
        <tbody>
          {changes.map((row) => (
            <tr key={row.address} className="border-t border-slate-800/80">
              <td className="px-3 py-2 font-mono text-xs text-slate-300">
                {row.address}
              </td>
              <td className="px-3 py-2 capitalize text-slate-200">{row.action}</td>
              <td className="px-3 py-2">
                <span
                  className={`rounded px-2 py-0.5 text-xs font-medium ${riskClass(row.risk_score)}`}
                >
                  {row.risk_score}
                </span>
              </td>
              <td className="px-3 py-2 text-xs text-slate-500">
                {flaggedSet.has(row.address) ? "destructive" : "—"}
                {row.modifiers?.length ? ` · ${row.modifiers.join(", ")}` : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
