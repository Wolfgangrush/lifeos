# Database Schema Documentation

Life OS uses SQLite with SQLAlchemy ORM. All tables are defined in `scripts/database.py`.

## Database Location

Default: `data/life_os.db`

Configure via environment variable:
```bash
DATABASE_PATH=data/life_os.db
```

## Schema Overview

```
┌─────────────┐
│    Tasks    │
├─────────────┤
│ id          │
│ description │
│ status      │
│ priority    │
│ focus_req   │
│ created_at  │
│ completed_at│
│ deadline    │
└─────────────┘

┌─────────────┐
│  FoodLogs   │
├─────────────┤
│ id          │
│ timestamp   │
│ items (JSON)│
│ macros(JSON)│
│ prediction  │
│   (JSON)    │
└─────────────┘

┌─────────────┐
│EnergyLevels │
├─────────────┤
│ id          │
│ timestamp   │
│ level (1-10)│
│ context     │
│ predicted   │
└─────────────┘

┌─────────────┐
│ HealthLogs  │
├─────────────┤
│ id          │
│ timestamp   │
│ supplements │
│   (JSON)    │
│ metrics     │
│   (JSON)    │
└─────────────┘

┌─────────────┐
│SystemEvents │
├─────────────┤
│ id          │
│ timestamp   │
│ event_type  │
│ data (JSON) │
│ triggered_by│
└─────────────┘
```

## Table Details

### Tasks

**Purpose:** Store all user tasks (pending, completed, cancelled)

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| description | STRING | Task description |
| status | STRING | 'pending', 'completed', 'cancelled' |
| priority | STRING | 'low', 'medium', 'high' |
| focus_required | BOOLEAN | True if task needs deep focus |
| created_at | DATETIME | When task was created |
| completed_at | DATETIME | When task was completed (null if pending) |
| deadline | DATETIME | Optional deadline |

**Indexes:**
- Primary key on `id`
- Index on `status` for fast filtering
- Index on `created_at` for chronological queries

**Example Row:**
```json
{
  "id": 1,
  "description": "Draft quarterly report",
  "status": "pending",
  "priority": "high",
  "focus_required": true,
  "created_at": "2024-01-15T09:00:00",
  "completed_at": null,
  "deadline": "2024-01-17T17:00:00"
}
```

### FoodLogs

**Purpose:** Track food intake with macro predictions and energy impact

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| timestamp | DATETIME | When food was consumed |
| items | JSON | Array of food items ["dal", "rice"] |
| macros | JSON | Macro breakdown {carbs: "high", protein: "medium", fat: "low"} |
| energy_prediction | JSON | Predicted energy impact |

**Energy Prediction Schema:**
```json
{
  "status": "stable" | "crash_warning" | "boost_expected",
  "time_of_crash": "ISO datetime or null",
  "message": "Human-readable explanation"
}
```

**Example Row:**
```json
{
  "id": 1,
  "timestamp": "2024-01-15T15:00:00",
  "items": ["dal", "rice", "vegetables"],
  "macros": {
    "carbs": "high",
    "protein": "medium",
    "fat": "low"
  },
  "energy_prediction": {
    "status": "crash_warning",
    "time_of_crash": "2024-01-15T15:45:00",
    "message": "Heavy carbs detected. Energy dip expected in 45 mins."
  }
}
```

### EnergyLevels

**Purpose:** Track actual and predicted energy levels throughout the day

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| timestamp | DATETIME | When energy was measured/predicted |
| level | INTEGER | Energy level (1-10 scale) |
| context | STRING | Optional note about the energy state |
| predicted | BOOLEAN | True if this is a prediction, false if actual |

**Levels:**
- 1-3: Low energy (😴)
- 4-6: Moderate energy (😊)
- 7-9: High energy (😄)
- 10: Peak performance (🚀)

**Example Rows:**
```json
[
  {
    "id": 1,
    "timestamp": "2024-01-15T09:00:00",
    "level": 7,
    "context": "Morning energy after coffee",
    "predicted": false
  },
  {
    "id": 2,
    "timestamp": "2024-01-15T15:45:00",
    "level": 4,
    "context": "Predicted from food intake",
    "predicted": true
  }
]
```

### HealthLogs

**Purpose:** Track supplements, medications, and health metrics

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| timestamp | DATETIME | When supplements/metrics were logged |
| supplements | JSON | Array of supplement names |
| metrics | JSON | Arbitrary health metrics |

**Metrics Examples:**
- `{"sleep_hours": 7.5}`
- `{"weight": 75, "unit": "kg"}`
- `{"steps": 8000}`
- `{"heart_rate": 72}`

