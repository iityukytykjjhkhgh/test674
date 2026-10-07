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
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
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
    return int(db.get_setting('referral_reward', str(DEFAULT_REFERRAL_REWARD)))

def get_first_join_reward():
    return int(db.get_setting('first_join_reward', str(FIRST_JOIN_REWARD)))

def is_bot_active():
    return db.get_setting('bot_active', '1') == '1'

async def check_force_join(user_id, context):
    channels = db.get_force_channels()
    if not channels:
        return True, []
    not_joined = []
    for ch in channels:
        try:
            member = await context.bot.get_chat_member(ch['channel_username'], user_id)
            if member.status in ['left', 'kicked']:
                not_joined.append(ch)
        except Exception:
            continue
    return len(not_joined) == 0, not_joined

def get_force_join_keyboard(check_callback="check_join_main"):
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

async def check_bot_is_admin_in_group(context, chat_id):
    """چک می‌کند که ربات در گروه ادمین است یا نه"""
    try:
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
        is_bot_admin = bot_member.status in ['administrator', 'creator']
        return is_bot_admin
    except Exception:
        return False

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
        <p>{time.strftime('%Y-%m-%d %H:%M:%S')}</p>
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
                logger.info("🟢 Self-ping OK")
    except Exception:
        pass


# ============ CHECK BOT ACTIVE (دکوراتور) ============

async def check_bot_active_and_notify(update, context):
    """چک می‌کند ربات روشن است یا خاموش. اگر خاموش، به کاربر اطلاع می‌دهد."""
    if is_bot_active():
        return True
    
    user = update.effective_user
    if is_admin(user.id):
        return True  # ادمین همیشه دسترسی داره
    
    text = (
        "⚠️ <b>ربات موقتاً خاموش است</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🔧 ربات از طرف پشتیبانی موقتاً غیرفعال شده است.\n"
        "لطفاً بعداً مجدداً تلاش کنید.\n\n"
        "💡 با پشتیبانی در تماس باشید."
    )
    
    try:
        if update.callback_query:
            await update.callback_query.answer("⚠️ ربات موقتاً خاموش است!", show_alert=True)
        else:
            await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    except Exception:
        pass
    return False


# ============ START COMMAND ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    if db.is_banned(user.id):
        await update.message.reply_text("❌ حساب شما مسدود شده است.")
        return

    # چک خاموش بودن ربات
    if not is_bot_active() and not is_admin(user.id):
        await update.message.reply_text(
            "⚠️ <b>ربات موقتاً خاموش است</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🔧 ربات از طرف پشتیبانی موقتاً غیرفعال شده است.\n"
            "لطفاً بعداً مجدداً تلاش کنید.",
            parse_mode=ParseMode.HTML
        )
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
                f"برای تایید هویت، پاسخ سوال زیر را ارسال کنید:\n\n"
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
                        f"📋 چک فعال شد\n👤 <code>{user.id}</code>\n💰 <code>{format_number(amount)}</code>",
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass
            return
        else:
            await update.message.reply_text("❌ چک نامعتبر یا استفاده شده است.")
            return

    # چک جوین اجباری دقیق
    joined, not_joined = await check_force_join(user.id, context)
    if not joined:
        await update.message.reply_text(
            f"📢 <b>عضویت اجباری در کانال‌ها</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"برای استفاده از ربات، در کانال‌های زیر عضو شوید:\n\n"
            f"💡 <i>روی هر کانال کلیک کنید و سپس «عضو شدم» را بزنید</i>",
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
                f"🎁 <b>هدیه ثبت‌نام شما:</b>\n"
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
        [InlineKeyboardButton("➕ افزودن ربات به گروه", url=f"https://t.me/{BOT_USERNAME}?startgroup=true")],
    ]

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
        f"🎮 <b>بازی‌های موجود در گروه:</b>\n"
        f"💥 انفجار | 🎲 تاس | 🎯 حدس بزن\n"
        f"🎰 کازینو | 💣 بمب | ⚽ فوتبال"
    )

    if query:
        try:
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception:
            await query.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))


# ============ JOIN CHECK CALLBACKS ============

async def check_join_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()
    joined, not_joined = await check_force_join(user.id, context)
    if not joined:
        not_joined_list = "\n".join([f"❌ {ch['channel_username']}" for ch in not_joined])
        await query.answer(
            f"❌ هنوز عضو همه کانال‌ها نیستی!\n\nعضو نشده‌ها:\n{not_joined_list}",
            show_alert=True
        )
        return

    u = db.get_user(user.id)
    if u and not u['first_reward_claimed']:
        reward = db.claim_first_reward(user.id)
        if reward:
            try:
                await context.bot.send_message(
                    user.id,
                    f"🎉 <b>خوش‌آمدید!</b>\n\n🎁 هدیه ثبت‌نام:\n💰 +<code>{format_number(reward)}</code> DP",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass

    await show_main_menu(update, context, query=query)


async def check_join_ref_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    joined, not_joined = await check_force_join(user.id, context)
    if not joined:
        not_joined_list = "\n".join([f"❌ {ch['channel_username']}" for ch in not_joined])
        await query.answer(
            f"❌ هنوز در همه کانال‌ها عضو نیستی!\n\nعضو نشده‌ها:\n{not_joined_list}",
            show_alert=True
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

    u = db.get_user(user.id)
    if u and not u['first_reward_claimed']:
        reward = db.claim_first_reward(user.id)
        if reward:
            try:
                await context.bot.send_message(
                    user.id,
                    f"🎉 <b>خوش‌آمدید!</b>\n\n🎁 هدیه ثبت‌نام:\n💰 +<code>{format_number(reward)}</code> DP",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass

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
        text += f"🏆 بالاترین سطح!\n"

    text += (
        f"\n👥 زیرمجموعه‌ها: {user['referral_count'] if user else 0}\n"
        f"📊 کل دریافتی: <code>{format_number(user['total_earned'] if user else 0)}</code> DP\n\n"
        f"━━━━━━━━━━━━━━━━━━"
    )

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))


# ============ WHEEL ============

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
        f"🎁 جوایز: <code>{format_number(WHEEL_MIN_PRIZE)}</code> تا <code>{format_number(WHEEL_MAX_PRIZE)}</code> DP\n"
        f"⏰ چرخش رایگان: هر ۲۴ ساعت\n"
        f"💵 چرخش اضافی: <code>{format_number(WHEEL_EXTRA_COST)}</code> DP\n\n"
    )

    buttons = []
    if can_free:
        buttons.append([InlineKeyboardButton("🎡 چرخش رایگان!", callback_data="wheel_spin_free")])
        text += "✅ <b>شما یک چرخش رایگان دارید!</b>"
    else:
        hours = int(remaining // 3600)
        mins = int((remaining % 3600) // 60)
        text += f"⏰ چرخش رایگان بعدی: <b>{hours}h {mins}m</b>"
        buttons.append([InlineKeyboardButton(f"💵 چرخش اضافی", callback_data="wheel_spin_paid")])

    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="dark_point_menu")])
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))


async def wheel_spin_free_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    can_free, _ = db.can_spin_wheel_free(user.id)
    if not can_free:
        await query.answer("❌ چرخش رایگان تمام شده!", show_alert=True)
        return

    prize = random.randint(WHEEL_MIN_PRIZE, WHEEL_MAX_PRIZE)
    db.add_dark_points(user.id, prize)
    db.set_wheel_spin_time(user.id)

    await query.answer("🎡 در حال چرخش...")
    await asyncio.sleep(1)

    await query.edit_message_text(
        f"🎡 <b>گردونه چرخید!</b> 🎡\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎉 <b>برنده شدی!</b>\n\n"
        f"💰 جایزه: +<code>{format_number(prize)}</code> DP\n"
        f"💎 موجودی: <code>{format_number(db.get_balance(user.id))}</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="dark_point_menu")]])
    )


async def wheel_spin_paid_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if not db.remove_dark_points(user.id, WHEEL_EXTRA_COST):
        await query.answer(f"❌ نیاز به {format_number(WHEEL_EXTRA_COST)} DP!", show_alert=True)
        return

    prize = random.randint(WHEEL_MIN_PRIZE, WHEEL_MAX_PRIZE)
    db.add_dark_points(user.id, prize)
    await query.answer("🎡 چرخش...")
    await asyncio.sleep(1)

    net = prize - WHEEL_EXTRA_COST
    await query.edit_message_text(
        f"🎡 <b>گردونه چرخید!</b>\n\n"
        f"🎉 جایزه: <code>{format_number(prize)}</code>\n"
        f"💵 هزینه: -<code>{format_number(WHEEL_EXTRA_COST)}</code>\n"
        f"📊 سود: <code>{format_number(net)}</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="dark_point_menu")]])
    )


# ============ INFO PAGES ============

INFO_PAGES = {
    1: (
        "📖 <b>دارک پوینت - صفحه ۱/۱۰</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        "🏴 <b>دارک پوینت چیست؟</b>\n\n"
        "واحد پولی اختصاصی ربات که با آن می‌توانید:\n\n"
        "⭐ استارز تلگرام برداشت کنید\n"
        "🛒 پنل VPN خریداری کنید\n"
        "🎁 گیفت تدی بگیرید\n"
        "🎮 بازی‌های متنوع کنید\n"
        "🏭 کارخونه بسازید\n"
        "🏦 در بانک سرمایه‌گذاری کنید\n"
        "🎡 گردونه شانس بچرخانید\n"
        "📋 تسک انجام دهید\n\n"
        "⭐ <b>هر ۱ میلیون DP = ۵۰ استارز</b>"
    ),
    2: (
        "📖 <b>دارک پوینت - صفحه ۲/۱۰</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        "💰 <b>راه‌های کسب DP:</b>\n\n"
        "1️⃣ کلمه <code>دارک</code> در گروه\n"
        "2️⃣ زیرمجموعه‌گیری\n"
        "3️⃣ کارخونه (ماین خودکار)\n"
        "4️⃣ بانک (سود ۱۵٪)\n"
        "5️⃣ بازی‌های شانسی\n"
        "6️⃣ گردونه رایگان روزانه\n"
        "7️⃣ تسک‌های عضویت و ماموریت\n"
        "8️⃣ هدیه ثبت‌نام"
    ),
    3: (
        "📖 <b>دارک پوینت - صفحه ۳/۱۰</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        "📊 <b>سیستم ۲۰ سطحی:</b>\n\n"
        "سطح ۱: 0 DP 🌑\n"
        "سطح ۵: 150K DP 🌕\n"
        "سطح ۱۰: 1M DP 🥈\n"
        "سطح ۱۵: 3M DP 🔮\n"
        "سطح ۲۰: 20M DP 🏴\n\n"
        "🎁 هر سطح پاداش ارتقا دارد!"
    ),
    4: (
        "📖 <b>دارک پوینت - صفحه ۴/۱۰</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        "🏭 <b>کارخونه دارکی:</b>\n"
        "افتتاح: 100K | نگهداری: ساعتی 80\n"
        "سطح ۱: 10 DP/دقیقه\n"
        "سطح ۵: 100 DP/دقیقه\n\n"
        "🏦 <b>بانک دارکی:</b>\n"
        "افتتاح: 20K\n"
        "سود ۲۴ ساعته: <b>۱۵٪</b>"
    ),
    5: (
        "📖 <b>دارک پوینت - صفحه ۵/۱۰</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        "💥 <b>بازی انفجار (گروه):</b>\n"
        "<code>انفجار 1000</code>\n"
        "ضریب رشد + Cash Out\n\n"
        "🎲 <b>بازی تاس (گروه):</b>\n"
        "<code>تاس 15000</code>\n"
        "۱ عدد: ۶x | ۲ عدد: ۳x | ۳ عدد: ۱.۵x"
    ),
    6: (
        "📖 <b>دارک پوینت - صفحه ۶/۱۰</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        "🎯 <b>بازی حدس بزن (گروه):</b>\n"
        "کلمه: <code>حدس بزن</code> - حداقل ۳۰K\n"
        "۱ عدد: ۱۰x | ۲ عدد: ۵x\n"
        "۳ عدد: ۲.۵x | ۴ عدد: ۱.۲x\n\n"
        "🎰 <b>بازی کازینو (گروه):</b>\n"
        "کلمه: <code>کازینو</code> - حداقل ۲۵K\n"
        "۳ تا ۷: ۱۵x | +لیمو: ۱۲x | +انگور: ۷x"
    ),
    7: (
        "📖 <b>دارک پوینت - صفحه ۷/۱۰</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        "💣 <b>بازی بمب (گروه):</b>\n"
        "کلمه: <code>بمب</code> - حداقل ۳۵K\n"
        "شبکه ۴×۴ با ۶ بمب تصادفی\n"
        "هر خانه امن: +۰.۴x ضریب\n"
        "بمب: باخت کامل!\n\n"
        "⚽ <b>بازی فوتبال (گروه):</b>\n"
        "کلمه: <code>فوتبال</code> - حداقل ۵۰K\n"
        "تیرک: ۱۲x | تیرک+بیرون: ۷x\n"
        "گل+تیرک+بیرون: ۳x"
    ),
    8: (
        "📖 <b>دارک پوینت - صفحه ۸/۱۰</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        "🎡 <b>گردونه شانس:</b>\n"
        "چرخش رایگان روزانه\n"
        "جایزه: ۵-۱۰۰ هزار DP\n\n"
        "💸 <b>انتقال DP:</b>\n"
        "<code>انتقال 1000</code> (ریپلای)\n"
        "کارمزد: ۱۰٪\n"
        "محدودیت: روزانه ۱۰ انتقال"
    ),
    9: (
        "📖 <b>دارک پوینت - صفحه ۹/۱۰</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        "📋 <b>تسک‌ها:</b>\n\n"
        "• <b>تسک عضویت:</b>\n"
        "عضویت در کانال‌ها → پاداش فوری\n\n"
        "• <b>تسک ماموریت:</b>\n"
        "انجام کار + اسکرین‌شات\n"
        "تایید ادمین → پاداش\n\n"
        "⚠️ <b>شرط خرید پنل:</b>\n"
        "حداقل ۵ زیرمجموعه فعال"
    ),
    10: (
        "📖 <b>دارک پوینت - صفحه ۱۰/۱۰</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        "⭐ <b>برداشت استارز:</b>\n"
        "هر ۱M DP = ۵۰ استارز\n\n"
        "📝 <b>دستورات گروه:</b>\n"
        "<code>دارک</code> | <code>موجودی</code>\n"
        "<code>پروفایل دارکی</code>\n"
        "<code>بازی</code> | <code>انفجار</code>\n"
        "<code>تاس</code> | <code>حدس بزن</code>\n"
        "<code>کازینو</code> | <code>بمب</code>\n"
        "<code>فوتبال</code> | <code>انتقال</code>\n"
        "<code>بانک دارکی</code> | <code>کارخونه دارکی</code>"
    ),
}

async def dp_info_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    page = int(query.data.split("_")[-1])
    text = INFO_PAGES.get(page, "یافت نشد")

    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"dp_info_{page-1}"))
    if page < 10:
        buttons.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"dp_info_{page+1}"))

    keyboard = [buttons] if buttons else []
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="dark_point_menu")])

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))


# ============ TASKS MENU (JOIN & MISSION) ============

