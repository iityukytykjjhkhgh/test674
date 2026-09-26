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

# متغیر کش برای نام کاربری ربات
BOT_USERNAME = ""

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
    return f"{num1} + {num2}", num1 + num2

def get_user_display(user):
    safe_name = html.escape(user.first_name or "کاربر")
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
        logger.error(f"Log channel error: {e}")

def is_admin(user_id):
    return user_id in ADMIN_IDS

# ============ KEEP-ALIVE HTTP SERVER ============

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Dark Point Bot is Alive! 🏴".encode("utf-8"))
    def log_message(self, format, *args):
        return

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        logger.info(f"Health server listening on {port}")
    except Exception as e:
        logger.error(f"Health server error: {e}")

async def self_ping(context: ContextTypes.DEFAULT_TYPE):
    url = os.environ.get("RENDER_EXTERNAL_URL")
    if not url:
        return
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'DarkBotKeeper'})
        with urllib.request.urlopen(req, timeout=10) as r:
            pass
    except Exception:
        pass

# ============ START & MENU ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    if db.is_banned(user.id):
        await update.message.reply_text("❌ حساب کاربری شما مسدود شده است.")
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

        # ارسال سوال کپچا برای کاربر جدید
        if ref_id > 0:
            context.user_data['pending_ref'] = ref_id
            q_text, ans = generate_captcha()
            context.user_data['captcha_ans'] = ans

            await update.message.reply_text(
                f"🔐 <b>تایید هویت امنیتی</b>\n\n"
                f"لطفاً حاصل عبارت زیر را ارسال کنید:\n\n"
                f"❓ <code>{q_text}</code> = ?\n\n"
                f"💡 <i>فقط عدد پاسخ را بفرستید.</i>",
                parse_mode=ParseMode.HTML
            )
            return

    db.update_last_active(user.id)

    # بررسی چک هدیه
    if args and len(args) > 0 and args[0].startswith("check_"):
        code = args[0].replace("check_", "")
        amount = db.claim_check(code, user.id)
        if amount:
            db.add_dark_points(user.id, amount)
            await update.message.reply_text(
                f"🎁 <b>چک شخصی با موفقیت فعال شد!</b>\n\n"
                f"💰 مبلغ: <code>{format_number(amount)}</code> DP\n"
                f"✅ به کیف پول شما اضافه گردید.",
                parse_mode=ParseMode.HTML
            )
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        admin_id,
                        f"📋 فعال‌سازی چک شخصی\n👤 کاربر: <code>{user.id}</code>\n💰 مبلغ: <code>{format_number(amount)}</code> DP",
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass
            return
        else:
            await update.message.reply_text("❌ این چک قبلاً استفاده شده یا نامعتبر است.")
            return

    # بررسی عضویت اجباری
    joined = await check_force_join(user.id, context)
    if not joined:
        channels = db.get_force_channels()
        channels_text = "\n".join([f"🔗 {ch['channel_username']}" for ch in channels])
        kb = [[InlineKeyboardButton("✅ تایید عضویت", callback_data="check_join_main")]]
        await update.message.reply_text(
            f"📢 <b>برای استفاده از ربات، ابتدا در کانال‌های زیر عضو شوید:</b>\n\n"
            f"{channels_text}\n\n"
            f"سپس دکمه تایید را فشار دهید.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(kb)
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
    balance = db_user['dark_points'] if db_user else 0
    level = db_user['level'] if db_user else 1
    title = get_level_title(level)
    safe_name = html.escape(user.first_name or "کاربر")

    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await context.bot.get_me()
        BOT_USERNAME = me.username

    keyboard = [
        [InlineKeyboardButton("⭐ برداشت استارز ⭐", callback_data="stars_withdraw")],
        [
            InlineKeyboardButton("🏴 دارک پوینت", callback_data="dark_point_menu"),
            InlineKeyboardButton("🛒 خرید پنل VPN", callback_data="buy_panel"),
        ],
        [
            InlineKeyboardButton("💥 بازی انفجار", callback_data="crash_menu"),
            InlineKeyboardButton("🎁 گیفت رایگان", callback_data="free_gift"),
        ],
        [
            InlineKeyboardButton("💰 خرید DP", callback_data="buy_dp"),
            InlineKeyboardButton("❤️ چالش لایکی", callback_data="like_challenge"),
        ],
        [
            InlineKeyboardButton("👥 زیرمجموعه‌گیری", callback_data="referral_menu"),
            InlineKeyboardButton("🏆 لیدربورد", callback_data="leaderboard"),
        ],
        [InlineKeyboardButton("➕ افزودن به گروه", url=f"https://t.me/{BOT_USERNAME}?startgroup=true")],
    ]

    text = (
        f"🏴 <b>به ربات دارک پوینت خوش آمدید!</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 کاربر: <b>{safe_name}</b>\n"
        f"🆔 شناسه: <code>{user.id}</code>\n"
        f"💎 موجودی: <code>{format_number(balance)}</code> DP\n"
        f"📊 سطح فعلی: {level} | {title}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⭐ <i>با جمع‌آوری دارک پوینت، استارز و پنل رایگان بگیرید!</i>"
    )

    if query:
        try:
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception:
            await query.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))


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
        [InlineKeyboardButton("📖 راهنمای کامل", callback_data="dp_info_1")],
        [InlineKeyboardButton("🔗 لینک زیرمجموعه‌گیری", callback_data="referral_menu")],
        [InlineKeyboardButton("🏆 جدول برترین‌ها", callback_data="leaderboard")],
        [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="main_menu")],
    ]

    text = (
        f"🏴 <b>مدیریت دارک پوینت</b>\n\n"
        f"💎 موجودی کیف پول: <code>{format_number(balance)}</code> DP\n"
        f"📊 سطح کاربری: {level} | {title}\n"
    )
    if next_req:
        text += f"📈 امتیاز لازم برای سطح بعد: <code>{format_number(needed)}</code> DP\n"
    else:
        text += f"🏆 شما به بالاترین سطح ممکن رسیده‌اید!\n"

    text += f"👥 تعداد زیرمجموعه‌ها: {user['referral_count'] if user else 0}"

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))


