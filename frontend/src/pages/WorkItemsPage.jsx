import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { Spinner, EmptyState, ErrorState } from '../components/States.jsx'
import { StatusBadge, PriorityBadge, TYPE_LABELS } from '../components/Badges.jsx'

export default function WorkItemsPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const q = searchParams.get('q') || ''
  const status = searchParams.get('status') || ''
  const priority = searchParams.get('priority') || ''
  const page = parseInt(searchParams.get('page') || '1', 10)
  const size = 15

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await api.listItems({ q, status, priority, page, size })
      setData(res)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [q, status, priority, page])

  const setParam = (key, value) => {
    const next = new URLSearchParams(searchParams)
    if (value) next.set(key, value)
    else next.delete(key)
    if (key !== 'page') next.delete('page')
    setSearchParams(next)
  }

  const totalPages = data?.meta?.pages || 0

  return (
    <div>
      <div className="topbar">
        <div>
          <div className="page-title">Work Items</div>
          <div className="page-sub">Search, filter and paginate — all handled on the server</div>
        </div>
        <button className="btn btn-primary" onClick={() => navigate('/items/new')}>＋ New Item</button>
      </div>

      <div className="filters-bar">
        <input
          className="filter-input"
          placeholder="Search title or description…"
          value={q}
          onChange={(e) => setParam('q', e.target.value)}
        />
        <select className="filter-select" value={status} onChange={(e) => setParam('status', e.target.value)}>
          <option value="">All statuses</option>
          <option value="open">Open</option>
          <option value="in_progress">In Progress</option>
          <option value="awaiting_approval">Awaiting Approval</option>
          <option value="resolved">Resolved</option>
          <option value="closed">Closed</option>
        </select>
        <select className="filter-select" value={priority} onChange={(e) => setParam('priority', e.target.value)}>
          <option value="">All priorities</option>
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
          <option value="critical">Critical</option>
        </select>
      </div>

      <div className="card" style={{ padding: 0 }}>
        {loading ? <Spinner /> : error ? <ErrorState message={error} /> : !data?.items?.length ? (
          <EmptyState title="No work items found" sub="Try adjusting your filters or create a new item." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Title</th><th>Priority</th><th>Status</th>
                  <th>Assignee</th><th>Team</th><th>Due</th><th>v</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((it) => (
                  <tr key={it.id} onClick={() => navigate(`/items/${it.id}`)}>
                    <td>
                      <div className="item-title truncate">{it.title}</div>
                      <div className="item-meta">{TYPE_LABELS[it.type] || it.type}</div>
                    </td>
                    <td><PriorityBadge priority={it.priority} /></td>
                    <td><StatusBadge status={it.status} /></td>
                    <td>{it.assignee_name || <span className="text-muted">Unassigned</span>}</td>
                    <td>{it.team_name || `#${it.team_id}`}</td>
                    <td className="text-muted">{it.due_date || '—'}</td>
                    <td className="text-muted">v{it.version}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="pagination">
              <div className="page-info">
                {data.meta.total} items · page {page} of {Math.max(totalPages, 1)}
              </div>
              <div className="page-btns">
                <button className="page-btn" disabled={page <= 1} onClick={() => setParam('page', page - 1)}>‹ Prev</button>
                <button className="page-btn" disabled={page >= totalPages} onClick={() => setParam('page', page + 1)}>Next ›</button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
