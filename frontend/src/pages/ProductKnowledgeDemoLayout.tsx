import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'

// Local dev-only route. It does not supply an identity or bypass EOS auth routes.
export default function ProductKnowledgeDemoLayout() {
  const [menuOpen, setMenuOpen] = useState(false)
  return <div className="workspace-shell">
    <header className="workspace-topbar"><div className="workspace-topbar-left"><button className="menu-toggle" type="button" aria-label="Открыть меню" aria-expanded={menuOpen} onClick={() => setMenuOpen(!menuOpen)}><span /><span /></button><NavLink className="workspace-logo" to="/dev/products">EOS</NavLink></div><span className="workspace-user product-demo-user">Локальный review · K0</span></header>
    {menuOpen && <button className="menu-backdrop" aria-label="Закрыть меню" onClick={() => setMenuOpen(false)} />}
    <aside className={`workspace-menu ${menuOpen ? 'workspace-menu-open' : ''}`}><div className="menu-header"><p className="eyebrow">ENTERPRISEOS</p><strong>Рабочее пространство</strong></div><nav className="menu-navigation"><NavLink to="/dev/products" className="menu-link menu-link-active" onClick={() => setMenuOpen(false)}><span>Продукция</span><span>→</span></NavLink></nav><div className="menu-footer"><span>Изолированные демонстрационные данные</span></div></aside>
    <main className="workspace-content"><Outlet /></main>
  </div>
}
