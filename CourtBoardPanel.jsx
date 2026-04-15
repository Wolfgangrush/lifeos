import React from 'react';

function trimText(value, max = 220) {
  const text = (value || '').trim();
  return text.length > max ? `${text.slice(0, max - 3)}...` : text;
}

export function CourtBoardPanel({ board, milestones, expenses, savedItems, onMarkBoardOver }) {
  const entries = board?.entries || [];
  const pending = entries.filter(entry => !entry.is_over);
  const done = entries.filter(entry => entry.is_over);
  const totalExpense = expenses.reduce((sum, expense) => sum + Number(expense.amount || 0), 0);

  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <p className="section-kicker">Office</p>
          <h3>High Court board</h3>
        </div>
        <div className="badge-row">
          <span className="count-badge">{pending.length} pending</span>
          <span className="count-badge success">{done.length} over</span>
        </div>
      </div>

      <div className="board-layout">
        <div className="board-list">
          {entries.length === 0 ? (
            <p className="empty-state">No board saved for today.</p>
          ) : (
            entries.map(entry => (
              <article key={entry.id} className={entry.is_over ? 'board-item over' : 'board-item'}>
                <div className="board-line">
                  <strong>No. {entry.serial_no || entry.id}</strong>
                  <span>Court {entry.court_no || '-'}</span>
                  <span>{entry.case_no || '-'}</span>
                </div>
                <p>{trimText(entry.title)}</p>
                {!entry.is_over && (
                  <button type="button" onClick={() => onMarkBoardOver(entry.id)}>
                    Mark over
                  </button>
                )}
              </article>
            ))
          )}
        </div>

        <aside className="office-side">
          <div className="mini-section">
            <div className="subheading">Milestones</div>
            {milestones.length === 0 ? (
              <p className="muted">No milestones yet.</p>
            ) : (
              milestones.slice(0, 5).map(item => (
                <div className="mini-row" key={item.id}>
                  <span>{item.title}</span>
                  <strong>{item.hours ? `${item.hours}h` : item.category}</strong>
                </div>
              ))
            )}
          </div>

          <div className="mini-section">
            <div className="subheading">Expenses</div>
            <div className="mini-row total">
              <span>Today</span>
              <strong>Rs {totalExpense.toLocaleString('en-IN')}</strong>
            </div>
            {expenses.slice(0, 4).map(expense => (
              <div className="mini-row" key={expense.id}>
                <span>{expense.description}</span>
                <strong>Rs {Number(expense.amount || 0).toLocaleString('en-IN')}</strong>
              </div>
            ))}
          </div>

          <div className="mini-section">
            <div className="subheading">Stuff for later</div>
            {savedItems.length === 0 ? (
              <p className="muted">Nothing saved yet.</p>
            ) : (
              savedItems.slice(0, 4).map(item => (
                <div className="mini-row" key={item.id}>
                  <span>{trimText(item.content || item.file_path || item.item_type, 48)}</span>
                  <strong>{item.item_type}</strong>
                </div>
              ))
            )}
          </div>
        </aside>
      </div>
    </section>
  );
}