async def tasks_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if db.get_setting('tasks_active', '1') != '1':
        await query.answer("❌ این بخش موقتاً غیرفعال می‌باشد.", show_alert=True)
        return

    text = (
        f"📋 <b>بخش انجام تسک</b> 📋\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 با انجام تسک‌ها، دارک پوینت رایگان کسب کنید:\n\n"
        f"📢 <b>تسک عضویت در کانال:</b>\n"
        f"عضویت در کانال → دریافت پاداش خودکار\n\n"
        f"🎖 <b>تسک ماموریت:</b>\n"
        f"انجام ماموریت → ارسال اسکرین‌شات\n"
        f"→ تایید ادمین → دریافت پاداش"
    )

    kb = [
        [InlineKeyboardButton("📢 تسک عضویت در کانال", callback_data="tasks_channel")],
        [InlineKeyboardButton("🎖 تسک ماموریت", callback_data="tasks_mission")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
    ]
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def tasks_channel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    tasks = db.get_tasks(task_type='channel', only_active=True)
    text = "📢 <b>تسک عضویت در کانال</b>\n━━━━━━━━━━━━━━━━━━\n\n"

    if not tasks:
        text += "❌ هیچ تسکی موجود نیست.\n\n<i>بزودی تسک‌های جدید اضافه می‌شود!</i>"
        kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="tasks_menu")]]
    else:
        text += "با عضویت در کانال‌ها، پاداش بگیرید:\n\n"
        kb = []
        for task in tasks:
            completed = db.is_task_completed(user.id, task['task_id'])
            is_full = db.is_task_full(task['task_id'])
            if completed:
                status = "✅"
            elif is_full:
                status = "🔒 پر شد"
            else:
                status = f"💰 {format_number(task['reward'])} DP"
            
            label = f"📢 {task['channel_title']} - {status}"
            if is_full and not completed:
                kb.append([InlineKeyboardButton(label, callback_data="task_full")])
            else:
                kb.append([InlineKeyboardButton(label, callback_data=f"task_view_{task['task_id']}")])
        kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="tasks_menu")])

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def tasks_mission_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    tasks = db.get_tasks(task_type='mission', only_active=True)
    text = "🎖 <b>تسک ماموریت</b>\n━━━━━━━━━━━━━━━━━━\n\n"

    if not tasks:
        text += "❌ هیچ ماموریتی موجود نیست.\n\n<i>بزودی اضافه می‌شود!</i>"
        kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="tasks_menu")]]
    else:
        text += "ماموریت‌های زیر را انجام دهید:\n\n"
        kb = []
        for task in tasks:
            completed = db.is_task_completed(user.id, task['task_id'])
            is_full = db.is_task_full(task['task_id'])
            pending = db.has_pending_mission_request(user.id, task['task_id'])
            if completed:
                status = "✅ انجام شده"
            elif pending:
                status = "⏳ در انتظار تایید"
            elif is_full:
                status = "🔒 ظرفیت پر"
            else:
                status = f"💰 {format_number(task['reward'])} DP"
            
            label = f"🎖 {task['channel_title']} - {status}"
            if (is_full or completed or pending) and not pending:
                kb.append([InlineKeyboardButton(label, callback_data="task_locked")])
            else:
                kb.append([InlineKeyboardButton(label, callback_data=f"task_mission_view_{task['task_id']}")])
        kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="tasks_menu")])

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
        await query.answer("✅ قبلاً انجام داده‌اید!", show_alert=True)
        return

    if db.is_task_full(task_id):
        await query.answer("🔒 ظرفیت تسک پر شده!", show_alert=True)
        return

    await query.answer()
    username = task['channel_username'].replace('@', '')
    capacity_text = ""
    if task['capacity'] > 0:
        remaining_cap = task['capacity'] - task['completed_count']
        capacity_text = f"\n👥 ظرفیت باقیمانده: {remaining_cap}/{task['capacity']}"

    text = (
        f"📢 <b>تسک: عضویت در کانال</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📢 کانال: {task['channel_title']}\n"
        f"🔗 آدرس: {task['channel_username']}\n"
        f"💰 پاداش: <code>{format_number(task['reward'])}</code> DP"
        f"{capacity_text}\n\n"
        f"📝 <b>مراحل:</b>\n"
        f"1️⃣ روی دکمه عضویت کلیک\n"
        f"2️⃣ در کانال عضو شوید\n"
        f"3️⃣ دکمه بررسی را بزنید"
    )

    kb = [
        [InlineKeyboardButton(f"📢 عضویت در {task['channel_title']}", url=f"https://t.me/{username}")],
        [InlineKeyboardButton("✅ بررسی و دریافت پاداش", callback_data=f"task_verify_{task_id}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="tasks_channel")],
    ]
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def task_verify_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    task_id = int(query.data.split("_")[-1])

    task = db.get_task(task_id)
    if not task:
        await query.answer("❌", show_alert=True)
        return
    if db.is_task_completed(user.id, task_id):
        await query.answer("✅ قبلاً دریافت شده!", show_alert=True)
        return
    if db.is_task_full(task_id):
        await query.answer("🔒 ظرفیت پر شده!", show_alert=True)
        return

    try:
        member = await context.bot.get_chat_member(task['channel_username'], user.id)
        if member.status in ['left', 'kicked']:
            await query.answer("❌ هنوز عضو کانال نیستی!", show_alert=True)
            return
    except Exception:
        await query.answer("❌ خطا در بررسی! ربات باید ادمین کانال باشد.", show_alert=True)
        return

    db.add_dark_points(user.id, task['reward'])
    db.mark_task_completed(user.id, task_id)

    await query.answer(f"✅ +{format_number(task['reward'])} DP!", show_alert=True)
    await query.edit_message_text(
        f"✅ <b>تسک انجام شد!</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        f"📢 کانال: {task['channel_title']}\n"
        f"💰 پاداش: +<code>{format_number(task['reward'])}</code> DP\n"
        f"💎 موجودی: <code>{format_number(db.get_balance(user.id))}</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 لیست تسک‌ها", callback_data="tasks_channel")]])
    )


