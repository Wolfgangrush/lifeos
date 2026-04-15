#!/usr/bin/env python3
"""
Startup Script for Life OS
Launches all services: Bot, API Server, and Automation Engine
"""

import os
import sys
import asyncio
import subprocess
import signal
import logging
import urllib.request
import re
import time
from pathlib import Path
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

LOCAL_API_URL = "http://127.0.0.1:8000"
LOCAL_DASHBOARD_URL = "http://127.0.0.1:3000"

class LifeOSLauncher:
    def __init__(self):
        load_dotenv()
        self.processes = []
        self.running = True
        self.base_dir = Path(__file__).resolve().parent
        self.logs_dir = self.base_dir / "logs"
        self.logs_dir.mkdir(exist_ok=True)
    
    def check_prerequisites(self):
        """Check if all prerequisites are met"""
        logger.info("Checking prerequisites...")
        
        # Check environment variables
        required_env_vars = ['TELEGRAM_BOT_TOKEN']
        missing_vars = [var for var in required_env_vars if not os.getenv(var)]
        
        if missing_vars:
            logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
            logger.error("Please set them in your .env file")
            return False
        
        # Check if database exists
        db_path = os.getenv('DATABASE_PATH', 'data/life_os.db')
        db_file = Path(db_path)
        if not db_file.is_absolute():
            db_file = self.base_dir / db_file
        if not db_file.exists():
            logger.warning(f"Database not found at {db_path}")
            logger.info("Run: python init_db.py --seed")
            response = input("Initialize database now? (y/n): ")
            if response.lower() == 'y':
                subprocess.run([sys.executable, 'init_db.py', '--seed'], cwd=self.base_dir)
            else:
                return False
        
        # Check if Ollama is running
        try:
            import httpx
            ollama_url = os.getenv('OLLAMA_URL', 'http://localhost:11434')
            response = httpx.get(f"{ollama_url}/api/tags", timeout=5.0)
            if response.status_code != 200:
                logger.warning("Ollama is not running. LLM parsing will not work.")
                logger.info("Start Ollama with: ollama serve")
        except Exception:
            logger.warning("Could not connect to Ollama. LLM parsing will not work.")
            logger.info("Make sure Ollama is installed and running.")
        
        logger.info("✅ Prerequisites check completed")
        return True
    
    def _log_slug(self, name):
        return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")

    def _open_process_logs(self, name):
        slug = self._log_slug(name)
        stdout = open(self.logs_dir / f"{slug}.out.log", "a", buffering=1)
        stderr = open(self.logs_dir / f"{slug}.err.log", "a", buffering=1)
        return stdout, stderr

    def _close_process_logs(self, proc_info):
        for stream_name in ("stdout", "stderr"):
            stream = proc_info.get(stream_name)
            if stream:
                try:
                    stream.close()
                except Exception:
                    pass

    def start_process(self, name, command, cwd=None):
        """Start a subprocess"""
        logger.info(f"Starting {name}...")
        stdout, stderr = self._open_process_logs(name)

        process = subprocess.Popen(
            command,
            stdout=stdout,
            stderr=stderr,
            cwd=cwd or self.base_dir,
            text=True,
            bufsize=1
        )

        proc_info = {
            'name': name,
            'command': command,
            'cwd': cwd or self.base_dir,
            'process': process,
            'stdout': stdout,
            'stderr': stderr,
            'restart_count': 0,
            'last_restart_at': None,
        }
        self.processes.append(proc_info)

        logger.info(f"✅ {name} started (PID: {process.pid})")
        return process

    def restart_process(self, proc_info):
        """Restart one child service without stopping the whole stack."""
        name = proc_info['name']
        proc_info['restart_count'] += 1
        proc_info['last_restart_at'] = time.time()
        self._close_process_logs(proc_info)
        stdout, stderr = self._open_process_logs(name)

        logger.warning(f"Restarting {name} (restart #{proc_info['restart_count']})...")
        process = subprocess.Popen(
            proc_info['command'],
            stdout=stdout,
            stderr=stderr,
            cwd=proc_info['cwd'],
            text=True,
            bufsize=1
        )

        proc_info['process'] = process
        proc_info['stdout'] = stdout
        proc_info['stderr'] = stderr
        logger.info(f"✅ {name} restarted (PID: {process.pid})")

    def url_is_up(self, url, timeout=2.0):
        """Return True when a local service is already responding."""
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                return 200 <= response.status < 500
        except Exception:
            return False
    
    async def monitor_processes(self):
        """Monitor all processes and restart if they crash"""
        while self.running:
            for proc_info in self.processes:
                name = proc_info['name']
                process = proc_info['process']

                # Check if process is still running
                if process.poll() is not None:
                    logger.error(f"❌ {name} has stopped unexpectedly!")
                    logger.error(f"Return code: {process.returncode}")

                    if self.running:
                        self.restart_process(proc_info)
            
            await asyncio.sleep(5)  # Check every 5 seconds
    
    def stop_all(self):
        """Stop all processes gracefully"""
        logger.info("Stopping all services...")
        self.running = False
        
        for proc_info in self.processes:
            name = proc_info['name']
            process = proc_info['process']
            
            logger.info(f"Stopping {name}...")
            
            try:
                process.terminate()
                process.wait(timeout=10)
                logger.info(f"✅ {name} stopped")
            except subprocess.TimeoutExpired:
                logger.warning(f"{name} did not stop gracefully, forcing...")
                process.kill()
                logger.info(f"✅ {name} killed")
            finally:
                self._close_process_logs(proc_info)
    
    def handle_shutdown(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"\nReceived signal {signum}")
        self.stop_all()
        sys.exit(0)
    
    async def run(self):
        """Main run loop"""
        # Register signal handlers
        signal.signal(signal.SIGINT, self.handle_shutdown)
        signal.signal(signal.SIGTERM, self.handle_shutdown)
        
        # Check prerequisites
        if not self.check_prerequisites():
            logger.error("Prerequisites not met. Exiting.")
            return
        
        logger.info("=" * 50)
        logger.info("🚀 Starting Life OS...")
        logger.info("=" * 50)
        
        # Start API server
        if self.url_is_up(f"{LOCAL_API_URL}/api/health"):
            logger.info(f"✅ API Server already running at {LOCAL_API_URL}")
        else:
            self.start_process(
                "API Server",
                [sys.executable, "api_server.py"]
            )
        
        # Wait a bit for API server to start
        await asyncio.sleep(2)
        
        # Start automation engine
        self.start_process(
            "Automation Engine",
            [sys.executable, "automation.py"]
        )
        
        # Wait a bit
        await asyncio.sleep(2)
        
        # Start Telegram bot
        self.start_process(
            "Telegram Bot",
            [sys.executable, "bot.py"]
        )

        # Start dashboard
        if self.url_is_up(LOCAL_DASHBOARD_URL):
            logger.info(f"✅ Dashboard already running at {LOCAL_DASHBOARD_URL}")
        else:
            self.start_process(
                "Dashboard",
                ["npm", "run", "dev"]
            )
        
        logger.info("=" * 50)
        logger.info("✅ All services started!")
        logger.info("=" * 50)
        logger.info("")
        logger.info("📱 Telegram bot is running - send it a message")
        logger.info(f"🌐 API server: {LOCAL_API_URL}")
        logger.info(f"📊 Dashboard: {LOCAL_DASHBOARD_URL}")
        logger.info("")
        logger.info("Press Ctrl+C to stop all services")
        logger.info("=" * 50)
        
        # Monitor processes
        await self.monitor_processes()

def main():
    launcher = LifeOSLauncher()
    
    try:
        asyncio.run(launcher.run())
    except KeyboardInterrupt:
        logger.info("\nShutting down...")
        launcher.stop_all()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        launcher.stop_all()
        sys.exit(1)

if __name__ == "__main__":
    main()
