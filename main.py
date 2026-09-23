import os
import sqlite3
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests

app = FastAPI()

# تفعيل الـ CORS لتتمكن واجهة المستخدم (HTML) من الاتصال بالسيرفر
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ⚙️ جلب المتغيرات البيئية من سيرفر Render
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")  # معرف قناتك الأساسية (مثال: @my_channel)

# 🗄️ اسم ملف قاعدة البيانات المجانية التي ستنشأ تلقائياً داخل Render
DB_FILE = "app_database.db"

def init_db():
    """إنشاء الجداول البرمجية داخل السيرفر تلقائياً عند التشغيل الأول"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # جدول المستخدمين وأرصدتهم بالـ TON وعداد الإعلانات
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            telegram_id TEXT PRIMARY KEY,
            username TEXT,
            balance_ton REAL,
            watched_ads_for_withdraw INTEGER,
            is_verified INTEGER
        )
    ''')
    
    # جدول حملات المعلنين الخارجيين لقنوات تليجرام
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
    
    # جدول فواتير السحب لتدقيقها ودفعها للمستخدمين
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id TEXT,
            wallet TEXT,
            amount REAL,
            status TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

# تشغيل دالة تهيئة قاعدة البيانات تلقائياً
init_db()

# ----------------------------------------------------
# 📌 النماذج البرمجية للبيانات المستقبلة (Pydantic Models)
# ----------------------------------------------------
class UserInitData(BaseModel):
    telegram_id: str
    username: str = "unknown"

class WatchAdRequest(BaseModel):
    telegram_id: str

class CreateAdRequest(BaseModel):
    owner_id: str
    channel_link: str

class CompleteTaskRequest(BaseModel):
    telegram_id: str
    ad_id: int

class WithdrawRequest(BaseModel):
    telegram_id: str
    wallet_address: str

# ----------------------------------------------------
# 🔍 الدوال المساعدة
# ----------------------------------------------------
def check_telegram_membership(user_id: str, chat_id: str) -> bool:
    """التحقق برمجياً من اشتراك المستخدم في قناة تليجرام معينة"""
    try:
        url = f"https://telegram.org{BOT_TOKEN}/getChatMember"
        response = requests.get(url, params={"chat_id": chat_id, "user_id": user_id}, timeout=10)
        data = response.json()
        if data.get("ok"):
            status = data["result"]["status"]
            return status in ["member", "administrator", "creator"]
        return False
    except Exception:
        return False

# ----------------------------------------------------
# 🚀 المسارات البرمجية للتطبيق (API Endpoints)
# ----------------------------------------------------

@app.post("/api/user/status")
async def get_user_status(user: UserInitData):
    """جلب بيانات المستخدم والتحقق من اشتراكه الإلزامي بقناتك"""
    is_subscribed = check_telegram_membership(user.telegram_id, CHANNEL_USERNAME)
    verified_status = 1 if is_subscribed else 0

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT balance_ton, watched_ads_for_withdraw FROM users WHERE telegram_id = ?", (user.telegram_id,))
    row = cursor.fetchone()

    if not row:
        # تسجيل مستخدم جديد برصيد صفر تـون
        cursor.execute("INSERT INTO users VALUES (?, ?, 0.0, 0, ?)", (user.telegram_id, user.username, verified_status))
        conn.commit()
        balance, watched = 0.0, 0
    else:
        # تحديث حالة اشتراكه الحالية بالقناة
        cursor.execute("UPDATE users SET is_verified = ? WHERE telegram_id = ?", (verified_status, user.telegram_id))
        conn.commit()
        balance, watched = row[0], row[1]
    
    conn.close()

    return {
        "telegram_id": user.telegram_id,
        "balance_ton": balance,
        "watched_ads": watched,
        "must_subscribe": not is_subscribed,
        "channel_url": f"https://t.me{CHANNEL_USERNAME.replace('@', '')}"
    }

@app.post("/api/ads/watch")
async def watch_ad(req: WatchAdRequest):
    """احساب أرباح مشاهدة الإعلانات الاختيارية وتحديث عداد السحب الـ 20"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    reward = 0.001  # المكافأة بالـ TON عن كل إعلان
    cursor.execute("UPDATE users SET balance_ton = balance_ton + ?, watched_ads_for_withdraw = watched_ads_for_withdraw + ? WHERE telegram_id = ?", (reward, 1, req.telegram_id))
    conn.commit()
    
    cursor.execute("SELECT watched_ads_for_withdraw FROM users WHERE telegram_id = ?", (req.telegram_id,))
    row = cursor.fetchone()
    conn.close()
    
    return {"success": True, "new_reward": reward, "total_watched": row[0] if row else 1}

