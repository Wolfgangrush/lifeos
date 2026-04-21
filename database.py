#!/usr/bin/env python3
"""
Database models and operations for Life OS
Uses SQLite with SQLAlchemy ORM
"""

import os
import json
import logging

logger = logging.getLogger(__name__)


from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional, Dict
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text, Float, JSON, or_, Index, event, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy import desc, func
from contextlib import contextmanager
from sqlalchemy.exc import SQLAlchemyError

Base = declarative_base()

class TaskStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class TaskPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

# Models

class Task(Base):
    __tablename__ = 'tasks'
    
    id = Column(Integer, primary_key=True)
    description = Column(String, nullable=False)
    status = Column(String, default=TaskStatus.PENDING)
    priority = Column(String, default=TaskPriority.MEDIUM)
    category = Column(String, default="misc")
    focus_required = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    completed_at = Column(DateTime, nullable=True)
    deadline = Column(DateTime, nullable=True)
    # Gemini's pre-completion estimate of effort (minutes).
    estimated_minutes = Column(Integer, nullable=True)
    # Actual effort the user spent on the task (minutes). Only set when the
    # user provides it explicitly on completion ("done in 20 min"), so the
    # efficiency metric stays honest — never auto-derived from wall clock.
    actual_minutes = Column(Integer, nullable=True)
    # Absolute path to an uploaded photo/doc/PDF that proves completion.
    evidence_path = Column(String, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'description': self.description,
            'status': self.status,
            'priority': self.priority,
            'category': self.category,
            'focus_required': self.focus_required,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'deadline': self.deadline.isoformat() if self.deadline else None,
            'estimated_minutes': self.estimated_minutes,
            'actual_minutes': self.actual_minutes,
            'evidence_path': self.evidence_path,
        }

class FoodLog(Base):
    __tablename__ = 'food_logs'
    
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.now)
    items = Column(JSON)  # List of food items
    macros = Column(JSON)  # {"carbs": "high", "protein": "medium", "fat": "low"}
    energy_prediction = Column(JSON)  # Prediction data
    
    def to_dict(self):
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'items': self.items,
            'macros': self.macros,
            'energy_prediction': self.energy_prediction,
        }

class EnergyLevel(Base):
    __tablename__ = 'energy_levels'
    
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.now)
    level = Column(Integer)  # 1-10 scale
    context = Column(String, nullable=True)
    predicted = Column(Boolean, default=False)  # True if predicted, False if actual
    
    def to_dict(self):
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'level': self.level,
            'context': self.context,
            'predicted': self.predicted,
        }

class HealthLog(Base):
    __tablename__ = 'health_logs'
    
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.now)
    supplements = Column(JSON)  # List of supplements taken
    metrics = Column(JSON)  # Other health metrics
    
    def to_dict(self):
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'supplements': self.supplements,
            'metrics': self.metrics,
        }

class Supplement(Base):
    __tablename__ = 'supplements'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    ingredients = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'ingredients': self.ingredients,
            'notes': self.notes,
            'active': self.active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

class SystemEvent(Base):
    __tablename__ = 'system_events'

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.now)
    event_type = Column(String)  # 'daily_summary', 'energy_prediction', etc.
    data = Column(JSON)
    triggered_by = Column(String, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'event_type': self.event_type,
            'data': self.data,
            'triggered_by': self.triggered_by,
        }

class Reminder(Base):
    __tablename__ = 'reminders'

    id = Column(Integer, primary_key=True)
    description = Column(String, nullable=False)
    reminder_type = Column(String)  # 'purchase', 'task', 'general'
    url = Column(String, nullable=True)  # For purchase reminders
    remind_at = Column(DateTime, nullable=True)  # When to remind
    created_at = Column(DateTime, default=datetime.now)
    is_active = Column(Boolean, default=True)
    completed = Column(Boolean, default=False)

    def to_dict(self):
        return {
            'id': self.id,
            'description': self.description,
            'reminder_type': self.reminder_type,
            'url': self.url,
            'remind_at': self.remind_at.isoformat() if self.remind_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'is_active': self.is_active,
            'completed': self.completed,
        }

class Milestone(Base):
    __tablename__ = 'milestones'

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    category = Column(String, default="office")
    hours = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'category': self.category,
            'hours': self.hours,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

class CourtBoardEntry(Base):
    __tablename__ = 'court_board_entries'

    id = Column(Integer, primary_key=True)
    board_date = Column(String, nullable=False, index=True)
    court_no = Column(String, nullable=True)
    serial_no = Column(Integer, nullable=True, index=True)
    case_no = Column(String, nullable=True)
    side = Column(String, nullable=True)
    title = Column(Text, nullable=False)
    remarks = Column(Text, nullable=True)
    is_over = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    completed_at = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'board_date': self.board_date,
            'court_no': self.court_no,
            'serial_no': self.serial_no,
            'case_no': self.case_no,
            'side': self.side,
            'title': self.title,
            'remarks': self.remarks,
            'is_over': self.is_over,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }

