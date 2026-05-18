import { useState } from "react";
import IncidentDetail from "../components/IncidentDetail.jsx";
import IncidentFeed from "../components/IncidentFeed.jsx";

export default function Incidents() {
  const [selected, setSelected] = useState(null);

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <header className="mb-6">
        <h1 className="text-xl font-semibold text-slate-100">Incident history</h1>
        <p className="mt-1 text-sm text-slate-500">
          Timeline, actions, postmortems, and false-positive marking.
        </p>
      </header>
      <IncidentFeed onSelect={setSelected} showFilters />
      <IncidentDetail incident={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
