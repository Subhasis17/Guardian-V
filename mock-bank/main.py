"""Independent synthetic bank. Never connects to real financial institutions."""
import hashlib
import hmac
import os
import random
import sqlite3
from contextlib import contextmanager, asynccontextmanager, closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
import importlib.util

# Load from this service's directory even when tests import it by file path.
_spec = importlib.util.spec_from_file_location("mock_bank_logging", Path(__file__).with_name("logging_setup.py"))
_logging = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_logging)
logger, access_logger = _logging.configure_logs(os.getenv("MOCK_BANK_LOG_DIR") or Path(__file__).parent / "logs", "mock_bank")

@asynccontextmanager
async def lifespan(app):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS accounts (user_id TEXT PRIMARY KEY, card_frozen INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS transactions (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, merchant TEXT NOT NULL, amount INTEGER NOT NULL, occurred_at TEXT NOT NULL, status TEXT NOT NULL, suspicious INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS freezes (request_key TEXT PRIMARY KEY, user_id TEXT NOT NULL);
        ''')
    yield


app = FastAPI(title="Guardian Mock Bank — SANDBOX", lifespan=lifespan)
app.add_middleware(_logging.RequestLogging, logger=logger, access=access_logger)
DB_PATH = Path(os.getenv("MOCK_BANK_DB_PATH") or Path(__file__).with_name("bank.db"))


def authorize(x_guardian_user: str = Header(), authorization: str = Header()):
    secret = os.getenv("MOCK_BANK_SERVICE_SECRET", "")
    if not secret:
        raise HTTPException(503, "Sandbox bank authentication is not configured.")
    if not x_guardian_user or len(x_guardian_user) > 128:
        raise HTTPException(401, "Invalid sandbox account identity.")
    expected = hmac.new(secret.encode(), x_guardian_user.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(authorization, "Bearer " + expected):
        raise HTTPException(401, "Invalid sandbox bank authorization.")
    return x_guardian_user


@contextmanager
def account_db(user, write=False):
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.row_factory = sqlite3.Row
        if not write and conn.execute("SELECT 1 FROM accounts WHERE user_id=?", (user,)).fetchone():
            yield conn
            return
        conn.execute("BEGIN IMMEDIATE")
        created = conn.execute("INSERT OR IGNORE INTO accounts(user_id) VALUES (?)", (user,)).rowcount
        if created:
            seed = hashlib.sha256(user.encode()).hexdigest()
            rng = random.Random(seed)
            now = datetime.now(timezone.utc)
            for index, merchant in enumerate(("Grocery Market", "UPI New Payee", "Fuel Station", "Online Store", "Electricity")):
                conn.execute("INSERT INTO transactions VALUES (?,?,?,?,?,?,?)", (
                    f"sandbox-{seed[:20]}-{index}", user, merchant,
                    rng.randint(15000, 45000) if index == 1 else rng.randint(100, 6000),
                    (now - timedelta(hours=index * 9 + 1)).isoformat(), "completed", int(index == 1)))
        yield conn


@app.get("/health")
def health():
    return {"status": "ok", "sandbox": True, "service": "guardian-mock-bank"}


@app.get("/account")
def snapshot(user=Depends(authorize)):
    with account_db(user) as conn:
        frozen = conn.execute("SELECT card_frozen FROM accounts WHERE user_id=?", (user,)).fetchone()[0]
        transactions = [dict(row) for row in conn.execute("SELECT id,merchant,amount,occurred_at,status,suspicious FROM transactions WHERE user_id=? ORDER BY occurred_at DESC", (user,))]
    return {"sandbox": True, "account": {"card_frozen": bool(frozen)}, "transactions": transactions}


class FreezeInput(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128)


@app.post("/card/freeze")
def freeze(payload: FreezeInput, user=Depends(authorize)):
    logger.info("sandbox_card_freeze_requested account=%s", hashlib.sha256(user.encode()).hexdigest()[:12])
    with account_db(user, write=True) as conn:
        previous = conn.execute("SELECT user_id FROM freezes WHERE request_key=?", (payload.idempotency_key,)).fetchone()
        if previous and previous[0] != user:
            raise HTTPException(409, "Request key belongs to another sandbox account.")
        conn.execute("INSERT OR IGNORE INTO freezes VALUES (?,?)", (payload.idempotency_key, user))
        conn.execute("UPDATE accounts SET card_frozen=1 WHERE user_id=?", (user,))
    logger.info("sandbox_card_freeze_succeeded account=%s", hashlib.sha256(user.encode()).hexdigest()[:12])
    return {"sandbox": True, "card_frozen": True}
