# API Documentation

The Life OS API is built with FastAPI and provides REST endpoints plus WebSocket support for real-time updates.

## Base URL

```
http://localhost:8000
```

Configure port via environment variable:
```bash
API_PORT=8000
```

## Authentication

Currently no authentication. The API is designed for local use only.

## Response Format

All responses are JSON:

**Success:**
```json
{
  "tasks": [...],
  "status": "success"
}
```

**Error:**
```json
{
  "error": "Error message",
  "status": "error"
}
```

## Endpoints

### Health Check

**GET** `/api/health`

Check if API is running.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00"
}
```

---

### Tasks

#### Get All Tasks

**GET** `/api/tasks`

**Query Parameters:**
- `status` (optional): Filter by status (`pending`, `completed`, `cancelled`)
- `limit` (optional): Max results (default: 100, max: 1000)

**Example:**
```
GET /api/tasks?status=pending&limit=20
```

**Response:**
```json
{
  "tasks": [
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
  ]
}
```

#### Get Single Task

**GET** `/api/tasks/{task_id}`

**Response:**
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

#### Complete Task

**POST** `/api/tasks/{task_id}/complete`

Mark a task as completed. Broadcasts update via WebSocket.

**Response:**
```json
{
  "id": 1,
  "description": "Draft quarterly report",
  "status": "completed",
  "completed_at": "2024-01-15T15:30:00",
  ...
}
```

---

### Food Logs

#### Get Food Logs

**GET** `/api/food`

**Query Parameters:**
- `start_date` (optional): ISO datetime (e.g., `2024-01-15T00:00:00`)
- `end_date` (optional): ISO datetime
- `limit` (optional): Max results (default: 100)

**Example:**
```
GET /api/food?start_date=2024-01-15T00:00:00&limit=10
```

**Response:**
```json
{
  "food_logs": [
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
  ]
}
```

#### Get Today's Food

**GET** `/api/food/today`

Shortcut for today's food logs.

**Response:** Same format as `/api/food`

---

### Energy Levels

#### Get Energy Levels

**GET** `/api/energy`

**Query Parameters:**
- `start_date` (optional): ISO datetime
- `end_date` (optional): ISO datetime
- `predicted_only` (optional): Boolean (default: false)
- `limit` (optional): Max results (default: 100)

**Example:**
```
GET /api/energy?predicted_only=false&limit=20
```

**Response:**
```json
{
  "energy_levels": [
    {
      "id": 1,
      "timestamp": "2024-01-15T09:00:00",
      "level": 7,
      "context": "Morning energy after coffee",
      "predicted": false
    }
  ]
}
```

#### Get Today's Energy

**GET** `/api/energy/today`

**Response:** Same format as `/api/energy`

#### Get Peak Energy Time

**GET** `/api/energy/peak-time`

Get the hour when user typically has highest energy.

**Response:**
```json
{
  "peak_time": "09:00"
}
```

---

### Health Logs

#### Get Health Logs

**GET** `/api/health-logs`

**Query Parameters:**
- `start_date` (optional): ISO datetime
- `end_date` (optional): ISO datetime
- `limit` (optional): Max results (default: 100)

**Response:**
```json
{
  "health_logs": [
    {
      "id": 1,
      "timestamp": "2024-01-15T08:00:00",
      "supplements": ["Vitamin D", "Omega-3"],
      "metrics": {
        "sleep_hours": 7.5,
        "sleep_quality": "good"
      }
    }
  ]
}
```

---

### Summary & Statistics

#### Get Daily Summary

**GET** `/api/summary/{date}`

**Parameters:**
- `date`: ISO date (e.g., `2024-01-15`)

**Response:**
```json
{
  "tasks_completed": 5,
  "tasks_pending": 3,
  "meals_logged": 3,
  "top_foods": ["rice", "chicken", "vegetables"],
  "avg_energy": 7.2,
  "min_energy": 4,
  "max_energy": 9,
  "supplements": ["Vitamin D", "Omega-3"]
}
```

#### Get Today's Summary

**GET** `/api/summary/today`

Shortcut for today's summary.

**Response:** Same format as `/api/summary/{date}`

#### Get Weekly Stats

**GET** `/api/stats`

**Response:**
```json
{
  "tasks_completed": 20,
  "tasks_pending": 5,
  "completion_rate": 80.0,
  "avg_energy": 7.1,
  "peak_energy_time": "09:00",
  "low_energy_time": "15:00",
  "meals_logged": 21,
  "top_food": "rice",
  "current_streak": 7
}
```

---

### Timeline

#### Get Combined Timeline

**GET** `/api/timeline`

Get all events (tasks, food, energy) in chronological order.

**Query Parameters:**
- `start_date` (optional): ISO datetime (default: 7 days ago)
- `end_date` (optional): ISO datetime (default: now)

**Response:**
```json
{
  "timeline": [
    {
      "type": "task",
      "timestamp": "2024-01-15T10:00:00",
      "data": { /* task object */ }
    },
    {
      "type": "food",
      "timestamp": "2024-01-15T12:00:00",
      "data": { /* food log object */ }
    },
    {
      "type": "energy",
      "timestamp": "2024-01-15T13:00:00",
      "data": { /* energy level object */ }
    }
  ]
}
```

---

## WebSocket

### Connection

**WS** `/ws`

Connect to receive real-time updates.

**Example (JavaScript):**
```javascript
const ws = new WebSocket('ws://localhost:8000/ws');