INFO_PAGES = {
    1: "📖 <b>راهنما (۱/۴): دارک پوینت چیست؟</b>\n\nدارک پوینت ارز درون ربات است که می‌توانید با آن استارز تلگرام، پنل VPN و گیفت خریداری کنید.",
    2: "📖 <b>راهنما (۲/۴): کسب درآمد در گروه</b>\n\nکافیست ربات را در گروه خود ادد کنید و بنویسید <code>دارک</code> تا پاداش دریافت کنید.",
    3: "📖 <b>راهنما (۳/۴): بانک و کارخونه</b>\n\nدر گروه با دستور <code>کارخونه دارکی</code> و <code>بانک دارکی</code> می‌توانید کسب سود فعال و غیرفعال داشته باشید.",
    4: "📖 <b>راهنما (۴/۴): بازی انفجار</b>\n\nدر گروه دستور <code>انفجار 1000</code> را بفرستید و ضریب‌های شگفت‌انگیز را تجربه کنید!",
}

async def dp_info_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    page = int(query.data.split("_")[-1])
    text = INFO_PAGES.get(page, "صفحه یافت نشد")

    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"dp_info_{page-1}"))
    if page < 4:
        buttons.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"dp_info_{page+1}"))

    keyboard = [buttons] if buttons else []
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="dark_point_menu")])

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))


# ============ GROUP INTERACTIONS ============

