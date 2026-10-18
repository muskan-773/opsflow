import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'

export default function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const initials = user?.name
    ?.split(' ')
    .slice(0, 2)
    .map((n) => n[0])
    .join('') || '?'

  const topRole = user?.is_admin
    ? 'Admin'
    : user?.memberships?.map((m) => `${m.role} · ${m.team_name}`).join(', ')

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="sidebar-brand-name">OpsFlow</div>
          <div className="sidebar-brand-sub">Operations Under Pressure</div>
        </div>
        <nav className="sidebar-nav">
          <NavLink to="/dashboard" className={({ isActive }) => (isActive ? 'active' : '')}>
            Dashboard
          </NavLink>
          <NavLink to="/items" className={({ isActive }) => (isActive ? 'active' : '')}>
            Work Items
          </NavLink>
          <NavLink to="/items/new" className={({ isActive }) => (isActive ? 'active' : '')}>
            New Item
          </NavLink>
        </nav>
        <div className="sidebar-footer">
          <div className="sidebar-user">
            <div className="sidebar-avatar">{initials}</div>
            <div className="sidebar-user-info">
              <div className="sidebar-user-name">{user?.name}</div>
              <div className="sidebar-user-role truncate">{topRole}</div>
            </div>
            <button className="btn btn-sm btn-ghost" onClick={handleLogout} title="Log out">
              Log out
            </button>
          </div>
        </div>
      </aside>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  )
}
