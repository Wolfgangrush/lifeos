import { useState, useEffect, useCallback } from 'react';

const API_URL = 'http://127.0.0.1:8000/api';

function dayBounds(date) {
  return {
    start: `${date}T00:00:00`,
    end: `${date}T23:59:59.999999`,
  };
}

export function useData(selectedDate) {
  const [tasks, setTasks] = useState([]);
  const [energy, setEnergy] = useState([]);
  const [food, setFood] = useState([]);
  const [summary, setSummary] = useState(null);
  const [stats, setStats] = useState(null);
  const [activityDays, setActivityDays] = useState([]);
  const [coachAnalysis, setCoachAnalysis] = useState(null);
  const [board, setBoard] = useState({ entries: [] });
  const [milestones, setMilestones] = useState([]);
  const [expenses, setExpenses] = useState([]);
  const [savedItems, setSavedItems] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchTasks = useCallback(async () => {
    try {
      const response = await fetch(`${API_URL}/tasks`);
      const data = await response.json();
      setTasks(data.tasks || []);
    } catch (error) {
      console.error('Error fetching tasks:', error);
    }
  }, []);

  const fetchEnergy = useCallback(async () => {
    try {
      const { start, end } = dayBounds(selectedDate);
      const response = await fetch(`${API_URL}/energy?start_date=${encodeURIComponent(start)}&end_date=${encodeURIComponent(end)}`);
      const data = await response.json();
      setEnergy(data.energy_levels || []);
    } catch (error) {
      console.error('Error fetching energy:', error);
    }
  }, [selectedDate]);

  const fetchFood = useCallback(async () => {
    try {
      const { start, end } = dayBounds(selectedDate);
      const response = await fetch(`${API_URL}/food?start_date=${encodeURIComponent(start)}&end_date=${encodeURIComponent(end)}`);
      const data = await response.json();
      setFood(data.food_logs || []);
    } catch (error) {
      console.error('Error fetching food:', error);
    }
  }, [selectedDate]);

  const fetchSummary = useCallback(async () => {
    try {
      const response = await fetch(`${API_URL}/summary/${selectedDate}`);
      const data = await response.json();
      setSummary(data);
    } catch (error) {
      console.error('Error fetching summary:', error);
    }
  }, [selectedDate]);

  const fetchStats = useCallback(async () => {
    try {
      const response = await fetch(`${API_URL}/stats`);
      const data = await response.json();
      setStats(data);
    } catch (error) {
      console.error('Error fetching stats:', error);
    }
  }, []);

  const fetchActivityDays = useCallback(async () => {
    try {
      const response = await fetch(`${API_URL}/activity-days?limit=45`);
      const data = await response.json();
      setActivityDays(data.days || []);
    } catch (error) {
      console.error('Error fetching activity days:', error);
    }
  }, []);

  const fetchCoachAnalysis = useCallback(async () => {
    try {
      const response = await fetch(`${API_URL}/coach/latest`);
      const data = await response.json();
      setCoachAnalysis(data.analysis || null);
    } catch (error) {
      console.error('Error fetching coach analysis:', error);
    }
  }, []);

  const fetchBoard = useCallback(async () => {
    try {
      const response = await fetch(`${API_URL}/board/today`);
      const data = await response.json();
      setBoard(data || { entries: [] });
    } catch (error) {
      console.error('Error fetching court board:', error);
    }
  }, []);

  const fetchMilestones = useCallback(async () => {
    try {
      const { start, end } = dayBounds(selectedDate);
      const response = await fetch(`${API_URL}/milestones?start_date=${encodeURIComponent(start)}&end_date=${encodeURIComponent(end)}`);
      const data = await response.json();
      setMilestones(data.milestones || []);
    } catch (error) {
      console.error('Error fetching milestones:', error);
    }
  }, [selectedDate]);

  const fetchExpenses = useCallback(async () => {
    try {
      const { start, end } = dayBounds(selectedDate);
      const response = await fetch(`${API_URL}/expenses?start_date=${encodeURIComponent(start)}&end_date=${encodeURIComponent(end)}`);
      const data = await response.json();
      setExpenses(data.expenses || []);
    } catch (error) {
      console.error('Error fetching expenses:', error);
    }
  }, [selectedDate]);

  const fetchSavedItems = useCallback(async () => {
    try {
      const response = await fetch(`${API_URL}/saved?limit=20`);
      const data = await response.json();
      setSavedItems(data.items || []);
    } catch (error) {
      console.error('Error fetching saved items:', error);
    }
  }, []);

  const refreshAll = useCallback(async () => {
    setLoading(true);
    await Promise.all([
      fetchTasks(),
      fetchEnergy(),
      fetchFood(),
      fetchSummary(),
      fetchStats(),
      fetchActivityDays(),
      fetchCoachAnalysis(),
      fetchBoard(),
      fetchMilestones(),
      fetchExpenses(),
      fetchSavedItems(),
    ]);
    setLoading(false);
  }, [fetchTasks, fetchEnergy, fetchFood, fetchSummary, fetchStats, fetchActivityDays, fetchCoachAnalysis, fetchBoard, fetchMilestones, fetchExpenses, fetchSavedItems]);

  const deleteTask = useCallback(async (taskId) => {
    const response = await fetch(`${API_URL}/tasks/${taskId}`, { method: 'DELETE' });
    if (!response.ok) {
      throw new Error(`Failed to delete task ${taskId}`);
    }
    await refreshAll();
  }, [refreshAll]);

  const createTask = useCallback(async (description) => {
    const response = await fetch(`${API_URL}/tasks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ description }),
    });
    if (!response.ok) {
      throw new Error('Failed to create task');
    }
    await refreshAll();
  }, [refreshAll]);

  const deleteFood = useCallback(async (foodId) => {
    const response = await fetch(`${API_URL}/food/${foodId}`, { method: 'DELETE' });
    if (!response.ok) {
      throw new Error(`Failed to delete food log ${foodId}`);
    }
    await refreshAll();
  }, [refreshAll]);

  const markBoardOver = useCallback(async (entryId) => {
    const response = await fetch(`${API_URL}/board/${entryId}/over`, { method: 'POST' });
    if (!response.ok) {
      throw new Error(`Failed to mark board entry ${entryId} over`);
    }
    await refreshAll();
  }, [refreshAll]);

  useEffect(() => {
    refreshAll();
    // No polling - rely on WebSocket updates for real-time data
  }, [refreshAll]);

  return {
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
    markBoardOver,
  };
}
