export function Spinner({ label }) {
  return (
    <div className="spinner-wrap">
      <div style={{ textAlign: 'center' }}>
        <div className="spinner" style={{ margin: '0 auto 8px' }} />
        {label && <div className="text-muted">{label}</div>}
      </div>
    </div>
  )
}

export function EmptyState({ icon, title = 'Nothing here', sub }) {
  return (
    <div className="empty-state">
      <div className="empty-icon">
        {icon || (
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ opacity: 0.4 }}>
            <rect x="2" y="7" width="20" height="14" rx="2" ry="2"></rect>
            <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"></path>
          </svg>
        )}
      </div>
      <div className="empty-title">{title}</div>
      {sub && <div className="empty-sub">{sub}</div>}
    </div>
  )
}

export function ErrorState({ message }) {
  return (
    <div className="alert alert-error">{message || 'Something went wrong. Please try again.'}</div>
  )
}
