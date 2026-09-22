import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

app = FastAPI()

# تفعيل الـ CORS لتتمكن واجهة المستخدم (HTML) من الاتصال بالسيرفر بدون مشاكل أمنية
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ⚙️ جلب المتغيرات البيئية السرية من منصة Render
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")  # قناتك الحالية (مثال: @my_channel)

# الاتصال بقاعدة البيانات MongoDB
client = AsyncIOMotorClient(MONGO_URI)
db = client["ton_ad_platform"]

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
    ad_id: str

class WithdrawRequest(BaseModel):
    telegram_id: str
    wallet_address: str

# ----------------------------------------------------
# 🔍 الدوال المساعدة (Helper Functions)
# ----------------------------------------------------
def check_telegram_membership(user_id: str, chat_id: str) -> bool:
    """التحقق برمجياً من اشتراك المستخدم في قناة تليجرام معينة"""
    try:
        url = f"https://telegram.org{BOT_TOKEN}/getChatMember"
        response = requests.get(url, params={"chat_id": chat_id, "user_id": user_id}, timeout=10)
        data = response.json()
        if data.get("ok"):
            status = data["result"]["status"]
            # العضو، المسؤول، والمنشئ يعتبرون مشتركين فعالين
            return status in ["member", "administrator", "creator"]
        return False
    except Exception:
        return False

# ----------------------------------------------------
# 🚀 المسارات البرمجية للتطبيق (API Endpoints)
# ----------------------------------------------------

@app.post("/api/user/status")
async def get_user_status(user: UserInitData):
    """جلب بيانات المستخدم، والتأكد من اشتراكه الإلزامي في قناتك الأساسية"""
    # 1. التحقق من الاشتراك الإلزامي بالقناة التابعة لك
    is_subscribed = check_telegram_membership(user.telegram_id, CHANNEL_USERNAME)
    
    # 2. البحث عن المستخدم أو إنشائه إن لم يكن موجوداً
    db_user = await db.users.find_one({"_id": user.telegram_id})
    if not db_user:
        db_user = {
            "_id": user.telegram_id,
            "username": user.username,
            "balance_ton": 0.0,
            "watched_ads_for_withdraw": 0,
            "is_verified": is_subscribed
        }
        await db.users.insert_one(db_user)
    else:
        # تحديث حالة التحقق في قاعدة البيانات
        await db.users.update_one({"_id": user.telegram_id}, {"$set": {"is_verified": is_subscribed}})
        db_user["is_verified"] = is_subscribed

    return {
        "telegram_id": db_user["_id"],
        "balance_ton": db_user["balance_ton"],
        "watched_ads": db_user["watched_ads_for_withdraw"],
        "must_subscribe": not is_subscribed,
        "channel_url": f"https://t.me{CHANNEL_USERNAME.replace('@', '')}"
    }

@app.post("/api/ads/watch")
async def watch_ad(req: WatchAdRequest):
    """احساب مشاهدة الإعلانات الاختيارية لزيادة الرصيد وتحديث عداد السحب"""
    user = await db.users.find_one({"_id": req.telegram_id})
    if not user:
        raise HTTPException(status_code=404, detail="المستخدم غير مسجل")

    # إضافة مكافأة مشاهدة الإعلان الاختياري (مثال: 0.001 TON)
    # وزيادة عداد السحب الإجباري بمقدار 1 حتى يصل لـ 20
    reward = 0.001 
    
    await db.users.update_one(
        {"_id": req.telegram_id},
        {
            "$inc": {
                "balance_ton": reward,
                "watched_ads_for_withdraw": 1
            }
        }
    )
    return {"success": True, "new_reward": reward, "total_watched": user.get("watched_ads_for_withdraw", 0) + 1}

@app.post("/api/campaigns/create")
async def create_campaign(req: CreateAdRequest):
    """إنشاء معلن خارجي لحملة إعلانية (تبادل أعضاء) بقيمة 0.30 TON داخل التطبيق"""
    total_cost = 0.30
    admin_profit = 0.10
    reward_per_user = (total_cost - admin_profit) / 100 # 0.002 TON للمستخدم المشترك

    user = await db.users.find_one({"_id": req.owner_id})
    if not user or user.get("balance_ton", 0) < total_cost:
        raise HTTPException(status_code=400, detail="رصيدك الداخلي غير كافٍ لإنشاء الإعلان")

    # خصم تكلفة الإعلان من رصيد المعلن الداخلي
    await db.users.update_one({"_id": req.owner_id}, {"$inc": {"balance_ton": -total_cost}})

    # تسجيل الحملة الإعلانية الجديدة
    new_ad = {
        "owner_id": req.owner_id,
        "channel": req.channel_link, # يجب أن يكون المعرف مثل @example_channel
        "target": 100,
        "current_count": 0,
        "reward_per_user": reward_per_user,
        "participants": [],
        "status": "active"
    }
    
    result = await db.campaigns.insert_one(new_ad)
    return {"success": True, "campaign_id": str(result.inserted_id)}

