import React from 'react';

function renderInlineMarkdown(text) {
  const parts = String(text || '').split(/(\*\*[^*]+\*\*)/g);

  return parts.map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    return <React.Fragment key={index}>{part}</React.Fragment>;
  });
}

function MarkdownText({ text }) {
  if (!text) return null;

  const lines = String(text)
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean);

  const blocks = [];
  let listItems = [];

  const flushList = () => {
    if (listItems.length) {
      blocks.push(
        <ul className="markdown-list" key={`list-${blocks.length}`}>
          {listItems.map((item, index) => (
            <li key={index}>{renderInlineMarkdown(item)}</li>
          ))}
        </ul>
      );
      listItems = [];
    }
  };

  lines.forEach((line) => {
    const listMatch = line.match(/^[-*]\s+(.+)$/);
    const numberedMatch = line.match(/^\d+\.\s+(.+)$/);
    const item = listMatch?.[1] || numberedMatch?.[1];

    if (item) {
      listItems.push(item);
      return;
    }

    flushList();
    blocks.push(
      <p className="markdown-paragraph" key={`p-${blocks.length}`}>
        {renderInlineMarkdown(line)}
      </p>
    );
  });

  flushList();

  return <div className="markdown-text">{blocks}</div>;
}

function InsightBlock({ title, items, renderItem }) {
  if (!items || items.length === 0) return null;

  return (
    <div className="coach-insight-block">
      <h4>{title}</h4>
      <div className="coach-insight-list">
        {items.slice(0, 3).map((item, index) => (
          <div className="coach-insight-item" key={`${title}-${index}`}>
            {renderItem(item)}
          </div>
        ))}
      </div>
    </div>
  );
}

export function CoachPanel({ analysis }) {
  const note = analysis?.data?.note;
  const taskInsights = analysis?.data?.task_intelligence || [];
  const foodInsights = analysis?.data?.food_intelligence || [];
  const energyInsights = analysis?.data?.energy_intelligence || [];
  const timestamp = analysis?.timestamp
    ? new Date(analysis.timestamp).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
    : null;

  return (
    <section className="panel coach-panel">
      <div className="panel-heading">
        <div>
          <p className="section-kicker">Coach</p>
          <h3>Life performance analysis</h3>
        </div>
        {timestamp && <span className="timestamp">{timestamp}</span>}
      </div>

      {note ? (
        <>
          <div className="coach-note">
            <MarkdownText text={note} />
          </div>

          <div className="coach-insights">
            <InsightBlock
              title="Task intelligence"
              items={taskInsights}
              renderItem={(item) => (
                <>
                  <strong>{item.task}</strong>
                  <span>
                    {[item.domain, item.complexity, item.estimated_hours ? `${item.estimated_hours} hours` : null]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                  {item.coach_note && <MarkdownText text={item.coach_note} />}
                </>
              )}
            />

            <InsightBlock
              title="Food intelligence"
              items={foodInsights}
              renderItem={(item) => (
                <>
                  <strong>{item.meal}</strong>
                  <span>
                    {[item.calories ? `${item.calories} kcal` : null, item.energy_impact, item.health_score ? `score ${item.health_score}/10` : null]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                  {item.coach_note && <MarkdownText text={item.coach_note} />}
                </>
              )}
            />

            <InsightBlock
              title="Energy pattern"
              items={energyInsights}
              renderItem={(item) => (
                <>
                  <strong>{item.pattern || 'Pattern pending'}</strong>
                  <span>
                    {[item.peak_hours ? `peak ${item.peak_hours}` : null, item.low_hours ? `low ${item.low_hours}` : null, item.next_crash ? `next dip ${item.next_crash}` : null]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                  {item.coach_note && <MarkdownText text={item.coach_note} />}
                </>
              )}
            />
          </div>
        </>
      ) : (
        <p className="empty-state">No coach analysis saved yet. The automation engine runs this every hour.</p>
      )}
    </section>
  );
}
