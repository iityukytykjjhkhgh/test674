# bot.py - Dark Point Bot Ultimate Version

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

def get_referral_reward():
    """گرفتن پاداش زیرمجموعه از دیتابیس"""
    return int(db.get_setting('referral_reward', str(DEFAULT_REFERRAL_REWARD)))

def get_first_join_reward():
    return int(db.get_setting('first_join_reward', str(FIRST_JOIN_REWARD)))

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
        username = ch['channel_username'].replace('@', '')
        title = ch['channel_title'] or ch['channel_username']
        kb.append([InlineKeyboardButton(f"📢 {title}", url=f"https://t.me/{username}")])
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

# ============ KEEP-ALIVE ============

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

# ============ START & MENU ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    if db.is_banned(user.id):
        await update.message.reply_text("❌ حساب شما مسدود شده است.")
        return

    args = context.args
    existing = db.get_user(user.id)
    is_new_user = not existing

    if is_new_user:
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

    # بررسی جوین اجباری
    joined = await check_force_join(user.id, context)
    if not joined:
        await update.message.reply_text(
            f"📢 <b>عضویت اجباری در کانال‌ها</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"برای استفاده از ربات ابتدا در کانال‌های زیر عضو شوید:\n\n"
            f"💡 <i>روی هر کانال کلیک کنید</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_force_join_keyboard("check_join_main")
        )
        return

    # هدیه اولین ورود
    u = db.get_user(user.id)
    if u and not u['first_reward_claimed']:
        reward = db.claim_first_reward(user.id)
        if reward:
            await update.message.reply_text(
                f"🎉 🎊 <b>خوش‌آمدید به دنیای دارک پوینت!</b> 🎊 🎉\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"🎁 <b>هدیه ثبت‌نام:</b>\n"
                f"💰 +<code>{format_number(reward)}</code> دارک پوینت\n\n"
                f"✅ به کیف پول شما اضافه شد!\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💎 موجودی: <code>{format_number(db.get_balance(user.id))}</code> DP",
                parse_mode=ParseMode.HTML
            )
            await asyncio.sleep(1)

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
            InlineKeyboardButton("📋 انجام تسک", callback_data="tasks_menu"),
            InlineKeyboardButton("❤️ چالش لایکی", callback_data="like_challenge"),
        ],
        [
            InlineKeyboardButton("👥 زیرمجموعه‌گیری", callback_data="referral_menu"),
            InlineKeyboardButton("🏆 لیدربورد", callback_data="leaderboard"),
        ],
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
        f"🎮 <i>بازی‌های گروهی:</i>\n"
        f"💥 انفجار | 🎲 تاس | 🎯 حدس بزن\n"
        f"🎰 کازینو | 💣 بمب"
    )

    if query:
        try:
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception:
            await query.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))


async def check_join_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()
    joined = await check_force_join(user.id, context)
    if not joined:
        await query.answer("❌ هنوز عضو همه کانال‌ها نشده‌اید!", show_alert=True)
        return

    # هدیه اولین ورود اگر نگرفته
    u = db.get_user(user.id)
    if u and not u['first_reward_claimed']:
        reward = db.claim_first_reward(user.id)
        if reward:
            await context.bot.send_message(
                user.id,
                f"🎉 <b>خوش‌آمدید!</b>\n\n🎁 هدیه ثبت‌نام:\n💰 +<code>{format_number(reward)}</code> DP",
                parse_mode=ParseMode.HTML
            )

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
        ref_reward = get_referral_reward()
        db.add_dark_points(referrer_id, ref_reward)
        try:
            await context.bot.send_message(
                referrer_id,
                f"🎉 <b>زیرمجموعه جدید!</b>\n💰 +{format_number(ref_reward)} DP!",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass

    context.user_data.pop('captcha_ans', None)
    context.user_data.pop('pending_ref', None)

    # هدیه اولین ورود
    u = db.get_user(user.id)
    if u and not u['first_reward_claimed']:
        reward = db.claim_first_reward(user.id)
        if reward:
            await context.bot.send_message(
                user.id,
                f"🎉 <b>خوش‌آمدید!</b>\n\n🎁 هدیه ثبت‌نام:\n💰 +<code>{format_number(reward)}</code> DP",
                parse_mode=ParseMode.HTML
            )

    await show_main_menu(update, context, query=query)# ============ DARK POINT MENU + WHEEL ============

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
        [InlineKeyboardButton("🎡 گردونه شانس", callback_data="wheel_menu")],
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
        f"━━━━━━━━━━━━━━━━━━"
    )

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))


# ============ WHEEL OF FORTUNE ============

async def wheel_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if db.get_setting('wheel_active', '1') != '1':
        await query.answer("❌ این بخش موقتاً غیرفعال می‌باشد.", show_alert=True)
        return

    can_free, remaining = db.can_spin_wheel_free(user.id)
    balance = db.get_balance(user.id)

    text = (
        f"🎡 <b>گردونه شانس دارکی</b> 🎡\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💎 موجودی: <code>{format_number(balance)}</code> DP\n\n"
        f"🎁 <b>جوایز گردونه:</b>\n"
        f"💰 بین <code>{format_number(WHEEL_MIN_PRIZE)}</code> تا <code>{format_number(WHEEL_MAX_PRIZE)}</code> DP\n\n"
        f"⏰ چرخش رایگان: <b>هر ۲۴ ساعت یکبار</b>\n"
        f"💵 چرخش اضافی: <code>{format_number(WHEEL_EXTRA_COST)}</code> DP\n"
        f"━━━━━━━━━━━━━━━━━━\n"
    )

    buttons = []
    if can_free:
        buttons.append([InlineKeyboardButton("🎡 چرخش رایگان!", callback_data="wheel_spin_free")])
        text += "✅ <b>شما یک چرخش رایگان دارید!</b>"
    else:
        hours = int(remaining // 3600)
        mins = int((remaining % 3600) // 60)
        text += f"⏰ چرخش رایگان بعدی: <b>{hours}h {mins}m</b>"
        buttons.append([InlineKeyboardButton(f"💵 چرخش اضافی ({format_number(WHEEL_EXTRA_COST)} DP)", callback_data="wheel_spin_paid")])

    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="dark_point_menu")])
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))


async def wheel_spin_free_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    can_free, _ = db.can_spin_wheel_free(user.id)
    if not can_free:
        await query.answer("❌ چرخش رایگان شما تمام شده!", show_alert=True)
        return

    prize = random.randint(WHEEL_MIN_PRIZE, WHEEL_MAX_PRIZE)
    db.add_dark_points(user.id, prize)
    db.set_wheel_spin_time(user.id)

    await query.answer("🎡 در حال چرخش...")
    await asyncio.sleep(1)

    await query.edit_message_text(
        f"🎡 <b>گردونه شانس چرخید!</b> 🎡\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎉 <b>تبریک! برنده شدید!</b>\n\n"
        f"💰 جایزه: +<code>{format_number(prize)}</code> DP\n"
        f"💎 موجودی جدید: <code>{format_number(db.get_balance(user.id))}</code> DP\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⏰ چرخش رایگان بعدی: <b>۲۴ ساعت دیگر</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="dark_point_menu")]])
    )


async def wheel_spin_paid_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if not db.remove_dark_points(user.id, WHEEL_EXTRA_COST):
        await query.answer(f"❌ نیاز به {format_number(WHEEL_EXTRA_COST)} DP دارید!", show_alert=True)
        return

    prize = random.randint(WHEEL_MIN_PRIZE, WHEEL_MAX_PRIZE)
    db.add_dark_points(user.id, prize)

    await query.answer("🎡 در حال چرخش...")
    await asyncio.sleep(1)

    net_profit = prize - WHEEL_EXTRA_COST

    await query.edit_message_text(
        f"🎡 <b>گردونه شانس چرخید!</b> 🎡\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎉 جایزه: <code>{format_number(prize)}</code> DP\n"
        f"💵 هزینه چرخش: -<code>{format_number(WHEEL_EXTRA_COST)}</code> DP\n"
        f"📊 سود خالص: <code>{format_number(net_profit)}</code> DP\n\n"
        f"💎 موجودی: <code>{format_number(db.get_balance(user.id))}</code> DP",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="dark_point_menu")]])
    )


# ============ INFO PAGES ============

INFO_PAGES = {
    1: (
        "📖 <b>دارک پوینت - صفحه ۱/۱۰</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🏴 <b>دارک پوینت چیست؟</b>\n\n"
        "واحد پولی اختصاصی ربات که با آن می‌توانید:\n\n"
        "⭐ استارز تلگرام برداشت کنید\n"
        "🛒 پنل VPN خریداری کنید\n"
        "🎁 گیفت تدی بگیرید\n"
        "🎮 بازی‌های مختلف کنید\n"
        "🏭 کارخونه بسازید\n"
        "🏦 در بانک سرمایه‌گذاری کنید\n"
        "🎡 گردونه شانس بچرخانید\n\n"
        "⭐ <b>هر ۱ میلیون DP = ۵۰ استارز</b>"
    ),
    2: (
        "📖 <b>دارک پوینت - صفحه ۲/۱۰</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "💰 <b>راه‌های کسب DP:</b>\n\n"
        "1️⃣ کلمه دارک در گروه: <code>دارک</code>\n"
        "2️⃣ زیرمجموعه‌گیری\n"
        "3️⃣ کارخونه دارکی\n"
        "4️⃣ بانک دارکی (سود ۱۵٪)\n"
        "5️⃣ بازی‌های شانسی\n"
        "6️⃣ گردونه شانس روزانه (رایگان)\n"
        "7️⃣ انجام تسک‌ها\n"
        "8️⃣ هدیه اولیه ثبت‌نام"
    ),
    3: (
        "📖 <b>دارک پوینت - صفحه ۳/۱۰</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "📊 <b>سیستم ۲۰ سطحی:</b>\n\n"
        "سطح ۱: 0 DP 🌑\n"
        "سطح ۵: 150K DP 🌕\n"
        "سطح ۱۰: 1M DP 🥈\n"
        "سطح ۱۵: 3M DP 🔮\n"
        "سطح ۲۰: 20M DP 🏴\n\n"
        "🎁 هر سطح جایزه ارتقا دارد!"
    ),
    4: (
        "📖 <b>دارک پوینت - صفحه ۴/۱۰</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🏭 <b>کارخونه دارکی:</b>\n"
        "افتتاح: ۱۰۰,۰۰۰ DP\n"
        "نگهداری: ساعتی ۸۰ DP\n\n"
        "سطح ۱: ۱۰ DP/دقیقه\n"
        "سطح ۵: ۱۰۰ DP/دقیقه\n\n"
        "🏦 <b>بانک دارکی:</b>\n"
        "افتتاح: ۲۰,۰۰۰ DP\n"
        "سود ۲۴ ساعته: <b>۱۵٪</b>"
    ),
    5: (
        "📖 <b>دارک پوینت - صفحه ۵/۱۰</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "💥 <b>بازی انفجار (گروه):</b>\n"
        "<code>انفجار 1000</code>\n"
        "ضریب رشد + Cash Out\n\n"
        "🎲 <b>بازی تاس (گروه):</b>\n"
        "<code>تاس 15000</code>\n"
        "۱ عدد: ۶x | ۲ عدد: ۳x | ۳ عدد: ۱.۵x"
    ),
    6: (
        "📖 <b>دارک پوینت - صفحه ۶/۱۰</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🎯 <b>بازی حدس بزن (گروه):</b>\n"
        "کلمه: <code>حدس بزن</code>\n"
        "حداقل: ۳۰,۰۰۰ DP\n\n"
        "۱ عدد از ۱۰: <b>۱۰x</b>\n"
        "۲ عدد: <b>۵x</b>\n"
        "۳ عدد: <b>۲.۵x</b>\n"
        "۴ عدد: <b>۱.۲x</b>"
    ),
    7: (
        "📖 <b>دارک پوینت - صفحه ۷/۱۰</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🎰 <b>بازی کازینو (گروه):</b>\n"
        "کلمه: <code>کازینو</code>\n"
        "حداقل شرط: ۲۵,۰۰۰ DP\n\n"
        "۳ تا ۷: <b>۱۵ برابر</b>\n"
        "۷ و لیمو: <b>۱۲ برابر</b>\n"
        "۷ و لیمو و انگور: <b>۷ برابر</b>"
    ),
    8: (
        "📖 <b>دارک پوینت - صفحه ۸/۱۰</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "💣 <b>بازی بمب (گروه):</b>\n"
        "کلمه: <code>بمب</code>\n"
        "حداقل شرط: ۳۵,۰۰۰ DP\n\n"
        "شبکه ۴×۴ با ۴ بمب\n"
        "هر خانه امن: <b>+۱.۸x ضریب</b>\n"
        "بمب: <b>باخت کامل</b>\n\n"
        "امکان برداشت زودهنگام"
    ),
    9: (
        "📖 <b>دارک پوینت - صفحه ۹/۱۰</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🎡 <b>گردونه شانس:</b>\n"
        "چرخش رایگان روزانه\n"
        "جایزه: ۵ تا ۱۰۰ هزار DP\n\n"
        "💸 <b>انتقال DP:</b>\n"
        "<code>انتقال 1000</code> (ریپلای)\n"
        "کارمزد: ۱۰٪"
    ),
    10: (
        "📖 <b>دارک پوینت - صفحه ۱۰/۱۰</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "⭐ <b>برداشت استارز:</b>\n"
        "هر ۱M DP = ۵۰ استارز\n\n"
        "🎁 <b>گیفت تدی:</b>\n"
        "قابل خرید با DP\n\n"
        "📋 <b>تسک‌ها:</b>\n"
        "با انجام تسک DP بگیرید\n\n"
        "📝 <b>دستورات گروه:</b>\n"
        "دارک | موجودی | پروفایل دارکی\n"
        "بازی | انفجار | تاس | حدس بزن\n"
        "کازینو | بمب | انتقال\n"
        "بانک دارکی | کارخونه دارکی"
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
    if page < 10:
        buttons.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"dp_info_{page+1}"))

    keyboard = [buttons] if buttons else []
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="dark_point_menu")])

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))


# ============ TASKS MENU ============

