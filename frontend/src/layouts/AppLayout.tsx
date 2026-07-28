import { useState } from "react";
import { Outlet } from "react-router-dom";

import { Sidebar } from "../components/Sidebar";
import { TopNav } from "../components/TopNav";

export function AppLayout() {
  const [isSidebarOpen, setSidebarOpen] = useState(false);

  const handleMenuClick = () => {
    setSidebarOpen((prev) => !prev);
  };

  const closeSidebar = () => {
    setSidebarOpen(false);
  };

  return (
    <div className="app-shell">
      <Sidebar isOpen={isSidebarOpen} onNavigate={closeSidebar} />
      <div className="app-main">
        <TopNav onMenuClick={handleMenuClick} />
        <main className="page-content" onClick={closeSidebar}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
