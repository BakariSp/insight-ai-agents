"""Gunicorn configuration for Insight AI Agent — 4-core 8GB production server.

Usage:
    gunicorn main:app -c deploy/gunicorn.conf.py

This config is optimized for an I/O-bound async service that makes
external LLM API calls (15-60s latency per request) and streams SSE.
"""

import multiprocessing
import os

# ─── Server socket ──────────────────────────────────────────────

bind = os.getenv("BIND", "0.0.0.0:5000")
backlog = 2048  # Pending connection queue

# ─── Worker processes ───────────────────────────────────────────
#
# For async ASGI: 1 worker per core is optimal.
# Each async worker handles thousands of concurrent connections via event loop.
# More workers waste memory without improving throughput.
#
# Memory budget per worker: ~300-500MB with all dependencies loaded
# 4 workers × 500MB = 2GB max → fits in 8GB with OS + DB overhead.

workers = int(os.getenv("WORKERS", min(multiprocessing.cpu_count(), 4)))
worker_class = "uvicorn.workers.UvicornWorker"

# ─── Timeouts ───────────────────────────────────────────────────
#
# LLM calls: 15-60s per request
# Blueprint pipeline: up to 120s
# SSE streams: 30-180s active connection
#
# The timeout must be longer than the longest expected operation.

timeout = 180           # Kill worker after 180s of no response
graceful_timeout = 60   # Allow 60s for in-flight SSE streams to complete
keepalive = 120         # Keep-alive for SSE long connections

# ─── Worker recycling ──────────────────────────────────────────
#
# Recycle workers periodically to prevent memory leaks from:
# - LiteLLM internal caches
# - LightRAG workspace instances
# - numpy/embedding buffers
# - Conversation store accumulation between cleanup cycles

max_requests = 3000          # Recycle after N requests
max_requests_jitter = 500    # Randomize to prevent simultaneous recycling

# ─── Logging ────────────────────────────────────────────────────

accesslog = "-"                     # stdout
errorlog = "-"                      # stderr
loglevel = os.getenv("LOG_LEVEL", "info")
access_log_format = (
    '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" %(D)sμs'
)

# ─── Process naming ─────────────────────────────────────────────

proc_name = "insight-ai-agent"

# ─── Server hooks ───────────────────────────────────────────────


def on_starting(server):
    """Called just before the master process is initialized."""
    server.log.info(
        "Starting Insight AI Agent — workers=%d, timeout=%ds, "
        "max_requests=%d, bind=%s",
        workers,
        timeout,
        max_requests,
        bind,
    )


def post_fork(server, worker):
    """Called just after a worker has been forked."""
    server.log.info("Worker spawned (pid: %s)", worker.pid)


def worker_exit(server, worker):
    """Called when a worker has been killed or exited."""
    server.log.info("Worker exit (pid: %s)", worker.pid)
