#!/usr/bin/env python3
"""
Database Initialization Script for Life OS
Creates the database schema and optionally seeds with sample data
"""

import os
import sys
import argparse
from datetime import datetime, timedelta
from database import Database, TaskStatus, TaskPriority

def init_database(reset=False, seed=False):
    """Initialize the database"""
    db_path = os.getenv('DATABASE_PATH', 'data/life_os.db')
    
    # If reset, delete existing database
    if reset and os.path.exists(db_path):
        print(f"Resetting database at {db_path}...")
        os.remove(db_path)
        print("Database deleted.")
    
    print(f"Initializing database at {db_path}...")
    db = Database(db_path=db_path)
    print("Database schema created successfully!")
    
    if seed:
        print("Seeding database with sample data...")
        seed_database(db)
        print("Sample data added successfully!")
    
    print(f"\n✅ Database ready at {db_path}")

def seed_database(db):
    """Seed database with sample data for testing"""
    
    # Sample tasks
    tasks = [
        {
            "description": "Draft quarterly report",
            "status": TaskStatus.PENDING,
            "priority": TaskPriority.HIGH,
            "focus_required": True,
            "deadline": (datetime.now() + timedelta(days=2)).isoformat()
        },
        {
            "description": "Review team proposals",
            "status": TaskStatus.PENDING,
            "priority": TaskPriority.MEDIUM,
            "focus_required": True,
        },
        {
            "description": "Call dentist for appointment",
            "status": TaskStatus.PENDING,
            "priority": TaskPriority.LOW,
            "focus_required": False,
        },
        {
            "description": "Completed morning workout",
            "status": TaskStatus.COMPLETED,
            "priority": TaskPriority.MEDIUM,
            "focus_required": False,
        }
    ]
    
    for task_data in tasks:
        db.create_task(**task_data)
    print(f"  • Added {len(tasks)} sample tasks")
    
    # Sample food logs
    now = datetime.now()
    food_logs = [
        {
            "items": ["oatmeal", "banana", "coffee"],
            "timestamp": (now - timedelta(hours=3)).isoformat(),
            "macros": {"carbs": "medium", "protein": "low", "fat": "low"},
            "energy_prediction": {"status": "stable", "message": "Balanced breakfast"}
        },
        {
            "items": ["chicken salad", "brown rice"],
            "timestamp": (now - timedelta(hours=1)).isoformat(),
            "macros": {"carbs": "medium", "protein": "high", "fat": "medium"},
            "energy_prediction": {"status": "boost_expected", "message": "Good protein content"}
        }
    ]
    
    for food_data in food_logs:
        db.log_food(**food_data)
    print(f"  • Added {len(food_logs)} sample food logs")
    
    # Sample energy levels
    energy_levels = [
        {"level": 7, "timestamp": (now - timedelta(hours=4)).isoformat(), "context": "Morning energy", "predicted": False},
        {"level": 8, "timestamp": (now - timedelta(hours=3)).isoformat(), "context": "After breakfast", "predicted": False},
        {"level": 6, "timestamp": (now - timedelta(hours=2)).isoformat(), "context": "Mid-morning", "predicted": False},
        {"level": 7, "timestamp": (now - timedelta(hours=1)).isoformat(), "context": "After lunch", "predicted": False},
        {"level": 5, "timestamp": (now + timedelta(minutes=30)).isoformat(), "context": "Predicted afternoon dip", "predicted": True},
    ]
    
    for energy_data in energy_levels:
        db.log_energy(**energy_data)
    print(f"  • Added {len(energy_levels)} sample energy logs")
    
    # Sample health logs
    health_logs = [
        {
            "supplements": ["Vitamin D", "Omega-3"],
            "timestamp": (now - timedelta(hours=3)).isoformat(),
            "metrics": {"sleep_hours": 7.5}
        }
    ]
    
    for health_data in health_logs:
        db.log_health(**health_data)
    print(f"  • Added {len(health_logs)} sample health logs")
    
    # Sample system event
    db.log_system_event(
        event_type='database_seeded',
        data={'timestamp': datetime.now().isoformat()},
        triggered_by='init_script'
    )

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Initialize Life OS database")
    parser.add_argument('--reset', action='store_true', help="Reset existing database")
    parser.add_argument('--seed', action='store_true', help="Seed with sample data")
    
    args = parser.parse_args()
    
    try:
        init_database(reset=args.reset, seed=args.seed)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
