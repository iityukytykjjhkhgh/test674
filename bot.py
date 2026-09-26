# bot.py - Dark Point Telegram Bot (Bulletproof Version)

import os
import logging
import time
import random
import string
import html
import asyncio
import json
import re
import threading
import requests
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)
from telegram.constants import ParseMode

from config import *
from database import Database

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

db = Database()

CAPTCHA_VERIFY = 1

# ============ HELPERS ============

def format_number(num):
    return "{:,}".format(int(num))

def get_level_title(level):
    return LEVEL_TITLES.get(level, f"سطح {level}")

def get_dp_range(level):
    base_min = BASE_MIN_DP + (level - 1) * DP_INCREASE_PER_LEVEL
    base_max = BASE_MAX_DP + (level - 1) * DP_INCREASE_PER_LEVEL
    return base_min, base_max

def get_random_cooldown():
    return random.randint(MIN_COOLDOWN, MAX_COOLDOWN)

def get_next_level_requirement(level):
    if level >= 20:
        return None
    return LEVEL_REQUIREMENTS.get(level + 1, None)

def generate_captcha():
    num1 = random.randint(1, 20)
    num2 = random.randint(1, 20)
    op = random.choice(['+', '-'])
    if op == '+':
        answer = num1 + num2
    else:
        if num1 < num2:
            num1, num2 = num2, num1
        answer = num1 - num2
    return f"{num1} {op} {num2}", answer

def get_user_display(user):
    safe_name = html.escape(user.first_name)
    if user.username:
        return f"@{user.username}"
    return f'<a href="tg://user?id={user.id}">{safe_name}</a>'

async def check_force_join(user_id, context):
    channels = db.get_force_channels()
    if not channels:
        return True
    for ch in channels:
        try:
            member = await context.bot.get_chat_member(ch['channel_username'], user_id)
            if member.status in ['left', 'kicked']:
                return False
        except Exception:
            continue
    return True

async def send_log(context, text, reply_markup=None):
    try:
        await context.bot.send_message(
            LOG_CHANNEL_ID, text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Log error: {e}")

def is_admin(user_id):
    return user_id in ADMIN_IDS

# ============ KEEP-ALIVE SERVER ============

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        res = "<html><body style='background:#000;color:#0f0;text-align:center;'><h1>Dark Point Bot Live!</h1></body></html>"
        self.wfile.write(res.encode("utf-8"))
    def log_message(self, format, *args):
        return

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
    except Exception as e:
        logger.error(f"Health error: {e}")

async def self_ping(context: ContextTypes.DEFAULT_TYPE):
    url = os.environ.get("RENDER_EXTERNAL_URL")
    if not url:
        return
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'DarkBot'})
        with urllib.request.urlopen(req, timeout=15) as r:
            pass
    except Exception:
        pass

