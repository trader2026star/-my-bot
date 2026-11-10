# ============================================================
# main.py — Bot V85.0 (Stable Deploy Version)
# ============================================================
import os
import re
import time
import hashlib
import threading
import logging
import sqlite3
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import ccxt
import requests
from flask import Flask, jsonify, request

from analysis import StrategyEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MainBot")
app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
ALLOWED_CHAT_IDS = {c.strip() for c in os.environ.get("ALLOWED_CHAT_IDS", "").split(",") if c.strip()}
if TELEGRAM_CHAT_ID:
    ALLOWED_CHAT_IDS.add(TELEGRAM_CHAT_ID)

DB_PATH = os.environ.get("DB_PATH", "/tmp/bot_state.db")

bingx = ccxt.bingx({"enableRateLimit": True, "timeout": 20000, "options": {"defaultType": "swap"}})
engine = StrategyEngine()

scan_stats = {"scanned_pairs": 0, "signals_sent": 0, "errors": 0}


def _db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def db_query(sql, params=(), one=False):
    conn = _db()
    try:
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
        conn.commit()
        if one:
            return rows[0] if rows else None
        return rows
    finally:
        conn.close()


def db_init():
    try:
        db_query("CREATE TABLE IF NOT EXISTS bot_state (key TEXT PRIMARY KEY, value TEXT)")
    except Exception:
        pass


@app.route("/")
def index():
    return jsonify({"status": "running", "version": "V85.0-Stable", "stats": scan_stats})


@app.route("/health")
def health():
    return "OK", 200


def bootstrap():
    db_init()
    logger.info("Bot bootstrapped successfully.")


bootstrap()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), threaded=True)
