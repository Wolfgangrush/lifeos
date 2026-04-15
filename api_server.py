#!/usr/bin/env python3
"""
FastAPI Backend for Life OS
Serves data to the frontend dashboard with WebSocket support
"""

import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from database import Database, TaskStatus
import json
from pydantic import BaseModel

# Timezone handling utilities
from zoneinfo import ZoneInfo
import pytz

def _ensure_utc(dt):
    """Ensure datetime is timezone-aware UTC"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(ZoneInfo("UTC"))

def _to_iso_utc(dt):
    """Convert datetime to ISO string in UTC"""
    if dt is None:
        return None
    return _ensure_utc(dt).isoformat()


load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Life OS API")

# CORS middleware - configurable via environment
_allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database instance
db = Database()

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Client connected. Total connections: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"Client disconnected. Total connections: {len(self.active_connections)}")
    
    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients"""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                disconnected.append(connection)
        
        # Clean up disconnected clients
        for connection in disconnected:
            if connection in self.active_connections:
                self.active_connections.remove(connection)

manager = ConnectionManager()


class TaskCreateRequest(BaseModel):
    description: str
    priority: str = "medium"
    category: str = "misc"
    focus_required: bool = False
    deadline: Optional[str] = None

# Routes

@app.get("/")
async def root():
    return {"message": "Life OS API", "status": "running"}

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

# Task endpoints

@app.get("/api/tasks")
async def get_tasks(
    status: Optional[str] = Query(None, description="Filter by status: pending, completed, cancelled"),
    limit: int = Query(100, le=1000)
):
    """Get tasks with optional filtering"""
    task_status = TaskStatus(status) if status else None
    tasks = db.get_tasks(status=task_status, limit=limit)
    return {"tasks": [task.to_dict() for task in tasks]}

@app.post("/api/tasks")
async def create_task(payload: TaskCreateRequest):
    """Create a pending task."""
    description = payload.description.strip()
    if not description:
        return JSONResponse(status_code=400, content={"error": "Task description is required"})

    task = db.create_task(
        description=description,
        priority=payload.priority,
        category=payload.category,
        focus_required=payload.focus_required,
        deadline=payload.deadline,
    )

    await manager.broadcast({
        "type": "task_created",
        "data": task.to_dict()
    })

    return task.to_dict()

@app.get("/api/tasks/{task_id}")
async def get_task(task_id: int):
    """Get a specific task"""
    session = db.get_session()
    try:
        from database import Task
        task = session.query(Task).filter(Task.id == task_id).first()
        if not task:
            return JSONResponse(status_code=404, content={"error": "Task not found"})
        return task.to_dict()
    finally:
        session.close()

@app.post("/api/tasks/{task_id}/complete")
async def complete_task(task_id: int):
    """Mark a task as complete"""
    task = db.update_task_status(task_id, TaskStatus.COMPLETED)
    if not task:
        return JSONResponse(status_code=404, content={"error": "Task not found"})
    
    # Broadcast update
    await manager.broadcast({
        "type": "task_updated",
        "data": task.to_dict()
    })
    
    return task.to_dict()

@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: int):
    """Delete a task."""
    task = db.delete_task(task_id)
    if not task:
        return JSONResponse(status_code=404, content={"error": "Task not found"})

    await manager.broadcast({
        "type": "task_deleted",
        "data": task.to_dict()
    })

    return {"deleted": True, "task": task.to_dict()}


@app.get("/api/milestones")
async def get_milestones(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = Query(100, le=1000)
):
    start = datetime.fromisoformat(start_date) if start_date else None
    end = datetime.fromisoformat(end_date) if end_date else None
    milestones = db.get_milestones(start_date=start, end_date=end, limit=limit)
    return {"milestones": [milestone.to_dict() for milestone in milestones]}


@app.get("/api/board/today")
async def get_today_board():
    board_date = datetime.now().date().isoformat()
    entries = db.get_court_board(board_date)
    return {"date": board_date, "entries": [entry.to_dict() for entry in entries]}

@app.get("/api/board/{date}")
async def get_board_by_date(date: str):
    """Get court board for a specific date (YYYY-MM-DD format)"""
    try:
        # Validate date format
        from datetime import datetime
        datetime.fromisoformat(date)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "Invalid date format. Use YYYY-MM-DD"})
    
    entries = db.get_court_board(date)
    return {"date": date, "entries": [entry.to_dict() for entry in entries]}

@app.get("/api/board/dates")
async def get_available_board_dates():
    """Get all dates that have board entries"""
    session = db.get_session()
    try:
        from database import CourtBoardEntry
        from sqlalchemy import func
        
        dates = session.query(
            CourtBoardEntry.board_date,
            func.count(CourtBoardEntry.id).label('count')
        ).group_by(
            CourtBoardEntry.board_date
        ).order_by(
            CourtBoardEntry.board_date.desc()
        ).limit(30).all()
        
        return {"dates": [{"date": d, "count": c} for d, c in dates]}
    finally:
        session.close()