# ============ START & MENU ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    if db.is_banned(user.id):
        await update.message.reply_text("❌ شما از ربات مسدود شده‌اید.")
        return ConversationHandler.END

    existing = db.get_user(user.id)
    if not existing:
        referrer_id = 0
        if args and args[0].startswith("ref_"):
            try:
                referrer_id = int(args[0].replace("ref_", ""))
                if referrer_id == user.id:
                    referrer_id = 0
            except Exception:
                referrer_id = 0

        db.create_user(user.id, user.username or "", user.first_name or "", referrer_id)

        if referrer_id > 0:
            context.user_data['pending_referrer'] = referrer_id
            captcha_q, captcha_a = generate_captcha()
            context.user_data['captcha_answer'] = captcha_a

            await update.message.reply_text(
                f"🔐 <b>تایید هویت</b>\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"لطفاً پاسخ این سوال را ارسال کنید:\n\n"
                f"❓ <code>{captcha_q}</code> = ?\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💡 <i>فقط عدد پاسخ را ارسال کنید</i>",
                parse_mode=ParseMode.HTML
            )
            return CAPTCHA_VERIFY

    db.update_last_active(user.id)

    if args and args[0].startswith("check_"):
        code = args[0].replace("check_", "")
        amount = db.claim_check(code, user.id)
        if amount:
            db.add_dark_points(user.id, amount)
            await update.message.reply_text(
                f"🎁 <b>چک شخصی فعال شد!</b>\n\n"
                f"💰 مبلغ: <code>{format_number(amount)}</code> DP\n"
                f"✅ به موجودی شما اضافه شد",
                parse_mode=ParseMode.HTML
            )
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        admin_id,
                        f"📋 چک فعال شد\n👤 <code>{user.id}</code>\n💰 <code>{format_number(amount)}</code> DP",
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass
            return ConversationHandler.END
        else:
            await update.message.reply_text("❌ این چک قبلاً استفاده شده یا نامعتبر است.")
            return ConversationHandler.END

    joined = await check_force_join(user.id, context)
    if not joined:
        channels = db.get_force_channels()
        channels_text = "\n".join([f"🔗 {ch['channel_username']}" for ch in channels])
        kb = [[InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_join_main")]]
        await update.message.reply_text(
            f"📢 <b>عضویت در کانال‌های زیر الزامی است:</b>\n\n"
            f"{channels_text}\n\n"
            f"سپس روی بررسی عضویت بزنید.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return ConversationHandler.END

    await show_main_menu(update, context)
    return ConversationHandler.END


async def captcha_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        answer = int(update.message.text.strip())
    except Exception:
        await update.message.reply_text("❌ لطفاً فقط عدد بفرستید.")
        return CAPTCHA_VERIFY

    correct = context.user_data.get('captcha_answer')
    referrer_id = context.user_data.get('pending_referrer', 0)

    if answer != correct:
        captcha_q, captcha_a = generate_captcha()
        context.user_data['captcha_answer'] = captcha_a
        await update.message.reply_text(
            f"❌ <b>پاسخ اشتباه!</b>\n\n❓ سوال جدید: <code>{captcha_q}</code> = ?",
            parse_mode=ParseMode.HTML
        )
        return CAPTCHA_VERIFY

    joined = await check_force_join(user.id, context)
    if not joined:
        channels = db.get_force_channels()
        channels_text = "\n".join([f"🔗 {ch['channel_username']}" for ch in channels])
        kb = [[InlineKeyboardButton("✅ عضو شدم", callback_data="check_join_ref")]]
        await update.message.reply_text(
            f"📢 <b>ابتدا در کانال‌ها عضو شوید:</b>\n\n{channels_text}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return ConversationHandler.END

    if referrer_id > 0:
        db.add_referral(referrer_id)
        db.add_dark_points(referrer_id, REFERRAL_REWARD)
        try:
            await context.bot.send_message(
                referrer_id,
                f"🎉 <b>زیرمجموعه جدید!</b>\n💰 +{format_number(REFERRAL_REWARD)} DP دریافت کردید!",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass

    context.user_data.pop('captcha_answer', None)
    context.user_data.pop('pending_referrer', None)

    await show_main_menu(update, context)
    return ConversationHandler.END


async def check_join_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()
    joined = await check_force_join(user.id, context)
    if not joined:
        await query.answer("❌ هنوز در کانال‌ها عضو نشده‌اید!", show_alert=True)
        return
    await show_main_menu(update, context, query=query)


async def check_join_ref_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    joined = await check_force_join(user.id, context)
    if not joined:
        await query.answer("❌ هنوز عضو نشده‌اید!", show_alert=True)
        return

    referrer_id = context.user_data.get('pending_referrer', 0)
    if referrer_id > 0:
        db.add_referral(referrer_id)
        db.add_dark_points(referrer_id, REFERRAL_REWARD)
        try:
            await context.bot.send_message(
                referrer_id,
                f"🎉 <b>زیرمجموعه جدید!</b>\n💰 +{format_number(REFERRAL_REWARD)} DP!",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass

    context.user_data.pop('captcha_answer', None)
    context.user_data.pop('pending_referrer', None)
    await show_main_menu(update, context, query=query)


async def show_main_menu(update, context, query=None):
    user = update.effective_user
    db_user = db.get_user(user.id)
    if not db_user:
        db.create_user(user.id, user.username or "", user.first_name or "")
        db_user = db.get_user(user.id)

    db.update_last_active(user.id)
    balance = db_user['dark_points']
    level = db_user['level']
    title = get_level_title(level)
    safe_name = html.escape(user.first_name)

    bot_username = (await context.bot.get_me()).username

    keyboard = [
        [InlineKeyboardButton("⭐️ 🌟 برداشت استارز 🌟 ⭐️", callback_data="stars_withdraw")],
        [
            InlineKeyboardButton("🏴 دارک پوینت", callback_data="dark_point_menu"),
            InlineKeyboardButton("🛒 خرید پنل", callback_data="buy_panel"),
        ],
        [
            InlineKeyboardButton("💥 بازی انفجار", callback_data="crash_menu"),
            InlineKeyboardButton("🎁 گیفت رایگان", callback_data="free_gift"),
        ],
        [
            InlineKeyboardButton("💰 خرید دارک پوینت", callback_data="buy_dp"),
            InlineKeyboardButton("❤️ چالش لایکی", callback_data="like_challenge"),
        ],
        [
            InlineKeyboardButton("👥 زیرمجموعه‌گیری", callback_data="referral_menu"),
            InlineKeyboardButton("🏆 لیدربورد", callback_data="leaderboard"),
        ],
        [InlineKeyboardButton("➕ افزودن به گروه", url=f"https://t.me/{bot_username}?startgroup=true")],
    ]

    text = (
        f"🏴 <b>به ربات دارک پوینت خوش آمدید!</b> 🏴\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 کاربر: <b>{safe_name}</b>\n"
        f"🆔 شناسه: <code>{user.id}</code>\n"
        f"💎 موجودی: <code>{format_number(balance)}</code> DP\n"
        f"📊 سطح شما: {level} | {title}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⭐ <i>هر ۱ میلیون DP = ۵۰ استارز رایگان!</i>\n"
        f"👥 <i>با زیرمجموعه‌گیری دارک پوینت نامحدود بگیر!</i>"
    )

    if query:
        try:
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception:
            await query.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))


# ============ DARK POINT MENU ============

async def dark_point_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = db.get_user(query.from_user.id)
    balance = user['dark_points'] if user else 0
    level = user['level'] if user else 1
    title = get_level_title(level)
    next_req = get_next_level_requirement(level)
    needed = max(0, (next_req or 0) - (user['total_earned'] if user else 0))

    keyboard = [
        [InlineKeyboardButton("📖 توضیحات کامل دارک پوینت", callback_data="dp_info_1")],
        [InlineKeyboardButton("🔗 لینک زیرمجموعه", callback_data="referral_menu")],
        [InlineKeyboardButton("🏆 لیدربورد", callback_data="leaderboard")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
    ]

    text = (
        f"🏴 <b>پنل دارک پوینت</b> 🏴\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💎 موجودی: <code>{format_number(balance)}</code> DP\n"
        f"📊 سطح: {level} | {title}\n"
    )
    if next_req:
        text += f"📈 تا سطح بعد: <code>{format_number(needed)}</code> DP\n"
    else:
        text += f"🏆 به بالاترین سطح رسیده‌اید!\n"

    text += (
        f"\n👥 زیرمجموعه‌ها: {user['referral_count'] if user else 0}\n"
        f"📊 کل دریافتی: <code>{format_number(user['total_earned'] if user else 0)}</code> DP\n\n"
        f"━━━━━━━━━━━━━━━━━━"
    )

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))


INFO_PAGES = {
    1: (
        "📖 <b>دارک پوینت - صفحه ۱/۸</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🏴 <b>دارک پوینت چیست؟</b>\n\n"
        "واحد پولی اختصاصی این ربات که با آن می‌توانید:\n\n"
        "⭐ استارز تلگرام دریافت کنید\n"
        "🛒 پنل VPN نامحدود بگیرید\n"
        "🎁 گیفت تدی بگیرید\n"
        "💥 بازی انفجار کنید\n"
        "🏭 کارخونه استخراج بسازید\n"
        "🏦 در بانک سود ۱۰٪ بگیرید\n\n"
        "⭐ <b>هر ۱,۰۰۰,۰۰۰ DP = ۵۰ استارز</b>"
    ),
    2: (
        "📖 <b>دارک پوینت - صفحه ۲/۸</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "💰 <b>راه‌های کسب دارک پوینت:</b>\n\n"
        "1️⃣ در گروه بگویید: <code>دارک</code> یا <code>دارک کانفیگ</code>\n"
        "2️⃣ زیرمجموعه‌گیری (هر نفر ۳۰,۰۰۰ DP)\n"
        "3️⃣ افتتاح کارخونه دارکی\n"
        "4️⃣ سرمایه‌گذاری در بانک دارکی\n"
        "5️⃣ شرکت در بازی انفجار و دو نفره"
    ),
    3: (
        "📖 <b>دارک پوینت - صفحه ۳/۸</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "📊 <b>سیستم ۲۰ سطحی:</b>\n\n"
        "سطح ۱: 0 DP\n"
        "سطح ۵: 150K DP\n"
        "سطح ۱۰: 1M DP\n"
        "سطح ۱۵: 3M DP\n"
        "سطح ۲۰: 20M DP\n\n"
        "🎁 با هر بار ارتقای سطح، پاداش دریافت می‌کنید."
    ),
    4: (
        "📖 <b>دارک پوینت - صفحه ۴/۸</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🏭 <b>کارخونه دارکی:</b>\n\n"
        "افتتاح: ۱۰۰,۰۰۰ DP\n"
        "نگهداری: ساعتی ۸۰ DP\n\n"
        "سطح ۱: ۱۰ DP/دقیقه\n"
        "سطح ۲: ۲۵ DP/دقیقه\n"
        "سطح ۳: ۴۰ DP/دقیقه\n"
        "سطح ۴: ۵۰ DP/دقیقه\n"
        "سطح ۵: ۱۰۰ DP/دقیقه\n\n"
        "دستور در گروه: <code>کارخونه دارکی</code>"
    ),
    5: (
        "📖 <b>دارک پوینت - صفحه ۵/۸</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🏦 <b>بانک دارکی:</b>\n\n"
        "افتتاح: ۲۰,۰۰۰ DP\n"
        "سود سپرده ۲۴ ساعته: ۱۰٪\n\n"
        "🎮 <b>بازی دو نفره:</b>\n"
        "دستور: <code>بازی 1000</code>\n"
        "جایزه برنده: ۲ برابر مبلغ"
    ),
    6: (
        "📖 <b>دارک پوینت - صفحه ۶/۸</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "💸 <b>انتقال دارک پوینت:</b>\n\n"
        "روش ۱: ریپلای روی پیام + <code>انتقال 1000</code>\n"
        "روش ۲: <code>انتقال 1000 به 123456789</code>\n"
        "کارمزد انتقال: ۱۰٪\n\n"
        "❤️ <b>چالش لایکی ۷ روزه:</b> ۳۰,۰۰۰ DP"
    ),
    7: (
        "📖 <b>دارک پوینت - صفحه ۷/۸</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "⭐ <b>برداشت استارز:</b>\n"
        "هر ۱ میلیون دارک پوینت = ۵۰ استارز مستقیم\n\n"
        "🎁 <b>گیفت رایگان:</b> گیفت تدی تلگرام\n\n"
        "📝 <b>دستورات گروه:</b>\n"
        "• <code>دارک</code>\n"
        "• <code>موجودی</code>\n"
        "• <code>پروفایل دارکی</code>\n"
        "• <code>بازی [مبلغ]</code>\n"
        "• <code>انفجار [مبلغ]</code>\n"
        "• <code>بانک دارکی</code>\n"
        "• <code>کارخونه دارکی</code>"
    ),
    8: (
        "📖 <b>دارک پوینت - صفحه ۸/۸</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "💥 <b>بازی انفجار:</b>\n\n"
        "دستور در گروه: <code>انفجار 1000</code>\n\n"
        "ضریب صعود می‌کند؛ قبل از منفجر شدن دکمه برداشت را بزنید!\n"
        "حداقل شرط: ۵۰۰ DP\n"
        "حداکثر شرط: ۵۰۰,۰۰۰ DP"
    ),
}

async def dp_info_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    page = int(query.data.split("_")[-1])
    text = INFO_PAGES.get(page, "صفحه یافت نشد")

    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"dp_info_{page-1}"))
    if page < 8:
        buttons.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"dp_info_{page+1}"))

    keyboard = [buttons] if buttons else []
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="dark_point_menu")])

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))