class SavedItem(Base):
    __tablename__ = 'saved_items'

    id = Column(Integer, primary_key=True)
    item_type = Column(String, default="text")
    content = Column(Text, nullable=True)
    file_path = Column(String, nullable=True)
    source = Column(String, default="telegram")
    tags = Column(JSON)
    created_at = Column(DateTime, default=datetime.now)

    def to_dict(self):
        return {
            'id': self.id,
            'item_type': self.item_type,
            'content': self.content,
            'file_path': self.file_path,
            'source': self.source,
            'tags': self.tags or [],
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

class ExpenseLog(Base):
    __tablename__ = 'expense_logs'

    id = Column(Integer, primary_key=True)
    amount = Column(Float, nullable=False)
    currency = Column(String, default="INR")
    description = Column(String, nullable=False)
    category = Column(String, default="misc")
    timestamp = Column(DateTime, default=datetime.now)

    def to_dict(self):
        return {
            'id': self.id,
            'amount': self.amount,
            'currency': self.currency,
            'description': self.description,
            'category': self.category,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
        }

# Database class


@contextmanager
def _transaction(session):
    """Context manager for safe database transactions with rollback on error"""
    try:
        yield session
        session.commit()
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Database transaction error: {e}")
        raise
    except Exception as e:
        session.rollback()
        logger.error(f"Unexpected error in transaction: {e}")
        raise
    finally:
        session.close()


class Database:
    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = os.getenv('DATABASE_PATH', 'data/life_os.db')
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        self.engine = create_engine(
            f'sqlite:///{db_path}',
            connect_args={
                "timeout": 30,
                "check_same_thread": False,
            },
        )

        @event.listens_for(self.engine, "connect")
        def configure_sqlite(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

        Base.metadata.create_all(self.engine)
        self._ensure_schema()
        self.SessionLocal = sessionmaker(bind=self.engine)

    def _ensure_schema(self):
        """Apply small SQLite migrations for existing local databases."""
        with self.engine.begin() as conn:
            task_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(tasks)")).fetchall()}
            if "category" not in task_columns:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN category VARCHAR DEFAULT 'misc'"))
            if "estimated_minutes" not in task_columns:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN estimated_minutes INTEGER"))
            if "actual_minutes" not in task_columns:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN actual_minutes INTEGER"))
            if "evidence_path" not in task_columns:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN evidence_path VARCHAR"))
    
    def get_session(self) -> Session:
        return self.SessionLocal()
    
    # Task operations
    
    def create_task(
        self,
        description: str,
        status: TaskStatus = TaskStatus.PENDING,
        priority: TaskPriority = TaskPriority.MEDIUM,
        category: str = "misc",
        focus_required: bool = False,
        deadline: str = None,
        completed_at: str = None
    ) -> Task:
        """Create a new task"""
        session = self.get_session()
        try:
            task = Task(
                description=description,
                status=status,
                priority=priority,
                category=category or "misc",
                focus_required=focus_required,
                completed_at=(
                    datetime.fromisoformat(completed_at)
                    if completed_at
                    else datetime.now() if status == TaskStatus.COMPLETED else None
                ),
                deadline=datetime.fromisoformat(deadline) if deadline else None
            )
            session.add(task)
            session.commit()
            session.refresh(task)
            return task
        finally:
            session.close()
    
    def get_tasks(
        self,
        status: TaskStatus = None,
        limit: int = 100
    ) -> List[Task]:
        """Get tasks with optional filtering"""
        session = self.get_session()
        try:
            query = session.query(Task)
            if status:
                query = query.filter(Task.status == status)
            query = query.order_by(desc(Task.created_at)).limit(limit)
            return query.all()
        finally:
            session.close()
    
    def update_task_status(self, task_id: int, status: TaskStatus, completed_at: str = None) -> Optional[Task]:
        """Update task status"""
        session = self.get_session()
        try:
            task = session.query(Task).filter(Task.id == task_id).first()
            if task:
                task.status = status
                if status == TaskStatus.COMPLETED:
                    task.completed_at = datetime.fromisoformat(completed_at) if completed_at else datetime.now()
                elif status == TaskStatus.PENDING:
                    # Uncompleting a task - clear the completed_at timestamp
                    task.completed_at = None
                session.commit()
                session.refresh(task)
            return task
        finally:
            session.close()

    def get_completed_tasks(self, limit: int = 50) -> List[Task]:
        """Get completed tasks"""
        session = self.get_session()
        try:
            return session.query(Task).filter(
                Task.status == TaskStatus.COMPLETED
            ).order_by(Task.completed_at.desc()).limit(limit).all()
        finally:
            session.close()
    
    def complete_task_by_description(self, description: str, completed_at: str = None) -> Optional[Task]:
        """Find and complete a task by description (fuzzy match)"""
        session = self.get_session()
        try:
            # Try exact match first
            task = session.query(Task).filter(
                Task.description.like(f"%{description}%"),
                Task.status == TaskStatus.PENDING
            ).first()

            if task:
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.fromisoformat(completed_at) if completed_at else datetime.now()
                session.commit()
                session.refresh(task)
            return task
        finally:
            session.close()

    def set_task_estimate(self, task_id: int, estimated_minutes: int) -> Optional[Task]:
        """Store Gemini's effort estimate on a task."""
        session = self.get_session()
        try:
            task = session.query(Task).filter(Task.id == task_id).first()
            if task:
                task.estimated_minutes = int(estimated_minutes) if estimated_minutes else None
                session.commit()
                session.refresh(task)
            return task
        finally:
            session.close()

    def set_task_actual_minutes(self, task_id: int, actual_minutes: int) -> Optional[Task]:
        """Store the user-reported actual effort in minutes."""
        session = self.get_session()
        try:
            task = session.query(Task).filter(Task.id == task_id).first()
            if task:
                task.actual_minutes = int(actual_minutes) if actual_minutes else None
                session.commit()
                session.refresh(task)
            return task
        finally:
            session.close()

    def set_task_evidence(self, task_id: int, evidence_path: str) -> Optional[Task]:
        """Attach an evidence file path (photo/doc/PDF) to the task."""
        session = self.get_session()
        try:
            task = session.query(Task).filter(Task.id == task_id).first()
            if task:
                task.evidence_path = evidence_path or None
                session.commit()
                session.refresh(task)
            return task
        finally:
            session.close()
    
    # Food operations
    
    def log_food(
        self,
        items: List[str],
        timestamp: str = None,
        macros: Dict = None,
        energy_prediction: Dict = None
    ) -> FoodLog:
        """Log food intake"""
        session = self.get_session()
        try:
            cleaned_items = [item for item in (items or []) if str(item).strip()]
            if not cleaned_items:
                raise ValueError("Cannot log food without items")
            logged_at = datetime.fromisoformat(timestamp) if timestamp else datetime.now()
            window_start = logged_at - timedelta(minutes=3)
            window_end = logged_at + timedelta(minutes=3)
            recent_logs = session.query(FoodLog).filter(
                FoodLog.timestamp >= window_start,
                FoodLog.timestamp <= window_end,
            ).all()
            normalized_items = sorted(str(item).strip().lower() for item in cleaned_items)
            for existing in recent_logs:
                existing_items = sorted(str(item).strip().lower() for item in (existing.items or []))
                if existing_items == normalized_items:
                    return existing

            food_log = FoodLog(
                items=cleaned_items,
                timestamp=logged_at,
                macros=macros or {},
                energy_prediction=energy_prediction or {}
            )
            session.add(food_log)
            session.commit()
            session.refresh(food_log)
            return food_log
        finally:
            session.close()

    def cleanup_empty_and_duplicate_food(self) -> Dict:
        session = self.get_session()
        try:
            logs = session.query(FoodLog).order_by(FoodLog.timestamp, FoodLog.id).all()
            seen = set()
            deleted_empty = 0
            deleted_duplicates = 0
            for log in logs:
                items = [str(item).strip().lower() for item in (log.items or []) if str(item).strip()]
                if not items:
                    session.delete(log)
                    deleted_empty += 1
                    continue
                minute_bucket = log.timestamp.replace(second=0, microsecond=0) if log.timestamp else None
                key = (tuple(sorted(items)), minute_bucket)
                if key in seen:
                    session.delete(log)
                    deleted_duplicates += 1
                    continue
                seen.add(key)
            session.commit()
            return {"empty": deleted_empty, "duplicates": deleted_duplicates}
        finally:
            session.close()
    
    def get_food_logs(
        self,
        start_date: datetime = None,
        end_date: datetime = None,
        limit: int = 100
    ) -> List[FoodLog]:
        """Get food logs with date filtering"""
        session = self.get_session()
        try:
            query = session.query(FoodLog)
            if start_date:
                query = query.filter(FoodLog.timestamp >= start_date)
            if end_date:
                query = query.filter(FoodLog.timestamp <= end_date)
            query = query.order_by(desc(FoodLog.timestamp)).limit(limit)
            return query.all()
        finally:
            session.close()

    def add_food_log(
        self,
        items: List[str],
        timestamp: datetime = None,
        macros: dict = None,
        energy_prediction: dict = None
    ) -> FoodLog:
        """Add a new food log"""
        session = self.get_session()
        try:
            food_log = FoodLog(
                items=items,
                timestamp=timestamp or datetime.now(),
                macros=macros,
                energy_prediction=energy_prediction
            )
            session.add(food_log)
            session.commit()
            session.refresh(food_log)
            return food_log
        finally:
            session.close()

    def update_food_log(self, food_id: int, **kwargs) -> Optional[FoodLog]:
        """Update an existing food log"""
        session = self.get_session()
        try:
            food_log = session.query(FoodLog).filter(FoodLog.id == food_id).first()
            if not food_log:
                return None

            for key, value in kwargs.items():
                if hasattr(food_log, key):
                    setattr(food_log, key, value)

            session.commit()
            session.refresh(food_log)
            return food_log
        finally:
            session.close()

    # Energy operations
    
    def log_energy(
        self,
        level: int,
        context: str = None,
        timestamp: str = None,
        predicted: bool = False
    ) -> EnergyLevel:
        """Log energy level"""
        session = self.get_session()
        try:
            energy = EnergyLevel(
                level=level,
                context=context,
                timestamp=datetime.fromisoformat(timestamp) if timestamp else datetime.now(),
                predicted=predicted
            )
            session.add(energy)
            session.commit()
            session.refresh(energy)
            return energy
        finally:
            session.close()
    
    def get_energy_levels(
        self,
        start_date: datetime = None,
        end_date: datetime = None,
        predicted_only: bool = False,
        limit: int = 100
    ) -> List[EnergyLevel]:
        """Get energy levels with filtering"""
        session = self.get_session()
        try:
            query = session.query(EnergyLevel)
            if start_date:
                query = query.filter(EnergyLevel.timestamp >= start_date)
            if end_date:
                query = query.filter(EnergyLevel.timestamp <= end_date)
            if predicted_only:
                query = query.filter(EnergyLevel.predicted == True)
            query = query.order_by(desc(EnergyLevel.timestamp)).limit(limit)
            return query.all()
        finally:
            session.close()
    
    def get_peak_energy_time(self) -> Optional[str]:
        """Get the hour when user typically has highest energy"""
        session = self.get_session()
        try:
            # Get last 7 days of actual (not predicted) energy data
            week_ago = datetime.now() - timedelta(days=7)
            energy_data = session.query(EnergyLevel).filter(
                EnergyLevel.timestamp >= week_ago,
                EnergyLevel.predicted == False
            ).all()
            
            if not energy_data:
                return None
            
            # Calculate average energy by hour
            hourly_energy = {}
            for entry in energy_data:
                hour = entry.timestamp.hour
                if hour not in hourly_energy:
                    hourly_energy[hour] = []
                hourly_energy[hour].append(entry.level)
            
            # Find hour with highest average
            best_hour = max(
                hourly_energy.items(),
                key=lambda x: sum(x[1]) / len(x[1])
            )[0]
            
            return f"{best_hour:02d}:00"
        finally:
            session.close()
    
    # Health operations

    def create_supplement(self, name: str, ingredients: str = None, notes: str = None) -> Supplement:
        session = self.get_session()
        try:
            normalized = name.strip()
            existing = session.query(Supplement).filter(func.lower(Supplement.name) == normalized.lower()).first()
            if existing:
                existing.ingredients = ingredients if ingredients is not None else existing.ingredients
                existing.notes = notes if notes is not None else existing.notes
                existing.active = True
                session.commit()
                session.refresh(existing)
                return existing

            supplement = Supplement(name=normalized, ingredients=ingredients, notes=notes, active=True)
            session.add(supplement)
            session.commit()
            session.refresh(supplement)
            return supplement
        finally:
            session.close()

    def get_supplements(self, active_only: bool = True) -> List[Supplement]:
        session = self.get_session()
        try:
            query = session.query(Supplement)
            if active_only:
                query = query.filter(Supplement.active == True)
            return query.order_by(Supplement.name).all()
        finally:
            session.close()

    def get_supplement(self, supplement_id: int) -> Optional[Supplement]:
        session = self.get_session()
        try:
            return session.query(Supplement).filter(Supplement.id == supplement_id).first()
        finally:
            session.close()

    def remove_supplement(self, supplement_id: int) -> Optional[Supplement]:
        session = self.get_session()
        try:
            supplement = session.query(Supplement).filter(Supplement.id == supplement_id).first()
            if supplement:
                supplement.active = False
                session.commit()
                session.refresh(supplement)
            return supplement
        finally:
            session.close()
    
    def log_health(
        self,
        supplements: List[str] = None,
        metrics: Dict = None,
        timestamp: str = None
    ) -> HealthLog:
        """Log health data"""
        session = self.get_session()
        try:
            health_log = HealthLog(
                supplements=supplements or [],
                metrics=metrics or {},
                timestamp=datetime.fromisoformat(timestamp) if timestamp else datetime.now()
            )
            session.add(health_log)
            session.commit()
            session.refresh(health_log)
            return health_log
        finally:
            session.close()

    def delete_task(self, task_id: int) -> Optional[Task]:
        session = self.get_session()
        try:
            task = session.query(Task).filter(Task.id == task_id).first()
            if task:
                snapshot = task.to_dict()
                session.delete(task)
                session.commit()
                deleted = Task(description=snapshot["description"])
                deleted.id = snapshot["id"]
                deleted.status = snapshot["status"]
                return deleted
            return None
        finally:
            session.close()

    def delete_food_log(self, food_id: int) -> Optional[FoodLog]:
        session = self.get_session()
        try:
            food_log = session.query(FoodLog).filter(FoodLog.id == food_id).first()
            if food_log:
                snapshot = food_log.to_dict()
                session.delete(food_log)
                session.commit()
                deleted = FoodLog(items=snapshot["items"], macros=snapshot["macros"], energy_prediction=snapshot["energy_prediction"])
                deleted.id = snapshot["id"]
                deleted.timestamp = datetime.fromisoformat(snapshot["timestamp"]) if snapshot["timestamp"] else None
                return deleted
            return None
        finally:
            session.close()

    def roll_over_incomplete_tasks(self, old_date: datetime.date = None) -> Dict:
        """
        Roll over incomplete tasks from the previous day to today.
        Updates deadlines to end of today and returns count of tasks rolled over.
        """
        if old_date is None:
            old_date = (datetime.now() - timedelta(days=1)).date()

        session = self.get_session()
        try:
            # Find incomplete tasks from the old date
            old_start = datetime.combine(old_date, datetime.min.time())
            old_end = datetime.combine(old_date, datetime.max.time())

            incomplete_tasks = session.query(Task).filter(
                Task.created_at <= old_end,
                Task.status == TaskStatus.PENDING,
                ~Task.description.ilike("Completed tasks from%")
            ).all()

            if not incomplete_tasks:
                return {"rolled_over": 0, "tasks": []}

            # Update deadlines to today
            today = datetime.now().date()
            today_end = datetime.combine(today, datetime.max.time())

            rolled_tasks = []
            for task in incomplete_tasks:
                # Only update if deadline is in the past or same as old date
                if task.deadline is None or task.deadline <= old_end:
                    task.deadline = today_end
                    rolled_tasks.append(task.description)

            session.commit()

            return {
                "rolled_over": len(rolled_tasks),
                "tasks": rolled_tasks,
                "new_deadline": today_end.isoformat()
            }
        finally:
            session.close()

    def get_tasks_overdue(self, hours: int = 24) -> List[Task]:
        """Get tasks that are overdue (past deadline and still pending)."""
        session = self.get_session()
        try:
            now = datetime.now()
            return session.query(Task).filter(
                Task.status == TaskStatus.PENDING,
                Task.deadline < now,
                ~Task.description.ilike("Completed tasks from%")
            ).all()
        finally:
            session.close()
    
    # Summary and stats operations
    
    def get_daily_summary(self, date: datetime.date) -> Dict:
        """Get aggregated data for a specific day"""
        session = self.get_session()
        try:
            start = datetime.combine(date, datetime.min.time())
            end = datetime.combine(date, datetime.max.time())
            
            # Tasks
            tasks_completed = session.query(Task).filter(
                Task.completed_at >= start,
                Task.completed_at <= end
            ).count()
            
            tasks_pending = session.query(Task).filter(
                Task.created_at <= end,
                or_(Task.status == TaskStatus.PENDING, Task.completed_at > end)
            ).count()
            
            # Food
            food_logs = session.query(FoodLog).filter(
                FoodLog.timestamp >= start,
                FoodLog.timestamp <= end
            ).all()
            
            meals_logged = len(food_logs)
            top_foods = []
            for log in food_logs:
                top_foods.extend(log.items)
            
            # Energy
            energy_logs = session.query(EnergyLevel).filter(
                EnergyLevel.timestamp >= start,
                EnergyLevel.timestamp <= end,
                EnergyLevel.predicted == False
            ).all()
            predicted_energy_logs = session.query(EnergyLevel).filter(
                EnergyLevel.timestamp >= start,
                EnergyLevel.timestamp <= end,
                EnergyLevel.predicted == True
            ).all()
            
            avg_energy = None
            min_energy = None
            max_energy = None
            energy_source = "none"
            
            if energy_logs:
                levels = [e.level for e in energy_logs]
                avg_energy = sum(levels) / len(levels)
                min_energy = min(levels)
                max_energy = max(levels)
                energy_source = "logged"
            elif predicted_energy_logs:
                levels = [e.level for e in predicted_energy_logs]
                avg_energy = sum(levels) / len(levels)
                min_energy = min(levels)
                max_energy = max(levels)
                energy_source = "forecast"
            
            # Health
            health_logs = session.query(HealthLog).filter(
                HealthLog.timestamp >= start,
                HealthLog.timestamp <= end
            ).all()

            milestones = session.query(Milestone).filter(
                Milestone.created_at >= start,
                Milestone.created_at <= end
            ).all()

            expenses = session.query(ExpenseLog).filter(
                ExpenseLog.timestamp >= start,
                ExpenseLog.timestamp <= end
            ).all()
            
            supplements = []
            steps_total = 0
            for log in health_logs:
                dose_map = (log.metrics or {}).get("supplement_doses", {}) if isinstance(log.metrics, dict) else {}
                for supplement in log.supplements or []:
                    dose = dose_map.get(supplement) or {}
                    quantity = dose.get("quantity")
                    unit = dose.get("unit")
                    if quantity:
                        unit_text = f" {unit}" if unit else ""
                        supplements.append(f"{supplement} x{quantity}{unit_text}")
                    else:
                        supplements.append(supplement)
                if isinstance(log.metrics, dict):
                    steps_total += int(log.metrics.get('steps') or 0)
            
            return {
                'tasks_completed': tasks_completed,
                'tasks_pending': tasks_pending,
                'meals_logged': meals_logged,
                'top_foods': list(set(top_foods))[:5],
                'avg_energy': avg_energy,
                'min_energy': min_energy,
                'max_energy': max_energy,
                'energy_source': energy_source,
                'supplements': list(dict.fromkeys(supplements)),
                'steps_total': steps_total,
                'milestones_count': len(milestones),
                'milestone_hours': sum(float(item.hours or 0) for item in milestones),
                'expense_total': sum(float(item.amount or 0) for item in expenses),
            }
        finally:
            session.close()
    
    def get_weekly_stats(self) -> Dict:
        """Get statistics for the past week"""
        session = self.get_session()
        try:
            week_ago = datetime.now() - timedelta(days=7)
            
            # Tasks
            tasks_completed = session.query(Task).filter(
                Task.completed_at >= week_ago,
                Task.status == TaskStatus.COMPLETED
            ).count()
            
            tasks_pending = session.query(Task).filter(
                Task.status == TaskStatus.PENDING
            ).count()
            
            total_tasks = tasks_completed + tasks_pending
            completion_rate = (tasks_completed / total_tasks * 100) if total_tasks > 0 else 0
            
            # Energy
            energy_logs = session.query(EnergyLevel).filter(
                EnergyLevel.timestamp >= week_ago,
                EnergyLevel.predicted == False
            ).all()
            
            avg_energy = 0
            peak_energy_time = "N/A"
            low_energy_time = "N/A"
            
            if energy_logs:
                levels = [e.level for e in energy_logs]
                avg_energy = sum(levels) / len(levels)
                
                # Find peak and low times
                hourly_energy = {}
                for entry in energy_logs:
                    hour = entry.timestamp.hour
                    if hour not in hourly_energy:
                        hourly_energy[hour] = []
                    hourly_energy[hour].append(entry.level)
                
                if hourly_energy:
                    avg_by_hour = {
                        hour: sum(levels) / len(levels)
                        for hour, levels in hourly_energy.items()
                    }
                    peak_hour = max(avg_by_hour.items(), key=lambda x: x[1])[0]
                    low_hour = min(avg_by_hour.items(), key=lambda x: x[1])[0]
                    peak_energy_time = f"{peak_hour:02d}:00"
                    low_energy_time = f"{low_hour:02d}:00"
            
            # Food
            food_logs = session.query(FoodLog).filter(
                FoodLog.timestamp >= week_ago
            ).all()
            
            meals_logged = len(food_logs)
            
            # Count food items
            food_counter = {}
            for log in food_logs:
                for item in log.items:
                    food_counter[item] = food_counter.get(item, 0) + 1
            
            top_food = max(food_counter.items(), key=lambda x: x[1])[0] if food_counter else "N/A"
            
            # Streak calculation
            current_streak = self._calculate_streak(session)
            
            return {
                'tasks_completed': tasks_completed,
                'tasks_pending': tasks_pending,
                'completion_rate': completion_rate,
                'avg_energy': avg_energy,
                'peak_energy_time': peak_energy_time,
                'low_energy_time': low_energy_time,
                'meals_logged': meals_logged,
                'top_food': top_food,
                'current_streak': current_streak,
            }
        finally:
            session.close()
    
    def _calculate_streak(self, session: Session) -> int:
        """Calculate current daily logging streak"""
        streak = 0
        current_date = datetime.now().date()
        
        while True:
            start = datetime.combine(current_date, datetime.min.time())
            end = datetime.combine(current_date, datetime.max.time())
            
            # Check if any data was logged this day
            has_data = (
                session.query(Task).filter(Task.created_at >= start, Task.created_at <= end).count() > 0
                or session.query(FoodLog).filter(FoodLog.timestamp >= start, FoodLog.timestamp <= end).count() > 0
                or session.query(EnergyLevel).filter(EnergyLevel.timestamp >= start, EnergyLevel.timestamp <= end).count() > 0
            )
            
            if has_data:
                streak += 1
                current_date -= timedelta(days=1)
            else:
                break
        
        return streak
    
    # System events
    
    def log_system_event(
        self,
        event_type: str,
        data: Dict,
        triggered_by: str = None
    ) -> SystemEvent:
        """Log a system event"""
        session = self.get_session()
        try:
            event = SystemEvent(
                event_type=event_type,
                data=data,
                triggered_by=triggered_by
            )
            session.add(event)
            session.commit()
            session.refresh(event)
            return event
        finally:
            session.close()

    # Milestone operations

    def create_milestone(
        self,
        title: str,
        category: str = "office",
        hours: float = None,
        notes: str = None,
    ) -> Milestone:
        session = self.get_session()
        try:
            milestone = Milestone(
                title=title.strip(),
                category=category or "office",
                hours=hours,
                notes=notes,
            )
            session.add(milestone)
            session.commit()
            session.refresh(milestone)
            return milestone
        finally:
            session.close()

    def get_milestones(
        self,
        start_date: datetime = None,
        end_date: datetime = None,
        limit: int = 100,
    ) -> List[Milestone]:
        session = self.get_session()
        try:
            query = session.query(Milestone)
            if start_date:
                query = query.filter(Milestone.created_at >= start_date)
            if end_date:
                query = query.filter(Milestone.created_at <= end_date)
            return query.order_by(desc(Milestone.created_at)).limit(limit).all()
        finally:
            session.close()

    # Court board operations

    def replace_court_board(self, board_date: str, entries: List[Dict]) -> List[CourtBoardEntry]:
        session = self.get_session()
        try:
            session.query(CourtBoardEntry).filter(CourtBoardEntry.board_date == board_date).delete()
            rows = []
            for entry in entries:
                row = CourtBoardEntry(
                    board_date=board_date,
                    court_no=entry.get("court_no"),
                    serial_no=entry.get("serial_no"),
                    case_no=entry.get("case_no"),
                    side=entry.get("side"),
                    title=entry.get("title") or entry.get("raw") or "",
                    remarks=entry.get("remarks"),
                    is_over=False,
                )
                session.add(row)
                rows.append(row)
            session.commit()
            for row in rows:
                session.refresh(row)
            return rows
        finally:
            session.close()

    def get_court_board(self, board_date: str, include_over: bool = True) -> List[CourtBoardEntry]:
        session = self.get_session()
        try:
            query = session.query(CourtBoardEntry).filter(CourtBoardEntry.board_date == board_date)
            if not include_over:
                query = query.filter(CourtBoardEntry.is_over == False)
            return query.order_by(CourtBoardEntry.serial_no.is_(None), CourtBoardEntry.serial_no, CourtBoardEntry.id).all()
        finally:
            session.close()

    def mark_board_entry_over(self, board_date: str, serial_no: int = None, entry_id: int = None) -> Optional[CourtBoardEntry]:
        session = self.get_session()
        try:
            query = session.query(CourtBoardEntry)
            if entry_id is not None:
                query = query.filter(CourtBoardEntry.id == entry_id)
            else:
                query = query.filter(
                    CourtBoardEntry.board_date == board_date,
                    CourtBoardEntry.serial_no == serial_no,
                )
            entry = query.first()
            if entry:
                entry.is_over = True
                entry.completed_at = datetime.now()
                session.commit()
                session.refresh(entry)
            return entry
        finally:
            session.close()

    # Saved item operations

    def create_saved_item(
        self,
        item_type: str = "text",
        content: str = None,
        file_path: str = None,
        source: str = "telegram",
        tags: List[str] = None,
    ) -> SavedItem:
        session = self.get_session()
        try:
            item = SavedItem(
                item_type=item_type,
                content=content,
                file_path=file_path,
                source=source,
                tags=tags or [],
            )
            session.add(item)
            session.commit()
            session.refresh(item)
            return item
        finally:
            session.close()

    def get_saved_items(self, limit: int = 100) -> List[SavedItem]:
        session = self.get_session()
        try:
            return session.query(SavedItem).order_by(desc(SavedItem.created_at)).limit(limit).all()
        finally:
            session.close()

    # Expense operations

    def create_expense(
        self,
        amount: float,
        description: str,
        category: str = "misc",
        currency: str = "INR",
        timestamp: str = None,
    ) -> ExpenseLog:
        session = self.get_session()
        try:
            expense = ExpenseLog(
                amount=amount,
                currency=currency,
                description=description.strip(),
                category=category or "misc",
                timestamp=datetime.fromisoformat(timestamp) if timestamp else datetime.now(),
            )
            session.add(expense)
            session.commit()
            session.refresh(expense)
            return expense
        finally:
            session.close()

    def get_expenses(
        self,
        start_date: datetime = None,
        end_date: datetime = None,
        limit: int = 100,
    ) -> List[ExpenseLog]:
        session = self.get_session()
        try:
            query = session.query(ExpenseLog)
            if start_date:
                query = query.filter(ExpenseLog.timestamp >= start_date)
            if end_date:
                query = query.filter(ExpenseLog.timestamp <= end_date)
            return query.order_by(desc(ExpenseLog.timestamp)).limit(limit).all()
        finally:
            session.close()

    # Reminder operations

    def create_reminder(
        self,
        description: str,
        reminder_type: str = "general",
        url: str = None,
        remind_at: str = None
    ) -> Reminder:
        """Create a new reminder"""
        session = self.get_session()
        try:
            reminder = Reminder(
                description=description,
                reminder_type=reminder_type,
                url=url,
                remind_at=datetime.fromisoformat(remind_at) if remind_at else None
            )
            session.add(reminder)
            session.commit()
            session.refresh(reminder)
            return reminder
        finally:
            session.close()

    def get_reminders(self, active_only: bool = True, limit: int = 50) -> List[Reminder]:
        """Get reminders"""
        session = self.get_session()
        try:
            query = session.query(Reminder)
            if active_only:
                query = query.filter(Reminder.is_active == True, Reminder.completed == False)
            query = query.order_by(Reminder.created_at.desc()).limit(limit)
            return query.all()
        finally:
            session.close()

    def complete_reminder(self, reminder_id: int) -> Optional[Reminder]:
        """Mark a reminder as completed"""
        session = self.get_session()
        try:
            reminder = session.query(Reminder).filter(Reminder.id == reminder_id).first()
            if reminder:
                reminder.completed = True
                reminder.is_active = False
                session.commit()
                session.refresh(reminder)
            return reminder
        finally:
            session.close()

    def delete_reminder(self, reminder_id: int) -> Optional[Reminder]:
        """Delete a reminder"""
        session = self.get_session()
        try:
            reminder = session.query(Reminder).filter(Reminder.id == reminder_id).first()
            if reminder:
                snapshot = reminder.to_dict()
                session.delete(reminder)
                session.commit()
                deleted = Reminder(description=snapshot["description"])
                deleted.id = snapshot["id"]
                return deleted
            return None
        finally:
            session.close()

    def get_due_reminders(self) -> List[Reminder]:
        """Get reminders that are due (remind_at has passed)"""
        session = self.get_session()
        try:
            now = datetime.now()
            return session.query(Reminder).filter(
                Reminder.is_active == True,
                Reminder.completed == False,
                Reminder.remind_at <= now
            ).all()
        finally:
            session.close()

    def delete_health_log_with_energy(self, health_log_id: int) -> Optional[HealthLog]:
        """
        Delete a health log and any associated predicted energy entries.
        This is used when a supplement was wrongly logged.
        """
        session = self.get_session()
        try:
            health_log = session.query(HealthLog).filter(HealthLog.id == health_log_id).first()
            if not health_log:
                return None

            log_time = health_log.timestamp
            supplements = health_log.supplements or []

            # Delete predicted energy entries within 10 minutes of the health log
            # These were likely auto-generated based on the supplement intake
            time_window_start = log_time - timedelta(minutes=10)
            time_window_end = log_time + timedelta(minutes=10)

            deleted_energy = session.query(EnergyLevel).filter(
                EnergyLevel.predicted == True,
                EnergyLevel.timestamp >= time_window_start,
                EnergyLevel.timestamp <= time_window_end
            ).all()

            count = len(deleted_energy)
            for energy in deleted_energy:
                session.delete(energy)

            # Delete the health log itself
            snapshot = health_log.to_dict()
            session.delete(health_log)
            session.commit()

            # Create a simple return object
            result = HealthLog(
                supplements=snapshot.get("supplements", []),
                timestamp=datetime.fromisoformat(snapshot["timestamp"]) if snapshot.get("timestamp") else None
            )
            result.id = snapshot["id"]
            result._deleted_energy_count = count

            return result

        finally:
            session.close()

    def get_recent_health_logs_with_energy(self, hours: int = 2, limit: int = 10) -> list:
        """
        Get recent health logs with count of associated predicted energy entries.
        Returns list of dicts with health log info and predicted energy count.
        """
        session = self.get_session()
        try:
            from database import EnergyLevel
            recent = datetime.now() - timedelta(hours=hours)

            health_logs = session.query(HealthLog).filter(
                HealthLog.timestamp >= recent
            ).order_by(HealthLog.timestamp.desc()).limit(limit).all()

            result = []
            for log in health_logs:
                # Count predicted energy entries within 10 minutes
                time_window_start = log.timestamp - timedelta(minutes=10)
                time_window_end = log.timestamp + timedelta(minutes=10)

                predicted_energy_count = session.query(EnergyLevel).filter(
                    EnergyLevel.predicted == True,
                    EnergyLevel.timestamp >= time_window_start,
                    EnergyLevel.timestamp <= time_window_end
                ).count()

                result.append({
                    "id": log.id,
                    "timestamp": log.timestamp,
                    "supplements": log.supplements or [],
                    "metrics": log.metrics or {},
                    "predicted_energy_count": predicted_energy_count
                })

            return result

        finally:
            session.close()


# ===== NEW: Enhanced Bot Tables =====

class ConversationMessage(Base):
    __tablename__ = 'conversation_messages'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    role = Column(String, nullable=False)  # 'user', 'assistant', 'system'
    content = Column(Text, nullable=False)
    meta_data = Column(JSON)  # Additional data like intent, confidence (renamed from metadata to avoid SQLAlchemy reserved word)
    timestamp = Column(DateTime, default=datetime.now, index=True)

    __table_args__ = (
        Index('idx_conv_user_time', 'user_id', 'timestamp'),
    )


class ConversationEntity(Base):
    __tablename__ = 'conversation_entities'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    entity_type = Column(String, nullable=False)  # 'person', 'project', 'location', 'organization'
    name = Column(String, nullable=False)
    attributes = Column(JSON)  # Additional data like role, department, etc.
    source_message = Column(Text)  # Where this was first mentioned
    mention_count = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.now)
    last_seen = Column(DateTime, default=datetime.now, index=True)

    __table_args__ = (
        Index('idx_entity_user_type', 'user_id', 'entity_type'),
    )


class ConversationMood(Base):
    __tablename__ = 'conversation_mood'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    sentiment = Column(Float, nullable=False)  # -1.0 (negative) to 1.0 (positive)
    emotion = Column(String)  # 'happy', 'sad', 'tired', 'stressed', etc.
    context = Column(String)  # What caused this mood
    message = Column(Text)  # Original message
    timestamp = Column(DateTime, default=datetime.now, index=True)

    __table_args__ = (
        Index('idx_mood_user_time', 'user_id', 'timestamp'),
    )


class UserPreference(Base):
    __tablename__ = 'user_preferences'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    key = Column(String, nullable=False)  # 'response_style', 'reminder_time', etc.
    value = Column(JSON)  # Can be string, number, boolean, or dict
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index('idx_pref_user_key', 'user_id', 'key'),
    )


class ScheduledInsight(Base):
    __tablename__ = 'scheduled_insights'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    insight_type = Column(String, nullable=False)  # 'daily', 'weekly', 'pattern', 'proactive'
    title = Column(String)
    content = Column(Text, nullable=False)
    data_summary = Column(JSON)  # The data that generated this insight
    scheduled_for = Column(DateTime, nullable=False, index=True)
    sent = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index('idx_insight_scheduled', 'scheduled_for'),
    )


class ProactiveReminder(Base):
    __tablename__ = 'proactive_reminders'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    trigger_type = Column(String, nullable=False)  # 'energy_dip', 'task_overdue', 'pattern_match'
    message = Column(Text, nullable=False)
    trigger_data = Column(JSON)  # Data that triggered this reminder
    scheduled_for = Column(DateTime, nullable=False, index=True)
    sent = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index('idx_proactive_scheduled', 'scheduled_for'),
    )
