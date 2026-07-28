import { NavLink } from "react-router-dom";

const navItems = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/trades", label: "Trades" },
  { to: "/portfolio", label: "Portfolio" },
  { to: "/ai-analysis", label: "AI Analysis" },
];

type SidebarProps = {
  isOpen: boolean;
  onNavigate: () => void;
};

export function Sidebar({ isOpen, onNavigate }: SidebarProps) {
  return (
    <aside className={`sidebar ${isOpen ? "open" : ""}`}>
      <div className="sidebar-header">Alterfolio</div>
      <nav className="sidebar-nav" aria-label="Main navigation">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `sidebar-link ${isActive ? "active" : ""}`
            }
            onClick={onNavigate}
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