# ============ GROUP HANDLERS ============

async def on_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            try:
                count = await context.bot.get_chat_member_count(chat.id)
                if count < MIN_GROUP_MEMBERS:
                    await update.message.reply_text(
                        f"❌ <b>گروه باید حداقل {MIN_GROUP_MEMBERS} عضو داشته باشد!</b>\n"
                        f"👥 اعضای فعلی: {count}",
                        parse_mode=ParseMode.HTML
                    )
                    await context.bot.leave_chat(chat.id)
                    return
                db.add_group(chat.id, chat.title, count)
                await update.message.reply_text(
                    "🏴 <b>ربات دارک پوینت با موفقیت فعال شد!</b>\n\n"
                    "📝 <b>دستورات:</b>\n"
                    "• <code>دارک</code> - دریافت امتیاز\n"
                    "• <code>موجودی</code> - موجودی من\n"
                    "• <code>پروفایل دارکی</code> - پروفایل من\n"
                    "• <code>بازی 1000</code> - بازی دو نفره\n"
                    "• <code>انفجار 1000</code> - بازی انفجار\n"
                    "• <code>انتقال 1000</code> - انتقال امتیاز\n"
                    "• <code>بانک دارکی</code> - مدیریت بانک\n"
                    "• <code>کارخونه دارکی</code> - کارخونه استخراج",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Group error: {e}")


async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    user = update.effective_user
    chat = update.effective_chat

    if chat.type not in ['group', 'supergroup']:
        return

    if db.is_banned(user.id):
        return

    if not db.get_user(user.id):
        db.create_user(user.id, user.username or "", user.first_name or "")

    db.update_last_active(user.id)

    u = db.get_user(user.id)
    if u and u['factory_active']:
        db.factory_maintenance_due(user.id)

    if text in ['دارک', 'دارک کانفیگ']:
        await handle_dark_claim(update, context)
    elif text == 'موجودی':
        await handle_balance_check(update, context)
    elif text == 'پروفایل دارکی':
        await handle_dark_profile(update, context)
    elif text.startswith('بازی'):
        parts = text.split()
        if len(parts) >= 2:
            try:
                amount = int(parts[1])
                await handle_create_game(update, context, amount)
            except ValueError:
                pass
    elif text.startswith('انفجار'):
        parts = text.split()
        if len(parts) >= 2:
            try:
                amount = int(parts[1])
                await handle_crash_game_group(update, context, amount)
            except ValueError:
                pass
    elif text.startswith('انتقال '):
        await handle_transfer(update, context)
    elif text == 'بانک دارکی':
        await handle_bank(update, context)
    elif text == 'کارخونه دارکی':
        await handle_factory(update, context)
    elif text == 'لیدربورد':
        await handle_leaderboard_group(update, context)


async def handle_dark_claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = db.get_user(user.id)
    if not u:
        db.create_user(user.id, user.username or "", user.first_name or "")
        u = db.get_user(user.id)

    remaining = db.get_cooldown_remaining(user.id)
    if remaining > 0:
        mins = int(remaining // 60)
        secs = int(remaining % 60)
        await update.message.reply_text(
            f"⏳ <b>کمی صبر کنید!</b>\n\n"
            f"⏰ <code>{mins}</code> دقیقه و <code>{secs}</code> ثانیه تا دریافت بعدی باقی مانده است.",
            parse_mode=ParseMode.HTML
        )
        return

    level = u['level']
    min_dp, max_dp = get_dp_range(level)
    earned = random.randint(min_dp, max_dp)
    cooldown = get_random_cooldown()

    db.add_dark_points(user.id, earned)
    db.set_claim(user.id, cooldown)

    new_level, reward = db.check_and_update_level(user.id)
    safe_name = html.escape(user.first_name)

    cd_mins = cooldown // 60
    cd_secs = cooldown % 60

    text = (
        f"🏴 <b>دارک پوینت دریافت شد!</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 کاربر: <b>{safe_name}</b>\n"
        f"💎 مقدار: +<code>{format_number(earned)}</code> DP\n"
        f"📊 سطح: {level} | {get_level_title(level)}\n"
        f"💰 موجودی: <code>{format_number(db.get_balance(user.id))}</code> DP\n\n"
        f"⏰ دریافت بعدی: {cd_mins}m {cd_secs}s"
    )

    if new_level:
        text += (
            f"\n\n🎉 <b>تبریک! ارتقا به سطح {new_level}!</b>\n"
            f"🏅 لقب جدید: {get_level_title(new_level)}\n"
            f"🎁 جایزه: +<code>{format_number(reward)}</code> DP"
        )

    bot_username = (await context.bot.get_me()).username
    kb = [[InlineKeyboardButton("🏴 ورود به ربات", url=f"https://t.me/{bot_username}")]]
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def handle_balance_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    balance = db.get_balance(user.id)
    level = db.get_level(user.id)
    safe_name = html.escape(user.first_name)

    bot_username = (await context.bot.get_me()).username
    kb = [[InlineKeyboardButton("🏴 ربات دارک پوینت", url=f"https://t.me/{bot_username}")]]
    await update.message.reply_text(
        f"💎 <b>استعلام موجودی</b>\n\n"
        f"👤 کاربر: <b>{safe_name}</b>\n"
        f"💰 موجودی: <code>{format_number(balance)}</code> DP\n"
        f"📊 سطح: {level} | {get_level_title(level)}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def handle_dark_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = db.get_user(user.id)
    if not u:
        return

    level = u['level']
    balance = u['dark_points']
    total = u['total_earned']
    refs = u['referral_count']
    title = get_level_title(level)
    next_req = get_next_level_requirement(level)
    needed = max(0, (next_req or 0) - total) if next_req else 0
    safe_name = html.escape(user.first_name)

    factory_info = ""
    if u['factory_active']:
        f_level = u['factory_level']
        mine_rate = FACTORY_LEVELS[f_level]['mine_per_min']
        factory_info = f"🏭 کارخونه: سطح {f_level} ({mine_rate} DP/min)\n"

    bank_info = ""
    if u['bank_account']:
        bank_info = f"🏦 موجودی بانک: <code>{format_number(u['bank_balance'])}</code> DP\n"

    stars_price = int(db.get_setting('stars_price', '1000000'))
    stars_can = balance // stars_price
    if stars_can > 0:
        stars_text = f"⭐ قابل برداشت: {stars_can * 50} استارز\n"
    else:
        stars_text = f"⭐ تا استارز: <code>{format_number(stars_price - balance)}</code> DP\n"

    crash_played = u['crash_games_played']
    crash_won = u['crash_games_won']
    win_rate = int((crash_won / crash_played * 100) if crash_played > 0 else 0)

    text = (
        f"🏴 <b>پروفایل کاربری</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 نام: <b>{safe_name}</b>\n"
        f"🆔 شناسه: <code>{user.id}</code>\n"
        f"📛 یوزرنیم: @{user.username or 'ندارد'}\n\n"
        f"💰 موجودی: <code>{format_number(balance)}</code> DP\n"
        f"📊 سطح: {level} | {title}\n"
    )

    if next_req:
        text += f"📈 تا سطح {level+1}: <code>{format_number(needed)}</code> DP\n"
    else:
        text += f"🏆 بالاترین سطح!\n"

    text += (
        f"📊 کل دریافتی: <code>{format_number(total)}</code> DP\n"
        f"👥 زیرمجموعه‌ها: {refs}\n"
        f"{stars_text}"
        f"{factory_info}"
        f"{bank_info}"
        f"💥 انفجار: {crash_won}/{crash_played} ({win_rate}% برد)\n"
        f"━━━━━━━━━━━━━━━━━━"
    )

    bot_username = (await context.bot.get_me()).username
    kb = [[InlineKeyboardButton("🏴 ورود به ربات", url=f"https://t.me/{bot_username}")]]
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


# ============ GAME ============

async def handle_create_game(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: int):
    user = update.effective_user
    chat = update.effective_chat

    if amount < MIN_GAME_AMOUNT:
        await update.message.reply_text(f"❌ حداقل مبلغ: {format_number(MIN_GAME_AMOUNT)} DP")
        return

    balance = db.get_balance(user.id)
    if balance < amount:
        await update.message.reply_text(
            f"❌ موجودی ناکافی!\n💰 موجودی شما: <code>{format_number(balance)}</code> DP",
            parse_mode=ParseMode.HTML
        )
        return

    db.remove_dark_points(user.id, amount)

    msg = await update.message.reply_text(
        f"🎮 <b>بازی جدید ایجاد شد!</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 سازنده: {get_user_display(user)}\n"
        f"💰 مبلغ ورودی: <code>{format_number(amount)}</code> DP\n"
        f"🏆 جایزه برنده: <code>{format_number(amount * 2)}</code> DP\n\n"
        f"⏳ در انتظار حریف...",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎮 پیوستن به بازی", callback_data="join_game_0")],
            [InlineKeyboardButton("❌ لغو بازی", callback_data="cancel_game_0")],
        ])
    )

    game_id = db.create_game(user.id, amount, chat.id, msg.message_id)

    await msg.edit_reply_markup(InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 پیوستن به بازی", callback_data=f"join_game_{game_id}")],
        [InlineKeyboardButton("❌ لغو بازی", callback_data=f"cancel_game_{game_id}")],
    ]))


