import { useEffect, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { api, ApiError } from '../api/client'
import { Spinner, EmptyState, ErrorState } from '../components/States.jsx'
import { StatusBadge, PriorityBadge, TYPE_LABELS } from '../components/Badges.jsx'

// Valid next statuses per current status (the backend is the source of truth;
// this only decides which buttons to render).
const NEXT_STATUSES = {
  open: ['in_progress'],
  in_progress: ['awaiting_approval'],
  awaiting_approval: ['resolved', 'in_progress'],
  resolved: ['closed', 'in_progress'],
  closed: [],
}
const STATUS_LABEL = {
  open: 'Open', in_progress: 'In Progress', awaiting_approval: 'Awaiting Approval',
  resolved: 'Resolved', closed: 'Closed',
}

function fmtDate(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return iso
  }
}

export default function WorkItemDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const [item, setItem] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [actionError, setActionError] = useState('')
  const [actionInfo, setActionInfo] = useState('')
  const [comment, setComment] = useState('')
  const [commentSending, setCommentSending] = useState(false)
  const [editing, setEditing] = useState(false)
  const [assignModal, setAssignModal] = useState(false)

  const role = (() => {
    if (!item) return null
    if (user?.is_admin) return 'admin'
    const m = user?.memberships?.find((m) => m.team_id === item.team_id)
    return m?.role || null
  })()

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const d = await api.getItem(id)
      setItem(d)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => { load() }, [load])

  const handleApiError = (err, fallback) => {
    if (err instanceof ApiError) {
      if (err.status === 409) {
        setActionError('This item changed since you loaded it. Reload to get the latest version.')
      } else {
        setActionError(err.message)
      }
    } else {
      setActionError(fallback || 'Action failed.')
    }
  }

  // Actions with optimistic UI reconciliation & rollback
  const doClaim = async () => {
    setActionError('')
    setActionInfo('')
    const previous = { ...item }

    // 1. Optimistically update local UI state immediately
    setItem(prev => ({
      ...prev,
      assignee_id: user?.id,
      assignee_name: user?.name,
      version: prev.version + 1,
    }))

    try {
      const updated = await api.claimItem(id)
      setItem(updated)
      setActionInfo('Item claimed successfully.')
      load()
    } catch (err) {
      // 2. Rollback to snapshot on conflict or error
      setItem(previous)
      if (err instanceof ApiError && err.status === 409) {
        setActionError('Claim conflict: This item was already claimed or updated by another user. Reloading latest state...')
        setTimeout(() => load(), 1200)
      } else {
        handleApiError(err, 'Could not claim item.')
      }
    }
  }

  const doTransition = async (target) => {
    setActionError('')
    setActionInfo('')
    const previous = { ...item }

    // 1. Optimistically update local UI state immediately
    setItem(prev => ({
      ...prev,
      status: target,
      version: prev.version + 1,
    }))

    try {
      const updated = await api.transitionItem(id, target)
      setItem(updated)
      setActionInfo(`Moved to ${STATUS_LABEL[target] || target}.`)
      load()
    } catch (err) {
      // 2. Rollback to snapshot on rejection (e.g. 403 or 409)
      setItem(previous)
      if (err instanceof ApiError && err.status === 409) {
        setActionError(`Transition conflict: The item was updated concurrently. Reloading latest state...`)
        setTimeout(() => load(), 1200)
      } else if (err instanceof ApiError && err.status === 403) {
        setActionError(`Permission denied: Your role cannot execute this transition. Reverted.`)
      } else {
        handleApiError(err, 'Transition rejected.')
      }
    }
  }

  const submitComment = async (e) => {
    e.preventDefault()
    setActionError(''); setActionInfo('')
    if (!comment.trim()) return
    setCommentSending(true)
    try {
      await api.addComment(id, comment.trim())
      setComment('')
      load()
    } catch (err) { handleApiError(err, 'Could not add comment.') }
    finally { setCommentSending(false) }
  }

  if (loading) return <Spinner label="Loading item…" />
  if (error) return <ErrorState message={error} />
  if (!item) return <EmptyState title="Item not found" />

  const canClaim = !item.assignee_id && role && role !== 'viewer'
  const canAssign = role && ['lead', 'admin'].includes(role)
  const canEdit = role === 'admin' || role === 'lead' ||
    (role === 'member' && (item.creator_id === user?.id || item.assignee_id === user?.id))

  return (
    <div>
      <div className="topbar">
        <div>
          <button className="btn btn-ghost btn-sm" onClick={() => navigate('/items')} style={{ marginBottom: 8 }}>
            ‹ Back to items
          </button>
          <div className="page-title truncate" style={{ maxWidth: 600 }}>{item.title}</div>
          <div className="page-sub">{TYPE_LABELS[item.type] || item.type} · #{item.id} · v{item.version}</div>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {canClaim && <button className="btn btn-secondary" onClick={doClaim}>Claim</button>}
          {canAssign && <button className="btn btn-secondary" onClick={() => setAssignModal(true)}>Assign</button>}
          {canEdit && <button className="btn btn-secondary" onClick={() => setEditing(true)}>Edit</button>}
        </div>
      </div>

      {actionError && <div className="alert alert-error">{actionError}{' '}
        {actionError.includes('Reload') && <button className="btn btn-sm btn-secondary" onClick={load}>Reload now</button>}
      </div>}
      {actionInfo && <div className="alert alert-success">{actionInfo}</div>}

      <div className="detail-grid">
        {/* Left column: details + comments */}
        <div>
          <div className="card" style={{ marginBottom: 20 }}>
            <div className="detail-meta-row">
              <StatusBadge status={item.status} />
              <PriorityBadge priority={item.priority} />
              <span className="badge" style={{ background: '#f1f5f9', color: '#475569' }}>
                {item.team_name || `Team #${item.team_id}`}
              </span>
            </div>

            <div className="meta-grid">
              <div className="meta-item">
                <span className="meta-label">Assignee</span>
                <span className="meta-value">{item.assignee_name || 'Unassigned'}</span>
              </div>
              <div className="meta-item">
                <span className="meta-label">Created by</span>
                <span className="meta-value">{item.creator_name || `#${item.creator_id}`}</span>
              </div>
              <div className="meta-item">
                <span className="meta-label">Due date</span>
                <span className="meta-value">{item.due_date || '—'}</span>
              </div>
              <div className="meta-item">
                <span className="meta-label">Updated</span>
                <span className="meta-value">{fmtDate(item.updated_at)}</span>
              </div>
            </div>

            <div className="divider" />
            <div className="section-title">Description</div>
            <div style={{ whiteSpace: 'pre-wrap', fontSize: 14, color: 'var(--text)' }}>
              {item.description || <span className="text-muted">No description provided.</span>}
            </div>
          </div>

          {/* Workflow transitions */}
          <div className="card" style={{ marginBottom: 20 }}>
            <div className="section-title">Workflow</div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {(NEXT_STATUSES[item.status] || []).length === 0 && (
                <span className="text-muted">This item is closed — no further transitions.</span>
              )}
              {(NEXT_STATUSES[item.status] || []).map((s) => {
                const isApprove = s === 'resolved' && item.status === 'awaiting_approval'
                return (
                  <button
                    key={s}
                    className={`btn ${isApprove ? 'btn-primary' : 'btn-secondary'}`}
                    onClick={() => doTransition(s)}
                  >
                    {isApprove ? 'Approve & Resolve' : `Move to ${STATUS_LABEL[s] || s}`}
                  </button>
                )
              })}
            </div>
            {role === 'member' && item.status === 'awaiting_approval' && (
              <div className="form-hint" style={{ marginTop: 8 }}>
                Only a Lead or Admin can approve. You can still send it back if you're a member.
              </div>
            )}
          </div>

          {/* Comments */}
          <div className="card">
            <div className="section-title">Comments</div>
            {(!item.comments || item.comments.length === 0) && (
              <div className="text-muted" style={{ fontSize: 13, marginBottom: 12 }}>No comments yet.</div>
            )}
            {item.comments?.map((c) => (
              <div className="comment-item" key={c.id}>
                <div>
                  <span className="comment-author">{c.author_name || `User #${c.author_id}`}</span>
                  <span className="comment-time">{fmtDate(c.created_at)}</span>
                </div>
                <div className="comment-body">{c.body}</div>
              </div>
            ))}
            {role && role !== 'viewer' && (
              <form onSubmit={submitComment} style={{ marginTop: 12, display: 'flex', gap: 8 }}>
                <input
                  className="form-input"
                  placeholder="Write a comment…"
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                />
                <button className="btn btn-primary" disabled={commentSending || !comment.trim()}>
                  {commentSending ? '…' : 'Post'}
                </button>
              </form>
            )}
          </div>
        </div>

        {/* Right column: activity feed */}
        <div className="card">
          <div className="section-title">Activity history</div>
          <div className="activity-feed">
            {(item.activity || []).slice().reverse().map((e) => (
              <div className="activity-item" key={e.id}>
                <div className="activity-dot" />
                <div className="activity-body">
                  <div className="activity-type">
                    {e.event_type.replace(/_/g, ' ')}
                    {e.field ? ` · ${e.field}` : ''}
                  </div>
                  {e.old_value !== null || e.new_value !== null ? (
                    <div className="activity-detail">
                      {e.old_value || '∅'} → {e.new_value || '∅'}
                    </div>
                  ) : null}
                  <div className="activity-time">
                    {e.actor_name || 'System'} · {fmtDate(e.created_at)}
                  </div>
                </div>
              </div>
            ))}
            {(!item.activity || item.activity.length === 0) && (
              <div className="text-muted" style={{ fontSize: 13 }}>No activity yet.</div>
            )}
          </div>
        </div>
      </div>

      {editing && (
        <EditModal
          item={item}
          onClose={() => setEditing(false)}
          onSaved={(msg) => { setEditing(false); setActionInfo(msg); load() }}
          onError={(msg) => { setEditing(false); setActionError(msg); load() }}
        />
      )}

      {assignModal && (
        <AssignModal
          item={item}
          onClose={() => setAssignModal(false)}
          onAssigned={() => { setAssignModal(false); setActionInfo('Assignee updated.'); load() }}
          onError={(msg) => { setAssignModal(false); setActionError(msg); load() }}
        />
      )}
    </div>
  )
}