@app.post("/api/tasks/verify")
async def verify_task(req: CompleteTaskRequest):
    """تحقق مستخدم عادي من تنفيذ مهمة اشتراك بقناة معلن خارجي وكسب TON"""
    try:
        campaign = await db.campaigns.find_one({"_id": ObjectId(req.ad_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="معرف الحملة غير صحيح")

    if not campaign or campaign["status"] != "active":
        raise HTTPException(status_code=404, detail="هذه الحملة غير نشطة أو مكتملة")

    if req.telegram_id in campaign["participants"]:
        raise HTTPException(status_code=400, detail="لقد قمت بإتمام هذه المهمة مسبقاً")

    # التحقق من الاشتراك الفعلي في قناة المعلن الخارجي
    is_member = check_telegram_membership(req.telegram_id, campaign["channel"])
    if not is_member:
        raise HTTPException(status_code=400, detail="لم تشترك في القناة بعد! الرجاء الاشتراك أولاً")

    # تحديث الحملة الإعلانية
    await db.campaigns.update_one(
        {"_id": ObjectId(req.ad_id)},
        {"$inc": {"current_count": 1}, "$push": {"participants": req.telegram_id}}
    )

    # إضافة المكافأة بالـ TON لحساب المستخدم مباشرة
    await db.users.update_one(
        {"_id": req.telegram_id},
        {"$inc": {"balance_ton": campaign["reward_per_user"]}}
    )

    # إغلاق الحملة إذا بلغت الـ 100 مشترك المطلوبين
    if campaign["current_count"] + 1 >= campaign["target"]:
        await db.campaigns.update_one({"_id": ObjectId(req.ad_id)}, {"$set": {"status": "completed"}})

    return {"success": True, "earned": campaign["reward_per_user"]}

@app.post("/api/user/withdraw")
async def request_withdraw(req: WithdrawRequest):
    """معالجة طلب السحب والتحقق الصارم من شروط الـ 20 إعلان والحد الأدنى"""
    user = await db.users.find_one({"_id": req.telegram_id})
    if not user:
        raise HTTPException(status_code=404, detail="المستخدم غير مسجل")

    min_withdraw = 0.50 # الحد الأدنى للسحب 0.50 TON
    if user.get("balance_ton", 0) < min_withdraw:
        raise HTTPException(status_code=400, detail=f"الحد الأدنى للسحب هو {min_withdraw} TON")

    # 🔒 التحقق الصارم من شرط مشاهدة الـ 20 إعلان
    if user.get("watched_ads_for_withdraw", 0) < 20:
        raise HTTPException(
            status_code=400, 
            detail=f"يجب مشاهدة 20 إعلاناً لفتح السحب وتغطية الرسوم. لقد شاهدت: {user.get('watched_ads_for_withdraw', 0)}/20"
        )

    # إذا استوفى الشروط، يتم تصفير العداد وخصم الرصيد بانتظار التحويل اليدوي أو عبر المحفظة الساخنة
    await db.users.update_one(
        {"_id": req.telegram_id},
        {
            "$set": {"watched_ads_for_withdraw": 0},
            "$inc": {"balance_ton": -user["balance_ton"]}
        }
    )

    # هنا يتم تسجيل عملية السحب في جدول السحوبات ليقوم الأدمن بالدفع أو ربط محفظة آلية لاحقاً
    withdrawal_invoice = {
        "telegram_id": req.telegram_id,
        "wallet": req.wallet_address,
        "amount": user["balance_ton"],
        "status": "pending_payout"
    }
    await db.withdrawals.insert_one(withdrawal_invoice)

    return {"success": True, "message": "تم تقديم طلب السحب بنجاح! سيتم التحويل إلى محفظتك قريباً بعد مراجعة الأمان."}

@app.post("/api/admin/clean-leavers")
async def clean_leavers():
    """نظام العقوبات: فحص دوري لقنوات المعلنين ومعاقبة من غادروا بالخصم من أرصدتهم"""
    penalties_count = 0
    async for campaign in db.campaigns.find({"status": "active"}):
        for user_id in campaign["participants"]:
            if not check_telegram_membership(user_id, campaign["channel"]):
                # المستخدم غش وغادر القناة، نقوم بخصم المكافأة وسحبه من المشاركين
                await db.users.update_one({"_id": user_id}, {"$inc": {"balance_ton": -campaign["reward_per_user"]}})
                await db.campaigns.update_one({"_id": campaign["_id"]}, {"$pull": {"participants": user_id}})
                penalties_count += 1
                
    return {"success": True, "penalties_applied": penalties_count}
