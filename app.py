import os
import logging
import sqlite3
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

# ---------- هندلر استارت ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        user_id = user.id
        first_name = user.first_name or ""
        username = user.username or ""

        # ثبت یا به‌روزرسانی کاربر
        existing_role = get_user_role(user_id)
        if existing_role == 'user':
            add_user(user_id, first_name, username, 'user')
        else:
            cursor.execute("UPDATE users SET first_name = ?, username = ? WHERE user_id = ?",
                          (first_name, username, user_id))
            conn.commit()

        # بررسی لینک اختصاصی
        args = context.args
        if args:
            try:
                target_id = int(args[0])
                if target_id != user_id:
                    context.user_data['target_user_id'] = target_id
                    await update.message.reply_text(
                        f"🔹 شما در حال ارسال پیام ناشناس به کاربری با آیدی {target_id} هستید.\n"
                        "📝 پیام خود را بفرستید."
                    )
                    return
            except ValueError:
                pass

        # گرفتن نقش کاربر
        role = get_user_role(user_id)
        is_admin = (role == 'admin' or user_id == MASTER_ADMIN_ID)

        # لینک اختصاصی برای همه
        bot_username = (await context.bot.get_me()).username
        link = f"https://t.me/{bot_username}?start={user_id}"

        main_message = (
            f"👋 سلام {first_name}!\n\n"
            f"🔗 لینک اختصاصی شما:\n{link}\n\n"
            "با ارسال این لینک به دیگران، آن‌ها می‌توانند به شما پیام ناشناس بفرستند.\n"
            "برای ارسال پیام به ادمین، مستقیم پیام خود را بفرستید."
        )

        # اگر ادمین هست، پنل رو هم اضافه کن
        if is_admin:
            keyboard = [
                [InlineKeyboardButton("📋 مشاهده لاگ", callback_data="view_log")],
                [InlineKeyboardButton("📊 آمار کاربران", callback_data="stats")],
                [InlineKeyboardButton("➕ اضافه کردن ادمین", callback_data="add_admin")],
            ]
            if user_id == MASTER_ADMIN_ID:
                keyboard.append([InlineKeyboardButton("❌ حذف ادمین", callback_data="remove_admin")])

            await update.message.reply_text(
                main_message + "\n\n👑 پنل مدیریت:\nاز دکمه‌های زیر استفاده کن:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await update.message.reply_text(main_message)

    except Exception as e:
        logger.error(f"خطا در start: {e}\n{traceback.format_exc()}")
        await update.message.reply_text("❌ خطایی رخ داد. لطفاً دوباره تلاش کن.")

# ---------- هندلر پیام‌ها ----------
async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        user_id = user.id
        text = update.message.text

        if is_user_blocked(user_id):
            await update.message.reply_text("⛔ شما بلاک شده‌اید.")
            return

        # ---------- ارسال به لینک اختصاصی (ناشناس) ----------
        target_id = context.user_data.get('target_user_id')
        if target_id:
            logger.info(f"📩 ارسال پیام ناشناس از {user_id} به {target_id}")

            save_message(user_id, target_id, text)

            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=f"📩 پیام ناشناس از طرف یک کاربر:\n\n{text}"
                )
                await update.message.reply_text("✅ پیام شما با موفقیت ارسال شد.")
                logger.info(f"✅ پیام با موفقیت به {target_id} ارسال شد.")

            except Exception as e:
                logger.error(f"❌ خطا در ارسال به {target_id}: {e}")
                error_msg = str(e).lower()

                if "user is deactivated" in error_msg or "bot was blocked" in error_msg or "chat not found" in error_msg:
                    await update.message.reply_text(
                        "❌ کاربر مورد نظر ربات را استارت نکرده یا بلاک کرده است.\n"
                        "لطفاً مطمئن شوید که آن کاربر ربات را استارت کرده باشد."
                    )
                elif "forbidden" in error_msg:
                    await update.message.reply_text("❌ شما اجازه ارسال پیام به این کاربر را ندارید.")
                else:
                    await update.message.reply_text(f"❌ خطا در ارسال پیام: {str(e)[:100]}")

            context.user_data.pop('target_user_id', None)
            return

        # ---------- ارسال به ادمین‌ها (پیام معمولی) ----------
        admins = get_all_admins()
        if not admins:
            await update.message.reply_text("⚠️ هیچ ادمینی برای دریافت پیام وجود ندارد.")
            return

        first_name = user.first_name or "ندارد"
        username = user.username or "ندارد"
        log_msg = (
            f"📩 پیام جدید از طرف کاربر:\n"
            f"👤 نام: {first_name}\n"
            f"🆔 آیدی: {user_id}\n"
            f"📛 یوزرنیم: @{username if username else 'ندارد'}\n\n"
            f"📝 متن:\n{text}"
        )
        keyboard = [
            [InlineKeyboardButton("✉️ پاسخ", callback_data=f"reply_{user_id}")],
            [InlineKeyboardButton("🚫 بلاک", callback_data=f"block_{user_id}")]
        ]
        for admin_id in admins:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=log_msg,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception as e:
                logger.error(f"نمی‌توان به ادمین {admin_id} ارسال کرد: {e}")

        save_message(user_id, admins[0], text)
        await update.message.reply_text("✅ پیام شما برای ادمین‌ها ارسال شد.")

    except Exception as e:
        logger.error(f"خطا در handle_user_message: {e}\n{traceback.format_exc()}")
        await update.message.reply_text("❌ خطایی رخ داد.")