async def task_mission_view_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    task_id = int(query.data.split("_")[-1])

    task = db.get_task(task_id)
    if not task:
        await query.answer("❌", show_alert=True)
        return

    await query.answer()
    capacity_text = ""
    if task['capacity'] > 0:
        remaining_cap = task['capacity'] - task['completed_count']
        capacity_text = f"\n👥 ظرفیت: {remaining_cap}/{task['capacity']}"

    text = (
        f"🎖 <b>تسک ماموریت</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 عنوان: <b>{task['channel_title']}</b>\n"
        f"💰 پاداش: <code>{format_number(task['reward'])}</code> DP"
        f"{capacity_text}\n\n"
        f"📋 <b>توضیحات ماموریت:</b>\n"
        f"{html.escape(task['description'] or 'توضیحی ثبت نشده')}\n\n"
        f"📸 <b>نحوه انجام:</b>\n"
        f"1️⃣ ماموریت را انجام دهید\n"
        f"2️⃣ اسکرین‌شات بگیرید\n"
        f"3️⃣ دکمه زیر را بزنید و عکس را ارسال کنید\n"
        f"4️⃣ منتظر تایید ادمین باشید"
    )

    kb = [
        [InlineKeyboardButton("📸 ارسال اسکرین‌شات", callback_data=f"task_mission_submit_{task_id}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="tasks_mission")],
    ]
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def task_mission_submit_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    task_id = int(query.data.split("_")[-1])

    task = db.get_task(task_id)
    if not task:
        await query.answer("❌", show_alert=True)
        return
    if db.is_task_completed(user.id, task_id):
        await query.answer("✅ انجام شده!", show_alert=True)
        return
    if db.has_pending_mission_request(user.id, task_id):
        await query.answer("⏳ درخواست قبلی شما در انتظار تایید است!", show_alert=True)
        return
    if db.is_task_full(task_id):
        await query.answer("🔒 ظرفیت پر!", show_alert=True)
        return

    await query.answer()
    context.user_data['awaiting_mission_screenshot'] = task_id

    await query.edit_message_text(
        f"📸 <b>ارسال اسکرین‌شات</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        f"🎖 ماموریت: {task['channel_title']}\n"
        f"💰 پاداش: <code>{format_number(task['reward'])}</code> DP\n\n"
        f"📸 لطفاً اسکرین‌شات انجام ماموریت را ارسال کنید.\n"
        f"می‌توانید همراه عکس یک متن توضیحی هم بنویسید.\n\n"
        f"برای لغو: /cancel",
        parse_mode=ParseMode.HTML
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

    text = (
        f"⭐ <b>برداشت استارز تلگرام</b> ⭐\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💎 موجودی: <code>{format_number(balance)}</code> DP\n"
        f"⭐ نرخ: <code>{format_number(stars_price)}</code> DP = {STARS_AMOUNT} استارز\n\n"
    )

    if balance >= stars_price:
        text += "✅ می‌توانید برداشت کنید!"
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
        f"✅ <b>سفارش ثبت شد!</b>\n\n⭐ {STARS_AMOUNT} استارز\n👤 مقصد: <code>{user.id}</code>",
        parse_mode=ParseMode.HTML
    )

    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await context.bot.get_me()
        BOT_USERNAME = me.username

    user_display = f"@{user.username}" if user.username else f"<code>{user.id}</code>"
    log_kb = [[InlineKeyboardButton("🤖 ورود به ربات", url=f"https://t.me/{BOT_USERNAME}")]]
    await send_log(context,
        f"⭐ <b>سفارش برداشت استارز</b>\n\n👤 {user_display}\n🆔 <code>{user.id}</code>\n⭐ {STARS_AMOUNT}\n📍 مقصد: <code>{user.id}</code>\n🆔 <code>{order_id}</code>",
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
    await query.edit_message_text("👥 آیدی مقصد را بفرست:")


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
        f"💎 موجودی: <code>{format_number(balance)}</code>"
    )

    buttons = []
    if balance >= gift_price:
        buttons.append([InlineKeyboardButton("🧸 سفارش گیفت تدی", callback_data="order_gift_teddy")])

    for plan in plans:
        plan_num = plan['key'].split('_')[2]
        name = plan['value']
        price = int(db.get_setting(f'gift_plan_{plan_num}_price', '0'))
        if price > 0:
            buttons.append([InlineKeyboardButton(f"🎁 {name} ({format_number(price)})", callback_data=f"order_gift_custom_{plan_num}")])

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
        f"✅ <b>سفارش ثبت شد!</b>\n🆔 <code>{order_id}</code>",
        parse_mode=ParseMode.HTML
    )

    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await context.bot.get_me()
        BOT_USERNAME = me.username

    user_display = f"@{user.username}" if user.username else f"<code>{user.id}</code>"
    log_kb = [[InlineKeyboardButton("🤖 ورود به ربات", url=f"https://t.me/{BOT_USERNAME}")]]
    await send_log(context,
        f"🧸 سفارش گیفت تدی\n👤 {user_display}\n🆔 <code>{user.id}</code>",
        reply_markup=InlineKeyboardMarkup(log_kb)
    )

    for admin_id in ADMIN_IDS:
        try:
            admin_kb = [[InlineKeyboardButton("💬 پاسخ", callback_data=f"admin_reply_{user.id}")]]
            await context.bot.send_message(
                admin_id,
                f"🧸 گیفت تدی\n👤 {user_display}",
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

    db.create_gift_order(user.id, name, price)
    await query.answer()
    await query.edit_message_text(f"✅ سفارش {name} ثبت شد!", parse_mode=ParseMode.HTML)


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
        f"💰 <b>خرید دارک پوینت</b> 💰\n━━━━━━━━━━━━━━━━━━\n\n"
        f"💎 هر <code>{format_number(dp_amount)}</code> DP\n"
        f"💵 قیمت: <code>{format_number(price_toman)}</code> تومان\n\n"
        f"📩 برای خرید به پشتیبانی پیام دهید."
    )
    kb = [
        [InlineKeyboardButton("📩 پشتیبانی", url=f"https://t.me/{SUPPORT_USERNAME.replace('@', '')}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
    ]
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


# ============ LEADERBOARD, REFERRAL, LIKE ============

async def leaderboard_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    rows = db.get_leaderboard(100)
    text = "🏆 <b>لیدربورد</b>\n━━━━━━━━━━━━━━━━━━\n\n"
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, row in enumerate(rows[:25], 1):
        medal = medals.get(i, f"{i}.")
        name = html.escape(row['first_name'] or row['username'] or str(row['user_id']))
        text += f"{medal} <b>{name}</b> - <code>{format_number(row['dark_points'])}</code>\n"

    kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


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
        f"👥 <b>زیرمجموعه‌گیری</b> 👥\n━━━━━━━━━━━━━━━━━━\n\n"
        f"🔗 لینک شما:\n<code>{ref_link}</code>\n\n"
        f"👥 زیرمجموعه‌ها: <b>{ref_count}</b>\n"
        f"💰 پاداش هر زیرمجموعه: <b>{format_number(ref_reward)}</b> DP\n"
        f"💎 کل درآمد: <code>{format_number(ref_count * ref_reward)}</code>\n\n"
        f"📋 شرایط:\n• حل کپچا ✅\n• عضویت در کانال‌ها ✅\n\n"
        f"⚠️ <b>شرط خرید پنل:</b> حداقل ۵ زیرمجموعه فعال!"
    )
    kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def like_challenge_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    u = db.get_user(user.id)

    if u['like_challenge_active'] and u['like_challenge_until'] > time.time():
        remaining = u['like_challenge_until'] - time.time()
        days = int(remaining // 86400)
        hours = int((remaining % 86400) // 3600)
        text = f"❤️ <b>چالش لایکی فعال</b>\n⏰ {days} روز و {hours} ساعت باقیمانده"
        kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
    else:
        text = f"❤️ <b>چالش لایکی ۷ روزه</b>\n💵 هزینه: {format_number(LIKE_CHALLENGE_COST)} DP"
        kb = [
            [InlineKeyboardButton(f"✅ فعال‌سازی", callback_data="like_activate")],
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
    await query.edit_message_text("✅ چالش لایکی فعال شد!", parse_mode=ParseMode.HTML)


# ============ BUY PANEL (WITH 5 REFERRAL CHECK) ============

# حداقل زیرمجموعه برای خرید پنل
MIN_REFERRALS_FOR_PANEL = 5

async def buy_panel_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    # چک خاموش بودن بخش پنل
    if db.get_setting('buy_panel_active', '1') != '1':
        await query.answer("❌ این بخش موقتاً غیرفعال می‌باشد.", show_alert=True)
        return

    # ⚠️ چک تعداد زیرمجموعه
    ref_count = db.get_referral_count(user.id)
    if ref_count < MIN_REFERRALS_FOR_PANEL:
        needed_refs = MIN_REFERRALS_FOR_PANEL - ref_count
        global BOT_USERNAME
        if not BOT_USERNAME:
            me = await context.bot.get_me()
            BOT_USERNAME = me.username

        ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user.id}"
        
        text = (
            f"⚠️ <b>برای خرید پنل باید حداقل ۵ زیرمجموعه داشته باشید!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 زیرمجموعه‌های فعلی شما: <b>{ref_count}</b>\n"
            f"📉 کسری: <b>{needed_refs}</b> زیرمجموعه\n\n"
            f"🔗 لینک زیرمجموعه‌گیری شما:\n<code>{ref_link}</code>\n\n"
            f"💡 <i>با معرفی دوستان خود این لینک، تعداد زیرمجموعه‌هایتان افزایش می‌یابد.</i>"
        )
        kb = [
            [InlineKeyboardButton("👥 بخش زیرمجموعه‌گیری", callback_data="referral_menu")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
        ]
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))
        return

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
    balance = db.get_balance(user.id)
    text = (
        f"🛒 <b>خرید پنل VPN سنایی</b> 🛒\n━━━━━━━━━━━━━━━━━━\n\n"
        f"💎 موجودی: <code>{format_number(balance)}</code> DP\n"
        f"👥 زیرمجموعه‌ها: <b>{ref_count}</b> ✅\n\n"
        f"<i>یک پلن انتخاب کنید:</i>"
    )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))


async def panel_buy_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    data = query.data

    # ⚠️ دوباره چک زیرمجموعه (برای امنیت بیشتر)
    ref_count = db.get_referral_count(user.id)
    if ref_count < MIN_REFERRALS_FOR_PANEL:
        await query.answer(
            f"❌ برای خرید پنل باید حداقل ۵ زیرمجموعه داشته باشید! (شما: {ref_count})",
            show_alert=True
        )
        return

    if data.startswith("panel_buy_custom_"):
        panel_id = int(data.split("_")[-1])
        conn = db.get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM custom_panels WHERE panel_id = ?", (panel_id,))
        panel = c.fetchone()
        conn.close()
        if not panel:
            await query.answer("❌", show_alert=True)
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
        f"✅ <b>سفارش پنل ثبت شد!</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        f"🛒 پلن: <b>{name}</b>\n"
        f"📊 حجم: <b>{data_limit}</b>\n"
        f"💵 هزینه: <code>{format_number(price)}</code>\n"
        f"🆔 سفارش: <code>{order_id}</code>\n\n"
        f"⏳ <i>ادمین کانفیگ رو از پنل سنایی بزودی برای شما ارسال می‌کند</i>",
        parse_mode=ParseMode.HTML
    )

    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await context.bot.get_me()
        BOT_USERNAME = me.username

    user_display = f"@{user.username}" if user.username else f"<code>{user.id}</code>"
    log_kb = [[InlineKeyboardButton("🤖 ورود به ربات", url=f"https://t.me/{BOT_USERNAME}")]]
    await send_log(context,
        f"🛒 <b>سفارش پنل جدید</b>\n\n👤 {user_display}\n🆔 <code>{user.id}</code>\n👥 زیرمجموعه: {ref_count}\n📦 {name} ({data_limit})\n💵 <code>{format_number(price)}</code>\n🆔 <code>{order_id}</code>",
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
                f"🛒 سفارش پنل\n👤 {user_display}\n🆔 <code>{user.id}</code>\n👥 زیرمجموعه: {ref_count}\n📦 {name} ({data_limit})\n🆔 <code>{order_id}</code>",
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
                        f"❌ <b>گروه باید حداقل {MIN_GROUP_MEMBERS} عضو داشته باشد!</b>\n👥 تعداد فعلی: {count}",
                        parse_mode=ParseMode.HTML
                    )
                    await context.bot.leave_chat(chat.id)
                    return
                
                # چک ادمین بودن
                is_bot_admin = await check_bot_is_admin_in_group(context, chat.id)
                db.add_or_update_group(chat.id, chat.title, count, 1 if is_bot_admin else 0)

                if not is_bot_admin:
                    await update.message.reply_text(
                        "⚠️ <b>برای فعالیت کامل ربات را ادمین کنید!</b>\n"
                        "━━━━━━━━━━━━━━━━━━\n\n"
                        "🔧 لطفاً ربات را ادمین گروه کنید تا بتواند کار کند.\n"
                        "دسترسی‌های لازم:\n"
                        "✅ حذف پیام\n"
                        "✅ ارسال پیام\n\n"
                        "💡 پس از ادمین شدن، دستور <code>دارک</code> را امتحان کنید.",
                        parse_mode=ParseMode.HTML
                    )
                    return

                await update.message.reply_text(
                    "🏴 ✨ <b>ربات دارک پوینت با موفقیت فعال شد!</b> ✨ 🏴\n"
                    "━━━━━━━━━━━━━━━━━━\n\n"
                    "📝 <b>دستورات کسب DP:</b>\n"
                    "• <code>دارک</code> - دریافت دارک پوینت\n"
                    "• <code>موجودی</code> - موجودی شما\n"
                    "• <code>پروفایل دارکی</code>\n\n"
                    "🎮 <b>بازی‌های هیجان‌انگیز:</b>\n"
                    "• <code>بازی 1000</code> - بازی دو نفره\n"
                    "• <code>انفجار 1000</code> - بازی انفجار\n"
                    "• <code>تاس 15000</code> - بازی تاس\n"
                    "• <code>حدس بزن</code> - بازی حدس عدد\n"
                    "• <code>کازینو</code> - کازینو\n"
                    "• <code>بمب</code> - بازی بمب\n"
                    "• <code>فوتبال</code> - بازی فوتبال\n\n"
                    "🏦 <b>سایر:</b>\n"
                    "• <code>انتقال 1000</code> - انتقال DP\n"
                    "• <code>بانک دارکی</code>\n"
                    "• <code>کارخونه دارکی</code>\n"
                    "• <code>لیدربورد</code>",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Group error: {e}")


async def check_group_requirements(update, context):
    """چک شرایط گروه قبل از اجرای دستور - اعضا و ادمین بودن"""
    chat = update.effective_chat
    
    try:
        # چک تعداد اعضا
        count = await context.bot.get_chat_member_count(chat.id)
        if count < MIN_GROUP_MEMBERS:
            await update.message.reply_text(
                f"❌ گروه باید حداقل {MIN_GROUP_MEMBERS} عضو داشته باشد!",
                parse_mode=ParseMode.HTML
            )
            return False
        
        # چک ادمین بودن ربات
        is_bot_admin = await check_bot_is_admin_in_group(context, chat.id)
        if not is_bot_admin:
            await update.message.reply_text(
                "⚠️ <b>اول ربات را در گروه ادمین کنید!</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                "🔧 ربات برای عملکرد صحیح باید ادمین باشد.",
                parse_mode=ParseMode.HTML
            )
            db.update_group_admin_status(chat.id, 0)
            return False
        
        # آپدیت گروه
        db.add_or_update_group(chat.id, chat.title, count, 1)
        return True
    except Exception as e:
        logger.error(f"Check group error: {e}")
        return True  # در صورت خطا، اجازه بده


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

    # چک خاموش بودن ربات برای کاربران
    if not is_bot_active() and not is_admin(user.id):
        return

    # دستور ایدی عددی - فقط ادمین با ریپلای
    if text == 'ایدی عددی' and is_admin(user.id) and update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        target_name = html.escape(target_user.first_name or "کاربر")
        await update.message.reply_text(
            f"👤 <b>اطلاعات کاربر</b>\n━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 نام: <b>{target_name}</b>\n"
            f"🆔 شناسه عددی: <code>{target_user.id}</code>\n"
            f"📛 یوزرنیم: @{target_user.username or 'ندارد'}",
            parse_mode=ParseMode.HTML
        )
        return

    # اول چک کن ریپلای برای بازی‌هاست
    if update.message.reply_to_message:
        handled = await handle_group_reply_for_games(update, context)
        if handled:
            return

    # چک شرایط گروه برای دستورات بازی و اصلی
    game_commands = ['دارک', 'دارک کانفیگ', 'موجودی', 'پروفایل دارکی', 'لیدربورد',
                     'بانک دارکی', 'کارخونه دارکی', 'حدس بزن', 'کازینو', 'بمب', 'فوتبال', 'انفجار']
    game_prefixes = ['بازی', 'انفجار', 'تاس', 'انتقال ']
    
    is_game_cmd = False
    for cmd in game_commands:
        if text == cmd or text.startswith(cmd + ' '):
            is_game_cmd = True
            break
    if not is_game_cmd:
        for prefix in game_prefixes:
            if text.startswith(prefix):
                is_game_cmd = True
                break

    if is_game_cmd:
        if not await check_group_requirements(update, context):
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
    elif text == 'فوتبال' or text.startswith('فوتبال'):
        await handle_football_start(update, context)
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
            f"⏳ <b>لطفاً کمی صبر کنید!</b>\n━━━━━━━━━━━━━━━━━━\n\n"
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
            f"\n\n🎊 🎉 <b>تبریک! ارتقا به سطح {new_level}!</b> 🎉 🎊\n"
            f"🏅 لقب جدید: {get_level_title(new_level)}\n"
            f"🎁 پاداش: +<code>{format_number(reward)}</code> DP"
        )

    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await context.bot.get_me()
        BOT_USERNAME = me.username

    kb = [[InlineKeyboardButton("🏴 ورود به ربات دارک پوینت", url=f"https://t.me/{BOT_USERNAME}")]]
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def handle_balance_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """موجودی با دکمه شیشه‌ای"""
    user = update.effective_user
    balance = db.get_balance(user.id)
    level = db.get_level(user.id)
    safe_name = html.escape(user.first_name or "کاربر")

    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await context.bot.get_me()
        BOT_USERNAME = me.username

    kb = [
        [InlineKeyboardButton(f"💎 موجودی من: {format_number(balance)} DP 💎", callback_data=f"show_my_balance_{user.id}")],
        [InlineKeyboardButton("🏴 ورود به ربات دارک پوینت", url=f"https://t.me/{BOT_USERNAME}")]
    ]
    
    await update.message.reply_text(
        f"💎 ✨ <b>موجودی دارک پوینت</b> ✨ 💎\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 کاربر: <b>{safe_name}</b>\n"
        f"🆔 شناسه: <code>{user.id}</code>\n\n"
        f"💰 موجودی: <code>{format_number(balance)}</code> DP\n"
        f"📊 سطح: {level} | {get_level_title(level)}\n"
        f"━━━━━━━━━━━━━━━━━━",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def show_my_balance_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پاسخ به دکمه شیشه‌ای موجودی"""
    query = update.callback_query
    user_id = int(query.data.split("_")[-1])
    
    if query.from_user.id != user_id:
        await query.answer("❌ این دکمه برای شما نیست!", show_alert=True)
        return
    
    balance = db.get_balance(user_id)
    level = db.get_level(user_id)
    
    await query.answer(
        f"💎 موجودی: {format_number(balance)} DP\n📊 سطح: {level} ({get_level_title(level)})",
        show_alert=True
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
        factory_info = f"🏭 کارخونه: سطح {f_level} ({mine_rate} DP/دقیقه) ✅\n"
    elif u['factory_level'] > 0:
        factory_info = f"🏭 کارخونه: <b>غیرفعال</b> (سطح {u['factory_level']})\n"

    bank_info = ""
    if u['bank_account']:
        bank_info = f"🏦 کارت بانک: <code>{u['bank_card']}</code>\n💰 موجودی بانک: <code>{format_number(u['bank_balance'])}</code>\n"

    stars_price = int(db.get_setting('stars_price', '1000000'))
    stars_can = balance // stars_price
    if stars_can > 0:
        stars_text = f"⭐ قابل برداشت: {stars_can * 50} استارز\n"
    else:
        stars_text = f"⭐ تا استارز بعدی: <code>{format_number(stars_price - balance)}</code>\n"

    crash_played = u['crash_games_played']
    crash_won = u['crash_games_won']
    win_rate = int((crash_won / crash_played * 100) if crash_played > 0 else 0)

    text = (
        f"🏴 ✨ <b>پروفایل دارکی</b> ✨ 🏴\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 نام: <b>{safe_name}</b>\n"
        f"🆔 شناسه: <code>{user.id}</code>\n"
        f"📛 یوزرنیم: @{user.username or 'ندارد'}\n"
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
        f"👥 زیرمجموعه‌ها: {refs}\n"
        f"{stars_text}"
        f"{factory_info}"
        f"{bank_info}"
        f"💥 انفجار: {crash_won}/{crash_played} ({win_rate}%)\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏴 <i>دارک پوینت | قدرت تاریکی</i>"
    )

    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await context.bot.get_me()
        BOT_USERNAME = me.username

    kb = [[InlineKeyboardButton("🏴 ورود به ربات", url=f"https://t.me/{BOT_USERNAME}")]]
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def handle_leaderboard_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.get_leaderboard(10)
    text = "🏆 <b>لیدربورد دارک پوینت</b> 🏆\n━━━━━━━━━━━━━━━━━━\n\n"
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, row in enumerate(rows, 1):
        medal = medals.get(i, f"{i}.")
        name = html.escape(row['first_name'] or str(row['user_id']))
        text += f"{medal} <b>{name}</b> - <code>{format_number(row['dark_points'])}</code>\n"

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
        await update.message.reply_text(f"❌ حداقل: <code>{format_number(MIN_GAME_AMOUNT)}</code> DP", parse_mode=ParseMode.HTML)
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
        f"🎮 ✨ <b>بازی جدید!</b> ✨ 🎮\n━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 سازنده: {get_user_display(user)}\n"
        f"💰 ورود: <code>{format_number(amount)}</code>\n"
        f"🏆 جایزه: <code>{format_number(amount * 2)}</code>\n\n"
        f"⏳ منتظر حریف...\n⚠️ در صورت عدم شرکت، بعد از ۱۰ دقیقه خودکار لغو می‌شود",
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

    # تایمر خودکار برای لغو
    asyncio.create_task(auto_cancel_game(context, game_id, chat.id, msg.message_id))


async def auto_cancel_game(context, game_id, chat_id, message_id):
    """لغو خودکار بازی بعد از ۱۰ دقیقه"""
    await asyncio.sleep(GAME_TIMEOUT)
    game = db.get_game(game_id)
    if game and game['status'] == 'waiting':
        db.add_dark_points(game['creator_id'], game['amount'])
        db.cancel_game(game_id)
        try:
            await context.bot.edit_message_text(
                f"⏰ <b>بازی به دلیل عدم شرکت خودکار لغو شد</b>\n💰 مبلغ بازگردانده شد",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass


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
        f"🎮 ✨ <b>نتیجه بازی!</b> ✨ 🎮\n━━━━━━━━━━━━━━━━━━\n\n"
        f"🏆 <b>برنده:</b> {winner_display}\n💰 جایزه: +<code>{format_number(prize)}</code>\n\n"
        f"💔 <b>بازنده:</b> {loser_display}\n━━━━━━━━━━━━━━━━━━\n"
        f"🎲 <i>برنده کاملاً تصادفی</i>",
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
        f"❌ لغو شد\n💰 <code>{format_number(game['amount'])}</code> بازگردانده شد",
        parse_mode=ParseMode.HTML
    )


# ============ TRANSFER WITH LIMIT ============

async def handle_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()

    # چک محدودیت انتقال
    can_tr, remaining = db.can_transfer(user.id)
    if not can_tr:
        hours = int(remaining // 3600)
        mins = int((remaining % 3600) // 60)
        await update.message.reply_text(
            f"⚠️ <b>سقف انتقال روزانه پر شده!</b>\n━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 سقف روزانه: {MAX_DAILY_TRANSFERS} انتقال\n"
            f"⏰ بازگشایی تا: {hours}h {mins}m",
            parse_mode=ParseMode.HTML
        )
        return

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
                await update.message.reply_text("❌ کاربر مقصد مسدود شده!")
                return

            fee = int(amount * TRANSFER_FEE)
            total_cost = amount + fee
            balance = db.get_balance(user.id)

            if balance < total_cost:
                await update.message.reply_text(
                    f"❌ <b>موجودی ناکافی!</b>\n━━━━━━━━━━━━━━━━━━\n"
                    f"💰 مبلغ: <code>{format_number(amount)}</code>\n"
                    f"💸 کارمزد ۱۰٪: <code>{format_number(fee)}</code>\n"
                    f"📊 کل نیاز: <code>{format_number(total_cost)}</code>\n"
                    f"💎 موجودی: <code>{format_number(balance)}</code>",
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
            db.increment_transfer_count(user.id)

            # محاسبه باقی مانده
            u = db.get_user(user.id)
            remaining_transfers = MAX_DAILY_TRANSFERS - u['transfer_count_today']

            target = update.message.reply_to_message.from_user
            target_display = f"@{target.username}" if target.username else f"<code>{target.id}</code>"

            await update.message.reply_text(
                f"✅ ✨ <b>انتقال موفق!</b> ✨ ✅\n━━━━━━━━━━━━━━━━━━\n\n"
                f"💰 مبلغ: <code>{format_number(amount)}</code>\n"
                f"💸 کارمزد: <code>{format_number(fee)}</code>\n"
                f"👤 مقصد: {target_display}\n"
                f"💎 موجودی: <code>{format_number(db.get_balance(user.id))}</code>\n\n"
                f"📊 انتقال‌های امروز: {u['transfer_count_today']}/{MAX_DAILY_TRANSFERS}",
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
            await update.message.reply_text("❌ کاربر مقصد یافت نشد!")
            return

        fee = int(amount * TRANSFER_FEE)
        if db.get_balance(user.id) < amount + fee:
            await update.message.reply_text("❌ موجودی ناکافی!")
            return

        db.remove_dark_points(user.id, amount + fee)
        db.add_dark_points(target_id, amount)
        db.record_transfer(user.id, target_id, amount, fee)
        db.increment_transfer_count(user.id)

        u = db.get_user(user.id)
        await update.message.reply_text(
            f"✅ انتقال موفق!\n💰 <code>{format_number(amount)}</code> به <code>{target_id}</code>\n📊 انتقال‌های امروز: {u['transfer_count_today']}/{MAX_DAILY_TRANSFERS}",
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
            f"🏦 ✨ <b>بانک دارکی</b> ✨ 🏦\n━━━━━━━━━━━━━━━━━━\n\n"
            f"❌ حسابی ندارید\n\n"
            f"💵 افتتاح: <code>{format_number(BANK_OPEN_COST)}</code>\n"
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
                buttons.append([InlineKeyboardButton("💸 برداشت (با سود ۱۵٪)", callback_data="bank_withdraw")])
            else:
                remaining = max(0, 86400 - elapsed)
                h = int(remaining // 3600)
                m = int((remaining % 3600) // 60)
                buttons.append([InlineKeyboardButton(f"⏰ {h}h {m}m تا سود", callback_data="bank_wait")])
            buttons.append([InlineKeyboardButton("💰 واریز بیشتر", callback_data="bank_deposit")])
            buttons.append([InlineKeyboardButton("💸 برداشت بدون سود", callback_data="bank_withdraw")])

        text = (
            f"🏦 ✨ <b>بانک دارکی</b> ✨ 🏦\n━━━━━━━━━━━━━━━━━━\n\n"
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
        f"💰 واریز\n💎 موجودی: <code>{format_number(balance)}</code>\n\nمبلغ را در پیوی بفرست:",
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


# ============ FACTORY ============

async def handle_factory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = db.get_user(user.id)

    if u['factory_level'] == 0:
        kb = [[InlineKeyboardButton(f"🏭 افتتاح ({format_number(FACTORY_OPEN_COST)})", callback_data="factory_open")]]
        await update.message.reply_text(
            f"🏭 <b>کارخونه دارکی</b>\n━━━━━━━━━━━━━━━━━━\n\n"
            f"❌ کارخونه ندارید\n\n"
            f"💵 افتتاح: <code>{format_number(FACTORY_OPEN_COST)}</code>\n"
            f"🔧 نگهداری: ساعتی ۸۰ DP",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    if not u['factory_active']:
        f_level = u['factory_level']
        mine_rate = FACTORY_LEVELS[f_level]['mine_per_min']
        kb = [
            [InlineKeyboardButton("🔄 فعال‌سازی مجدد", callback_data="factory_reactivate")],
            [InlineKeyboardButton("💰 جمع‌آوری", callback_data="factory_collect")],
        ]
        await update.message.reply_text(
            f"🏭 <b>کارخونه غیرفعال</b>\n━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 سطح: {f_level}\n⚡ نرخ: {mine_rate} DP/دقیقه\n"
            f"⚠️ <b>کمبود موجودی!</b>\n\n"
            f"💎 موجودی: <code>{format_number(db.get_balance(user.id))}</code>",
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
        buttons.append([InlineKeyboardButton(f"⬆️ ارتقا به {f_level+1} ({format_number(upgrade_cost)})", callback_data="factory_upgrade")])
    buttons.append([InlineKeyboardButton("💰 جمع‌آوری", callback_data="factory_collect")])

    text = (
        f"🏭 <b>کارخونه دارکی</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 سطح: <b>{f_level}</b>\n⚡ نرخ: <b>{mine_rate}</b> DP/دقیقه\n"
        f"📋 ✅ فعال\n"
    )
    if mined > 0:
        text += f"💰 جمع‌آوری: +<code>{format_number(mined)}</code>\n"
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
    await query.edit_message_text(f"✅ کارخونه افتتاح شد!", parse_mode=ParseMode.HTML)


async def factory_reactivate_cb(update, context):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    u = db.get_user(user.id)
    if not u or u['factory_level'] == 0:
        return
    if u['factory_active']:
        await query.answer("✅ فعال است!", show_alert=True)
        return

    if db.get_balance(user.id) < FACTORY_HOURLY_MAINTENANCE:
        await query.answer(f"❌ حداقل {FACTORY_HOURLY_MAINTENANCE} DP!", show_alert=True)
        return

    db.reactivate_factory(user.id)
    await query.edit_message_text(
        f"✅ <b>کارخونه دوباره فعال شد!</b>\n🏭 سطح: {u['factory_level']}",
        parse_mode=ParseMode.HTML
    )


async def factory_upgrade_cb(update, context):
    query = update.callback_query
    user = query.from_user
    await query.answer()
    u = db.get_user(user.id)
    if not u or u['factory_level'] >= 5:
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
        await update.message.reply_text(f"❌ حداقل: <code>{format_number(CRASH_MIN_BET)}</code>", parse_mode=ParseMode.HTML)
        return
    if amount > CRASH_MAX_BET:
        await update.message.reply_text(f"❌ حداکثر: <code>{format_number(CRASH_MAX_BET)}</code>", parse_mode=ParseMode.HTML)
        return

    balance = db.get_balance(user.id)
    if balance < amount:
        await update.message.reply_text(f"❌ موجودی ناکافی!", parse_mode=ParseMode.HTML)
        return

    db.remove_dark_points(user.id, amount)
    crash_point = generate_crash_point()

    msg = await update.message.reply_text(
        f"💥 ✨ <b>بازی انفجار شروع شد!</b> ✨ 💥\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 بازیکن: {get_user_display(user)}\n"
        f"💰 شرط: <code>{format_number(amount)}</code>\n\n"
        f"🚀 ضریب: <code>1.00x</code>\n"
        f"⚡️ آماده شوید...",
        parse_mode=ParseMode.HTML
    )

    game_id = db.create_crash_game(user.id, amount, crash_point, update.effective_chat.id, msg.message_id)

    await msg.edit_text(
        f"💥 <b>بازی انفجار زنده</b> 💥\n━━━━━━━━━━━━━━━━━━\n\n"
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
                f"💥 <b>بازی انفجار زنده</b> 💥\n━━━━━━━━━━━━━━━━━━\n\n"
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
                f"💥💥💥 <b>منفجر شد!</b> 💥💥💥\n━━━━━━━━━━━━━━━━━━\n\n"
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
            f"🎉 🏆 <b>برنده شدی!</b> 🏆 🎉\n━━━━━━━━━━━━━━━━━━\n\n"
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

async def cleanup_game_dict(game_dict, key, delay):
    await asyncio.sleep(delay)
    if key in game_dict:
        del game_dict[key]


async def auto_cancel_dice(game_key, delay=GAME_TIMEOUT):
    """لغو خودکار بازی تاس بعد از ۱۰ دقیقه عدم فعالیت"""
    await asyncio.sleep(delay)
    game = dice_games.get(game_key)
    if game and game['status'] == 'picking':
        # برگرداندن پول
        db.add_dark_points(game['user_id'], game['amount'])
        game['status'] = 'auto_cancelled'
        if game_key in dice_games:
            del dice_games[game_key]


async def handle_dice_game_group(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: int):
    user = update.effective_user

    if db.get_setting('dice_active', '1') != '1':
        await update.message.reply_text("❌ این بخش موقتاً غیرفعال می‌باشد.")
        return

    # چک بازی باز
    for k, g in list(dice_games.items()):
        if g['user_id'] == user.id and g['status'] == 'picking':
            await update.message.reply_text("❌ شما یک بازی تاس باز دارید!")
            return

    if amount < DICE_MIN_BET:
        await update.message.reply_text(
            f"❌ حداقل: <code>{format_number(DICE_MIN_BET)}</code>",
            parse_mode=ParseMode.HTML
        )
        return

    balance = db.get_balance(user.id)
    if balance < amount:
        await update.message.reply_text(f"❌ موجودی ناکافی!")
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
        f"🎲 ✨ <b>بازی تاس دارکی</b> ✨ 🎲\n━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 بازیکن: {get_user_display(user)}\n"
        f"💰 شرط: <code>{format_number(amount)}</code>\n\n"
        f"🎯 <b>ضرایب:</b>\n"
        f"• ۱ عدد: <b>۶ برابر</b> 🥇\n"
        f"• ۲ عدد: <b>۳ برابر</b> 🥈\n"
        f"• ۳ عدد: <b>۱.۵ برابر</b> 🥉\n\n"
        f"📌 اعداد انتخابی: <code>هیچ</code>\n"
        f"⏰ در صورت عدم فعالیت ۱۰ دقیقه خودکار لغو می‌شود",
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

    asyncio.create_task(auto_cancel_dice(game_key))


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
            f"🎲 ✨ <b>بازی تاس دارکی</b> ✨ 🎲\n━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 {get_user_display(user)}\n"
            f"💰 شرط: <code>{format_number(game['amount'])}</code>\n\n"
            f"🎯 ضرایب:\n• ۱ عدد: ۶x | ۲ عدد: ۳x | ۳ عدد: ۱.۵x\n\n"
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
        await query.answer("❌", show_alert=True)
        return
    if len(game['picks']) == 0:
        await query.answer("⚠️ حداقل یک عدد انتخاب کنید!", show_alert=True)
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
            f"🎉 🏆 <b>برنده شدی!</b> 🏆 🎉\n━━━━━━━━━━━━━━━━━━\n\n"
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
            f"💔 <b>باختی!</b> 💔\n━━━━━━━━━━━━━━━━━━\n\n"
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


# ============ GUESS GAME ============

guess_games = {}

async def auto_cancel_guess(game_key, delay=GAME_TIMEOUT):
    await asyncio.sleep(delay)
    game = guess_games.get(game_key)
    if game and game['status'] in ['picking', 'awaiting_bet']:
        if game['amount'] > 0:
            db.add_dark_points(game['user_id'], game['amount'])
        game['status'] = 'auto_cancelled'
        if game_key in guess_games:
            del guess_games[game_key]


async def handle_guess_game_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if db.get_setting('guess_active', '1') != '1':
        await update.message.reply_text("❌ این بخش موقتاً غیرفعال می‌باشد.")
        return

    for k, g in list(guess_games.items()):
        if g['user_id'] == user.id and g['status'] in ['awaiting_bet', 'picking']:
            await update.message.reply_text("❌ شما یک بازی حدس بزن باز دارید!")
            return

    balance = db.get_balance(user.id)
    if balance < GUESS_MIN_BET:
        await update.message.reply_text(
            f"❌ موجودی ناکافی!\n💵 حداقل: <code>{format_number(GUESS_MIN_BET)}</code>",
            parse_mode=ParseMode.HTML
        )
        return

    msg = await update.message.reply_text(
        f"🎯 ✨ <b>بازی حدس بزن</b> ✨ 🎯\n━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 بازیکن: {get_user_display(user)}\n\n"
        f"🎯 <b>عدد بین ۱ تا ۱۰ حدس بزن!</b>\n\n"
        f"💰 حداقل شرط: <code>{format_number(GUESS_MIN_BET)}</code> DP\n\n"
        f"📊 <b>ضرایب:</b>\n"
        f"• ۱ عدد: ۱۰x 🥇 | ۲ عدد: ۵x 🥈\n"
        f"• ۳ عدد: ۲.۵x 🥉 | ۴ عدد: ۱.۲x\n\n"
        f"✏️ <b>مبلغ شرط را روی این پیام ریپلای کن:</b>\n"
        f"⏰ در صورت عدم فعالیت ۱۰ دقیقه خودکار لغو می‌شود",
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
    asyncio.create_task(auto_cancel_guess(game_key))


async def handle_guess_bet_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await update.message.reply_text("❌ عدد!")
        return True

    if amount < GUESS_MIN_BET:
        await update.message.reply_text(f"❌ حداقل: <code>{format_number(GUESS_MIN_BET)}</code>", parse_mode=ParseMode.HTML)
        return True

    if db.get_balance(user.id) < amount:
        await update.message.reply_text("❌ موجودی ناکافی!")
        return True

    db.remove_dark_points(user.id, amount)
    game = guess_games[game_key]
    game['amount'] = amount
    game['status'] = 'picking'

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
        [InlineKeyboardButton("🎯 تایید انتخاب", callback_data="guess_confirm")],
        [InlineKeyboardButton("❌ لغو", callback_data="guess_cancel")],
    ]

    new_msg = await update.message.reply_text(
        f"🎯 <b>بازی حدس بزن</b> 🎯\n━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 {get_user_display(user)}\n"
        f"💰 شرط: <code>{format_number(amount)}</code>\n\n"
        f"📊 ضرایب:\n• ۱: ۱۰x | ۲: ۵x | ۳: ۲.۵x | ۴: ۱.۲x\n\n"
        f"📌 انتخابی: <code>هیچ</code>\n"
        f"⚡️ حداکثر ۴ عدد انتخاب + تایید",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(kb)
    )

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
        await query.answer("❌", show_alert=True)
        return

    game = guess_games[game_key]
    if game['user_id'] != user.id:
        await query.answer("❌ این بازی شما نیست!", show_alert=True)
        return
    if game['status'] != 'picking':
        return

    picks = game['picks']
    if picked in picks:
        picks.remove(picked)
        await query.answer(f"❌ {picked} حذف شد")
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
            f"🎯 <b>بازی حدس بزن</b>\n━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 {get_user_display(user)}\n"
            f"💰 شرط: <code>{format_number(game['amount'])}</code>\n\n"
            f"📊 ۱: ۱۰x | ۲: ۵x | ۳: ۲.۵x | ۴: ۱.۲x\n\n"
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
        return

    game = guess_games[game_key]
    if game['user_id'] != user.id:
        await query.answer("❌ این بازی شما نیست!", show_alert=True)
        return
    if game['status'] != 'picking':
        return
    if len(game['picks']) == 0:
        await query.answer("⚠️ حداقل یک عدد!", show_alert=True)
        return

    game['status'] = 'rolling'
    await query.answer("🎯 انتخاب عدد...")

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
            f"🎉 🏆 <b>برنده شدی!</b> 🏆 🎉\n━━━━━━━━━━━━━━━━━━\n\n"
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
            f"💔 <b>باختی!</b> 💔\n━━━━━━━━━━━━━━━━━━\n\n"
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
        del guess_games[game_key]


# ============ CASINO ============

casino_games = {}

async def auto_cancel_casino(game_key, delay=GAME_TIMEOUT):
    await asyncio.sleep(delay)
    game = casino_games.get(game_key)
    if game and game['status'] in ['picking', 'awaiting_bet']:
        if game['amount'] > 0:
            db.add_dark_points(game['user_id'], game['amount'])
        game['status'] = 'auto_cancelled'
        if game_key in casino_games:
            del casino_games[game_key]


async def handle_casino_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if db.get_setting('casino_active', '1') != '1':
        await update.message.reply_text("❌ این بخش موقتاً غیرفعال می‌باشد.")
        return

    for k, g in list(casino_games.items()):
        if g['user_id'] == user.id and g['status'] in ['awaiting_bet', 'picking']:
            await update.message.reply_text("❌ شما یک کازینو باز دارید!")
            return

    balance = db.get_balance(user.id)
    if balance < CASINO_MIN_BET:
        await update.message.reply_text(f"❌ حداقل: <code>{format_number(CASINO_MIN_BET)}</code>", parse_mode=ParseMode.HTML)
        return

    msg = await update.message.reply_text(
        f"🎰 ✨ <b>بازی کازینو دارکی</b> ✨ 🎰\n━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 {get_user_display(user)}\n\n"
        f"🎯 <b>حدس بزن چه چیزی میاد!</b>\n\n"
        f"💰 حداقل شرط: <code>{format_number(CASINO_MIN_BET)}</code>\n\n"
        f"📊 <b>ضرایب:</b>\n"
        f"• فقط 7️⃣: <b>۱۵ برابر</b>\n"
        f"• 7️⃣ + 🍋: <b>۱۲ برابر</b>\n"
        f"• 7️⃣ + 🍋 + 🍇: <b>۷ برابر</b>\n\n"
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
        'picks': [],
        'amount': 0,
        'created_at': time.time(),
    }
    asyncio.create_task(auto_cancel_casino(game_key))


async def handle_casino_bet_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await update.message.reply_text("❌ عدد!")
        return True

    if amount < CASINO_MIN_BET:
        await update.message.reply_text(f"❌ حداقل: <code>{format_number(CASINO_MIN_BET)}</code>", parse_mode=ParseMode.HTML)
        return True

    if db.get_balance(user.id) < amount:
        await update.message.reply_text("❌ موجودی ناکافی!")
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
        f"🎰 <b>بازی کازینو</b> 🎰\n━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 {get_user_display(user)}\n"
        f"💰 شرط: <code>{format_number(amount)}</code>\n\n"
        f"📊 ضرایب:\n• 7️⃣: ۱۵x | 7️⃣+🍋: ۱۲x | 7️⃣+🍋+🍇: ۷x\n\n"
        f"📌 انتخابی: <code>هیچ</code>",
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
    picked = query.data.split("_")[-1]

    game_key = None
    for k, g in list(casino_games.items()):
        if g['message_id'] == query.message.message_id and g['chat_id'] == query.message.chat_id:
            game_key = k
            break

    if not game_key:
        return

    game = casino_games[game_key]
    if game['user_id'] != user.id:
        await query.answer("❌", show_alert=True)
        return
    if game['status'] != 'picking':
        return

    picks = game['picks']
    if picked in picks:
        picks.remove(picked)
        await query.answer("❌ حذف شد")
    else:
        if len(picks) >= 3:
            await query.answer("⚠️ حداکثر ۳!", show_alert=True)
            return
        picks.append(picked)
        await query.answer("✅ اضافه شد")

    game['picks'] = picks
    display_map = {'7': '7️⃣', 'lemon': '🍋', 'grape': '🍇'}
    picks_display = " + ".join([display_map[p] for p in picks]) if picks else "هیچ"

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
        lbl = f"{emoji} {label}"
        if name in picks:
            lbl = f"✅ {lbl}"
        return InlineKeyboardButton(lbl, callback_data=f"casino_pick_{name}")

    kb = [
        [get_btn('7', '۳ تا هفت')],
        [get_btn('lemon', '۳ تا لیمو')],
        [get_btn('grape', '۳ تا انگور')],
        [InlineKeyboardButton("🎰 چرخش!", callback_data="casino_spin")],
        [InlineKeyboardButton("❌ لغو", callback_data="casino_cancel")],
    ]

    try:
        await query.edit_message_text(
            f"🎰 <b>بازی کازینو</b>\n━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 {get_user_display(user)}\n"
            f"💰 شرط: <code>{format_number(game['amount'])}</code>\n\n"
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
        return
    if game['status'] != 'picking' or len(game['picks']) == 0:
        await query.answer("⚠️ انتخاب کنید!", show_alert=True)
        return

    picks_set = set(game['picks'])
    valid_combos = [{'7'}, {'7', 'lemon'}, {'7', 'lemon', 'grape'}]
    if picks_set not in valid_combos:
        await query.answer("❌ ترکیب نامعتبر!", show_alert=True)
        return

    game['status'] = 'rolling'
    await query.answer("🎰 چرخش...")

    casino_msg = await context.bot.send_dice(chat_id=game['chat_id'], emoji='🎰')
    casino_value = casino_msg.dice.value
    await asyncio.sleep(3)

    winning_map = {1: 'bar', 22: 'grape', 43: 'lemon', 64: 'seven'}
    result_symbol = winning_map.get(casino_value, None)
    result_display = {
        'seven': '7️⃣ 7️⃣ 7️⃣', 'lemon': '🍋 🍋 🍋',
        'grape': '🍇 🍇 🍇', 'bar': 'BAR BAR BAR', None: 'ترکیب مختلف'
    }
    result_str = result_display.get(result_symbol, 'ترکیب مختلف')

    won = False
    multiplier = 0
    mult_display = ""
    picks = game['picks']
    amount = game['amount']

    if picks_set == {'7'} and result_symbol == 'seven':
        won = True; multiplier = 15.0; mult_display = "۱۵ برابر"
    elif picks_set == {'7', 'lemon'} and result_symbol in ['seven', 'lemon']:
        won = True; multiplier = 12.0; mult_display = "۱۲ برابر"
    elif picks_set == {'7', 'lemon', 'grape'} and result_symbol in ['seven', 'lemon', 'grape']:
        won = True; multiplier = 7.0; mult_display = "۷ برابر"

    display_map = {'7': '7️⃣', 'lemon': '🍋', 'grape': '🍇'}
    picks_display = " + ".join([display_map[p] for p in picks])

    if won:
        prize = int(amount * multiplier)
        db.add_dark_points(user.id, prize)
        text = (
            f"🎉 🎰 <b>جکپات!</b> 🎰 🎉\n━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 {get_user_display(user)}\n💰 شرط: <code>{format_number(amount)}</code>\n\n"
            f"🎰 نتیجه: <b>{result_str}</b>\n📌 انتخاب: {picks_display}\n💎 ضریب: {mult_display}\n\n"
            f"🏆 برد: +<code>{format_number(prize)}</code>\n💰 موجودی: <code>{format_number(db.get_balance(user.id))}</code>"
        )
    else:
        text = (
            f"💔 <b>باختی!</b> 💔\n━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 {get_user_display(user)}\n💰 شرط: <code>{format_number(amount)}</code>\n\n"
            f"🎰 نتیجه: {result_str}\n📌 انتخاب: {picks_display}"
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
        return
    if game['amount'] > 0:
        db.add_dark_points(user.id, game['amount'])
    game['status'] = 'cancelled'
    await query.edit_message_text(f"❌ لغو شد", parse_mode=ParseMode.HTML)
    if game_key in casino_games:
        del casino_games[game_key]# ============ BOMB GAME (6 BOMBS - 0.4x PER SAFE) ============

bomb_games = {}

async def auto_cancel_bomb(game_key, delay=GAME_TIMEOUT):
    await asyncio.sleep(delay)
    game = bomb_games.get(game_key)
    if game and game['status'] in ['playing', 'awaiting_bet']:
        if len(game.get('revealed', [])) == 0 and game['amount'] > 0:
            db.add_dark_points(game['user_id'], game['amount'])
        game['status'] = 'auto_cancelled'
        if game_key in bomb_games:
            del bomb_games[game_key]


async def handle_bomb_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if db.get_setting('bomb_active', '1') != '1':
        await update.message.reply_text("❌ این بخش موقتاً غیرفعال می‌باشد.")
        return

    for k, g in list(bomb_games.items()):
        if g['user_id'] == user.id and g['status'] in ['awaiting_bet', 'playing']:
            await update.message.reply_text("❌ شما یک بمب باز دارید!")
            return

    balance = db.get_balance(user.id)
    if balance < BOMB_MIN_BET:
        await update.message.reply_text(
            f"❌ موجودی ناکافی!\n💵 حداقل: <code>{format_number(BOMB_MIN_BET)}</code>",
            parse_mode=ParseMode.HTML
        )
        return

    msg = await update.message.reply_text(
        f"💣 ✨ <b>بازی بمب دارکی</b> ✨ 💣\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 بازیکن: {get_user_display(user)}\n\n"
        f"🎯 <b>نحوه بازی:</b>\n"
        f"• شبکه ۴×۴ (۱۶ خانه)\n"
        f"• ۶ خانه بمب تصادفی 💣\n"
        f"• هر خانه امن = <b>+۰.۴x ضریب</b>\n"
        f"• بمب = <b>باخت کامل!</b>\n"
        f"• هر زمان خواستی برداشت کن!\n\n"
        f"💰 حداقل شرط: <code>{format_number(BOMB_MIN_BET)}</code> DP\n\n"
        f"✏️ <b>مبلغ شرط را ریپلای کن:</b>\n"
        f"⏰ در صورت عدم فعالیت ۱۰ دقیقه خودکار لغو",
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
        'bombs': [],
        'revealed': [],
        'multiplier': 1.0,
        'created_at': time.time(),
    }
    asyncio.create_task(auto_cancel_bomb(game_key))


async def handle_bomb_bet_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await update.message.reply_text("❌ عدد!")
        return True

    if amount < BOMB_MIN_BET:
        await update.message.reply_text(
            f"❌ حداقل: <code>{format_number(BOMB_MIN_BET)}</code>",
            parse_mode=ParseMode.HTML
        )
        return True

    if db.get_balance(user.id) < amount:
        await update.message.reply_text("❌ موجودی ناکافی!")
        return True

    db.remove_dark_points(user.id, amount)
    game = bomb_games[game_key]
    game['amount'] = amount
    game['status'] = 'playing'
    game['multiplier'] = 1.0

    # تعیین ۶ موقعیت تصادفی بمب از ۱۶ خانه
    all_positions = list(range(16))
    bomb_positions = random.sample(all_positions, BOMB_COUNT)
    game['bombs'] = bomb_positions
    game['revealed'] = []

    kb = generate_bomb_keyboard(game)
    new_msg = await update.message.reply_text(
        f"💣 <b>بازی بمب فعال!</b> 💣\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 {get_user_display(user)}\n"
        f"💰 شرط: <code>{format_number(amount)}</code>\n\n"
        f"💎 ضریب فعلی: <b>1.0x</b>\n"
        f"🏆 برد فعلی: <code>{format_number(amount)}</code>\n"
        f"💣 تعداد بمب: <b>{BOMB_COUNT}</b> از ۱۶\n\n"
        f"⚡️ <i>هر خانه امن = +۰.۴ ضریب</i>",
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
            if status in ['won', 'lost', 'cashed_out', 'auto_cancelled']:
                if pos in bombs:
                    label = "💣"
                elif pos in revealed:
                    label = "💎"
                else:
                    label = "⬜"
            else:
                if pos in revealed:
                    label = "💎"
                else:
                    label = "🎁"
            row_buttons.append(InlineKeyboardButton(label, callback_data=f"bomb_click_{pos}"))
        kb.append(row_buttons)

    if status == 'playing' and len(game['revealed']) > 0:
        kb.append([InlineKeyboardButton(f"💰 برداشت ({game['multiplier']:.1f}x)", callback_data="bomb_cashout")])

    if status == 'playing' and len(game['revealed']) == 0:
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
        await query.answer("❌ قبلاً باز شده!", show_alert=True)
        return

    # چک بمب
    if pos in game['bombs']:
        game['status'] = 'lost'
        await query.answer("💥 بوم! بمب!", show_alert=True)

        kb = generate_bomb_keyboard(game)
        await query.edit_message_text(
            f"💥💥💥 <b>منفجر شد!</b> 💥💥💥\n"
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

    # خانه امن - ضریب +۰.۴
    game['revealed'].append(pos)
    game['multiplier'] = round(1.0 + (len(game['revealed']) * BOMB_MULTIPLIER_STEP), 2)
    potential_win = int(game['amount'] * game['multiplier'])

    await query.answer(f"✅ +{game['multiplier']}x!")

    # چک برد کامل (همه ۱۰ خانه امن باز شده - چون ۶ بمب داریم)
    safe_count = 16 - BOMB_COUNT  # = 10
    if len(game['revealed']) == safe_count:
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
            f"🎁 خانه‌های امن: {len(game['revealed'])}/{safe_count}\n"
            f"💣 بمب‌ها: {BOMB_COUNT}\n\n"
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
        return
    if game['status'] != 'playing' or len(game['revealed']) == 0:
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
        return
    if game['status'] != 'playing' or len(game['revealed']) > 0:
        await query.answer("❌ قابل لغو نیست!", show_alert=True)
        return

    db.add_dark_points(user.id, game['amount'])
    game['status'] = 'cancelled'
    await query.edit_message_text(
        f"❌ لغو شد\n💰 <code>{format_number(game['amount'])}</code> بازگردانده شد",
        parse_mode=ParseMode.HTML
    )
    if game_key in bomb_games:
        del bomb_games[game_key]


# ============ FOOTBALL GAME ============

football_games = {}

async def auto_cancel_football(game_key, delay=GAME_TIMEOUT):
    await asyncio.sleep(delay)
    game = football_games.get(game_key)
    if game and game['status'] in ['picking', 'awaiting_bet']:
        if game['amount'] > 0:
            db.add_dark_points(game['user_id'], game['amount'])
        game['status'] = 'auto_cancelled'
        if game_key in football_games:
            del football_games[game_key]


async def handle_football_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع بازی فوتبال"""
    user = update.effective_user

    if db.get_setting('football_active', '1') != '1':
        await update.message.reply_text("❌ این بخش موقتاً غیرفعال می‌باشد.")
        return

    for k, g in list(football_games.items()):
        if g['user_id'] == user.id and g['status'] in ['awaiting_bet', 'picking']:
            await update.message.reply_text("❌ شما یک بازی فوتبال باز دارید!")
            return

    balance = db.get_balance(user.id)
    if balance < FOOTBALL_MIN_BET:
        await update.message.reply_text(
            f"❌ موجودی ناکافی!\n💵 حداقل: <code>{format_number(FOOTBALL_MIN_BET)}</code>",
            parse_mode=ParseMode.HTML
        )
        return

    msg = await update.message.reply_text(
        f"⚽ ✨ <b>بازی فوتبال دارکی</b> ✨ ⚽\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 بازیکن: {get_user_display(user)}\n\n"
        f"🎯 <b>حدس بزن توپ کجا میره!</b>\n\n"
        f"💰 حداقل شرط: <code>{format_number(FOOTBALL_MIN_BET)}</code> DP\n\n"
        f"📊 <b>ضرایب برد:</b>\n"
        f"• فقط تیرک: <b>۱۲ برابر</b> 🥇\n"
        f"• تیرک + بیرون رفتن: <b>۷ برابر</b> 🥈\n"
        f"• گل + تیرک + بیرون: <b>۳ برابر</b> 🥉\n\n"
        f"✏️ <b>مبلغ شرط را ریپلای کن:</b>\n"
        f"⏰ در صورت عدم فعالیت ۱۰ دقیقه خودکار لغو",
        parse_mode=ParseMode.HTML
    )

    game_key = f"football_{user.id}_{msg.message_id}"
    football_games[game_key] = {
        'user_id': user.id,
        'user_obj': user,
        'status': 'awaiting_bet',
        'chat_id': msg.chat_id,
        'message_id': msg.message_id,
        'picks': [],  # ['goal', 'bar', 'out']
        'amount': 0,
        'created_at': time.time(),
    }
    asyncio.create_task(auto_cancel_football(game_key))


async def handle_football_bet_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پاسخ به مبلغ شرط فوتبال"""
    user = update.effective_user
    text = update.message.text.strip() if update.message.text else ""

    if not update.message.reply_to_message:
        return False

    reply_msg_id = update.message.reply_to_message.message_id
    game_key = None
    for k, g in list(football_games.items()):
        if g['user_id'] == user.id and g['message_id'] == reply_msg_id and g['status'] == 'awaiting_bet':
            game_key = k
            break

    if not game_key:
        return False

    try:
        amount = int(text)
    except Exception:
        await update.message.reply_text("❌ عدد!")
        return True

    if amount < FOOTBALL_MIN_BET:
        await update.message.reply_text(
            f"❌ حداقل: <code>{format_number(FOOTBALL_MIN_BET)}</code>",
            parse_mode=ParseMode.HTML
        )
        return True

    if db.get_balance(user.id) < amount:
        await update.message.reply_text("❌ موجودی ناکافی!")
        return True

    db.remove_dark_points(user.id, amount)
    game = football_games[game_key]
    game['amount'] = amount
    game['status'] = 'picking'

    kb = [
        [InlineKeyboardButton("🥅 گل زدن (داخل دروازه)", callback_data="football_pick_goal")],
        [InlineKeyboardButton("🎯 برخورد به تیرک", callback_data="football_pick_bar")],
        [InlineKeyboardButton("💨 بیرون رفتن توپ", callback_data="football_pick_out")],
        [InlineKeyboardButton("⚽ شوت توپ!", callback_data="football_shoot")],
        [InlineKeyboardButton("❌ لغو", callback_data="football_cancel")],
    ]

    new_msg = await update.message.reply_text(
        f"⚽ <b>بازی فوتبال</b> ⚽\n━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 {get_user_display(user)}\n"
        f"💰 شرط: <code>{format_number(amount)}</code>\n\n"
        f"📊 <b>ترکیب‌های معتبر:</b>\n"
        f"• فقط تیرک: ۱۲x 🥇\n"
        f"• تیرک + بیرون: ۷x 🥈\n"
        f"• گل + تیرک + بیرون: ۳x 🥉\n\n"
        f"📌 انتخابی: <code>هیچ</code>\n\n"
        f"⚡️ <i>انتخاب کن و شوت بزن!</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(kb)
    )

    game['message_id'] = new_msg.message_id
    new_key = f"football_{user.id}_{new_msg.message_id}"
    football_games[new_key] = football_games.pop(game_key)
    return True


async def football_pick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    picked = query.data.split("_")[-1]  # goal, bar, out

    game_key = None
    for k, g in list(football_games.items()):
        if g['message_id'] == query.message.message_id and g['chat_id'] == query.message.chat_id:
            game_key = k
            break

    if not game_key:
        return

    game = football_games[game_key]
    if game['user_id'] != user.id:
        await query.answer("❌", show_alert=True)
        return
    if game['status'] != 'picking':
        return

    picks = game['picks']
    if picked in picks:
        picks.remove(picked)
        await query.answer("❌ حذف شد")
    else:
        if len(picks) >= 3:
            await query.answer("⚠️ حداکثر ۳!", show_alert=True)
            return
        picks.append(picked)
        await query.answer("✅ اضافه شد")

    game['picks'] = picks

    display_map = {'goal': '🥅 گل', 'bar': '🎯 تیرک', 'out': '💨 بیرون'}
    picks_display = " + ".join([display_map[p] for p in picks]) if picks else "هیچ"

    # تعیین ضریب
    picks_set = set(picks)
    if picks_set == {'bar'}:
        mult_text = "۱۲ برابر 🥇"
    elif picks_set == {'bar', 'out'}:
        mult_text = "۷ برابر 🥈"
    elif picks_set == {'goal', 'bar', 'out'}:
        mult_text = "۳ برابر 🥉"
    elif len(picks) == 0:
        mult_text = "بدون انتخاب"
    else:
        mult_text = "❌ ترکیب نامعتبر"

    def get_btn(name, label):
        emoji = {'goal': '🥅', 'bar': '🎯', 'out': '💨'}[name]
        lbl = f"{emoji} {label}"
        if name in picks:
            lbl = f"✅ {lbl}"
        return InlineKeyboardButton(lbl, callback_data=f"football_pick_{name}")

    kb = [
        [get_btn('goal', 'گل زدن')],
        [get_btn('bar', 'برخورد به تیرک')],
        [get_btn('out', 'بیرون رفتن توپ')],
        [InlineKeyboardButton("⚽ شوت توپ!", callback_data="football_shoot")],
        [InlineKeyboardButton("❌ لغو", callback_data="football_cancel")],
    ]

    try:
        await query.edit_message_text(
            f"⚽ <b>بازی فوتبال</b>\n━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 {get_user_display(user)}\n"
            f"💰 شرط: <code>{format_number(game['amount'])}</code>\n\n"
            f"📊 ترکیب‌های معتبر:\n"
            f"• تیرک: ۱۲x | تیرک+بیرون: ۷x\n"
            f"• گل+تیرک+بیرون: ۳x\n\n"
            f"📌 انتخابی: <code>{picks_display}</code>\n"
            f"💎 ضریب: {mult_text}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(kb)
        )
    except Exception:
        pass


async def football_shoot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    game_key = None
    for k, g in list(football_games.items()):
        if g['message_id'] == query.message.message_id and g['chat_id'] == query.message.chat_id:
            game_key = k
            break

    if not game_key:
        return

    game = football_games[game_key]
    if game['user_id'] != user.id:
        return
    if game['status'] != 'picking' or len(game['picks']) == 0:
        await query.answer("⚠️ انتخاب کنید!", show_alert=True)
        return

    picks_set = set(game['picks'])
    valid_combos = [{'bar'}, {'bar', 'out'}, {'goal', 'bar', 'out'}]
    if picks_set not in valid_combos:
        await query.answer("❌ ترکیب نامعتبر!", show_alert=True)
        return

    game['status'] = 'shooting'
    await query.answer("⚽ شوت...")

    # ارسال فوتبال تلگرام
    football_msg = await context.bot.send_dice(chat_id=game['chat_id'], emoji='⚽')
    football_value = football_msg.dice.value
    # ۱=پاس | ۲=برخورد به تیرک | ۳=گل | ۴=بیرون | ۵=گل
    # ما مپ می‌کنیم:
    # 1 = out, 2 = bar, 3 = goal, 4 = out, 5 = goal
    result_map = {1: 'out', 2: 'bar', 3: 'goal', 4: 'out', 5: 'goal'}
    result = result_map.get(football_value, 'out')
    
    await asyncio.sleep(4)

    picks = game['picks']
    amount = game['amount']
    won = result in picks

    if picks_set == {'bar'}:
        multiplier = 12.0
        mult_display = "۱۲ برابر"
    elif picks_set == {'bar', 'out'}:
        multiplier = 7.0
        mult_display = "۷ برابر"
    else:
        multiplier = 3.0
        mult_display = "۳ برابر"

    display_map = {'goal': '🥅 گل', 'bar': '🎯 تیرک', 'out': '💨 بیرون'}
    picks_display = " + ".join([display_map[p] for p in picks])
    result_display = display_map.get(result, 'نامشخص')

    if won:
        prize = int(amount * multiplier)
        db.add_dark_points(user.id, prize)
        text = (
            f"🎉 ⚽ <b>گل! برنده شدی!</b> ⚽ 🎉\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 {get_user_display(user)}\n"
            f"💰 شرط: <code>{format_number(amount)}</code>\n\n"
            f"⚽ نتیجه شوت: <b>{result_display}</b>\n"
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
            f"⚽ نتیجه شوت: <b>{result_display}</b>\n"
            f"📌 انتخاب شما: {picks_display}\n\n"
            f"💰 موجودی: <code>{format_number(db.get_balance(user.id))}</code>\n\n"
            f"⚽ <i>دفعه بعد شانس بیشتر!</i>"
        )

    try:
        await query.edit_message_text(text, parse_mode=ParseMode.HTML)
    except Exception:
        pass

    game['status'] = 'finished'
    asyncio.create_task(cleanup_game_dict(football_games, game_key, 30))


async def football_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    game_key = None
    for k, g in list(football_games.items()):
        if g['message_id'] == query.message.message_id and g['chat_id'] == query.message.chat_id:
            game_key = k
            break
    if not game_key:
        return
    game = football_games[game_key]
    if game['user_id'] != user.id:
        return
    if game['amount'] > 0:
        db.add_dark_points(user.id, game['amount'])
    game['status'] = 'cancelled'
    await query.edit_message_text(f"❌ لغو شد", parse_mode=ParseMode.HTML)
    if game_key in football_games:
        del football_games[game_key]


# ============ HANDLE GROUP REPLY FOR GAMES ============

async def handle_group_reply_for_games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پاسخ‌های ریپلای در گروه برای بازی‌های حدس بزن/کازینو/بمب/فوتبال"""
    handled = await handle_guess_bet_reply(update, context)
    if handled:
        return True

    handled = await handle_casino_bet_reply(update, context)
    if handled:
        return True

    handled = await handle_bomb_bet_reply(update, context)
    if handled:
        return True

    handled = await handle_football_bet_reply(update, context)
    if handled:
        return True

    return False# ============ ADMIN PANEL ============

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return

    stats = db.get_stats()

    bot_active_status = "🟢" if db.get_setting('bot_active', '1') == '1' else "🔴"
    gift_status = "🟢" if db.get_setting('gift_section_active', '1') == '1' else "🔴"
    stars_status = "🟢" if db.get_setting('stars_section_active', '1') == '1' else "🔴"
    buydp_status = "🟢" if db.get_setting('buy_dp_active', '1') == '1' else "🔴"
    buypanel_status = "🟢" if db.get_setting('buy_panel_active', '1') == '1' else "🔴"
    crash_status = "🟢" if db.get_setting('crash_active', '1') == '1' else "🔴"
    dice_status = "🟢" if db.get_setting('dice_active', '1') == '1' else "🔴"
    guess_status = "🟢" if db.get_setting('guess_active', '1') == '1' else "🔴"
    casino_status = "🟢" if db.get_setting('casino_active', '1') == '1' else "🔴"
    bomb_status = "🟢" if db.get_setting('bomb_active', '1') == '1' else "🔴"
    football_status = "🟢" if db.get_setting('football_active', '1') == '1' else "🔴"
    wheel_status = "🟢" if db.get_setting('wheel_active', '1') == '1' else "🔴"
    tasks_status = "🟢" if db.get_setting('tasks_active', '1') == '1' else "🔴"

    kb = [
        # کنترل اصلی ربات
        [InlineKeyboardButton(f"⚡️ وضعیت ربات: {bot_active_status} (کلیک برای تغییر)", callback_data="adm_toggle_bot")],
        [InlineKeyboardButton("📊 آمار کامل ربات", callback_data="adm_stats")],
        
        # پیام همگانی و تبلیغات
        [
            InlineKeyboardButton("📢 پیام همگانی", callback_data="adm_broadcast_msg"),
            InlineKeyboardButton("📤 فوروارد همگانی", callback_data="adm_broadcast_fwd"),
        ],
        [InlineKeyboardButton("📣 ارسال تبلیغ به گروه‌ها", callback_data="adm_broadcast_groups")],
        [InlineKeyboardButton("📋 لیست گروه‌های ادمین", callback_data="adm_list_groups")],
        
        # مدیریت کاربران
        [
            InlineKeyboardButton("💰 افزودن DP", callback_data="adm_add_dp"),
            InlineKeyboardButton("💸 کسر DP", callback_data="adm_remove_dp"),
        ],
        [
            InlineKeyboardButton("🔍 جستجوی کاربر", callback_data="adm_search_user"),
            InlineKeyboardButton("🚫 بن/آنبن", callback_data="adm_ban_user"),
        ],
        
        # کانال‌ها و تسک‌ها
        [InlineKeyboardButton("📢 مدیریت کانال‌های اجباری", callback_data="adm_channels")],
        [InlineKeyboardButton("📋 مدیریت تسک‌ها", callback_data="adm_tasks")],
        [InlineKeyboardButton("🎖 درخواست‌های ماموریت در انتظار", callback_data="adm_mission_requests")],
        
        # تغییر مقادیر
        [
            InlineKeyboardButton("👥 تغییر پاداش رفرال", callback_data="adm_ref_reward"),
            InlineKeyboardButton("🎁 تغییر هدیه ثبت‌نام", callback_data="adm_first_reward"),
        ],
        [
            InlineKeyboardButton("💵 قیمت پنل سنایی", callback_data="adm_panel_prices"),
            InlineKeyboardButton("📦 افزودن پلن پنل", callback_data="adm_create_panel"),
        ],
        [InlineKeyboardButton("🗑 حذف پلن پنل", callback_data="adm_delete_panel")],
        [
            InlineKeyboardButton("💵 قیمت گیفت", callback_data="adm_set_gift_price"),
            InlineKeyboardButton("⭐ قیمت استارز", callback_data="adm_set_stars_price"),
        ],
        [InlineKeyboardButton("🎁 افزودن پلن گیفت", callback_data="adm_add_gift_plan")],
        
        # بکاپ
        [InlineKeyboardButton("💾 بکاپ کامل دیتابیس", callback_data="adm_backup_db")],
        
        # روشن/خاموش بخش‌ها
        [
            InlineKeyboardButton(f"🛒 خرید پنل: {buypanel_status}", callback_data="adm_toggle_buypanel"),
            InlineKeyboardButton(f"🎁 گیفت: {gift_status}", callback_data="adm_toggle_gift"),
        ],
        [
            InlineKeyboardButton(f"⭐ استارز: {stars_status}", callback_data="adm_toggle_stars"),
            InlineKeyboardButton(f"💰 خرید DP: {buydp_status}", callback_data="adm_toggle_buydp"),
        ],
        [
            InlineKeyboardButton(f"💥 انفجار: {crash_status}", callback_data="adm_toggle_crash"),
            InlineKeyboardButton(f"🎲 تاس: {dice_status}", callback_data="adm_toggle_dice"),
        ],
        [
            InlineKeyboardButton(f"🎯 حدس بزن: {guess_status}", callback_data="adm_toggle_guess"),
            InlineKeyboardButton(f"🎰 کازینو: {casino_status}", callback_data="adm_toggle_casino"),
        ],
        [
            InlineKeyboardButton(f"💣 بمب: {bomb_status}", callback_data="adm_toggle_bomb"),
            InlineKeyboardButton(f"⚽ فوتبال: {football_status}", callback_data="adm_toggle_football"),
        ],
        [
            InlineKeyboardButton(f"🎡 گردونه: {wheel_status}", callback_data="adm_toggle_wheel"),
            InlineKeyboardButton(f"📋 تسک‌ها: {tasks_status}", callback_data="adm_toggle_tasks"),
        ],
        
        # ابزارهای ادمین
        [InlineKeyboardButton("💬 ارسال پیام به کاربر خاص", callback_data="adm_send_to_user")],
        [InlineKeyboardButton("📋 آخرین سفارشات", callback_data="adm_recent_orders")],
        [InlineKeyboardButton("🎁 هدیه به کاربران برتر", callback_data="adm_gift_top")],
        [InlineKeyboardButton("📝 ساخت چک شخصی", callback_data="adm_create_check")],
        [InlineKeyboardButton("🎁 هدیه به همه کاربران", callback_data="adm_gift_all")],
        
        [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="main_menu")],
    ]

    text = (
        f"🛡 <b>پنل مدیریت ادمین</b> 🛡\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"⚡️ وضعیت ربات: {bot_active_status}\n"
        f"👥 کل کاربران: <b>{stats['total_users']}</b>\n"
        f"✅ فعال ۷ روز: <b>{stats['active_7d']}</b>\n"
        f"🆕 جدید امروز: <b>{stats['new_today']}</b>\n"
        f"🚫 بن شده: <b>{stats['banned_users']}</b>\n"
        f"💎 کل DP: <code>{format_number(stats['total_dp'])}</code>\n"
        f"🏦 کل بانک: <code>{format_number(stats['total_bank'])}</code>\n"
        f"📣 گروه‌های ادمین: <b>{stats['admin_groups']}</b>\n"
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
        f"   • باخت: {stats['crash_lost']}\n\n"
        f"📣 <b>گروه‌ها:</b>\n"
        f"   • کل: {stats['total_groups']}\n"
        f"   • ادمین: {stats['admin_groups']}\n"
    )

    tasks = db.get_tasks(only_active=False)
    text += f"\n📋 <b>تسک‌ها:</b> {len(tasks)} تسک\n"
    text += f"━━━━━━━━━━━━━━━━━━"

    kb = [[InlineKeyboardButton("🔙 پنل ادمین", callback_data="adm_back")]]
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


