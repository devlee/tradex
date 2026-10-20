import { NavLink, Outlet } from "react-router-dom";

export default function Layout() {
  return (
    <div className="app-shell">
      <header className="topnav">
        <p className="eyebrow">OKX 公开行情 · 本地重放 · 不下真实单</p>
        <nav>
          <NavLink to="/" end>钟点进场</NavLink>
          <NavLink to="/secretary">秘书问题</NavLink>
          <NavLink to="/secretary-2">秘书问题2</NavLink>
          <NavLink to="/secretary-3">秘书问题3</NavLink>
        </nav>
      </header>
      <Outlet />
    </div>
  );
}