@app.post("/api/campaigns/create")
async def create_campaign(req: CreateAdRequest):
    """إنشاء معلن خارجي لحملة ترويجية بقيمة 0.30 TON من رصيده الداخلي"""
    total_cost = 0.30
    admin_profit = 0.10
    reward_per_user = (total_cost - admin_profit) / 100  # 0.002 TON للمستخدم المشترك

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT balance_ton FROM users WHERE telegram_id = ?", (req.owner_id,))
    row = cursor.fetchone()

    if not row or row[0] < total_cost:
        conn.close()
        raise HTTPException(status_code=400, detail="رصيدك الداخلي غير كافٍ لإنشاء الإعلان")

    # خصم تكلفة الحملة
    cursor.execute("UPDATE users SET balance_ton = balance_ton - ? WHERE telegram_id = ?", (total_cost, req.owner_id))
    
    # تسجيل الإعلان الجديد في جدول الحملات
    cursor.execute("INSERT INTO campaigns (owner_id, channel, target, current_count, reward_per_user, participants, status) VALUES (?, ?, 100, 0, ?, '', 'active')",
                   (req.owner_id, req.channel_link, reward_per_user))
    conn.commit()
    conn.close()
    return {"success": True}

@app.post("/api/user/withdraw")
async def request_withdraw(req: WithdrawRequest):
    """معالجة طلب السحب والتحقق الصارم من شرط الـ 20 إعلان والحد الأدنى 0.50 TON"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT balance_ton, watched_ads_for_withdraw FROM users WHERE telegram_id = ?", (req.telegram_id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="المستخدم غير مسجل")

    balance, watched_ads = row[0], row[1]
    min_withdraw = 0.50

    if balance < min_withdraw:
        conn.close()
        raise HTTPException(status_code=400, detail=f"الحد الأدنى للسحب هو {min_withdraw} TON")

    # 🔒 شرط الـ 20 إعلان الإجباري للسحب لضمان أرباح المنصة وتغطية الرسوم
    if watched_ads < 20:
        conn.close()
        raise HTTPException(status_code=400, detail=f"يجب مشاهدة 20 إعلاناً لفك قفل السحب. لقد شاهدت: {watched_ads}/20")

    # تصفير العداد وخصم الرصيد المسحوب
    cursor.execute("UPDATE users SET watched_ads_for_withdraw = 0, balance_ton = 0.0 WHERE telegram_id = ?", (req.telegram_id,))
    
    # تسجيل طلب السحب في جدول الفواتير للأدمن
    cursor.execute("INSERT INTO withdrawals (telegram_id, wallet, amount, status) VALUES (?, ?, ?, 'pending')",
                   (req.telegram_id, req.wallet_address, balance))
    
    conn.commit()
    conn.close()
    return {"success": True, "message": "تم تقديم طلب السحب بنجاح! سيتم التحويل إلى محفظة Tonkeeper الخاصة بك قريباً."}
from fastapi.responses import HTMLResponse

@app.get("/", response_class=HTMLResponse)
async def get_index():
    """دالة لقرأة ملف index.html وعرضه مباشرة عند فتح الرابط العام"""
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h3>⚠️ خطأ: لم يتم العثور على ملف index.html في السيرفر!</h3>"
