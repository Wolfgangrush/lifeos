import React, { useState } from 'react';

const priorityLabel = {
  high: 'High',
  medium: 'Medium',
  low: 'Low',
};

function TaskItem({ task, onDelete }) {
  const description = (task.description || '').trim();
  const due = task.deadline
    ? new Date(task.deadline).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    : null;
  const handleDelete = async () => {
    const confirmed = window.confirm(`Remove this task?\n\n${description}`);
    if (!confirmed) {
      return;
    }
    await onDelete(task.id);
  };

  return (
    <article className={`task-item priority-${task.priority || 'medium'}`}>
      <div className="task-main">
        <div className={task.status === 'completed' ? 'task-check done' : 'task-check'}></div>
        <div>
          <h4>{description}</h4>
          <div className="task-meta">
            <span>{priorityLabel[task.priority] || 'Medium'}</span>
            {task.category && <span>{task.category}</span>}
            {due && <span>Due {due}</span>}
            {task.focus_required && <span>Focus</span>}
          </div>
        </div>
        <button type="button" className="task-remove" onClick={handleDelete}>
          Remove
        </button>
      </div>
    </article>
  );
}

function sameDay(value, date) {
  return value?.slice(0, 10) === date;
}

function afterDay(value, date) {
  return value && value.slice(0, 10) > date;
}

export function TaskBoard({ tasks, selectedDate, isToday = true, onCreateTask, onDeleteTask }) {
  const [newTask, setNewTask] = useState('');
  const [saving, setSaving] = useState(false);
  const createTask = onCreateTask || (() => Promise.resolve());
  const deleteTask = onDeleteTask || (() => Promise.resolve());
  const visibleTasks = tasks.filter(t => (t.description || '').trim());
  const pending = visibleTasks.filter(task => {
    const createdBeforeEnd = !selectedDate || !task.created_at || task.created_at.slice(0, 10) <= selectedDate;
    const stillOpenThen = task.status === 'pending' || afterDay(task.completed_at, selectedDate);
    return createdBeforeEnd && stillOpenThen;
  });
  const completed = selectedDate
    ? visibleTasks.filter(task => task.status === 'completed' && sameDay(task.completed_at, selectedDate))
    : visibleTasks.filter(task => task.status === 'completed');
  const handleCreate = async (event) => {
    event.preventDefault();
    const description = newTask.trim();
    if (!description) {
      return;
    }
    setSaving(true);
    try {
      await createTask(description);
      setNewTask('');
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <p className="section-kicker">Tasks</p>
          <h3>{isToday ? 'Open work' : 'Task history'}</h3>
        </div>
        <div className="badge-row">
          <span className="count-badge">{pending.length} open</span>
          <span className="count-badge success">{completed.length} done</span>
        </div>
      </div>

      {isToday && (
        <form className="task-create" onSubmit={handleCreate}>
          <input
            type="text"
            value={newTask}
            onChange={(event) => setNewTask(event.target.value)}
            placeholder="Add a task"
            aria-label="New task"
          />
          <button type="submit" disabled={saving || !newTask.trim()}>
            {saving ? 'Adding' : 'Add'}
          </button>
        </form>
      )}

      <div className="task-columns">
        <div className="task-list">
          <div className="subheading">{isToday ? 'Pending now' : 'Open on this day'}</div>
          {pending.length === 0 ? (
            <p className="empty-state">No pending tasks.</p>
          ) : (
            pending.map(task => <TaskItem key={task.id} task={task} onDelete={deleteTask} />)
          )}
        </div>

        <div className="task-list">
          <div className="subheading">Completed that day</div>
          {completed.length === 0 ? (
            <p className="empty-state">No completed tasks yet.</p>
          ) : (
            completed.slice(0, 12).map(task => <TaskItem key={task.id} task={task} onDelete={deleteTask} />)
          )}
        </div>
      </div>
    </section>
  );
}
