import React from 'react';

function energyState(level) {
  if (level >= 8) return 'strong';
  if (level >= 6) return 'steady';
  if (level >= 4) return 'low';
  return 'critical';
}

export function EnergyChart({ energy }) {
  const actual = energy.filter(e => !e.predicted);
  const predicted = energy.filter(e => e.predicted);
  const forecast = [...predicted].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
  const latestActual = actual[0] || actual[actual.length - 1];
  const latestForecast = forecast.find(entry => new Date(entry.timestamp) >= new Date()) || forecast[forecast.length - 1];
  const latest = latestActual || latestForecast;
  const energyBasis = actual.length ? actual : forecast;
  const avgEnergy = energyBasis.length
    ? energyBasis.reduce((sum, entry) => sum + entry.level, 0) / energyBasis.length
    : null;
  const visible = actual;
  const statusLabel = latestActual ? `${latestActual.level}/10` : latestForecast ? `${latestForecast.level}/10 forecast` : 'No data';

  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <p className="section-kicker">Energy</p>
          <h3>Energy level</h3>
        </div>
        <span className={`status-chip ${latest ? energyState(latest.level) : ''}`}>
          {statusLabel}
        </span>
      </div>

      <div className="energy-meter">
        <div>
          <span>Latest</span>
          <strong>{latest ? latest.level : '-'}</strong>
        </div>
        <div className="meter-track">
          <div
            className={`meter-fill ${latest ? energyState(latest.level) : ''}`}
            style={{ width: latest ? `${latest.level * 10}%` : '0%' }}
          ></div>
        </div>
        <small>{actual.length ? 'Average' : 'Forecast average'} {avgEnergy ? `${avgEnergy.toFixed(1)}/10` : 'No data'}</small>
      </div>

      <div className="timeline-list">
        <div className="subheading">Logged entries</div>
        {visible.length === 0 ? (
          <p className="empty-state">No energy entries yet.</p>
        ) : (
          visible.map(entry => (
            <div className="timeline-row" key={entry.id || entry.timestamp}>
              <time>{new Date(entry.timestamp).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}</time>
              <div className="mini-track">
                <div
                  className={`mini-fill ${energyState(entry.level)}`}
                  style={{ width: `${entry.level * 10}%` }}
                ></div>
              </div>
              <strong>{entry.level}</strong>
            </div>
          ))
        )}
      </div>

      {predicted.length > 0 && (
        <div className="forecast-block">
          <div className="subheading">Energy forecast</div>
          <div className="timeline-list">
            {forecast.map(entry => (
              <div className="timeline-row predicted" key={entry.id || entry.timestamp}>
                <time>{new Date(entry.timestamp).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}</time>
                <div className="mini-track">
                  <div
                    className={`mini-fill ${energyState(entry.level)}`}
                    style={{ width: `${entry.level * 10}%` }}
                  ></div>
                </div>
                <strong>{entry.level}</strong>
              </div>
            ))}
          </div>
          <span className="forecast-note">Forecasts are generated from food and supplement data. Log /energy to replace them with measured energy.</span>
        </div>
      )}
    </section>
  );
}