@app.post("/api/board/{entry_id}/over")
async def mark_board_entry_over(entry_id: int):
    entry = db.mark_board_entry_over(datetime.now().date().isoformat(), entry_id=entry_id)
    if not entry:
        return JSONResponse(status_code=404, content={"error": "Board entry not found"})
    await manager.broadcast({"type": "board_updated", "data": entry.to_dict()})
    return entry.to_dict()


@app.get("/api/saved")
async def get_saved_items(limit: int = Query(100, le=1000)):
    items = db.get_saved_items(limit=limit)
    return {"items": [item.to_dict() for item in items]}


@app.get("/api/expenses")
async def get_expenses(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = Query(100, le=1000)
):
    start = datetime.fromisoformat(start_date) if start_date else None
    end = datetime.fromisoformat(end_date) if end_date else None
    expenses = db.get_expenses(start_date=start, end_date=end, limit=limit)
    return {
        "expenses": [expense.to_dict() for expense in expenses],
        "total": sum(expense.amount for expense in expenses),
    }

# Food endpoints

@app.get("/api/food")
async def get_food_logs(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = Query(100, le=1000)
):
    """Get food logs with date filtering"""
    start = datetime.fromisoformat(start_date) if start_date else None
    end = datetime.fromisoformat(end_date) if end_date else None
    
    food_logs = db.get_food_logs(start_date=start, end_date=end, limit=limit)
    return {"food_logs": [log.to_dict() for log in food_logs]}

@app.get("/api/food/today")
async def get_todays_food():
    """Get today's food logs"""
    today = datetime.now().date()
    start = datetime.combine(today, datetime.min.time())
    end = datetime.combine(today, datetime.max.time())
    
    food_logs = db.get_food_logs(start_date=start, end_date=end)
    return {"food_logs": [log.to_dict() for log in food_logs]}

@app.delete("/api/food/{food_id}")
async def delete_food_log(food_id: int):
    """Delete a food log."""
    food = db.delete_food_log(food_id)
    if not food:
        return JSONResponse(status_code=404, content={"error": "Food log not found"})

    await manager.broadcast({
        "type": "food_deleted",
        "data": food.to_dict()
    })

    return {"deleted": True, "food": food.to_dict()}

# Energy endpoints

@app.get("/api/energy")
async def get_energy_levels(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    predicted_only: bool = False,
    limit: int = Query(100, le=1000)
):
    """Get energy levels with filtering"""
    start = datetime.fromisoformat(start_date) if start_date else None
    end = datetime.fromisoformat(end_date) if end_date else None
    
    energy_levels = db.get_energy_levels(
        start_date=start,
        end_date=end,
        predicted_only=predicted_only,
        limit=limit
    )
    return {"energy_levels": [level.to_dict() for level in energy_levels]}

@app.get("/api/energy/today")
async def get_todays_energy():
    """Get today's energy levels (actual and predicted)"""
    today = datetime.now().date()
    start = datetime.combine(today, datetime.min.time())
    end = datetime.combine(today, datetime.max.time())
    
    energy_levels = db.get_energy_levels(start_date=start, end_date=end)
    return {"energy_levels": [level.to_dict() for level in energy_levels]}

@app.get("/api/energy/peak-time")
async def get_peak_energy_time():
    """Get the user's typical peak energy time"""
    peak_time = db.get_peak_energy_time()
    return {"peak_time": peak_time}

# Health endpoints

@app.get("/api/health-logs")
async def get_health_logs(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = Query(100, le=1000)
):
    """Get health logs"""
    session = db.get_session()
    try:
        from database import HealthLog
        query = session.query(HealthLog)
        
        if start_date:
            query = query.filter(HealthLog.timestamp >= datetime.fromisoformat(start_date))
        if end_date:
            query = query.filter(HealthLog.timestamp <= datetime.fromisoformat(end_date))
        
        query = query.order_by(HealthLog.timestamp.desc()).limit(limit)
        health_logs = query.all()
        
        return {"health_logs": [log.to_dict() for log in health_logs]}
    finally:
        session.close()

# Summary and stats endpoints

@app.get("/api/summary/today")
async def get_todays_summary():
    """Get today's summary"""
    today = datetime.now().date()
    summary = db.get_daily_summary(today)
    return summary

@app.get("/api/summary/{date}")
async def get_daily_summary(date: str):
    """Get daily summary for a specific date"""
    try:
        target_date = datetime.fromisoformat(date).date()
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "Invalid date format"})
    
    summary = db.get_daily_summary(target_date)
    return summary

