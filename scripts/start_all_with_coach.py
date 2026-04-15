#!/usr/bin/env python3
"""
Start Life OS with Analysis Coach
"""

import os
import sys
import subprocess
import signal
import asyncio
from pathlib import Path

processes = []

def start_process(name, command):
    print(f"Starting {name}...")
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    processes.append({'name': name, 'process': process})
    print(f"✅ {name} started (PID: {process.pid})")
    return process

def stop_all(signum=None, frame=None):
    print("\n🛑 Stopping all services...")
    for proc_info in processes:
        name = proc_info['name']
        process = proc_info['process']
        print(f"Stopping {name}...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    sys.exit(0)

signal.signal(signal.SIGINT, stop_all)
signal.signal(signal.SIGTERM, stop_all)

print("=" * 60)
print("🚀 Starting Life OS with Analysis Coach")
print("=" * 60)

# Start API server
start_process("API Server", [sys.executable, "scripts/api_server.py"])

# Start Telegram bot
start_process("Telegram Bot", [sys.executable, "scripts/bot.py"])

# Start Automation engine
start_process("Automation Engine", [sys.executable, "scripts/automation.py"])

# Start Analysis Coach
start_process("Analysis Coach", [sys.executable, "scripts/analysis_coach.py"])

print("=" * 60)
print("✅ All services running!")
print("=" * 60)
print("\n📊 Analysis Coach is active!")
print("   → Analyzing your data every hour")
print("   → Enriching food logs with nutrition")
print("   → Tracking performance patterns")
print("\nPress Ctrl+C to stop all services")
print("=" * 60)

# Keep running
try:
    while True:
        import time
        time.sleep(1)
except KeyboardInterrupt:
    stop_all()