async def join_game_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    game_id = int(query.data.split("_")[-1])

    game = db.get_game(game_id)
    if not game:
        await query.answer("❌ بازی یافت نشد!", show_alert=True)
        return
    if game['status'] != 'waiting':
        await query.answer("❌ این بازی به پایان رسیده است.", show_alert=True)
        return
    if user.id == game['creator_id']:
        await query.answer("❌ نمی‌توانید با خودتان بازی کنید!", show_alert=True)
        return

    amount = game['amount']
    balance = db.get_balance(user.id)
    if balance < amount:
        await query.answer(f"❌ موجودی ناکافی! نیاز: {format_number(amount)} DP", show_alert=True)
        return

    db.remove_dark_points(user.id, amount)
    db.join_game(game_id, user.id)

    await query.answer("🎮 در حال انتخاب برنده...")
    await asyncio.sleep(2)

    players = [game['creator_id'], user.id]
    winner_id = random.choice(players)
    loser_id = players[0] if winner_id == players[1] else players[1]

    prize = amount * 2
    db.add_dark_points(winner_id, prize)
    db.finish_game(game_id, winner_id, loser_id)

    try:
        w_obj = await context.bot.get_chat(winner_id)
        w_disp = f"@{w_obj.username}" if w_obj.username else html.escape(w_obj.first_name)
    except Exception:
        w_disp = str(winner_id)

    try:
        l_obj = await context.bot.get_chat(loser_id)
        l_disp = f"@{l_obj.username}" if l_obj.username else html.escape(l_obj.first_name)
    except Exception:
        l_disp = str(loser_id)

    await query.edit_message_text(
        f"🎮 <b>نتیجه بازی دو نفره</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🏆 برنده: <b>{w_disp}</b> (+{format_number(prize)} DP)\n"
        f"💔 بازنده: <b>{l_disp}</b>\n\n"
        f"🎲 <i>برنده به صورت تصادفی انتخاب شد.</i>",
        parse_mode=ParseMode.HTML
    )


async def cancel_game_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    game_id = int(query.data.split("_")[-1])

    game = db.get_game(game_id)
    if not game:
        await query.answer("❌ یافت نشد!", show_alert=True)
        return
    if user.id != game['creator_id']:
        await query.answer("❌ فقط سازنده می‌تواند لغو کند!", show_alert=True)
        return
    if game['status'] != 'waiting':
        await query.answer("❌ بازی قبلاً شروع شده است!", show_alert=True)
        return

    db.add_dark_points(game['creator_id'], game['amount'])
    db.cancel_game(game_id)

    await query.edit_message_text(
        f"❌ بازی لغو شد و مبلغ <code>{format_number(game['amount'])}</code> DP برگشت داده شد.",
        parse_mode=ParseMode.HTML
    )


# ============ CRASH GAME ============

def generate_crash_point():
    r = random.random()
    if r < 0.35:
        return round(random.uniform(1.01, 1.5), 2)
    elif r < 0.70:
        return round(random.uniform(1.5, 3.0), 2)
    elif r < 0.90:
        return round(random.uniform(3.0, 6.0), 2)
    else:
        return round(random.uniform(6.0, CRASH_MAX_MULTIPLIER), 2)


async def crash_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if db.get_setting('crash_active', '1') != '1':
        await query.answer("❌ بازی انفجار موقتاً خاموش است.", show_alert=True)
        return

    balance = db.get_balance(user.id)
    u = db.get_user(user.id)

    text = (
        f"💥 <b>بازی انفجار دارکی</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 <b>نحوه بازی در گروه:</b>\n"
        f"دستور: <code>انفجار 1000</code>\n\n"
        f"ضریب بالا می‌رود و باید قبل از انفجار برداشت کنید!\n\n"
        f"💰 موجودی شما: <code>{format_number(balance)}</code> DP\n"
        f"💥 کل بازی‌ها: {u['crash_games_played']}\n"
        f"🏆 بردها: {u['crash_games_won']}\n\n"
        f"⚠️ حداقل شرط: {format_number(CRASH_MIN_BET)} DP"
    )

    kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def handle_crash_game_group(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: int):
    user = update.effective_user

    if db.get_setting('crash_active', '1') != '1':
        await update.message.reply_text("❌ بازی انفجار غیرفعال است.")
        return

    if amount < CRASH_MIN_BET or amount > CRASH_MAX_BET:
        await update.message.reply_text(f"❌ مبلغ باید بین {format_number(CRASH_MIN_BET)} تا {format_number(CRASH_MAX_BET)} باشد.")
        return

    balance = db.get_balance(user.id)
    if balance < amount:
        await update.message.reply_text(f"❌ موجودی ناکافی! موجودی: <code>{format_number(balance)}</code> DP", parse_mode=ParseMode.HTML)
        return

    db.remove_dark_points(user.id, amount)
    crash_point = generate_crash_point()

    msg = await update.message.reply_text(
        f"💥 <b>بازی انفجار شروع شد!</b>\n\n"
        f"👤 بازیکن: {get_user_display(user)}\n"
        f"💰 مبلغ شرط: <code>{format_number(amount)}</code> DP\n"
        f"🚀 ضریب: <code>1.00x</code>",
        parse_mode=ParseMode.HTML
    )

    game_id = db.create_crash_game(user.id, amount, crash_point, update.effective_chat.id, msg.message_id)

    await msg.edit_reply_markup(InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 برداشت (Cash Out)", callback_data=f"crash_out_{game_id}")]
    ]))

    asyncio.create_task(run_crash_game(context, game_id, user.id, amount, crash_point, msg.chat_id, msg.message_id))