**Example Row:**
```json
{
  "id": 1,
  "timestamp": "2024-01-15T08:00:00",
  "supplements": ["Vitamin D", "Omega-3", "Magnesium"],
  "metrics": {
    "sleep_hours": 7.5,
    "sleep_quality": "good"
  }
}
```

### SystemEvents

**Purpose:** Log automated system activities and summaries

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| timestamp | DATETIME | When event occurred |
| event_type | STRING | Type of event |
| data | JSON | Event-specific data |
| triggered_by | STRING | What triggered this event |

**Event Types:**
- `daily_summary` - Nightly summary generated
- `weekly_review` - Weekly review sent
- `energy_prediction` - Energy crash predicted
- `contextual_reminder` - Smart task reminder sent
- `database_seeded` - Initial data added

**Example Row:**
```json
{
  "id": 1,
  "timestamp": "2024-01-15T23:59:00",
  "event_type": "daily_summary",
  "data": {
    "tasks_completed": 5,
    "avg_energy": 7.2,
    "summary_text": "Great day! You completed 5 tasks..."
  },
  "triggered_by": "automation"
}
```

## Common Queries

### Get Today's Tasks
```python
from datetime import datetime
today = datetime.now().date()
start = datetime.combine(today, datetime.min.time())
end = datetime.combine(today, datetime.max.time())

tasks = session.query(Task).filter(
    Task.created_at >= start,
    Task.created_at <= end
).all()
```

### Get Energy Trend
```python
from datetime import timedelta
week_ago = datetime.now() - timedelta(days=7)

energy_logs = session.query(EnergyLevel).filter(
    EnergyLevel.timestamp >= week_ago,
    EnergyLevel.predicted == False
).order_by(EnergyLevel.timestamp).all()
```

### Calculate Completion Rate
```python
completed = session.query(Task).filter(
    Task.status == TaskStatus.COMPLETED
).count()

total = session.query(Task).count()

completion_rate = (completed / total * 100) if total > 0 else 0
```

### Find Peak Energy Time
```python
# Get last 7 days of energy data
energy_data = session.query(EnergyLevel).filter(
    EnergyLevel.timestamp >= week_ago,
    EnergyLevel.predicted == False
).all()

# Group by hour
hourly_energy = {}
for entry in energy_data:
    hour = entry.timestamp.hour
    if hour not in hourly_energy:
        hourly_energy[hour] = []
    hourly_energy[hour].append(entry.level)

# Find average by hour
avg_by_hour = {
    hour: sum(levels) / len(levels)
    for hour, levels in hourly_energy.items()
}

# Peak hour
peak_hour = max(avg_by_hour.items(), key=lambda x: x[1])[0]
```

## Database Operations

### Initialize Database
```bash
python scripts/init_db.py
```

### Reset Database
```bash
python scripts/init_db.py --reset
```

### Seed with Sample Data
```bash
python scripts/init_db.py --reset --seed
```

### Backup Database
```bash
cp data/life_os.db data/life_os_backup_$(date +%Y%m%d).db
```

### Restore from Backup
```bash
cp data/life_os_backup_20240115.db data/life_os.db
```

## Performance Considerations

### Indexing
All frequently queried columns are indexed:
- `Tasks.status`
- `Tasks.created_at`
- `FoodLogs.timestamp`
- `EnergyLevels.timestamp`
- `HealthLogs.timestamp`

### Cleanup
Old predictions can be cleaned up weekly:
```python
# Remove old energy predictions (older than 7 days)
cutoff = datetime.now() - timedelta(days=7)
session.query(EnergyLevel).filter(
    EnergyLevel.predicted == True,
    EnergyLevel.timestamp < cutoff
).delete()
```

### Pagination
For large datasets, use pagination:
```python
# Get tasks with pagination
page = 1
per_page = 20
offset = (page - 1) * per_page

tasks = session.query(Task)\
    .limit(per_page)\
    .offset(offset)\
    .all()
```

## Migrations

Currently no migration system. For schema changes:

1. **Small changes**: Alter table manually
2. **Major changes**: Backup → Reset → Reimport

Future: Consider Alembic for migrations.

## Data Export

### Export to JSON
```python
import json

tasks = db.get_tasks(limit=1000)
with open('tasks_export.json', 'w') as f:
    json.dump([t.to_dict() for t in tasks], f, indent=2)
```

### Export to CSV
```python
import csv

tasks = db.get_tasks(limit=1000)
with open('tasks_export.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=tasks[0].to_dict().keys())
    writer.writeheader()
    for task in tasks:
        writer.writerow(task.to_dict())
```

## Security

- Database is local only (not exposed to network)
- No user authentication (single-user system)
- Sensitive health data stored in plaintext SQLite

**For enhanced security:**
1. Encrypt the database file (use SQLCipher)
2. Set file permissions: `chmod 600 data/life_os.db`
3. Regular backups to encrypted storage
