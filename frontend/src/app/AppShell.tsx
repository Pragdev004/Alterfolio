import { NavLink, Outlet, useLocation } from "react-router-dom";

import { useGChords } from "./useGChords";

const SCREENS = [
  ["/holdings", "Holdings"],
  ["/trips", "Trips"],
  ["/costs", "Costs"],
  ["/ask", "Ask"],
  ["/upload", "Upload"],
] as const;

export function AppShell() {
  useGChords();
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
            <small>Educational, not financial advice.</small>
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