ws.onopen = () => {
  console.log('Connected');
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Update:', data);
};
```

### Message Format

**Server → Client:**
```json
{
  "type": "task_updated" | "food_logged" | "energy_predicted",
  "data": { /* relevant object */ },
  "timestamp": "2024-01-15T10:00:00"
}
```

**Client → Server:**
```javascript
// Ping to keep connection alive
ws.send("ping");
// Server responds with "pong"
```

### Event Types

- `task_updated` - Task created/completed/updated
- `food_logged` - New food entry
- `energy_predicted` - Energy crash predicted
- `health_logged` - New health entry
- `summary_generated` - Daily summary created

---

## CORS

CORS is enabled for all origins in development. For production, configure:

```python
# In api_server.py
allow_origins=["https://yourdomain.com"]
```

---

## Rate Limiting

Currently no rate limiting (local use only).

For production, consider adding:
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.get("/api/tasks")
@limiter.limit("100/minute")
async def get_tasks():
    ...
```

---

## Error Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Bad Request (invalid parameters) |
| 404 | Not Found |
| 500 | Internal Server Error |

---

## Testing with curl

### Get tasks
```bash
curl http://localhost:8000/api/tasks?status=pending
```

### Complete a task
```bash
curl -X POST http://localhost:8000/api/tasks/1/complete
```

### Get today's summary
```bash
curl http://localhost:8000/api/summary/today
```

### Test WebSocket
```bash
npm install -g wscat
wscat -c ws://localhost:8000/ws
```

---

## Frontend Integration

### React Hook Example

```javascript
import { useState, useEffect } from 'react';

function useTasks() {
  const [tasks, setTasks] = useState([]);
  
  useEffect(() => {
    fetch('http://localhost:8000/api/tasks')
      .then(res => res.json())
      .then(data => setTasks(data.tasks));
  }, []);
  
  return tasks;
}
```

### WebSocket Hook Example

```javascript
function useWebSocket() {
  const [lastMessage, setLastMessage] = useState(null);
  
  useEffect(() => {
    const ws = new WebSocket('ws://localhost:8000/ws');
    
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setLastMessage(data);
    };
    
    return () => ws.close();
  }, []);
  
  return lastMessage;
}
```

---

## Development

### Start the API Server

```bash
python scripts/api_server.py
```

Or with uvicorn directly:
```bash
uvicorn scripts.api_server:app --reload --port 8000
```

### View API Docs

FastAPI provides interactive docs:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### Logs

API logs are written to:
- Console (stdout)
- Application handles its own logging

Configure log level:
```bash
LOG_LEVEL=DEBUG python scripts/api_server.py
```

---

## Production Deployment

For production use:

1. **Use a production ASGI server:**
```bash
gunicorn scripts.api_server:app -w 4 -k uvicorn.workers.UvicornWorker
```

2. **Enable HTTPS** (via nginx reverse proxy)

3. **Add authentication** (API keys or OAuth)

4. **Configure CORS** properly

5. **Add rate limiting**

6. **Monitor with** logging service

---

## Future Enhancements

Potential API improvements:

- Pagination headers (X-Total-Count, Link)
- Filtering by multiple fields
- Sorting options
- Bulk operations
- File uploads (images of food)
- Export endpoints (CSV, PDF)
- GraphQL endpoint
- API versioning (/api/v1/)
