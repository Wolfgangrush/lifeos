import React from 'react';

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

export function FoodTimeline({ food, onDeleteFood }) {
  const visible = food.filter(log => (log.items || []).some(item => String(item || '').trim()));
  const deleteFood = onDeleteFood || (() => Promise.resolve());

  const handleDelete = async (log) => {
    const items = (log.items || []).join(', ');
    const confirmed = window.confirm(`Remove this food log?\n\n${items}`);
    if (!confirmed) {
      return;
    }
    await deleteFood(log.id);
  };

  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <p className="section-kicker">Food</p>
          <h3>Food intake</h3>
        </div>
        <span className="count-badge">{food.length} logged</span>
      </div>

      {visible.length === 0 ? (
        <p className="empty-state">No food logged for this day.</p>
      ) : (
        <div className="food-list">
          {visible.map(log => (
            <article className="food-item" key={log.id || log.timestamp}>
              <div className="food-time">
                {new Date(log.timestamp).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}
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
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
