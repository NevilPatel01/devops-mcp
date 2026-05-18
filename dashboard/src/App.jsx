import { useState } from "react";
import Dashboard from "./pages/Dashboard.jsx";
import Incidents from "./pages/Incidents.jsx";

const views = [
  { id: "dashboard", label: "Overview" },
  { id: "incidents", label: "Incidents" },
];

export default function App() {
  const [view, setView] = useState("dashboard");

  return (
    <div className="min-h-screen bg-slate-950">
      <nav className="border-b border-slate-800 bg-slate-900/90 px-6 py-2">
        <div className="mx-auto flex max-w-6xl gap-1">
          {views.map((v) => (
            <button
              key={v.id}
              type="button"
              onClick={() => setView(v.id)}
              className={`rounded-lg px-3 py-1.5 text-sm transition-colors ${
                view === v.id
                  ? "bg-slate-800 text-slate-100"
                  : "text-slate-500 hover:bg-slate-800/50 hover:text-slate-300"
              }`}
            >
              {v.label}
            </button>
          ))}
        </div>
      </nav>
      {view === "dashboard" ? <Dashboard /> : <Incidents />}
    </div>
  );
}
