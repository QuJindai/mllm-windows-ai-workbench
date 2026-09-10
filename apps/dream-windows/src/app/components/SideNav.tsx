export type SideNavItem<Route extends string> = { id: Route; label: string; icon: string };

export function SideNav<Route extends string>({ items, active, onNavigate }: { items: SideNavItem<Route>[]; active: Route; onNavigate: (route: Route) => void }) {
  return (
    <aside className="side-nav" aria-label="主导航">
      <nav className="nav-list">
        {items.map((item) => <button className={`nav-item ${active === item.id ? "is-active" : ""}`} key={item.id} type="button" aria-label={item.label} title={item.label} aria-current={active === item.id ? "page" : undefined} onClick={() => onNavigate(item.id)}><span className="nav-icon" aria-hidden="true">{item.icon}</span><span>{item.label}</span></button>)}
      </nav>
      <div className="nav-footer"><div className="footer-brand">Dream</div><div className="footer-version">v0.8.0<br />浏览器工作站</div><div className="footer-ready"><span className="status-dot" />就绪</div></div>
    </aside>
  );
}