# ============ TOGGLE BOT ON/OFF ============

async def adm_toggle_bot_cb(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    cur = db.get_setting('bot_active', '1')
    new = '0' if cur == '1' else '1'
    db.set_setting('bot_active', new)
    status = "✅ روشن شد" if new == '1' else "⚠️ خاموش شد"
    await query.answer(f"ربات {status}", show_alert=True)
    await admin_panel(update, context)


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


async def adm_broadcast_groups_cb(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()
    context.user_data['admin_action'] = 'broadcast_groups'
    
    groups = db.get_admin_groups()
    await query.edit_message_text(
        f"📣 <b>ارسال تبلیغ به گروه‌ها</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 گروه‌های ادمین: <b>{len(groups)}</b>\n\n"
        f"پیام تبلیغاتی را ارسال کنید (هر نوع).\n\n"
        f"برای لغو: /cancel",
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


async def do_broadcast_groups(update, context):
    """ارسال به گروه‌هایی که ربات ادمین است"""
    admin_id = update.effective_user.id
    groups = db.get_admin_groups()
    total = len(groups)
    sent, failed = 0, 0
    start_time = time.time()

    status_msg = await update.message.reply_text(
        f"⏳ در حال ارسال به <b>{total}</b> گروه...",
        parse_mode=ParseMode.HTML
    )

    for g in groups:
        try:
            await context.bot.copy_message(
                chat_id=g['chat_id'],
                from_chat_id=update.message.chat_id,
                message_id=update.message.message_id
            )
            sent += 1
        except Exception:
            failed += 1
        
        if (sent + failed) % 10 == 0:
            try:
                await status_msg.edit_text(
                    f"⏳ در حال ارسال به گروه‌ها...\n\n✅ موفق: {sent}\n❌ ناموفق: {failed}\n📊 {sent+failed}/{total}",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass
        await asyncio.sleep(0.3)

    total_time = int(time.time() - start_time)
    success_rate = int(sent/total*100 if total else 0)
    
    await status_msg.edit_text(
        f"✅ <b>ارسال به گروه‌ها کامل شد!</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📣 کل گروه‌ها: <b>{total}</b>\n"
        f"✅ موفق: <b>{sent}</b>\n"
        f"❌ ناموفق: <b>{failed}</b>\n"
        f"📈 موفقیت: <b>{success_rate}%</b>\n"
        f"⏱ زمان: <b>{total_time}s</b>",
        parse_mode=ParseMode.HTML
    )


# ============ LIST GROUPS ============

async def adm_list_groups_cb(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()

    groups = db.get_all_groups()
    text = f"📣 <b>لیست گروه‌های ربات</b> 📣\n━━━━━━━━━━━━━━━━━━\n\n"
    
    if not groups:
        text += "❌ هیچ گروهی ثبت نشده\n"
    else:
        for g in groups[:30]:  # حداکثر 30 گروه
            title = html.escape(g['title'] or "بدون عنوان")
            admin_mark = "👑" if g['is_admin'] else "❌"
            text += f"{admin_mark} <b>{title}</b>\n"
            text += f"   🆔 <code>{g['chat_id']}</code> | 👥 {g['member_count']}\n\n"

        if len(groups) > 30:
            text += f"\n<i>... و {len(groups) - 30} گروه دیگر</i>"
    
    text += f"\n━━━━━━━━━━━━━━━━━━\n👑 ادمین | ❌ غیر ادمین"
    
    kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="adm_back")]]
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


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
            task_type_emoji = "📢" if t['task_type'] == 'channel' else "🎖"
            cap_text = ""
            if t['capacity'] > 0:
                cap_text = f" | {t['completed_count']}/{t['capacity']}"
            text += f"{task_type_emoji} #{t['task_id']} - {title}\n  💰 {format_number(t['reward'])}{cap_text}\n\n"

    kb = [
        [InlineKeyboardButton("➕ تسک عضویت کانال", callback_data="adm_add_task_channel")],
        [InlineKeyboardButton("➕ تسک ماموریت", callback_data="adm_add_task_mission")],
    ]
    for t in tasks:
        title = html.escape(t['channel_title'] or "")[:20]
        kb.append([InlineKeyboardButton(f"🗑 حذف #{t['task_id']} - {title}", callback_data=f"adm_del_task_{t['task_id']}")])
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="adm_back")])

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def adm_add_task_channel_cb(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()
    context.user_data['admin_action'] = 'add_task_channel'
    context.user_data['task_step'] = 'channel'
    await query.edit_message_text(
        "📢 <b>افزودن تسک عضویت کانال</b>\n\nیوزرنیم کانال را با @ بفرستید:\n⚠️ ربات باید ادمین کانال باشد\n\nبرای لغو: /cancel",
        parse_mode=ParseMode.HTML
    )


async def adm_add_task_mission_cb(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()
    context.user_data['admin_action'] = 'add_task_mission'
    context.user_data['task_step'] = 'title'
    await query.edit_message_text(
        "🎖 <b>افزودن تسک ماموریت</b>\n\nعنوان ماموریت را بفرستید:\n\nمثال: استارت زدن ربات @darkbot\n\nبرای لغو: /cancel",
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


# ============ MISSION REQUESTS ============

async def adm_mission_requests_cb(update, context):
    """نمایش درخواست‌های تایید ماموریت"""
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()

    conn = db.get_conn()
    c = conn.cursor()
    c.execute("""SELECT mr.*, t.channel_title as task_title, t.reward 
                 FROM mission_requests mr 
                 JOIN tasks t ON mr.task_id = t.task_id 
                 WHERE mr.status = 'pending' 
                 ORDER BY mr.created_at DESC LIMIT 20""")
    requests = c.fetchall()
    conn.close()

    text = "🎖 <b>درخواست‌های تایید ماموریت</b>\n━━━━━━━━━━━━━━━━━━\n\n"
    
    if not requests:
        text += "✅ هیچ درخواست در انتظار نیست"
        kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="adm_back")]]
    else:
        for r in requests:
            title = html.escape(r['task_title'] or "")
            text += f"🆔 #<code>{r['request_id']}</code> | 👤 <code>{r['user_id']}</code>\n"
            text += f"🎖 {title} | 💰 {format_number(r['reward'])}\n\n"

        kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="adm_back")]]

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def admin_approve_mission_cb(update, context):
    """تایید ماموریت توسط ادمین"""
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    
    request_id = int(query.data.split("_")[-1])
    request = db.get_mission_request(request_id)
    if not request or request['status'] != 'pending':
        await query.answer("❌ درخواست یافت نشد یا پردازش شده!", show_alert=True)
        return

    task = db.get_task(request['task_id'])
    if not task:
        await query.answer("❌ تسک یافت نشد!", show_alert=True)
        return

    # پاداش به کاربر
    db.add_dark_points(request['user_id'], task['reward'])
    db.mark_task_completed(request['user_id'], request['task_id'])
    db.approve_mission_request(request_id)

    await query.answer("✅ تایید شد و پاداش ارسال شد", show_alert=True)

    try:
        await context.bot.send_message(
            request['user_id'],
            f"✅ <b>ماموریت شما تایید شد!</b>\n━━━━━━━━━━━━━━━━━━\n\n"
            f"🎖 {task['channel_title']}\n"
            f"💰 پاداش: +<code>{format_number(task['reward'])}</code> DP\n"
            f"💎 موجودی: <code>{format_number(db.get_balance(request['user_id']))}</code>",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass

    try:
        await query.edit_message_text(
            query.message.text_html + "\n\n✅ <b>تایید شد و پاداش ارسال شد</b>",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass


async def admin_reject_mission_cb(update, context):
    """رد ماموریت"""
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    
    request_id = int(query.data.split("_")[-1])
    request = db.get_mission_request(request_id)
    if not request or request['status'] != 'pending':
        await query.answer("❌ یافت نشد!", show_alert=True)
        return

    db.reject_mission_request(request_id)
    await query.answer("❌ رد شد", show_alert=True)

    try:
        await context.bot.send_message(
            request['user_id'],
            f"❌ <b>ماموریت شما رد شد</b>\n\nمی‌توانید دوباره ارسال کنید.",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass

    try:
        await query.edit_message_text(
            query.message.text_html + "\n\n❌ <b>رد شد</b>",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass


# ============ REFERRAL REWARD & FIRST REWARD ============

async def adm_ref_reward_cb(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()
    current = get_referral_reward()
    context.user_data['admin_action'] = 'set_ref_reward'
    await query.edit_message_text(
        f"👥 <b>تغییر پاداش زیرمجموعه</b>\n\nمقدار فعلی: <code>{format_number(current)}</code> DP\n\nمقدار جدید را بفرستید:",
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
        f"🎁 <b>تغییر هدیه ثبت‌نام</b>\n\nمقدار فعلی: <code>{format_number(current)}</code>\n\nمقدار جدید:",
        parse_mode=ParseMode.HTML
    )


# ============ FULL BACKUP ============

async def adm_backup_db_cb(update, context):
    """بکاپ کامل دیتابیس"""
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer("⏳ در حال آماده‌سازی...")

    try:
        with open(db.db_name, 'rb') as f:
            await context.bot.send_document(
                chat_id=query.from_user.id,
                document=f,
                filename=f"darkpoint_full_backup_{int(time.time())}.db",
                caption=(
                    f"💾 <b>بکاپ کامل دیتابیس دارک پوینت</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n\n"
                    f"📅 تاریخ: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"👥 کل کاربران: {db.get_all_users_count()}\n"
                    f"💎 کل DP: {format_number(db.get_stats()['total_dp'])}\n"
                    f"🏦 کل بانک: {format_number(db.get_stats()['total_bank'])}\n\n"
                    f"<b>شامل:</b>\n"
                    f"✅ تمام کاربران + موجودی‌ها\n"
                    f"✅ تمام سفارشات\n"
                    f"✅ تمام تنظیمات\n"
                    f"✅ کانال‌ها و تسک‌ها\n"
                    f"✅ گروه‌ها و بانک‌ها\n"
                    f"✅ تاریخچه تراکنش‌ها\n\n"
                    f"⚠️ <b>این فایل را در جای امن نگه دارید</b>"
                ),
                parse_mode=ParseMode.HTML
            )
        await query.message.reply_text("✅ بکاپ کامل به پیوی شما ارسال شد.")
    except Exception as e:
        await query.message.reply_text(f"❌ خطا:\n{str(e)[:200]}")


# ============ PANEL PRICES & DELETE ============

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


async def adm_delete_panel_cb(update, context):
    """حذف پلن از بخش ساخت پنل"""
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()

    panels = db.get_all_custom_panels()
    active_panels = [p for p in panels if p['active'] == 1]
    
    text = "🗑 <b>حذف پلن پنل</b>\n━━━━━━━━━━━━━━━━━━\n\n"
    if not active_panels:
        text += "❌ هیچ پلن سفارشی برای حذف نیست\n"
        kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="adm_back")]]
    else:
        text += "پلن مورد نظر برای حذف را انتخاب کنید:\n"
        kb = []
        for p in active_panels:
            kb.append([InlineKeyboardButton(
                f"🗑 حذف {p['name']} ({format_number(p['price'])})",
                callback_data=f"adm_del_panel_{p['panel_id']}"
            )])
        kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="adm_back")])
    
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def adm_del_panel_cb(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    panel_id = int(query.data.split("_")[-1])
    db.delete_custom_panel(panel_id)
    await query.answer("✅ پلن حذف شد", show_alert=True)
    await adm_delete_panel_cb(update, context)


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
    elif data == "adm_toggle_bot":
        await adm_toggle_bot_cb(update, context)
    elif data == "adm_broadcast_msg":
        await adm_broadcast_msg_cb(update, context)
    elif data == "adm_broadcast_fwd":
        await adm_broadcast_fwd_cb(update, context)
    elif data == "adm_broadcast_groups":
        await adm_broadcast_groups_cb(update, context)
    elif data == "adm_list_groups":
        await adm_list_groups_cb(update, context)
    elif data == "adm_channels":
        await adm_channels_cb(update, context)
    elif data == "adm_add_channel":
        await adm_add_channel_cb(update, context)
    elif data.startswith("adm_del_ch_"):
        await adm_del_ch_cb(update, context)
    elif data == "adm_tasks":
        await adm_tasks_cb(update, context)
    elif data == "adm_add_task_channel":
        await adm_add_task_channel_cb(update, context)
    elif data == "adm_add_task_mission":
        await adm_add_task_mission_cb(update, context)
    elif data.startswith("adm_del_task_"):
        await adm_del_task_cb(update, context)
    elif data == "adm_mission_requests":
        await adm_mission_requests_cb(update, context)
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
    elif data == "adm_delete_panel":
        await adm_delete_panel_cb(update, context)
    elif data.startswith("adm_del_panel_"):
        await adm_del_panel_cb(update, context)
    elif data == "adm_send_to_user":
        await adm_send_to_user_cb(update, context)
    elif data == "adm_recent_orders":
        await adm_recent_orders_cb(update, context)
    elif data == "adm_gift_top":
        await adm_gift_top_cb(update, context)
    elif data == "adm_add_dp":
        await query.answer()
        context.user_data['admin_action'] = 'add_dp'
        await query.edit_message_text("💰 شماره کاربری:\n\nبرای لغو: /cancel")
    elif data == "adm_remove_dp":
        await query.answer()
        context.user_data['admin_action'] = 'remove_dp'
        await query.edit_message_text("💸 شماره کاربری:\n\nبرای لغو: /cancel")
    elif data == "adm_search_user":
        await query.answer()
        context.user_data['admin_action'] = 'search_user'
        await query.edit_message_text("🔍 شماره یا @username:")
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
        await query.edit_message_text("💵 قیمت گیفت تدی (DP):")
    elif data == "adm_set_stars_price":
        await query.answer()
        context.user_data['admin_action'] = 'set_stars_price'
        await query.edit_message_text(f"⭐ قیمت {STARS_AMOUNT} استارز (DP):")
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
    elif data == "adm_toggle_buypanel":
        cur = db.get_setting('buy_panel_active', '1')
        new = '0' if cur == '1' else '1'
        db.set_setting('buy_panel_active', new)
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
    elif data == "adm_toggle_football":
        cur = db.get_setting('football_active', '1')
        new = '0' if cur == '1' else '1'
        db.set_setting('football_active', new)
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
        await query.edit_message_text("🎁 مقدار DP هدیه به همه:")
    elif data.startswith("admin_approve_mission_"):
        await admin_approve_mission_cb(update, context)
    elif data.startswith("admin_reject_mission_"):
        await admin_reject_mission_cb(update, context)# ============ HANDLE ADMIN TEXT INPUTS ============

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

    # ============ افزودن تسک عضویت کانال ============
    if action == 'add_task_channel':
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
                    f"❌ خطا:\n{str(e)[:100]}",
                    parse_mode=ParseMode.HTML
                )
                context.user_data.clear()
        elif step == 'reward':
            try:
                context.user_data['task_reward'] = int(text)
                context.user_data['task_step'] = 'capacity'
                await update.message.reply_text(
                    "👥 <b>ظرفیت تسک</b>\n\nحداکثر چند نفر بتوانند انجام دهند؟\n\n<i>برای نامحدود عدد ۰ بفرستید</i>",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                await update.message.reply_text("❌ عدد نامعتبر!")
                context.user_data.clear()
        elif step == 'capacity':
            try:
                capacity = int(text)
                channel = context.user_data['task_channel']
                title = context.user_data['task_title']
                reward = context.user_data['task_reward']
                task_id = db.add_task('channel', channel, title, '', reward, capacity)
                cap_text = f"👥 ظرفیت: {capacity}" if capacity > 0 else "👥 ظرفیت: نامحدود"
                await update.message.reply_text(
                    f"✅ <b>تسک عضویت اضافه شد!</b>\n\n"
                    f"📢 {channel}\n"
                    f"📝 {html.escape(title)}\n"
                    f"💰 پاداش: <code>{format_number(reward)}</code>\n"
                    f"{cap_text}\n"
                    f"🆔 <code>{task_id}</code>",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                await update.message.reply_text("❌ عدد نامعتبر!")
            context.user_data.clear()
        return

    # ============ افزودن تسک ماموریت ============
    if action == 'add_task_mission':
        step = context.user_data.get('task_step')
        if step == 'title':
            context.user_data['task_title'] = text
            context.user_data['task_step'] = 'description'
            await update.message.reply_text(
                "📝 <b>توضیحات ماموریت را بفرستید</b>\n\n"
                "مثال: ربات @darkbot را استارت بزن و اسکرین‌شات از منوی اصلی بفرست.",
                parse_mode=ParseMode.HTML
            )
        elif step == 'description':
            context.user_data['task_description'] = text
            context.user_data['task_step'] = 'reward'
            await update.message.reply_text("💰 پاداش ماموریت (DP):")
        elif step == 'reward':
            try:
                context.user_data['task_reward'] = int(text)
                context.user_data['task_step'] = 'capacity'
                await update.message.reply_text(
                    "👥 <b>ظرفیت تسک</b>\n\nحداکثر چند نفر؟ (۰ = نامحدود)",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                await update.message.reply_text("❌ عدد!")
                context.user_data.clear()
        elif step == 'capacity':
            try:
                capacity = int(text)
                title = context.user_data['task_title']
                description = context.user_data['task_description']
                reward = context.user_data['task_reward']
                task_id = db.add_task('mission', '', title, description, reward, capacity)
                cap_text = f"👥 ظرفیت: {capacity}" if capacity > 0 else "👥 ظرفیت: نامحدود"
                await update.message.reply_text(
                    f"✅ <b>تسک ماموریت اضافه شد!</b>\n\n"
                    f"🎖 عنوان: {html.escape(title)}\n"
                    f"💰 پاداش: <code>{format_number(reward)}</code>\n"
                    f"{cap_text}\n"
                    f"🆔 <code>{task_id}</code>",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                await update.message.reply_text("❌ عدد!")
            context.user_data.clear()
        return

    # ============ تغییر پاداش رفرال ============
    if action == 'set_ref_reward':
        try:
            amount = int(text)
            db.set_setting('referral_reward', str(amount))
            await update.message.reply_text(
                f"✅ پاداش رفرال: <code>{format_number(amount)}</code> DP",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await update.message.reply_text("❌")
        context.user_data.clear()
        return

    # ============ تغییر هدیه ثبت‌نام ============
    if action == 'set_first_reward':
        try:
            amount = int(text)
            db.set_setting('first_join_reward', str(amount))
            await update.message.reply_text(
                f"✅ هدیه ثبت‌نام: <code>{format_number(amount)}</code> DP",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await update.message.reply_text("❌")
        context.user_data.clear()
        return

    # ============ افزودن DP ============
    if action == 'add_dp':
        if 'admin_target_user' not in context.user_data:
            try:
                target_id = int(text)
                context.user_data['admin_target_user'] = target_id
                await update.message.reply_text(f"💰 چقدر به <code>{target_id}</code>؟", parse_mode=ParseMode.HTML)
                return
            except Exception:
                await update.message.reply_text("❌")
                context.user_data.clear()
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
                    f"✅ +<code>{format_number(amount)}</code> به <code>{target_id}</code>\n💎 موجودی: <code>{format_number(new_balance)}</code>",
                    parse_mode=ParseMode.HTML
                )
                try:
                    await context.bot.send_message(
                        target_id,
                        f"🎁 هدیه ادمین!\n+<code>{format_number(amount)}</code> DP",
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass
            except Exception:
                await update.message.reply_text("❌")
            context.user_data.clear()
            return

    # ============ کسر DP ============
    if action == 'remove_dp':
        if 'admin_target_user' not in context.user_data:
            try:
                context.user_data['admin_target_user'] = int(text)
                await update.message.reply_text("💸 چقدر کم شود؟")
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
                await update.message.reply_text("❌")
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
            await update.message.reply_text("❌ یافت نشد!")
        else:
            banned = "🚫 بن" if u['is_banned'] else "✅ فعال"
            name = html.escape(u['first_name'] or "")
            reply_kb = [[InlineKeyboardButton("💬 پاسخ به کاربر", callback_data=f"admin_reply_{u['user_id']}")]]
            await update.message.reply_text(
                f"👤 <b>اطلاعات کاربر</b>\n━━━━━━━━━━━━━━━━━━\n\n"
                f"🆔 <code>{u['user_id']}</code>\n"
                f"📛 @{u['username'] or 'ندارد'}\n"
                f"👤 <b>{name}</b>\n"
                f"💰 <code>{format_number(u['dark_points'])}</code> DP\n"
                f"📊 سطح: {u['level']}\n"
                f"👥 زیرمجموعه: {u['referral_count']}\n"
                f"🏭 کارخونه: {u['factory_level']} ({'فعال' if u['factory_active'] else 'خاموش'})\n"
                f"🏦 بانک: <code>{format_number(u['bank_balance'])}</code>\n"
                f"📊 وضعیت: {banned}",
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
                    await update.message.reply_text(f"✅ <code>{target_id}</code> آنبن شد.", parse_mode=ParseMode.HTML)
                else:
                    db.ban_user(target_id)
                    await update.message.reply_text(f"🚫 <code>{target_id}</code> بن شد.", parse_mode=ParseMode.HTML)
        except Exception:
            await update.message.reply_text("❌")
        context.user_data.clear()
        return

    # ============ ساخت پلن پنل ============
    if action == 'create_panel':
        step = context.user_data.get('panel_step')
        if step == 'name':
            context.user_data['panel_name'] = text
            context.user_data['panel_step'] = 'desc'
            await update.message.reply_text("📝 توضیحات:")
        elif step == 'desc':
            context.user_data['panel_desc'] = text
            context.user_data['panel_step'] = 'price'
            await update.message.reply_text("💰 قیمت:")
        elif step == 'price':
            try:
                context.user_data['panel_price'] = int(text)
                context.user_data['panel_step'] = 'data'
                await update.message.reply_text("📊 حجم (مثلاً 500GB):")
            except Exception:
                await update.message.reply_text("❌")
        elif step == 'data':
            db.add_custom_panel(
                context.user_data['panel_name'],
                context.user_data['panel_desc'],
                context.user_data['panel_price'],
                text
            )
            await update.message.reply_text(
                f"✅ پلن ساخته شد!\n📦 {html.escape(context.user_data['panel_name'])}\n💰 <code>{format_number(context.user_data['panel_price'])}</code>",
                parse_mode=ParseMode.HTML
            )
            context.user_data.clear()
        return

    # ============ قیمت گیفت ============
    if action == 'set_gift_price':
        try:
            price = int(text)
            db.set_setting('gift_teddy_price', str(price))
            await update.message.reply_text(f"✅ قیمت گیفت: <code>{format_number(price)}</code>", parse_mode=ParseMode.HTML)
        except Exception:
            await update.message.reply_text("❌")
        context.user_data.clear()
        return

    # ============ قیمت استارز ============
    if action == 'set_stars_price':
        try:
            price = int(text)
            db.set_setting('stars_price', str(price))
            await update.message.reply_text(f"✅ قیمت استارز: <code>{format_number(price)}</code>", parse_mode=ParseMode.HTML)
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
                f"✅ قیمت سنایی {plan_name}: <code>{format_number(price)}</code>",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await update.message.reply_text("❌")
        context.user_data.clear()
        return

    # ============ ارسال به کاربر خاص ============
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
            await update.message.reply_text("❌")
            context.user_data.clear()
        return

    # ============ هدیه به کاربران برتر ============
    if action == 'gift_top_count':
        try:
            count = int(text)
            context.user_data['admin_action'] = 'gift_top_amount'
            context.user_data['gift_top_count'] = count
            await update.message.reply_text(f"✅ {count} نفر\n\nمقدار هدیه هر نفر:")
        except Exception:
            await update.message.reply_text("❌")
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
                        f"🎁 <b>جزو {count} نفر برتر!</b>\n💰 +<code>{format_number(amount)}</code> DP",
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass
            await update.message.reply_text(
                f"✅ به {len(top_users)} نفر هدیه داده شد.",
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
                f"✅ چک ساخته شد!\n💰 <code>{format_number(amount)}</code>\n🔗 {link}",
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
                    f"✅ پلن {html.escape(name)}: <code>{format_number(price)}</code>",
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
                f"✅ هدیه به همه!\n💰 <code>{format_number(amount)}</code> به {len(users)} کاربر",
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

    # چک خاموش بودن ربات برای کاربران
    if not is_bot_active() and not is_admin(user.id):
        await update.message.reply_text(
            "⚠️ <b>ربات موقتاً خاموش است</b>\n\n🔧 از طرف پشتیبانی موقتاً غیرفعال شده است.",
            parse_mode=ParseMode.HTML
        )
        return

    if not db.get_user(user.id):
        db.create_user(user.id, user.username or "", user.first_name or "")

    db.update_last_active(user.id)

    # ============ ادمین: پیام‌های چندرسانه‌ای ============
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

        # ارسال به گروه‌ها
        if action == 'broadcast_groups':
            context.user_data.pop('admin_action', None)
            await do_broadcast_groups(update, context)
            return

        # ارسال کانفیگ
        if action == 'send_config':
            order_id = context.user_data.get('config_order_id')
            target_user_id = context.user_data.get('config_user_id')
            try:
                await context.bot.send_message(
                    target_user_id,
                    f"✅ <b>کانفیگ سفارش شما آماده شد!</b>\n━━━━━━━━━━━━━━━━━━\n🆔 <code>{order_id}</code>\n\n⬇️ کانفیگ:",
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

        # پاسخ به کاربر
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
                await update.message.reply_text(f"✅ ارسال شد.", parse_mode=ParseMode.HTML)
            except Exception as e:
                await update.message.reply_text(f"❌ خطا:\n{str(e)[:200]}")
            context.user_data.clear()
            return

        # ارسال به کاربر خاص از پنل
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
                await update.message.reply_text(f"✅ ارسال شد.", parse_mode=ParseMode.HTML)
            except Exception as e:
                await update.message.reply_text(f"❌ خطا:\n{str(e)[:200]}")
            context.user_data.clear()
            return

    # ============ درخواست اسکرین‌شات ماموریت ============
    if 'awaiting_mission_screenshot' in context.user_data:
        task_id = context.user_data.get('awaiting_mission_screenshot')
        task = db.get_task(task_id)
        
        if not task:
            await update.message.reply_text("❌ تسک یافت نشد!")
            context.user_data.pop('awaiting_mission_screenshot', None)
            return
        
        if db.is_task_completed(user.id, task_id):
            await update.message.reply_text("✅ قبلاً انجام داده‌اید!")
            context.user_data.pop('awaiting_mission_screenshot', None)
            return
        
        if db.has_pending_mission_request(user.id, task_id):
            await update.message.reply_text("⏳ درخواست قبلی در انتظار است!")
            context.user_data.pop('awaiting_mission_screenshot', None)
            return
        
        if not update.message.photo:
            await update.message.reply_text("❌ لطفاً یک عکس (اسکرین‌شات) ارسال کنید.")
            return
        
        # ثبت درخواست
        request_id = db.create_mission_request(user.id, task_id)
        context.user_data.pop('awaiting_mission_screenshot', None)
        
        await update.message.reply_text(
            f"✅ <b>اسکرین‌شات ارسال شد!</b>\n━━━━━━━━━━━━━━━━━━\n\n"
            f"🎖 {task['channel_title']}\n"
            f"💰 پاداش: <code>{format_number(task['reward'])}</code> DP\n"
            f"🆔 درخواست: <code>{request_id}</code>\n\n"
            f"⏳ <i>منتظر تایید ادمین باشید</i>",
            parse_mode=ParseMode.HTML
        )
        
        # ارسال به ادمین
        user_display = f"@{user.username}" if user.username else f"<code>{user.id}</code>"
        for admin_id in ADMIN_IDS:
            try:
                caption = (
                    f"🎖 <b>درخواست تایید ماموریت جدید</b>\n━━━━━━━━━━━━━━━━━━\n\n"
                    f"👤 کاربر: {user_display}\n"
                    f"🆔 <code>{user.id}</code>\n"
                    f"🎖 ماموریت: {html.escape(task['channel_title'])}\n"
                    f"📋 توضیح: {html.escape(task['description'] or 'ندارد')}\n"
                    f"💰 پاداش: <code>{format_number(task['reward'])}</code> DP\n"
                    f"🆔 درخواست: <code>{request_id}</code>"
                )
                admin_kb = [
                    [
                        InlineKeyboardButton("✅ تایید", callback_data=f"admin_approve_mission_{request_id}"),
                        InlineKeyboardButton("❌ رد", callback_data=f"admin_reject_mission_{request_id}")
                    ],
                    [InlineKeyboardButton("💬 پاسخ به کاربر", callback_data=f"admin_reply_{user.id}")]
                ]
                # کپی عکس
                await context.bot.copy_message(
                    chat_id=admin_id,
                    from_chat_id=update.message.chat_id,
                    message_id=update.message.message_id,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(admin_kb)
                )
            except Exception as e:
                logger.error(f"Admin notify error: {e}")
        
        return

    text = update.message.text.strip() if update.message.text else ""
    if not text:
        return

    if text.lower() in ['/cancel', 'لغو', 'cancel']:
        context.user_data.clear()
        await update.message.reply_text("✅ لغو شد.")
        return

    # ============ کپچای زیرمجموعه ============
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
                f"❌ اشتباه!\n❓ <code>{q_text}</code> = ?",
                parse_mode=ParseMode.HTML
            )
            return

        joined, not_joined = await check_force_join(user.id, context)
        if not joined:
            await update.message.reply_text(
                f"📢 <b>ابتدا در کانال‌ها عضو شوید:</b>",
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

        u = db.get_user(user.id)
        if u and not u['first_reward_claimed']:
            reward = db.claim_first_reward(user.id)
            if reward:
                await update.message.reply_text(
                    f"🎉 <b>خوش‌آمدید!</b>\n🎁 +<code>{format_number(reward)}</code> DP هدیه ثبت‌نام",
                    parse_mode=ParseMode.HTML
                )

        await update.message.reply_text("✅ <b>تایید هویت موفق!</b>", parse_mode=ParseMode.HTML)
        await show_main_menu(update, context)
        return

    # اقدامات متنی ادمین
    if is_admin(user.id) and 'admin_action' in context.user_data:
        await handle_admin_text(update, context)
        return

    # ============ شماره کارت بانک ============
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

    # ============ واریز بانک ============
    if context.user_data.get('awaiting_bank_deposit'):
        try:
            amount = int(text)
            if amount <= 0:
                await update.message.reply_text("❌")
                return
            if db.bank_deposit(user.id, amount):
                context.user_data.pop('awaiting_bank_deposit', None)
                await update.message.reply_text(
                    f"✅ واریز موفق!\n💰 <code>{format_number(amount)}</code>\n📈 سود ۱۵٪ بعد از ۲۴ ساعت",
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text("❌ موجودی ناکافی!")
        except Exception:
            await update.message.reply_text("❌")
        return

    # ============ مقصد استارز ============
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
            f"✅ سفارش ثبت شد!\n⭐ {STARS_AMOUNT}\n👤 <code>{target}</code>",
            parse_mode=ParseMode.HTML
        )

        global BOT_USERNAME
        if not BOT_USERNAME:
            me = await context.bot.get_me()
            BOT_USERNAME = me.username

        user_display = f"@{user.username}" if user.username else f"<code>{user.id}</code>"
        log_kb = [[InlineKeyboardButton("🤖 ورود", url=f"https://t.me/{BOT_USERNAME}")]]
        await send_log(context,
            f"⭐ سفارش استارز\n👤 {user_display}\n📍 <code>{target}</code>\n🆔 <code>{order_id}</code>",
            reply_markup=InlineKeyboardMarkup(log_kb)
        )

        for admin_id in ADMIN_IDS:
            try:
                admin_kb = [
                    [InlineKeyboardButton("💬 پاسخ", callback_data=f"admin_reply_{user.id}")],
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
        return# ============ MAIN CALLBACK ROUTER ============

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user = query.from_user

    # چک خاموش بودن ربات (به جز ادمین)
    if not is_bot_active() and not is_admin(user.id):
        if not data.startswith("adm_") and not data.startswith("admin_"):
            await query.answer("⚠️ ربات موقتاً خاموش است!", show_alert=True)
            return

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
    elif data == "tasks_channel":
        await tasks_channel_cb(update, context)
    elif data == "tasks_mission":
        await tasks_mission_cb(update, context)
    elif data.startswith("task_view_"):
        await task_view_cb(update, context)
    elif data.startswith("task_verify_"):
        await task_verify_cb(update, context)
    elif data.startswith("task_mission_view_"):
        await task_mission_view_cb(update, context)
    elif data.startswith("task_mission_submit_"):
        await task_mission_submit_cb(update, context)
    elif data == "task_full":
        await query.answer("🔒 ظرفیت این تسک پر شده!", show_alert=True)
    elif data == "task_locked":
        await query.answer("⏳ در انتظار تایید یا ظرفیت پر", show_alert=True)

    # موجودی گروهی
    elif data.startswith("show_my_balance_"):
        await show_my_balance_cb(update, context)

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

    # بازی فوتبال
    elif data.startswith("football_pick_"):
        await football_pick_callback(update, context)
    elif data == "football_shoot":
        await football_shoot_callback(update, context)
    elif data == "football_cancel":
        await football_cancel_callback(update, context)

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

    # ادمین کالبک‌های ویژه
    elif data.startswith("admin_send_config_"):
        await admin_send_config_cb(update, context)
    elif data.startswith("admin_reply_"):
        await admin_reply_cb(update, context)
    elif data.startswith("admin_confirm_stars_"):
        await admin_confirm_stars_cb(update, context)
    elif data.startswith("admin_confirm_gift_"):
        await admin_confirm_gift_cb(update, context)
    elif data.startswith("admin_approve_mission_"):
        await admin_approve_mission_cb(update, context)
    elif data.startswith("admin_reject_mission_"):
        await admin_reject_mission_cb(update, context)

    # ادمین
    elif data.startswith("adm_"):
        await admin_callbacks(update, context)


# ============ TRACK BOT ADMIN STATUS IN GROUPS ============

async def my_chat_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ردیابی وضعیت ادمین بودن ربات در گروه‌ها"""
    try:
        chat = update.effective_chat
        if chat.type not in ['group', 'supergroup']:
            return

        new_member = update.my_chat_member.new_chat_member
        new_status = new_member.status

        try:
            count = await context.bot.get_chat_member_count(chat.id)
        except Exception:
            count = 0

        if new_status in ['administrator', 'creator']:
            db.add_or_update_group(chat.id, chat.title, count, 1)
            logger.info(f"Bot became admin in {chat.title} ({chat.id})")
        elif new_status in ['member', 'restricted']:
            db.add_or_update_group(chat.id, chat.title, count, 0)
            logger.info(f"Bot became regular member in {chat.title}")
        elif new_status in ['left', 'kicked']:
            # ربات از گروه خارج شد
            conn = db.get_conn()
            c = conn.cursor()
            c.execute("DELETE FROM groups WHERE chat_id = ?", (chat.id,))
            conn.commit()
            conn.close()
    except Exception as e:
        logger.error(f"my_chat_member error: {e}")


# ============ PERIODIC MAINTENANCE ============

async def periodic_maintenance(context: ContextTypes.DEFAULT_TYPE):
    """نگهداری خودکار کارخونه و پاکسازی بازی‌های قدیمی"""
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


async def check_bot_admin_in_all_groups(context: ContextTypes.DEFAULT_TYPE):
    """بررسی ادمین بودن ربات در تمام گروه‌های ثبت شده"""
    try:
        groups = db.get_all_groups()
        for g in groups:
            try:
                bot_member = await context.bot.get_chat_member(g['chat_id'], context.bot.id)
                is_admin_status = 1 if bot_member.status in ['administrator', 'creator'] else 0
                if g['is_admin'] != is_admin_status:
                    db.update_group_admin_status(g['chat_id'], is_admin_status)
            except Exception:
                pass
            await asyncio.sleep(0.2)
    except Exception as e:
        logger.error(f"Check admin status error: {e}")


# ============ ERROR HANDLER ============

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception:", exc_info=context.error)


# ============ CANCEL COMMAND ============

async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ همه عملیات‌ها لغو شد.")


# ============ BACKUP COMMAND (ADMIN) ============

async def backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /backup برای بکاپ‌گیری"""
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("❌ دسترسی ندارید!")
        return

    try:
        await update.message.reply_text("⏳ آماده‌سازی بکاپ کامل...")
        with open(db.db_name, 'rb') as f:
            await context.bot.send_document(
                chat_id=user.id,
                document=f,
                filename=f"darkpoint_full_backup_{int(time.time())}.db",
                caption=(
                    f"💾 <b>بکاپ کامل دیتابیس</b>\n\n"
                    f"📅 {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"👥 کاربران: {db.get_all_users_count()}\n"
                    f"💎 کل DP: {format_number(db.get_stats()['total_dp'])}\n\n"
                    f"<b>شامل تمام اطلاعات:</b>\n"
                    f"✅ کاربران + موجودی‌ها\n"
                    f"✅ سفارشات\n"
                    f"✅ تنظیمات\n"
                    f"✅ کانال‌ها و تسک‌ها\n"
                    f"✅ گروه‌ها و بانک‌ها"
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

    # Private messages (پشتیبانی از همه نوع)
    application.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & ~filters.COMMAND,
        handle_private_message
    ))

    # New chat members
    application.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS,
        on_new_chat_members
    ))

    # تغییرات وضعیت ادمین بودن ربات در گروه‌ها
    from telegram.ext import ChatMemberHandler
    application.add_handler(ChatMemberHandler(my_chat_member_handler, ChatMemberHandler.MY_CHAT_MEMBER))

    # Jobs
    application.job_queue.run_repeating(periodic_maintenance, interval=300, first=30)
    application.job_queue.run_repeating(self_ping, interval=480, first=60)
    application.job_queue.run_repeating(check_bot_admin_in_all_groups, interval=1800, first=120)

    print("🏴 Dark Point Bot Ultimate Version is running!")
    print(f"✅ Admin IDs: {ADMIN_IDS}")
    print(f"✅ Log Channel: {LOG_CHANNEL_ID}")
    logger.info("Bot started successfully")

    application.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