async def tasks_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if db.get_setting('tasks_active', '1') != '1':
        await query.answer("❌ این بخش موقتاً غیرفعال می‌باشد.", show_alert=True)
        return

    tasks = db.get_tasks(only_active=True)
    text = (
        f"📋 <b>انجام تسک و کسب DP</b> 📋\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
    )

    if not tasks:
        text += "❌ هیچ تسکی موجود نیست.\n\n<i>بزودی تسک‌های جدید اضافه می‌شود!</i>"
        kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))
        return

    text += "با عضویت در کانال‌های زیر و تایید عضویت، پاداش دریافت کنید:\n\n"

    kb = []
    for task in tasks:
        completed = db.is_task_completed(user.id, task['task_id'])
        status = "✅ انجام شده" if completed else f"💰 {format_number(task['reward'])} DP"
        kb.append([InlineKeyboardButton(
            f"📢 {task['channel_title']} - {status}",
            callback_data=f"task_view_{task['task_id']}"
        )])

    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def task_view_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    task_id = int(query.data.split("_")[-1])

    task = db.get_task(task_id)
    if not task:
        await query.answer("❌ تسک یافت نشد!", show_alert=True)
        return

    if db.is_task_completed(user.id, task_id):
        await query.answer("✅ این تسک را قبلاً انجام داده‌اید!", show_alert=True)
        return

    await query.answer()
    username = task['channel_username'].replace('@', '')

    text = (
        f"📋 <b>تسک: عضویت در کانال</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📢 کانال: {task['channel_title']}\n"
        f"🔗 آدرس: {task['channel_username']}\n"
        f"💰 پاداش: <code>{format_number(task['reward'])}</code> DP\n\n"
        f"1️⃣ روی دکمه زیر کلیک کنید\n"
        f"2️⃣ در کانال عضو شوید\n"
        f"3️⃣ دکمه «بررسی و دریافت» را بزنید"
    )

    kb = [
        [InlineKeyboardButton(f"📢 عضویت در {task['channel_title']}", url=f"https://t.me/{username}")],
        [InlineKeyboardButton("✅ بررسی و دریافت پاداش", callback_data=f"task_verify_{task_id}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="tasks_menu")],
    ]

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def task_verify_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    task_id = int(query.data.split("_")[-1])

    task = db.get_task(task_id)
    if not task:
        await query.answer("❌ تسک یافت نشد!", show_alert=True)
        return

    if db.is_task_completed(user.id, task_id):
        await query.answer("✅ قبلاً دریافت شده!", show_alert=True)
        return

    # بررسی عضویت در کانال
    try:
        member = await context.bot.get_chat_member(task['channel_username'], user.id)
        if member.status in ['left', 'kicked']:
            await query.answer("❌ هنوز عضو کانال نشده‌اید!", show_alert=True)
            return
    except Exception:
        await query.answer("❌ خطا در بررسی عضویت! مطمئن شوید ربات ادمین کانال است.", show_alert=True)
        return

    # پاداش
    db.add_dark_points(user.id, task['reward'])
    db.mark_task_completed(user.id, task_id)

    await query.answer(f"✅ +{format_number(task['reward'])} DP دریافت شد!", show_alert=True)
    await query.edit_message_text(
        f"✅ <b>تسک با موفقیت انجام شد!</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📢 کانال: {task['channel_title']}\n"
        f"💰 پاداش: +<code>{format_number(task['reward'])}</code> DP\n"
        f"💎 موجودی: <code>{format_number(db.get_balance(user.id))}</code> DP",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لیست تسک‌ها", callback_data="tasks_menu")]])
    )


# ============ STARS ============

async def stars_withdraw_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if db.get_setting('stars_section_active', '1') != '1':
        await query.answer("❌ این بخش موقتاً غیرفعال می‌باشد.", show_alert=True)
        return

    stars_price = int(db.get_setting('stars_price', '1000000'))
    balance = db.get_balance(user.id)
    can_withdraw = balance >= stars_price

    text = (
        f"⭐ <b>برداشت استارز تلگرام</b> ⭐\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💎 موجودی: <code>{format_number(balance)}</code> DP\n"
        f"⭐ نرخ: <code>{format_number(stars_price)}</code> DP = {STARS_AMOUNT} استارز\n\n"
    )

    if can_withdraw:
        text += f"✅ می‌توانید {STARS_AMOUNT} استارز برداشت کنید!"
        kb = [
            [InlineKeyboardButton(f"⭐ برداشت {STARS_AMOUNT} استارز", callback_data="stars_do")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
        ]
    else:
        needed = stars_price - balance
        text += f"❌ نیاز: <code>{format_number(needed)}</code> DP بیشتر"
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
        f"⭐ <b>برداشت {STARS_AMOUNT} استارز</b>\n\nبرای کدام اکانت؟",
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
        f"⭐ تعداد: {STARS_AMOUNT}\n"
        f"👤 مقصد: <code>{user.id}</code>\n"
        f"⏳ <i>بزودی واریز می‌شود</i>",
        parse_mode=ParseMode.HTML
    )

    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await context.bot.get_me()
        BOT_USERNAME = me.username

    user_display = f"@{user.username}" if user.username else f"<code>{user.id}</code>"
    log_kb = [[InlineKeyboardButton("🤖 ورود به ربات", url=f"https://t.me/{BOT_USERNAME}")]]
    await send_log(context,
        f"⭐ <b>سفارش برداشت استارز</b>\n\n"
        f"👤 {user_display}\n"
        f"🆔 <code>{user.id}</code>\n"
        f"⭐ {STARS_AMOUNT} استارز\n"
        f"📍 مقصد: <code>{user.id}</code>\n"
        f"💵 <code>{format_number(stars_price)}</code> DP\n"
        f"🆔 سفارش: <code>{order_id}</code>",
        reply_markup=InlineKeyboardMarkup(log_kb)
    )

    for admin_id in ADMIN_IDS:
        try:
            admin_kb = [
                [InlineKeyboardButton("💬 پاسخ به کاربر", callback_data=f"admin_reply_{user.id}")],
                [InlineKeyboardButton("✅ تایید سفارش", callback_data=f"admin_confirm_stars_{order_id}")]
            ]
            await context.bot.send_message(
                admin_id,
                f"⭐ سفارش استارز\n👤 {user_display}\n🆔 <code>{user.id}</code>",
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
        "👥 آیدی اکانت مقصد را بفرستید (@username یا شماره):",
        parse_mode=ParseMode.HTML
    )


# ============ FREE GIFT ============

async def free_gift_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if db.get_setting('gift_section_active', '1') != '1':
        await query.answer("❌ این بخش موقتاً غیرفعال می‌باشد.", show_alert=True)
        return

    gift_price = int(db.get_setting('gift_teddy_price', '750000'))
    balance = db.get_balance(user.id)

    conn = db.get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM settings WHERE key LIKE 'gift_plan_%_name'")
    plans = c.fetchall()
    conn.close()

    text = (
        f"🎁 <b>گیفت رایگان تدی</b> 🎁\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🧸 گیفت تدی تلگرام\n"
        f"💰 قیمت: <code>{format_number(gift_price)}</code> DP\n"
        f"💎 موجودی: <code>{format_number(balance)}</code> DP"
    )

    buttons = []
    if balance >= gift_price:
        buttons.append([InlineKeyboardButton("🧸 سفارش گیفت تدی", callback_data="order_gift_teddy")])

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
        f"✅ <b>سفارش گیفت تدی ثبت شد!</b>\n🆔 <code>{order_id}</code>",
        parse_mode=ParseMode.HTML
    )

    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await context.bot.get_me()
        BOT_USERNAME = me.username

    user_display = f"@{user.username}" if user.username else f"<code>{user.id}</code>"
    log_kb = [[InlineKeyboardButton("🤖 ورود به ربات", url=f"https://t.me/{BOT_USERNAME}")]]
    await send_log(context,
        f"🧸 <b>سفارش گیفت تدی</b>\n\n👤 {user_display}\n🆔 <code>{user.id}</code>\n💵 <code>{format_number(gift_price)}</code>",
        reply_markup=InlineKeyboardMarkup(log_kb)
    )

    for admin_id in ADMIN_IDS:
        try:
            admin_kb = [[InlineKeyboardButton("💬 پاسخ به کاربر", callback_data=f"admin_reply_{user.id}")]]
            await context.bot.send_message(
                admin_id,
                f"🧸 سفارش گیفت\n👤 {user_display}\n🆔 <code>{user.id}</code>",
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
        f"✅ سفارش ثبت شد!\n🎁 {name}\n🆔 <code>{order_id}</code>",
        parse_mode=ParseMode.HTML
    )

    user_display = f"@{user.username}" if user.username else f"<code>{user.id}</code>"
    for admin_id in ADMIN_IDS:
        try:
            admin_kb = [[InlineKeyboardButton("💬 پاسخ به کاربر", callback_data=f"admin_reply_{user.id}")]]
            await context.bot.send_message(
                admin_id,
                f"🎁 {name}\n👤 {user_display}",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(admin_kb)
            )
        except Exception:
            pass


# ============ BUY DP ============

async def buy_dp_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if db.get_setting('buy_dp_active', '1') != '1':
        await query.answer("❌ این بخش موقتاً غیرفعال می‌باشد.", show_alert=True)
        return

    dp_amount = int(db.get_setting('buy_dp_amount', '500000'))
    price_toman = int(db.get_setting('buy_dp_price_toman', '50000'))

    text = (
        f"💰 <b>خرید دارک پوینت</b> 💰\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💎 هر <code>{format_number(dp_amount)}</code> DP\n"
        f"💵 قیمت: <code>{format_number(price_toman)}</code> تومان\n\n"
        f"📩 برای خرید به پشتیبانی پیام دهید."
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
    text = "🏆 <b>لیدربورد دارک پوینت</b> 🏆\n━━━━━━━━━━━━━━━━━━\n\n"
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, row in enumerate(rows[:25], 1):
        medal = medals.get(i, f"{i}.")
        name = html.escape(row['first_name'] or row['username'] or str(row['user_id']))
        text += f"{medal} <b>{name}</b> - <code>{format_number(row['dark_points'])}</code> DP\n"

    if len(rows) > 25:
        text += f"\n<i>... و {len(rows) - 25} نفر دیگر</i>"

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
    ref_reward = get_referral_reward()

    text = (
        f"👥 <b>زیرمجموعه‌گیری</b> 👥\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🔗 لینک شما:\n<code>{ref_link}</code>\n\n"
        f"👥 زیرمجموعه‌ها: <b>{ref_count}</b>\n"
        f"💰 پاداش هر زیرمجموعه: <b>{format_number(ref_reward)}</b> DP\n"
        f"💎 کل درآمد: <code>{format_number(ref_count * ref_reward)}</code> DP\n\n"
        f"📋 <b>شرایط:</b>\n"
        f"• حل کپچا ✅\n"
        f"• عضویت در کانال‌ها ✅"
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
        text = f"❤️ <b>چالش لایکی فعال</b> ❤️\n\n⏰ باقیمانده: {days} روز و {hours} ساعت"
        kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
    else:
        text = (
            f"❤️ <b>چالش لایکی ۷ روزه</b>\n"
            f"💵 هزینه: {format_number(LIKE_CHALLENGE_COST)} DP\n"
            f"💎 موجودی: <code>{format_number(db.get_balance(user.id))}</code>"
        )
        kb = [
            [InlineKeyboardButton(f"✅ فعال‌سازی ({format_number(LIKE_CHALLENGE_COST)})", callback_data="like_activate")],
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

    db.update_user(user.id, like_challenge_active=1, like_challenge_until=time.time() + (7 * 86400))
    await query.edit_message_text(
        f"✅ چالش لایکی ۷ روزه فعال شد!",
        parse_mode=ParseMode.HTML
    )


# ============ BUY PANEL ============

async def buy_panel_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

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
            await query.answer("❌ یافت نشد!", show_alert=True)
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
        f"🆔 سفارش: <code>{order_id}</code>\n\n"
        f"⏳ <i>کانفیگ توسط ادمین بزودی ارسال می‌شود</i>",
        parse_mode=ParseMode.HTML
    )

    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await context.bot.get_me()
        BOT_USERNAME = me.username

    user_display = f"@{user.username}" if user.username else f"<code>{user.id}</code>"
    log_kb = [[InlineKeyboardButton("🤖 ورود به ربات", url=f"https://t.me/{BOT_USERNAME}")]]
    await send_log(context,
        f"🛒 <b>سفارش پنل جدید</b>\n\n"
        f"👤 {user_display}\n"
        f"🆔 <code>{user.id}</code>\n"
        f"📦 <b>{name}</b> ({data_limit})\n"
        f"💵 <code>{format_number(price)}</code> DP\n"
        f"🆔 <code>{order_id}</code>",
        reply_markup=InlineKeyboardMarkup(log_kb)
    )

    for admin_id in ADMIN_IDS:
        try:
            admin_kb = [
                [InlineKeyboardButton("📤 ارسال کانفیگ", callback_data=f"admin_send_config_{order_id}_{user.id}")],
                [InlineKeyboardButton("💬 پاسخ به کاربر", callback_data=f"admin_reply_{user.id}")]
            ]
            await context.bot.send_message(
                admin_id,
                f"🛒 <b>سفارش پنل جدید</b>\n\n"
                f"👤 {user_display}\n"
                f"🆔 <code>{user.id}</code>\n"
                f"📦 <b>{name}</b> ({data_limit})\n"
                f"💵 <code>{format_number(price)}</code> DP\n"
                f"🆔 سفارش: <code>{order_id}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(admin_kb)
            )
        except Exception:
            pass# ============ GROUP HANDLERS ============

async def on_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            try:
                count = await context.bot.get_chat_member_count(chat.id)
                if count < MIN_GROUP_MEMBERS:
                    await update.message.reply_text(
                        f"❌ <b>گروه باید حداقل {MIN_GROUP_MEMBERS} عضو داشته باشد!</b>\n👥 فعلی: {count}",
                        parse_mode=ParseMode.HTML
                    )
                    await context.bot.leave_chat(chat.id)
                    return
                db.add_group(chat.id, chat.title, count)
                await update.message.reply_text(
                    "🏴 <b>ربات دارک پوینت فعال شد!</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n\n"
                    "📝 <b>دستورات:</b>\n"
                    "• <code>دارک</code> - دریافت DP\n"
                    "• <code>موجودی</code>\n"
                    "• <code>پروفایل دارکی</code>\n"
                    "• <code>بازی 1000</code>\n"
                    "• <code>انفجار 1000</code>\n"
                    "• <code>تاس 15000</code>\n"
                    "• <code>حدس بزن</code>\n"
                    "• <code>کازینو</code>\n"
                    "• <code>بمب</code>\n"
                    "• <code>انتقال 1000</code>\n"
                    "• <code>بانک دارکی</code>\n"
                    "• <code>کارخونه دارکی</code>\n"
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
    elif text == 'حدس بزن' or text.startswith('حدس بزن'):
        await handle_guess_game_start(update, context)
    elif text == 'کازینو' or text.startswith('کازینو'):
        await handle_casino_start(update, context)
    elif text == 'بمب' or text.startswith('بمب'):
        await handle_bomb_start(update, context)
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
            f"⏳ <b>لطفاً صبر کنید!</b>\n\n⏰ <b>{mins}</b> دقیقه و <b>{secs}</b> ثانیه تا دریافت بعدی",
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
            f"\n\n🎊 <b>ارتقا به سطح {new_level}!</b> 🎊\n"
            f"🏅 {get_level_title(new_level)}\n"
            f"🎁 +<code>{format_number(reward)}</code> DP"
        )

    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await context.bot.get_me()
        BOT_USERNAME = me.username

    kb = [[InlineKeyboardButton("🏴 ورود به ربات", url=f"https://t.me/{BOT_USERNAME}")]]
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
        f"👤 <b>{safe_name}</b>\n"
        f"🆔 <code>{user.id}</code>\n\n"
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
    safe_name = html.escape(user.first_name or "کاربر")

    factory_info = ""
    if u['factory_active']:
        f_level = u['factory_level']
        mine_rate = FACTORY_LEVELS[f_level]['mine_per_min']
        factory_info = f"🏭 کارخونه: سطح {f_level} ({mine_rate} DP/دقیقه)\n"
    elif u['factory_level'] > 0:
        factory_info = f"🏭 کارخونه: <b>غیرفعال</b> (سطح {u['factory_level']})\n"

    bank_info = ""
    if u['bank_account']:
        bank_info = f"🏦 کارت: <code>{u['bank_card']}</code>\n💰 بانک: <code>{format_number(u['bank_balance'])}</code>\n"

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
        f"🏴 <b>پروفایل دارکی</b> 🏴\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 نام: <b>{safe_name}</b>\n"
        f"🆔 <code>{user.id}</code>\n"
        f"📛 @{user.username or 'ندارد'}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 موجودی: <code>{format_number(balance)}</code> DP\n"
        f"📊 سطح: {level} | {title}\n"
    )
    if next_req:
        text += f"📈 تا سطح {level+1}: <code>{format_number(needed)}</code>\n"
    else:
        text += f"🏆 بالاترین سطح!\n"

    text += (
        f"📊 کل دریافتی: <code>{format_number(total)}</code>\n"
        f"👥 زیرمجموعه: {refs}\n"
        f"{stars_text}"
        f"{factory_info}"
        f"{bank_info}"
        f"💥 انفجار: {crash_won}/{crash_played} ({win_rate}%)\n"
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
            f"❌ حداقل: <code>{format_number(MIN_GAME_AMOUNT)}</code> DP",
            parse_mode=ParseMode.HTML
        )
        return

    balance = db.get_balance(user.id)
    if balance < amount:
        await update.message.reply_text(
            f"❌ موجودی ناکافی!\n💰 موجودی: <code>{format_number(balance)}</code>",
            parse_mode=ParseMode.HTML
        )
        return

    db.remove_dark_points(user.id, amount)

    msg = await update.message.reply_text(
        f"🎮 <b>بازی جدید!</b>\n\n"
        f"👤 سازنده: {get_user_display(user)}\n"
        f"💰 ورود: <code>{format_number(amount)}</code>\n"
        f"🏆 جایزه: <code>{format_number(amount * 2)}</code>\n\n"
        f"⏳ منتظر حریف...",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎮 پیوستن به بازی", callback_data="join_game_0")],
            [InlineKeyboardButton("❌ لغو", callback_data="cancel_game_0")],
        ])
    )

    game_id = db.create_game(user.id, amount, chat.id, msg.message_id)
    await msg.edit_reply_markup(InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 پیوستن به بازی", callback_data=f"join_game_{game_id}")],
        [InlineKeyboardButton("❌ لغو", callback_data=f"cancel_game_{game_id}")],
    ]))


async def join_game_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    game_id = int(query.data.split("_")[-1])

    game = db.get_game(game_id)
    if not game:
        await query.answer("❌ یافت نشد!", show_alert=True)
        return
    if game['status'] != 'waiting':
        await query.answer("❌ تمام شده!", show_alert=True)
        return
    if user.id == game['creator_id']:
        await query.answer("❌ به بازی خودتان نمی‌توانید!", show_alert=True)
        return

    amount = game['amount']
    if db.get_balance(user.id) < amount:
        await query.answer(f"❌ نیاز: {format_number(amount)}", show_alert=True)
        return

    db.remove_dark_points(user.id, amount)
    db.join_game(game_id, user.id)

    await query.answer("🎮 مشخص کردن برنده...")
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
        f"🎮 <b>نتیجه بازی!</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        f"🏆 برنده: {winner_display}\n"
        f"💰 +<code>{format_number(prize)}</code> DP\n\n"
        f"💔 بازنده: {loser_display}",
        parse_mode=ParseMode.HTML
    )


async def cancel_game_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    game_id = int(query.data.split("_")[-1])

    game = db.get_game(game_id)
    if not game:
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
        f"❌ بازی لغو شد\n💰 <code>{format_number(game['amount'])}</code> DP بازگردانده شد",
        parse_mode=ParseMode.HTML
    )


# ============ TRANSFER ============

