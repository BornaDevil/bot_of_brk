import os
import logging
import sqlite3
import re
import traceback
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ---------- تنظیمات ----------
TOKEN = "8930850659:AAHPa6kZCIctxoqK6B2m6f6B9Xpdz_kPZ4k"
MASTER_ADMIN_ID = 6747512673

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- تابع escape ایمن ----------
def escape_markdown(text):
    if text is None:
        return ""
    text = str(text)
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(r'([{}])'.format(re.escape(escape_chars)), r'\\\1', text)

# ---------- دیتابیس ----------
conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        first_name TEXT,
        username TEXT,
        role TEXT DEFAULT 'user',
        is_blocked INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_user_id INTEGER,
        to_user_id INTEGER,
        message_text TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
""")
conn.commit()

# ---------- توابع کمکی ----------
def add_user(user_id, first_name, username, role='user'):
    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, first_name, username, role) VALUES (?, ?, ?, ?)",
        (user_id, first_name, username, role)
    )
    conn.commit()

def get_user_role(user_id):
    cursor.execute("SELECT role FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else 'user'

def set_user_role(user_id, role):
    cursor.execute("UPDATE users SET role = ? WHERE user_id = ?", (role, user_id))
    conn.commit()

def is_user_blocked(user_id):
    cursor.execute("SELECT is_blocked FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row is not None and row[0] == 1

def block_user(user_id):
    cursor.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (user_id,))
    conn.commit()

def save_message(from_user_id, to_user_id, text):
    cursor.execute(
        "INSERT INTO messages (from_user_id, to_user_id, message_text) VALUES (?, ?, ?)",
        (from_user_id, to_user_id, text)
    )
    conn.commit()

def get_recent_messages(limit=20):
    cursor.execute(
        "SELECT from_user_id, to_user_id, message_text, created_at FROM messages ORDER BY id DESC LIMIT ?",
        (limit,)
    )
    return cursor.fetchall()

def get_user_info(user_id):
    cursor.execute("SELECT first_name, username FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row if row else ("نامشخص", "ندارد")

def get_all_admins():
    cursor.execute("SELECT user_id FROM users WHERE role = 'admin'")
    return [row[0] for row in cursor.fetchall()]

# ---------- هندلر استارت (با لاگ کامل) ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.info("📩 دریافت /start از کاربر")
        user = update.effective_user
        user_id = user.id
        first_name = user.first_name or ""
        username = user.username or ""

        logger.info(f"👤 کاربر: {user_id} - {first_name}")

        existing_role = get_user_role(user_id)
        if existing_role == 'user':
            add_user(user_id, first_name, username, 'user')
        else:
            cursor.execute("UPDATE users SET first_name = ?, username = ? WHERE user_id = ?",
                          (first_name, username, user_id))
            conn.commit()

        args = context.args
        if args:
            try:
                target_id = int(args[0])
                if target_id != user_id:
                    context.user_data['target_user_id'] = target_id
                    await update.message.reply_text(
                        f"🔹 شما در حال ارسال پیام ناشناس به کاربری با آیدی `{target_id}` هستید.\n"
                        "📝 پیام خود را بفرستید."
                    )
                    return
            except ValueError:
                pass

        role = get_user_role(user_id)
        logger.info(f"📌 نقش کاربر: {role}")

        if role == 'admin' or user_id == MASTER_ADMIN_ID:
            keyboard = [
                [InlineKeyboardButton("📋 مشاهده لاگ", callback_data="view_log")],
                [InlineKeyboardButton("📊 آمار کاربران", callback_data="stats")],
                [InlineKeyboardButton("➕ اضافه کردن ادمین", callback_data="add_admin")],
            ]
            if user_id == MASTER_ADMIN_ID:
                keyboard.append([InlineKeyboardButton("❌ حذف ادمین", callback_data="remove_admin")])
            
            await update.message.reply_text(
                "👋 **سلام ادمین! به پنل مدیریت خوش آمدی.**\n\nاز دکمه‌های زیر استفاده کن:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="MarkdownV2"
            )
            logger.info("✅ پیام ادمین ارسال شد")
        else:
            bot_username = (await context.bot.get_me()).username
            link = f"https://t.me/{bot_username}?start={user_id}"
            await update.message.reply_text(
                f"👋 سلام {escape_markdown(first_name)}!\n\n"
                f"🔗 **لینک اختصاصی شما:**\n{escape_markdown(link)}\n\n"
                "با ارسال این لینک به دیگران، آن‌ها می‌توانند **به شما** پیام ناشناس بفرستند.\n"
                "برای ارسال پیام به ادمین، مستقیم پیام خود را بفرستید.",
                parse_mode="MarkdownV2"
            )
            logger.info("✅ پیام کاربر عادی ارسال شد")

    except Exception as e:
        logger.error(f"❌ خطا در start: {e}")
        logger.error(traceback.format_exc())
        await update.message.reply_text("❌ خطایی رخ داد. لطفاً دوباره تلاش کن.")

# ---------- بقیه توابع (همون کد قبلی) ----------
# برای اختصار، بقیه توابع رو اینجا نمی‌نویسم چون قبلاً فرستادم
# ولی تو باید کل کد رو با نسخه‌ی جدید جایگزین کنی

# ---------- تابع اصلی ----------
def main():
    logger.info("🚀 ربات در حال اجراست...")
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.User(MASTER_ADMIN_ID), handle_text_input))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_reply))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_message))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(application.run_polling(allowed_updates=Update.ALL_TYPES))
    finally:
        loop.close()

if __name__ == "__main__":
    main()
