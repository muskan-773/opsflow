const STATUS_LABELS = {
  open: 'Open',
  in_progress: 'In Progress',
  awaiting_approval: 'Awaiting Approval',
  resolved: 'Resolved',
  closed: 'Closed',
}

const PRIORITY_LABELS = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  critical: 'Critical',
}

export function StatusBadge({ status }) {
  const cls = `badge badge-status-${status}`
  return <span className={cls}>{STATUS_LABELS[status] || status}</span>
}

export function PriorityBadge({ priority }) {
  const cls = `badge badge-priority-${priority}`
  return <span className={cls}>{PRIORITY_LABELS[priority] || priority}</span>
}

export const TYPE_LABELS = {
  incident: 'Incident',
  customer_issue: 'Customer Issue',
  payment: 'Payment',
  compliance: 'Compliance',
  task: 'Task',
}
