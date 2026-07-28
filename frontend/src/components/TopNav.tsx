type TopNavProps = {
  onMenuClick: () => void;
};

export function TopNav({ onMenuClick }: TopNavProps) {
  return (
    <header className="top-nav">
      <button
        type="button"
        className="menu-toggle"
        onClick={onMenuClick}
        aria-label="Toggle navigation"
      >
        ☰
      </button>
      <div className="top-nav-title">Alterfolio Frontend MVP</div>
    </header>
  );
}