async def on_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            try:
                count = await context.bot.get_chat_member_count(chat.id)
                if count < MIN_GROUP_MEMBERS:
                    await update.message.reply_text(
                        f"❌ <b>گروه باید حداقل {MIN_GROUP_MEMBERS} عضو داشته باشد!</b>\nتعداد فعلی: {count}",
                        parse_mode=ParseMode.HTML
                    )
                    await context.bot.leave_chat(chat.id)
                    return
                db.add_group(chat.id, chat.title, count)
                await update.message.reply_text(
                    "🏴 <b>ربات دارک پوینت با موفقیت در این گروه فعال شد!</b>\n\n"
                    "دستورات موجود:\n"
                    "• <code>دارک</code>\n"
                    "• <code>موجودی</code>\n"
                    "• <code>پروفایل دارکی</code>\n"
                    "• <code>بازی 1000</code>\n"
                    "• <code>انفجار 1000</code>\n"
                    "• <code>بانک دارکی</code>\n"
                    "• <code>کارخونه دارکی</code>",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Error joining group: {e}")


async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    user = update.effective_user

    if db.is_banned(user.id):
        return

    if not db.get_user(user.id):
        db.create_user(user.id, user.username or "", user.first_name or "")

    db.update_last_active(user.id)

    if text in ['دارک', 'دارک کانفیگ']:
        await handle_dark_claim(update, context)
    elif text == 'موجودی':
        balance = db.get_balance(user.id)
        level = db.get_level(user.id)
        safe_name = html.escape(user.first_name or "کاربر")
        await update.message.reply_text(
            f"👤 کاربر: <b>{safe_name}</b>\n💰 موجودی: <code>{format_number(balance)}</code> DP\n📊 سطح: {level}",
            parse_mode=ParseMode.HTML
        )
    elif text == 'پروفایل دارکی':
        await handle_dark_profile(update, context)
    elif text.startswith('بازی'):
        parts = text.split()
        if len(parts) >= 2 and parts[1].isdigit():
            await handle_create_game(update, context, int(parts[1]))
    elif text.startswith('انفجار'):
        parts = text.split()
        if len(parts) >= 2 and parts[1].isdigit():
            await handle_crash_game_group(update, context, int(parts[1]))
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

    rem = db.get_cooldown_remaining(user.id)
    if rem > 0:
        mins = int(rem // 60)
        secs = int(rem % 60)
        await update.message.reply_text(f"⏳ لطفاً <b>{mins}m {secs}s</b> دیگر صبر کنید.", parse_mode=ParseMode.HTML)
        return

    level = u['level']
    min_dp, max_dp = get_dp_range(level)
    earned = random.randint(min_dp, max_dp)
    cooldown = get_random_cooldown()

    db.add_dark_points(user.id, earned)
    db.set_claim(user.id, cooldown)
    new_level, reward = db.check_and_update_level(user.id)
    safe_name = html.escape(user.first_name or "کاربر")

    text = (
        f"🏴 <b>دارک پوینت دریافت شد!</b>\n\n"
        f"👤 کاربر: <b>{safe_name}</b>\n"
        f"💎 مقدار پاداش: +<code>{format_number(earned)}</code> DP\n"
        f"💰 موجودی کل: <code>{format_number(db.get_balance(user.id))}</code> DP"
    )
    if new_level:
        text += f"\n\n🎉 <b>تبریک! ارتقا به سطح {new_level}!</b> (+{format_number(reward)} DP)"

    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def handle_dark_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = db.get_user(user.id)
    if not u:
        return

    level = u['level']
    balance = u['dark_points']
    total = u['total_earned']
    safe_name = html.escape(user.first_name or "کاربر")

    text = (
        f"🏴 <b>پروفایل دارکی</b>\n━━━━━━━━━━\n"
        f"👤 نام: <b>{safe_name}</b>\n"
        f"🆔 شناسه: <code>{user.id}</code>\n"
        f"💰 موجودی: <code>{format_number(balance)}</code> DP\n"
        f"📊 سطح: {level} | {get_level_title(level)}\n"
        f"👥 زیرمجموعه‌ها: {u['referral_count']}\n"
        f"💥 بازی انفجار: {u['crash_games_won']}/{u['crash_games_played']}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ============ GAME & CRASH ============

async def handle_create_game(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: int):
    user = update.effective_user
    if amount < MIN_GAME_AMOUNT or db.get_balance(user.id) < amount:
        await update.message.reply_text("❌ موجودی ناکافی یا مبلغ کمتر از حد مجاز است.")
        return

    db.remove_dark_points(user.id, amount)
    msg = await update.message.reply_text(
        f"🎮 <b>بازی دو نفره ایجاد شد!</b>\n👤 سازنده: {get_user_display(user)}\n💰 شرط: <code>{format_number(amount)}</code> DP",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎮 پیوستن به بازی", callback_data="join_game_0")]])
    )
    game_id = db.create_game(user.id, amount, update.effective_chat.id, msg.message_id)
    await msg.edit_reply_markup(InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 پیوستن به بازی", callback_data=f"join_game_{game_id}")],
        [InlineKeyboardButton("❌ لغو بازی", callback_data=f"cancel_game_{game_id}")],
    ]))


async def handle_crash_game_group(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: int):
    user = update.effective_user
    if amount < CRASH_MIN_BET or amount > CRASH_MAX_BET or db.get_balance(user.id) < amount:
        await update.message.reply_text("❌ مبلغ شرط نامعتبر یا موجودی ناکافی است.")
        return

    db.remove_dark_points(user.id, amount)
    crash_point = round(random.uniform(1.1, 5.0), 2)

    msg = await update.message.reply_text(
        f"💥 <b>بازی انفجار</b>\n👤 بازیکن: {get_user_display(user)}\n💰 شرط: <code>{format_number(amount)}</code> DP\n🚀 ضریب: <code>1.00x</code>",
        parse_mode=ParseMode.HTML
    )
    game_id = db.create_crash_game(user.id, amount, crash_point, update.effective_chat.id, msg.message_id)
    await msg.edit_reply_markup(InlineKeyboardMarkup([[InlineKeyboardButton("💰 برداشت (Cash Out)", callback_data=f"crash_out_{game_id}")]]))

    async def animate():
        cur = 1.0
        while cur < crash_point:
            g = db.get_crash_game(game_id)
            if not g or g['status'] != 'playing':
                return
            await asyncio.sleep(1.2)
            cur = round(cur + 0.2, 2)
            if cur >= crash_point:
                break
            try:
                await msg.edit_text(
                    f"💥 <b>بازی انفجار زنده</b>\n👤 بازیکن: {get_user_display(user)}\n🚀 ضریب فعلی: <code>{cur}x</code> 📈",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"💰 برداشت در {cur}x", callback_data=f"crash_out_{game_id}")]])
                )
            except Exception:
                pass
        g = db.get_crash_game(game_id)
        if g and g['status'] == 'playing':
            db.crash_game_lost(game_id)
            db.increment_crash_stats(user.id, won=False)
            try:
                await msg.edit_text(f"💥💥 <b>منفجر شد در {crash_point}x!</b>\nباخت شرط <code>{format_number(amount)}</code> DP", parse_mode=ParseMode.HTML)
            except Exception:
                pass
    asyncio.create_task(animate())