// Edit modal with optimistic locking check
function EditModal({ item, onClose, onSaved, onError }) {
  const [form, setForm] = useState({
    title: item.title,
    description: item.description || '',
    type: item.type,
    priority: item.priority,
    due_date: item.due_date || '',
  })
  const [saving, setSaving] = useState(false)
  const [localErr, setLocalErr] = useState('')

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))

  const save = async (e) => {
    e.preventDefault()
    setSaving(true); setLocalErr('')
    try {
      await api.updateItem(item.id, {
        title: form.title,
        description: form.description,
        type: form.type,
        priority: form.priority,
        due_date: form.due_date || null,
        version: item.version, // optimistic lock token
      })
      onSaved('Item updated.')
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setLocalErr('This item was edited by someone else. Reload to get the latest version before editing.')
      } else {
        setLocalErr(err.message)
        onError(err.message)
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-title">Edit work item</div>
        {localErr && <div className="alert alert-error">{localErr}</div>}
        <form onSubmit={save}>
          <div className="form-group">
            <label className="form-label">Title</label>
            <input className="form-input" value={form.title} onChange={(e) => set('title', e.target.value)} required />
          </div>
          <div className="form-group">
            <label className="form-label">Description</label>
            <textarea className="form-textarea" value={form.description} onChange={(e) => set('description', e.target.value)} />
          </div>
          <div className="meta-grid">
            <div className="form-group">
              <label className="form-label">Type</label>
              <select className="form-select" value={form.type} onChange={(e) => set('type', e.target.value)}>
                {Object.entries(TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Priority</label>
              <select className="form-select" value={form.priority} onChange={(e) => set('priority', e.target.value)}>
                {['low', 'medium', 'high', 'critical'].map((p) => (
                  <option key={p} value={p}>{p[0].toUpperCase() + p.slice(1)}</option>
                ))}
              </select>
            </div>
          </div>
          <div className="form-group">
            <label className="form-label">Due date</label>
            <input className="form-input" type="date" value={form.due_date} onChange={(e) => set('due_date', e.target.value)} />
          </div>
          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={onClose} type="button">Cancel</button>
            <button className="btn btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
          </div>
        </form>
      </div>
    </div>
  )
}

// Assign modal
function AssignModal({ item, onClose, onAssigned, onError }) {
  const [assigneeId, setAssigneeId] = useState('')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')

  const save = async (e) => {
    e.preventDefault()
    setSaving(true); setErr('')
    try {
      await api.assignItem(item.id, parseInt(assigneeId, 10))
      onAssigned()
    } catch (err) {
      setErr(err instanceof ApiError ? err.message : 'Failed to assign.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-title">Assign / reassign</div>
        {err && <div className="alert alert-error">{err}</div>}
        <form onSubmit={save}>
          <div className="form-group">
            <label className="form-label">Assignee user ID</label>
            <input
              className="form-input"
              type="number"
              value={assigneeId}
              onChange={(e) => setAssigneeId(e.target.value)}
              placeholder="e.g. 2"
              required
              autoFocus
            />
            <div className="form-hint">
              The user must be a member of the item's team ({item.team_name || `#${item.team_id}`}).
            </div>
          </div>
          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={onClose} type="button">Cancel</button>
            <button className="btn btn-primary" disabled={saving || !assigneeId}>{saving ? 'Saving…' : 'Assign'}</button>
          </div>
        </form>
      </div>
    </div>
  )
}