# ---------- هندلر دکمه‌ها ----------
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        role = get_user_role(user_id)
        is_master = (user_id == MASTER_ADMIN_ID)

        if role != 'admin' and not is_master:
            await query.edit_message_text("⛔ شما دسترسی به این بخش را ندارید.")
            return

        data = query.data

        if data == "view_log":
            messages = get_recent_messages(20)
            if not messages:
                await query.edit_message_text("📭 هیچ پیامی یافت نشد.")
                return
            text = "📋 لاگ پیام‌های اخیر:\n\n"
            for from_id, to_id, msg, created in messages:
                from_name, _ = get_user_info(from_id)
                to_name, _ = get_user_info(to_id)
                text += f"🆔 از {from_name} ({from_id}) به {to_name} ({to_id}):\n\"{msg[:40]}{'...' if len(msg)>40 else ''}\"\n\n"
            await query.edit_message_text(text)

        elif data == "stats":
            cursor.execute("SELECT COUNT(*) FROM users WHERE role='user'")
            users_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM messages")
            messages_count = cursor.fetchone()[0]
            await query.edit_message_text(
                f"📊 آمار کلی:\n\n"
                f"👥 تعداد کاربران عادی: {users_count}\n"
                f"💬 تعداد کل پیام‌ها: {messages_count}"
            )

        elif data == "add_admin":
            if not is_master:
                await query.edit_message_text("⛔ فقط ادمین اصلی می‌تواند ادمین اضافه کند.")
                return
            context.user_data['add_admin_mode'] = True
            await query.edit_message_text(
                "🔹 لطفاً آیدی عددی یا یوزرنیم (با @) کاربر مورد نظر را وارد کنید.\n"
                "مثال: 123456789 یا @username\n\n"
                "برای لغو، دستور /cancel را بفرستید."
            )

        elif data == "remove_admin":
            if not is_master:
                await query.edit_message_text("⛔ فقط ادمین اصلی می‌تواند ادمین حذف کند.")
                return
            admins = get_all_admins()
            keyboard = []
            for admin_id in admins:
                if admin_id == MASTER_ADMIN_ID:
                    continue
                first_name, _ = get_user_info(admin_id)
                keyboard.append([InlineKeyboardButton(f"🗑️ {first_name} ({admin_id})", callback_data=f"remove_confirm_{admin_id}")])
            if not keyboard:
                await query.edit_message_text("📭 هیچ ادمین دیگری برای حذف وجود ندارد.")
                return
            await query.edit_message_text(
                "👤 لیست ادمین‌ها (به جز خودت):\nروی هرکدام کلیک کن تا حذف شود.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif data.startswith("remove_confirm_"):
            if not is_master:
                await query.edit_message_text("⛔ فقط ادمین اصلی می‌تواند ادمین حذف کند.")
                return
            target_id = int(data.split("_")[2])
            if target_id == MASTER_ADMIN_ID:
                await query.edit_message_text("⛔ نمی‌توانی خودت را حذف کنی.")
                return
            set_user_role(target_id, 'user')
            await query.edit_message_text(f"✅ کاربر با آیدی {target_id} از نقش ادمین حذف شد.")

        elif data.startswith("reply_"):
            target_id = int(data.split("_")[1])
            context.user_data['reply_to_user'] = target_id
            context.user_data['waiting_for_reply'] = True
            await query.edit_message_text(
                f"✉️ پاسخ خود را برای کاربر با آیدی {target_id} تایپ کنید.\n(برای لغو، دستور /cancel را بفرستید.)"
            )

        elif data.startswith("block_"):
            target_id = int(data.split("_")[1])
            block_user(target_id)
            await query.edit_message_text(f"✅ کاربر با آیدی {target_id} با موفقیت بلاک شد.")

    except Exception as e:
        logger.error(f"خطا در button_callback: {e}\n{traceback.format_exc()}")
        await query.edit_message_text("❌ خطایی رخ داد.")

# ---------- هندلر اضافه کردن ادمین ----------
async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        if user_id != MASTER_ADMIN_ID:
            return

        if context.user_data.get('add_admin_mode'):
            text = update.message.text.strip()
            if text.startswith('@'):
                username = text[1:]
                try:
                    chat = await context.bot.get_chat(f"@{username}")
                    target_id = chat.id
                except Exception as e:
                    await update.message.reply_text(f"❌ کاربر با یوزرنیم {text} پیدا نشد.")
                    context.user_data['add_admin_mode'] = False
                    return
            else:
                try:
                    target_id = int(text)
                except ValueError:
                    await update.message.reply_text("❌ لطفاً یک آیدی عددی معتبر یا یوزرنیم با @ وارد کنید.")
                    return

            role = get_user_role(target_id)
            if role == 'admin':
                await update.message.reply_text(f"ℹ️ کاربر با آیدی {target_id} از قبل ادمین است.")
            else:
                set_user_role(target_id, 'admin')
                add_user(target_id, "", "", 'admin')
                await update.message.reply_text(f"✅ کاربر با آیدی {target_id} با موفقیت به ادمین‌ها اضافه شد.")

            context.user_data['add_admin_mode'] = False

    except Exception as e:
        logger.error(f"خطا در handle_text_input: {e}\n{traceback.format_exc()}")
        await update.message.reply_text("❌ خطایی رخ داد.")

# ---------- هندلر پاسخ ادمین ----------
async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        role = get_user_role(user_id)
        if role != 'admin' and user_id != MASTER_ADMIN_ID:
            return

        if not context.user_data.get('waiting_for_reply'):
            return

        target_id = context.user_data.get('reply_to_user')
        if not target_id:
            await update.message.reply_text("❌ خطا: کاربر مقصد یافت نشد.")
            context.user_data['waiting_for_reply'] = False
            return

        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"📩 پاسخ ادمین:\n\n{update.message.text}"
            )
            await update.message.reply_text("✅ پیام شما با موفقیت ارسال شد.")
        except Exception as e:
            logger.error(f"خطا در ارسال پاسخ: {e}")
            await update.message.reply_text("❌ خطا در ارسال پیام. کاربر ممکن است ربات را بلاک کرده باشد.")

        context.user_data['waiting_for_reply'] = False
        context.user_data['reply_to_user'] = None

    except Exception as e:
        logger.error(f"خطا در handle_admin_reply: {e}\n{traceback.format_exc()}")
        await update.message.reply_text("❌ خطایی رخ داد.")

# ---------- هندلر لغو ----------
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        role = get_user_role(user_id)
        if role != 'admin' and user_id != MASTER_ADMIN_ID:
            return

        if context.user_data.get('add_admin_mode'):
            context.user_data['add_admin_mode'] = False
            await update.message.reply_text("✅ حالت اضافه کردن ادمین لغو شد.")
        elif context.user_data.get('waiting_for_reply'):
            context.user_data['waiting_for_reply'] = False
            context.user_data['reply_to_user'] = None
            await update.message.reply_text("✅ حالت پاسخگویی لغو شد.")
        else:
            await update.message.reply_text("⚠️ شما در هیچ حالت خاصی نیستید.")

    except Exception as e:
        logger.error(f"خطا در cancel: {e}\n{traceback.format_exc()}")

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
