import { useEffect, useState } from "react";
import Dashboard from "./pages/Dashboard.jsx";
import Analyze from "./pages/Analyze.jsx";
import Sessions from "./pages/Sessions.jsx";
import SettingsPage from "./pages/Settings.jsx";

const PAGES = [
  { id: "dashboard", label: "Dashboard", component: Dashboard },
  { id: "analyze", label: "Analyze Item", component: Analyze },
  { id: "sessions", label: "Seller Sessions", component: Sessions },
  { id: "settings", label: "Settings", component: SettingsPage },
];
const COMING = ["Comparable Research", "Inventory"];

export default function App() {
  const [page, setPage] = useState(() => window.location.hash.slice(1) || "dashboard");
  const [simulated, setSimulated] = useState(() => localStorage.getItem("ph-mode") === "simulated");

  useEffect(() => {
    window.location.hash = page;
  }, [page]);
  useEffect(() => {
    localStorage.setItem("ph-mode", simulated ? "simulated" : "real");
  }, [simulated]);

  const current = PAGES.find((p) => p.id === page) || PAGES[0];
  const Page = current.component;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">Profit Hunter</div>
        <nav>
          {PAGES.map((p) => (
            <button key={p.id} className={p.id === current.id ? "nav active" : "nav"} onClick={() => setPage(p.id)}>
              {p.label}
            </button>
          ))}
          {COMING.map((label) => (
            <button key={label} className="nav" disabled title="Arrives in a later milestone">
              {label} <small>soon</small>
            </button>
          ))}
        </nav>
        <div className="mode">
          <div className="mode-label">Mode</div>
          <div className="segmented">
            <button className={!simulated ? "on" : ""} onClick={() => setSimulated(false)}>Real</button>
            <button className={simulated ? "on" : ""} onClick={() => setSimulated(true)}>Practice</button>
          </div>
          <p className="hint">Practice purchases use a separate budget and never mix with real ones.</p>
        </div>
        <p className="hint foot">Recommendations only. Profit Hunter never bids or buys.</p>
      </aside>
      <main className="main">
        {simulated && <div className="banner-sim">PRACTICE MODE — simulated purchases, separate budget</div>}
        <Page key={`${current.id}-${simulated}`} simulated={simulated} goTo={setPage} />
      </main>
    </div>
  );
}
