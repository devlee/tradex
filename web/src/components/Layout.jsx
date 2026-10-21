import { NavLink, Outlet } from "react-router-dom";
import { useCoin } from "../coin";

export default function Layout() {
  const { coin, setCoin, coins } = useCoin();
  return (
    <div className="app-shell">
      <header className="topnav">
        <p className="eyebrow">OKX 公开行情 · 本地重放 · 不下真实单</p>
        <div className="nav-side">
          <nav>
            <NavLink to="/" end>统计</NavLink>
            <NavLink to="/clock">钟点进场</NavLink>
            <NavLink to="/secretary">秘书问题</NavLink>
            <NavLink to="/secretary-2">秘书问题2</NavLink>
            <NavLink to="/secretary-3">秘书问题3</NavLink>
            <NavLink to="/secretary-4">秘书问题4</NavLink>
            <NavLink to="/demo">模拟单</NavLink>
          </nav>
          <label className="coin-switch">
            币种
            <select value={coin} onChange={(event) => setCoin(event.target.value)}>
              {coins.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
        </div>
      </header>
      <Outlet />
    </div>
  );
}