async def run_crash_game(context, game_id, user_id, bet, crash_point, chat_id, message_id):
    current = 1.00
    step = 0.1
    delay = 1.5

    while current < crash_point:
        g = db.get_crash_game(game_id)
        if not g or g['status'] != 'playing':
            return

        await asyncio.sleep(delay)
        current = round(current + step, 2)
        if current >= crash_point:
            current = crash_point

        if current > 2:
            step = 0.2
            delay = 1.2
        if current > 5:
            step = 0.4
            delay = 1.0

        pot_win = int(bet * current)

        try:
            u_obj = await context.bot.get_chat(user_id)
            u_name = html.escape(u_obj.first_name)
        except Exception:
            u_name = str(user_id)

        try:
            await context.bot.edit_message_text(
                f"💥 <b>بازی انفجار زنده</b>\n\n"
                f"👤 بازیکن: <b>{u_name}</b>\n"
                f"💰 شرط: <code>{format_number(bet)}</code> DP\n\n"
                f"🚀 ضریب فعلی: <code>{current}x</code> 📈\n"
                f"💎 جایزه: <code>{format_number(pot_win)}</code> DP",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"💰 برداشت در {current}x", callback_data=f"crash_out_{game_id}")]
                ])
            )
        except Exception:
            pass

        if current >= crash_point:
            break

    g = db.get_crash_game(game_id)
    if g and g['status'] == 'playing':
        db.crash_game_lost(game_id)
        db.increment_crash_stats(user_id, won=False)
        try:
            u_obj = await context.bot.get_chat(user_id)
            u_name = html.escape(u_obj.first_name)
        except Exception:
            u_name = str(user_id)

        try:
            await context.bot.edit_message_text(
                f"💥💥 <b>منفجر شد!</b> 💥💥\n\n"
                f"👤 بازیکن: <b>{u_name}</b>\n"
                f"💥 ضریب انفجار: <code>{crash_point}x</code>\n"
                f"😔 نتیجه: باخت شرط ({format_number(bet)} DP)",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass


async def crash_out_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    game_id = int(query.data.split("_")[-1])

    g = db.get_crash_game(game_id)
    if not g:
        await query.answer("❌ بازی یافت نشد!", show_alert=True)
        return
    if g['user_id'] != user.id:
        await query.answer("❌ این بازی شما نیست!", show_alert=True)
        return
    if g['status'] != 'playing':
        await query.answer("❌ بازی تمام شده است!", show_alert=True)
        return

    msg_text = query.message.text
    match = re.search(r'(\d+\.\d+)x', msg_text)
    if not match:
        await query.answer("❌ خطا در ثبت ضریب!", show_alert=True)
        return

    current_mult = float(match.group(1))
    win_amount = int(g['bet_amount'] * current_mult)
    profit = win_amount - g['bet_amount']

    if db.cashout_crash_game(game_id, current_mult, profit):
        db.add_dark_points(user.id, win_amount)
        db.increment_crash_stats(user.id, won=True)
        safe_name = html.escape(user.first_name)

        await query.answer(f"✅ با موفقیت برداشت شد! +{format_number(win_amount)} DP", show_alert=True)
        await query.edit_message_text(
            f"🎉 <b>برنده شدید!</b> 🎉\n\n"
            f"👤 بازیکن: <b>{safe_name}</b>\n"
            f"💎 ضریب برداشت: <code>{current_mult}x</code>\n"
            f"🏆 کل دریافتی: <code>{format_number(win_amount)}</code> DP\n"
            f"📈 سود خالص: +<code>{format_number(profit)}</code> DP",
            parse_mode=ParseMode.HTML
        )


# ============ TRANSFERS, BANK, FACTORY ============

async def handle_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()

    if update.message.reply_to_message:
        parts = text.split()
        if len(parts) >= 2:
            try:
                amount = int(parts[1])
            except Exception:
                await update.message.reply_text("❌ مبلغ نامعتبر است.")
                return

            target_id = update.message.reply_to_message.from_user.id
            if target_id == user.id:
                await update.message.reply_text("❌ نمی‌توانید به خودتان انتقال دهید!")
                return

            fee = int(amount * TRANSFER_FEE)
            total_cost = amount + fee
            balance = db.get_balance(user.id)

            if balance < total_cost:
                await update.message.reply_text(f"❌ موجودی ناکافی! کل نیاز با کارمزد ۱۰٪: <code>{format_number(total_cost)}</code> DP", parse_mode=ParseMode.HTML)
                return

            if not db.remove_dark_points(user.id, total_cost):
                return

            db.add_dark_points(target_id, amount)
            db.record_transfer(user.id, target_id, amount, fee)

            await update.message.reply_text(
                f"✅ <b>انتقال موفق</b>\n\n"
                f"💰 مبلغ: <code>{format_number(amount)}</code> DP\n"
                f"💸 کارمزد: <code>{format_number(fee)}</code> DP\n"
                f"👤 مقصد: <code>{target_id}</code>",
                parse_mode=ParseMode.HTML
            )
            return

    match = re.match(r'انتقال\s+(\d+)\s+به\s+(\d+)', text)
    if match:
        amount = int(match.group(1))
        target_id = int(match.group(2))

        if target_id == user.id:
            await update.message.reply_text("❌ نمی‌توانید به خودتان انتقال دهید!")
            return

        fee = int(amount * TRANSFER_FEE)
        total_cost = amount + fee
        balance = db.get_balance(user.id)

        if balance < total_cost:
            await update.message.reply_text(f"❌ نیاز: <code>{format_number(total_cost)}</code> DP", parse_mode=ParseMode.HTML)
            return

        if not db.remove_dark_points(user.id, total_cost):
            return

        db.add_dark_points(target_id, amount)
        db.record_transfer(user.id, target_id, amount, fee)

        await update.message.reply_text(
            f"✅ <b>انتقال با موفقیت انجام شد.</b>\n💰 مبلغ: <code>{format_number(amount)}</code> DP",
            parse_mode=ParseMode.HTML
        )


async def handle_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = db.get_user(user.id)

    total_bank = db.get_total_bank_balance()

    if not u['bank_account']:
        kb = [[InlineKeyboardButton("🏦 افتتاح حساب (20,000 DP)", callback_data="bank_open")]]
        await update.message.reply_text(
            f"🏦 <b>بانک دارکی</b>\n\n"
            f"❌ شما حسابی ندارید.\n"
            f"💵 هزینه افتتاح: ۲۰,۰۰۰ DP\n"
            f"📈 سود سپرده ۲۴ ساعته: ۱۰٪\n\n"
            f"🏦 کل سپرده‌های بانک: <code>{format_number(total_bank)}</code> DP",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(kb)
        )
    else:
        elapsed = time.time() - u['bank_deposit_time'] if u['bank_deposit_time'] > 0 else 0
        interest_ready = elapsed >= 86400 and u['bank_balance'] > 0
        potential = int(u['bank_balance'] * 0.10) if interest_ready else 0

        buttons = []
        if u['bank_balance'] == 0:
            buttons.append([InlineKeyboardButton("💰 واریز سپرده", callback_data="bank_deposit")])
        else:
            if interest_ready:
                buttons.append([InlineKeyboardButton("💸 برداشت با سود", callback_data="bank_withdraw")])
            else:
                remaining = max(0, 86400 - elapsed)
                h = int(remaining // 3600)
                m = int((remaining % 3600) // 60)
                buttons.append([InlineKeyboardButton(f"⏰ {h}h {m}m تا سود", callback_data="bank_wait")])
            buttons.append([InlineKeyboardButton("💰 واریز بیشتر", callback_data="bank_deposit")])

        text = (
            f"🏦 <b>حساب بانک دارکی</b>\n\n"
            f"💳 شماره کارت: <code>{u['bank_card']}</code>\n"
            f"💰 موجودی در بانک: <code>{format_number(u['bank_balance'])}</code> DP\n"
        )
        if potential > 0:
            text += f"📈 سود آماده: +<code>{format_number(potential)}</code> DP\n"

        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))


async def bank_open_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if db.get_balance(user.id) < BANK_OPEN_COST:
        await query.answer(f"❌ موجودی ناکافی! نیاز: {format_number(BANK_OPEN_COST)} DP", show_alert=True)
        return

    kb = [
        [InlineKeyboardButton("🎲 ساخت خودکار", callback_data="bank_auto_card")],
        [InlineKeyboardButton("✏️ شماره دلخواه", callback_data="bank_custom_card")],
    ]
    await query.edit_message_text("🏦 نحوه ایجاد شماره کارت ۱۳ رقمی را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(kb))


async def bank_auto_card_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if db.get_balance(user.id) < BANK_OPEN_COST:
        return

    card = db.generate_bank_card()
    while db.card_exists(card):
        card = db.generate_bank_card()

    db.remove_dark_points(user.id, BANK_OPEN_COST)
    db.open_bank_account(user.id, card)

    await query.edit_message_text(
        f"✅ <b>حساب بانکی شما افتتاح شد!</b>\n\n💳 شماره کارت: <code>{card}</code>",
        parse_mode=ParseMode.HTML
    )


async def bank_custom_card_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_bank_card'] = True
    await query.edit_message_text("✏️ شماره کارت ۱۳ رقمی دلخواه (فقط عدد انگلیسی) را در پیوی بفرستید:")


async def bank_deposit_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_bank_deposit'] = True
    await query.edit_message_text("💰 مبلغ مورد نظر برای واریز به بانک را ارسال کنید:")


async def bank_withdraw_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    balance, interest = db.bank_withdraw(user.id)
    total = balance + interest
    if total == 0:
        await query.answer("❌ موجودی ندارید!", show_alert=True)
        return

    await query.edit_message_text(
        f"✅ <b>برداشت موفق!</b>\n\n💰 اصل: <code>{format_number(balance)}</code> DP\n📈 سود: <code>{format_number(interest)}</code> DP\n💎 کل: <code>{format_number(total)}</code> DP",
        parse_mode=ParseMode.HTML
    )


async def bank_wait_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("⏰ برای دریافت سود باید ۲۴ ساعت از سپرده بگذرد.", show_alert=True)


async def handle_factory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = db.get_user(user.id)

    if not u['factory_active'] and u['factory_level'] == 0:
        kb = [[InlineKeyboardButton(f"🏭 افتتاح کارخونه ({format_number(FACTORY_OPEN_COST)} DP)", callback_data="factory_open")]]
        await update.message.reply_text(
            f"🏭 <b>کارخونه دارکی</b>\n\n"
            f"❌ شما کارخونه‌ای ندارید.\n"
            f"💵 هزینه افتتاح: {format_number(FACTORY_OPEN_COST)} DP\n"
            f"🔧 هزینه نگهداری: ساعتی ۸۰ DP",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    mined = db.collect_factory(user.id)
    db.factory_maintenance_due(user.id)
    u = db.get_user(user.id)
    f_level = u['factory_level']
    mine_rate = FACTORY_LEVELS[f_level]['mine_per_min']

    buttons = []
    if f_level < 5:
        upgrade_cost = FACTORY_LEVELS[f_level]['upgrade_cost']
        buttons.append([InlineKeyboardButton(f"⬆️ ارتقا به {f_level+1} ({format_number(upgrade_cost)} DP)", callback_data="factory_upgrade")])
    buttons.append([InlineKeyboardButton("💰 جمع‌آوری دارک پوینت", callback_data="factory_collect")])

    status = "✅ فعال" if u['factory_active'] else "❌ متوقف به علت کمبود موجودی"
    text = (
        f"🏭 <b>کارخونه استخراج</b>\n\n"
        f"📊 سطح: {f_level}\n"
        f"⚡ نرخ استخراج: {mine_rate} DP/دقیقه\n"
        f"📋 وضعیت: {status}\n"
    )
    if mined > 0:
        text += f"💰 ماین شده: +<code>{format_number(mined)}</code> DP\n"

    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))


async def factory_open_cb(update, context):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if db.get_balance(user.id) < FACTORY_OPEN_COST:
        await query.answer("❌ موجودی ناکافی!", show_alert=True)
        return

    db.remove_dark_points(user.id, FACTORY_OPEN_COST)
    db.open_factory(user.id)
    await query.edit_message_text("✅ کارخونه افتتاح شد و استخراج شروع شد!")


async def factory_upgrade_cb(update, context):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    u = db.get_user(user.id)
    if not u or u['factory_level'] >= 5:
        return

    cost = FACTORY_LEVELS[u['factory_level']]['upgrade_cost']
    if db.get_balance(user.id) < cost:
        await query.answer(f"❌ نیاز: {format_number(cost)} DP", show_alert=True)
        return

    db.collect_factory(user.id)
    db.remove_dark_points(user.id, cost)
    db.upgrade_factory(user.id)
    await query.edit_message_text(f"⬆️ کارخونه به سطح {u['factory_level']+1} ارتقا یافت!")


async def factory_collect_cb(update, context):
    query = update.callback_query
    user = query.from_user
    await query.answer()
    mined = db.collect_factory(user.id)
    await query.answer(f"💰 {format_number(mined)} DP جمع‌آوری شد!", show_alert=True)


# ============ STARS & GIFTS & PANELS ============

async def stars_withdraw_menu(update, context):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if db.get_setting('stars_section_active', '1') != '1':
        await query.answer("❌ بخش برداشت استارز موقتاً خاموش است.", show_alert=True)
        return

    stars_price = int(db.get_setting('stars_price', '1000000'))
    balance = db.get_balance(user.id)
    can_withdraw = balance >= stars_price

    text = (
        f"⭐ <b>برداشت استارز تلگرام</b>\n\n"
        f"💎 موجودی شما: <code>{format_number(balance)}</code> DP\n"
        f"⭐ قیمت هر ۵۰ استارز: <code>{format_number(stars_price)}</code> DP\n\n"
    )

    if can_withdraw:
        text += "✅ شما موجودی کافی برای برداشت ۵۰ استارز را دارید!"
        kb = [
            [InlineKeyboardButton(f"⭐ برداشت {STARS_AMOUNT} استارز", callback_data="stars_do")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
        ]
    else:
        needed = stars_price - balance
        text += f"❌ برای برداشت به <code>{format_number(needed)}</code> DP دیگر نیاز دارید."
        kb = [
            [InlineKeyboardButton("👥 زیرمجموعه‌گیری", callback_data="referral_menu")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
        ]

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def stars_do(update, context):
    query = update.callback_query
    await query.answer()
    kb = [
        [InlineKeyboardButton("👤 همین اکانتم", callback_data="stars_self")],
        [InlineKeyboardButton("👥 اکانت دیگر", callback_data="stars_other")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="stars_withdraw")],
    ]
    await query.edit_message_text("⭐ استارز به کدام اکانت ارسال شود؟", reply_markup=InlineKeyboardMarkup(kb))


async def stars_self_cb(update, context):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    stars_price = int(db.get_setting('stars_price', '1000000'))
    if not db.remove_dark_points(user.id, stars_price):
        await query.answer("❌ موجودی ناکافی است!", show_alert=True)
        return

    db.create_stars_order(user.id, str(user.id), 'self', STARS_AMOUNT, stars_price)
    await query.edit_message_text("✅ سفارش برداشت ۵۰ استارز ثبت شد و به زودی واریز می‌شود.")

    bot_username = (await context.bot.get_me()).username
    log_kb = [[InlineKeyboardButton("🤖 ورود", url=f"https://t.me/{bot_username}")]]
    await send_log(context, f"⭐ <b>سفارش استارز</b>\n👤 <code>{user.id}</code>\n⭐ ۵۰ استارز", reply_markup=InlineKeyboardMarkup(log_kb))


async def stars_other_cb(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_stars_target'] = True
    await query.edit_message_text("👥 آیدی یا شماره عددی اکانت مقصد را ارسال کنید:")


async def free_gift_menu(update, context):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if db.get_setting('gift_section_active', '1') != '1':
        await query.answer("❌ بخش گیفت رایگان موقتاً خاموش است.", show_alert=True)
        return

    gift_price = int(db.get_setting('gift_teddy_price', '750000'))
    balance = db.get_balance(user.id)
    can_buy = balance >= gift_price

    text = (
        f"🎁 <b>گیفت رایگان تدی تلگرام</b>\n\n"
        f"🧸 قیمت گیفت تدی: <code>{format_number(gift_price)}</code> DP\n"
        f"💎 موجودی شما: <code>{format_number(balance)}</code> DP"
    )

    buttons = []
    if can_buy:
        buttons.append([InlineKeyboardButton("🧸 ثبت سفارش گیفت تدی", callback_data="order_gift_teddy")])
    buttons.append([InlineKeyboardButton("👥 زیرمجموعه‌گیری", callback_data="referral_menu")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))


async def order_gift_teddy(update, context):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    gift_price = int(db.get_setting('gift_teddy_price', '750000'))
    if not db.remove_dark_points(user.id, gift_price):
        await query.answer("❌ موجودی ناکافی است!", show_alert=True)
        return

    db.create_gift_order(user.id, 'teddy', gift_price)
    await query.edit_message_text("✅ سفارش گیفت تدی با موفقیت ثبت شد.")


async def buy_dp_menu(update, context):
    query = update.callback_query
    await query.answer()

    if db.get_setting('buy_dp_active', '1') != '1':
        await query.answer("❌ این بخش موقتاً غیرفعال است.", show_alert=True)
        return

    dp_amount = int(db.get_setting('buy_dp_amount', '500000'))
    price_toman = int(db.get_setting('buy_dp_price_toman', '50000'))

    text = (
        f"💰 <b>خرید مستقیم دارک پوینت</b>\n\n"
        f"💎 هر <code>{format_number(dp_amount)}</code> DP = <code>{format_number(price_toman)}</code> تومان\n\n"
        f"برای خرید به پشتیبانی پیام دهید."
    )
    kb = [
        [InlineKeyboardButton("📩 پیام به پشتیبانی", url=f"https://t.me/{SUPPORT_USERNAME.replace('@', '')}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
    ]
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def leaderboard_menu(update, context):
    query = update.callback_query
    await query.answer()

    rows = db.get_leaderboard(25)
    text = "🏆 <b>برترین کاربران دارک پوینت</b>\n\n"
    for i, row in enumerate(rows, 1):
        name = html.escape(row['first_name'] or row['username'] or str(row['user_id']))
        text += f"{i}. <b>{name}</b> — <code>{format_number(row['dark_points'])}</code> DP\n"

    kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def handle_leaderboard_group(update, context):
    rows = db.get_leaderboard(10)
    text = "🏆 <b>۱۰ کاربر برتر:</b>\n\n"
    for i, row in enumerate(rows, 1):
        name = html.escape(row['first_name'] or str(row['user_id']))
        text += f"{i}. {name} — <code>{format_number(row['dark_points'])}</code> DP\n"

    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def referral_menu(update, context):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    bot_username = (await context.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref_{user.id}"
    ref_count = db.get_referral_count(user.id)

    text = (
        f"👥 <b>سیستم زیرمجموعه‌گیری</b>\n\n"
        f"🔗 لینک اختصاصی شما:\n<code>{ref_link}</code>\n\n"
        f"👥 تعداد زیرمجموعه‌ها: <b>{ref_count}</b>\n"
        f"💰 پاداش هر عضو: <b>{format_number(REFERRAL_REWARD)}</b> DP"
    )
    kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def like_challenge_menu(update, context):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    u = db.get_user(user.id)

    if u['like_challenge_active'] and u['like_challenge_until'] > time.time():
        rem = u['like_challenge_until'] - time.time()
        days = int(rem // 86400)
        hours = int((rem % 86400) // 3600)
        text = f"❤️ <b>چالش لایکی فعال است</b> ({days} روز و {hours} ساعت باقی مانده)"
        kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
    else:
        text = f"❤️ <b>فعال‌سازی چالش لایکی ۷ روزه:</b> {format_number(LIKE_CHALLENGE_COST)} DP"
        kb = [
            [InlineKeyboardButton("✅ فعال‌سازی", callback_data="like_activate")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
        ]
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def like_activate_cb(update, context):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if not db.remove_dark_points(user.id, LIKE_CHALLENGE_COST):
        await query.answer("❌ موجودی ناکافی است!", show_alert=True)
        return

    db.update_user(user.id, like_challenge_active=1, like_challenge_until=time.time() + (7 * 86400))
    await query.edit_message_text("✅ چالش لایکی برای ۷ روز فعال شد.")


async def buy_panel_menu(update, context):
    query = update.callback_query
    await query.answer()

    buttons = [
        [InlineKeyboardButton(f"🛒 سنایی 500GB ({format_number(DEFAULT_PANEL_PRICES['snai_500gb'])} DP)", callback_data="panel_buy_snai_500gb")],
        [InlineKeyboardButton(f"🛒 سنایی 800GB ({format_number(DEFAULT_PANEL_PRICES['snai_800gb'])} DP)", callback_data="panel_buy_snai_800gb")],
        [InlineKeyboardButton(f"🛒 سنایی 1TB ({format_number(DEFAULT_PANEL_PRICES['snai_1tb'])} DP)", callback_data="panel_buy_snai_1tb")],
    ]

    for panel in db.get_custom_panels():
        buttons.append([InlineKeyboardButton(f"🛒 {panel['name']} ({format_number(panel['price'])} DP)", callback_data=f"panel_buy_custom_{panel['panel_id']}")])

    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])
    await query.edit_message_text("🛒 <b>پلن VPN مورد نظر را انتخاب کنید:</b>", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))


async def panel_buy_cb(update, context):
    query = update.callback_query
    user = query.from_user
    data = query.data

    if data.startswith("panel_buy_custom_"):
        panel_id = int(data.split("_")[-1])
        conn = db.get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM custom_panels WHERE panel_id = ?", (panel_id,))
        panel = c.fetchone()
        conn.close()
        if not panel:
            return
        name = panel['name']
        price = panel['price']
    else:
        plan_key = data.replace("panel_buy_", "")
        prices = {"snai_500gb": ("سنایی 500GB", DEFAULT_PANEL_PRICES['snai_500gb']),
                  "snai_800gb": ("سنایی 800GB", DEFAULT_PANEL_PRICES['snai_800gb']),
                  "snai_1tb": ("سنایی 1TB", DEFAULT_PANEL_PRICES['snai_1tb'])}
        if plan_key not in prices:
            return
        name, price = prices[plan_key]

    if not db.remove_dark_points(user.id, price):
        await query.answer("❌ موجودی ناکافی است!", show_alert=True)
        return

    order_id = db.create_panel_order(user.id, name, price, f"vpn_{user.id}_{int(time.time())}")
    await query.edit_message_text(f"✅ <b>خرید موفق!</b>\nپلن: {name}\nکد پیگیری: {order_id}", parse_mode=ParseMode.HTML)


# ============ ADMIN PANEL ============

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("❌ شما دسترسی به پنل ادمین را ندارید.")
        return

    stats = db.get_stats()
    kb = [
        [InlineKeyboardButton("📊 آمار کامل", callback_data="adm_stats")],
        [
            InlineKeyboardButton("📢 پیام همگانی", callback_data="adm_broadcast_msg"),
            InlineKeyboardButton("📤 فوروارد همگانی", callback_data="adm_broadcast_fwd"),
        ],
        [
            InlineKeyboardButton("💰 افزودن DP", callback_data="adm_add_dp"),
            InlineKeyboardButton("💸 کسر DP", callback_data="adm_remove_dp"),
        ],
        [
            InlineKeyboardButton("🔍 جستجوی کاربر", callback_data="adm_search_user"),
            InlineKeyboardButton("🚫 بن / آنبن", callback_data="adm_ban_user"),
        ],
        [InlineKeyboardButton("📢 مدیریت کانال‌های اجباری", callback_data="adm_channels")],
        [
            InlineKeyboardButton("🎁 روشن/خاموش گیفت", callback_data="adm_toggle_gift"),
            InlineKeyboardButton("⭐ روشن/خاموش استارز", callback_data="adm_toggle_stars"),
        ],
        [InlineKeyboardButton("📝 ساخت چک شخصی", callback_data="adm_create_check")],
        [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="main_menu")],
    ]

    text = (
        f"🛡 <b>پنل مدیریت ربات</b>\n\n"
        f"👥 کل کاربران: <b>{stats['total_users']}</b>\n"
        f"💎 کل DP در گردش: <b>{format_number(stats['total_dp'])}</b>\n"
        f"🆕 کاربران جدید امروز: <b>{stats['new_today']}</b>"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def admin_stats(update, context):
    query = update.callback_query
    await query.answer()
    stats = db.get_stats()
    text = (
        f"📊 <b>آمار جامع ربات</b>\n\n"
        f"👥 کل کاربران: {stats['total_users']}\n"
        f"✅ فعال ۷ روز اخیر: {stats['active_7d']}\n"
        f"🚫 مسدود شده: {stats['banned_users']}\n\n"
        f"💰 موجودی کل کاربران: {format_number(stats['total_dp'])} DP\n"
        f"🏦 کل دارایی بانک: {format_number(stats['total_bank'])} DP\n\n"
        f"📦 کل سفارشات پنل: {stats['panel_orders']}\n"
        f"⭐ کل سفارشات استارز: {stats['stars_orders']}"
    )
    kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="adm_back")]]
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def adm_broadcast_msg(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data['admin_action'] = 'broadcast_msg'
    await query.edit_message_text("📢 پیام مورد نظر را برای ارسال همگانی بفرستید:")


async def adm_broadcast_fwd(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data['admin_action'] = 'broadcast_fwd'
    await query.edit_message_text("📤 پیامی که می‌خواهید فوروارد شود را بفرستید:")


async def do_broadcast(update, context, mode='copy'):
    users = db.get_all_user_ids()
    total = len(users)
    sent, failed = 0, 0
    status = await update.message.reply_text(f"⏳ در حال ارسال به {total} کاربر...")

    for uid in users:
        try:
            if mode == 'copy':
                await context.bot.copy_message(chat_id=uid, from_chat_id=update.message.chat_id, message_id=update.message.message_id)
            else:
                await context.bot.forward_message(chat_id=uid, from_chat_id=update.message.chat_id, message_id=update.message.message_id)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.04)

    await status.edit_text(f"✅ ارسال به اتمام رسید!\nموفق: {sent} | ناموفق: {failed}")


async def adm_channels(update, context):
    query = update.callback_query
    await query.answer()
    channels = db.get_force_channels()
    text = "📢 <b>کانال‌های عضویت اجباری:</b>\n\n"
    for ch in channels:
        text += f"• {ch['channel_username']}\n"

    kb = [[InlineKeyboardButton("➕ افزودن کانال", callback_data="adm_add_channel")]]
    for ch in channels:
        kb.append([InlineKeyboardButton(f"🗑 حذف {ch['channel_username']}", callback_data=f"adm_del_ch_{ch['channel_id']}")])
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="adm_back")])
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def admin_callbacks(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌ دسترسی ندارید!", show_alert=True)
        return

    data = query.data
    if data == "adm_back":
        await admin_panel(update, context)
    elif data == "adm_stats":
        await admin_stats(update, context)
    elif data == "adm_broadcast_msg":
        await adm_broadcast_msg(update, context)
    elif data == "adm_broadcast_fwd":
        await adm_broadcast_fwd(update, context)
    elif data == "adm_channels":
        await adm_channels(update, context)
    elif data == "adm_add_channel":
        await query.answer()
        context.user_data['admin_action'] = 'add_channel'
        await query.edit_message_text("➕ یوزرنیم کانال را با @ ارسال کنید:")
    elif data.startswith("adm_del_ch_"):
        cid = int(data.split("_")[-1])
        db.remove_force_channel(cid)
        await query.answer("✅ کانال حذف شد.", show_alert=True)
        await adm_channels(update, context)
    elif data == "adm_add_dp":
        await query.answer()
        context.user_data['admin_action'] = 'add_dp'
        await query.edit_message_text("💰 شناسه عددی کاربر را بفرستید:")
    elif data == "adm_remove_dp":
        await query.answer()
        context.user_data['admin_action'] = 'remove_dp'
        await query.edit_message_text("💸 شناسه عددی کاربر را بفرستید:")
    elif data == "adm_search_user":
        await query.answer()
        context.user_data['admin_action'] = 'search_user'
        await query.edit_message_text("🔍 شناسه عددی یا @username را بفرستید:")
    elif data == "adm_ban_user":
        await query.answer()
        context.user_data['admin_action'] = 'ban_user'
        await query.edit_message_text("🚫 شناسه عددی کاربر را برای بن/آنبن بفرستید:")
    elif data == "adm_toggle_gift":
        cur = db.get_setting('gift_section_active', '1')
        new = '0' if cur == '1' else '1'
        db.set_setting('gift_section_active', new)
        await query.answer("تغییر اعمال شد.", show_alert=True)
        await admin_panel(update, context)
    elif data == "adm_toggle_stars":
        cur = db.get_setting('stars_section_active', '1')
        new = '0' if cur == '1' else '1'
        db.set_setting('stars_section_active', new)
        await query.answer("تغییر اعمال شد.", show_alert=True)
        await admin_panel(update, context)
    elif data == "adm_create_check":
        await query.answer()
        context.user_data['admin_action'] = 'create_check'
        await query.edit_message_text("📝 مبلغ چک شخصی (DP) را ارسال کنید:")


async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if db.is_banned(user.id):
        return

    if is_admin(user.id):
        action = context.user_data.get('admin_action')
        if action == 'broadcast_msg':
            context.user_data.pop('admin_action', None)
            await do_broadcast(update, context, mode='copy')
            return
        if action == 'broadcast_fwd':
            context.user_data.pop('admin_action', None)
            await do_broadcast(update, context, mode='forward')
            return

    text = update.message.text.strip() if update.message.text else ""
    if not text:
        return

    if is_admin(user.id) and 'admin_action' in context.user_data:
        action = context.user_data.get('admin_action')
        if action == 'add_channel':
            ch = text if text.startswith('@') else '@' + text
            db.add_force_channel(ch)
            await update.message.reply_text(f"✅ کانال {ch} اضافه شد.")
            context.user_data.clear()
            return
        if action == 'add_dp':
            if 'target' not in context.user_data:
                context.user_data['target'] = int(text)
                await update.message.reply_text("مبلغ را بفرستید:")
            else:
                amt = int(text)
                db.add_dark_points(context.user_data['target'], amt)
                await update.message.reply_text(f"✅ {amt} DP اضافه شد.")
                context.user_data.clear()
            return
        if action == 'remove_dp':
            if 'target' not in context.user_data:
                context.user_data['target'] = int(text)
                await update.message.reply_text("مبلغ را بفرستید:")
            else:
                amt = int(text)
                db.remove_dark_points(context.user_data['target'], amt)
                await update.message.reply_text(f"✅ {amt} DP کسر شد.")
                context.user_data.clear()
            return
        if action == 'create_check':
            amt = int(text)
            code = db.create_check(amt)
            bot_username = (await context.bot.get_me()).username
            await update.message.reply_text(f"✅ چک ساخته شد:\nhttps://t.me/{bot_username}?start=check_{code}")
            context.user_data.clear()
            return

    if context.user_data.get('awaiting_bank_card'):
        if len(text) == 13 and text.isdigit():
            if db.card_exists(text):
                await update.message.reply_text("❌ کارت تکراری است!")
            elif db.remove_dark_points(user.id, BANK_OPEN_COST):
                db.open_bank_account(user.id, text)
                context.user_data.clear()
                await update.message.reply_text(f"✅ حساب با کارت <code>{text}</code> ساخته شد.", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("❌ باید ۱۳ رقم انگلیسی باشد.")
        return

    if context.user_data.get('awaiting_bank_deposit'):
        try:
            amt = int(text)
            if db.bank_deposit(user.id, amt):
                context.user_data.clear()
                await update.message.reply_text("✅ مبلغ به بانک واریز شد.")
            else:
                await update.message.reply_text("❌ موجودی ناکافی!")
        except Exception:
            pass
        return


# ============ ROUTER & MAIN ============

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    routes = {
        "main_menu": show_main_menu,
        "dark_point_menu": dark_point_menu,
        "referral_menu": referral_menu,
        "stars_withdraw": stars_withdraw_menu,
        "stars_do": stars_do,
        "stars_self": stars_self_cb,
        "stars_other": stars_other_cb,
        "free_gift": free_gift_menu,
        "order_gift_teddy": order_gift_teddy,
        "buy_dp": buy_dp_menu,
        "leaderboard": leaderboard_menu,
        "like_challenge": like_challenge_menu,
        "like_activate": like_activate_cb,
        "buy_panel": buy_panel_menu,
        "bank_open": bank_open_cb,
        "bank_auto_card": bank_auto_card_cb,
        "bank_custom_card": bank_custom_card_cb,
        "bank_deposit": bank_deposit_cb,
        "bank_withdraw": bank_withdraw_cb,
        "bank_wait": bank_wait_cb,
        "factory_open": factory_open_cb,
        "factory_upgrade": factory_upgrade_cb,
        "factory_collect": factory_collect_cb,
        "check_join_main": check_join_main,
        "check_join_ref": check_join_ref_cb,
        "crash_menu": crash_menu,
    }

    if data == "main_menu":
        await show_main_menu(update, context, query=query)
    elif data in routes:
        await routes[data](update, context)
    elif data.startswith("dp_info_"):
        await dp_info_page(update, context)
    elif data.startswith("panel_buy_"):
        await panel_buy_cb(update, context)
    elif data.startswith("join_game_"):
        await join_game_callback(update, context)
    elif data.startswith("cancel_game_"):
        await cancel_game_callback(update, context)
    elif data.startswith("crash_out_"):
        await crash_out_callback(update, context)
    elif data.startswith("adm_"):
        await admin_callbacks(update, context)


def main():
    start_health_server()
    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CAPTCHA_VERIFY: [MessageHandler(filters.TEXT & ~filters.COMMAND, captcha_verify)],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True
    )
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CallbackQueryHandler(callback_router))
    application.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, handle_group_message))
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, handle_private_message))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_chat_members))

    application.job_queue.run_repeating(self_ping, interval=480, first=60)

    print("Dark Point Bot is fully running!")
    application.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
