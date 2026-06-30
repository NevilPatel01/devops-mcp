import { useState } from "react";
import AppShell, { useFleetStats } from "./components/layout/AppShell.jsx";
import OverviewPage from "./pages/Overview.jsx";
import SitesPage from "./pages/Sites.jsx";
import IncidentsPage from "./pages/IncidentsPage.jsx";
import SettingsPage from "./pages/Settings.jsx";
import SetupBanner from "./components/SetupBanner.jsx";
import { IconPlus, IconServer } from "./components/ui/icons.jsx";

export default function App() {
  const [view, setView] = useState("sites");
  const { stats, refreshStats } = useFleetStats();
  const [showServer, setShowServer] = useState(false);
  const [showSite, setShowSite] = useState(false);

  const navigate = (id) => {
    setView(id);
    refreshStats();
  };

  const headerActions =
    view === "sites" ? (
      <>
        <button type="button" className="btn-secondary text-xs" onClick={() => setShowServer(true)}>
          <IconServer className="h-3.5 w-3.5" />
          Server
        </button>
        <button type="button" className="btn-primary text-xs" onClick={() => setShowSite(true)}>
          <IconPlus className="h-3.5 w-3.5" />
          Add site
        </button>
      </>
    ) : null;

  return (
    <AppShell view={view} onNavigate={navigate} stats={stats} actions={headerActions}>
      {view === "sites" && (
        <>
          <div className="mb-4">
            <SetupBanner />
          </div>
          <SitesPage
          onStatsChange={refreshStats}
          onNavigate={navigate}
          showServer={showServer}
          showSite={showSite}
          setShowServer={setShowServer}
          setShowSite={setShowSite}
        />
        </>
      )}
      {view === "overview" && <OverviewPage onNavigate={navigate} />}
      {view === "incidents" && <IncidentsPage />}
      {view === "settings" && <SettingsPage />}
    </AppShell>
  );
}
