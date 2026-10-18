import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { Spinner, EmptyState, ErrorState } from '../components/States.jsx'
import { StatusBadge, PriorityBadge, TYPE_LABELS } from '../components/Badges.jsx'

function StatCard({ label, value, tone }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value" style={{ color: tone }}>{value}</div>
    </div>
  )
}

function MiniList({ title, items, emptyText }) {
  return (
    <div className="card" style={{ marginBottom: 20 }}>
      <div className="section-title">{title}</div>
      {!items?.length ? (
        <div className="text-muted" style={{ padding: '8px 0', fontSize: 13 }}>{emptyText}</div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Title</th><th>Priority</th><th>Status</th><th>Team</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.id} onClick={() => (window.location.href = `/items/${it.id}`)}>
                  <td>
                    <div className="item-title truncate">{it.title}</div>
                    <div className="item-meta">{TYPE_LABELS[it.type] || it.type}</div>
                  </td>
                  <td><PriorityBadge priority={it.priority} /></td>
                  <td><StatusBadge status={it.status} /></td>
                  <td>{it.team_name || `#${it.team_id}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default function DashboardPage() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const d = await api.dashboard()
      setData(d)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  if (loading) return <Spinner label="Loading dashboard…" />
  if (error) return <ErrorState message={error} />
  if (!data) return <EmptyState title="No data" />

  const s = data.stats
  return (
    <div>
      <div className="topbar">
        <div>
          <div className="page-title">Dashboard</div>
          <div className="page-sub">Operations overview across your teams</div>
        </div>
        <button className="btn btn-secondary" onClick={load}>Refresh</button>
      </div>

      <div className="stat-grid">
        <StatCard label="Total Open" value={s.total_open} />
        <StatCard label="Critical / High" value={s.critical_high} tone="var(--warning)" />
        <StatCard label="Assigned to Me" value={s.assigned_to_me} tone="var(--primary)" />
        <StatCard label="Unassigned Urgent" value={s.unassigned_urgent} tone="var(--danger)" />
        <StatCard label="Awaiting My Approval" value={s.awaiting_my_approval} tone="#7c3aed" />
      </div>

      <MiniList
        title="Assigned to me"
        items={data.assigned_to_me}
        emptyText="No items assigned to you right now."
      />
      <MiniList
        title="Unassigned urgent — claim one"
        items={data.unassigned_urgent}
        emptyText="No unassigned urgent items."
      />
      <MiniList
        title="Awaiting your approval"
        items={data.awaiting_my_approval}
        emptyText="Nothing waiting on your approval."
      />
    </div>
  )
}
