import { useState } from "react";
import IncidentDetail from "../components/IncidentDetail.jsx";
import IncidentFeed from "../components/IncidentFeed.jsx";

export default function IncidentsPage() {
  const [selected, setSelected] = useState(null);
  const [feedKey, setFeedKey] = useState(0);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-white">Incidents</h1>
        <p className="mt-0.5 text-sm text-zinc-500">Detected issues and resolution history.</p>
      </div>
      <IncidentFeed key={feedKey} onSelect={setSelected} showFilters />
      <IncidentDetail
        incident={selected}
        onClose={() => setSelected(null)}
        onFalsePositiveMarked={() => setFeedKey((k) => k + 1)}
      />
    </div>
  );
}