async def crash_out_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    game_id = int(query.data.split("_")[-1])

    g = db.get_crash_game(game_id)
    if not g or g['user_id'] != user.id or g['status'] != 'playing':
        await query.answer("❌ این بازی به اتمام رسیده است.", show_alert=True)
        return

    msg_text = query.message.text
    match = re.search(r'(\d+\.\d+)x', msg_text)
    mult = float(match.group(1)) if match else 1.2
    win_amt = int(g['bet_amount'] * mult)

    if db.cashout_crash_game(game_id, mult, win_amt - g['bet_amount']):
        db.add_dark_points(user.id, win_amt)
        db.increment_crash_stats(user.id, won=True)
        await query.answer(f"✅ با موفقیت برداشت شد! +{format_number(win_amt)} DP", show_alert=True)
        await query.edit_message_text(f"🎉 <b>برنده شدید!</b>\nضریب: <code>{mult}x</code>\nجایزه: <code>{format_number(win_amt)}</code> DP", parse_mode=ParseMode.HTML)


# ============ TRANSFERS, BANK, FACTORY ============

async def handle_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    match = re.match(r'انتقال\s+(\d+)\s+به\s+(\d+)', text)
    if match:
        amount = int(match.group(1))
        target_id = int(match.group(2))
        fee = int(amount * TRANSFER_FEE)
        if db.get_balance(user.id) >= amount + fee:
            db.remove_dark_points(user.id, amount + fee)
            db.add_dark_points(target_id, amount)
            db.record_transfer(user.id, target_id, amount, fee)
            await update.message.reply_text(f"✅ <code>{format_number(amount)}</code> DP انتقال یافت.", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("❌ موجودی ناکافی است.")


async def handle_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = db.get_user(user.id)
    if not u['bank_account']:
        kb = [[InlineKeyboardButton("🏦 افتتاح حساب (20,000 DP)", callback_data="bank_open")]]
        await update.message.reply_text("🏦 شما حسابی ندارید. برای افتتاح کلیک کنید:", reply_markup=InlineKeyboardMarkup(kb))
    else:
        kb = [[InlineKeyboardButton("💰 واریز به بانک", callback_data="bank_deposit")], [InlineKeyboardButton("💸 برداشت موجودی", callback_data="bank_withdraw")]]
        await update.message.reply_text(f"🏦 <b>کارت:</b> <code>{u['bank_card']}</code>\n💰 <b>موجودی در بانک:</b> <code>{format_number(u['bank_balance'])}</code> DP", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def handle_factory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = db.get_user(user.id)
    if not u['factory_active']:
        kb = [[InlineKeyboardButton(f"🏭 افتتاح ({format_number(FACTORY_OPEN_COST)} DP)", callback_data="factory_open")]]
        await update.message.reply_text("🏭 شما کارخونه‌ای ندارید:", reply_markup=InlineKeyboardMarkup(kb))
    else:
        mined = db.collect_factory(user.id)
        kb = [[InlineKeyboardButton("💰 جمع‌آوری سود", callback_data="factory_collect")]]
        await update.message.reply_text(f"🏭 کارخونه سطح {u['factory_level']}\nماین شده: +<code>{format_number(mined)}</code> DP", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def handle_leaderboard_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.get_leaderboard(10)
    text = "🏆 <b>۱۰ کاربر برتر دارک پوینت:</b>\n\n"
    for i, row in enumerate(rows, 1):
        name = html.escape(row['first_name'] or str(row['user_id']))
        text += f"{i}. {name} — <code>{format_number(row['dark_points'])}</code> DP\n"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ============ ADMIN & PRIVATE ============

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        return

    stats = db.get_stats()
    kb = [
        [InlineKeyboardButton("📢 پیام همگانی", callback_data="adm_broadcast_msg"), InlineKeyboardButton("📤 فوروارد همگانی", callback_data="adm_broadcast_fwd")],
        [InlineKeyboardButton("💰 افزودن DP", callback_data="adm_add_dp"), InlineKeyboardButton("💸 کسر DP", callback_data="adm_remove_dp")],
        [InlineKeyboardButton("📢 کانال‌های اجباری", callback_data="adm_channels"), InlineKeyboardButton("📝 ساخت چک", callback_data="adm_create_check")],
        [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="main_menu")],
    ]
    await update.message.reply_text(
        f"🛡 <b>پنل مدیریت</b>\n\n👥 کاربران: {stats['total_users']}\n💎 کل DP: {format_number(stats['total_dp'])}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()

    # پاسخ کپچای زیرمجموعه
    if 'captcha_ans' in context.user_data:
        try:
            if int(text) == context.user_data['captcha_ans']:
                ref = context.user_data.get('pending_ref', 0)
                if ref > 0:
                    db.add_referral(ref)
                    db.add_dark_points(ref, REFERRAL_REWARD)
                    try:
                        await context.bot.send_message(ref, f"🎉 <b>زیرمجموعه جدید تایید شد!</b> (+{format_number(REFERRAL_REWARD)} DP)", parse_mode=ParseMode.HTML)
                    except Exception:
                        pass
                context.user_data.pop('captcha_ans', None)
                await update.message.reply_text("✅ هویت شما با موفقیت تایید شد.")
                await show_main_menu(update, context)
                return
            else:
                await update.message.reply_text("❌ پاسخ نادرست است! مجدداً امتحان کنید.")
                return
        except Exception:
            return

    # پردازش اقدامات ادمین
    if is_admin(user.id) and 'admin_action' in context.user_data:
        action = context.user_data['admin_action']
        if action == 'add_dp':
            parts = text.split()
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                db.add_dark_points(int(parts[0]), int(parts[1]))
                await update.message.reply_text(f"✅ مبلغ {parts[1]} DP به کاربر {parts[0]} اضافه شد.")
                context.user_data.clear()
                return
        elif action == 'create_check' and text.isdigit():
            code = db.create_check(int(text))
            await update.message.reply_text(f"✅ چک ساخته شد:\nhttps://t.me/{BOT_USERNAME}?start=check_{code}")
            context.user_data.clear()
            return
        elif action == 'add_channel':
            ch = text if text.startswith('@') else '@' + text
            db.add_force_channel(ch)
            await update.message.reply_text(f"✅ کانال {ch} به عضویت اجباری اضافه شد.")
            context.user_data.clear()
            return


# ============ CALLBACK ROUTER ============

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user = query.from_user

    if data == "main_menu":
        await show_main_menu(update, context, query=query)
    elif data == "dark_point_menu":
        await dark_point_menu(update, context)
    elif data.startswith("dp_info_"):
        await dp_info_page(update, context)
    elif data == "stars_withdraw":
        stars_price = int(db.get_setting('stars_price', '1000000'))
        bal = db.get_balance(user.id)
        if bal >= stars_price:
            db.remove_dark_points(user.id, stars_price)
            db.create_stars_order(user.id, str(user.id), 'self', STARS_AMOUNT, stars_price)
            await query.answer("✅ سفارش استارز ثبت شد.", show_alert=True)
        else:
            await query.answer(f"❌ موجودی ناکافی! نیاز: {format_number(stars_price)} DP", show_alert=True)
    elif data == "free_gift":
        await query.answer("🎁 گیفت تدی به زودی!", show_alert=True)
    elif data == "buy_panel":
        await query.answer("🛒 برای خرید پنل به پشتیبانی پیام دهید.", show_alert=True)
    elif data == "buy_dp":
        await query.answer("💰 هر ۵۰۰ هزار DP = ۵۰ هزار تومان", show_alert=True)
    elif data == "referral_menu":
        await query.edit_message_text(f"🔗 لینک شما:\nhttps://t.me/{BOT_USERNAME}?start=ref_{user.id}")
    elif data == "leaderboard":
        rows = db.get_leaderboard(10)
        t = "🏆 <b>برترین‌ها:</b>\n\n" + "\n".join([f"{i}. {r['user_id']} — {format_number(r['dark_points'])} DP" for i, r in enumerate(rows, 1)])
        await query.edit_message_text(t, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]))
    elif data == "check_join_main":
        joined = await check_force_join(user.id, context)
        if joined:
            await show_main_menu(update, context, query=query)
        else:
            await query.answer("❌ هنوز عضو کانال‌ها نشده‌اید!", show_alert=True)
    elif data.startswith("join_game_"):
        gid = int(data.split("_")[-1])
        g = db.get_game(gid)
        if g and g['status'] == 'waiting' and user.id != g['creator_id'] and db.get_balance(user.id) >= g['amount']:
            db.remove_dark_points(user.id, g['amount'])
            winner = random.choice([g['creator_id'], user.id])
            db.add_dark_points(winner, g['amount'] * 2)
            db.finish_game(gid, winner, user.id if winner == g['creator_id'] else g['creator_id'])
            await query.edit_message_text(f"🎮 بازی تمام شد! برنده: <code>{winner}</code> (+{format_number(g['amount']*2)} DP)", parse_mode=ParseMode.HTML)
        else:
            await query.answer("❌ امکان ورود به بازی وجود ندارد.", show_alert=True)
    elif data.startswith("crash_out_"):
        await crash_out_callback(update, context)
    elif data == "bank_open":
        if db.get_balance(user.id) >= BANK_OPEN_COST:
            card = db.generate_bank_card()
            db.remove_dark_points(user.id, BANK_OPEN_COST)
            db.open_bank_account(user.id, card)
            await query.answer("✅ حساب افتتاح شد!", show_alert=True)
            await query.edit_message_text(f"💳 کارت شما: <code>{card}</code>", parse_mode=ParseMode.HTML)
        else:
            await query.answer("❌ موجودی ناکافی است.", show_alert=True)
    elif data == "factory_open":
        if db.get_balance(user.id) >= FACTORY_OPEN_COST:
            db.remove_dark_points(user.id, FACTORY_OPEN_COST)
            db.open_factory(user.id)
            await query.answer("✅ کارخونه استخراج فعال شد!", show_alert=True)
        else:
            await query.answer("❌ موجودی ناکافی است.", show_alert=True)
    elif data == "adm_add_dp":
        context.user_data['admin_action'] = 'add_dp'
        await query.edit_message_text("ارسال کنید: [شناسه عددی] [مبلغ]\nمثال: <code>123456789 50000</code>", parse_mode=ParseMode.HTML)
    elif data == "adm_create_check":
        context.user_data['admin_action'] = 'create_check'
        await query.edit_message_text("مبلغ چک را به عدد ارسال کنید:")
    elif data == "adm_channels":
        context.user_data['admin_action'] = 'add_channel'
        await query.edit_message_text("یوزرنیم کانال را با @ ارسال کنید:")


# ============ ERROR HANDLER ============

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)


# ============ MAIN ============

def main():
    start_health_server()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_error_handler(error_handler)

    # ثبت هندلرها بدون قفل
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CallbackQueryHandler(callback_router))
    application.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, handle_group_message))
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, handle_private_message))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_chat_members))

    # تسک پینگ جهت آنلاین ماندن
    application.job_queue.run_repeating(self_ping, interval=400, first=30)

    print("🚀 Dark Point Bot is starting...")
    application.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
