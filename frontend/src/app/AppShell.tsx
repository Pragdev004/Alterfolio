import { NavLink, Outlet, useLocation } from "react-router-dom";

import { useGShortcutsSetting } from "./preferences";
import { useGChords } from "./useGChords";

const SCREENS = [
  ["/holdings", "Holdings"],
  ["/trips", "Trips"],
  ["/costs", "Costs"],
  ["/ask", "Ask"],
  ["/upload", "Upload"],
] as const;

export function AppShell() {
  const [shortcuts, setShortcuts] = useGShortcutsSetting();
  useGChords(shortcuts);
  const { search } = useLocation();
  return (
    <>
      <a className="skip" href="#main">Skip to main content</a>
      <div className="shell">
        <nav className="rail" aria-label="Screens">
          <div className="rail-in">
            <p className="brand">Alterfolio</p>
            <ul>
              {SCREENS.map(([to, label]) => (
                <li key={to}><NavLink to={{ pathname: to, search }}>{label}</NavLink></li>
              ))}
            </ul>
            <label className="pref">
              <input type="checkbox" checked={shortcuts} onChange={(e) => setShortcuts(e.target.checked)} />
              <span>Keyboard shortcuts<small>g then h, t, c, a or u</small></span>
            </label>
          </div>
        </nav>
        <main id="main" tabIndex={-1}>
          <Outlet />
          <footer><span>Educational, not financial advice. Nothing here predicts future returns.</span></footer>
        </main>
      </div>
    </>
  );
}
