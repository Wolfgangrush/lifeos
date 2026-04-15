import React from 'react';

const formatEnergy = (value) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return 'No data';
  }
  return `${Number(value).toFixed(1)}/10`;
};

function Metric({ label, value, tone }) {
  return (
    <div className={`metric ${tone || ''}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function efficiencyValue(summary) {
  const completed = summary?.tasks_completed || 0;
  const pending = summary?.tasks_pending || 0;
  const total = completed + pending;
  if (!total) {
    return 'No task data';
  }
  const taskScore = (completed / total) * 70;
  const energyScore = ((summary?.avg_energy || 0) / 10) * 30;
  return `${Math.round(taskScore + energyScore)}%`;
}

function ProgressRow({ label, value }) {
  const clamped = Math.max(0, Math.min(100, value || 0));
  return (
    <div className="progress-row">
      <div className="progress-label">
        <span>{label}</span>
        <strong>{Math.round(clamped)}%</strong>
      </div>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${clamped}%` }}></div>
      </div>
    </div>
  );
}

export function DailySummary({ summary, stats, selectedDate, fullView = false }) {
  if (!summary && !stats) {
    return (
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="section-kicker">Summary</p>
            <h3>Loading</h3>
          </div>
        </div>
      </section>
    );
  }

  const totalTasks = (stats?.tasks_completed || 0) + (stats?.tasks_pending || 0);
  const completionRate = totalTasks ? ((stats?.tasks_completed || 0) / totalTasks) * 100 : 0;
  const energyLabel = summary?.energy_source === 'forecast' ? 'Energy forecast' : 'Energy';

  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <p className="section-kicker">Summary</p>
          <h3>Daily snapshot</h3>
        </div>
        <span className="timestamp">
          {new Date(`${selectedDate || new Date().toISOString().slice(0, 10)}T12:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
        </span>
      </div>

      <div className="metrics-grid">
        <Metric label="Tasks done" value={summary?.tasks_completed || 0} tone="success" />
        <Metric label="Pending" value={summary?.tasks_pending || 0} tone="warn" />
        <Metric label="Meals" value={summary?.meals_logged || 0} tone="info" />
        <Metric label="Steps" value={summary?.steps_total || 0} tone="success" />
        <Metric label={energyLabel} value={formatEnergy(summary?.avg_energy)} tone="energy" />
        <Metric label="Efficiency" value={efficiencyValue(summary)} tone="info" />
      </div>

      {!fullView && (
        <div className="insight-strip">
          <strong>Next useful signal</strong>
          <span>
            {summary?.tasks_pending
              ? `${summary.tasks_pending} task${summary.tasks_pending === 1 ? '' : 's'} waiting.`
              : 'No pending tasks in the current list.'}
            {summary?.avg_energy ? ` Average energy is ${formatEnergy(summary.avg_energy)}.` : ''}
          </span>
        </div>
      )}

      {fullView && (
        <div className="details-grid">
          <div className="detail-block">
            <h4>Weekly work</h4>
            <ProgressRow label="Completion rate" value={stats?.completion_rate ?? completionRate} />
            <dl className="definition-list">
              <div>
                <dt>Completed</dt>
                <dd>{stats?.tasks_completed || 0}</dd>
              </div>
              <div>
                <dt>Current streak</dt>
                <dd>{stats?.current_streak || 0} days</dd>
              </div>
            </dl>
          </div>

          <div className="detail-block">
            <h4>Energy pattern</h4>
            <dl className="definition-list">
              <div>
                <dt>Average</dt>
                <dd>{formatEnergy(stats?.avg_energy)}</dd>
              </div>
              <div>
                <dt>Peak time</dt>
                <dd>{stats?.peak_energy_time || 'No data'}</dd>
              </div>
              <div>
                <dt>Low time</dt>
                <dd>{stats?.low_energy_time || 'No data'}</dd>
              </div>
            </dl>
          </div>

          <div className="detail-block">
            <h4>Food</h4>
            <dl className="definition-list">
              <div>
                <dt>Meals this week</dt>
                <dd>{stats?.meals_logged || 0}</dd>
              </div>
              <div>
                <dt>Most common</dt>
                <dd>{stats?.top_food || 'No data'}</dd>
              </div>
            </dl>
          </div>

          <div className="detail-block">
            <h4>Today</h4>
            <div className="pill-row">
              {(summary?.top_foods || []).map(item => (
                <span className="pill" key={item}>{item}</span>
              ))}
              {(summary?.supplements || []).map(item => (
                <span className="pill green" key={item}>{item}</span>
              ))}
              {!(summary?.top_foods || []).length && !(summary?.supplements || []).length && (
                <span className="muted">No entries yet.</span>
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
