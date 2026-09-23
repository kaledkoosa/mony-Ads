import os
import sqlite3
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.responses import HTMLResponse

app = FastAPI()

# تفعيل الـ CORS لتتمكن واجهة المستخدم من الاتصال بالسيرفر
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# جلب المتغيرات البيئية من سيرفر Render
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")

# اسم ملف قاعدة البيانات المحلية
DB_FILE = "app_database.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            telegram_id TEXT PRIMARY KEY,
            username TEXT,
            balance_ton REAL,
            watched_ads_for_withdraw INTEGER,
            is_verified INTEGER
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id TEXT,
            channel TEXT,
            target INTEGER,
            current_count INTEGER,
            reward_per_user REAL,
            participants TEXT,
            status TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id TEXT,
            wallet TEXT,
            amount REAL,
            status TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            referrer_id TEXT,
            referred_id TEXT UNIQUE,
            status TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

class UserInitData(BaseModel):
    telegram_id: str
    username: str = "unknown"
    referrer_id: str = None

class WatchAdRequest(BaseModel):
    telegram_id: str

class CreateAdRequest(BaseModel):
    owner_id: str
    channel_link: str

class WithdrawRequest(BaseModel):
    telegram_id: str
    wallet_address: str

def check_telegram_membership(user_id: str, chat_id: str) -> bool:
    try:
        url = f"https://telegram.org{BOT_TOKEN}/getChatMember"
        response = requests.get(url, params={"chat_id": chat_id, "user_id": user_id}, timeout=10)
        data = response.json()
        if data.get("ok"):
            return data["result"]["status"] in ["member", "administrator", "creator"]
        return False
    except Exception:
        return False

@app.get("/", response_class=HTMLResponse)
async def get_index():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h3>⚠️ خطأ: لم يتم العثور على ملف index.html في السيرفر!</h3>"

@app.post("/api/user/status")
async def get_user_status(user: UserInitData):
    is_subscribed = check_telegram_membership(user.telegram_id, CHANNEL_USERNAME)
    verified_status = 1 if is_subscribed else 0

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT balance_ton, watched_ads_for_withdraw FROM users WHERE telegram_id = ?", (user.telegram_id,))
    row = cursor.fetchone()

    if not row:
        cursor.execute("INSERT INTO users VALUES (?, ?, 0.0, 0, ?)", (user.telegram_id, user.username, verified_status))
        if user.referrer_id and user.referrer_id != user.telegram_id:
            try:
                cursor.execute("INSERT INTO referrals VALUES (?, ?, 'pending')", (user.referrer_id, user.telegram_id))
            except sqlite3.IntegrityError:
                pass
        conn.commit()
        balance, watched = 0.0, 0
    else:
        cursor.execute("UPDATE users SET is_verified = ? WHERE telegram_id = ?", (verified_status, user.telegram_id))
        conn.commit()
        balance, watched = row, row
    
    cursor.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user.telegram_id,))
    ref_count = cursor.fetchone()[0]
    conn.close()

    return {
        "telegram_id": user.telegram_id,
        "balance_ton": balance,
        "watched_ads": watched,
        "referrals_count": ref_count,
        "must_subscribe": not is_subscribed,
        "channel_url": f"https://t.me{CHANNEL_USERNAME.replace('@', '')}"
    }

@app.post("/api/ads/watch")
async def watch_ad(req: WatchAdRequest):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    reward = 0.001
    cursor.execute("UPDATE users SET balance_ton = balance_ton + ?, watched_ads_for_withdraw = watched_ads_for_withdraw + ? WHERE telegram_id = ?", (reward, 1, req.telegram_id))
    conn.commit()
    cursor.execute("SELECT watched_ads_for_withdraw FROM users WHERE telegram_id = ?", (req.telegram_id,))
    row = cursor.fetchone()[0]
    conn.close()
    return {"success": True, "new_reward": reward, "total_watched": row}

@app.post("/api/user/withdraw")
async def request_withdraw(req: WithdrawRequest):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT balance_ton, watched_ads_for_withdraw FROM users WHERE telegram_id = ?", (req.telegram_id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="المستخدم غير مسجل")

    balance, watched_ads = row[0], row[1]
    if balance < 0.50:
        conn.close()
        raise HTTPException(status_code=400, detail="الحد الأدنى للسحب هو 0.50 TON")

    if watched_ads < 20:
        conn.close()
        raise HTTPException(status_code=400, detail=f"يجب مشاهدة 20 إعلاناً. لقد شاهدت: {watched_ads}/20")

    cursor.execute("UPDATE users SET watched_ads_for_withdraw = 0, balance_ton = 0.0 WHERE telegram_id = ?", (req.telegram_id,))
    cursor.execute("INSERT INTO withdrawals (telegram_id, wallet, amount, status) VALUES (?, ?, ?, 'pending')",
                   (req.telegram_id, req.wallet_address, balance))
    conn.commit()
    conn.close()
    return {"success": True, "message": "تم تقديم طلب السحب بنجاح!"}
