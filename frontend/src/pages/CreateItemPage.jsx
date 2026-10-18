import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { api, ApiError } from '../api/client'
import { TYPE_LABELS } from '../components/Badges.jsx'

const PRIORITIES = ['low', 'medium', 'high', 'critical']

export default function CreateItemPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const teams = user?.memberships?.map((m) => ({ id: m.team_id, name: m.team_name })) || []

  const [form, setForm] = useState({
    title: '',
    description: '',
    type: 'incident',
    priority: 'medium',
    team_id: teams[0]?.id || '',
    due_date: '',
  })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    if (!form.team_id) {
      setError('Select a team first.')
      return
    }
    setLoading(true)
    try {
      // Idempotency key guards against double-clicks creating duplicates.
      const key = `create-${Date.now()}-${Math.random().toString(36).slice(2)}`
      const created = await api.createItem(
        {
          ...form,
          due_date: form.due_date || null,
        },
        key,
      )
      navigate(`/items/${created.id}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to create item.')
    } finally {
      setLoading(false)
    }
  }

  if (user?.memberships?.length === 0 && !user?.is_admin) {
    return (
      <div className="alert alert-warning">
        You are not a member of any team, so you can't create items. Contact an admin.
      </div>
    )
  }

  return (
    <div style={{ maxWidth: 640 }}>
      <div className="topbar">
        <div>
          <div className="page-title">New Work Item</div>
          <div className="page-sub">Create a task, incident, or issue</div>
        </div>
        <button className="btn btn-secondary" onClick={() => navigate(-1)}>Cancel</button>
      </div>

      <div className="card">
        {error && <div className="alert alert-error">{error}</div>}
        <form onSubmit={submit}>
          <div className="form-group">
            <label className="form-label">Title *</label>
            <input
              className="form-input"
              value={form.title}
              onChange={(e) => set('title', e.target.value)}
              placeholder="Short, clear summary of the work"
              required
              autoFocus
            />
          </div>

          <div className="form-group">
            <label className="form-label">Description</label>
            <textarea
              className="form-textarea"
              value={form.description}
              onChange={(e) => set('description', e.target.value)}
              placeholder="Add context, steps to reproduce, links…"
            />
          </div>

          <div className="meta-grid">
            <div className="form-group">
              <label className="form-label">Type *</label>
              <select className="form-select" value={form.type} onChange={(e) => set('type', e.target.value)}>
                {Object.entries(TYPE_LABELS).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Priority</label>
              <select className="form-select" value={form.priority} onChange={(e) => set('priority', e.target.value)}>
                {PRIORITIES.map((p) => (
                  <option key={p} value={p}>{p[0].toUpperCase() + p.slice(1)}</option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Team *</label>
              <select className="form-select" value={form.team_id} onChange={(e) => set('team_id', parseInt(e.target.value, 10))}>
                {teams.map((t) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Due date</label>
              <input
                className="form-input"
                type="date"
                value={form.due_date}
                onChange={(e) => set('due_date', e.target.value)}
              />
            </div>
          </div>

          <div className="form-hint">
            An Idempotency-Key is generated automatically so a double-click won't create two items.
          </div>

          <button className="btn btn-primary" disabled={loading} style={{ marginTop: 16 }}>
            {loading ? 'Creating…' : 'Create item'}
          </button>
        </form>
      </div>
    </div>
  )
}
