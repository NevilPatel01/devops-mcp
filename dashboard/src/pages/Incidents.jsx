import { useCallback, useEffect, useState } from "react";
import IncidentDetail from "../components/IncidentDetail.jsx";
import IncidentFeed from "../components/IncidentFeed.jsx";

export default function Incidents() {
  const [selected, setSelected] = useState(null);
  const [suppressionCount, setSuppressionCount] = useState(0);
  const [feedKey, setFeedKey] = useState(0);

  const refreshSuppressions = useCallback(() => {
    fetch("/api/suppressions")
      .then((r) => r.json())
      .then((data) => {
        if (data.success) setSuppressionCount(data.count ?? 0);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    refreshSuppressions();
  }, [refreshSuppressions]);

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <header className="mb-6">
        <h1 className="text-xl font-semibold text-slate-100">Incident history</h1>
        <p className="mt-1 text-sm text-slate-500">
          Timeline, actions, postmortems, and false-positive marking.
          {suppressionCount > 0 && (
            <span className="ml-2 text-amber-400/90">
              {suppressionCount} active suppression{suppressionCount === 1 ? "" : "s"}
            </span>
          )}
        </p>
      </header>
      <IncidentFeed key={feedKey} onSelect={setSelected} showFilters />
      <IncidentDetail
        incident={selected}
        onClose={() => setSelected(null)}
        onFalsePositiveMarked={() => {
          refreshSuppressions();
          setFeedKey((k) => k + 1);
        }}
      />
    </div>
  );
}
