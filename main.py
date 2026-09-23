import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import threading

# تهيئة البوت باستخدام التوكن السري المخزن في Render
bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    """استقبال المستخدمين عند الضغط على /start وإظهار زر التطبيق المصغر"""
    user_id = message.from_user.id
    username = message.from_user.username or "User"
    
    # 🔗 التقاط معرف الشخص الداعي إذا كان المستخدم قد دخل عبر رابط إحالة
    # تليجرام يرسل معرف الداعي بعد أمر /start تلقائياً كمصطلح نصي
    text_parts = message.text.split()
    referrer_id = text_parts[1] if len(text_parts) > 1 else None

    # تجهيز نص الترحيب الأنيق
    welcome_text = (
        f"👋 أهلاً بك يا @{username} في منصة TON Task Earn!\n\n"
        "💰 هنا يمكنك كسب عملة TON الحقيقية مجاناً عبر إتمام المهام البسيطة ومشاهدة الإعلانات، "
        "أو يمكنك ترويج قناتك الخاصة لآلاف المستخدمين.\n\n"
        "👇 اضغط على الزر بالأسفل لفتح التطبيق وبدء الكسب الآن!"
    )

    # 🛠️ إنشاء الزر الشفاف التفاعلي المدمج لفتح التطبيق
    markup = InlineKeyboardMarkup()
    
    # رابط التطبيق المصغر الذي حصلت عليه من BotFather (استبدله برابط تطبيقك الفعلي)
    # مثال: https://t.me
    # نقوم بتمرير معرف الإحالة (startapp) داخله برمجياً لكي يلقطه كود الواجهة
    app_url = f"https://t.me/tonmonyAdsbot/tonmonyads"
    
    if referrer_id:
        app_url += f"?startapp={referrer_id}"

    webapp_button = InlineKeyboardButton(
        text="🚀 فتح التطبيق وبدء الكسب", 
        url=app_url
    )
    markup.add(webapp_button)

    # إرسال الرسالة للمستخدم مع الزر
    bot.send_message(message.chat.id, welcome_text, reply_markup=markup)

# 🔄 دالة لتشغيل البوت في خلفية السيرفر (Background Thread) دون أن يعطل مسارات FastAPI
def run_bot():
    bot.remove_webhook()
    bot.infinity_polling()

# إطلاق البوت تلقائياً فور تشغيل السيرفر على Render
threading.Thread(target=run_bot, daemon=True).start()
