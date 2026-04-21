import React, { useState, useEffect } from 'react';
import { TaskBoard } from './TaskBoard';
import { EnergyChart } from './EnergyChart';
import { FoodTimeline } from './FoodTimeline';
import { DailySummary } from './DailySummary';
import { CoachPanel } from './CoachPanel';
import { CourtBoardPanel } from './CourtBoardPanel';
import { useWebSocket } from './useWebSocket';
import { useData } from './useData';

const todayString = () => {
  const now = new Date();
  const offset = now.getTimezoneOffset();
  return new Date(now.getTime() - offset * 60 * 1000).toISOString().slice(0, 10);
};

function formatSelectedDate(date) {
  return new Date(`${date}T12:00:00`).toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

function App() {
  const [selectedDate, setSelectedDate] = useState(todayString());
  const {
    tasks,
    energy,
    food,
    summary,
    stats,
    activityDays,
    coachAnalysis,
    board,
    milestones,
    expenses,
    savedItems,
    loading,
    refreshAll,
    createTask,
    deleteTask,
    deleteFood,
    createFood,
    updateFood,
    markBoardOver,
  } = useData(selectedDate);
  const { isConnected, lastMessage, error: wsError } = useWebSocket('ws://127.0.0.1:8000/ws');
  const isToday = selectedDate === todayString();

  useEffect(() => {
    if (lastMessage) {
      refreshAll();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastMessage]);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">LO</div>
          <div>
            <h1>Life OS</h1>
            <p>{new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' })}</p>
          </div>
        </div>

        <div className="ws-status" title={isConnected ? 'WebSocket connected' : wsError || 'WebSocket disconnected'}>
          <span className={`ws-indicator ${isConnected ? 'connected' : 'disconnected'}`}></span>
          <span className="ws-text">{isConnected ? 'Live' : 'Offline'}</span>
        </div>

        <div className="calendar-control" aria-label="Calendar">
          <label htmlFor="selected-date">Calendar</label>
          <input
            id="selected-date"
            type="date"
            value={selectedDate}
            onChange={(event) => setSelectedDate(event.target.value)}
          />
          {!isToday && (
            <button
              type="button"
              className="today-button"
              onClick={() => setSelectedDate(todayString())}
            >
              Today
            </button>
          )}
        </div>

        <div className={isConnected ? 'connection online' : 'connection offline'}>
          <span></span>
          {isConnected ? 'Live' : 'Offline'}
        </div>
      </header>

      <main className="page">
        <section className="page-intro">
          <div>
            <p className="eyebrow">Local command center</p>
            <h2>Today at a glance</h2>
            <p className="selected-day">{formatSelectedDate(selectedDate)}</p>
          </div>
          <button type="button" className="refresh-button" onClick={refreshAll}>
            {loading ? 'Refreshing...' : 'Refresh'}
          </button>
        </section>

        {activityDays.length > 0 && (
          <section className="history-strip" aria-label="Recent days">
            <span>History</span>
            {activityDays.slice(0, 10).map(day => (
              <button
                key={day.date}
                type="button"
                className={selectedDate === day.date ? 'history-day active' : 'history-day'}
                onClick={() => setSelectedDate(day.date)}
              >
                <strong>{new Date(`${day.date}T12:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</strong>
                <small>{day.completed} done</small>
              </button>
            ))}
          </section>
        )}

        <div className="dashboard-grid">
          <div className="span-all">
            <DailySummary summary={summary} stats={stats} selectedDate={selectedDate} />
          </div>

          <div className="span-all">
            <CourtBoardPanel
              board={board}
              milestones={milestones}
              expenses={expenses}
              savedItems={savedItems}
              onMarkBoardOver={markBoardOver}
            />
          </div>

          <div className="span-two">
            <TaskBoard tasks={tasks} selectedDate={selectedDate} isToday={isToday} onCreateTask={createTask} onDeleteTask={deleteTask} />
          </div>

          <div>
            <EnergyChart energy={energy} selectedDate={selectedDate} />
          </div>

          <div className="span-all">
            <FoodTimeline
              food={food}
              selectedDate={selectedDate}
              onDeleteFood={deleteFood}
              onCreateFood={createFood}
              onUpdateFood={updateFood}
            />
          </div>

          <div className="span-all">
            <CoachPanel analysis={coachAnalysis} />
          </div>

          <div className="span-all">
            <DailySummary summary={summary} stats={stats} selectedDate={selectedDate} fullView />
          </div>
        </div>
      </main>
    </div>
  );
}

export default App;
