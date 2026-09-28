# bot.py - Dark Point Bot (Ultimate Professional Version)

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
    ContextTypes, filters
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
BOT_USERNAME = ""

# ============ HELPER FUNCTIONS ============

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
    num1 = random.randint(1, 15)
    num2 = random.randint(1, 15)
    op = random.choice(['+', '-'])
    if op == '+':
        answer = num1 + num2
    else:
        if num1 < num2:
            num1, num2 = num2, num1
        answer = num1 - num2
    return f"{num1} {op} {num2}", answer

def get_user_display(user):
    safe_name = html.escape(user.first_name or "کاربر")
    if user.username:
        return f"@{user.username}"
    return f'<a href="tg://user?id={user.id}">{safe_name}</a>'

async def get_user_mention(context, user_id):
    try:
        u = await context.bot.get_chat(user_id)
        if u.username:
            return f"@{u.username}"
        name = html.escape(u.first_name or str(user_id))
        return f'<a href="tg://user?id={user_id}">{name}</a>'
    except Exception:
        return f"<code>{user_id}</code>"

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

def get_force_join_keyboard(check_callback="check_join_main"):
    """کیبورد جوین اجباری با دکمه شیشه‌ای برای هر کانال"""
    channels = db.get_force_channels()
    kb = []
    for ch in channels:
        # دکمه شیشه‌ای برای هر کانال - لینک به کانال
        username = ch['channel_username'].replace('@', '')
        title = ch['channel_title'] or ch['channel_username']
        kb.append([InlineKeyboardButton(f"📢 {title}", url=f"https://t.me/{username}")])
    # دکمه بررسی عضویت
    kb.append([InlineKeyboardButton("✅ عضو شدم", callback_data=check_callback)])
    return InlineKeyboardMarkup(kb)

async def send_log(context, text, reply_markup=None):
    try:
        await context.bot.send_message(
            LOG_CHANNEL_ID, text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    except Exception as e:
        # اگه با آیدی عددی نشد با یوزرنیم امتحان کن
        try:
            await context.bot.send_message(
                LOG_CHANNEL_USERNAME, text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
        except Exception as e2:
            logger.error(f"Log channel error: {e} | {e2}")

def is_admin(user_id):
    return user_id in ADMIN_IDS

# ============ KEEP-ALIVE HTTP SERVER ============

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        html_page = f"""
        <html><head><title>Dark Point Bot</title></head>
        <body style="background:#000;color:#0f0;text-align:center;font-family:Arial;padding:50px;">
        <h1>🏴 Dark Point Bot 🏴</h1>
        <h2>✅ Alive & Running</h2>
        <p>Server Time: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
        </body></html>"""
        self.wfile.write(html_page.encode("utf-8"))
    def log_message(self, format, *args):
        return

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        logger.info(f"🌐 Health server on port {port}")
    except Exception as e:
        logger.error(f"Health server error: {e}")

async def self_ping(context: ContextTypes.DEFAULT_TYPE):
    url = os.environ.get("RENDER_EXTERNAL_URL")
    if not url:
        return
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'DarkBot'})
        with urllib.request.urlopen(req, timeout=10) as r:
            if r.status == 200:
                logger.info("🟢 Self-ping successful")
    except Exception:
        pass

# ============ START COMMAND ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    if db.is_banned(user.id):
        await update.message.reply_text("❌ حساب شما مسدود شده است.")
        return

    args = context.args
    existing = db.get_user(user.id)

    if not existing:
        ref_id = 0
        if args and len(args) > 0 and args[0].startswith("ref_"):
            try:
                ref_id = int(args[0].replace("ref_", ""))
                if ref_id == user.id:
                    ref_id = 0
            except Exception:
                ref_id = 0

        db.create_user(user.id, user.username or "", user.first_name or "", ref_id)

        if ref_id > 0:
            context.user_data['pending_ref'] = ref_id
            q_text, ans = generate_captcha()
            context.user_data['captcha_ans'] = ans

            await update.message.reply_text(
                f"🔐 <b>تایید هویت امنیتی</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"شما توسط لینک زیرمجموعه‌گیری وارد شده‌اید.\n"
                f"برای تایید، پاسخ سوال زیر را ارسال کنید:\n\n"
                f"❓ <code>{q_text}</code> = ?\n\n"
                f"💡 فقط عدد پاسخ را بفرستید.",
                parse_mode=ParseMode.HTML
            )
            return

    db.update_last_active(user.id)

    # چک هدیه
    if args and len(args) > 0 and args[0].startswith("check_"):
        code = args[0].replace("check_", "")
        amount = db.claim_check(code, user.id)
        if amount:
            db.add_dark_points(user.id, amount)
            await update.message.reply_text(
                f"🎁 <b>چک شخصی فعال شد!</b>\n\n"
                f"💰 مبلغ: <code>{format_number(amount)}</code> DP\n"
                f"✅ به کیف پول شما اضافه شد.",
                parse_mode=ParseMode.HTML
            )
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        admin_id,
                        f"📋 <b>چک فعال شد</b>\n👤 <code>{user.id}</code>\n💰 <code>{format_number(amount)}</code> DP",
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass
            return
        else:
            await update.message.reply_text("❌ چک نامعتبر یا استفاده شده است.")
            return

    # بررسی جوین اجباری با دکمه شیشه‌ای برای کانال‌ها
    joined = await check_force_join(user.id, context)
    if not joined:
        await update.message.reply_text(
            f"📢 <b>عضویت اجباری در کانال‌ها</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"برای استفاده از ربات، ابتدا در کانال‌های زیر عضو شوید و سپس دکمه «عضو شدم» را بزنید:\n\n"
            f"💡 <i>روی هر کانال کلیک کنید تا وارد شوید</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_force_join_keyboard("check_join_main")
        )
        return

    await show_main_menu(update, context)


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
    safe_name = html.escape(user.first_name or "کاربر")

    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await context.bot.get_me()
        BOT_USERNAME = me.username

    # منوی اصلی (بازی انفجار حذف شد - فقط در گروه)
    keyboard = [
        [InlineKeyboardButton("⭐️ 🌟 برداشت استارز 🌟 ⭐️", callback_data="stars_withdraw")],
        [
            InlineKeyboardButton("🏴 دارک پوینت", callback_data="dark_point_menu"),
            InlineKeyboardButton("🛒 خرید پنل", callback_data="buy_panel"),
        ],
        [
            InlineKeyboardButton("🎁 گیفت رایگان", callback_data="free_gift"),
            InlineKeyboardButton("💰 خرید دارک پوینت", callback_data="buy_dp"),
        ],
        [
            InlineKeyboardButton("❤️ چالش لایکی", callback_data="like_challenge"),
            InlineKeyboardButton("🏆 لیدربورد", callback_data="leaderboard"),
        ],
        [InlineKeyboardButton("👥 زیرمجموعه‌گیری", callback_data="referral_menu")],
        [InlineKeyboardButton("➕ افزودن به گروه", url=f"https://t.me/{BOT_USERNAME}?startgroup=true")],
    ]

    # دکمه پنل ادمین فقط برای ادمین
    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("🛡 پنل ادمین 🛡", callback_data="adm_back")])

    text = (
        f"🏴 <b>به دنیای دارک پوینت خوش آمدید!</b> 🏴\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 نام: <b>{safe_name}</b>\n"
        f"🆔 شناسه: <code>{user.id}</code>\n"
        f"💎 موجودی: <code>{format_number(balance)}</code> DP\n"
        f"📊 سطح: {level} | {title}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⭐ <i>هر ۱ میلیون DP = ۵۰ استارز رایگان!</i>\n"
        f"👥 <i>با زیرمجموعه‌گیری DP نامحدود کسب کنید!</i>\n\n"
        f"💥 <i>بازی انفجار و 🎲 تاس در گروه فعال است</i>"
    )

    if query:
        try:
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception:
            await query.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))


# ============ CHECK JOIN CALLBACKS ============

async def check_join_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()
    joined = await check_force_join(user.id, context)
    if not joined:
        await query.answer("❌ هنوز عضو همه کانال‌ها نشده‌اید!", show_alert=True)
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

    referrer_id = context.user_data.get('pending_ref', 0)
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

    context.user_data.pop('captcha_ans', None)
    context.user_data.pop('pending_ref', None)
    await show_main_menu(update, context, query=query)# ============ DARK POINT MENU ============

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
        [InlineKeyboardButton("🔗 لینک زیرمجموعه‌گیری", callback_data="referral_menu")],
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
        text += f"🏆 شما به بالاترین سطح رسیده‌اید!\n"

    text += (
        f"\n👥 زیرمجموعه‌ها: {user['referral_count'] if user else 0}\n"
        f"📊 کل دریافتی: <code>{format_number(user['total_earned'] if user else 0)}</code> DP\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💡 <i>برای اطلاعات کامل، توضیحات را بزنید</i>"
    )

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))


INFO_PAGES = {
    1: (
        "📖 <b>دارک پوینت - صفحه ۱/۹</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🏴 <b>دارک پوینت چیست؟</b>\n\n"
        "دارک پوینت واحد پولی اختصاصی این ربات است.\n\n"
        "با آن می‌توانید:\n\n"
        "⭐ استارز تلگرام برداشت کنید\n"
        "🛒 پنل VPN خریداری کنید\n"
        "🎁 گیفت تدی رایگان بگیرید\n"
        "🎮 بازی دو نفره کنید\n"
        "💥 بازی انفجار کنید\n"
        "🎲 بازی تاس کنید\n"
        "🏭 کارخونه بسازید\n"
        "🏦 در بانک سرمایه‌گذاری کنید\n\n"
        "⭐ <b>هر ۱,۰۰۰,۰۰۰ DP = ۵۰ استارز</b>"
    ),
    2: (
        "📖 <b>دارک پوینت - صفحه ۲/۹</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "💰 <b>نحوه کسب دارک پوینت:</b>\n\n"
        "1️⃣ <b>کلمه دارک در گروه:</b>\n"
        "در گروه: <code>دارک</code> یا <code>دارک کانفیگ</code>\n"
        "سطح ۱: ۱۰۰ تا ۲۵۰ DP\n"
        "هر سطح: +۴۰ DP اضافه\n\n"
        "2️⃣ <b>زیرمجموعه‌گیری:</b>\n"
        "هر زیرمجموعه = ۳۰,۰۰۰ DP\n\n"
        "3️⃣ <b>کارخونه دارکی:</b>\n"
        "خودکار DP ماین می‌کند\n\n"
        "4️⃣ <b>بانک دارکی:</b>\n"
        "سود ۱۰٪ در ۲۴ ساعت\n\n"
        "5️⃣ <b>بازی‌ها:</b>\n"
        "بازی، انفجار و تاس"
    ),
    3: (
        "📖 <b>دارک پوینت - صفحه ۳/۹</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "📊 <b>سیستم ۲۰ سطحی:</b>\n\n"
        "سطح ۱: 0 DP 🌑\n"
        "سطح ۲: 20K DP 🌒\n"
        "سطح ۳: 40K DP 🌓\n"
        "سطح ۴: 80K DP 🌔\n"
        "سطح ۵: 150K DP 🌕\n"
        "سطح ۶: 200K DP ⭐\n"
        "سطح ۷: 300K DP 🌟\n"
        "سطح ۸: 500K DP 💫\n"
        "سطح ۹: 800K DP ✨\n"
        "سطح ۱۰: 1M DP 🥈\n"
        "سطح ۱۱-۲۰: تا 20M DP 🏴\n\n"
        "🎁 هر سطح جایزه ارتقا دارد!"
    ),
    4: (
        "📖 <b>دارک پوینت - صفحه ۴/۹</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🏭 <b>کارخونه دارکی:</b>\n\n"
        "💵 افتتاح: ۱۰۰,۰۰۰ DP\n"
        "🔧 نگهداری: ساعتی ۸۰ DP\n\n"
        "📊 سطوح:\n"
        "سطح ۱: ۱۰ DP/دقیقه\n"
        "سطح ۲: ۲۵ DP/دقیقه (۵۰K)\n"
        "سطح ۳: ۴۰ DP/دقیقه (۸۰K)\n"
        "سطح ۴: ۵۰ DP/دقیقه (۱۰۰K)\n"
        "سطح ۵: ۱۰۰ DP/دقیقه (۲۵۰K)\n\n"
        "دستور: <code>کارخونه دارکی</code>"
    ),
    5: (
        "📖 <b>دارک پوینت - صفحه ۵/۹</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🏦 <b>بانک دارکی:</b>\n\n"
        "💵 افتتاح: ۲۰,۰۰۰ DP\n"
        "📈 سود ۲۴ ساعته: ۱۰٪\n"
        "کارت ۱۳ رقمی + سود بعد از ۲۴ ساعت\n\n"
        "🎮 <b>بازی دو نفره:</b>\n"
        "دستور: <code>بازی 1000</code>\n"
        "جایزه: ۲ برابر مبلغ\n"
        "برنده تصادفی"
    ),
    6: (
        "📖 <b>دارک پوینت - صفحه ۶/۹</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "💸 <b>انتقال دارک پوینت:</b>\n\n"
        "روش ۱: ریپلای + <code>انتقال 1000</code>\n"
        "روش ۲: <code>انتقال 1000 به 123456</code>\n"
        "⚠️ کارمزد: ۱۰٪\n\n"
        "❤️ <b>چالش لایکی ۷ روزه:</b>\n"
        "۳۰,۰۰۰ DP\n\n"
        "💰 <b>خرید DP:</b>\n"
        "۵۰۰ هزار DP = ۵۰ هزار تومان"
    ),
    7: (
        "📖 <b>دارک پوینت - صفحه ۷/۹</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "⭐ <b>برداشت استارز:</b>\n"
        "هر ۱M DP = ۵۰ استارز\n"
        "کاملاً رایگان با زیرمجموعه‌گیری!\n\n"
        "🎁 <b>گیفت رایگان:</b>\n"
        "گیفت تدی تلگرام\n\n"
        "📝 <b>دستورات گروه:</b>\n"
        "• <code>دارک</code>\n"
        "• <code>موجودی</code>\n"
        "• <code>پروفایل دارکی</code>\n"
        "• <code>بازی 1000</code>\n"
        "• <code>انفجار 1000</code>\n"
        "• <code>تاس 15000</code>\n"
        "• <code>انتقال 1000</code>\n"
        "• <code>بانک دارکی</code>\n"
        "• <code>کارخونه دارکی</code>\n"
        "• <code>لیدربورد</code>"
    ),
    8: (
        "📖 <b>دارک پوینت - صفحه ۸/۹</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "💥 <b>بازی انفجار:</b>\n\n"
        "🎯 <b>نحوه بازی:</b>\n"
        "در گروه: <code>انفجار 1000</code>\n\n"
        "۱. ضریب از ۱x شروع می‌شود\n"
        "۲. قبل از انفجار Cash Out کنید\n"
        "۳. برد = مبلغ × ضریب\n\n"
        "مثال: شرط ۱۰۰۰ در ۳x = ۳۰۰۰\n\n"
        "⚠️ حداقل: ۵۰۰ DP\n"
        "⚠️ حداکثر: ۵۰۰,۰۰۰ DP\n\n"
        "🎲 <i>ضریب کاملاً تصادفی</i>"
    ),
    9: (
        "📖 <b>دارک پوینت - صفحه ۹/۹</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🎲 <b>بازی تاس:</b>\n\n"
        "🎯 <b>نحوه بازی:</b>\n"
        "در گروه بنویسید: <code>تاس 15000</code>\n\n"
        "۱. مبلغ شرط را وارد کنید (حداقل ۱۵ هزار)\n"
        "۲. عدد یا اعداد شانستون رو انتخاب کنید\n"
        "۳. تاس پرتاب می‌شود\n\n"
        "🎯 <b>ضرایب برد:</b>\n"
        "• ۱ عدد انتخاب: <b>۶ برابر</b> 🥇\n"
        "• ۲ عدد انتخاب: <b>۳ برابر</b> 🥈\n"
        "• ۳ عدد انتخاب: <b>۱.۵ برابر</b> 🥉\n\n"
        "⚠️ حداکثر ۳ عدد انتخاب کنید\n"
        "⚠️ حداقل شرط: ۱۵,۰۰۰ DP\n\n"
        "🎲 <i>موفق باشید!</i>"
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
    if page < 9:
        buttons.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"dp_info_{page+1}"))

    keyboard = [buttons] if buttons else []
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="dark_point_menu")])

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))


