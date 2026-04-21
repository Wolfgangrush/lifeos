import React, { useState } from 'react';

function macroTone(value) {
  if (value === 'high') return 'red';
  if (value === 'medium') return 'amber';
  if (value === 'low') return 'green';
  return 'neutral';
}

function Macro({ label, value }) {
  if (!value) return null;
  return (
    <span className={`macro ${macroTone(value)}`}>
      {label}: {value}
    </span>
  );
}

function caloriesFor(log) {
  return log.macros?.calories || log.energy_prediction?.calories || null;
}

function FoodForm({ onSubmit, onCancel, initialValues = {} }) {
  const [items, setItems] = useState(initialValues.items?.join(', ') || '');
  const [time, setTime] = useState(() => {
    if (initialValues.timestamp) {
      const date = new Date(initialValues.timestamp);
      return date.toTimeString().slice(0, 5);
    }
    return new Date().toTimeString().slice(0, 5);
  });
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    const itemsList = items.split(',').map(s => s.trim()).filter(Boolean);
    if (itemsList.length === 0) return;

    setSaving(true);
    try {
      // Create full timestamp with selected time
      const timestamp = new Date();
      const [hours, minutes] = time.split(':');
      timestamp.setHours(parseInt(hours), parseInt(minutes), 0, 0);

      await onSubmit({
        items: itemsList,
        timestamp: timestamp.toISOString(),
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="food-form" onSubmit={handleSubmit}>
      <div className="form-row">
        <label>What did you eat?</label>
        <input
          type="text"
          value={items}
          onChange={(e) => setItems(e.target.value)}
          placeholder="e.g., rice, dal, vegetables"
          autoFocus
        />
      </div>
      <div className="form-row">
        <label>What time?</label>
        <input
          type="time"
          value={time}
          onChange={(e) => setTime(e.target.value)}
        />
      </div>
      <div className="form-actions">
        <button type="submit" disabled={saving || !items.trim()}>
          {saving ? 'Saving...' : (initialValues.id ? 'Update' : 'Add')}
        </button>
        <button type="button" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export function FoodTimeline({ food, onDeleteFood, onCreateFood, onUpdateFood }) {
  const visible = food.filter(log => (log.items || []).some(item => String(item || '').trim()));
  const deleteFood = onDeleteFood || (() => Promise.resolve());
  const createFood = onCreateFood || (() => Promise.resolve());
  const updateFood = onUpdateFood || (() => Promise.resolve());

  const [showAddForm, setShowAddForm] = useState(false);
  const [editingLog, setEditingLog] = useState(null);

  const handleDelete = async (log) => {
    const items = (log.items || []).join(', ');
    const confirmed = window.confirm(`Remove this food log?\n\n${items}`);
    if (!confirmed) {
      return;
    }
    await deleteFood(log.id);
  };

  const handleCreate = async (data) => {
    await createFood(data);
    setShowAddForm(false);
  };

  const handleUpdate = async (data) => {
    await updateFood(editingLog.id, data);
    setEditingLog(null);
  };

  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <p className="section-kicker">Food</p>
          <h3>Food intake</h3>
        </div>
        <div className="panel-actions">
          <span className="count-badge">{food.length} logged</span>
          <button
            type="button"
            className="add-button"
            onClick={() => setShowAddForm(!showAddForm)}
          >
            {showAddForm ? '−' : '+ Add Food'}
          </button>
        </div>
      </div>

      {showAddForm && (
        <FoodForm
          onSubmit={handleCreate}
          onCancel={() => setShowAddForm(false)}
        />
      )}

      {visible.length === 0 && !showAddForm ? (
        <p className="empty-state">No food logged for this day.</p>
      ) : (
        <div className="food-list">
          {visible.map(log => (
            <article className="food-item" key={log.id || log.timestamp}>
              {editingLog?.id === log.id ? (
                <div className="food-edit-form">
                  <FoodForm
                    initialValues={log}
                    onSubmit={handleUpdate}
                    onCancel={() => setEditingLog(null)}
                  />
                </div>
              ) : (
                <>
                  <div className="food-time">
                    <button
                      type="button"
                      className="time-edit"
                      onClick={() => setEditingLog(log)}
                      title="Edit time"
                    >
                      {new Date(log.timestamp).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}
                      <span>✎</span>
                    </button>
                  </div>
                  <div className="food-body">
                    <h4>{log.items.join(', ')}</h4>
                    {caloriesFor(log) && (
                      <div className="food-calories">{caloriesFor(log)} kcal</div>
                    )}

                    {/* Macro breakdown in grams */}
                    <div className="macro-row">
                      {log.macros?.protein_g && (
                        <span className="macro neutral">Protein: {log.macros.protein_g}g</span>
                      )}
                      {log.macros?.carbs_g && (
                        <span className="macro neutral">Carbs: {log.macros.carbs_g}g</span>
                      )}
                      {log.macros?.fat_g && (
                        <span className="macro neutral">Fat: {log.macros.fat_g}g</span>
                      )}
                    </div>

                    {/* Macro levels with color coding */}
                    <div className="macro-row">
                      <Macro label="Carbs" value={log.macros?.carbs} />
                      <Macro label="Protein" value={log.macros?.protein} />
                      <Macro label="Fat" value={log.macros?.fat} />
                    </div>

                    {/* Energy Impact Prediction */}
                    {log.energy_prediction?.energy_impact && (
                      <div className="energy-impact">
                        <span className="energy-label">Energy:</span>
                        <span className={`energy-value impact-${log.energy_prediction.energy_impact}`}>
                          {log.energy_prediction.energy_impact.replace('_', ' ')}
                        </span>
                        {log.energy_prediction.energy_timeline && (
                          <span className="energy-timeline">({log.energy_prediction.energy_timeline})</span>
                        )}
                      </div>
                    )}

                    {/* Health Score */}
                    {log.energy_prediction?.health_score !== undefined && (
                      <div className="health-score">
                        <span className="score-label">Health Score:</span>
                        <span className={`score-value ${log.energy_prediction.health_score >= 7 ? 'good' : log.energy_prediction.health_score >= 5 ? 'okay' : 'poor'}`}>
                          {log.energy_prediction.health_score}/10
                        </span>
                      </div>
                    )}

                    {log.energy_prediction?.health_note && (
                      <p className="food-note">{log.energy_prediction.health_note}</p>
                    )}
                    {log.energy_prediction?.analysis && (
                      <p className="food-analysis">{log.energy_prediction.analysis}</p>
                    )}
                    {log.energy_prediction?.status && log.energy_prediction.status !== 'stable' && (
                      <div className={log.energy_prediction.status === 'crash_warning' ? 'notice warning compact' : 'notice compact'}>
                        <strong>{log.energy_prediction.status === 'crash_warning' ? '⚠️ Energy crash expected' : 'Energy support'}</strong>
                        <span>{log.energy_prediction.message}</span>
                      </div>
                    )}
                  </div>
                  <button type="button" className="item-remove" onClick={() => handleDelete(log)}>
                    Remove
                  </button>
                </>
              )}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