async def handle_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()

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
                await update.message.reply_text("❌ به خودتان نمی‌توانید!")
                return
            if db.is_banned(target_id):
                await update.message.reply_text("❌ کاربر مسدود!")
                return

            fee = int(amount * TRANSFER_FEE)
            total_cost = amount + fee
            balance = db.get_balance(user.id)

            if balance < total_cost:
                await update.message.reply_text(
                    f"❌ <b>موجودی ناکافی!</b>\n"
                    f"💰 مبلغ: <code>{format_number(amount)}</code>\n"
                    f"💸 کارمزد: <code>{format_number(fee)}</code>\n"
                    f"📊 کل: <code>{format_number(total_cost)}</code>",
                    parse_mode=ParseMode.HTML
                )
                return

            if not db.remove_dark_points(user.id, total_cost):
                return

            if not db.get_user(target_id):
                target = update.message.reply_to_message.from_user
                db.create_user(target_id, target.username or "", target.first_name or "")

            db.add_dark_points(target_id, amount)
            db.record_transfer(user.id, target_id, amount, fee)

            target = update.message.reply_to_message.from_user
            target_display = f"@{target.username}" if target.username else f"<code>{target.id}</code>"

            await update.message.reply_text(
                f"✅ <b>انتقال موفق!</b>\n\n"
                f"💰 <code>{format_number(amount)}</code>\n"
                f"💸 کارمزد: <code>{format_number(fee)}</code>\n"
                f"👤 مقصد: {target_display}",
                parse_mode=ParseMode.HTML
            )
            try:
                await context.bot.send_message(
                    target_id,
                    f"💰 <b>DP دریافتی!</b>\n\n👤 از: {get_user_display(user)}\n💰 <code>{format_number(amount)}</code>",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass
            return

    match = re.match(r'انتقال\s+(\d+)\s+به\s+(\d+)', text)
    if match:
        amount = int(match.group(1))
        target_id = int(match.group(2))
        if target_id == user.id:
            return
        target_user = db.get_user(target_id)
        if not target_user:
            await update.message.reply_text("❌ کاربر یافت نشد!")
            return

        fee = int(amount * TRANSFER_FEE)
        if db.get_balance(user.id) < amount + fee:
            await update.message.reply_text("❌ موجودی ناکافی!")
            return

        db.remove_dark_points(user.id, amount + fee)
        db.add_dark_points(target_id, amount)
        db.record_transfer(user.id, target_id, amount, fee)

        await update.message.reply_text(
            f"✅ انتقال موفق!\n💰 <code>{format_number(amount)}</code> به <code>{target_id}</code>",
            parse_mode=ParseMode.HTML
        )
        try:
            await context.bot.send_message(
                target_id,
                f"💰 DP دریافتی!\n💰 <code>{format_number(amount)}</code>",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass


# ============ BANK ============

async def handle_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = db.get_user(user.id)
    total_bank = db.get_total_bank_balance()

    if not u['bank_account']:
        kb = [[InlineKeyboardButton(f"🏦 افتتاح ({format_number(BANK_OPEN_COST)} DP)", callback_data="bank_open")]]
        await update.message.reply_text(
            f"🏦 <b>بانک دارکی</b>\n━━━━━━━━━━━━━━━━━━\n\n"
            f"❌ شما حسابی ندارید\n\n"
            f"💵 افتتاح: <code>{format_number(BANK_OPEN_COST)}</code> DP\n"
            f"📈 سود ۲۴ ساعته: <b>۱۵٪</b>\n\n"
            f"🏦 کل بانک: <code>{format_number(total_bank)}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(kb)
        )
    else:
        elapsed = time.time() - u['bank_deposit_time'] if u['bank_deposit_time'] > 0 else 0
        interest_ready = elapsed >= 86400 and u['bank_balance'] > 0 and not u['bank_interest_collected']
        potential = int(u['bank_balance'] * BANK_INTEREST_RATE) if interest_ready else 0

        buttons = []
        if u['bank_balance'] == 0:
            buttons.append([InlineKeyboardButton("💰 واریز", callback_data="bank_deposit")])
        else:
            if interest_ready:
                buttons.append([InlineKeyboardButton("💸 برداشت با سود ۱۵٪", callback_data="bank_withdraw")])
            else:
                remaining = max(0, 86400 - elapsed)
                h = int(remaining // 3600)
                m = int((remaining % 3600) // 60)
                buttons.append([InlineKeyboardButton(f"⏰ {h}h {m}m تا سود", callback_data="bank_wait")])
            buttons.append([InlineKeyboardButton("💰 واریز بیشتر", callback_data="bank_deposit")])
            buttons.append([InlineKeyboardButton("💸 برداشت بدون سود", callback_data="bank_withdraw")])

        text = (
            f"🏦 <b>بانک دارکی</b>\n━━━━━━━━━━━━━━━━━━\n\n"
            f"💳 کارت: <code>{u['bank_card']}</code>\n"
            f"💰 موجودی: <code>{format_number(u['bank_balance'])}</code>\n"
        )
        if potential > 0:
            text += f"📈 سود آماده: +<code>{format_number(potential)}</code>\n"
        text += f"\n🏦 کل بانک: <code>{format_number(total_bank)}</code>"

        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))


async def bank_open_cb(update, context):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if db.get_balance(user.id) < BANK_OPEN_COST:
        await query.answer(f"❌ نیاز: {format_number(BANK_OPEN_COST)}", show_alert=True)
        return

    kb = [
        [InlineKeyboardButton("🎲 خودکار", callback_data="bank_auto_card")],
        [InlineKeyboardButton("✏️ دلخواه", callback_data="bank_custom_card")],
    ]
    await query.edit_message_text(
        f"🏦 افتتاح حساب\n💵 هزینه: <code>{format_number(BANK_OPEN_COST)}</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def bank_auto_card_cb(update, context):
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
        f"✅ <b>حساب افتتاح شد!</b>\n💳 <code>{card}</code>",
        parse_mode=ParseMode.HTML
    )


async def bank_custom_card_cb(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_bank_card'] = True
    await query.edit_message_text("✏️ شماره ۱۳ رقمی دلخواه را در پیوی بفرستید:")


async def bank_deposit_cb(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_bank_deposit'] = True
    balance = db.get_balance(query.from_user.id)
    await query.edit_message_text(
        f"💰 واریز\n💎 موجودی: <code>{format_number(balance)}</code>\n\nمبلغ را در پیوی بفرستید:",
        parse_mode=ParseMode.HTML
    )


async def bank_withdraw_cb(update, context):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    balance, interest = db.bank_withdraw(user.id)
    total = balance + interest
    if total == 0:
        await query.answer("❌ موجودی ندارید!", show_alert=True)
        return

    await query.edit_message_text(
        f"✅ <b>برداشت موفق</b>\n\n"
        f"💰 اصل: <code>{format_number(balance)}</code>\n"
        f"📈 سود ۱۵٪: +<code>{format_number(interest)}</code>\n"
        f"💎 کل: <code>{format_number(total)}</code>",
        parse_mode=ParseMode.HTML
    )


async def bank_wait_cb(update, context):
    query = update.callback_query
    await query.answer("⏰ ۲۴ ساعت صبر کنید", show_alert=True)


# ============ FACTORY WITH REACTIVATE ============

async def handle_factory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = db.get_user(user.id)

    # کاربر کارخونه ندارد
    if u['factory_level'] == 0:
        kb = [[InlineKeyboardButton(f"🏭 افتتاح ({format_number(FACTORY_OPEN_COST)})", callback_data="factory_open")]]
        await update.message.reply_text(
            f"🏭 <b>کارخونه دارکی</b>\n━━━━━━━━━━━━━━━━━━\n\n"
            f"❌ کارخونه ندارید\n\n"
            f"💵 افتتاح: <code>{format_number(FACTORY_OPEN_COST)}</code>\n"
            f"🔧 نگهداری: ساعتی {FACTORY_HOURLY_MAINTENANCE} DP\n\n"
            f"📊 <b>سطوح:</b>\n"
            f"سطح ۱: ۱۰ DP/دقیقه\n"
            f"سطح ۲: ۲۵ DP/دقیقه (۵۰K)\n"
            f"سطح ۳: ۴۰ DP/دقیقه (۸۰K)\n"
            f"سطح ۴: ۵۰ DP/دقیقه (۱۰۰K)\n"
            f"سطح ۵: ۱۰۰ DP/دقیقه (۲۵۰K)",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    # کارخونه غیرفعال - دکمه فعال‌سازی مجدد
    if not u['factory_active']:
        f_level = u['factory_level']
        mine_rate = FACTORY_LEVELS[f_level]['mine_per_min']
        kb = [
            [InlineKeyboardButton("🔄 فعال‌سازی مجدد کارخونه", callback_data="factory_reactivate")],
            [InlineKeyboardButton("💰 جمع‌آوری DP باقیمانده", callback_data="factory_collect")],
        ]
        await update.message.reply_text(
            f"🏭 <b>کارخونه غیرفعال</b>\n━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 سطح: {f_level}\n"
            f"⚡ نرخ: {mine_rate} DP/دقیقه\n"
            f"⚠️ <b>کارخونه به دلیل کمبود موجودی متوقف شده!</b>\n\n"
            f"💎 موجودی: <code>{format_number(db.get_balance(user.id))}</code>\n\n"
            f"💡 <i>پس از فعال‌سازی مجدد، ماین دوباره شروع می‌شود</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    # کارخونه فعال
    mined = db.collect_factory(user.id)
    maintenance = db.factory_maintenance_due(user.id)
    u = db.get_user(user.id)
    f_level = u['factory_level']
    mine_rate = FACTORY_LEVELS[f_level]['mine_per_min']

    buttons = []
    if f_level < 5:
        upgrade_cost = FACTORY_LEVELS[f_level]['upgrade_cost']
        buttons.append([InlineKeyboardButton(
            f"⬆️ ارتقا به {f_level+1} ({format_number(upgrade_cost)})",
            callback_data="factory_upgrade"
        )])
    buttons.append([InlineKeyboardButton("💰 جمع‌آوری", callback_data="factory_collect")])

    text = (
        f"🏭 <b>کارخونه دارکی</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 سطح: <b>{f_level}</b>\n"
        f"⚡ نرخ: <b>{mine_rate}</b> DP/دقیقه\n"
        f"📋 وضعیت: ✅ فعال\n"
    )
    if mined > 0:
        text += f"💰 جمع‌آوری: +<code>{format_number(mined)}</code>\n"
    if maintenance > 0:
        text += f"🔧 نگهداری: -<code>{format_number(maintenance)}</code>\n"
    text += f"\n💎 موجودی: <code>{format_number(db.get_balance(user.id))}</code>"

    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))


async def factory_open_cb(update, context):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if db.get_balance(user.id) < FACTORY_OPEN_COST:
        await query.answer(f"❌ نیاز: {format_number(FACTORY_OPEN_COST)}", show_alert=True)
        return

    db.remove_dark_points(user.id, FACTORY_OPEN_COST)
    db.open_factory(user.id)
    await query.edit_message_text(
        f"✅ <b>کارخونه افتتاح شد!</b>\n📊 سطح ۱\n⚡ ۱۰ DP/دقیقه",
        parse_mode=ParseMode.HTML
    )


async def factory_reactivate_cb(update, context):
    """فعال‌سازی مجدد کارخونه"""
    query = update.callback_query
    user = query.from_user
    await query.answer()

    u = db.get_user(user.id)
    if not u or u['factory_level'] == 0:
        await query.answer("❌ کارخونه ندارید!", show_alert=True)
        return
    if u['factory_active']:
        await query.answer("✅ کارخونه فعال است!", show_alert=True)
        return

    # چک موجودی برای حداقل ۱ ساعت نگهداری
    if db.get_balance(user.id) < FACTORY_HOURLY_MAINTENANCE:
        await query.answer(
            f"❌ برای فعال‌سازی حداقل {FACTORY_HOURLY_MAINTENANCE} DP نیاز دارید!",
            show_alert=True
        )
        return

    db.reactivate_factory(user.id)
    await query.edit_message_text(
        f"✅ <b>کارخونه دوباره فعال شد!</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        f"🏭 سطح: {u['factory_level']}\n"
        f"⚡ ماین از این لحظه شروع شد",
        parse_mode=ParseMode.HTML
    )


async def factory_upgrade_cb(update, context):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    u = db.get_user(user.id)
    if not u or u['factory_level'] >= 5:
        await query.answer("❌ حداکثر سطح!", show_alert=True)
        return

    cost = FACTORY_LEVELS[u['factory_level']]['upgrade_cost']
    if db.get_balance(user.id) < cost:
        await query.answer(f"❌ نیاز: {format_number(cost)}", show_alert=True)
        return

    db.collect_factory(user.id)
    db.remove_dark_points(user.id, cost)
    db.upgrade_factory(user.id)
    new_level = u['factory_level'] + 1
    new_rate = FACTORY_LEVELS[new_level]['mine_per_min']

    await query.edit_message_text(
        f"⬆️ <b>ارتقا یافت!</b>\n📊 سطح {new_level}\n⚡ {new_rate} DP/دقیقه",
        parse_mode=ParseMode.HTML
    )


async def factory_collect_cb(update, context):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    mined = db.collect_factory(user.id)
    db.factory_maintenance_due(user.id)
    await query.answer(f"💰 {format_number(mined)} DP جمع شد!", show_alert=True)# ============ CRASH GAME ============

crash_active_games = {}

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
        await update.message.reply_text("❌ این بخش موقتاً غیرفعال می‌باشد.")
        return

    if amount < CRASH_MIN_BET:
        await update.message.reply_text(
            f"❌ حداقل: <code>{format_number(CRASH_MIN_BET)}</code> DP",
            parse_mode=ParseMode.HTML
        )
        return
    if amount > CRASH_MAX_BET:
        await update.message.reply_text(
            f"❌ حداکثر: <code>{format_number(CRASH_MAX_BET)}</code> DP",
            parse_mode=ParseMode.HTML
        )
        return

    balance = db.get_balance(user.id)
    if balance < amount:
        await update.message.reply_text(
            f"❌ موجودی ناکافی!\n💰 موجودی: <code>{format_number(balance)}</code>",
            parse_mode=ParseMode.HTML
        )
        return

    db.remove_dark_points(user.id, amount)
    crash_point = generate_crash_point()

    msg = await update.message.reply_text(
        f"💥 <b>بازی انفجار شروع شد!</b> 💥\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 بازیکن: {get_user_display(user)}\n"
        f"💰 شرط: <code>{format_number(amount)}</code>\n\n"
        f"🚀 ضریب: <code>1.00x</code>",
        parse_mode=ParseMode.HTML
    )

    game_id = db.create_crash_game(user.id, amount, crash_point, update.effective_chat.id, msg.message_id)

    await msg.edit_text(
        f"💥 <b>بازی انفجار زنده</b> 💥\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 {get_user_display(user)}\n"
        f"💰 شرط: <code>{format_number(amount)}</code>\n\n"
        f"🚀 ضریب: <code>1.00x</code>\n"
        f"💎 برد فعلی: <code>{format_number(amount)}</code>",
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
                f"👤 {get_user_display(user_obj)}\n"
                f"💰 شرط: <code>{format_number(bet)}</code>\n\n"
                f"🚀 ضریب: <code>{current}x</code> 📈\n"
                f"💎 برد فعلی: <code>{format_number(potential_win)}</code>",
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
                f"👤 {get_user_display(user_obj)}\n"
                f"💰 شرط: <code>{format_number(bet)}</code>\n\n"
                f"💥 ضریب انفجار: <code>{crash_point}x</code>\n"
                f"😔 نتیجه: باختی!\n\n"
                f"💎 موجودی: <code>{format_number(db.get_balance(user_id))}</code>",
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
        await query.answer("❌ یافت نشد!", show_alert=True)
        return
    if g['user_id'] != user.id:
        await query.answer("❌ این بازی شما نیست!", show_alert=True)
        return
    if g['status'] != 'playing':
        await query.answer("❌ تمام شده!", show_alert=True)
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

        await query.answer(f"✅ +{format_number(win_amount)} DP", show_alert=True)
        await query.edit_message_text(
            f"🎉 🏆 <b>برنده شدی!</b> 🏆 🎉\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 {get_user_display(user)}\n"
            f"💰 شرط: <code>{format_number(g['bet_amount'])}</code>\n\n"
            f"💎 ضریب: <code>{current_mult}x</code>\n"
            f"🏆 برد: <code>{format_number(win_amount)}</code>\n"
            f"📈 سود: +<code>{format_number(profit)}</code>\n\n"
            f"💎 موجودی: <code>{format_number(db.get_balance(user.id))}</code>",
            parse_mode=ParseMode.HTML
        )


# ============ DICE GAME ============

dice_games = {}

async def handle_dice_game_group(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: int):
    user = update.effective_user

    if db.get_setting('dice_active', '1') != '1':
        await update.message.reply_text("❌ این بخش موقتاً غیرفعال می‌باشد.")
        return

    if amount < DICE_MIN_BET:
        await update.message.reply_text(
            f"❌ حداقل شرط: <code>{format_number(DICE_MIN_BET)}</code> DP",
            parse_mode=ParseMode.HTML
        )
        return

    balance = db.get_balance(user.id)
    if balance < amount:
        await update.message.reply_text(f"❌ موجودی ناکافی!\n💰 <code>{format_number(balance)}</code>", parse_mode=ParseMode.HTML)
        return

    db.remove_dark_points(user.id, amount)

    kb = [
        [
            InlineKeyboardButton("1️⃣", callback_data="dice_pick_1"),
            InlineKeyboardButton("2️⃣", callback_data="dice_pick_2"),
            InlineKeyboardButton("3️⃣", callback_data="dice_pick_3"),
        ],
        [
            InlineKeyboardButton("4️⃣", callback_data="dice_pick_4"),
            InlineKeyboardButton("5️⃣", callback_data="dice_pick_5"),
            InlineKeyboardButton("6️⃣", callback_data="dice_pick_6"),
        ],
        [InlineKeyboardButton("🎲 پرتاب تاس", callback_data="dice_roll")],
        [InlineKeyboardButton("❌ لغو", callback_data="dice_cancel")],
    ]

    msg = await update.message.reply_text(
        f"🎲 <b>بازی تاس دارکی</b> 🎲\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 بازیکن: {get_user_display(user)}\n"
        f"💰 شرط: <code>{format_number(amount)}</code> DP\n\n"
        f"🎯 <b>ضرایب:</b>\n"
        f"• ۱ عدد: <b>۶ برابر</b> 🥇\n"
        f"• ۲ عدد: <b>۳ برابر</b> 🥈\n"
        f"• ۳ عدد: <b>۱.۵ برابر</b> 🥉\n\n"
        f"📌 اعداد انتخابی: <code>هیچ</code>\n\n"
        f"⚡️ <i>حداکثر ۳ عدد + دکمه پرتاب</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(kb)
    )

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
    query = update.callback_query
    user = query.from_user
    picked = int(query.data.split("_")[-1])

    game_key = f"{query.message.chat_id}_{query.message.message_id}"
    game = dice_games.get(game_key)

    if not game:
        await query.answer("❌ یافت نشد!", show_alert=True)
        return
    if game['user_id'] != user.id:
        await query.answer("❌ این بازی شما نیست!", show_alert=True)
        return
    if game['status'] != 'picking':
        await query.answer("❌ تمام شده!", show_alert=True)
        return

    picks = game['picks']
    if picked in picks:
        picks.remove(picked)
        await query.answer(f"❌ {picked} حذف شد.")
    else:
        if len(picks) >= 3:
            await query.answer("⚠️ حداکثر ۳ عدد!", show_alert=True)
            return
        picks.append(picked)
        await query.answer(f"✅ {picked} انتخاب شد.")

    game['picks'] = picks
    picks_display = " - ".join([str(p) for p in sorted(picks)]) if picks else "هیچ"

    if len(picks) == 1:
        mult_text = "۶ برابر 🥇"
    elif len(picks) == 2:
        mult_text = "۳ برابر 🥈"
    elif len(picks) == 3:
        mult_text = "۱.۵ برابر 🥉"
    else:
        mult_text = "بدون انتخاب"

    def get_btn(num):
        emoji_map = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣", 6: "6️⃣"}
        label = emoji_map[num]
        if num in picks:
            label = f"✅ {label}"
        return InlineKeyboardButton(label, callback_data=f"dice_pick_{num}")

    kb = [
        [get_btn(1), get_btn(2), get_btn(3)],
        [get_btn(4), get_btn(5), get_btn(6)],
        [InlineKeyboardButton("🎲 پرتاب تاس", callback_data="dice_roll")],
        [InlineKeyboardButton("❌ لغو", callback_data="dice_cancel")],
    ]

    try:
        await query.edit_message_text(
            f"🎲 <b>بازی تاس دارکی</b> 🎲\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 {get_user_display(user)}\n"
            f"💰 شرط: <code>{format_number(game['amount'])}</code>\n\n"
            f"🎯 ضرایب:\n"
            f"• ۱ عدد: ۶x\n"
            f"• ۲ عدد: ۳x\n"
            f"• ۳ عدد: ۱.۵x\n\n"
            f"📌 اعداد: <code>{picks_display}</code>\n"
            f"💎 ضریب: {mult_text}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(kb)
        )
    except Exception:
        pass


async def dice_roll_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    game_key = f"{query.message.chat_id}_{query.message.message_id}"
    game = dice_games.get(game_key)

    if not game or game['user_id'] != user.id or game['status'] != 'picking':
        await query.answer("❌ نامعتبر!", show_alert=True)
        return
    if len(game['picks']) == 0:
        await query.answer("⚠️ حداقل یک عدد!", show_alert=True)
        return

    game['status'] = 'rolling'
    await query.answer("🎲 پرتاب...")

    dice_msg = await context.bot.send_dice(chat_id=game['chat_id'], emoji='🎲')
    dice_value = dice_msg.dice.value

    await asyncio.sleep(4)

    picks = game['picks']
    amount = game['amount']
    won = dice_value in picks

    if len(picks) == 1:
        multiplier = 6.0
        mult_display = "۶ برابر"
    elif len(picks) == 2:
        multiplier = 3.0
        mult_display = "۳ برابر"
    else:
        multiplier = 1.5
        mult_display = "۱.۵ برابر"

    picks_display = " - ".join([str(p) for p in sorted(picks)])

    if won:
        prize = int(amount * multiplier)
        db.add_dark_points(user.id, prize)
        text = (
            f"🎉 🏆 <b>برنده شدی!</b> 🏆 🎉\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 {get_user_display(user)}\n"
            f"💰 شرط: <code>{format_number(amount)}</code>\n\n"
            f"🎲 عدد تاس: <b>{dice_value}</b>\n"
            f"📌 اعداد شما: <code>{picks_display}</code>\n"
            f"💎 ضریب: {mult_display}\n\n"
            f"🏆 برد: +<code>{format_number(prize)}</code>\n"
            f"💰 موجودی: <code>{format_number(db.get_balance(user.id))}</code>"
        )
    else:
        text = (
            f"💔 <b>باختی!</b> 💔\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 {get_user_display(user)}\n"
            f"💰 شرط: <code>{format_number(amount)}</code>\n\n"
            f"🎲 عدد تاس: <b>{dice_value}</b>\n"
            f"📌 اعداد شما: <code>{picks_display}</code>\n\n"
            f"💰 موجودی: <code>{format_number(db.get_balance(user.id))}</code>"
        )

    try:
        await query.edit_message_text(text, parse_mode=ParseMode.HTML)
    except Exception:
        pass

    game['status'] = 'finished'
    asyncio.create_task(cleanup_game_dict(dice_games, game_key, 30))


async def dice_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    game_key = f"{query.message.chat_id}_{query.message.message_id}"
    game = dice_games.get(game_key)

    if not game or game['user_id'] != user.id:
        await query.answer("❌", show_alert=True)
        return
    if game['status'] != 'picking':
        return

    db.add_dark_points(user.id, game['amount'])
    game['status'] = 'cancelled'
    await query.edit_message_text(
        f"❌ لغو شد\n💰 <code>{format_number(game['amount'])}</code> بازگردانده شد",
        parse_mode=ParseMode.HTML
    )
    if game_key in dice_games:
        del dice_games[game_key]


async def cleanup_game_dict(game_dict, key, delay):
    await asyncio.sleep(delay)
    if key in game_dict:
        del game_dict[key]


# ============ GUESS GAME (1-10) ============

guess_games = {}

async def handle_guess_game_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع بازی حدس بزن - درخواست مبلغ"""
    user = update.effective_user

    if db.get_setting('guess_active', '1') != '1':
        await update.message.reply_text("❌ این بخش موقتاً غیرفعال می‌باشد.")
        return

    # چک اینکه در حال حاضر بازی نداشته باشد
    for k, g in list(guess_games.items()):
        if g['user_id'] == user.id and g['status'] in ['awaiting_bet', 'picking']:
            await update.message.reply_text("❌ شما یک بازی حدس بزن در حال انجام دارید!")
            return

    balance = db.get_balance(user.id)
    if balance < GUESS_MIN_BET:
        await update.message.reply_text(
            f"❌ موجودی ناکافی!\n💰 موجودی: <code>{format_number(balance)}</code>\n💵 حداقل: <code>{format_number(GUESS_MIN_BET)}</code>",
            parse_mode=ParseMode.HTML
        )
        return

    msg = await update.message.reply_text(
        f"🎯 <b>بازی حدس بزن</b> 🎯\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 بازیکن: {get_user_display(user)}\n\n"
        f"🎯 <b>عدد بین ۱ تا ۱۰ حدس بزن!</b>\n\n"
        f"💰 حداقل شرط: <code>{format_number(GUESS_MIN_BET)}</code> DP\n\n"
        f"📊 <b>ضرایب برد:</b>\n"
        f"• ۱ عدد: <b>۱۰ برابر</b> 🥇\n"
        f"• ۲ عدد: <b>۵ برابر</b> 🥈\n"
        f"• ۳ عدد: <b>۲.۵ برابر</b> 🥉\n"
        f"• ۴ عدد: <b>۱.۲ برابر</b>\n\n"
        f"✏️ <b>مبلغ شرط را در همین گروه (ریپلای بر این پیام) بفرست:</b>",
        parse_mode=ParseMode.HTML
    )

    game_key = f"guess_{user.id}_{msg.message_id}"
    guess_games[game_key] = {
        'user_id': user.id,
        'user_obj': user,
        'status': 'awaiting_bet',
        'chat_id': msg.chat_id,
        'message_id': msg.message_id,
        'picks': [],
        'amount': 0,
        'created_at': time.time(),
    }


async def handle_guess_bet_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پاسخ به مبلغ شرط بازی حدس بزن"""
    user = update.effective_user
    text = update.message.text.strip() if update.message.text else ""

    if not update.message.reply_to_message:
        return False

    reply_msg_id = update.message.reply_to_message.message_id
    game_key = None
    for k, g in list(guess_games.items()):
        if g['user_id'] == user.id and g['message_id'] == reply_msg_id and g['status'] == 'awaiting_bet':
            game_key = k
            break

    if not game_key:
        return False

    try:
        amount = int(text)
    except Exception:
        await update.message.reply_text("❌ فقط عدد بفرستید!")
        return True

    if amount < GUESS_MIN_BET:
        await update.message.reply_text(
            f"❌ حداقل: <code>{format_number(GUESS_MIN_BET)}</code>",
            parse_mode=ParseMode.HTML
        )
        return True

    balance = db.get_balance(user.id)
    if balance < amount:
        await update.message.reply_text(f"❌ موجودی ناکافی!\n💰 <code>{format_number(balance)}</code>", parse_mode=ParseMode.HTML)
        return True

    db.remove_dark_points(user.id, amount)
    game = guess_games[game_key]
    game['amount'] = amount
    game['status'] = 'picking'

    # کیبورد ۱ تا ۱۰
    kb = [
        [
            InlineKeyboardButton("1️⃣", callback_data="guess_pick_1"),
            InlineKeyboardButton("2️⃣", callback_data="guess_pick_2"),
            InlineKeyboardButton("3️⃣", callback_data="guess_pick_3"),
            InlineKeyboardButton("4️⃣", callback_data="guess_pick_4"),
            InlineKeyboardButton("5️⃣", callback_data="guess_pick_5"),
        ],
        [
            InlineKeyboardButton("6️⃣", callback_data="guess_pick_6"),
            InlineKeyboardButton("7️⃣", callback_data="guess_pick_7"),
            InlineKeyboardButton("8️⃣", callback_data="guess_pick_8"),
            InlineKeyboardButton("9️⃣", callback_data="guess_pick_9"),
            InlineKeyboardButton("🔟", callback_data="guess_pick_10"),
        ],
        [InlineKeyboardButton("🎯 تایید و انتخاب عدد", callback_data="guess_confirm")],
        [InlineKeyboardButton("❌ لغو", callback_data="guess_cancel")],
    ]

    new_msg = await update.message.reply_text(
        f"🎯 <b>بازی حدس بزن</b> 🎯\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 {get_user_display(user)}\n"
        f"💰 شرط: <code>{format_number(amount)}</code>\n\n"
        f"📊 ضرایب:\n"
        f"• ۱ عدد: ۱۰x\n"
        f"• ۲ عدد: ۵x\n"
        f"• ۳ عدد: ۲.۵x\n"
        f"• ۴ عدد: ۱.۲x\n\n"
        f"📌 انتخابی: <code>هیچ</code>\n\n"
        f"⚡️ <i>حداکثر ۴ عدد انتخاب + تایید</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(kb)
    )

    # به‌روزرسانی کلید
    game['message_id'] = new_msg.message_id
    new_key = f"guess_{user.id}_{new_msg.message_id}"
    guess_games[new_key] = guess_games.pop(game_key)

    return True


async def guess_pick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    picked = int(query.data.split("_")[-1])

    game_key = None
    for k, g in list(guess_games.items()):
        if g['message_id'] == query.message.message_id and g['chat_id'] == query.message.chat_id:
            game_key = k
            break

    if not game_key:
        await query.answer("❌ یافت نشد!", show_alert=True)
        return

    game = guess_games[game_key]
    if game['user_id'] != user.id:
        await query.answer("❌ این بازی شما نیست!", show_alert=True)
        return
    if game['status'] != 'picking':
        await query.answer("❌ تمام شده!", show_alert=True)
        return

    picks = game['picks']
    if picked in picks:
        picks.remove(picked)
        await query.answer(f"❌ {picked} حذف شد.")
    else:
        if len(picks) >= 4:
            await query.answer("⚠️ حداکثر ۴ عدد!", show_alert=True)
            return
        picks.append(picked)
        await query.answer(f"✅ {picked}")

    game['picks'] = picks
    picks_display = " - ".join([str(p) for p in sorted(picks)]) if picks else "هیچ"

    if len(picks) == 1:
        mult_text = "۱۰ برابر 🥇"
    elif len(picks) == 2:
        mult_text = "۵ برابر 🥈"
    elif len(picks) == 3:
        mult_text = "۲.۵ برابر 🥉"
    elif len(picks) == 4:
        mult_text = "۱.۲ برابر"
    else:
        mult_text = "بدون انتخاب"

    emoji_map = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣",
                 6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣", 10: "🔟"}

    def get_btn(num):
        label = emoji_map[num]
        if num in picks:
            label = f"✅{label}"
        return InlineKeyboardButton(label, callback_data=f"guess_pick_{num}")

    kb = [
        [get_btn(1), get_btn(2), get_btn(3), get_btn(4), get_btn(5)],
        [get_btn(6), get_btn(7), get_btn(8), get_btn(9), get_btn(10)],
        [InlineKeyboardButton("🎯 تایید", callback_data="guess_confirm")],
        [InlineKeyboardButton("❌ لغو", callback_data="guess_cancel")],
    ]

    try:
        await query.edit_message_text(
            f"🎯 <b>بازی حدس بزن</b> 🎯\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 {get_user_display(user)}\n"
            f"💰 شرط: <code>{format_number(game['amount'])}</code>\n\n"
            f"📊 ضرایب:\n"
            f"• ۱ عدد: ۱۰x | ۲ عدد: ۵x\n"
            f"• ۳ عدد: ۲.۵x | ۴ عدد: ۱.۲x\n\n"
            f"📌 انتخابی: <code>{picks_display}</code>\n"
            f"💎 ضریب: {mult_text}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(kb)
        )
    except Exception:
        pass


async def guess_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    game_key = None
    for k, g in list(guess_games.items()):
        if g['message_id'] == query.message.message_id and g['chat_id'] == query.message.chat_id:
            game_key = k
            break

    if not game_key:
        await query.answer("❌", show_alert=True)
        return

    game = guess_games[game_key]
    if game['user_id'] != user.id:
        await query.answer("❌ این بازی شما نیست!", show_alert=True)
        return
    if game['status'] != 'picking':
        await query.answer("❌", show_alert=True)
        return
    if len(game['picks']) == 0:
        await query.answer("⚠️ حداقل یک عدد!", show_alert=True)
        return

    game['status'] = 'rolling'
    await query.answer("🎯 انتخاب عدد...")

    # انیمیشن انتخاب
    try:
        await query.edit_message_text(
            f"🎯 <b>در حال انتخاب عدد تصادفی...</b>\n\n🎰 🎰 🎰",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass

    await asyncio.sleep(3)

    picked_number = random.randint(1, 10)
    picks = game['picks']
    amount = game['amount']
    won = picked_number in picks

    if len(picks) == 1:
        multiplier = 10.0
        mult_display = "۱۰ برابر"
    elif len(picks) == 2:
        multiplier = 5.0
        mult_display = "۵ برابر"
    elif len(picks) == 3:
        multiplier = 2.5
        mult_display = "۲.۵ برابر"
    else:
        multiplier = 1.2
        mult_display = "۱.۲ برابر"

    picks_display = " - ".join([str(p) for p in sorted(picks)])

    if won:
        prize = int(amount * multiplier)
        db.add_dark_points(user.id, prize)
        text = (
            f"🎉 🏆 <b>برنده شدی!</b> 🏆 🎉\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 {get_user_display(user)}\n"
            f"💰 شرط: <code>{format_number(amount)}</code>\n\n"
            f"🎯 عدد ربات: <b>{picked_number}</b>\n"
            f"📌 اعداد شما: <code>{picks_display}</code>\n"
            f"💎 ضریب: {mult_display}\n\n"
            f"🏆 برد: +<code>{format_number(prize)}</code>\n"
            f"💰 موجودی: <code>{format_number(db.get_balance(user.id))}</code>"
        )
    else:
        text = (
            f"💔 <b>باختی!</b> 💔\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 {get_user_display(user)}\n"
            f"💰 شرط: <code>{format_number(amount)}</code>\n\n"
            f"🎯 عدد ربات: <b>{picked_number}</b>\n"
            f"📌 اعداد شما: <code>{picks_display}</code>\n\n"
            f"💰 موجودی: <code>{format_number(db.get_balance(user.id))}</code>"
        )

    try:
        await query.edit_message_text(text, parse_mode=ParseMode.HTML)
    except Exception:
        pass

    game['status'] = 'finished'
    asyncio.create_task(cleanup_game_dict(guess_games, game_key, 30))


async def guess_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    game_key = None
    for k, g in list(guess_games.items()):
        if g['message_id'] == query.message.message_id and g['chat_id'] == query.message.chat_id:
            game_key = k
            break

    if not game_key:
        return

    game = guess_games[game_key]
    if game['user_id'] != user.id:
        await query.answer("❌ فقط سازنده!", show_alert=True)
        return
    if game['status'] not in ['picking', 'awaiting_bet']:
        return

    if game['amount'] > 0:
        db.add_dark_points(user.id, game['amount'])
    game['status'] = 'cancelled'
    await query.edit_message_text(
        f"❌ لغو شد\n💰 <code>{format_number(game['amount'])}</code> بازگردانده شد",
        parse_mode=ParseMode.HTML
    )
    if game_key in guess_games:
        del guess_games[game_key]# ============ CASINO GAME ============

casino_games = {}

# سیمبل‌های کازینو
CASINO_SYMBOLS = ['7️⃣', '🍋', '🍇']

async def handle_casino_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع بازی کازینو"""
    user = update.effective_user

    if db.get_setting('casino_active', '1') != '1':
        await update.message.reply_text("❌ این بخش موقتاً غیرفعال می‌باشد.")
        return

    for k, g in list(casino_games.items()):
        if g['user_id'] == user.id and g['status'] in ['awaiting_bet', 'picking']:
            await update.message.reply_text("❌ شما یک بازی کازینو در حال انجام دارید!")
            return

    balance = db.get_balance(user.id)
    if balance < CASINO_MIN_BET:
        await update.message.reply_text(
            f"❌ موجودی ناکافی!\n💰 موجودی: <code>{format_number(balance)}</code>\n💵 حداقل: <code>{format_number(CASINO_MIN_BET)}</code>",
            parse_mode=ParseMode.HTML
        )
        return

    msg = await update.message.reply_text(
        f"🎰 <b>بازی کازینو دارکی</b> 🎰\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 بازیکن: {get_user_display(user)}\n\n"
        f"🎯 <b>حدس بزن چه چیزی در چرخش کازینو میاد!</b>\n\n"
        f"💰 حداقل شرط: <code>{format_number(CASINO_MIN_BET)}</code> DP\n\n"
        f"📊 <b>ضرایب برد:</b>\n"
        f"• فقط ۳ تا ۷️⃣ : <b>۱۵ برابر</b>\n"
        f"• ۷️⃣ یا 🍋 : <b>۱۲ برابر</b>\n"
        f"• ۷️⃣ یا 🍋 یا 🍇 : <b>۷ برابر</b>\n\n"
        f"✏️ <b>مبلغ شرط را ریپلای کن:</b>",
        parse_mode=ParseMode.HTML
    )

    game_key = f"casino_{user.id}_{msg.message_id}"
    casino_games[game_key] = {
        'user_id': user.id,
        'user_obj': user,
        'status': 'awaiting_bet',
        'chat_id': msg.chat_id,
        'message_id': msg.message_id,
        'picks': [],  # لیست انتخاب‌ها: ['7', 'lemon', 'grape']
        'amount': 0,
        'created_at': time.time(),
    }


async def handle_casino_bet_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پاسخ به مبلغ شرط کازینو"""
    user = update.effective_user
    text = update.message.text.strip() if update.message.text else ""

    if not update.message.reply_to_message:
        return False

    reply_msg_id = update.message.reply_to_message.message_id
    game_key = None
    for k, g in list(casino_games.items()):
        if g['user_id'] == user.id and g['message_id'] == reply_msg_id and g['status'] == 'awaiting_bet':
            game_key = k
            break

    if not game_key:
        return False

    try:
        amount = int(text)
    except Exception:
        await update.message.reply_text("❌ فقط عدد بفرستید!")
        return True

    if amount < CASINO_MIN_BET:
        await update.message.reply_text(
            f"❌ حداقل: <code>{format_number(CASINO_MIN_BET)}</code>",
            parse_mode=ParseMode.HTML
        )
        return True

    balance = db.get_balance(user.id)
    if balance < amount:
        await update.message.reply_text(f"❌ موجودی ناکافی!\n💰 <code>{format_number(balance)}</code>", parse_mode=ParseMode.HTML)
        return True

    db.remove_dark_points(user.id, amount)
    game = casino_games[game_key]
    game['amount'] = amount
    game['status'] = 'picking'

    kb = [
        [InlineKeyboardButton("7️⃣ ۳ تا هفت", callback_data="casino_pick_7")],
        [InlineKeyboardButton("🍋 ۳ تا لیمو", callback_data="casino_pick_lemon")],
        [InlineKeyboardButton("🍇 ۳ تا انگور", callback_data="casino_pick_grape")],
        [InlineKeyboardButton("🎰 چرخش کازینو!", callback_data="casino_spin")],
        [InlineKeyboardButton("❌ لغو", callback_data="casino_cancel")],
    ]

    new_msg = await update.message.reply_text(
        f"🎰 <b>بازی کازینو دارکی</b> 🎰\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 {get_user_display(user)}\n"
        f"💰 شرط: <code>{format_number(amount)}</code>\n\n"
        f"📊 <b>ضرایب:</b>\n"
        f"• فقط 7️⃣: ۱۵x\n"
        f"• 7️⃣ + 🍋: ۱۲x\n"
        f"• 7️⃣ + 🍋 + 🍇: ۷x\n\n"
        f"📌 انتخابی: <code>هیچ</code>\n\n"
        f"⚡️ <i>انتخاب کن و چرخش بزن</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(kb)
    )

    game['message_id'] = new_msg.message_id
    new_key = f"casino_{user.id}_{new_msg.message_id}"
    casino_games[new_key] = casino_games.pop(game_key)

    return True


async def casino_pick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    picked = query.data.split("_")[-1]  # 7, lemon, grape

    game_key = None
    for k, g in list(casino_games.items()):
        if g['message_id'] == query.message.message_id and g['chat_id'] == query.message.chat_id:
            game_key = k
            break

    if not game_key:
        await query.answer("❌", show_alert=True)
        return

    game = casino_games[game_key]
    if game['user_id'] != user.id:
        await query.answer("❌ این بازی شما نیست!", show_alert=True)
        return
    if game['status'] != 'picking':
        return

    picks = game['picks']
    if picked in picks:
        picks.remove(picked)
        await query.answer(f"❌ حذف شد")
    else:
        if len(picks) >= 3:
            await query.answer("⚠️ حداکثر ۳ گزینه!", show_alert=True)
            return
        picks.append(picked)
        await query.answer(f"✅ اضافه شد")

    game['picks'] = picks

    # نمایش انتخاب‌ها
    display_map = {'7': '7️⃣', 'lemon': '🍋', 'grape': '🍇'}
    picks_display = " + ".join([display_map[p] for p in picks]) if picks else "هیچ"

    # تعیین ضریب فعلی
    if len(picks) == 1 and '7' in picks:
        mult_text = "۱۵ برابر 🥇"
    elif len(picks) == 2 and set(picks) == {'7', 'lemon'}:
        mult_text = "۱۲ برابر 🥈"
    elif len(picks) == 3 and set(picks) == {'7', 'lemon', 'grape'}:
        mult_text = "۷ برابر 🥉"
    elif len(picks) == 0:
        mult_text = "بدون انتخاب"
    else:
        mult_text = "❌ ترکیب نامعتبر"

    def get_btn(name, label):
        emoji = {'7': '7️⃣', 'lemon': '🍋', 'grape': '🍇'}[name]
        text_lbl = f"{emoji} {label}"
        if name in picks:
            text_lbl = f"✅ {text_lbl}"
        return InlineKeyboardButton(text_lbl, callback_data=f"casino_pick_{name}")

    kb = [
        [get_btn('7', '۳ تا هفت')],
        [get_btn('lemon', '۳ تا لیمو')],
        [get_btn('grape', '۳ تا انگور')],
        [InlineKeyboardButton("🎰 چرخش کازینو!", callback_data="casino_spin")],
        [InlineKeyboardButton("❌ لغو", callback_data="casino_cancel")],
    ]

    try:
        await query.edit_message_text(
            f"🎰 <b>بازی کازینو دارکی</b> 🎰\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 {get_user_display(user)}\n"
            f"💰 شرط: <code>{format_number(game['amount'])}</code>\n\n"
            f"📊 ضرایب معتبر:\n"
            f"• فقط 7️⃣: ۱۵x\n"
            f"• 7️⃣ + 🍋: ۱۲x\n"
            f"• 7️⃣ + 🍋 + 🍇: ۷x\n\n"
            f"📌 انتخابی: <code>{picks_display}</code>\n"
            f"💎 ضریب: {mult_text}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(kb)
        )
    except Exception:
        pass


async def casino_spin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    game_key = None
    for k, g in list(casino_games.items()):
        if g['message_id'] == query.message.message_id and g['chat_id'] == query.message.chat_id:
            game_key = k
            break

    if not game_key:
        return

    game = casino_games[game_key]
    if game['user_id'] != user.id:
        await query.answer("❌ این بازی شما نیست!", show_alert=True)
        return
    if game['status'] != 'picking':
        return
    if len(game['picks']) == 0:
        await query.answer("⚠️ حداقل یک گزینه!", show_alert=True)
        return

    # بررسی معتبر بودن ترکیب
    picks_set = set(game['picks'])
    valid_combos = [{'7'}, {'7', 'lemon'}, {'7', 'lemon', 'grape'}]
    if picks_set not in valid_combos:
        await query.answer("❌ ترکیب نامعتبر! فقط ترکیبات: 7 | 7+لیمو | 7+لیمو+انگور", show_alert=True)
        return

    game['status'] = 'rolling'
    await query.answer("🎰 در حال چرخش...")

    # ارسال کازینو تلگرام
    casino_msg = await context.bot.send_dice(chat_id=game['chat_id'], emoji='🎰')
    casino_value = casino_msg.dice.value
    
    await asyncio.sleep(3)

    # مقادیر برنده کازینو تلگرام (1، 22، 43، 64 = ۳ تای یکسان)
    # 1 = BAR (3 bar), 22 = 3 grape, 43 = 3 lemon, 64 = 3 seven (jackpot)
    # ما آن‌ها را به سیمبل تبدیل می‌کنیم
    winning_map = {
        1: 'bar',
        22: 'grape',   # 🍇🍇🍇
        43: 'lemon',   # 🍋🍋🍋
        64: 'seven',   # 7️⃣7️⃣7️⃣
    }
    result_symbol = winning_map.get(casino_value, None)

    # نمایش نتیجه
    result_display_map = {
        'seven': '7️⃣ 7️⃣ 7️⃣ (۳ تا هفت)',
        'lemon': '🍋 🍋 🍋 (۳ تا لیمو)',
        'grape': '🍇 🍇 🍇 (۳ تا انگور)',
        'bar': 'BAR BAR BAR',
        None: 'ترکیب مختلف',
    }
    result_str = result_display_map.get(result_symbol, 'ترکیب مختلف')

    # بررسی برد
    won = False
    multiplier = 0
    mult_display = ""

    picks = game['picks']
    amount = game['amount']

    # فقط 7 انتخاب شده - ۱۵ برابر اگر 7 بیاد
    if picks_set == {'7'}:
        if result_symbol == 'seven':
            won = True
            multiplier = 15.0
            mult_display = "۱۵ برابر"
    # 7 + لیمو - ۱۲ برابر اگر 7 یا لیمو بیاد
    elif picks_set == {'7', 'lemon'}:
        if result_symbol in ['seven', 'lemon']:
            won = True
            multiplier = 12.0
            mult_display = "۱۲ برابر"
    # 7 + لیمو + انگور - ۷ برابر اگر یکی از این ۳ بیاد
    elif picks_set == {'7', 'lemon', 'grape'}:
        if result_symbol in ['seven', 'lemon', 'grape']:
            won = True
            multiplier = 7.0
            mult_display = "۷ برابر"

    display_map = {'7': '7️⃣', 'lemon': '🍋', 'grape': '🍇'}
    picks_display = " + ".join([display_map[p] for p in picks])

    if won:
        prize = int(amount * multiplier)
        db.add_dark_points(user.id, prize)
        text = (
            f"🎉 🎰 <b>جکپات! برنده شدی!</b> 🎰 🎉\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 {get_user_display(user)}\n"
            f"💰 شرط: <code>{format_number(amount)}</code>\n\n"
            f"🎰 نتیجه: <b>{result_str}</b>\n"
            f"📌 انتخاب شما: {picks_display}\n"
            f"💎 ضریب: {mult_display}\n\n"
            f"🏆 برد: +<code>{format_number(prize)}</code>\n"
            f"💰 موجودی: <code>{format_number(db.get_balance(user.id))}</code>"
        )
    else:
        text = (
            f"💔 <b>باختی!</b> 💔\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 {get_user_display(user)}\n"
            f"💰 شرط: <code>{format_number(amount)}</code>\n\n"
            f"🎰 نتیجه: {result_str}\n"
            f"📌 انتخاب شما: {picks_display}\n\n"
            f"💰 موجودی: <code>{format_number(db.get_balance(user.id))}</code>\n\n"
            f"🎲 <i>دفعه بعد شانس بیشتر!</i>"
        )

    try:
        await query.edit_message_text(text, parse_mode=ParseMode.HTML)
    except Exception:
        pass

    game['status'] = 'finished'
    asyncio.create_task(cleanup_game_dict(casino_games, game_key, 30))


async def casino_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    game_key = None
    for k, g in list(casino_games.items()):
        if g['message_id'] == query.message.message_id and g['chat_id'] == query.message.chat_id:
            game_key = k
            break

    if not game_key:
        return

    game = casino_games[game_key]
    if game['user_id'] != user.id:
        await query.answer("❌ فقط سازنده!", show_alert=True)
        return

    if game['amount'] > 0:
        db.add_dark_points(user.id, game['amount'])
    game['status'] = 'cancelled'
    await query.edit_message_text(
        f"❌ لغو شد\n💰 <code>{format_number(game['amount'])}</code> بازگردانده شد",
        parse_mode=ParseMode.HTML
    )
    if game_key in casino_games:
        del casino_games[game_key]


# ============ BOMB GAME ============

bomb_games = {}

async def handle_bomb_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع بازی بمب"""
    user = update.effective_user

    if db.get_setting('bomb_active', '1') != '1':
        await update.message.reply_text("❌ این بخش موقتاً غیرفعال می‌باشد.")
        return

    for k, g in list(bomb_games.items()):
        if g['user_id'] == user.id and g['status'] in ['awaiting_bet', 'playing']:
            await update.message.reply_text("❌ شما یک بازی بمب در حال انجام دارید!")
            return

    balance = db.get_balance(user.id)
    if balance < BOMB_MIN_BET:
        await update.message.reply_text(
            f"❌ موجودی ناکافی!\n💰 موجودی: <code>{format_number(balance)}</code>\n💵 حداقل: <code>{format_number(BOMB_MIN_BET)}</code>",
            parse_mode=ParseMode.HTML
        )
        return

    msg = await update.message.reply_text(
        f"💣 <b>بازی بمب دارکی</b> 💣\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 بازیکن: {get_user_display(user)}\n\n"
        f"🎯 <b>نحوه بازی:</b>\n"
        f"• شبکه ۴×۴ (۱۶ خانه)\n"
        f"• ۴ خانه بمب (یکی در هر ردیف)\n"
        f"• هر خانه امن = <b>+۱.۸x ضریب</b>\n"
        f"• بمب = <b>باخت کامل!</b>\n\n"
        f"💰 حداقل شرط: <code>{format_number(BOMB_MIN_BET)}</code> DP\n\n"
        f"✏️ <b>مبلغ شرط را ریپلای کن:</b>",
        parse_mode=ParseMode.HTML
    )

    game_key = f"bomb_{user.id}_{msg.message_id}"
    bomb_games[game_key] = {
        'user_id': user.id,
        'user_obj': user,
        'status': 'awaiting_bet',
        'chat_id': msg.chat_id,
        'message_id': msg.message_id,
        'amount': 0,
        'bombs': [],  # لیست موقعیت بمب‌ها
        'revealed': [],  # خانه‌های باز شده
        'multiplier': 1.0,
        'created_at': time.time(),
    }


async def handle_bomb_bet_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پاسخ به مبلغ شرط بمب"""
    user = update.effective_user
    text = update.message.text.strip() if update.message.text else ""

    if not update.message.reply_to_message:
        return False

    reply_msg_id = update.message.reply_to_message.message_id
    game_key = None
    for k, g in list(bomb_games.items()):
        if g['user_id'] == user.id and g['message_id'] == reply_msg_id and g['status'] == 'awaiting_bet':
            game_key = k
            break

    if not game_key:
        return False

    try:
        amount = int(text)
    except Exception:
        await update.message.reply_text("❌ فقط عدد بفرستید!")
        return True

    if amount < BOMB_MIN_BET:
        await update.message.reply_text(
            f"❌ حداقل: <code>{format_number(BOMB_MIN_BET)}</code>",
            parse_mode=ParseMode.HTML
        )
        return True

    balance = db.get_balance(user.id)
    if balance < amount:
        await update.message.reply_text(f"❌ موجودی ناکافی!", parse_mode=ParseMode.HTML)
        return True

    db.remove_dark_points(user.id, amount)
    game = bomb_games[game_key]
    game['amount'] = amount
    game['status'] = 'playing'
    game['multiplier'] = 1.0

    # تعیین موقعیت بمب‌ها - در هر ردیف یک بمب تصادفی
    bombs = []
    for row in range(4):
        col = random.randint(0, 3)
        bombs.append(row * 4 + col)  # موقعیت خطی (0-15)
    game['bombs'] = bombs
    game['revealed'] = []

    kb = generate_bomb_keyboard(game)
    new_msg = await update.message.reply_text(
        f"💣 <b>بازی بمب فعال</b> 💣\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 {get_user_display(user)}\n"
        f"💰 شرط: <code>{format_number(amount)}</code>\n\n"
        f"💎 ضریب فعلی: <b>1.0x</b>\n"
        f"🏆 برد فعلی: <code>{format_number(amount)}</code>\n\n"
        f"⚡️ <i>روی هر خانه کلیک کن. اگر بمب نبود ضریب +۱.۸ می‌شود</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(kb)
    )

    game['message_id'] = new_msg.message_id
    new_key = f"bomb_{user.id}_{new_msg.message_id}"
    bomb_games[new_key] = bomb_games.pop(game_key)

    return True


def generate_bomb_keyboard(game):
    """تولید کیبورد ۴×۴ بازی بمب"""
    revealed = game['revealed']
    bombs = game['bombs']
    status = game['status']

    kb = []
    for row in range(4):
        row_buttons = []
        for col in range(4):
            pos = row * 4 + col
            if status in ['won', 'lost', 'cashed_out']:
                # نمایش کامل
                if pos in bombs:
                    label = "💣"
                elif pos in revealed:
                    label = "💎"
                else:
                    label = "▫️"
            else:
                if pos in revealed:
                    label = "💎"
                else:
                    label = "🎁"
            row_buttons.append(InlineKeyboardButton(label, callback_data=f"bomb_click_{pos}"))
        kb.append(row_buttons)

    if status == 'playing' and len(game['revealed']) > 0:
        kb.append([InlineKeyboardButton(f"💰 برداشت ({game['multiplier']:.1f}x)", callback_data="bomb_cashout")])

    if status == 'playing':
        kb.append([InlineKeyboardButton("❌ لغو", callback_data="bomb_cancel")])

    return kb


async def bomb_click_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    pos = int(query.data.split("_")[-1])

    game_key = None
    for k, g in list(bomb_games.items()):
        if g['message_id'] == query.message.message_id and g['chat_id'] == query.message.chat_id:
            game_key = k
            break

    if not game_key:
        return

    game = bomb_games[game_key]
    if game['user_id'] != user.id:
        await query.answer("❌ این بازی شما نیست!", show_alert=True)
        return
    if game['status'] != 'playing':
        await query.answer("❌ تمام شده!", show_alert=True)
        return
    if pos in game['revealed']:
        await query.answer("❌ این خانه قبلاً باز شده!", show_alert=True)
        return

    # چک بمب
    if pos in game['bombs']:
        # باخت!
        game['status'] = 'lost'
        await query.answer("💥 بوم! بمب!", show_alert=True)

        kb = generate_bomb_keyboard(game)
        await query.edit_message_text(
            f"💥💥💥 <b>بمب!</b> 💥💥💥\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 {get_user_display(user)}\n"
            f"💰 شرط: <code>{format_number(game['amount'])}</code>\n\n"
            f"💣 روی بمب کلیک کردی!\n"
            f"💔 نتیجه: <b>باخت کامل!</b>\n\n"
            f"💎 موجودی: <code>{format_number(db.get_balance(user.id))}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(kb)
        )
        asyncio.create_task(cleanup_game_dict(bomb_games, game_key, 30))
        return

    # خانه امن - افزایش ضریب
    game['revealed'].append(pos)
    game['multiplier'] = round(game['multiplier'] + 0.8, 2)
    if game['multiplier'] < 1.8:
        game['multiplier'] = 1.8  # اولین کلیک
    else:
        game['multiplier'] = round(game['multiplier'] + 0.8, 2)

    # اصلاح: هر کلیک +1.8 اضافه می‌شود
    if len(game['revealed']) == 1:
        game['multiplier'] = 1.8
    else:
        game['multiplier'] = round(1.0 + (len(game['revealed']) * 0.8), 2)

    potential_win = int(game['amount'] * game['multiplier'])

    await query.answer(f"✅ +{game['multiplier']}x!")

    # چک برد کامل (همه ۱۲ خانه امن باز شده)
    if len(game['revealed']) == 12:
        # برد کامل - جکپات
        game['status'] = 'won'
        prize = potential_win
        db.add_dark_points(user.id, prize)
        kb = generate_bomb_keyboard(game)
        await query.edit_message_text(
            f"🏆 🎊 <b>جکپات کامل!</b> 🎊 🏆\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 {get_user_display(user)}\n"
            f"💰 شرط: <code>{format_number(game['amount'])}</code>\n\n"
            f"💎 ضریب: <b>{game['multiplier']}x</b>\n"
            f"🏆 برد: <code>{format_number(prize)}</code>\n\n"
            f"💰 موجودی: <code>{format_number(db.get_balance(user.id))}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(kb)
        )
        asyncio.create_task(cleanup_game_dict(bomb_games, game_key, 30))
        return

    kb = generate_bomb_keyboard(game)
    try:
        await query.edit_message_text(
            f"💣 <b>بازی بمب فعال</b> 💣\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 {get_user_display(user)}\n"
            f"💰 شرط: <code>{format_number(game['amount'])}</code>\n\n"
            f"💎 ضریب: <b>{game['multiplier']}x</b>\n"
            f"🏆 برد فعلی: <code>{format_number(potential_win)}</code>\n"
            f"🎁 خانه‌های باز شده: {len(game['revealed'])}\n\n"
            f"⚡️ <i>ادامه بده یا برداشت کن!</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(kb)
        )
    except Exception:
        pass


async def bomb_cashout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    game_key = None
    for k, g in list(bomb_games.items()):
        if g['message_id'] == query.message.message_id and g['chat_id'] == query.message.chat_id:
            game_key = k
            break

    if not game_key:
        return

    game = bomb_games[game_key]
    if game['user_id'] != user.id:
        await query.answer("❌ این بازی شما نیست!", show_alert=True)
        return
    if game['status'] != 'playing':
        return
    if len(game['revealed']) == 0:
        await query.answer("❌ حداقل یک خانه باز کن!", show_alert=True)
        return

    prize = int(game['amount'] * game['multiplier'])
    profit = prize - game['amount']
    db.add_dark_points(user.id, prize)
    game['status'] = 'cashed_out'

    await query.answer(f"✅ +{format_number(prize)} DP", show_alert=True)

    kb = generate_bomb_keyboard(game)
    await query.edit_message_text(
        f"🎉 💰 <b>برداشت موفق!</b> 💰 🎉\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 {get_user_display(user)}\n"
        f"💰 شرط: <code>{format_number(game['amount'])}</code>\n\n"
        f"💎 ضریب برداشت: <b>{game['multiplier']}x</b>\n"
        f"🏆 برد: <code>{format_number(prize)}</code>\n"
        f"📈 سود خالص: +<code>{format_number(profit)}</code>\n\n"
        f"💰 موجودی: <code>{format_number(db.get_balance(user.id))}</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(kb)
    )
    asyncio.create_task(cleanup_game_dict(bomb_games, game_key, 30))


async def bomb_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    game_key = None
    for k, g in list(bomb_games.items()):
        if g['message_id'] == query.message.message_id and g['chat_id'] == query.message.chat_id:
            game_key = k
            break

    if not game_key:
        return

    game = bomb_games[game_key]
    if game['user_id'] != user.id:
        await query.answer("❌ فقط سازنده!", show_alert=True)
        return

    # فقط قبل از شروع بازی می‌تواند لغو کند
    if game['status'] != 'playing' or len(game['revealed']) > 0:
        await query.answer("❌ بازی شروع شده!", show_alert=True)
        return

    db.add_dark_points(user.id, game['amount'])
    game['status'] = 'cancelled'
    await query.edit_message_text(
        f"❌ لغو شد\n💰 <code>{format_number(game['amount'])}</code> بازگردانده شد",
        parse_mode=ParseMode.HTML
    )
    if game_key in bomb_games:
        del bomb_games[game_key]# ============ ADMIN PANEL ============

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
    dice_status = "🟢" if db.get_setting('dice_active', '1') == '1' else "🔴"
    guess_status = "🟢" if db.get_setting('guess_active', '1') == '1' else "🔴"
    casino_status = "🟢" if db.get_setting('casino_active', '1') == '1' else "🔴"
    bomb_status = "🟢" if db.get_setting('bomb_active', '1') == '1' else "🔴"
    wheel_status = "🟢" if db.get_setting('wheel_active', '1') == '1' else "🔴"
    tasks_status = "🟢" if db.get_setting('tasks_active', '1') == '1' else "🔴"

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
        [InlineKeyboardButton("📋 مدیریت تسک‌ها", callback_data="adm_tasks")],
        # قابلیت‌های جدید
        [
            InlineKeyboardButton("👥 تغییر پاداش رفرال", callback_data="adm_ref_reward"),
            InlineKeyboardButton("🎁 تغییر هدیه ثبت‌نام", callback_data="adm_first_reward"),
        ],
        [
            InlineKeyboardButton("💵 قیمت پنل سنایی", callback_data="adm_panel_prices"),
            InlineKeyboardButton("📦 افزودن پلن پنل", callback_data="adm_create_panel"),
        ],
        [
            InlineKeyboardButton("💵 قیمت گیفت", callback_data="adm_set_gift_price"),
            InlineKeyboardButton("⭐ قیمت استارز", callback_data="adm_set_stars_price"),
        ],
        [InlineKeyboardButton("🎁 افزودن پلن گیفت", callback_data="adm_add_gift_plan")],
        # ذخیره و بکاپ
        [InlineKeyboardButton("💾 بکاپ‌گیری اطلاعات", callback_data="adm_backup_db")],
        # روشن/خاموش بخش‌ها
        [
            InlineKeyboardButton(f"🎁 گیفت: {gift_status}", callback_data="adm_toggle_gift"),
            InlineKeyboardButton(f"⭐ استارز: {stars_status}", callback_data="adm_toggle_stars"),
        ],
        [
            InlineKeyboardButton(f"💰 خرید DP: {buydp_status}", callback_data="adm_toggle_buydp"),
            InlineKeyboardButton(f"💥 انفجار: {crash_status}", callback_data="adm_toggle_crash"),
        ],
        [
            InlineKeyboardButton(f"🎲 تاس: {dice_status}", callback_data="adm_toggle_dice"),
            InlineKeyboardButton(f"🎯 حدس بزن: {guess_status}", callback_data="adm_toggle_guess"),
        ],
        [
            InlineKeyboardButton(f"🎰 کازینو: {casino_status}", callback_data="adm_toggle_casino"),
            InlineKeyboardButton(f"💣 بمب: {bomb_status}", callback_data="adm_toggle_bomb"),
        ],
        [
            InlineKeyboardButton(f"🎡 گردونه: {wheel_status}", callback_data="adm_toggle_wheel"),
            InlineKeyboardButton(f"📋 تسک‌ها: {tasks_status}", callback_data="adm_toggle_tasks"),
        ],
        [InlineKeyboardButton("💬 ارسال به کاربر خاص", callback_data="adm_send_to_user")],
        [InlineKeyboardButton("📋 آخرین سفارشات", callback_data="adm_recent_orders")],
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
        f"   • کل: {stats['total_users']}\n"
        f"   • فعال ۷ روزه: {stats['active_7d']}\n"
        f"   • جدید امروز: {stats['new_today']}\n"
        f"   • بن شده: {stats['banned_users']}\n\n"
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
    )

    tasks = db.get_tasks(only_active=False)
    text += f"\n📋 <b>تسک‌ها:</b> {len(tasks)} تسک\n"
    text += f"━━━━━━━━━━━━━━━━━━"

    kb = [[InlineKeyboardButton("🔙 پنل ادمین", callback_data="adm_back")]]
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


# ============ BROADCAST ============

async def adm_broadcast_msg_cb(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()
    context.user_data['admin_action'] = 'broadcast_msg'
    await query.edit_message_text(
        "📢 <b>پیام همگانی</b>\n\nپیام مورد نظر را ارسال کنید (هر نوع).\n\nبرای لغو: /cancel",
        parse_mode=ParseMode.HTML
    )


async def adm_broadcast_fwd_cb(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()
    context.user_data['admin_action'] = 'broadcast_fwd'
    await query.edit_message_text(
        "📤 <b>فوروارد همگانی</b>\n\nپیامی که می‌خواهید فوروارد شود را بفرستید.\n\nبرای لغو: /cancel",
        parse_mode=ParseMode.HTML
    )


async def do_broadcast(update, context, mode='copy'):
    admin_id = update.effective_user.id
    users = db.get_all_user_ids()
    total = len(users)
    sent, failed, blocked = 0, 0, 0
    start_time = time.time()

    status_msg = await update.message.reply_text(
        f"⏳ در حال ارسال به <b>{total}</b> کاربر...",
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
            if 'blocked' in err_str or 'kicked' in err_str or 'deactivated' in err_str:
                blocked += 1
            failed += 1

        if (sent + failed) % 20 == 0:
            try:
                await status_msg.edit_text(
                    f"⏳ در حال ارسال...\n\n✅ موفق: <b>{sent}</b>\n❌ ناموفق: <b>{failed}</b>\n📊 {sent+failed}/{total}",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass
        await asyncio.sleep(0.05)

    db.log_broadcast(admin_id, mode, total, sent, failed)
    total_time = int(time.time() - start_time)
    success_rate = int(sent/total*100 if total else 0)

    await status_msg.edit_text(
        f"✅ <b>ارسال کامل شد!</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 گزارش کامل:\n\n"
        f"👥 کل: <b>{total}</b>\n"
        f"✅ موفق: <b>{sent}</b>\n"
        f"❌ ناموفق: <b>{failed}</b>\n"
        f"🚫 بلاک کرده: <b>{blocked}</b>\n"
        f"📈 موفقیت: <b>{success_rate}%</b>\n"
        f"⏱ زمان: <b>{total_time}s</b>",
        parse_mode=ParseMode.HTML
    )


# ============ CHANNELS MANAGEMENT ============

async def adm_channels_cb(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()

    channels = db.get_force_channels()
    text = "📢 <b>کانال‌های اجباری</b>\n━━━━━━━━━━━━━━━━━━\n\n"
    if not channels:
        text += "❌ هیچ کانالی ثبت نشده\n"
    else:
        for ch in channels:
            title = html.escape(ch['channel_title'] or "بدون عنوان")
            text += f"• {ch['channel_username']} ({title})\n"

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
        "➕ یوزرنیم کانال را با @ بفرستید:\n\nمثال: <code>@mychannel</code>\n⚠️ ربات باید ادمین کانال باشد\n\nبرای لغو: /cancel",
        parse_mode=ParseMode.HTML
    )


async def adm_del_ch_cb(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    channel_id = int(query.data.split("_")[-1])
    db.remove_force_channel(channel_id)
    await query.answer("✅ حذف شد", show_alert=True)
    await adm_channels_cb(update, context)


# ============ TASKS MANAGEMENT ============

async def adm_tasks_cb(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()

    tasks = db.get_tasks(only_active=False)
    text = "📋 <b>مدیریت تسک‌ها</b>\n━━━━━━━━━━━━━━━━━━\n\n"
    if not tasks:
        text += "❌ هیچ تسکی موجود نیست\n"
    else:
        for t in tasks:
            title = html.escape(t['channel_title'] or "")
            text += f"• {t['channel_username']} ({title})\n  💰 {format_number(t['reward'])} DP\n\n"

    kb = [[InlineKeyboardButton("➕ افزودن تسک جدید", callback_data="adm_add_task")]]
    for t in tasks:
        kb.append([InlineKeyboardButton(f"🗑 حذف {t['channel_username']}", callback_data=f"adm_del_task_{t['task_id']}")])
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="adm_back")])

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def adm_add_task_cb(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()
    context.user_data['admin_action'] = 'add_task'
    context.user_data['task_step'] = 'channel'
    await query.edit_message_text(
        "📋 <b>افزودن تسک جدید</b>\n\nیوزرنیم کانال را با @ بفرستید:\n⚠️ ربات باید ادمین کانال باشد\n\nبرای لغو: /cancel",
        parse_mode=ParseMode.HTML
    )


async def adm_del_task_cb(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    task_id = int(query.data.split("_")[-1])
    db.delete_task(task_id)
    await query.answer("✅ تسک حذف شد", show_alert=True)
    await adm_tasks_cb(update, context)


# ============ NEW: REFERRAL REWARD & FIRST REWARD ============

async def adm_ref_reward_cb(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()

    current = get_referral_reward()
    context.user_data['admin_action'] = 'set_ref_reward'
    await query.edit_message_text(
        f"👥 <b>تغییر پاداش زیرمجموعه‌گیری</b>\n\n"
        f"مقدار فعلی: <code>{format_number(current)}</code> DP\n\n"
        f"مقدار جدید را به DP بفرستید:\n\nبرای لغو: /cancel",
        parse_mode=ParseMode.HTML
    )


async def adm_first_reward_cb(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()

    current = get_first_join_reward()
    context.user_data['admin_action'] = 'set_first_reward'
    await query.edit_message_text(
        f"🎁 <b>تغییر هدیه ثبت‌نام</b>\n\n"
        f"مقدار فعلی: <code>{format_number(current)}</code> DP\n\n"
        f"مقدار جدید را بفرستید:\n\nبرای لغو: /cancel",
        parse_mode=ParseMode.HTML
    )


# ============ BACKUP DATABASE ============

async def adm_backup_db_cb(update, context):
    """بکاپ‌گیری دیتابیس"""
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer("⏳ در حال آماده‌سازی بکاپ...")

    try:
        with open(db.db_name, 'rb') as f:
            await context.bot.send_document(
                chat_id=query.from_user.id,
                document=f,
                filename=f"darkpoint_backup_{int(time.time())}.db",
                caption=(
                    f"💾 <b>بکاپ دیتابیس دارک پوینت</b>\n\n"
                    f"📅 تاریخ: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"👥 تعداد کاربران: {db.get_all_users_count()}\n"
                    f"💎 کل DP: {format_number(db.get_stats()['total_dp'])}\n\n"
                    f"✅ این فایل را در جای امن نگه دارید"
                ),
                parse_mode=ParseMode.HTML
            )
        await query.message.reply_text("✅ بکاپ به پیوی شما ارسال شد.")
    except Exception as e:
        await query.message.reply_text(f"❌ خطا در بکاپ‌گیری:\n{str(e)[:200]}")


# ============ PANEL PRICES ============

async def adm_panel_prices_cb(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()

    price_500 = int(db.get_setting('panel_snai_500gb', str(DEFAULT_PANEL_PRICES['snai_500gb'])))
    price_800 = int(db.get_setting('panel_snai_800gb', str(DEFAULT_PANEL_PRICES['snai_800gb'])))
    price_1tb = int(db.get_setting('panel_snai_1tb', str(DEFAULT_PANEL_PRICES['snai_1tb'])))

    text = (
        f"💵 <b>مدیریت قیمت پنل سنایی</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        f"🛒 سنایی 500GB: <code>{format_number(price_500)}</code>\n"
        f"🛒 سنایی 800GB: <code>{format_number(price_800)}</code>\n"
        f"🛒 سنایی 1TB: <code>{format_number(price_1tb)}</code>\n\n"
        f"دکمه را انتخاب کنید:"
    )

    kb = [
        [InlineKeyboardButton(f"✏️ 500GB ({format_number(price_500)})", callback_data="adm_edit_price_500gb")],
        [InlineKeyboardButton(f"✏️ 800GB ({format_number(price_800)})", callback_data="adm_edit_price_800gb")],
        [InlineKeyboardButton(f"✏️ 1TB ({format_number(price_1tb)})", callback_data="adm_edit_price_1tb")],
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
        plan_key, plan_name = "panel_snai_500gb", "500GB"
    elif data == "adm_edit_price_800gb":
        plan_key, plan_name = "panel_snai_800gb", "800GB"
    elif data == "adm_edit_price_1tb":
        plan_key, plan_name = "panel_snai_1tb", "1TB"
    else:
        return

    context.user_data['admin_action'] = 'set_panel_price'
    context.user_data['panel_price_key'] = plan_key
    context.user_data['panel_price_name'] = plan_name

    await query.edit_message_text(
        f"✏️ قیمت جدید سنایی {plan_name} (DP):\n\nبرای لغو: /cancel",
        parse_mode=ParseMode.HTML
    )


# ============ SEND TO USER, RECENT ORDERS, GIFT TOP ============

async def adm_send_to_user_cb(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()
    context.user_data['admin_action'] = 'send_to_user_id'
    await query.edit_message_text(
        "💬 <b>ارسال پیام به کاربر خاص</b>\n\nشماره کاربری مقصد را بفرستید:",
        parse_mode=ParseMode.HTML
    )


async def adm_recent_orders_cb(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()

    conn = db.get_conn()
    c = conn.cursor()
    text = "📋 <b>آخرین سفارشات</b>\n━━━━━━━━━━━━━━━━━━\n\n"

    text += "🛒 <b>۵ سفارش آخر پنل:</b>\n"
    c.execute("SELECT * FROM panel_orders ORDER BY created_at DESC LIMIT 5")
    for o in c.fetchall():
        text += f"• #<code>{o['order_id']}</code> {html.escape(o['plan_name'])} - <code>{o['user_id']}</code>\n"

    text += "\n⭐ <b>۵ سفارش آخر استارز:</b>\n"
    c.execute("SELECT * FROM stars_orders ORDER BY created_at DESC LIMIT 5")
    for o in c.fetchall():
        text += f"• #<code>{o['order_id']}</code> {o['amount']}⭐ - <code>{o['user_id']}</code>\n"

    text += "\n🎁 <b>۵ سفارش آخر گیفت:</b>\n"
    c.execute("SELECT * FROM gift_orders ORDER BY created_at DESC LIMIT 5")
    for o in c.fetchall():
        text += f"• #<code>{o['order_id']}</code> {html.escape(o['gift_type'])} - <code>{o['user_id']}</code>\n"

    conn.close()
    kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="adm_back")]]
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def adm_gift_top_cb(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()
    context.user_data['admin_action'] = 'gift_top_count'
    await query.edit_message_text(
        "🎁 چند نفر برتر هدیه بگیرند؟\n\nمثال: <code>10</code>",
        parse_mode=ParseMode.HTML
    )


# ============ ADMIN CALLBACKS: SEND CONFIG & REPLY ============

async def admin_send_config_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return

    parts = query.data.split("_")
    order_id = int(parts[3])
    user_id = int(parts[4])

    await query.answer()
    context.user_data['admin_action'] = 'send_config'
    context.user_data['config_order_id'] = order_id
    context.user_data['config_user_id'] = user_id

    await query.message.reply_text(
        f"📤 <b>ارسال کانفیگ به کاربر</b>\n\n"
        f"👤 <code>{user_id}</code>\n"
        f"🆔 سفارش: <code>{order_id}</code>\n\n"
        f"کانفیگ (از پنل سنایی) را بفرستید (هر نوع):\n\nبرای لغو: /cancel",
        parse_mode=ParseMode.HTML
    )


async def admin_reply_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return

    user_id = int(query.data.split("_")[-1])
    await query.answer()
    context.user_data['admin_action'] = 'reply_user'
    context.user_data['reply_user_id'] = user_id

    await query.message.reply_text(
        f"💬 <b>پاسخ به کاربر</b>\n👤 <code>{user_id}</code>\n\nپیام را بفرستید:\n\nبرای لغو: /cancel",
        parse_mode=ParseMode.HTML
    )


async def admin_confirm_stars_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer("✅ سفارش تایید شد", show_alert=True)
    try:
        await query.edit_message_text(
            query.message.text_html + "\n\n✅ <b>تایید توسط ادمین</b>",
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
            query.message.text_html + "\n\n✅ <b>تایید توسط ادمین</b>",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass


# ============ MAIN ADMIN CALLBACK ROUTER ============

async def admin_callbacks(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌", show_alert=True)
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
    elif data == "adm_tasks":
        await adm_tasks_cb(update, context)
    elif data == "adm_add_task":
        await adm_add_task_cb(update, context)
    elif data.startswith("adm_del_task_"):
        await adm_del_task_cb(update, context)
    elif data == "adm_ref_reward":
        await adm_ref_reward_cb(update, context)
    elif data == "adm_first_reward":
        await adm_first_reward_cb(update, context)
    elif data == "adm_backup_db":
        await adm_backup_db_cb(update, context)
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
        await query.edit_message_text("💰 شماره کاربری را بفرستید:\n\nبرای لغو: /cancel")
    elif data == "adm_remove_dp":
        await query.answer()
        context.user_data['admin_action'] = 'remove_dp'
        await query.edit_message_text("💸 شماره کاربری را بفرستید:\n\nبرای لغو: /cancel")
    elif data == "adm_search_user":
        await query.answer()
        context.user_data['admin_action'] = 'search_user'
        await query.edit_message_text("🔍 شماره کاربری یا @username:")
    elif data == "adm_ban_user":
        await query.answer()
        context.user_data['admin_action'] = 'ban_user'
        await query.edit_message_text("🚫 شماره کاربری:")
    elif data == "adm_create_panel":
        await query.answer()
        context.user_data['admin_action'] = 'create_panel'
        context.user_data['panel_step'] = 'name'
        await query.edit_message_text("📦 نام پلن:")
    elif data == "adm_set_gift_price":
        await query.answer()
        context.user_data['admin_action'] = 'set_gift_price'
        await query.edit_message_text("💵 قیمت جدید گیفت تدی (DP):")
    elif data == "adm_set_stars_price":
        await query.answer()
        context.user_data['admin_action'] = 'set_stars_price'
        await query.edit_message_text(f"⭐ قیمت جدید {STARS_AMOUNT} استارز (DP):")
    elif data == "adm_toggle_gift":
        cur = db.get_setting('gift_section_active', '1')
        new = '0' if cur == '1' else '1'
        db.set_setting('gift_section_active', new)
        await query.answer(f"{'✅' if new=='1' else '❌'}", show_alert=True)
        await admin_panel(update, context)
    elif data == "adm_toggle_stars":
        cur = db.get_setting('stars_section_active', '1')
        new = '0' if cur == '1' else '1'
        db.set_setting('stars_section_active', new)
        await query.answer(f"{'✅' if new=='1' else '❌'}", show_alert=True)
        await admin_panel(update, context)
    elif data == "adm_toggle_buydp":
        cur = db.get_setting('buy_dp_active', '1')
        new = '0' if cur == '1' else '1'
        db.set_setting('buy_dp_active', new)
        await query.answer(f"{'✅' if new=='1' else '❌'}", show_alert=True)
        await admin_panel(update, context)
    elif data == "adm_toggle_crash":
        cur = db.get_setting('crash_active', '1')
        new = '0' if cur == '1' else '1'
        db.set_setting('crash_active', new)
        await query.answer(f"{'✅' if new=='1' else '❌'}", show_alert=True)
        await admin_panel(update, context)
    elif data == "adm_toggle_dice":
        cur = db.get_setting('dice_active', '1')
        new = '0' if cur == '1' else '1'
        db.set_setting('dice_active', new)
        await query.answer(f"{'✅' if new=='1' else '❌'}", show_alert=True)
        await admin_panel(update, context)
    elif data == "adm_toggle_guess":
        cur = db.get_setting('guess_active', '1')
        new = '0' if cur == '1' else '1'
        db.set_setting('guess_active', new)
        await query.answer(f"{'✅' if new=='1' else '❌'}", show_alert=True)
        await admin_panel(update, context)
    elif data == "adm_toggle_casino":
        cur = db.get_setting('casino_active', '1')
        new = '0' if cur == '1' else '1'
        db.set_setting('casino_active', new)
        await query.answer(f"{'✅' if new=='1' else '❌'}", show_alert=True)
        await admin_panel(update, context)
    elif data == "adm_toggle_bomb":
        cur = db.get_setting('bomb_active', '1')
        new = '0' if cur == '1' else '1'
        db.set_setting('bomb_active', new)
        await query.answer(f"{'✅' if new=='1' else '❌'}", show_alert=True)
        await admin_panel(update, context)
    elif data == "adm_toggle_wheel":
        cur = db.get_setting('wheel_active', '1')
        new = '0' if cur == '1' else '1'
        db.set_setting('wheel_active', new)
        await query.answer(f"{'✅' if new=='1' else '❌'}", show_alert=True)
        await admin_panel(update, context)
    elif data == "adm_toggle_tasks":
        cur = db.get_setting('tasks_active', '1')
        new = '0' if cur == '1' else '1'
        db.set_setting('tasks_active', new)
        await query.answer(f"{'✅' if new=='1' else '❌'}", show_alert=True)
        await admin_panel(update, context)
    elif data == "adm_create_check":
        await query.answer()
        context.user_data['admin_action'] = 'create_check'
        await query.edit_message_text("📝 مبلغ چک (DP):")
    elif data == "adm_add_gift_plan":
        await query.answer()
        context.user_data['admin_action'] = 'add_gift_plan'
        context.user_data['gift_plan_step'] = 'name'
        await query.edit_message_text("🎁 نام پلن گیفت:")
    elif data == "adm_gift_all":
        await query.answer()
        context.user_data['admin_action'] = 'gift_all'
        await query.edit_message_text("🎁 مقدار DP هدیه به همه:")# ============ HANDLE ADMIN TEXT INPUTS ============

async def handle_admin_text(update, context):
    """پردازش ورودی‌های متنی ادمین"""
    user = update.effective_user
    text = update.message.text.strip() if update.message.text else ""
    action = context.user_data.get('admin_action')

    # ============ افزودن کانال جوین اجباری ============
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
                f"❌ خطا! مطمئن شوید ربات ادمین کانال است.\n{str(e)[:100]}",
                parse_mode=ParseMode.HTML
            )
        context.user_data.pop('admin_action', None)
        return

    # ============ افزودن تسک ============
    if action == 'add_task':
        step = context.user_data.get('task_step')
        if step == 'channel':
            username = text.strip()
            if not username.startswith('@'):
                username = '@' + username
            try:
                chat = await context.bot.get_chat(username)
                title = chat.title or username
                context.user_data['task_channel'] = username
                context.user_data['task_title'] = title
                context.user_data['task_step'] = 'reward'
                await update.message.reply_text(
                    f"✅ کانال: {username}\n\n💰 مقدار پاداش (DP) را بفرستید:",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                await update.message.reply_text(
                    f"❌ خطا در بررسی کانال:\n{str(e)[:100]}\n\n⚠️ مطمئن شوید ربات ادمین کانال است",
                    parse_mode=ParseMode.HTML
                )
                context.user_data.clear()
        elif step == 'reward':
            try:
                reward = int(text)
                channel = context.user_data['task_channel']
                title = context.user_data['task_title']
                task_id = db.add_task(channel, title, reward)
                await update.message.reply_text(
                    f"✅ <b>تسک اضافه شد!</b>\n\n"
                    f"📢 {channel}\n"
                    f"📝 {html.escape(title)}\n"
                    f"💰 پاداش: <code>{format_number(reward)}</code> DP\n"
                    f"🆔 <code>{task_id}</code>",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                await update.message.reply_text("❌ عدد نامعتبر!")
            context.user_data.clear()
        return

    # ============ تغییر پاداش رفرال ============
    if action == 'set_ref_reward':
        try:
            amount = int(text)
            db.set_setting('referral_reward', str(amount))
            await update.message.reply_text(
                f"✅ <b>پاداش زیرمجموعه‌گیری تغییر کرد!</b>\n\n💰 مقدار جدید: <code>{format_number(amount)}</code> DP",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await update.message.reply_text("❌ عدد نامعتبر!")
        context.user_data.clear()
        return

    # ============ تغییر هدیه ثبت‌نام ============
    if action == 'set_first_reward':
        try:
            amount = int(text)
            db.set_setting('first_join_reward', str(amount))
            await update.message.reply_text(
                f"✅ <b>هدیه ثبت‌نام تغییر کرد!</b>\n\n💰 مقدار جدید: <code>{format_number(amount)}</code> DP",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await update.message.reply_text("❌ نامعتبر!")
        context.user_data.clear()
        return

    # ============ افزودن DP ============
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
                    f"💰 +<code>{format_number(amount)}</code>\n"
                    f"💎 موجودی: <code>{format_number(new_balance)}</code>",
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

    # ============ کسر DP ============
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

    # ============ جستجوی کاربر ============
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
            reply_kb = [[InlineKeyboardButton("💬 پاسخ به کاربر", callback_data=f"admin_reply_{u['user_id']}")]]
            await update.message.reply_text(
                f"👤 <b>اطلاعات کاربر</b>\n━━━━━━━━━━━━━━━━━━\n\n"
                f"🆔 <code>{u['user_id']}</code>\n"
                f"📛 @{u['username'] or 'ندارد'}\n"
                f"👤 <b>{name}</b>\n"
                f"💰 <code>{format_number(u['dark_points'])}</code> DP\n"
                f"📊 سطح: {u['level']}\n"
                f"👥 زیرمجموعه: {u['referral_count']}\n"
                f"📊 وضعیت: {banned}\n"
                f"🏭 کارخونه: {u['factory_level']} ({'فعال' if u['factory_active'] else 'غیرفعال'})\n"
                f"🏦 بانک: <code>{format_number(u['bank_balance'])}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(reply_kb)
            )
        context.user_data.clear()
        return

    # ============ بن/آنبن ============
    if action == 'ban_user':
        try:
            target_id = int(text)
            u = db.get_user(target_id)
            if not u:
                await update.message.reply_text("❌ یافت نشد!")
            else:
                if u['is_banned']:
                    db.unban_user(target_id)
                    await update.message.reply_text(
                        f"✅ <code>{target_id}</code> آنبن شد.",
                        parse_mode=ParseMode.HTML
                    )
                else:
                    db.ban_user(target_id)
                    await update.message.reply_text(
                        f"🚫 <code>{target_id}</code> بن شد.",
                        parse_mode=ParseMode.HTML
                    )
        except Exception:
            await update.message.reply_text("❌ نامعتبر!")
        context.user_data.clear()
        return

    # ============ ساخت پلن پنل سفارشی ============
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
                await update.message.reply_text("📊 حجم دیتا (مثلاً 500GB):")
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
                f"✅ <b>پلن ساخته شد!</b>\n\n📦 {html.escape(context.user_data['panel_name'])}\n💰 <code>{format_number(context.user_data['panel_price'])}</code>",
                parse_mode=ParseMode.HTML
            )
            context.user_data.clear()
        return

    # ============ تغییر قیمت گیفت ============
    if action == 'set_gift_price':
        try:
            price = int(text)
            db.set_setting('gift_teddy_price', str(price))
            await update.message.reply_text(
                f"✅ قیمت گیفت تدی: <code>{format_number(price)}</code> DP",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await update.message.reply_text("❌")
        context.user_data.clear()
        return

    # ============ تغییر قیمت استارز ============
    if action == 'set_stars_price':
        try:
            price = int(text)
            db.set_setting('stars_price', str(price))
            await update.message.reply_text(
                f"✅ قیمت {STARS_AMOUNT} استارز: <code>{format_number(price)}</code> DP",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await update.message.reply_text("❌")
        context.user_data.clear()
        return

    # ============ تغییر قیمت پنل سنایی ============
    if action == 'set_panel_price':
        try:
            price = int(text)
            plan_key = context.user_data['panel_price_key']
            plan_name = context.user_data['panel_price_name']
            db.set_setting(plan_key, str(price))
            await update.message.reply_text(
                f"✅ <b>قیمت پنل تغییر کرد!</b>\n\n📦 سنایی {plan_name}\n💰 <code>{format_number(price)}</code>",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await update.message.reply_text("❌ نامعتبر!")
        context.user_data.clear()
        return

    # ============ ارسال پیام به کاربر خاص - مرحله ۱: شماره ============
    if action == 'send_to_user_id':
        try:
            target_id = int(text)
            context.user_data['admin_action'] = 'send_to_user_msg'
            context.user_data['send_target_id'] = target_id
            await update.message.reply_text(
                f"✅ کاربر <code>{target_id}</code>\n\nپیام را بفرستید:",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await update.message.reply_text("❌ شماره نامعتبر!")
            context.user_data.clear()
        return

    # ============ هدیه به کاربران برتر - مرحله ۱ ============
    if action == 'gift_top_count':
        try:
            count = int(text)
            context.user_data['admin_action'] = 'gift_top_amount'
            context.user_data['gift_top_count'] = count
            await update.message.reply_text(f"✅ {count} نفر\n\nمقدار DP هدیه هر نفر:")
        except Exception:
            await update.message.reply_text("❌")
            context.user_data.clear()
        return

    # ============ هدیه به کاربران برتر - مرحله ۲ ============
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
                        f"🎁 <b>شما جزو {count} کاربر برتر بودید!</b>\n\n💰 +<code>{format_number(amount)}</code> DP هدیه",
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass
            await update.message.reply_text(
                f"✅ <b>هدیه ارسال شد!</b>\n\n💰 <code>{format_number(amount)}</code> به {len(top_users)} نفر",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await update.message.reply_text("❌")
        context.user_data.clear()
        return

    # ============ ساخت چک ============
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
                f"✅ <b>چک ساخته شد!</b>\n\n💰 <code>{format_number(amount)}</code>\n🔗 {link}",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await update.message.reply_text("❌")
        context.user_data.clear()
        return

    # ============ افزودن پلن گیفت ============
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
                    f"✅ پلن {html.escape(name)}\n💰 <code>{format_number(price)}</code>",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                await update.message.reply_text("❌")
            context.user_data.clear()
        return

    # ============ هدیه به همه ============
    if action == 'gift_all':
        try:
            amount = int(text)
            users = db.get_all_user_ids()
            for uid in users:
                db.add_dark_points(uid, amount)
            await update.message.reply_text(
                f"✅ <b>هدیه به همه!</b>\n💰 <code>{format_number(amount)}</code> به {len(users)} کاربر",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await update.message.reply_text("❌")
        context.user_data.clear()
        return


# ============ PRIVATE MESSAGE HANDLER ============

async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    if db.is_banned(user.id):
        return

    if not db.get_user(user.id):
        db.create_user(user.id, user.username or "", user.first_name or "")

    db.update_last_active(user.id)

    # ادمین: پیام‌های چندرسانه‌ای
    if is_admin(user.id):
        action = context.user_data.get('admin_action')

        # پیام همگانی
        if action == 'broadcast_msg':
            context.user_data.pop('admin_action', None)
            await do_broadcast(update, context, mode='copy')
            return

        # فوروارد همگانی
        if action == 'broadcast_fwd':
            context.user_data.pop('admin_action', None)
            await do_broadcast(update, context, mode='forward')
            return

        # ارسال کانفیگ
        if action == 'send_config':
            order_id = context.user_data.get('config_order_id')
            target_user_id = context.user_data.get('config_user_id')
            try:
                await context.bot.send_message(
                    target_user_id,
                    f"✅ <b>کانفیگ سفارش شما آماده شد!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"🆔 سفارش: <code>{order_id}</code>\n\n⬇️ کانفیگ:",
                    parse_mode=ParseMode.HTML
                )
                await context.bot.copy_message(
                    chat_id=target_user_id,
                    from_chat_id=update.message.chat_id,
                    message_id=update.message.message_id
                )
                await update.message.reply_text(
                    f"✅ کانفیگ برای <code>{target_user_id}</code> ارسال شد.",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                await update.message.reply_text(f"❌ خطا:\n{str(e)[:200]}")
            context.user_data.clear()
            return

        # پاسخ ادمین به کاربر
        if action == 'reply_user':
            target_user_id = context.user_data.get('reply_user_id')
            try:
                await context.bot.send_message(
                    target_user_id,
                    "📩 <b>پیام از پشتیبانی ربات:</b>",
                    parse_mode=ParseMode.HTML
                )
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
                await update.message.reply_text(f"❌ خطا:\n{str(e)[:200]}")
            context.user_data.clear()
            return

        # ارسال به کاربر خاص - مرحله پیام
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

    text = update.message.text.strip() if update.message.text else ""
    if not text:
        return

    if text.lower() in ['/cancel', 'لغو', 'cancel']:
        context.user_data.clear()
        await update.message.reply_text("✅ لغو شد.")
        return

    # کپچای زیرمجموعه
    if 'captcha_ans' in context.user_data:
        try:
            answer = int(text)
        except Exception:
            await update.message.reply_text("❌ فقط عدد!")
            return

        correct = context.user_data.get('captcha_ans')
        if answer != correct:
            q_text, ans = generate_captcha()
            context.user_data['captcha_ans'] = ans
            await update.message.reply_text(
                f"❌ اشتباه!\n\n❓ سوال جدید: <code>{q_text}</code> = ?",
                parse_mode=ParseMode.HTML
            )
            return

        joined = await check_force_join(user.id, context)
        if not joined:
            await update.message.reply_text(
                f"📢 <b>ابتدا در کانال‌ها عضو شوید:</b>\n\n💡 روی هر کانال کلیک کنید",
                parse_mode=ParseMode.HTML,
                reply_markup=get_force_join_keyboard("check_join_ref")
            )
            return

        referrer_id = context.user_data.get('pending_ref', 0)
        if referrer_id > 0:
            db.add_referral(referrer_id)
            ref_reward = get_referral_reward()
            db.add_dark_points(referrer_id, ref_reward)
            try:
                await context.bot.send_message(
                    referrer_id,
                    f"🎉 <b>زیرمجموعه جدید!</b>\n💰 +{format_number(ref_reward)} DP!",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass

        context.user_data.pop('captcha_ans', None)
        context.user_data.pop('pending_ref', None)

        # هدیه ثبت‌نام
        u = db.get_user(user.id)
        if u and not u['first_reward_claimed']:
            reward = db.claim_first_reward(user.id)
            if reward:
                await update.message.reply_text(
                    f"🎉 <b>خوش‌آمدید!</b>\n\n🎁 هدیه ثبت‌نام:\n💰 +<code>{format_number(reward)}</code> DP",
                    parse_mode=ParseMode.HTML
                )

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
            await update.message.reply_text("❌ ۱۳ رقم انگلیسی!")
            return
        if db.card_exists(text):
            await update.message.reply_text("❌ کارت تکراری!")
            return
        if not db.remove_dark_points(user.id, BANK_OPEN_COST):
            await update.message.reply_text("❌ موجودی ناکافی!")
            context.user_data.pop('awaiting_bank_card', None)
            return
        db.open_bank_account(user.id, text)
        context.user_data.pop('awaiting_bank_card', None)
        await update.message.reply_text(
            f"✅ حساب افتتاح شد!\n💳 <code>{text}</code>",
            parse_mode=ParseMode.HTML
        )
        return

    # واریز بانک
    if context.user_data.get('awaiting_bank_deposit'):
        try:
            amount = int(text)
            if amount <= 0:
                await update.message.reply_text("❌ نامعتبر!")
                return
            if db.bank_deposit(user.id, amount):
                context.user_data.pop('awaiting_bank_deposit', None)
                await update.message.reply_text(
                    f"✅ <b>واریز موفق!</b>\n💰 <code>{format_number(amount)}</code>\n📈 سود ۱۵٪ بعد از ۲۴ ساعت",
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text("❌ موجودی ناکافی!")
        except Exception:
            await update.message.reply_text("❌ فقط عدد!")
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
            f"✅ <b>سفارش ثبت شد!</b>\n\n⭐ {STARS_AMOUNT} استارز\n👤 مقصد: <code>{target}</code>",
            parse_mode=ParseMode.HTML
        )

        global BOT_USERNAME
        if not BOT_USERNAME:
            me = await context.bot.get_me()
            BOT_USERNAME = me.username

        user_display = f"@{user.username}" if user.username else f"<code>{user.id}</code>"
        log_kb = [[InlineKeyboardButton("🤖 ورود به ربات", url=f"https://t.me/{BOT_USERNAME}")]]
        await send_log(context,
            f"⭐ <b>سفارش استارز - اکانت دیگه</b>\n\n👤 {user_display}\n🆔 <code>{user.id}</code>\n📍 <code>{target}</code>\n⭐ {STARS_AMOUNT}",
            reply_markup=InlineKeyboardMarkup(log_kb)
        )

        for admin_id in ADMIN_IDS:
            try:
                admin_kb = [
                    [InlineKeyboardButton("💬 پاسخ به کاربر", callback_data=f"admin_reply_{user.id}")],
                    [InlineKeyboardButton("✅ تایید", callback_data=f"admin_confirm_stars_{order_id}")]
                ]
                await context.bot.send_message(
                    admin_id,
                    f"⭐ سفارش استارز\n👤 {user_display}\n📍 <code>{target}</code>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(admin_kb)
                )
            except Exception:
                pass
        return# ============ HANDLE PRIVATE REPLIES FOR GROUP GAMES ============

async def handle_group_reply_for_games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پاسخ‌های ریپلای در گروه برای بازی‌های حدس بزن/کازینو/بمب"""
    # چک بازی حدس بزن
    handled = await handle_guess_bet_reply(update, context)
    if handled:
        return True

    # چک بازی کازینو
    handled = await handle_casino_bet_reply(update, context)
    if handled:
        return True

    # چک بازی بمب
    handled = await handle_bomb_bet_reply(update, context)
    if handled:
        return True

    return False


# اصلاح handle_group_message برای پشتیبانی از ریپلای‌های بازی
_original_handle_group_message = handle_group_message

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """هندلر اصلاح شده گروه"""
    if not update.message or not update.message.text:
        return

    # اول چک ریپلای برای بازی‌ها
    if update.message.reply_to_message:
        handled = await handle_group_reply_for_games(update, context)
        if handled:
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
    elif text == 'حدس بزن' or text.startswith('حدس بزن'):
        await handle_guess_game_start(update, context)
    elif text == 'کازینو' or text.startswith('کازینو'):
        await handle_casino_start(update, context)
    elif text == 'بمب' or text.startswith('بمب'):
        await handle_bomb_start(update, context)
    elif text.startswith('انتقال '):
        await handle_transfer(update, context)
    elif text == 'بانک دارکی':
        await handle_bank(update, context)
    elif text == 'کارخونه دارکی':
        await handle_factory(update, context)
    elif text == 'لیدربورد':
        await handle_leaderboard_group(update, context)


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

    # گردونه شانس
    elif data == "wheel_menu":
        await wheel_menu(update, context)
    elif data == "wheel_spin_free":
        await wheel_spin_free_cb(update, context)
    elif data == "wheel_spin_paid":
        await wheel_spin_paid_cb(update, context)

    # تسک‌ها
    elif data == "tasks_menu":
        await tasks_menu(update, context)
    elif data.startswith("task_view_"):
        await task_view_cb(update, context)
    elif data.startswith("task_verify_"):
        await task_verify_cb(update, context)

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

    # بازی دو نفره
    elif data.startswith("join_game_"):
        await join_game_callback(update, context)
    elif data.startswith("cancel_game_"):
        await cancel_game_callback(update, context)

    # بازی انفجار
    elif data.startswith("crash_out_"):
        await crash_out_callback(update, context)

    # بازی تاس
    elif data.startswith("dice_pick_"):
        await dice_pick_callback(update, context)
    elif data == "dice_roll":
        await dice_roll_callback(update, context)
    elif data == "dice_cancel":
        await dice_cancel_callback(update, context)

    # بازی حدس بزن
    elif data.startswith("guess_pick_"):
        await guess_pick_callback(update, context)
    elif data == "guess_confirm":
        await guess_confirm_callback(update, context)
    elif data == "guess_cancel":
        await guess_cancel_callback(update, context)

    # بازی کازینو
    elif data.startswith("casino_pick_"):
        await casino_pick_callback(update, context)
    elif data == "casino_spin":
        await casino_spin_callback(update, context)
    elif data == "casino_cancel":
        await casino_cancel_callback(update, context)

    # بازی بمب
    elif data.startswith("bomb_click_"):
        await bomb_click_callback(update, context)
    elif data == "bomb_cashout":
        await bomb_cashout_callback(update, context)
    elif data == "bomb_cancel":
        await bomb_cancel_callback(update, context)

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
    elif data == "factory_reactivate":
        await factory_reactivate_cb(update, context)

    # جوین اجباری
    elif data == "check_join_main":
        await check_join_main(update, context)
    elif data == "check_join_ref":
        await check_join_ref_cb(update, context)

    # ادمین - کالبک‌های ویژه
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


# ============ BACKUP COMMAND (ADMIN) ============

async def backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /backup برای بکاپ‌گیری از دیتابیس"""
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("❌ دسترسی ندارید!")
        return

    try:
        await update.message.reply_text("⏳ در حال آماده‌سازی بکاپ...")
        with open(db.db_name, 'rb') as f:
            await context.bot.send_document(
                chat_id=user.id,
                document=f,
                filename=f"darkpoint_backup_{int(time.time())}.db",
                caption=(
                    f"💾 <b>بکاپ دیتابیس دارک پوینت</b>\n\n"
                    f"📅 تاریخ: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"👥 کاربران: {db.get_all_users_count()}\n"
                    f"💎 کل DP: {format_number(db.get_stats()['total_dp'])}"
                ),
                parse_mode=ParseMode.HTML
            )
    except Exception as e:
        await update.message.reply_text(f"❌ خطا:\n{str(e)[:200]}")


# ============ MAIN FUNCTION ============

def main():
    """راه اندازی ربات"""
    start_health_server()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_error_handler(error_handler)

    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("cancel", cancel_cmd))
    application.add_handler(CommandHandler("backup", backup_cmd))

    # Callbacks
    application.add_handler(CallbackQueryHandler(callback_router))

    # Group messages
    application.add_handler(MessageHandler(
        filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
        handle_group_message
    ))

    # Private messages
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

    print("🏴 Dark Point Bot Ultimate Version is running!")
    print(f"✅ Admin IDs: {ADMIN_IDS}")
    print(f"✅ Log Channel: {LOG_CHANNEL_ID}")
    logger.info("Bot started successfully")

    application.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