# ============ STARS WITHDRAWAL ============

async def stars_withdraw_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if db.get_setting('stars_section_active', '1') != '1':
        await query.answer("❌ این بخش موقتاً خاموش است.", show_alert=True)
        return

    stars_price = int(db.get_setting('stars_price', '1000000'))
    balance = db.get_balance(user.id)
    can_withdraw = balance >= stars_price

    text = (
        f"⭐ <b>برداشت استارز تلگرام</b> ⭐\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💎 موجودی شما: <code>{format_number(balance)}</code> DP\n"
        f"⭐ نرخ: <code>{format_number(stars_price)}</code> DP = {STARS_AMOUNT} استارز\n\n"
    )

    if can_withdraw:
        text += f"✅ شما می‌توانید {STARS_AMOUNT} استارز برداشت کنید!\n\n"
        text += "🎉 <i>رایگان با زیرمجموعه‌گیری قابل کسب!</i>"
        kb = [
            [InlineKeyboardButton(f"⭐ برداشت {STARS_AMOUNT} استارز", callback_data="stars_do")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
        ]
    else:
        needed = stars_price - balance
        text += f"❌ موجودی ناکافی\n📈 <code>{format_number(needed)}</code> DP دیگر نیاز دارید"
        kb = [
            [InlineKeyboardButton("👥 زیرمجموعه‌گیری", callback_data="referral_menu")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
        ]

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def stars_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = [
        [InlineKeyboardButton("👤 همین اکانتم", callback_data="stars_self")],
        [InlineKeyboardButton("👥 اکانت دیگه", callback_data="stars_other")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="stars_withdraw")],
    ]
    await query.edit_message_text(
        f"⭐ <b>برداشت {STARS_AMOUNT} استارز</b>\n\n"
        f"استارز برای کدام اکانت واریز شود؟",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def stars_self_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    stars_price = int(db.get_setting('stars_price', '1000000'))
    if not db.remove_dark_points(user.id, stars_price):
        await query.answer("❌ موجودی ناکافی!", show_alert=True)
        return

    order_id = db.create_stars_order(user.id, str(user.id), 'self', STARS_AMOUNT, stars_price)

    await query.edit_message_text(
        f"✅ <b>سفارش استارز ثبت شد!</b>\n\n"
        f"⭐ تعداد: {STARS_AMOUNT} استارز\n"
        f"👤 مقصد: <code>{user.id}</code>\n"
        f"💵 هزینه: <code>{format_number(stars_price)}</code> DP\n\n"
        f"⏳ <i>بزودی واریز می‌شود</i>",
        parse_mode=ParseMode.HTML
    )

    user_display = f"@{user.username}" if user.username else f"<code>{user.id}</code>"
    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await context.bot.get_me()
        BOT_USERNAME = me.username

    log_kb = [[InlineKeyboardButton("🤖 ورود به ربات", url=f"https://t.me/{BOT_USERNAME}")]]
    await send_log(context,
        f"⭐ <b>سفارش برداشت استارز</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 کاربر: {user_display}\n"
        f"🆔 شناسه: <code>{user.id}</code>\n"
        f"⭐ تعداد: {STARS_AMOUNT} استارز\n"
        f"📍 مقصد: <code>{user.id}</code> (همین اکانت)\n"
        f"💵 هزینه: <code>{format_number(stars_price)}</code> DP\n"
        f"🆔 سفارش: <code>{order_id}</code>",
        reply_markup=InlineKeyboardMarkup(log_kb)
    )

    # پیام مستقیم برای ادمین با دکمه پاسخ
    for admin_id in ADMIN_IDS:
        try:
            admin_kb = [
                [InlineKeyboardButton("💬 پاسخ به کاربر", callback_data=f"admin_reply_{user.id}")],
                [InlineKeyboardButton("✅ تیک تایید سفارش", callback_data=f"admin_confirm_stars_{order_id}")]
            ]
            await context.bot.send_message(
                admin_id,
                f"⭐ <b>سفارش استارز جدید</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"👤 کاربر: {user_display}\n"
                f"🆔 <code>{user.id}</code>\n"
                f"⭐ تعداد: {STARS_AMOUNT}\n"
                f"📍 مقصد: <code>{user.id}</code>\n"
                f"💵 <code>{format_number(stars_price)}</code> DP",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(admin_kb)
            )
        except Exception:
            pass


async def stars_other_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_stars_target'] = True
    await query.edit_message_text(
        "👥 <b>اکانت دیگر</b>\n\n"
        "آیدی اکانتی که می‌خواهید استارز براش واریز بشه رو بفرستید:\n\n"
        "مثال: <code>@username</code> یا <code>123456789</code>",
        parse_mode=ParseMode.HTML
    )


# ============ FREE GIFT ============

async def free_gift_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if db.get_setting('gift_section_active', '1') != '1':
        await query.answer("❌ این بخش موقتاً خاموش است.", show_alert=True)
        return

    gift_price = int(db.get_setting('gift_teddy_price', '750000'))
    balance = db.get_balance(user.id)
    can_buy = balance >= gift_price

    conn = db.get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM settings WHERE key LIKE 'gift_plan_%_name'")
    plans = c.fetchall()
    conn.close()

    text = (
        f"🎁 <b>گیفت رایگان تدی تلگرام</b> 🎁\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🧸 <b>گیفت تدی تلگرام</b>\n"
        f"💰 قیمت: <code>{format_number(gift_price)}</code> DP\n"
        f"💎 موجودی: <code>{format_number(balance)}</code> DP\n\n"
        f"🆓 <i>رایگان با زیرمجموعه‌گیری قابل کسب!</i>\n"
        f"👥 هر زیرمجموعه = {format_number(REFERRAL_REWARD)} DP"
    )

    buttons = []
    if can_buy:
        buttons.append([InlineKeyboardButton("🧸 سفارش گیفت تدی", callback_data="order_gift_teddy")])
    else:
        needed = gift_price - balance
        text += f"\n\n📈 <code>{format_number(needed)}</code> DP دیگر نیاز دارید"

    for plan in plans:
        plan_num = plan['key'].split('_')[2]
        name = plan['value']
        price = int(db.get_setting(f'gift_plan_{plan_num}_price', '0'))
        if price > 0:
            buttons.append([InlineKeyboardButton(f"🎁 {name} ({format_number(price)} DP)", callback_data=f"order_gift_custom_{plan_num}")])

    buttons.append([InlineKeyboardButton("👥 زیرمجموعه‌گیری", callback_data="referral_menu")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))


async def order_gift_teddy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    gift_price = int(db.get_setting('gift_teddy_price', '750000'))
    if not db.remove_dark_points(user.id, gift_price):
        await query.answer("❌ موجودی ناکافی!", show_alert=True)
        return

    order_id = db.create_gift_order(user.id, 'teddy', gift_price)

    await query.edit_message_text(
        f"✅ <b>سفارش گیفت تدی ثبت شد!</b>\n\n"
        f"🧸 گیفت تدی تلگرام\n"
        f"💵 هزینه: <code>{format_number(gift_price)}</code> DP\n"
        f"🆔 شماره سفارش: <code>{order_id}</code>\n\n"
        f"⏳ <i>بزودی ارسال می‌شود</i>",
        parse_mode=ParseMode.HTML
    )

    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await context.bot.get_me()
        BOT_USERNAME = me.username

    user_display = f"@{user.username}" if user.username else f"<code>{user.id}</code>"
    log_kb = [[InlineKeyboardButton("🤖 ورود به ربات", url=f"https://t.me/{BOT_USERNAME}")]]
    await send_log(context,
        f"🧸 <b>سفارش جدید گیفت تدی تلگرام</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 کاربر: {user_display}\n"
        f"🆔 <code>{user.id}</code>\n"
        f"💵 <code>{format_number(gift_price)}</code> DP\n"
        f"🆔 سفارش: <code>{order_id}</code>",
        reply_markup=InlineKeyboardMarkup(log_kb)
    )

    for admin_id in ADMIN_IDS:
        try:
            admin_kb = [
                [InlineKeyboardButton("💬 پاسخ به کاربر", callback_data=f"admin_reply_{user.id}")],
                [InlineKeyboardButton("✅ تایید سفارش", callback_data=f"admin_confirm_gift_{order_id}")]
            ]
            await context.bot.send_message(
                admin_id,
                f"🧸 <b>سفارش گیفت تدی</b>\n\n"
                f"👤 {user_display}\n"
                f"🆔 <code>{user.id}</code>\n"
                f"💵 <code>{format_number(gift_price)}</code> DP",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(admin_kb)
            )
        except Exception:
            pass


async def order_gift_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    plan_num = query.data.split("_")[-1]

    name = db.get_setting(f'gift_plan_{plan_num}_name', 'نامشخص')
    price = int(db.get_setting(f'gift_plan_{plan_num}_price', '0'))

    if not db.remove_dark_points(user.id, price):
        await query.answer("❌ موجودی ناکافی!", show_alert=True)
        return

    order_id = db.create_gift_order(user.id, name, price)
    await query.answer()

    await query.edit_message_text(
        f"✅ <b>سفارش ثبت شد!</b>\n\n"
        f"🎁 {name}\n"
        f"💵 هزینه: <code>{format_number(price)}</code> DP\n"
        f"🆔 <code>{order_id}</code>",
        parse_mode=ParseMode.HTML
    )

    user_display = f"@{user.username}" if user.username else f"<code>{user.id}</code>"
    for admin_id in ADMIN_IDS:
        try:
            admin_kb = [[InlineKeyboardButton("💬 پاسخ به کاربر", callback_data=f"admin_reply_{user.id}")]]
            await context.bot.send_message(
                admin_id,
                f"🎁 سفارش: {name}\n👤 {user_display}\n🆔 <code>{user.id}</code>\n💵 <code>{format_number(price)}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(admin_kb)
            )
        except Exception:
            pass


# ============ BUY DARK POINTS ============

async def buy_dp_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if db.get_setting('buy_dp_active', '1') != '1':
        await query.answer("❌ این بخش موقتاً خاموش است.", show_alert=True)
        return

    dp_amount = int(db.get_setting('buy_dp_amount', '500000'))
    price_toman = int(db.get_setting('buy_dp_price_toman', '50000'))

    text = (
        f"💰 <b>خرید مستقیم دارک پوینت</b> 💰\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💎 هر <code>{format_number(dp_amount)}</code> DP\n"
        f"💵 قیمت: <code>{format_number(price_toman)}</code> تومان\n\n"
        f"⚠️ هر نفر فقط یکبار می‌تواند خرید کند\n"
        f"👥 <i>بقیه رو با زیرمجموعه‌گیری بگیر!</i>\n\n"
        f"📩 برای خرید به پشتیبانی پیام دهید:"
    )

    kb = [
        [InlineKeyboardButton("📩 پشتیبانی", url=f"https://t.me/{SUPPORT_USERNAME.replace('@', '')}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
    ]
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


# ============ LEADERBOARD ============

async def leaderboard_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    rows = db.get_leaderboard(100)
    text = "🏆 <b>لیدربورد دارک پوینت</b> 🏆\n"
    text += "━━━━━━━━━━━━━━━━━━\n\n"

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, row in enumerate(rows[:25], 1):
        medal = medals.get(i, f"{i}.")
        name = html.escape(row['first_name'] or row['username'] or str(row['user_id']))
        text += f"{medal} <b>{name}</b> - <code>{format_number(row['dark_points'])}</code> DP\n"

    if len(rows) > 25:
        text += f"\n<i>... و {len(rows) - 25} نفر دیگر</i>\n"

    text += "\n━━━━━━━━━━━━━━━━━━\n🏆 <i>۱۰۰ نفر برتر نمایش داده می‌شوند</i>"

    kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


# ============ REFERRAL ============

async def referral_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await context.bot.get_me()
        BOT_USERNAME = me.username

    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user.id}"
    ref_count = db.get_referral_count(user.id)

    text = (
        f"👥 <b>زیرمجموعه‌گیری</b> 👥\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🔗 لینک اختصاصی شما:\n<code>{ref_link}</code>\n\n"
        f"👥 تعداد زیرمجموعه‌ها: <b>{ref_count}</b>\n"
        f"💰 پاداش هر زیرمجموعه: <b>{format_number(REFERRAL_REWARD)}</b> DP\n"
        f"💎 کل درآمد: <code>{format_number(ref_count * REFERRAL_REWARD)}</code> DP\n\n"
        f"📋 <b>شرایط:</b>\n"
        f"• حل کپچای ریاضی ✅\n"
        f"• عضویت در همه کانال‌ها ✅\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💡 <i>لینک را به اشتراک بگذارید و DP بگیرید!</i>"
    )

    kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


# ============ LIKE CHALLENGE ============

async def like_challenge_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    u = db.get_user(user.id)

    if u['like_challenge_active'] and u['like_challenge_until'] > time.time():
        remaining = u['like_challenge_until'] - time.time()
        days = int(remaining // 86400)
        hours = int((remaining % 86400) // 3600)
        text = (
            f"❤️ <b>چالش لایکی فعال است</b> ❤️\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"⏰ زمان باقیمانده: {days} روز و {hours} ساعت"
        )
        kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
    else:
        text = (
            f"❤️ <b>چالش لایکی</b> ❤️\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"💵 هزینه ۷ روزه: <code>{format_number(LIKE_CHALLENGE_COST)}</code> DP\n"
            f"💎 موجودی: <code>{format_number(db.get_balance(user.id))}</code> DP"
        )
        kb = [
            [InlineKeyboardButton(f"✅ فعال‌سازی ({format_number(LIKE_CHALLENGE_COST)} DP)", callback_data="like_activate")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
        ]

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def like_activate_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if not db.remove_dark_points(user.id, LIKE_CHALLENGE_COST):
        await query.answer("❌ موجودی ناکافی!", show_alert=True)
        return

    until = time.time() + (7 * 86400)
    db.update_user(user.id, like_challenge_active=1, like_challenge_until=until)

    await query.edit_message_text(
        f"✅ <b>چالش لایکی فعال شد!</b>\n\n"
        f"💵 هزینه: <code>{format_number(LIKE_CHALLENGE_COST)}</code> DP\n"
        f"⏰ مدت: ۷ روز",
        parse_mode=ParseMode.HTML
    )


# ============ BUY PANEL (SANAI) - با لاگ کامل ============

async def buy_panel_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # قیمت‌ها از دیتابیس خوانده می‌شوند (قابل تغییر توسط ادمین)
    price_500 = int(db.get_setting('panel_snai_500gb', str(DEFAULT_PANEL_PRICES['snai_500gb'])))
    price_800 = int(db.get_setting('panel_snai_800gb', str(DEFAULT_PANEL_PRICES['snai_800gb'])))
    price_1tb = int(db.get_setting('panel_snai_1tb', str(DEFAULT_PANEL_PRICES['snai_1tb'])))

    buttons = [
        [InlineKeyboardButton(f"🛒 سنایی 500GB ({format_number(price_500)} DP)", callback_data="panel_buy_snai_500gb")],
        [InlineKeyboardButton(f"🛒 سنایی 800GB ({format_number(price_800)} DP)", callback_data="panel_buy_snai_800gb")],
        [InlineKeyboardButton(f"🛒 سنایی 1TB ({format_number(price_1tb)} DP)", callback_data="panel_buy_snai_1tb")],
    ]

    for panel in db.get_custom_panels():
        buttons.append([InlineKeyboardButton(
            f"🛒 {panel['name']} ({format_number(panel['price'])} DP)",
            callback_data=f"panel_buy_custom_{panel['panel_id']}"
        )])

    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])
    balance = db.get_balance(query.from_user.id)

    text = (
        f"🛒 <b>خرید پنل VPN سنایی</b> 🛒\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💎 موجودی: <code>{format_number(balance)}</code> DP\n\n"
        f"<i>یک پلن انتخاب کنید:</i>"
    )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))


async def panel_buy_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            await query.answer("❌ پلن یافت نشد!", show_alert=True)
            return
        name = panel['name']
        price = panel['price']
        data_limit = panel['data_limit']
    else:
        plan_key = data.replace("panel_buy_", "")
        if plan_key == "snai_500gb":
            name = "سنایی 500GB"
            price = int(db.get_setting('panel_snai_500gb', str(DEFAULT_PANEL_PRICES['snai_500gb'])))
            data_limit = "500GB"
        elif plan_key == "snai_800gb":
            name = "سنایی 800GB"
            price = int(db.get_setting('panel_snai_800gb', str(DEFAULT_PANEL_PRICES['snai_800gb'])))
            data_limit = "800GB"
        elif plan_key == "snai_1tb":
            name = "سنایی 1TB"
            price = int(db.get_setting('panel_snai_1tb', str(DEFAULT_PANEL_PRICES['snai_1tb'])))
            data_limit = "1TB"
        else:
            return

    await query.answer()
    if not db.remove_dark_points(user.id, price):
        await query.answer("❌ موجودی ناکافی!", show_alert=True)
        return

    order_id = db.create_panel_order(user.id, name, price, "")

    await query.edit_message_text(
        f"✅ <b>سفارش پنل ثبت شد!</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🛒 پلن: <b>{name}</b>\n"
        f"📊 حجم: <b>{data_limit}</b>\n"
        f"💵 هزینه: <code>{format_number(price)}</code> DP\n"
        f"🆔 شماره سفارش: <code>{order_id}</code>\n\n"
        f"⏳ <i>ادمین کانفیگ رو بزودی برات میفرسته</i>\n"
        f"💎 موجودی جدید: <code>{format_number(db.get_balance(user.id))}</code> DP",
        parse_mode=ParseMode.HTML
    )

    # لاگ در کانال با دکمه شیشه‌ای
    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await context.bot.get_me()
        BOT_USERNAME = me.username

    user_display = f"@{user.username}" if user.username else f"<code>{user.id}</code>"
    log_kb = [[InlineKeyboardButton("🤖 ورود به ربات", url=f"https://t.me/{BOT_USERNAME}")]]
    await send_log(context,
        f"🛒 <b>سفارش جدید پنل سنایی</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 کاربر: {user_display}\n"
        f"🆔 شناسه: <code>{user.id}</code>\n"
        f"📦 پلن: <b>{name}</b>\n"
        f"📊 حجم: <b>{data_limit}</b>\n"
        f"💵 هزینه: <code>{format_number(price)}</code> DP\n"
        f"🆔 سفارش: <code>{order_id}</code>",
        reply_markup=InlineKeyboardMarkup(log_kb)
    )

    # پیام مستقیم برای ادمین با دکمه پاسخ (ارسال کانفیگ)
    for admin_id in ADMIN_IDS:
        try:
            admin_kb = [
                [InlineKeyboardButton("📤 ارسال کانفیگ به کاربر", callback_data=f"admin_send_config_{order_id}_{user.id}")],
                [InlineKeyboardButton("💬 پاسخ به کاربر", callback_data=f"admin_reply_{user.id}")]
            ]
            await context.bot.send_message(
                admin_id,
                f"🛒 <b>سفارش جدید پنل سنایی</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"👤 کاربر: {user_display}\n"
                f"🆔 شناسه: <code>{user.id}</code>\n"
                f"📦 پلن: <b>{name}</b>\n"
                f"📊 حجم: <b>{data_limit}</b>\n"
                f"💵 مبلغ پرداختی: <code>{format_number(price)}</code> DP\n"
                f"🆔 شماره سفارش: <code>{order_id}</code>\n\n"
                f"⚡️ <i>کانفیگ رو از پنل سنایی بسازید و برای کاربر ارسال کنید</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(admin_kb)
            )
        except Exception as e:
            logger.error(f"Admin notify error: {e}")# ============ GROUP HANDLERS ============

async def on_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            try:
                count = await context.bot.get_chat_member_count(chat.id)
                if count < MIN_GROUP_MEMBERS:
                    await update.message.reply_text(
                        f"❌ <b>گروه باید حداقل {MIN_GROUP_MEMBERS} عضو داشته باشد!</b>\n"
                        f"👥 تعداد فعلی: {count}",
                        parse_mode=ParseMode.HTML
                    )
                    await context.bot.leave_chat(chat.id)
                    return
                db.add_group(chat.id, chat.title, count)
                await update.message.reply_text(
                    "🏴 <b>ربات دارک پوینت با موفقیت فعال شد!</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n\n"
                    "📝 <b>دستورات موجود:</b>\n"
                    "• <code>دارک</code> - دریافت DP\n"
                    "• <code>دارک کانفیگ</code> - دریافت DP\n"
                    "• <code>موجودی</code> - مشاهده موجودی\n"
                    "• <code>پروفایل دارکی</code> - پروفایل کامل\n"
                    "• <code>بازی 1000</code> - بازی دو نفره\n"
                    "• <code>انفجار 1000</code> - بازی انفجار\n"
                    "• <code>تاس 15000</code> - بازی تاس\n"
                    "• <code>انتقال 1000</code> - انتقال DP\n"
                    "• <code>بانک دارکی</code> - بانک\n"
                    "• <code>کارخونه دارکی</code> - کارخونه\n"
                    "• <code>لیدربورد</code>",
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
    elif text.startswith('تاس'):
        parts = text.split()
        if len(parts) >= 2:
            try:
                amount = int(parts[1])
                await handle_dice_game_group(update, context, amount)
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
            f"⏳ <b>لطفاً صبر کنید!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"⏰ <b>{mins}</b> دقیقه و <b>{secs}</b> ثانیه تا دریافت بعدی\n\n"
            f"💡 <i>صبر کلید موفقیت است!</i>",
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
    safe_name = html.escape(user.first_name or "کاربر")

    cd_mins = cooldown // 60
    cd_secs = cooldown % 60

    text = (
        f"✨ 🏴 <b>دارک پوینت دریافت شد!</b> 🏴 ✨\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 کاربر: <b>{safe_name}</b>\n"
        f"💎 دریافتی: +<code>{format_number(earned)}</code> DP 🎉\n"
        f"📊 سطح: {level} | {get_level_title(level)}\n"
        f"💰 موجودی: <code>{format_number(db.get_balance(user.id))}</code> DP\n\n"
        f"⏰ دریافت بعدی: {cd_mins} دقیقه و {cd_secs} ثانیه"
    )

    if new_level:
        text += (
            f"\n\n🎊 <b>تبریک! ارتقا به سطح {new_level}!</b> 🎊\n"
            f"🏅 لقب جدید: {get_level_title(new_level)}\n"
            f"🎁 جایزه: +<code>{format_number(reward)}</code> DP"
        )

    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await context.bot.get_me()
        BOT_USERNAME = me.username

    kb = [[InlineKeyboardButton("🏴 ورود به ربات دارک پوینت", url=f"https://t.me/{BOT_USERNAME}")]]
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def handle_balance_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    balance = db.get_balance(user.id)
    level = db.get_level(user.id)
    safe_name = html.escape(user.first_name or "کاربر")

    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await context.bot.get_me()
        BOT_USERNAME = me.username

    kb = [[InlineKeyboardButton("🏴 ورود به ربات", url=f"https://t.me/{BOT_USERNAME}")]]
    await update.message.reply_text(
        f"💎 <b>موجودی دارک پوینت</b> 💎\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 کاربر: <b>{safe_name}</b>\n"
        f"🆔 شناسه: <code>{user.id}</code>\n\n"
        f"💰 موجودی: <code>{format_number(balance)}</code> DP\n"
        f"📊 سطح: {level} | {get_level_title(level)}\n"
        f"━━━━━━━━━━━━━━━━━━",
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
    safe_name = html.escape(user.first_name or "کاربر")

    factory_info = ""
    if u['factory_active']:
        f_level = u['factory_level']
        mine_rate = FACTORY_LEVELS[f_level]['mine_per_min']
        factory_info = f"🏭 کارخونه: سطح {f_level} ({mine_rate} DP/دقیقه)\n"

    bank_info = ""
    if u['bank_account']:
        bank_info = f"🏦 کارت بانک: <code>{u['bank_card']}</code>\n💰 موجودی بانک: <code>{format_number(u['bank_balance'])}</code> DP\n"

    stars_price = int(db.get_setting('stars_price', '1000000'))
    stars_can = balance // stars_price
    if stars_can > 0:
        stars_text = f"⭐ قابل برداشت: {stars_can * 50} استارز\n"
    else:
        stars_text = f"⭐ تا استارز بعدی: <code>{format_number(stars_price - balance)}</code> DP\n"

    crash_played = u['crash_games_played']
    crash_won = u['crash_games_won']
    win_rate = int((crash_won / crash_played * 100) if crash_played > 0 else 0)

    text = (
        f"🏴 <b>پروفایل دارکی</b> 🏴\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 نام: <b>{safe_name}</b>\n"
        f"🆔 شناسه: <code>{user.id}</code>\n"
        f"📛 یوزرنیم: @{user.username or 'ندارد'}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
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

    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await context.bot.get_me()
        BOT_USERNAME = me.username

    kb = [[InlineKeyboardButton("🏴 ورود به ربات", url=f"https://t.me/{BOT_USERNAME}")]]
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def handle_leaderboard_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.get_leaderboard(10)
    text = "🏆 <b>لیدربورد دارک پوینت</b>\n━━━━━━━━━━━━━━━━━━\n\n"
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, row in enumerate(rows, 1):
        medal = medals.get(i, f"{i}.")
        name = html.escape(row['first_name'] or str(row['user_id']))
        text += f"{medal} <b>{name}</b> - <code>{format_number(row['dark_points'])}</code> DP\n"

    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await context.bot.get_me()
        BOT_USERNAME = me.username

    kb = [[InlineKeyboardButton("🏴 ورود به ربات", url=f"https://t.me/{BOT_USERNAME}")]]
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


# ============ 2-PLAYER GAME ============

async def handle_create_game(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: int):
    user = update.effective_user
    chat = update.effective_chat

    if amount < MIN_GAME_AMOUNT:
        await update.message.reply_text(
            f"❌ حداقل مبلغ بازی: <code>{format_number(MIN_GAME_AMOUNT)}</code> DP",
            parse_mode=ParseMode.HTML
        )
        return

    balance = db.get_balance(user.id)
    if balance < amount:
        await update.message.reply_text(
            f"❌ <b>موجودی ناکافی!</b>\n💰 موجودی: <code>{format_number(balance)}</code> DP",
            parse_mode=ParseMode.HTML
        )
        return

    db.remove_dark_points(user.id, amount)

    msg = await update.message.reply_text(
        f"🎮 <b>بازی جدید ایجاد شد!</b> 🎮\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 سازنده: {get_user_display(user)}\n"
        f"💰 مبلغ ورود: <code>{format_number(amount)}</code> DP\n"
        f"🏆 جایزه برنده: <code>{format_number(amount * 2)}</code> DP\n\n"
        f"⏳ منتظر حریف...",
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
        await query.answer("❌ بازی تمام شده!", show_alert=True)
        return
    if user.id == game['creator_id']:
        await query.answer("❌ به بازی خودتان نمی‌توانید بپیوندید!", show_alert=True)
        return

    amount = game['amount']
    balance = db.get_balance(user.id)
    if balance < amount:
        await query.answer(f"❌ نیاز: {format_number(amount)} DP", show_alert=True)
        return

    db.remove_dark_points(user.id, amount)
    db.join_game(game_id, user.id)

    await query.answer("🎮 در حال مشخص کردن برنده...")
    await asyncio.sleep(2)

    players = [game['creator_id'], user.id]
    winner_id = random.choice(players)
    loser_id = players[0] if winner_id == players[1] else players[1]

    prize = amount * 2
    db.add_dark_points(winner_id, prize)
    db.finish_game(game_id, winner_id, loser_id)

    winner_display = await get_user_mention(context, winner_id)
    loser_display = await get_user_mention(context, loser_id)

    await query.edit_message_text(
        f"🎮 <b>نتیجه بازی!</b> 🎮\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🏆 <b>برنده:</b> {winner_display}\n"
        f"💰 جایزه: +<code>{format_number(prize)}</code> DP\n"
        f"💎 موجودی جدید: <code>{format_number(db.get_balance(winner_id))}</code> DP\n\n"
        f"💔 <b>بازنده:</b> {loser_display}\n"
        f"💎 موجودی جدید: <code>{format_number(db.get_balance(loser_id))}</code> DP\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎲 <i>برنده کاملاً تصادفی</i>",
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
        await query.answer("❌ فقط سازنده!", show_alert=True)
        return
    if game['status'] != 'waiting':
        await query.answer("❌ شروع شده!", show_alert=True)
        return

    db.add_dark_points(game['creator_id'], game['amount'])
    db.cancel_game(game_id)

    await query.edit_message_text(
        f"❌ <b>بازی لغو شد</b>\n\n💰 <code>{format_number(game['amount'])}</code> DP بازگردانده شد.",
        parse_mode=ParseMode.HTML
    )


# ============ CRASH GAME (Only in Group) ============

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


async def handle_crash_game_group(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: int):
    user = update.effective_user

    if db.get_setting('crash_active', '1') != '1':
        await update.message.reply_text("❌ بازی انفجار غیرفعال است.")
        return

    if amount < CRASH_MIN_BET:
        await update.message.reply_text(
            f"❌ حداقل مبلغ: <code>{format_number(CRASH_MIN_BET)}</code> DP",
            parse_mode=ParseMode.HTML
        )
        return
    if amount > CRASH_MAX_BET:
        await update.message.reply_text(
            f"❌ حداکثر مبلغ: <code>{format_number(CRASH_MAX_BET)}</code> DP",
            parse_mode=ParseMode.HTML
        )
        return

    balance = db.get_balance(user.id)
    if balance < amount:
        await update.message.reply_text(
            f"❌ <b>موجودی ناکافی!</b>\n💰 موجودی: <code>{format_number(balance)}</code> DP",
            parse_mode=ParseMode.HTML
        )
        return

    db.remove_dark_points(user.id, amount)
    crash_point = generate_crash_point()

    msg = await update.message.reply_text(
        f"💥 <b>بازی انفجار شروع شد!</b> 💥\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 بازیکن: {get_user_display(user)}\n"
        f"💰 شرط: <code>{format_number(amount)}</code> DP\n\n"
        f"🚀 ضریب: <code>1.00x</code>\n\n"
        f"⚡️ آماده شوید...",
        parse_mode=ParseMode.HTML
    )

    game_id = db.create_crash_game(user.id, amount, crash_point, update.effective_chat.id, msg.message_id)

    await msg.edit_text(
        f"💥 <b>بازی انفجار زنده</b> 💥\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 بازیکن: {get_user_display(user)}\n"
        f"💰 شرط: <code>{format_number(amount)}</code> DP\n\n"
        f"🚀 ضریب: <code>1.00x</code>\n"
        f"💎 برد فعلی: <code>{format_number(amount)}</code> DP",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 برداشت (Cash Out)", callback_data=f"crash_out_{game_id}")]
        ])
    )

    asyncio.create_task(run_crash_animation(context, game_id, user.id, amount, crash_point, msg.chat_id, msg.message_id, user))


async def run_crash_animation(context, game_id, user_id, bet, crash_point, chat_id, message_id, user_obj):
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
            step = 0.15
            delay = 1.2
        if current > 4:
            step = 0.25
            delay = 1.0
        if current > 7:
            step = 0.4
            delay = 0.8

        potential_win = int(bet * current)

        try:
            await context.bot.edit_message_text(
                f"💥 <b>بازی انفجار زنده</b> 💥\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"👤 بازیکن: {get_user_display(user_obj)}\n"
                f"💰 شرط: <code>{format_number(bet)}</code> DP\n\n"
                f"🚀 ضریب: <code>{current}x</code> 📈\n"
                f"💎 برد فعلی: <code>{format_number(potential_win)}</code> DP",
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
            await context.bot.edit_message_text(
                f"💥💥💥 <b>منفجر شد!</b> 💥💥💥\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"👤 بازیکن: {get_user_display(user_obj)}\n"
                f"💰 شرط: <code>{format_number(bet)}</code> DP\n\n"
                f"💥 ضریب انفجار: <code>{crash_point}x</code>\n"
                f"😔 نتیجه: باختی!\n\n"
                f"💎 موجودی: <code>{format_number(db.get_balance(user_id))}</code> DP\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🎲 <i>دفعه بعد شانس بیشتر!</i>",
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
        await query.answer("❌ بازی تمام شده!", show_alert=True)
        return

    msg_text = query.message.text
    match = re.search(r'(\d+\.\d+)x', msg_text)
    if not match:
        await query.answer("❌ خطا!", show_alert=True)
        return

    current_mult = float(match.group(1))
    win_amount = int(g['bet_amount'] * current_mult)
    profit = win_amount - g['bet_amount']

    if db.cashout_crash_game(game_id, current_mult, profit):
        db.add_dark_points(user.id, win_amount)
        db.increment_crash_stats(user.id, won=True)

        await query.answer(f"✅ برداشت موفق! +{format_number(win_amount)} DP", show_alert=True)

        await query.edit_message_text(
            f"🎉 🏆 <b>برنده شدی!</b> 🏆 🎉\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 بازیکن: {get_user_display(user)}\n"
            f"💰 شرط: <code>{format_number(g['bet_amount'])}</code> DP\n\n"
            f"💎 ضریب برداشت: <code>{current_mult}x</code>\n"
            f"🏆 کل برد: <code>{format_number(win_amount)}</code> DP\n"
            f"📈 سود خالص: +<code>{format_number(profit)}</code> DP\n\n"
            f"💎 موجودی: <code>{format_number(db.get_balance(user.id))}</code> DP\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎯 <i>در زمان درست خارج شدی!</i>",
            parse_mode=ParseMode.HTML
        )


# ============ DICE GAME (Only in Group) ============

# ذخیره موقت بازی‌های تاس در حافظه
dice_games = {}

async def handle_dice_game_group(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: int):
    """شروع بازی تاس در گروه"""
    user = update.effective_user

    if amount < DICE_MIN_BET:
        await update.message.reply_text(
            f"❌ <b>حداقل مبلغ شرط تاس: <code>{format_number(DICE_MIN_BET)}</code> DP</b>",
            parse_mode=ParseMode.HTML
        )
        return

    balance = db.get_balance(user.id)
    if balance < amount:
        await update.message.reply_text(
            f"❌ <b>موجودی ناکافی!</b>\n💰 موجودی: <code>{format_number(balance)}</code> DP",
            parse_mode=ParseMode.HTML
        )
        return

    # کسر مبلغ شرط
    db.remove_dark_points(user.id, amount)

    # ساخت کیبورد انتخاب عدد
    kb = [
        [
            InlineKeyboardButton("1️⃣", callback_data=f"dice_pick_1"),
            InlineKeyboardButton("2️⃣", callback_data=f"dice_pick_2"),
            InlineKeyboardButton("3️⃣", callback_data=f"dice_pick_3"),
        ],
        [
            InlineKeyboardButton("4️⃣", callback_data=f"dice_pick_4"),
            InlineKeyboardButton("5️⃣", callback_data=f"dice_pick_5"),
            InlineKeyboardButton("6️⃣", callback_data=f"dice_pick_6"),
        ],
        [InlineKeyboardButton("🎲 پرتاب تاس (Roll)", callback_data=f"dice_roll")],
        [InlineKeyboardButton("❌ لغو بازی", callback_data=f"dice_cancel")],
    ]

    msg = await update.message.reply_text(
        f"🎲 <b>بازی تاس دارکی</b> 🎲\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 بازیکن: {get_user_display(user)}\n"
        f"💰 مبلغ شرط: <code>{format_number(amount)}</code> DP\n\n"
        f"🎯 <b>ضرایب برد:</b>\n"
        f"• ۱ عدد: <b>۶ برابر</b>\n"
        f"• ۲ عدد: <b>۳ برابر</b>\n"
        f"• ۳ عدد: <b>۱.۵ برابر</b>\n\n"
        f"📌 <b>اعداد انتخابی:</b> <code>هیچ</code>\n\n"
        f"⚡️ <i>حداکثر ۳ عدد انتخاب کنید و دکمه پرتاب را بزنید</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(kb)
    )

    # ذخیره در حافظه با کلید (chat_id, message_id)
    game_key = f"{msg.chat_id}_{msg.message_id}"
    dice_games[game_key] = {
        'user_id': user.id,
        'user_obj': user,
        'amount': amount,
        'picks': [],
        'chat_id': msg.chat_id,
        'message_id': msg.message_id,
        'status': 'picking',
        'created_at': time.time(),
    }


async def dice_pick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """انتخاب عدد در بازی تاس"""
    query = update.callback_query
    user = query.from_user
    picked = int(query.data.split("_")[-1])

    game_key = f"{query.message.chat_id}_{query.message.message_id}"
    game = dice_games.get(game_key)

    if not game:
        await query.answer("❌ بازی یافت نشد!", show_alert=True)
        return
    if game['user_id'] != user.id:
        await query.answer("❌ این بازی شما نیست!", show_alert=True)
        return
    if game['status'] != 'picking':
        await query.answer("❌ بازی تمام شده!", show_alert=True)
        return

    picks = game['picks']

    # اگر قبلاً انتخاب شده، حذف کن
    if picked in picks:
        picks.remove(picked)
        await query.answer(f"❌ عدد {picked} حذف شد.")
    else:
        if len(picks) >= 3:
            await query.answer("⚠️ حداکثر ۳ عدد می‌توانید انتخاب کنید!", show_alert=True)
            return
        picks.append(picked)
        await query.answer(f"✅ عدد {picked} انتخاب شد.")

    game['picks'] = picks

    # نمایش اعداد انتخابی
    picks_display = " - ".join([str(p) for p in sorted(picks)]) if picks else "هیچ"
    
    # نشون دادن ضریب فعلی
    if len(picks) == 1:
        mult_text = "۶ برابر 🥇"
    elif len(picks) == 2:
        mult_text = "۳ برابر 🥈"
    elif len(picks) == 3:
        mult_text = "۱.۵ برابر 🥉"
    else:
        mult_text = "بدون انتخاب"

    # کیبورد جدید با نمایش تیک روی اعداد انتخابی
    def get_btn(num):
        emoji_map = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣", 6: "6️⃣"}
        label = emoji_map[num]
        if num in picks:
            label = f"✅ {label}"
        return InlineKeyboardButton(label, callback_data=f"dice_pick_{num}")

    kb = [
        [get_btn(1), get_btn(2), get_btn(3)],
        [get_btn(4), get_btn(5), get_btn(6)],
        [InlineKeyboardButton("🎲 پرتاب تاس (Roll)", callback_data=f"dice_roll")],
        [InlineKeyboardButton("❌ لغو بازی", callback_data=f"dice_cancel")],
    ]

    try:
        await query.edit_message_text(
            f"🎲 <b>بازی تاس دارکی</b> 🎲\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 بازیکن: {get_user_display(user)}\n"
            f"💰 مبلغ شرط: <code>{format_number(game['amount'])}</code> DP\n\n"
            f"🎯 <b>ضرایب برد:</b>\n"
            f"• ۱ عدد: ۶ برابر 🥇\n"
            f"• ۲ عدد: ۳ برابر 🥈\n"
            f"• ۳ عدد: ۱.۵ برابر 🥉\n\n"
            f"📌 <b>اعداد انتخابی:</b> <code>{picks_display}</code>\n"
            f"💎 <b>ضریب فعلی:</b> {mult_text}\n\n"
            f"⚡️ <i>حداکثر ۳ عدد + دکمه پرتاب</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(kb)
        )
    except Exception:
        pass


async def dice_roll_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پرتاب تاس"""
    query = update.callback_query
    user = query.from_user

    game_key = f"{query.message.chat_id}_{query.message.message_id}"
    game = dice_games.get(game_key)

    if not game:
        await query.answer("❌ بازی یافت نشد!", show_alert=True)
        return
    if game['user_id'] != user.id:
        await query.answer("❌ این بازی شما نیست!", show_alert=True)
        return
    if game['status'] != 'picking':
        await query.answer("❌ بازی تمام شده!", show_alert=True)
        return
    if len(game['picks']) == 0:
        await query.answer("⚠️ حداقل یک عدد انتخاب کنید!", show_alert=True)
        return

    game['status'] = 'rolling'
    await query.answer("🎲 در حال پرتاب تاس...")

    # ارسال تاس تلگرام (انیمیشن واقعی)
    dice_msg = await context.bot.send_dice(chat_id=game['chat_id'], emoji='🎲')
    dice_value = dice_msg.dice.value

    # صبر برای اتمام انیمیشن
    await asyncio.sleep(4)

    picks = game['picks']
    amount = game['amount']
    won = dice_value in picks

    # محاسبه ضریب و برد
    if len(picks) == 1:
        multiplier = 6.0
        mult_display = "۶ برابر"
    elif len(picks) == 2:
        multiplier = 3.0
        mult_display = "۳ برابر"
    else:  # 3
        multiplier = 1.5
        mult_display = "۱.۵ برابر"

    picks_display = " - ".join([str(p) for p in sorted(picks)])

    if won:
        prize = int(amount * multiplier)
        db.add_dark_points(user.id, prize)

        result_text = (
            f"🎉 🏆 <b>برنده شدی!</b> 🏆 🎉\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 بازیکن: {get_user_display(user)}\n"
            f"💰 مبلغ شرط: <code>{format_number(amount)}</code> DP\n\n"
            f"🎲 عدد تاس: <b>{dice_value}</b>\n"
            f"📌 اعداد شما: <code>{picks_display}</code>\n"
            f"💎 ضریب برد: {mult_display}\n\n"
            f"🏆 مبلغ برد: +<code>{format_number(prize)}</code> DP\n"
            f"💰 موجودی جدید: <code>{format_number(db.get_balance(user.id))}</code> DP\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎯 <i>خوش‌شانسی!</i>"
        )
    else:
        result_text = (
            f"💔 <b>باختی!</b> 💔\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 بازیکن: {get_user_display(user)}\n"
            f"💰 مبلغ شرط: <code>{format_number(amount)}</code> DP\n\n"
            f"🎲 عدد تاس: <b>{dice_value}</b>\n"
            f"📌 اعداد شما: <code>{picks_display}</code>\n\n"
            f"😔 <i>هیچ عددی مطابقت نداشت</i>\n"
            f"💰 موجودی: <code>{format_number(db.get_balance(user.id))}</code> DP\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎲 <i>دفعه بعد شانس بیشتر!</i>"
        )

    try:
        await query.edit_message_text(result_text, parse_mode=ParseMode.HTML)
    except Exception:
        pass

    game['status'] = 'finished'
    # پاک کردن از حافظه بعد از ۳۰ ثانیه
    asyncio.create_task(cleanup_dice_game(game_key, 30))


async def cleanup_dice_game(game_key, delay):
    await asyncio.sleep(delay)
    if game_key in dice_games:
        del dice_games[game_key]


async def dice_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لغو بازی تاس"""
    query = update.callback_query
    user = query.from_user

    game_key = f"{query.message.chat_id}_{query.message.message_id}"
    game = dice_games.get(game_key)

    if not game:
        await query.answer("❌ یافت نشد!", show_alert=True)
        return
    if game['user_id'] != user.id:
        await query.answer("❌ فقط سازنده می‌تواند لغو کند!", show_alert=True)
        return
    if game['status'] != 'picking':
        await query.answer("❌ بازی شروع شده!", show_alert=True)
        return

    # برگرداندن پول
    db.add_dark_points(user.id, game['amount'])
    game['status'] = 'cancelled'

    await query.edit_message_text(
        f"❌ <b>بازی تاس لغو شد</b>\n\n💰 <code>{format_number(game['amount'])}</code> DP بازگردانده شد.",
        parse_mode=ParseMode.HTML
    )

    if game_key in dice_games:
        del dice_games[game_key]# ============ TRANSFER ============

async def handle_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()

    # روش ۱: ریپلای + انتقال [مبلغ]
    if update.message.reply_to_message:
        parts = text.split()
        if len(parts) >= 2:
            try:
                amount = int(parts[1])
            except Exception:
                await update.message.reply_text("❌ مبلغ نامعتبر!")
                return

            target_id = update.message.reply_to_message.from_user.id
            if target_id == user.id:
                await update.message.reply_text("❌ نمی‌توانید به خودتان انتقال دهید!")
                return

            if db.is_banned(target_id):
                await update.message.reply_text("❌ کاربر مقصد مسدود شده است.")
                return

            fee = int(amount * TRANSFER_FEE)
            total_cost = amount + fee
            balance = db.get_balance(user.id)

            if balance < total_cost:
                await update.message.reply_text(
                    f"❌ <b>موجودی ناکافی!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"💰 مبلغ انتقال: <code>{format_number(amount)}</code> DP\n"
                    f"💸 کارمزد ۱۰٪: <code>{format_number(fee)}</code> DP\n"
                    f"📊 کل نیاز: <code>{format_number(total_cost)}</code> DP\n"
                    f"💎 موجودی شما: <code>{format_number(balance)}</code> DP",
                    parse_mode=ParseMode.HTML
                )
                return

            if not db.remove_dark_points(user.id, total_cost):
                await update.message.reply_text("❌ خطا در انتقال!")
                return

            if not db.get_user(target_id):
                target = update.message.reply_to_message.from_user
                db.create_user(target_id, target.username or "", target.first_name or "")

            db.add_dark_points(target_id, amount)
            db.record_transfer(user.id, target_id, amount, fee)

            target = update.message.reply_to_message.from_user
            target_display = f"@{target.username}" if target.username else f"<code>{target.id}</code>"

            await update.message.reply_text(
                f"✅ <b>انتقال موفق!</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"💰 مبلغ: <code>{format_number(amount)}</code> DP\n"
                f"💸 کارمزد: <code>{format_number(fee)}</code> DP\n"
                f"👤 مقصد: {target_display}\n"
                f"💎 موجودی جدید: <code>{format_number(db.get_balance(user.id))}</code> DP",
                parse_mode=ParseMode.HTML
            )

            try:
                await context.bot.send_message(
                    target_id,
                    f"💰 <b>دارک پوینت دریافت کردید!</b>\n\n"
                    f"👤 از: {get_user_display(user)}\n"
                    f"💰 مبلغ: <code>{format_number(amount)}</code> DP\n"
                    f"💎 موجودی جدید: <code>{format_number(db.get_balance(target_id))}</code> DP",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass
            return

    # روش ۲: انتقال [مبلغ] به [شماره]
    match = re.match(r'انتقال\s+(\d+)\s+به\s+(\d+)', text)
    if match:
        amount = int(match.group(1))
        target_id = int(match.group(2))

        if target_id == user.id:
            await update.message.reply_text("❌ نمی‌توانید به خودتان انتقال دهید!")
            return

        target_user = db.get_user(target_id)
        if not target_user:
            await update.message.reply_text("❌ کاربر مقصد یافت نشد!")
            return

        if db.is_banned(target_id):
            await update.message.reply_text("❌ کاربر مقصد مسدود شده است.")
            return

        fee = int(amount * TRANSFER_FEE)
        total_cost = amount + fee
        balance = db.get_balance(user.id)

        if balance < total_cost:
            await update.message.reply_text(
                f"❌ <b>موجودی ناکافی!</b>\n"
                f"📊 کل نیاز: <code>{format_number(total_cost)}</code> DP\n"
                f"💎 موجودی: <code>{format_number(balance)}</code> DP",
                parse_mode=ParseMode.HTML
            )
            return

        if not db.remove_dark_points(user.id, total_cost):
            return

        db.add_dark_points(target_id, amount)
        db.record_transfer(user.id, target_id, amount, fee)

        await update.message.reply_text(
            f"✅ <b>انتقال موفق!</b>\n\n"
            f"💰 مبلغ: <code>{format_number(amount)}</code> DP\n"
            f"💸 کارمزد: <code>{format_number(fee)}</code> DP\n"
            f"👤 مقصد: <code>{target_id}</code>\n"
            f"💎 موجودی جدید: <code>{format_number(db.get_balance(user.id))}</code> DP",
            parse_mode=ParseMode.HTML
        )

        try:
            await context.bot.send_message(
                target_id,
                f"💰 <b>دارک پوینت دریافت شد!</b>\n\n"
                f"💰 مبلغ: <code>{format_number(amount)}</code> DP\n"
                f"💎 موجودی جدید: <code>{format_number(db.get_balance(target_id))}</code> DP",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass


# ============ BANK DARKI ============

async def handle_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = db.get_user(user.id)

    total_bank = db.get_total_bank_balance()

    if not u['bank_account']:
        kb = [[InlineKeyboardButton(f"🏦 افتتاح حساب ({format_number(BANK_OPEN_COST)} DP)", callback_data="bank_open")]]
        await update.message.reply_text(
            f"🏦 <b>بانک دارکی</b> 🏦\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"❌ شما حسابی ندارید\n\n"
            f"💵 هزینه افتتاح: <code>{format_number(BANK_OPEN_COST)}</code> DP\n"
            f"📈 سود ۲۴ ساعته: <b>۱۰٪</b>\n\n"
            f"🏦 کل موجودی بانک: <code>{format_number(total_bank)}</code> DP\n"
            f"━━━━━━━━━━━━━━━━━━",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(kb)
        )
    else:
        elapsed = time.time() - u['bank_deposit_time'] if u['bank_deposit_time'] > 0 else 0
        interest_ready = elapsed >= 86400 and u['bank_balance'] > 0 and not u['bank_interest_collected']
        potential = int(u['bank_balance'] * 0.10) if interest_ready else 0

        buttons = []
        if u['bank_balance'] == 0:
            buttons.append([InlineKeyboardButton("💰 واریز", callback_data="bank_deposit")])
        else:
            if interest_ready:
                buttons.append([InlineKeyboardButton("💸 برداشت (با سود)", callback_data="bank_withdraw")])
            else:
                remaining = max(0, 86400 - elapsed)
                hours = int(remaining // 3600)
                mins = int((remaining % 3600) // 60)
                buttons.append([InlineKeyboardButton(f"⏰ {hours}h {mins}m تا سود", callback_data="bank_wait")])
            buttons.append([InlineKeyboardButton("💰 واریز بیشتر", callback_data="bank_deposit")])
            buttons.append([InlineKeyboardButton("💸 برداشت بدون سود", callback_data="bank_withdraw")])

        text = (
            f"🏦 <b>بانک دارکی</b> 🏦\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"💳 شماره کارت: <code>{u['bank_card']}</code>\n"
            f"💰 موجودی بانک: <code>{format_number(u['bank_balance'])}</code> DP\n"
        )
        if potential > 0:
            text += f"📈 سود آماده: +<code>{format_number(potential)}</code> DP\n"

        text += (
            f"\n🏦 کل موجودی بانک: <code>{format_number(total_bank)}</code> DP\n"
            f"━━━━━━━━━━━━━━━━━━"
        )

        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))


async def bank_open_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if db.get_balance(user.id) < BANK_OPEN_COST:
        await query.answer(f"❌ نیاز: {format_number(BANK_OPEN_COST)} DP", show_alert=True)
        return

    kb = [
        [InlineKeyboardButton("🎲 خودکار بساز", callback_data="bank_auto_card")],
        [InlineKeyboardButton("✏️ شماره دلخواه", callback_data="bank_custom_card")],
    ]
    await query.edit_message_text(
        f"🏦 <b>افتتاح حساب بانک دارکی</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💵 هزینه: <code>{format_number(BANK_OPEN_COST)}</code> DP\n\n"
        f"🎲 خودکار: شماره ۱۳ رقمی می‌سازد\n"
        f"✏️ دلخواه: شماره دلخواه بفرستید",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def bank_auto_card_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if db.get_balance(user.id) < BANK_OPEN_COST:
        await query.answer("❌ ناکافی!", show_alert=True)
        return

    card = db.generate_bank_card()
    while db.card_exists(card):
        card = db.generate_bank_card()

    db.remove_dark_points(user.id, BANK_OPEN_COST)
    db.open_bank_account(user.id, card)

    await query.edit_message_text(
        f"✅ <b>حساب بانک دارکی افتتاح شد!</b>\n\n"
        f"💳 شماره کارت: <code>{card}</code>\n"
        f"💵 هزینه: <code>{format_number(BANK_OPEN_COST)}</code> DP\n\n"
        f"<i>اکنون می‌توانید واریز کنید و سود بگیرید!</i>",
        parse_mode=ParseMode.HTML
    )


async def bank_custom_card_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_bank_card'] = True
    await query.edit_message_text(
        f"✏️ <b>شماره کارت دلخواه</b>\n\n"
        f"یک شماره ۱۳ رقمی از اعداد انگلیسی بفرستید\n"
        f"⚠️ نباید قبلاً ثبت شده باشد\n\n"
        f"<i>به پیوی ربات بفرستید</i>",
        parse_mode=ParseMode.HTML
    )


async def bank_deposit_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_bank_deposit'] = True

    balance = db.get_balance(query.from_user.id)
    await query.edit_message_text(
        f"💰 <b>واریز به بانک دارکی</b>\n\n"
        f"💎 موجودی: <code>{format_number(balance)}</code> DP\n\n"
        f"مبلغ را به پیوی ربات بفرستید:",
        parse_mode=ParseMode.HTML
    )


async def bank_withdraw_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    balance, interest = db.bank_withdraw(user.id)
    total = balance + interest

    if total == 0:
        await query.answer("❌ موجودی بانکی ندارید!", show_alert=True)
        return

    await query.edit_message_text(
        f"✅ <b>برداشت از بانک دارکی</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 اصل سپرده: <code>{format_number(balance)}</code> DP\n"
        f"📈 سود ۱۰٪: +<code>{format_number(interest)}</code> DP\n"
        f"💎 کل دریافتی: <code>{format_number(total)}</code> DP\n\n"
        f"💎 موجودی جدید: <code>{format_number(db.get_balance(user.id))}</code> DP",
        parse_mode=ParseMode.HTML
    )


async def bank_wait_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("⏰ سود شما هنوز آماده نیست. ۲۴ ساعت صبر کنید.", show_alert=True)


# ============ FACTORY DARKI ============

async def handle_factory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = db.get_user(user.id)

    if not u['factory_active'] and u['factory_level'] == 0:
        kb = [[InlineKeyboardButton(f"🏭 افتتاح کارخونه ({format_number(FACTORY_OPEN_COST)} DP)", callback_data="factory_open")]]
        await update.message.reply_text(
            f"🏭 <b>کارخونه دارکی</b> 🏭\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"❌ شما کارخونه‌ای ندارید\n\n"
            f"💵 هزینه افتتاح: <code>{format_number(FACTORY_OPEN_COST)}</code> DP\n"
            f"🔧 نگهداری: ساعتی <code>{FACTORY_HOURLY_MAINTENANCE}</code> DP\n\n"
            f"📊 <b>سطوح کارخونه:</b>\n"
            f"سطح ۱: ۱۰ DP/دقیقه\n"
            f"سطح ۲: ۲۵ DP/دقیقه (ارتقا: ۵۰K)\n"
            f"سطح ۳: ۴۰ DP/دقیقه (ارتقا: ۸۰K)\n"
            f"سطح ۴: ۵۰ DP/دقیقه (ارتقا: ۱۰۰K)\n"
            f"سطح ۵: ۱۰۰ DP/دقیقه (ارتقا: ۲۵۰K)\n"
            f"━━━━━━━━━━━━━━━━━━",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    mined = db.collect_factory(user.id)
    maintenance = db.factory_maintenance_due(user.id)
    u = db.get_user(user.id)
    f_level = u['factory_level']
    mine_rate = FACTORY_LEVELS[f_level]['mine_per_min']

    buttons = []
    if f_level < 5:
        upgrade_cost = FACTORY_LEVELS[f_level]['upgrade_cost']
        buttons.append([InlineKeyboardButton(
            f"⬆️ ارتقا به سطح {f_level+1} ({format_number(upgrade_cost)} DP)",
            callback_data="factory_upgrade"
        )])
    buttons.append([InlineKeyboardButton("💰 جمع‌آوری", callback_data="factory_collect")])

    status = "✅ فعال" if u['factory_active'] else "❌ غیرفعال"

    text = (
        f"🏭 <b>کارخونه دارکی</b> 🏭\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 سطح: <b>{f_level}</b>\n"
        f"⚡ نرخ: <b>{mine_rate}</b> DP/دقیقه\n"
        f"📋 وضعیت: {status}\n"
    )
    if mined > 0:
        text += f"💰 جمع‌آوری شده: +<code>{format_number(mined)}</code> DP\n"
    if maintenance == -1:
        text += f"\n⚠️ کارخونه متوقف شد!\n"
    elif maintenance > 0:
        text += f"🔧 هزینه نگهداری: -<code>{format_number(maintenance)}</code> DP\n"

    text += f"\n💎 موجودی: <code>{format_number(db.get_balance(user.id))}</code> DP\n━━━━━━━━━━━━━━━━━━"

    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))


async def factory_open_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if db.get_balance(user.id) < FACTORY_OPEN_COST:
        await query.answer(f"❌ نیاز: {format_number(FACTORY_OPEN_COST)} DP", show_alert=True)
        return

    db.remove_dark_points(user.id, FACTORY_OPEN_COST)
    db.open_factory(user.id)

    await query.edit_message_text(
        f"✅ <b>کارخونه دارکی افتتاح شد!</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 سطح: ۱\n"
        f"⚡ نرخ: ۱۰ DP/دقیقه\n"
        f"💵 هزینه: <code>{format_number(FACTORY_OPEN_COST)}</code> DP\n\n"
        f"<i>کارخونه شروع به ماین کرد!</i>",
        parse_mode=ParseMode.HTML
    )


async def factory_upgrade_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    u = db.get_user(user.id)
    if not u or u['factory_level'] >= 5:
        await query.answer("❌ حداکثر سطح!", show_alert=True)
        return

    upgrade_cost = FACTORY_LEVELS[u['factory_level']]['upgrade_cost']
    if db.get_balance(user.id) < upgrade_cost:
        await query.answer(f"❌ نیاز: {format_number(upgrade_cost)} DP", show_alert=True)
        return

    db.collect_factory(user.id)
    db.remove_dark_points(user.id, upgrade_cost)
    db.upgrade_factory(user.id)

    new_level = u['factory_level'] + 1
    new_rate = FACTORY_LEVELS[new_level]['mine_per_min']

    await query.edit_message_text(
        f"⬆️ <b>کارخونه ارتقا یافت!</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 سطح جدید: <b>{new_level}</b>\n"
        f"⚡ نرخ جدید: <b>{new_rate}</b> DP/دقیقه\n"
        f"💵 هزینه ارتقا: <code>{format_number(upgrade_cost)}</code> DP\n"
        f"💎 موجودی: <code>{format_number(db.get_balance(user.id))}</code> DP",
        parse_mode=ParseMode.HTML
    )


async def factory_collect_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    mined = db.collect_factory(user.id)
    db.factory_maintenance_due(user.id)

    await query.answer(f"💰 {format_number(mined)} DP جمع‌آوری شد!", show_alert=True)# ============ ADMIN PANEL - Enhanced ============

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return

    stats = db.get_stats()

    gift_status = "🟢" if db.get_setting('gift_section_active', '1') == '1' else "🔴"
    stars_status = "🟢" if db.get_setting('stars_section_active', '1') == '1' else "🔴"
    buydp_status = "🟢" if db.get_setting('buy_dp_active', '1') == '1' else "🔴"
    crash_status = "🟢" if db.get_setting('crash_active', '1') == '1' else "🔴"

    kb = [
        [InlineKeyboardButton("📊 آمار کامل ربات", callback_data="adm_stats")],
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
            InlineKeyboardButton("🚫 بن/آنبن", callback_data="adm_ban_user"),
        ],
        [InlineKeyboardButton("📢 مدیریت کانال‌های اجباری", callback_data="adm_channels")],
        # قابلیت جدید ۱: تغییر قیمت پنل سنایی
        [InlineKeyboardButton("💵 تغییر قیمت پنل سنایی", callback_data="adm_panel_prices")],
        [
            InlineKeyboardButton("📦 ساخت پلن پنل", callback_data="adm_create_panel"),
            InlineKeyboardButton("🎁 افزودن پلن گیفت", callback_data="adm_add_gift_plan"),
        ],
        [
            InlineKeyboardButton("💵 قیمت گیفت", callback_data="adm_set_gift_price"),
            InlineKeyboardButton("⭐ قیمت استارز", callback_data="adm_set_stars_price"),
        ],
        [
            InlineKeyboardButton(f"🎁 گیفت: {gift_status}", callback_data="adm_toggle_gift"),
            InlineKeyboardButton(f"⭐ استارز: {stars_status}", callback_data="adm_toggle_stars"),
        ],
        [
            InlineKeyboardButton(f"💰 خرید DP: {buydp_status}", callback_data="adm_toggle_buydp"),
            InlineKeyboardButton(f"💥 انفجار: {crash_status}", callback_data="adm_toggle_crash"),
        ],
        # قابلیت جدید ۲: ارسال پیام به کاربر خاص
        [InlineKeyboardButton("💬 ارسال پیام به کاربر خاص", callback_data="adm_send_to_user")],
        # قابلیت جدید ۳: مشاهده لیست سفارشات اخیر
        [InlineKeyboardButton("📋 آخرین سفارشات", callback_data="adm_recent_orders")],
        # قابلیت جدید ۴: هدیه به تعداد مشخص از کاربران برتر
        [InlineKeyboardButton("🎁 هدیه به کاربران برتر", callback_data="adm_gift_top")],
        [InlineKeyboardButton("📝 ساخت چک شخصی", callback_data="adm_create_check")],
        [InlineKeyboardButton("🎁 هدیه به همه کاربران", callback_data="adm_gift_all")],
        [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="main_menu")],
    ]

    text = (
        f"🛡 <b>پنل مدیریت ادمین</b> 🛡\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 کل کاربران: <b>{stats['total_users']}</b>\n"
        f"✅ فعال ۷ روز: <b>{stats['active_7d']}</b>\n"
        f"🆕 جدید امروز: <b>{stats['new_today']}</b>\n"
        f"🚫 بن شده: <b>{stats['banned_users']}</b>\n"
        f"💎 کل DP: <code>{format_number(stats['total_dp'])}</code>\n"
        f"🏦 کل بانک: <code>{format_number(stats['total_bank'])}</code>\n"
        f"━━━━━━━━━━━━━━━━━━"
    )

    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))
        except Exception:
            await update.callback_query.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def admin_stats_cb(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()

    stats = db.get_stats()
    text = (
        f"📊 <b>آمار کامل ربات</b> 📊\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 <b>کاربران:</b>\n"
        f"   • کل: <b>{stats['total_users']}</b>\n"
        f"   • فعال ۷ روزه: <b>{stats['active_7d']}</b>\n"
        f"   • جدید امروز: <b>{stats['new_today']}</b>\n"
        f"   • بن شده: <b>{stats['banned_users']}</b>\n\n"
        f"💰 <b>مالی:</b>\n"
        f"   • کل DP: <code>{format_number(stats['total_dp'])}</code>\n"
        f"   • کل بانک: <code>{format_number(stats['total_bank'])}</code>\n\n"
        f"📦 <b>سفارشات:</b>\n"
        f"   • پنل: {stats['panel_orders']}\n"
        f"   • گیفت: {stats['gift_orders']}\n"
        f"   • استارز: {stats['stars_orders']}\n\n"
        f"💥 <b>بازی انفجار:</b>\n"
        f"   • برد: {stats['crash_won']}\n"
        f"   • باخت: {stats['crash_lost']}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    kb = [[InlineKeyboardButton("🔙 پنل ادمین", callback_data="adm_back")]]
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


# ============ BROADCAST WITH FULL REPORT ============

async def adm_broadcast_msg_cb(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()
    context.user_data['admin_action'] = 'broadcast_msg'
    await query.edit_message_text(
        "📢 <b>پیام همگانی</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "پیام مورد نظر را ارسال کنید (متن، عکس، ویدیو، استیکر یا هر چیز):\n\n"
        "💡 <i>پیام برای همه کاربران ارسال می‌شود</i>\n\n"
        "برای لغو: /cancel",
        parse_mode=ParseMode.HTML
    )


async def adm_broadcast_fwd_cb(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()
    context.user_data['admin_action'] = 'broadcast_fwd'
    await query.edit_message_text(
        "📤 <b>فوروارد همگانی</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "پیامی که می‌خواهید فوروارد شود را ارسال کنید:\n\n"
        "برای لغو: /cancel",
        parse_mode=ParseMode.HTML
    )


async def do_broadcast(update, context, mode='copy'):
    admin_id = update.effective_user.id
    users = db.get_all_user_ids()
    total = len(users)
    sent = 0
    failed = 0
    blocked = 0
    start_time = time.time()

    status_msg = await update.message.reply_text(
        f"⏳ <b>در حال ارسال به {total} کاربر...</b>\n\n"
        f"لطفاً صبر کنید...",
        parse_mode=ParseMode.HTML
    )

    for uid in users:
        try:
            if mode == 'copy':
                await context.bot.copy_message(
                    chat_id=uid,
                    from_chat_id=update.message.chat_id,
                    message_id=update.message.message_id
                )
            else:
                await context.bot.forward_message(
                    chat_id=uid,
                    from_chat_id=update.message.chat_id,
                    message_id=update.message.message_id
                )
            sent += 1
        except Exception as e:
            err_str = str(e).lower()
            if 'blocked' in err_str or 'bot was blocked' in err_str or 'kicked' in err_str or 'deactivated' in err_str:
                blocked += 1
            failed += 1

        if (sent + failed) % 20 == 0:
            try:
                elapsed_now = int(time.time() - start_time)
                await status_msg.edit_text(
                    f"⏳ <b>در حال ارسال...</b>\n\n"
                    f"✅ موفق: <b>{sent}</b>\n"
                    f"❌ ناموفق: <b>{failed}</b>\n"
                    f"🚫 بلاک کرده: <b>{blocked}</b>\n"
                    f"📊 پیشرفت: <b>{sent+failed}/{total}</b>\n"
                    f"📈 درصد: <b>{int((sent+failed)/total*100)}%</b>\n"
                    f"⏱ زمان: {elapsed_now} ثانیه",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass
        await asyncio.sleep(0.05)

    db.log_broadcast(admin_id, mode, total, sent, failed)

    mode_text = "پیام همگانی" if mode == 'copy' else "فوروارد همگانی"
    success_rate = int(sent/total*100 if total else 0)
    total_time = int(time.time() - start_time)

    await status_msg.edit_text(
        f"✅ <b>{mode_text} تکمیل شد!</b> ✅\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 <b>گزارش کامل:</b>\n\n"
        f"👥 کل کاربران هدف: <b>{total}</b>\n"
        f"✅ ارسال موفق: <b>{sent}</b>\n"
        f"❌ ارسال ناموفق: <b>{failed}</b>\n"
        f"🚫 کاربران بلاک‌کرده ربات: <b>{blocked}</b>\n"
        f"📈 درصد موفقیت: <b>{success_rate}%</b>\n"
        f"⏱ زمان کل: <b>{total_time}</b> ثانیه\n"
        f"━━━━━━━━━━━━━━━━━━",
        parse_mode=ParseMode.HTML
    )


# ============ CHANNELS MANAGEMENT ============

async def adm_channels_cb(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()

    channels = db.get_force_channels()
    text = f"📢 <b>کانال‌های عضویت اجباری</b> 📢\n━━━━━━━━━━━━━━━━━━\n\n"

    if not channels:
        text += "❌ هیچ کانالی ثبت نشده\n"
    else:
        for ch in channels:
            title = html.escape(ch['channel_title'] or "بدون عنوان")
            text += f"• {ch['channel_username']} ({title})\n"

    text += "\n━━━━━━━━━━━━━━━━━━\n💡 <i>ربات باید ادمین کانال باشد</i>"

    kb = [[InlineKeyboardButton("➕ افزودن کانال", callback_data="adm_add_channel")]]
    for ch in channels:
        kb.append([InlineKeyboardButton(f"🗑 حذف {ch['channel_username']}", callback_data=f"adm_del_ch_{ch['channel_id']}")])
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="adm_back")])

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def adm_add_channel_cb(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()
    context.user_data['admin_action'] = 'add_channel'
    await query.edit_message_text(
        "➕ <b>افزودن کانال جوین اجباری</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "یوزرنیم کانال را با @ بفرستید:\n\n"
        "مثال: <code>@mychannel</code>\n\n"
        "⚠️ <b>ربات باید در کانال ادمین باشد</b>\n\n"
        "برای لغو: /cancel",
        parse_mode=ParseMode.HTML
    )


async def adm_del_ch_cb(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    channel_id = int(query.data.split("_")[-1])
    db.remove_force_channel(channel_id)
    await query.answer("✅ کانال حذف شد", show_alert=True)
    await adm_channels_cb(update, context)


# ============ NEW: PANEL PRICES MANAGEMENT ============

async def adm_panel_prices_cb(update, context):
    """قابلیت جدید: تغییر قیمت پنل سنایی"""
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()

    price_500 = int(db.get_setting('panel_snai_500gb', str(DEFAULT_PANEL_PRICES['snai_500gb'])))
    price_800 = int(db.get_setting('panel_snai_800gb', str(DEFAULT_PANEL_PRICES['snai_800gb'])))
    price_1tb = int(db.get_setting('panel_snai_1tb', str(DEFAULT_PANEL_PRICES['snai_1tb'])))

    text = (
        f"💵 <b>مدیریت قیمت پنل سنایی</b> 💵\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 <b>قیمت‌های فعلی:</b>\n\n"
        f"🛒 سنایی 500GB: <code>{format_number(price_500)}</code> DP\n"
        f"🛒 سنایی 800GB: <code>{format_number(price_800)}</code> DP\n"
        f"🛒 سنایی 1TB: <code>{format_number(price_1tb)}</code> DP\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"برای تغییر، دکمه مورد نظر را بزنید:"
    )

    kb = [
        [InlineKeyboardButton(f"✏️ تغییر 500GB ({format_number(price_500)} DP)", callback_data="adm_edit_price_500gb")],
        [InlineKeyboardButton(f"✏️ تغییر 800GB ({format_number(price_800)} DP)", callback_data="adm_edit_price_800gb")],
        [InlineKeyboardButton(f"✏️ تغییر 1TB ({format_number(price_1tb)} DP)", callback_data="adm_edit_price_1tb")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="adm_back")],
    ]
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def adm_edit_price_cb(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()

    data = query.data
    if data == "adm_edit_price_500gb":
        plan_key = "panel_snai_500gb"
        plan_name = "500GB"
    elif data == "adm_edit_price_800gb":
        plan_key = "panel_snai_800gb"
        plan_name = "800GB"
    elif data == "adm_edit_price_1tb":
        plan_key = "panel_snai_1tb"
        plan_name = "1TB"
    else:
        return

    context.user_data['admin_action'] = 'set_panel_price'
    context.user_data['panel_price_key'] = plan_key
    context.user_data['panel_price_name'] = plan_name

    await query.edit_message_text(
        f"✏️ <b>تغییر قیمت سنایی {plan_name}</b>\n\n"
        f"قیمت جدید را به DP بفرستید:\n\n"
        f"مثال: <code>500000</code>\n\n"
        f"برای لغو: /cancel",
        parse_mode=ParseMode.HTML
    )


# ============ NEW: SEND MESSAGE TO SPECIFIC USER ============

async def adm_send_to_user_cb(update, context):
    """قابلیت جدید: ارسال پیام به کاربر خاص"""
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()
    context.user_data['admin_action'] = 'send_to_user_id'
    await query.edit_message_text(
        "💬 <b>ارسال پیام به کاربر خاص</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "شماره کاربری مقصد را بفرستید:\n\n"
        "مثال: <code>123456789</code>\n\n"
        "برای لغو: /cancel",
        parse_mode=ParseMode.HTML
    )


# ============ NEW: RECENT ORDERS ============

async def adm_recent_orders_cb(update, context):
    """قابلیت جدید: مشاهده لیست آخرین سفارشات"""
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()

    conn = db.get_conn()
    c = conn.cursor()
    
    text = "📋 <b>آخرین سفارشات ربات</b> 📋\n━━━━━━━━━━━━━━━━━━\n\n"
    
    # پنل
    text += "🛒 <b>۵ سفارش آخر پنل:</b>\n"
    c.execute("SELECT * FROM panel_orders ORDER BY created_at DESC LIMIT 5")
    panel_orders = c.fetchall()
    if panel_orders:
        for o in panel_orders:
            text += f"• #<code>{o['order_id']}</code> | {html.escape(o['plan_name'])} | <code>{o['user_id']}</code>\n"
    else:
        text += "  <i>هیچ</i>\n"
    
    text += "\n⭐ <b>۵ سفارش آخر استارز:</b>\n"
    c.execute("SELECT * FROM stars_orders ORDER BY created_at DESC LIMIT 5")
    stars_orders = c.fetchall()
    if stars_orders:
        for o in stars_orders:
            text += f"• #<code>{o['order_id']}</code> | {o['amount']} استارز | <code>{o['target_id']}</code>\n"
    else:
        text += "  <i>هیچ</i>\n"

    text += "\n🎁 <b>۵ سفارش آخر گیفت:</b>\n"
    c.execute("SELECT * FROM gift_orders ORDER BY created_at DESC LIMIT 5")
    gift_orders = c.fetchall()
    if gift_orders:
        for o in gift_orders:
            text += f"• #<code>{o['order_id']}</code> | {html.escape(o['gift_type'])} | <code>{o['user_id']}</code>\n"
    else:
        text += "  <i>هیچ</i>\n"
    
    conn.close()
    text += "\n━━━━━━━━━━━━━━━━━━"

    kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="adm_back")]]
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


# ============ NEW: GIFT TO TOP USERS ============

async def adm_gift_top_cb(update, context):
    """قابلیت جدید: هدیه به N کاربر برتر"""
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()
    context.user_data['admin_action'] = 'gift_top_count'
    await query.edit_message_text(
        "🎁 <b>هدیه به کاربران برتر</b> 🎁\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "چند نفر از کاربران برتر (بیشترین DP) هدیه بگیرند؟\n\n"
        "مثال: <code>10</code> (به ۱۰ نفر برتر)\n\n"
        "برای لغو: /cancel",
        parse_mode=ParseMode.HTML
    )


# ============ ADMIN CALLBACK: SEND CONFIG & REPLY ============

async def admin_send_config_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ارسال کانفیگ توسط ادمین به کاربر خاص - سفارش پنل"""
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌", show_alert=True)
        return

    parts = query.data.split("_")
    order_id = int(parts[3])
    user_id = int(parts[4])

    await query.answer()
    context.user_data['admin_action'] = 'send_config'
    context.user_data['config_order_id'] = order_id
    context.user_data['config_user_id'] = user_id

    await query.message.reply_text(
        f"📤 <b>ارسال کانفیگ به کاربر</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 کاربر: <code>{user_id}</code>\n"
        f"🆔 سفارش: <code>{order_id}</code>\n\n"
        f"کانفیگ ساخته شده از پنل سنایی را بفرستید:\n"
        f"<i>(می‌تواند متن، فایل، عکس یا هر چیز باشد)</i>\n\n"
        f"برای لغو: /cancel",
        parse_mode=ParseMode.HTML
    )


async def admin_reply_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پاسخ ادمین به کاربر"""
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌", show_alert=True)
        return

    user_id = int(query.data.split("_")[-1])
    await query.answer()
    context.user_data['admin_action'] = 'reply_user'
    context.user_data['reply_user_id'] = user_id

    await query.message.reply_text(
        f"💬 <b>پاسخ به کاربر</b>\n\n"
        f"👤 کاربر: <code>{user_id}</code>\n\n"
        f"پیام خود را بفرستید (متن، عکس، ویدیو یا هر چیز):\n\n"
        f"برای لغو: /cancel",
        parse_mode=ParseMode.HTML
    )


async def admin_confirm_stars_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تایید سفارش استارز"""
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    order_id = int(query.data.split("_")[-1])
    await query.answer("✅ سفارش تایید شد", show_alert=True)
    
    # نمایش تایید در پیام
    try:
        await query.edit_message_text(
            query.message.text_html + f"\n\n✅ <b>سفارش تایید شد توسط ادمین</b>",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass


async def admin_confirm_gift_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer("✅ سفارش تایید شد", show_alert=True)
    try:
        await query.edit_message_text(
            query.message.text_html + f"\n\n✅ <b>سفارش تایید شد</b>",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass


# ============ MAIN ADMIN CALLBACK ROUTER ============

async def admin_callbacks(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌ شما ادمین نیستید!", show_alert=True)
        return

    data = query.data

    if data == "adm_back":
        await admin_panel(update, context)
    elif data == "adm_stats":
        await admin_stats_cb(update, context)
    elif data == "adm_broadcast_msg":
        await adm_broadcast_msg_cb(update, context)
    elif data == "adm_broadcast_fwd":
        await adm_broadcast_fwd_cb(update, context)
    elif data == "adm_channels":
        await adm_channels_cb(update, context)
    elif data == "adm_add_channel":
        await adm_add_channel_cb(update, context)
    elif data.startswith("adm_del_ch_"):
        await adm_del_ch_cb(update, context)
    elif data == "adm_panel_prices":
        await adm_panel_prices_cb(update, context)
    elif data.startswith("adm_edit_price_"):
        await adm_edit_price_cb(update, context)
    elif data == "adm_send_to_user":
        await adm_send_to_user_cb(update, context)
    elif data == "adm_recent_orders":
        await adm_recent_orders_cb(update, context)
    elif data == "adm_gift_top":
        await adm_gift_top_cb(update, context)
    elif data == "adm_add_dp":
        await query.answer()
        context.user_data['admin_action'] = 'add_dp'
        await query.edit_message_text(
            "💰 <b>افزودن DP به کاربر</b>\n\nشماره کاربری را بفرستید:\n\nبرای لغو: /cancel",
            parse_mode=ParseMode.HTML
        )
    elif data == "adm_remove_dp":
        await query.answer()
        context.user_data['admin_action'] = 'remove_dp'
        await query.edit_message_text(
            "💸 <b>کسر DP از کاربر</b>\n\nشماره کاربری را بفرستید:\n\nبرای لغو: /cancel",
            parse_mode=ParseMode.HTML
        )
    elif data == "adm_search_user":
        await query.answer()
        context.user_data['admin_action'] = 'search_user'
        await query.edit_message_text(
            "🔍 <b>جستجوی کاربر</b>\n\nشماره کاربری یا @username را بفرستید:",
            parse_mode=ParseMode.HTML
        )
    elif data == "adm_ban_user":
        await query.answer()
        context.user_data['admin_action'] = 'ban_user'
        await query.edit_message_text(
            "🚫 <b>بن/آنبن کاربر</b>\n\nشماره کاربری را بفرستید:",
            parse_mode=ParseMode.HTML
        )
    elif data == "adm_create_panel":
        await query.answer()
        context.user_data['admin_action'] = 'create_panel'
        context.user_data['panel_step'] = 'name'
        await query.edit_message_text("📦 <b>ساخت پلن پنل</b>\n\nنام پلن را بفرستید:", parse_mode=ParseMode.HTML)
    elif data == "adm_set_gift_price":
        await query.answer()
        context.user_data['admin_action'] = 'set_gift_price'
        await query.edit_message_text("💵 قیمت جدید گیفت تدی به DP:", parse_mode=ParseMode.HTML)
    elif data == "adm_set_stars_price":
        await query.answer()
        context.user_data['admin_action'] = 'set_stars_price'
        await query.edit_message_text(f"⭐ قیمت جدید {STARS_AMOUNT} استارز به DP:", parse_mode=ParseMode.HTML)
    elif data == "adm_toggle_gift":
        cur = db.get_setting('gift_section_active', '1')
        new = '0' if cur == '1' else '1'
        db.set_setting('gift_section_active', new)
        await query.answer(f"گیفت: {'✅' if new=='1' else '❌'}", show_alert=True)
        await admin_panel(update, context)
    elif data == "adm_toggle_stars":
        cur = db.get_setting('stars_section_active', '1')
        new = '0' if cur == '1' else '1'
        db.set_setting('stars_section_active', new)
        await query.answer(f"استارز: {'✅' if new=='1' else '❌'}", show_alert=True)
        await admin_panel(update, context)
    elif data == "adm_toggle_buydp":
        cur = db.get_setting('buy_dp_active', '1')
        new = '0' if cur == '1' else '1'
        db.set_setting('buy_dp_active', new)
        await query.answer(f"خرید DP: {'✅' if new=='1' else '❌'}", show_alert=True)
        await admin_panel(update, context)
    elif data == "adm_toggle_crash":
        cur = db.get_setting('crash_active', '1')
        new = '0' if cur == '1' else '1'
        db.set_setting('crash_active', new)
        await query.answer(f"انفجار: {'✅' if new=='1' else '❌'}", show_alert=True)
        await admin_panel(update, context)
    elif data == "adm_create_check":
        await query.answer()
        context.user_data['admin_action'] = 'create_check'
        await query.edit_message_text("📝 <b>ساخت چک شخصی</b>\n\nمبلغ چک (DP):", parse_mode=ParseMode.HTML)
    elif data == "adm_add_gift_plan":
        await query.answer()
        context.user_data['admin_action'] = 'add_gift_plan'
        context.user_data['gift_plan_step'] = 'name'
        await query.edit_message_text("🎁 <b>افزودن پلن گیفت</b>\n\nنام پلن:", parse_mode=ParseMode.HTML)
    elif data == "adm_gift_all":
        await query.answer()
        context.user_data['admin_action'] = 'gift_all'
        await query.edit_message_text(
            "🎁 <b>هدیه به همه کاربران</b>\n\nمقدار DP:",
            parse_mode=ParseMode.HTML
        )


# ============ HANDLE ADMIN TEXT INPUTS ============

async def handle_admin_text(update, context):
    user = update.effective_user
    text = update.message.text.strip() if update.message.text else ""
    action = context.user_data.get('admin_action')

    # افزودن کانال
    if action == 'add_channel':
        username = text.strip()
        if not username.startswith('@'):
            username = '@' + username
        try:
            chat = await context.bot.get_chat(username)
            title = chat.title or username
            if db.add_force_channel(username, title):
                await update.message.reply_text(
                    f"✅ <b>کانال اضافه شد!</b>\n\n📢 {username}\n📝 {title}",
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text("❌ این کانال قبلاً اضافه شده!")
        except Exception as e:
            await update.message.reply_text(
                f"❌ <b>خطا!</b>\n\nمطمئن شوید ربات ادمین کانال است.\n{str(e)[:100]}",
                parse_mode=ParseMode.HTML
            )
        context.user_data.pop('admin_action', None)
        return

    # افزودن DP
    if action == 'add_dp':
        if 'admin_target_user' not in context.user_data:
            try:
                target_id = int(text)
                context.user_data['admin_target_user'] = target_id
                await update.message.reply_text(
                    f"💰 چقدر DP به <code>{target_id}</code> اضافه شود؟",
                    parse_mode=ParseMode.HTML
                )
                return
            except Exception:
                await update.message.reply_text("❌ نامعتبر!")
                context.user_data.pop('admin_action', None)
                return
        else:
            try:
                amount = int(text)
                target_id = context.user_data['admin_target_user']

                if not db.get_user(target_id):
                    db.create_user(target_id)

                db.add_dark_points(target_id, amount)
                new_balance = db.get_balance(target_id)

                await update.message.reply_text(
                    f"✅ <b>DP اضافه شد!</b>\n\n"
                    f"👤 <code>{target_id}</code>\n"
                    f"💰 +<code>{format_number(amount)}</code> DP\n"
                    f"💎 موجودی: <code>{format_number(new_balance)}</code> DP",
                    parse_mode=ParseMode.HTML
                )

                try:
                    await context.bot.send_message(
                        target_id,
                        f"🎁 <b>هدیه ادمین!</b>\n\n➕ <code>{format_number(amount)}</code> DP\n💎 موجودی: <code>{format_number(new_balance)}</code>",
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass
            except Exception:
                await update.message.reply_text("❌ نامعتبر!")
            context.user_data.clear()
            return

    # کسر DP
    if action == 'remove_dp':
        if 'admin_target_user' not in context.user_data:
            try:
                context.user_data['admin_target_user'] = int(text)
                await update.message.reply_text("💸 چقدر DP کم شود؟")
                return
            except Exception:
                context.user_data.clear()
                return
        else:
            try:
                amount = int(text)
                target_id = context.user_data['admin_target_user']
                db.remove_dark_points(target_id, amount)
                await update.message.reply_text(
                    f"✅ -<code>{format_number(amount)}</code> از <code>{target_id}</code>",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                await update.message.reply_text("❌ نامعتبر!")
            context.user_data.clear()
            return

    # جستجوی کاربر
    if action == 'search_user':
        u = None
        try:
            uid = int(text)
            u = db.get_user(uid)
        except Exception:
            conn = db.get_conn()
            c = conn.cursor()
            uname = text.replace("@", "")
            c.execute("SELECT * FROM users WHERE username = ?", (uname,))
            u = c.fetchone()
            conn.close()

        if not u:
            await update.message.reply_text("❌ کاربر یافت نشد!")
        else:
            banned = "🚫 بن شده" if u['is_banned'] else "✅ فعال"
            name = html.escape(u['first_name'] or "بدون نام")
            reply_kb = [[InlineKeyboardButton("💬 پاسخ به این کاربر", callback_data=f"admin_reply_{u['user_id']}")]]
            await update.message.reply_text(
                f"👤 <b>اطلاعات کاربر</b>\n━━━━━━━━━━━━━━━━━━\n\n"
                f"🆔 <code>{u['user_id']}</code>\n"
                f"📛 @{u['username'] or 'ندارد'}\n"
                f"👤 <b>{name}</b>\n"
                f"💰 <code>{format_number(u['dark_points'])}</code> DP\n"
                f"📊 سطح: {u['level']}\n"
                f"👥 زیرمجموعه: {u['referral_count']}\n"
                f"📊 وضعیت: {banned}",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(reply_kb)
            )
        context.user_data.clear()
        return

    # بن/آنبن
    if action == 'ban_user':
        try:
            target_id = int(text)
            u = db.get_user(target_id)
            if not u:
                await update.message.reply_text("❌ یافت نشد!")
            else:
                if u['is_banned']:
                    db.unban_user(target_id)
                    await update.message.reply_text(f"✅ <code>{target_id}</code> آنبن شد.", parse_mode=ParseMode.HTML)
                else:
                    db.ban_user(target_id)
                    await update.message.reply_text(f"🚫 <code>{target_id}</code> بن شد.", parse_mode=ParseMode.HTML)
        except Exception:
            await update.message.reply_text("❌ نامعتبر!")
        context.user_data.clear()
        return

    # ساخت پلن پنل
    if action == 'create_panel':
        step = context.user_data.get('panel_step')
        if step == 'name':
            context.user_data['panel_name'] = text
            context.user_data['panel_step'] = 'desc'
            await update.message.reply_text("📝 توضیحات پلن:")
        elif step == 'desc':
            context.user_data['panel_desc'] = text
            context.user_data['panel_step'] = 'price'
            await update.message.reply_text("💰 قیمت (DP):")
        elif step == 'price':
            try:
                context.user_data['panel_price'] = int(text)
                context.user_data['panel_step'] = 'data'
                await update.message.reply_text("📊 حجم دیتا:")
            except Exception:
                await update.message.reply_text("❌ عدد!")
        elif step == 'data':
            db.add_custom_panel(
                context.user_data['panel_name'],
                context.user_data['panel_desc'],
                context.user_data['panel_price'],
                text
            )
            await update.message.reply_text(
                f"✅ <b>پلن ساخته شد!</b>\n\n📦 {html.escape(context.user_data['panel_name'])}\n💰 {format_number(context.user_data['panel_price'])} DP",
                parse_mode=ParseMode.HTML
            )
            context.user_data.clear()
        return

    # تغییر قیمت گیفت
    if action == 'set_gift_price':
        try:
            price = int(text)
            db.set_setting('gift_teddy_price', str(price))
            await update.message.reply_text(f"✅ قیمت گیفت: <code>{format_number(price)}</code> DP", parse_mode=ParseMode.HTML)
        except Exception:
            await update.message.reply_text("❌")
        context.user_data.clear()
        return

    # تغییر قیمت استارز
    if action == 'set_stars_price':
        try:
            price = int(text)
            db.set_setting('stars_price', str(price))
            await update.message.reply_text(f"✅ قیمت استارز: <code>{format_number(price)}</code> DP", parse_mode=ParseMode.HTML)
        except Exception:
            await update.message.reply_text("❌")
        context.user_data.clear()
        return

    # تغییر قیمت پنل سنایی (جدید)
    if action == 'set_panel_price':
        try:
            price = int(text)
            plan_key = context.user_data['panel_price_key']
            plan_name = context.user_data['panel_price_name']
            db.set_setting(plan_key, str(price))
            await update.message.reply_text(
                f"✅ <b>قیمت پنل تغییر کرد!</b>\n\n📦 سنایی {plan_name}\n💰 <code>{format_number(price)}</code> DP",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await update.message.reply_text("❌ نامعتبر!")
        context.user_data.clear()
        return

    # ارسال پیام به کاربر خاص (جدید)
    if action == 'send_to_user_id':
        try:
            target_id = int(text)
            context.user_data['admin_action'] = 'send_to_user_msg'
            context.user_data['send_target_id'] = target_id
            await update.message.reply_text(
                f"✅ کاربر <code>{target_id}</code>\n\nحالا پیام مورد نظر را بفرستید (متن، عکس، ویدیو یا هر چیز):",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await update.message.reply_text("❌ شماره کاربری نامعتبر!")
            context.user_data.clear()
        return

    # هدیه به کاربران برتر (جدید)
    if action == 'gift_top_count':
        try:
            count = int(text)
            context.user_data['admin_action'] = 'gift_top_amount'
            context.user_data['gift_top_count'] = count
            await update.message.reply_text(
                f"✅ {count} نفر برتر\n\nمقدار DP هدیه به هر نفر را بفرستید:"
            )
        except Exception:
            await update.message.reply_text("❌ عدد!")
            context.user_data.clear()
        return

    if action == 'gift_top_amount':
        try:
            amount = int(text)
            count = context.user_data['gift_top_count']
            top_users = db.get_leaderboard(count)
            for tu in top_users:
                db.add_dark_points(tu['user_id'], amount)
                try:
                    await context.bot.send_message(
                        tu['user_id'],
                        f"🎁 <b>شما جزو {count} کاربر برتر بودید!</b>\n\n💰 +<code>{format_number(amount)}</code> DP هدیه ادمین",
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass
            await update.message.reply_text(
                f"✅ <b>هدیه ارسال شد!</b>\n\n💰 <code>{format_number(amount)}</code> DP\n👥 به {len(top_users)} کاربر برتر",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await update.message.reply_text("❌")
        context.user_data.clear()
        return

    # ساخت چک
    if action == 'create_check':
        try:
            amount = int(text)
            code = db.create_check(amount)
            global BOT_USERNAME
            if not BOT_USERNAME:
                me = await context.bot.get_me()
                BOT_USERNAME = me.username
            link = f"https://t.me/{BOT_USERNAME}?start=check_{code}"
            await update.message.reply_text(
                f"✅ <b>چک ساخته شد!</b>\n\n💰 <code>{format_number(amount)}</code> DP\n🔗 {link}",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await update.message.reply_text("❌")
        context.user_data.clear()
        return

    # افزودن پلن گیفت
    if action == 'add_gift_plan':
        step = context.user_data.get('gift_plan_step')
        if step == 'name':
            context.user_data['gift_plan_name'] = text
            context.user_data['gift_plan_step'] = 'price'
            await update.message.reply_text("💰 قیمت (DP):")
        elif step == 'price':
            try:
                price = int(text)
                name = context.user_data['gift_plan_name']
                conn = db.get_conn()
                c = conn.cursor()
                c.execute("SELECT COUNT(*) as cnt FROM settings WHERE key LIKE 'gift_plan_%_name'")
                cnt = c.fetchone()['cnt']
                conn.close()
                plan_num = cnt + 1
                db.set_setting(f'gift_plan_{plan_num}_name', name)
                db.set_setting(f'gift_plan_{plan_num}_price', str(price))
                await update.message.reply_text(
                    f"✅ پلن گیفت اضافه شد!\n🎁 {html.escape(name)}\n💰 {format_number(price)} DP",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                await update.message.reply_text("❌")
            context.user_data.clear()
        return

    # هدیه به همه
    if action == 'gift_all':
        try:
            amount = int(text)
            users = db.get_all_user_ids()
            for uid in users:
                db.add_dark_points(uid, amount)
            await update.message.reply_text(
                f"✅ <b>هدیه به همه!</b>\n\n💰 <code>{format_number(amount)}</code> DP به {len(users)} کاربر",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await update.message.reply_text("❌")
        context.user_data.clear()
        return# ============ PRIVATE MESSAGE HANDLER ============

async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    if db.is_banned(user.id):
        return

    if not db.get_user(user.id):
        db.create_user(user.id, user.username or "", user.first_name or "")

    db.update_last_active(user.id)

    # ادمین: اقدامات مخصوص که هر نوع پیام می‌پذیرند
    if is_admin(user.id):
        action = context.user_data.get('admin_action')

        # پیام همگانی (هر نوع پیام)
        if action == 'broadcast_msg':
            context.user_data.pop('admin_action', None)
            await do_broadcast(update, context, mode='copy')
            return

        # فوروارد همگانی (هر نوع پیام)
        if action == 'broadcast_fwd':
            context.user_data.pop('admin_action', None)
            await do_broadcast(update, context, mode='forward')
            return

        # ارسال کانفیگ برای سفارش پنل (هر نوع پیام)
        if action == 'send_config':
            order_id = context.user_data.get('config_order_id')
            target_user_id = context.user_data.get('config_user_id')

            try:
                # کپی پیام برای کاربر
                sent_note = await context.bot.send_message(
                    target_user_id,
                    f"✅ <b>کانفیگ سفارش شما آماده شد!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"🆔 سفارش: <code>{order_id}</code>\n\n"
                    f"⬇️ کانفیگ در پیام بعدی:",
                    parse_mode=ParseMode.HTML
                )
                await context.bot.copy_message(
                    chat_id=target_user_id,
                    from_chat_id=update.message.chat_id,
                    message_id=update.message.message_id
                )
                await update.message.reply_text(
                    f"✅ کانفیگ برای کاربر <code>{target_user_id}</code> ارسال شد.",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                await update.message.reply_text(
                    f"❌ خطا در ارسال:\n{str(e)[:200]}",
                    parse_mode=ParseMode.HTML
                )

            context.user_data.clear()
            return

        # پاسخ ادمین به کاربر خاص (هر نوع پیام)
        if action == 'reply_user':
            target_user_id = context.user_data.get('reply_user_id')
            try:
                # پیام هدر
                await context.bot.send_message(
                    target_user_id,
                    "📩 <b>پیام از پشتیبانی ربات:</b>",
                    parse_mode=ParseMode.HTML
                )
                # کپی پیام
                await context.bot.copy_message(
                    chat_id=target_user_id,
                    from_chat_id=update.message.chat_id,
                    message_id=update.message.message_id
                )
                await update.message.reply_text(
                    f"✅ پیام برای <code>{target_user_id}</code> ارسال شد.",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                await update.message.reply_text(
                    f"❌ خطا در ارسال:\n{str(e)[:200]}",
                    parse_mode=ParseMode.HTML
                )
            context.user_data.clear()
            return

        # ارسال پیام به کاربر خاص از پنل ادمین (هر نوع پیام)
        if action == 'send_to_user_msg':
            target_id = context.user_data.get('send_target_id')
            try:
                await context.bot.send_message(
                    target_id,
                    "📩 <b>پیام از پشتیبانی ربات:</b>",
                    parse_mode=ParseMode.HTML
                )
                await context.bot.copy_message(
                    chat_id=target_id,
                    from_chat_id=update.message.chat_id,
                    message_id=update.message.message_id
                )
                await update.message.reply_text(
                    f"✅ پیام برای <code>{target_id}</code> ارسال شد.",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                await update.message.reply_text(f"❌ خطا:\n{str(e)[:200]}")
            context.user_data.clear()
            return

    # از اینجا فقط متن پردازش می‌شود
    text = update.message.text.strip() if update.message.text else ""
    if not text:
        return

    # دستور لغو
    if text.lower() in ['/cancel', 'لغو', 'cancel']:
        context.user_data.clear()
        await update.message.reply_text("✅ لغو شد.")
        return

    # کپچای زیرمجموعه
    if 'captcha_ans' in context.user_data:
        try:
            answer = int(text)
        except Exception:
            await update.message.reply_text("❌ فقط عدد بفرستید!")
            return

        correct = context.user_data.get('captcha_ans')
        if answer != correct:
            q_text, ans = generate_captcha()
            context.user_data['captcha_ans'] = ans
            await update.message.reply_text(
                f"❌ <b>پاسخ اشتباه!</b>\n\n❓ سوال جدید: <code>{q_text}</code> = ?",
                parse_mode=ParseMode.HTML
            )
            return

        joined = await check_force_join(user.id, context)
        if not joined:
            await update.message.reply_text(
                f"📢 <b>ابتدا در کانال‌ها عضو شوید:</b>\n\n"
                f"روی هر کانال کلیک کنید تا وارد شوید.",
                parse_mode=ParseMode.HTML,
                reply_markup=get_force_join_keyboard("check_join_ref")
            )
            return

        referrer_id = context.user_data.get('pending_ref', 0)
        if referrer_id > 0:
            db.add_referral(referrer_id)
            db.add_dark_points(referrer_id, REFERRAL_REWARD)
            try:
                await context.bot.send_message(
                    referrer_id,
                    f"🎉 <b>زیرمجموعه جدید!</b>\n\n💰 +{format_number(REFERRAL_REWARD)} DP دریافت کردید!",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass

        context.user_data.pop('captcha_ans', None)
        context.user_data.pop('pending_ref', None)

        await update.message.reply_text("✅ <b>تایید هویت موفق!</b>", parse_mode=ParseMode.HTML)
        await show_main_menu(update, context)
        return

    # اقدامات متنی ادمین
    if is_admin(user.id) and 'admin_action' in context.user_data:
        await handle_admin_text(update, context)
        return

    # شماره کارت بانک
    if context.user_data.get('awaiting_bank_card'):
        if len(text) != 13 or not text.isdigit():
            await update.message.reply_text("❌ باید ۱۳ رقم انگلیسی باشد!")
            return

        if db.card_exists(text):
            await update.message.reply_text("❌ این کارت قبلاً ثبت شده!")
            return

        if not db.remove_dark_points(user.id, BANK_OPEN_COST):
            await update.message.reply_text("❌ موجودی ناکافی!")
            context.user_data.pop('awaiting_bank_card', None)
            return

        db.open_bank_account(user.id, text)
        context.user_data.pop('awaiting_bank_card', None)

        await update.message.reply_text(
            f"✅ <b>حساب بانک دارکی افتتاح شد!</b>\n\n"
            f"💳 شماره کارت: <code>{text}</code>\n"
            f"💵 هزینه: <code>{format_number(BANK_OPEN_COST)}</code> DP",
            parse_mode=ParseMode.HTML
        )
        return

    # واریز به بانک
    if context.user_data.get('awaiting_bank_deposit'):
        try:
            amount = int(text)
            if amount <= 0:
                await update.message.reply_text("❌ مبلغ نامعتبر!")
                return
            if db.bank_deposit(user.id, amount):
                context.user_data.pop('awaiting_bank_deposit', None)
                await update.message.reply_text(
                    f"✅ <b>واریز موفق!</b>\n\n"
                    f"💰 مبلغ: <code>{format_number(amount)}</code> DP\n"
                    f"📈 سود ۱۰٪ بعد از ۲۴ ساعت\n"
                    f"💎 موجودی: <code>{format_number(db.get_balance(user.id))}</code> DP",
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text("❌ موجودی ناکافی!")
        except Exception:
            await update.message.reply_text("❌ فقط عدد بفرستید!")
        return

    # مقصد استارز
    if context.user_data.get('awaiting_stars_target'):
        target = text.strip().replace("@", "")
        stars_price = int(db.get_setting('stars_price', '1000000'))

        if not db.remove_dark_points(user.id, stars_price):
            await update.message.reply_text("❌ موجودی ناکافی!")
            context.user_data.pop('awaiting_stars_target', None)
            return

        order_id = db.create_stars_order(user.id, target, 'other', STARS_AMOUNT, stars_price)
        context.user_data.pop('awaiting_stars_target', None)

        await update.message.reply_text(
            f"✅ <b>سفارش استارز ثبت شد!</b>\n\n"
            f"⭐ تعداد: {STARS_AMOUNT} استارز\n"
            f"👤 مقصد: <code>{target}</code>\n"
            f"💵 هزینه: <code>{format_number(stars_price)}</code> DP",
            parse_mode=ParseMode.HTML
        )

        global BOT_USERNAME
        if not BOT_USERNAME:
            me = await context.bot.get_me()
            BOT_USERNAME = me.username

        user_display = f"@{user.username}" if user.username else f"<code>{user.id}</code>"
        log_kb = [[InlineKeyboardButton("🤖 ورود به ربات", url=f"https://t.me/{BOT_USERNAME}")]]
        await send_log(context,
            f"⭐ <b>سفارش استارز - اکانت دیگه</b>\n\n"
            f"👤 سفارش‌دهنده: {user_display}\n"
            f"🆔 <code>{user.id}</code>\n"
            f"📍 مقصد: <code>{target}</code>\n"
            f"⭐ {STARS_AMOUNT} استارز\n"
            f"💵 <code>{format_number(stars_price)}</code> DP\n"
            f"🆔 سفارش: <code>{order_id}</code>",
            reply_markup=InlineKeyboardMarkup(log_kb)
        )

        for admin_id in ADMIN_IDS:
            try:
                admin_kb = [
                    [InlineKeyboardButton("💬 پاسخ به کاربر", callback_data=f"admin_reply_{user.id}")],
                    [InlineKeyboardButton("✅ تیک تایید سفارش", callback_data=f"admin_confirm_stars_{order_id}")]
                ]
                await context.bot.send_message(
                    admin_id,
                    f"⭐ <b>سفارش استارز - اکانت دیگه</b>\n\n"
                    f"👤 {user_display}\n"
                    f"🆔 <code>{user.id}</code>\n"
                    f"📍 مقصد: <code>{target}</code>\n"
                    f"⭐ {STARS_AMOUNT}",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(admin_kb)
                )
            except Exception:
                pass
        return


# ============ MAIN CALLBACK ROUTER ============

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    # منوهای اصلی
    if data == "main_menu":
        await show_main_menu(update, context, query=query)
    elif data == "dark_point_menu":
        await dark_point_menu(update, context)
    elif data.startswith("dp_info_"):
        await dp_info_page(update, context)
    elif data == "referral_menu":
        await referral_menu(update, context)

    # استارز
    elif data == "stars_withdraw":
        await stars_withdraw_menu(update, context)
    elif data == "stars_do":
        await stars_do(update, context)
    elif data == "stars_self":
        await stars_self_cb(update, context)
    elif data == "stars_other":
        await stars_other_cb(update, context)

    # گیفت
    elif data == "free_gift":
        await free_gift_menu(update, context)
    elif data == "order_gift_teddy":
        await order_gift_teddy(update, context)
    elif data.startswith("order_gift_custom_"):
        await order_gift_custom(update, context)

    # سایر
    elif data == "buy_dp":
        await buy_dp_menu(update, context)
    elif data == "leaderboard":
        await leaderboard_menu(update, context)
    elif data == "like_challenge":
        await like_challenge_menu(update, context)
    elif data == "like_activate":
        await like_activate_cb(update, context)
    elif data == "buy_panel":
        await buy_panel_menu(update, context)
    elif data.startswith("panel_buy_"):
        await panel_buy_cb(update, context)

    # بازی
    elif data.startswith("join_game_"):
        await join_game_callback(update, context)
    elif data.startswith("cancel_game_"):
        await cancel_game_callback(update, context)

    # انفجار
    elif data.startswith("crash_out_"):
        await crash_out_callback(update, context)

    # تاس
    elif data.startswith("dice_pick_"):
        await dice_pick_callback(update, context)
    elif data == "dice_roll":
        await dice_roll_callback(update, context)
    elif data == "dice_cancel":
        await dice_cancel_callback(update, context)

    # بانک
    elif data == "bank_open":
        await bank_open_cb(update, context)
    elif data == "bank_auto_card":
        await bank_auto_card_cb(update, context)
    elif data == "bank_custom_card":
        await bank_custom_card_cb(update, context)
    elif data == "bank_deposit":
        await bank_deposit_cb(update, context)
    elif data == "bank_withdraw":
        await bank_withdraw_cb(update, context)
    elif data == "bank_wait":
        await bank_wait_cb(update, context)

    # کارخونه
    elif data == "factory_open":
        await factory_open_cb(update, context)
    elif data == "factory_upgrade":
        await factory_upgrade_cb(update, context)
    elif data == "factory_collect":
        await factory_collect_cb(update, context)

    # جوین اجباری
    elif data == "check_join_main":
        await check_join_main(update, context)
    elif data == "check_join_ref":
        await check_join_ref_cb(update, context)

    # ادمین: کالبک‌های ویژه
    elif data.startswith("admin_send_config_"):
        await admin_send_config_cb(update, context)
    elif data.startswith("admin_reply_"):
        await admin_reply_cb(update, context)
    elif data.startswith("admin_confirm_stars_"):
        await admin_confirm_stars_cb(update, context)
    elif data.startswith("admin_confirm_gift_"):
        await admin_confirm_gift_cb(update, context)

    # ادمین - همه دکمه‌های پنل
    elif data.startswith("adm_"):
        await admin_callbacks(update, context)


# ============ PERIODIC MAINTENANCE ============

async def periodic_maintenance(context: ContextTypes.DEFAULT_TYPE):
    """نگهداری خودکار کارخونه"""
    try:
        conn = db.get_conn()
        c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE factory_active = 1")
        rows = c.fetchall()
        conn.close()
        for row in rows:
            try:
                db.factory_maintenance_due(row['user_id'])
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Maintenance error: {e}")


# ============ ERROR HANDLER ============

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception:", exc_info=context.error)


# ============ CANCEL COMMAND ============

async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ همه عملیات‌ها لغو شد.")


# ============ MAIN ============

def main():
    start_health_server()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_error_handler(error_handler)

    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("cancel", cancel_cmd))

    # Callbacks
    application.add_handler(CallbackQueryHandler(callback_router))

    # Group messages
    application.add_handler(MessageHandler(
        filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
        handle_group_message
    ))

    # Private messages (پشتیبانی از همه نوع پیام برای ادمین)
    application.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & ~filters.COMMAND,
        handle_private_message
    ))

    # New chat members
    application.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS,
        on_new_chat_members
    ))

    # Jobs
    application.job_queue.run_repeating(periodic_maintenance, interval=300, first=30)
    application.job_queue.run_repeating(self_ping, interval=480, first=60)

    print("🏴 Dark Point Bot is fully running with all features!")
    logger.info("Bot started successfully")

    application.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
