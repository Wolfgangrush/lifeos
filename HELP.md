# LifeOS Help

Quick reference for running and debugging your LifeOS setup.

## First-Time Setup

Run the configure script to personalize paths and install the launchd service:

```zsh
./configure.sh
```

This generates your LaunchAgent plist, sets up log directories, and installs the `operator` command.

## Fresh Restart

After rebooting your machine:

1. Start Ollama.
2. Open Terminal in your LifeOS project folder.
3. Start or restart LifeOS:

   ```zsh
   operator restart
   ```

4. Open the dashboard:

   ```text
   http://127.0.0.1:3000
   ```

The `operator restart` command starts the launchd service that runs:

- API server: `http://127.0.0.1:8000`
- Dashboard: `http://127.0.0.1:3000`
- Telegram bot
- Automation engine

LifeOS is designed to stay on while your machine is awake and logged in.

## Normal Commands

Check whether LifeOS is running:

```zsh
operator status
```

Start LifeOS if it is off:

```zsh
operator on
```

Restart LifeOS when it feels stuck:

```zsh
operator restart
```

Turn LifeOS off:

```zsh
operator off
```

## Browser Links

Use `127.0.0.1`, not `localhost`.

Dashboard:

```text
http://127.0.0.1:3000
```

API health check:

```text
http://127.0.0.1:8000/api/health
```

API docs:

```text
http://127.0.0.1:8000/docs
```

## If Browser Is Not Working

First run:

```zsh
operator status
```

If it is not running:

```zsh
operator on
```

If it says running but the browser is still not working:

```zsh
operator restart
```

Then open:

```text
http://127.0.0.1:3000
```

If it still does not work, check whether the ports are listening:

```zsh
lsof -nP -iTCP:3000 -sTCP:LISTEN
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

Expected:

- port `3000` should show a `node` or `vite` process
- port `8000` should show a `Python` process

Check API health:

```zsh
curl --max-time 5 -sS http://127.0.0.1:8000/api/health
```

Expected:

```json
{"status":"healthy","timestamp":"..."}
```

## Logs

Bot log:

```zsh
tail -n 120 logs/bot.log
```

Launchd logs (created by `configure.sh`):

```zsh
tail -n 120 ~/.lifeos/launchd.err.log
tail -n 120 ~/.lifeos/launchd.out.log
```

Supervisor child service logs:

```zsh
tail -n 120 logs/api_server.out.log logs/api_server.err.log
tail -n 120 logs/dashboard.out.log logs/dashboard.err.log
tail -n 120 logs/telegram_bot.out.log logs/telegram_bot.err.log
tail -n 120 logs/automation_engine.out.log logs/automation_engine.err.log
```

Supervisor status from launchd:

```zsh
launchctl print gui/$(id -u)/com.lifeos.bot
```

## Important Paths

After running `./configure.sh`, the following are set up:

| What | Where |
|------|-------|
| Project folder | wherever you cloned this repo |
| Operator command | `./Operator` (or symlinked to `~/.local/bin/operator`) |
| LaunchAgent plist | `~/Library/LaunchAgents/com.lifeos.bot.plist` |
| Launchd wrapper | `./run_lifeos_bot.sh` |
| Database | `data/life_os.db` |

## Telegram Commands

Ask Telegram for the current command list:

```text
/help
```

Most useful commands:

```text
/task
/newtask
/delete_task
/eatery
/food
/foodtoday
/delete_food
/energy
/supplements
/addsupplement
/removesupplement
/delete_recent
/remind
/reminders
/summary
/stats
/rollover
/analyze
/style
/mood
/operator
```

## Dashboard Actions

The dashboard supports:

- viewing today's summary
- viewing pending and completed tasks
- removing tasks
- viewing energy logs
- viewing food logs
- removing food logs
- viewing coach analysis
- selecting previous days from the activity strip

Dashboard URL:

```text
http://127.0.0.1:3000
```

## When Something Was Logged Wrong

Remove a wrong task:

```text
/task
```

Then choose `Remove Task`.

Or:

```text
/delete_task
```

Remove wrong food:

```text
/foodtoday
```

Then tap the delete button.

Or:

```text
/delete_food
```

Remove recent supplement or energy logs:

```text
/delete_recent
```

## Developer Checks

Run Python syntax checks:

```zsh
python3 -m py_compile api_server.py bot.py database.py start_all.py
```

Build the dashboard:

```zsh
npm run build
```

Restart after code changes:

```zsh
operator restart
```

## Important Notes

- Use `operator restart` when LifeOS feels stuck.
- Use `http://127.0.0.1:3000`, not `localhost`.
- Ollama must be running for the LLM features to work.
- The launchd service may auto-start after login. If `operator status` says running, you do not need to start it again.
- If `operator status` says running but the browser does not load, check `http://127.0.0.1:8000/api/health` and the child service logs above.
- The Telegram bot and dashboard both read/write the same SQLite database at `data/life_os.db`.