@app.get("/api/activity-days")
async def get_activity_days(limit: int = Query(45, le=180)):
    """Get recent calendar days that have tasks, food, energy, or health data."""
    session = db.get_session()
    try:
        from database import EnergyLevel, FoodLog, HealthLog, Task

        days = {}

        def ensure_day(day):
            return days.setdefault(day, {
                "date": day,
                "completed": 0,
                "food": 0,
                "energy": 0,
                "health": 0,
            })

        completed_tasks = (
            session.query(Task.completed_at)
            .filter(Task.completed_at.isnot(None))
            .order_by(Task.completed_at.desc())
            .limit(limit * 10)
            .all()
        )
        for (completed_at,) in completed_tasks:
            day = completed_at.date().isoformat()
            ensure_day(day)["completed"] += 1

        food_logs = (
            session.query(FoodLog.timestamp)
            .order_by(FoodLog.timestamp.desc())
            .limit(limit * 10)
            .all()
        )
        for (timestamp,) in food_logs:
            day = timestamp.date().isoformat()
            ensure_day(day)["food"] += 1

        energy_logs = (
            session.query(EnergyLevel.timestamp)
            .order_by(EnergyLevel.timestamp.desc())
            .limit(limit * 10)
            .all()
        )
        for (timestamp,) in energy_logs:
            day = timestamp.date().isoformat()
            ensure_day(day)["energy"] += 1

        health_logs = (
            session.query(HealthLog.timestamp)
            .order_by(HealthLog.timestamp.desc())
            .limit(limit * 10)
            .all()
        )
        for (timestamp,) in health_logs:
            day = timestamp.date().isoformat()
            ensure_day(day)["health"] += 1

        ordered = sorted(days.values(), key=lambda item: item["date"], reverse=True)
        return {"days": ordered[:limit]}
    finally:
        session.close()

@app.get("/api/stats")
async def get_stats():
    """Get weekly statistics"""
    stats = db.get_weekly_stats()
    return stats

@app.get("/api/stats/weekly")
async def get_weekly_stats():
    """Get detailed weekly statistics"""
    return db.get_weekly_stats()

@app.get("/api/coach/latest")
async def get_latest_coach_analysis():
    """Get the latest saved life coach analysis."""
    session = db.get_session()
    try:
        from database import SystemEvent
        event = (
            session.query(SystemEvent)
            .filter(SystemEvent.event_type == "hourly_life_coach_analysis")
            .order_by(SystemEvent.timestamp.desc())
            .first()
        )
        return {"analysis": event.to_dict() if event else None}
    finally:
        session.close()

# Timeline endpoint (combined view)

@app.get("/api/timeline")
async def get_timeline(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """Get combined timeline of all events"""
    start = datetime.fromisoformat(start_date) if start_date else (datetime.now() - timedelta(days=7))
    end = datetime.fromisoformat(end_date) if end_date else datetime.now()
    
    # Get all data
    tasks = db.get_tasks()
    food_logs = db.get_food_logs(start_date=start, end_date=end)
    energy_levels = db.get_energy_levels(start_date=start, end_date=end)
    
    # Combine into timeline
    timeline = []
    
    for task in tasks:
        if task.created_at >= start and task.created_at <= end:
            timeline.append({
                "type": "task",
                "timestamp": task.created_at.isoformat(),
                "data": task.to_dict()
            })
    
    for log in food_logs:
        timeline.append({
            "type": "food",
            "timestamp": log.timestamp.isoformat(),
            "data": log.to_dict()
        })
    
    for level in energy_levels:
        timeline.append({
            "type": "energy",
            "timestamp": level.timestamp.isoformat(),
            "data": level.to_dict()
        })
    
    # Sort by timestamp
    timeline.sort(key=lambda x: x["timestamp"], reverse=True)
    
    return {"timeline": timeline}

# WebSocket endpoint

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket connection for real-time updates"""
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive and receive any client messages
            data = await websocket.receive_text()
            
            # Echo back or handle client messages if needed
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# Broadcast helper (called from other services)

async def broadcast_update(update_type: str, data: dict):
    """
    Broadcast an update to all connected WebSocket clients
    Called from bot or automation services
    """
    await manager.broadcast({
        "type": update_type,
        "data": data,
        "timestamp": datetime.now().isoformat()
    })

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv('API_PORT', 8000))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")

# Auto-refresh endpoint
@app.post("/api/refresh")
async def trigger_refresh():
    """Trigger manual intelligence refresh and return results"""
    from automation import AutomationEngine
    
    automation = AutomationEngine()
    result = await automation.run_hourly_intelligence()
    
    # Broadcast update to all connected clients
    await manager.broadcast({
        "type": "refresh_complete",
        "data": result
    })
    
    return result
