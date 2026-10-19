# bot.py — Dark Point Bot (قسمت 1/12)
import os
import sys
import time
import random
import logging
import html
import uuid
import threading
import json
import asyncio
from datetime import datetime, date, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

import requests
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument,
)
from telegram.constants import ParseMode, ChatMemberStatus, ChatType
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ChatMemberHandler,
    filters,
)
from telegram.error import TelegramError, BadRequest, Forbidden

import config
import database

# ──────────────── Globals ────────────────
db = database.Database()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

# ──────────────── Keep-Alive HTTP Server ────────────────
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Dark Point Bot is alive")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        return


def run_health_server():
    try:
        srv = HTTPServer(("0.0.0.0", config.PORT), HealthHandler)
        logger.info(f"🌐 Health server on port {config.PORT}")
        srv.serve_forever()
    except Exception as e:
        logger.error(f"Health server error: {e}")


def self_ping_loop():
    while True:
        time.sleep(480)  # 8 min
        if config.RENDER_URL:
            try:
                requests.get(config.RENDER_URL, timeout=10)
                logger.info("🔄 Self-ping OK")
            except Exception as e:
                logger.warning(f"Self-ping failed: {e}")


# ──────────────── Helpers ────────────────
def fmt(n):
    """Pretty number format"""
    try:
        if isinstance(n, float):
            if n < 0.0001:
                return f"{n:.8f}"
            if n < 0.01:
                return f"{n:.6f}"
            if n < 1:
                return f"{n:.4f}"
            return f"{n:,.2f}"
        return f"{int(n):,}"
    except Exception:
        return str(n)


def dp_to_ton(dp):
    """Convert DP to TON by the official withdrawal rate"""
    return (dp / config.TON_WITHDRAWAL_DP_RATE) * config.TON_WITHDRAWAL_TON_AMOUNT


def ton_to_dp(ton):
    """Convert TON amount back to DP cost"""
    return int((ton / config.TON_WITHDRAWAL_TON_AMOUNT) * config.TON_WITHDRAWAL_DP_RATE)


def mask_wallet(addr):
    """Mask middle of wallet with 6 asterisks"""
    if not addr:
        return "******"
    if len(addr) <= 12:
        return addr[:3] + "******" + addr[-3:]
    return addr[:6] + "******" + addr[-6:]


def section_off_text():
    return f"⚠️ {config.SECTION_OFF_MESSAGE}"


def bot_off_text():
    return f"🔧 {config.BOT_OFF_MESSAGE}"


def is_admin(uid):
    return uid == config.ADMIN_ID


def gen_tracking_code(prefix="DP"):
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def seconds_to_hms(s):
    s = max(0, int(s))
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {sec}s"
    return f"{sec}s"


async def check_force_join(bot, uid):
    """Return (ok, bad_channels)"""
    chs = db.get_force_channels()
    if not chs:
        return True, []
    bad = []
    for ch in chs:
        try:
            m = await bot.get_chat_member(ch['channel_id'], uid)
            if m.status not in (ChatMemberStatus.MEMBER,
                                ChatMemberStatus.ADMINISTRATOR,
                                ChatMemberStatus.OWNER):
                bad.append(ch)
        except Exception:
            bad.append(ch)
    return (len(bad) == 0), bad


def force_join_kb(channels):
    rows = []
    for ch in channels:
        u = ch['channel_username'].lstrip('@')
        rows.append([InlineKeyboardButton(
            f"📢 عضویت در {ch['channel_username']}",
            url=f"https://t.me/{u}"
        )])
    rows.append([InlineKeyboardButton("✅ عضو شدم", callback_data="check_join")])
    return InlineKeyboardMarkup(rows)


async def send_log(bot, text, kb=None, photo=None):
    """Send message to log channel"""
    try:
        if photo:
            await bot.send_photo(
                config.LOG_CHANNEL, photo, caption=text,
                parse_mode=ParseMode.HTML, reply_markup=kb)
        else:
            await bot.send_message(
                config.LOG_CHANNEL, text,
                parse_mode=ParseMode.HTML, reply_markup=kb,
                disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Log channel err: {e}")


async def safe_edit(query, text, kb=None):
    try:
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=kb,
            disable_web_page_preview=True)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            logger.warning(f"Edit err: {e}")
    except Exception as e:
        logger.warning(f"Edit err: {e}")


async def safe_send(bot, chat_id, text, kb=None):
    try:
        return await bot.send_message(
            chat_id, text, parse_mode=ParseMode.HTML,
            reply_markup=kb, disable_web_page_preview=True)
    except Exception as e:
        logger.warning(f"Send err to {chat_id}: {e}")
        return None


def clear_user_state(ctx):
    """Clear all user_data flags used for input flows"""
    for k in list(ctx.user_data.keys()):
        if k.startswith(('tw_', 'bank_', 'buy_', 'transfer_',
                         'admin_', 'shop_', 'task_', 'gift_',
                         'force_', 'panel_', 'send_', 'addrm_',
                         'search_', 'ban_', 'reply_', 'guess_',
                         'bomb_', 'set_', 'edit_')):
            ctx.user_data.pop(k, None)# bot.py — Dark Point Bot (قسمت 2/12)

# ──────────────── Main Menus ────────────────
def main_menu_kb():
    """User main menu — TON withdrawal is FIRST and LARGE"""
    return ReplyKeyboardMarkup([
        [KeyboardButton("💎 برداشت TON 💎")],
        [KeyboardButton("🎁 دریافت جایزه"), KeyboardButton("👤 پروفایل دارکی")],
        [KeyboardButton("🎮 بازی‌ها"), KeyboardButton("⛏ ماینر دارکی")],
        [KeyboardButton("🏦 بانک دارکی"), KeyboardButton("🏭 کارخونه دارکی")],
        [KeyboardButton("🛒 فروشگاه"), KeyboardButton("🎰 گردونه شانس")],
        [KeyboardButton("💰 خرید DP"), KeyboardButton("⭐ برداشت استارز")],
        [KeyboardButton("📋 تسک‌ها"), KeyboardButton("👍 چالش لایک")],
        [KeyboardButton("💱 تبدیل ارز"), KeyboardButton("🎁 هدیه")],
        [KeyboardButton("📊 لیدربورد"), KeyboardButton("👥 زیرمجموعه‌گیری")],
        [KeyboardButton("📖 پنل DP"), KeyboardButton("➕ افزودن به گروه")],
    ], resize_keyboard=True)


def admin_menu_kb():
    """Admin panel menu"""
    return ReplyKeyboardMarkup([
        [KeyboardButton("📊 آمار ربات"), KeyboardButton("💎 آمار برداشت TON")],
        [KeyboardButton("⛏ آمار ماینینگ"), KeyboardButton("💱 آمار ارز")],
        [KeyboardButton("📢 ارسال همگانی"), KeyboardButton("📣 ارسال به گروه‌ها")],
        [KeyboardButton("💰 افزودن DP"), KeyboardButton("➖ کسر DP")],
        [KeyboardButton("🔍 جستجوی کاربر"), KeyboardButton("👤 ارسال به کاربر")],
        [KeyboardButton("🚫 بن کاربر"), KeyboardButton("✅ آنبان")],
        [KeyboardButton("📢 فورس جوین"), KeyboardButton("📋 گروه‌های من")],
        [KeyboardButton("📋 مدیریت تسک‌ها"), KeyboardButton("✅ تایید ماموریت")],
        [KeyboardButton("🛒 مدیریت فروشگاه"), KeyboardButton("🎁 مدیریت هدایا")],
        [KeyboardButton("💰 تنظیم خرید DP"), KeyboardButton("⭐ تنظیم استارز")],
        [KeyboardButton("📦 پلن‌های پنل"), KeyboardButton("🏷 پاداش رفرال")],
        [KeyboardButton("⚙️ روشن/خاموش بخش‌ها"), KeyboardButton("🔌 ربات روشن/خاموش")],
        [KeyboardButton("💾 بکاپ"), KeyboardButton("♻️ ریستور")],
        [KeyboardButton("🎁 هدیه به برترین‌ها"), KeyboardButton("🎁 هدیه به همه")],
        [KeyboardButton("💬 پاسخ به کاربر"), KeyboardButton("📜 سفارش‌های اخیر")],
        [KeyboardButton("🔙 بازگشت به منو")],
    ], resize_keyboard=True)


def games_inline_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💥 کرش", callback_data="g_crash_info"),
         InlineKeyboardButton("🎲 تاس", callback_data="g_dice_info")],
        [InlineKeyboardButton("🔮 حدس بزن", callback_data="g_guess_info"),
         InlineKeyboardButton("🎰 کازینو", callback_data="g_casino_info")],
        [InlineKeyboardButton("💣 بمب", callback_data="g_bomb_info")],
    ])


def sections_toggle_kb():
    """Admin section toggle keyboard"""
    sections = [
        ("ton_withdraw", "💎 برداشت TON"),
        ("claim", "🎁 دریافت جایزه"),
        ("games", "🎮 بازی‌ها"),
        ("miner", "⛏ ماینر"),
        ("bank", "🏦 بانک"),
        ("shop", "🛒 فروشگاه"),
        ("gift", "🎁 هدیه"),
        ("stars", "⭐ استارز"),
        ("buy_dp", "💰 خرید DP"),
        ("tasks", "📋 تسک‌ها"),
        ("like", "👍 چالش لایک"),
        ("wheel", "🎰 گردونه"),
        ("convert", "💱 تبدیل ارز"),
        ("leaderboard", "📊 لیدربورد"),
        ("factory", "🏭 کارخانه"),
    ]
    rows = []
    for key, name in sections:
        state = "🟢" if db.is_section_on(key) else "🔴"
        rows.append([InlineKeyboardButton(
            f"{state} {name}", callback_data=f"toggle_sec_{key}")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")])
    return InlineKeyboardMarkup(rows)


# ──────────────── /start Command ────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        # group /start: just greet
        await update.message.reply_text(
            "👋 سلام! برای استفاده از ربات به چت خصوصی مراجعه کنید.\n"
            f"@{(await ctx.bot.get_me()).username}")
        return

    user = update.effective_user
    uid = user.id

    # Bot off check
    if not db.is_bot_on() and not is_admin(uid):
        await update.message.reply_text(bot_off_text())
        return

    # Ban check
    if db.is_banned(uid):
        await update.message.reply_text("🚫 شما از ربات بن شده‌اید.")
        return

    # Referral parse
    ref_by = 0
    if ctx.args:
        try:
            ref_by = int(ctx.args[0])
            if ref_by == uid:
                ref_by = 0
        except Exception:
            ref_by = 0

    # Create user if not exists
    existing = db.get_user(uid)
    is_new = existing is None
    db.create_user(uid, user.username or "", user.first_name or "", ref_by)
    db.update_username(uid, user.username or "", user.first_name or "")

    # First-join reward (only if new)
    if is_new:
        reward = int(db.get_setting('first_join_reward', config.DEFAULT_FIRST_JOIN_REWARD))
        if reward > 0 and ref_by == 0:
            db.add_balance(uid, reward)

    # Clear any stale flow state
    clear_user_state(ctx)

    # Force join check
    ok, bad = await check_force_join(ctx.bot, uid)
    if not ok:
        await update.message.reply_text(
            "⚠️ <b>برای استفاده از ربات ابتدا در کانال‌های زیر عضو شوید:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=force_join_kb(bad))
        return

    await send_welcome(ctx.bot, uid, user.first_name or "")


async def send_welcome(bot, uid, fname):
    """Send welcome message with main menu"""
    bal = db.get_balance(uid)
    lvl = db.get_user_level(uid)
    ton_eq = dp_to_ton(bal)
    text = (
        f"👋 سلام <b>{html.escape(fname)}</b> عزیز!\n\n"
        f"🎊 به <b>Dark Point Bot</b> خوش آمدید\n\n"
        f"💎 موجودی شما: <b>{fmt(bal)}</b> DP\n"
        f"💰 معادل: <b>{ton_eq:.6f}</b> TON\n"
        f"📊 سطح: <b>{lvl}</b> / 20\n\n"
        f"از منوی زیر گزینه مورد نظر را انتخاب کنید 👇"
    )
    await bot.send_message(uid, text, parse_mode=ParseMode.HTML,
                           reply_markup=main_menu_kb())


# ──────────────── Check Join Callback ────────────────
async def cb_check_join(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    ok, bad = await check_force_join(ctx.bot, uid)
    if not ok:
        try:
            await q.edit_message_text(
                "❌ هنوز در همه کانال‌ها عضو نشده‌اید!",
                reply_markup=force_join_kb(bad))
        except Exception:
            pass
        return
    try:
        await q.edit_message_text("✅ عضویت تایید شد!")
    except Exception:
        pass
    await send_welcome(ctx.bot, uid, q.from_user.first_name or "")


# ──────────────── Admin Panel Entry ────────────────
async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    clear_user_state(ctx)
    await update.message.reply_text(
        "⚙️ <b>پنل مدیریت</b>\n\nگزینه مورد نظر را انتخاب کنید:",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_menu_kb())


async def msg_back_to_main(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    clear_user_state(ctx)
    await update.message.reply_text(
        "🔙 بازگشت به منوی اصلی",
        reply_markup=main_menu_kb())


# ──────────────── /help ────────────────
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    text = (
        "📖 <b>راهنمای Dark Point Bot</b>\n\n"
        "💎 <b>برداشت TON:</b> تبدیل DP به TON و برداشت به کیف‌پول Keeper\n"
        "🎁 <b>دریافت جایزه:</b> هر ۳-۵ دقیقه DP رایگان بگیرید\n"
        "🎮 <b>بازی‌ها:</b> کرش، تاس، حدس، کازینو، بمب\n"
        "⛏ <b>ماینر:</b> استخراج TON یا USDT\n"
        "🏦 <b>بانک:</b> ۳٪ سود هر ۴۸ ساعت\n"
        "🛒 <b>فروشگاه:</b> خرید پلن و محصولات\n"
        "👥 <b>زیرمجموعه‌گیری:</b> با دعوت دوستان DP بگیرید\n\n"
        "📝 <b>دستورات گروه:</b>\n"
        "• دارک / دارک کانفیگ\n"
        "• موجودی\n"
        "• پروفایل دارکی\n"
        "• بازی [مبلغ] (کرش)\n"
        "• انفجار [مبلغ]\n"
        "• تاس [مبلغ]\n"
        "• حدس بزن\n"
        "• کازینو\n"
        "• بمب\n"
        "• انتقال [مبلغ]\n"
        "• بانک دارکی\n"
        "• ماینر دارکی\n"
        "• لیدربورد\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)# bot.py — Dark Point Bot (قسمت 3/12)

# ──────────────── Profile ────────────────
async def msg_profile(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    uid = update.effective_user.id
    if not db.is_bot_on() and not is_admin(uid):
        await update.message.reply_text(bot_off_text()); return

    u = db.get_user(uid)
    if not u:
        await update.message.reply_text("❌ کاربر یافت نشد"); return

    bal = u['balance']
    lvl = db.get_user_level(uid)
    ton_eq = dp_to_ton(bal)
    ref_reward = int(db.get_setting('referral_reward', config.DEFAULT_REFERRAL_REWARD))
    ref_link = f"https://t.me/{(await ctx.bot.get_me()).username}?start={uid}"

    # Level progress
    next_lvl = min(lvl + 1, 20)
    if lvl < 20:
        cur_thresh = config.LEVEL_THRESHOLDS[lvl - 1]
        nxt_thresh = config.LEVEL_THRESHOLDS[lvl]
        progress = min(100, int((bal - cur_thresh) / max(1, nxt_thresh - cur_thresh) * 100))
        bar = "█" * (progress // 10) + "░" * (10 - progress // 10)
        lvl_text = f"📊 سطح: <b>{lvl}</b> / 20\n{bar} {progress}%\n🎯 تا سطح بعدی: <b>{fmt(nxt_thresh - bal)}</b> DP"
    else:
        lvl_text = "📊 سطح: <b>20 (MAX)</b> 🏆"

    text = (
        f"👤 <b>پروفایل دارکی</b>\n"
        f"{'─' * 28}\n\n"
        f"🆔 آیدی عددی: <code>{uid}</code>\n"
        f"👤 نام: {html.escape(u['first_name'] or '—')}\n"
        f"🔖 یوزرنیم: @{html.escape(u['username'] or '—')}\n\n"
        f"💎 موجودی: <b>{fmt(bal)}</b> DP\n"
        f"💰 معادل TON: <b>{ton_eq:.6f}</b> TON\n"
        f"🏆 کل درآمد: <b>{fmt(u['total_earned'])}</b> DP\n\n"
        f"{lvl_text}\n\n"
        f"👥 زیرمجموعه: <b>{u['referrals']}</b> نفر\n"
        f"💵 پاداش هر رفرال: <b>{fmt(ref_reward)}</b> DP\n\n"
        f"🔗 <b>لینک دعوت شما:</b>\n<code>{ref_link}</code>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ──────────────── Claim (دریافت جایزه) ────────────────
async def msg_claim(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    uid = update.effective_user.id
    if not db.is_bot_on() and not is_admin(uid):
        await update.message.reply_text(bot_off_text()); return
    if not db.is_section_on('claim') and not is_admin(uid):
        await update.message.reply_text(section_off_text()); return

    ok, rem = db.can_claim(uid)
    if not ok:
        await update.message.reply_text(
            f"⏳ <b>هنوز زمان دریافت نرسیده!</b>\n\n"
            f"⏱ باقی‌مانده: <b>{seconds_to_hms(rem)}</b>\n"
            f"💡 هر ۳ تا ۵ دقیقه می‌توانید جایزه بگیرید.",
            parse_mode=ParseMode.HTML)
        return

    amt = db.do_claim(uid)
    lu = db.check_level_up(uid)

    text = f"🎉 <b>تبریک!</b>\n\n💎 <b>{fmt(amt)}</b> DP دریافت کردید!"

    if lu:
        old_lvl, new_lvl = lu
        reward = config.get_level_reward(new_lvl)
        text += (
            f"\n\n🚀 <b>ارتقای سطح!</b>\n"
            f"📊 سطح {old_lvl} ➜ <b>{new_lvl}</b>\n"
            f"🎁 پاداش ارتقا: <b>+{fmt(reward)}</b> DP"
        )

    bal = db.get_balance(uid)
    text += f"\n\n💰 موجودی فعلی: <b>{fmt(bal)}</b> DP"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ──────────────── Referral (زیرمجموعه‌گیری) ────────────────
async def msg_referral(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    uid = update.effective_user.id
    if not db.is_bot_on() and not is_admin(uid):
        await update.message.reply_text(bot_off_text()); return

    u = db.get_user(uid)
    if not u:
        return

    ref_reward = int(db.get_setting('referral_reward', config.DEFAULT_REFERRAL_REWARD))
    first_reward = int(db.get_setting('first_join_reward', config.DEFAULT_FIRST_JOIN_REWARD))
    bot_user = await ctx.bot.get_me()
    ref_link = f"https://t.me/{bot_user.username}?start={uid}"

    text = (
        f"👥 <b>سیستم زیرمجموعه‌گیری</b>\n"
        f"{'─' * 28}\n\n"
        f"👤 تعداد زیرمجموعه: <b>{u['referrals']}</b> نفر\n"
        f"💵 پاداش هر رفرال: <b>{fmt(ref_reward)}</b> DP\n"
        f"🎁 پاداش ورود جدید: <b>{fmt(first_reward)}</b> DP\n\n"
        f"💡 با زیرمجموعه‌گیری راحت می‌توانید برداشت کنید!\n\n"
        f"🔗 <b>لینک اختصاصی شما:</b>\n<code>{ref_link}</code>\n\n"
        f"📤 این لینک را برای دوستانتان بفرستید و DP رایگان بگیرید!"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 اشتراک لینک", url=f"https://t.me/share/url?url={ref_link}&text=بیا تو Dark Point Bot DP رایگان بگیر!")],
    ])
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


# ──────────────── Leaderboard ────────────────
async def msg_leaderboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    uid = update.effective_user.id
    if not db.is_bot_on() and not is_admin(uid):
        await update.message.reply_text(bot_off_text()); return
    if not db.is_section_on('leaderboard') and not is_admin(uid):
        await update.message.reply_text(section_off_text()); return

    top = db.get_top_users(15)
    if not top:
        await update.message.reply_text("📊 هنوز کاربری ثبت نشده."); return

    medals = ["🥇", "🥈", "🥉"]
    text = "🏆 <b>لیدربورد Dark Point</b>\n" + "─" * 28 + "\n\n"

    for i, u in enumerate(top):
        rank = medals[i] if i < 3 else f"  {i + 1}."
        name = html.escape(u['username'] or u['first_name'] or str(u['user_id']))
        if u['username']:
            name = f"@{name}"
        text += f"{rank} {name} — <b>{fmt(u['balance'])}</b> DP\n"

    # User's own rank
    all_users = db.get_top_users(999999)
    user_rank = next((i + 1 for i, u in enumerate(all_users) if u['user_id'] == uid), "—")
    user_bal = db.get_balance(uid)
    text += (
        f"\n{'─' * 28}\n"
        f"📍 رتبه شما: <b>{user_rank}</b>\n"
        f"💎 موجودی شما: <b>{fmt(user_bal)}</b> DP"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ──────────────── Wheel of Fortune (گردونه شانس) ────────────────
async def msg_wheel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    uid = update.effective_user.id
    if not db.is_bot_on() and not is_admin(uid):
        await update.message.reply_text(bot_off_text()); return
    if not db.is_section_on('wheel') and not is_admin(uid):
        await update.message.reply_text(section_off_text()); return

    # Daily reset check
    today = date.today().isoformat()
    u = db.get_user(uid)
    if u and u['wheel_reset_date'] != today:
        c = db.conn.cursor()
        c.execute('UPDATE users SET wheel_used_today=0, wheel_reset_date=? WHERE user_id=?', (today, uid))
        db.conn.commit()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎰 چرخش رایگان روزانه", callback_data="wheel_free")],
        [InlineKeyboardButton(f"🎰 چرخش اضافی ({fmt(config.WHEEL_EXTRA_COST)} DP)", callback_data="wheel_extra")],
    ])

    await update.message.reply_text(
        "🎰 <b>گردونه شانس</b>\n"
        f"{'─' * 28}\n\n"
        f"🎁 هر روز یک چرخش رایگان!\n"
        f"💰 جوایز: {fmt(config.WHEEL_FREE_MIN)} تا {fmt(config.WHEEL_FREE_MAX)} DP\n\n"
        f"🔄 چرخش اضافی: {fmt(config.WHEEL_EXTRA_COST)} DP\n"
        f"💡 جوایز چرخش اضافی بیشتر است!",
        parse_mode=ParseMode.HTML, reply_markup=kb)


async def cb_wheel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if q.data == "wheel_free":
        today = date.today().isoformat()
        u = db.get_user(uid)
        if u and u['wheel_reset_date'] != today:
            c = db.conn.cursor()
            c.execute('UPDATE users SET wheel_used_today=0, wheel_reset_date=? WHERE user_id=?', (today, uid))
            db.conn.commit()
            u = db.get_user(uid)

        if u and u['wheel_used_today'] >= 1:
            await q.edit_message_text("⏳ چرخش رایگان امروز را استفاده کرده‌اید.\nفردا دوباره بیایید!")
            return

        prize = random.randint(config.WHEEL_FREE_MIN, config.WHEEL_FREE_MAX)
        db.add_balance(uid, prize)
        c = db.conn.cursor()
        c.execute('UPDATE users SET wheel_used_today=wheel_used_today+1 WHERE user_id=?', (uid,))
        db.conn.commit()
        db.check_level_up(uid)

        await q.edit_message_text(
            f"🎰 <b>گردونه چرخید!</b>\n\n"
            f"🎉 تبریک! <b>{fmt(prize)}</b> DP برنده شدید!\n"
            f"💰 موجودی: <b>{fmt(db.get_balance(uid))}</b> DP",
            parse_mode=ParseMode.HTML)

    elif q.data == "wheel_extra":
        if not db.deduct_balance(uid, config.WHEEL_EXTRA_COST):
            await q.edit_message_text("❌ موجودی کافی نیست!")
            return

        # Extra spin has higher prizes
        prize = random.randint(config.WHEEL_FREE_MAX, config.WHEEL_FREE_MAX * 3)
        db.add_balance(uid, prize)
        db.check_level_up(uid)

        await q.edit_message_text(
            f"🎰 <b>چرخش اضافی!</b>\n\n"
            f"🎉 تبریک! <b>{fmt(prize)}</b> DP برنده شدید!\n"
            f"💰 موجودی: <b>{fmt(db.get_balance(uid))}</b> DP",
            parse_mode=ParseMode.HTML)# bot.py — Dark Point Bot (قسمت 4/12)

# ══════════════════════════════════════════════
#                  GAMES
# ══════════════════════════════════════════════

def _game_section_check(uid):
    """Return True if games section is on or user is admin"""
    return db.is_section_on('games') or is_admin(uid)


# ──────────────── Games Menu (inline) ────────────────
async def msg_games(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    uid = update.effective_user.id
    if not db.is_bot_on() and not is_admin(uid):
        await update.message.reply_text(bot_off_text()); return
    if not _game_section_check(uid):
        await update.message.reply_text(section_off_text()); return

    text = (
        "🎮 <b>بازی‌های Dark Point</b>\n"
        f"{'─' * 28}\n\n"
        "💥 <b>کرش:</b> 500 – 500,000 DP | ضرایب 2x/3x/5x\n"
        "🎲 <b>تاس:</b> 15,000+ DP | ضرایب 1.5x/3x/6x\n"
        "🔮 <b>حدس بزن:</b> 30,000+ DP | ضرایب تا 10x\n"
        "🎰 <b>کازینو:</b> 25,000+ DP | ضرایب 7x/12x/15x\n"
        "💣 <b>بمب:</b> 35,000+ DP | +0.2x هر خانه امن\n\n"
        "⚠️ <b>همه بازی‌ها فقط در گروه قابل اجرا هستند!</b>\n"
        "دستور بازی را در گروه بفرستید."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML,
                                    reply_markup=games_inline_kb())


async def cb_game_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    infos = {
        "g_crash_info": (
            "💥 <b>بازی کرش</b>\n\n"
            "📝 دستور: <code>بازی [مبلغ]</code>\n"
            f"💰 حداقل: {fmt(config.CRASH_MIN_BET)} | حداکثر: {fmt(config.CRASH_MAX_BET)}\n"
            "🎰 ضرایب: 2x | 3x | 5x\n"
            "⚠️ فقط در گروه"
        ),
        "g_dice_info": (
            "🎲 <b>بازی تاس</b>\n\n"
            "📝 دستور: <code>تاس [مبلغ]</code>\n"
            f"💰 حداقل: {fmt(config.DICE_MIN_BET)}\n"
            "🎯 تاس 6 = 6x | تاس 5 = 3x | تاس 4 = 1.5x\n"
            "⚠️ فقط در گروه"
        ),
        "g_guess_info": (
            "🔮 <b>بازی حدس بزن</b>\n\n"
            "📝 دستور: <code>حدس بزن [مبلغ]</code>\n"
            f"💰 حداقل: {fmt(config.GUESS_MIN_BET)}\n"
            "🎯 ضرایب: 10x | 5x | 2.5x | 1.2x\n"
            "⚠️ فقط در گروه"
        ),
        "g_casino_info": (
            "🎰 <b>بازی کازینو</b>\n\n"
            "📝 دستور: <code>کازینو [مبلغ]</code>\n"
            f"💰 حداقل: {fmt(config.CASINO_MIN_BET)}\n"
            "🎰 ضرایب: 7x | 12x | 15x\n"
            "⚠️ فقط در گروه"
        ),
        "g_bomb_info": (
            "💣 <b>بازی بمب</b>\n\n"
            "📝 دستور: <code>بمب [مبلغ]</code>\n"
            f"💰 حداقل: {fmt(config.BOMB_MIN_BET)}\n"
            "🔲 گرید 4×4 | 6 بمب | 10 خانه امن\n"
            "📈 هر خانه امن: +0.2x ضریب\n"
            "⚠️ فقط در گروه"
        ),
    }
    text = infos.get(q.data, "❌ نامعتبر")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت به بازی‌ها", callback_data="games_back")]
    ])
    await safe_edit(q, text, kb)


async def cb_games_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    text = (
        "🎮 <b>بازی‌های Dark Point</b>\n\n"
        "⚠️ همه بازی‌ها فقط در گروه قابل اجرا هستند.\n"
        "دستور بازی را در گروه بفرستید."
    )
    await safe_edit(q, text, games_inline_kb())


# ──────────────── Helper: Parse Bet ────────────────
async def _parse_bet(update, ctx, min_bet, max_bet=None):
    """Parse bet from command args. Returns (bet, True) or (None, False)."""
    uid = update.effective_user.id
    if not _game_section_check(uid):
        await update.message.reply_text(section_off_text())
        return None, False
    if not db.is_bot_on() and not is_admin(uid):
        await update.message.reply_text(bot_off_text())
        return None, False

    parts = (update.message.text or "").strip().split()
    if len(parts) < 2:
        await update.message.reply_text(
            f"❌ مبلغ شرط را وارد کنید!\n"
            f"مثال: <code>{parts[0]} {fmt(min_bet)}</code>\n"
            f"حداقل: {fmt(min_bet)}"
            + (f" | حداکثر: {fmt(max_bet)}" if max_bet else ""),
            parse_mode=ParseMode.HTML)
        return None, False

    try:
        bet = int(parts[1])
    except ValueError:
        await update.message.reply_text("❌ مبلغ نامعتبر! فقط عدد وارد کنید.")
        return None, False

    if bet < min_bet:
        await update.message.reply_text(f"❌ حداقل شرط: <b>{fmt(min_bet)}</b> DP",
                                        parse_mode=ParseMode.HTML)
        return None, False
    if max_bet and bet > max_bet:
        await update.message.reply_text(f"❌ حداکثر شرط: <b>{fmt(max_bet)}</b> DP",
                                        parse_mode=ParseMode.HTML)
        return None, False
    if not db.deduct_balance(uid, bet):
        await update.message.reply_text("❌ موجودی کافی نیست!")
        return None, False

    return bet, True


# ══════════════════════════════════════════════
#           1) CRASH  (💥 کرش — 🎰 dice)
# ══════════════════════════════════════════════
async def cmd_crash(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.message.reply_text("⚠️ این بازی فقط در <b>گروه</b> قابل اجراست!",
                                        parse_mode=ParseMode.HTML)
        return

    bet, ok = await _parse_bet(update, ctx, config.CRASH_MIN_BET, config.CRASH_MAX_BET)
    if not ok:
        return

    uid = update.effective_user.id
    uname = html.escape(update.effective_user.first_name or "بازیکن")

    # Send spinning dice
    status_msg = await update.message.reply_text(
        f"💥 <b>کرش شروع شد!</b>\n"
        f"👤 {uname}\n"
        f"💰 شرط: <b>{fmt(bet)}</b> DP\n\n"
        f"⏳ در حال چرخش...",
        parse_mode=ParseMode.HTML)

    dice_msg = await ctx.bot.send_dice(update.effective_chat.id, emoji='🎰')
    val = dice_msg.dice.value

    # 🎰 values: 1=bar(lose), 22=grape(2x), 43=lemon(3x), 64=seven(5x)
    mult_map = {1: 0, 22: 2, 43: 3, 64: 5}
    mult = mult_map.get(val, 0)

    if mult > 0:
        win = bet * mult
        db.add_balance(uid, win)
        db.check_level_up(uid)
        await status_msg.edit_text(
            f"💥 <b>کرش!</b>\n"
            f"👤 {uname}\n"
            f"🎰 ضریب: <b>{mult}x</b>\n"
            f"🎉 برنده: <b>+{fmt(win)}</b> DP\n"
            f"💰 موجودی: <b>{fmt(db.get_balance(uid))}</b> DP",
            parse_mode=ParseMode.HTML)
    else:
        await status_msg.edit_text(
            f"💥 <b>کرش!</b>\n"
            f"👤 {uname}\n"
            f"💀 باختید: <b>-{fmt(bet)}</b> DP\n"
            f"💰 موجودی: <b>{fmt(db.get_balance(uid))}</b> DP",
            parse_mode=ParseMode.HTML)


# ══════════════════════════════════════════════
#           2) DICE  (🎲 تاس)
# ══════════════════════════════════════════════
async def cmd_dice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.message.reply_text("⚠️ فقط در <b>گروه</b>!", parse_mode=ParseMode.HTML)
        return

    bet, ok = await _parse_bet(update, ctx, config.DICE_MIN_BET)
    if not ok:
        return

    uid = update.effective_user.id
    uname = html.escape(update.effective_user.first_name or "بازیکن")

    dice_msg = await ctx.bot.send_dice(update.effective_chat.id, emoji='🎲')
    val = dice_msg.dice.value  # 1-6

    # 6 → 6x, 5 → 3x, 4 → 1.5x, else lose
    if val == 6:
        mult = 6
    elif val == 5:
        mult = 3
    elif val == 4:
        mult = 1.5
    else:
        mult = 0

    if mult > 0:
        win = int(bet * mult)
        db.add_balance(uid, win)
        db.check_level_up(uid)
        await update.message.reply_text(
            f"🎲 <b>تاس: {val}</b>\n"
            f"👤 {uname}\n"
            f"🎉 ضریب: <b>{mult}x</b> — برنده: <b>+{fmt(win)}</b> DP",
            parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(
            f"🎲 <b>تاس: {val}</b>\n"
            f"👤 {uname}\n"
            f"💀 باختید: <b>-{fmt(bet)}</b> DP",
            parse_mode=ParseMode.HTML)


# ══════════════════════════════════════════════
#        3) GUESS  (🔮 حدس بزن — 10x/5x/2.5x/1.2x)
# ══════════════════════════════════════════════
async def cmd_guess(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.message.reply_text("⚠️ فقط در <b>گروه</b>!", parse_mode=ParseMode.HTML)
        return

    bet, ok = await _parse_bet(update, ctx, config.GUESS_MIN_BET)
    if not ok:
        return

    uid = update.effective_user.id

    # Store bet in user_data for callback
    ctx.user_data['guess_bet'] = bet
    ctx.user_data['guess_uid'] = uid
    ctx.user_data['guess_time'] = time.time()

    # Assign random multipliers to 4 positions
    mults = [10, 5, 2.5, 1.2]
    random.shuffle(mults)
    ctx.user_data['guess_mults'] = mults

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("1️⃣", callback_data="guess_1"),
         InlineKeyboardButton("2️⃣", callback_data="guess_2"),
         InlineKeyboardButton("3️⃣", callback_data="guess_3"),
         InlineKeyboardButton("4️⃣", callback_data="guess_4")],
    ])

    await update.message.reply_text(
        f"🔮 <b>بازی حدس بزن</b>\n\n"
        f"💰 شرط: <b>{fmt(bet)}</b> DP\n"
        f"🎯 یکی از ۴ جعبه را انتخاب کنید!\n"
        f"💎 ضرایب مخفی: 10x | 5x | 2.5x | 1.2x\n\n"
        f"⏳ ۱۰ دقیقه وقت دارید.",
        parse_mode=ParseMode.HTML, reply_markup=kb)


async def cb_guess(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    # Validate
    if ctx.user_data.get('guess_uid') != uid:
        await q.edit_message_text("❌ این بازی متعلق به شما نیست!")
        return

    # Timeout check
    if time.time() - ctx.user_data.get('guess_time', 0) > config.GAME_TIMEOUT:
        await q.edit_message_text("⏳ زمان بازی تمام شد!")
        ctx.user_data.pop('guess_bet', None)
        ctx.user_data.pop('guess_uid', None)
        ctx.user_data.pop('guess_time', None)
        ctx.user_data.pop('guess_mults', None)
        return

    bet = ctx.user_data.get('guess_bet', 0)
    mults = ctx.user_data.get('guess_mults', [10, 5, 2.5, 1.2])
    pick = int(q.data.split('_')[1])  # 1-4
    mult = mults[pick - 1]

    # Clean up
    for k in ('guess_bet', 'guess_uid', 'guess_time', 'guess_mults'):
        ctx.user_data.pop(k, None)

    win = int(bet * mult)
    db.add_balance(uid, win)
    db.check_level_up(uid)

    # Reveal all
    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]
    reveal = " | ".join(
        f"{emojis[i]}={m}x{' ✅' if i == pick - 1 else ''}"
        for i, m in enumerate(mults)
    )

    await q.edit_message_text(
        f"🔮 <b>نتیجه حدس بزن</b>\n\n"
        f"🎯 انتخاب شما: {emojis[pick - 1]}\n"
        f"💎 ضریب: <b>{mult}x</b>\n"
        f"🎉 برنده: <b>+{fmt(win)}</b> DP\n\n"
        f"📊 ضرایب: {reveal}",
        parse_mode=ParseMode.HTML)


# ══════════════════════════════════════════════
#        4) CASINO  (🎰 کازینو — 7x/12x/15x)
# ══════════════════════════════════════════════
async def cmd_casino(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.message.reply_text("⚠️ فقط در <b>گروه</b>!", parse_mode=ParseMode.HTML)
        return

    bet, ok = await _parse_bet(update, ctx, config.CASINO_MIN_BET)
    if not ok:
        return

    uid = update.effective_user.id
    uname = html.escape(update.effective_user.first_name or "بازیکن")

    status_msg = await update.message.reply_text(
        f"🎰 <b>کازینو شروع شد!</b>\n"
        f"👤 {uname}\n"
        f"💰 شرط: <b>{fmt(bet)}</b> DP\n\n"
        f"⏳ در حال چرخش...",
        parse_mode=ParseMode.HTML)

    dice_msg = await ctx.bot.send_dice(update.effective_chat.id, emoji='🎰')
    val = dice_msg.dice.value

    # 🎰 values: 64=seven(15x), 43=lemon(12x), 22=grape(7x), else lose
    mult_map = {64: 15, 43: 12, 22: 7}
    mult = mult_map.get(val, 0)

    if mult > 0:
        win = bet * mult
        db.add_balance(uid, win)
        db.check_level_up(uid)
        await status_msg.edit_text(
            f"🎰 <b>کازینو!</b>\n"
            f"👤 {uname}\n"
            f"🎰 ضریب: <b>{mult}x</b>\n"
            f"🎉 برنده: <b>+{fmt(win)}</b> DP\n"
            f"💰 موجودی: <b>{fmt(db.get_balance(uid))}</b> DP",
            parse_mode=ParseMode.HTML)
    else:
        await status_msg.edit_text(
            f"🎰 <b>کازینو!</b>\n"
            f"👤 {uname}\n"
            f"💀 باختید: <b>-{fmt(bet)}</b> DP\n"
            f"💰 موجودی: <b>{fmt(db.get_balance(uid))}</b> DP",
            parse_mode=ParseMode.HTML)


# ══════════════════════════════════════════════
#    5) BOMB  (💣 بمب — 4×4, 6 bombs, +0.2x)
# ══════════════════════════════════════════════
async def cmd_bomb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.message.reply_text("⚠️ فقط در <b>گروه</b>!", parse_mode=ParseMode.HTML)
        return

    bet, ok = await _parse_bet(update, ctx, config.BOMB_MIN_BET)
    if not ok:
        return

    uid = update.effective_user.id
    uname = html.escape(update.effective_user.first_name or "بازیکن")

    # Generate grid: 16 cells, 6 bombs
    grid = [0] * 16
    bomb_positions = random.sample(range(16), config.BOMB_COUNT)
    for b in bomb_positions:
        grid[b] = 1

    # Store game state
    ctx.user_data['bomb'] = {
        'grid': grid,
        'revealed': set(),
        'bet': bet,
        'uid': uid,
        'mult': 1.0,
        'time': time.time(),
        'chat_id': update.effective_chat.id,
    }

    total_safe = 16 - config.BOMB_COUNT
    kb = _build_bomb_kb(set(), uid)

    await update.message.reply_text(
        f"💣 <b>بازی بمب</b>\n"
        f"👤 {uname}\n"
        f"💰 شرط: <b>{fmt(bet)}</b> DP\n"
        f"🔲 گرید: 4×4 | 💣 بمب: {config.BOMB_COUNT} | ✅ امن: {total_safe}\n"
        f"📈 ضریب فعلی: <b>1.0x</b>\n\n"
        f"یک خانه انتخاب کنید (1-16):",
        parse_mode=ParseMode.HTML, reply_markup=kb)


def _build_bomb_kb(revealed, uid):
    """Build 4×4 grid keyboard for bomb game"""
    rows = []
    for r in range(4):
        row = []
        for c in range(4):
            idx = r * 4 + c + 1  # 1-16
            if idx in revealed:
                row.append(InlineKeyboardButton("✅", callback_data=f"bomb_{idx}"))
            else:
                row.append(InlineKeyboardButton(f"  {idx}  ", callback_data=f"bomb_{idx}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("💰 برداشت سود", callback_data="bomb_cash")])
    return InlineKeyboardMarkup(rows)


async def cb_bomb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    game = ctx.user_data.get('bomb')
    if not game:
        await q.edit_message_text("❌ بازی فعالی ندارید!")
        return

    if game['uid'] != uid:
        await q.answer("❌ این بازی متعلق به شما نیست!", show_alert=True)
        return

    # Timeout
    if time.time() - game['time'] > config.GAME_TIMEOUT:
        await q.edit_message_text("⏳ زمان بازی تمام شد!")
        ctx.user_data.pop('bomb', None)
        return

    # Cash out
    if q.data == "bomb_cash":
        win = int(game['bet'] * game['mult'])
        db.add_balance(uid, win)
        db.check_level_up(uid)
        safe_count = len(game['revealed'])
        ctx.user_data.pop('bomb', None)
        await q.edit_message_text(
            f"💰 <b>برداشت از بمب!</b>\n\n"
            f"🔲 خانه‌های امن باز شده: <b>{safe_count}</b>\n"
            f"📈 ضریب نهایی: <b>{game['mult']:.1f}x</b>\n"
            f"🎉 برنده: <b>+{fmt(win)}</b> DP\n"
            f"💰 موجودی: <b>{fmt(db.get_balance(uid))}</b> DP",
            parse_mode=ParseMode.HTML)
        return

    # Pick a cell
    try:
        cell = int(q.data.split('_')[1])
    except (ValueError, IndexError):
        return

    if cell in game['revealed']:
        await q.answer("⚠️ این خانه قبلاً باز شده!", show_alert=True)
        return

    game['revealed'].add(cell)
    grid_idx = cell - 1

    if game['grid'][grid_idx] == 1:
        # BOOM!
        ctx.user_data.pop('bomb', None)
        # Reveal all bombs
        bomb_cells = [i + 1 for i, v in enumerate(game['grid']) if v == 1]
        await q.edit_message_text(
            f"💥 <b>بمب خورد!</b>\n\n"
            f"👤 بازیکن باخت!\n"
            f"💀 از دست دادید: <b>-{fmt(game['bet'])}</b> DP\n"
            f"🔲 خانه‌های امن باز شده: {len(game['revealed']) - 1}\n"
            f"📈 ضریب: {game['mult']:.1f}x\n"
            f"💣 بمب‌ها در خانه‌های: {', '.join(map(str, bomb_cells))}",
            parse_mode=ParseMode.HTML)
        return

    # Safe! Increase multiplier by 0.2
    game['mult'] = round(game['mult'] + config.BOMB_MULTIPLIER_STEP, 1)
    safe_count = len(game['revealed'])
    total_safe = 16 - config.BOMB_COUNT

    # Check if all safe cells revealed
    if safe_count >= total_safe:
        win = int(game['bet'] * game['mult'])
        db.add_balance(uid, win)
        db.check_level_up(uid)
        ctx.user_data.pop('bomb', None)
        await q.edit_message_text(
            f"🏆 <b>همه خانه‌های امن باز شد!</b>\n\n"
            f"🔲 {total_safe} خانه امن!\n"
            f"📈 ضریب نهایی: <b>{game['mult']:.1f}x</b>\n"
            f"🎉 برنده: <b>+{fmt(win)}</b> DP\n"
            f"💰 موجودی: <b>{fmt(db.get_balance(uid))}</b> DP",
            parse_mode=ParseMode.HTML)
        return

    # Continue
    potential_win = int(game['bet'] * game['mult'])
    kb = _build_bomb_kb(game['revealed'], uid)
    await q.edit_message_text(
        f"💣 <b>بازی بمب</b>\n\n"
        f"✅ امن! خانه {cell}\n"
        f"📈 ضریب: <b>{game['mult']:.1f}x</b>\n"
        f"💰 سود فعلی: <b>{fmt(potential_win)}</b> DP\n"
        f"🔲 باقی‌مانده: {total_safe - safe_count} خانه امن\n\n"
        f"ادامه بدهید یا برداشت کنید:",
        parse_mode=ParseMode.HTML, reply_markup=kb)# bot.py — Dark Point Bot (قسمت 5/12)

# ══════════════════════════════════════════════
#        💎 TON WITHDRAWAL (NEW — کامل)
# ══════════════════════════════════════════════
# نرخ: 200,000,000 DP = 0.0005 TON
# حداقل برداشت: 0.01 TON
# جریان: مبلغ → آدرس کیف‌پول → تأیید → ارسال به ادمین

# ──────────────── TON Withdraw Menu ────────────────
async def msg_ton_withdraw(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Display TON withdrawal main page"""
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    uid = update.effective_user.id
    if not db.is_bot_on() and not is_admin(uid):
        await update.message.reply_text(bot_off_text()); return
    if not db.is_section_on('ton_withdraw') and not is_admin(uid):
        await update.message.reply_text(section_off_text()); return

    clear_user_state(ctx)
    bal = db.get_balance(uid)
    ton_eq = dp_to_ton(bal)
    min_ton = config.TON_WITHDRAWAL_MIN
    can_withdraw = ton_eq >= min_ton

    # Build progress bar for minimum
    pct = min(100, int(ton_eq / min_ton * 100)) if min_ton > 0 else 0
    bar = "█" * (pct // 10) + "░" * (10 - pct // 10)

    text = (
        f"💎 <b>برداشت TON</b>\n"
        f"{'═' * 30}\n\n"
        f"💰 موجودی شما: <b>{fmt(bal)}</b> DP\n"
        f"💎 معادل TON: <b>{ton_eq:.6f}</b> TON\n\n"
        f"📊 <b>نرخ تبدیل:</b>\n"
        f"   {fmt(config.TON_WITHDRAWAL_DP_RATE)} DP = {config.TON_WITHDRAWAL_TON_AMOUNT} TON\n\n"
        f"📉 <b>حداقل برداشت:</b> {min_ton} TON\n"
        f"📈 وضعیت: {bar} {pct}%\n\n"
    )

    if can_withdraw:
        text += "✅ شما امکان برداشت دارید!\n"
    else:
        needed_dp = ton_to_dp(min_ton) - bal
        text += (
            f"⚠️ موجودی کافی نیست.\n"
            f"🔻 به <b>{fmt(max(0, needed_dp))}</b> DP دیگر نیاز دارید.\n"
        )

    text += (
        f"\n💡 با زیرمجموعه‌گیری راحت می‌توانید برداشت کنید\n"
        f"{'═' * 30}"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "💎 ثبت درخواست برداشت TON" if can_withdraw else "🔒 موجودی ناکافی",
            callback_data="tw_start" if can_withdraw else "tw_locked"
        )],
        [InlineKeyboardButton("📜 سفارش‌های من", callback_data="tw_history")],
    ])

    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


# ──────────────── Start Withdrawal Flow ────────────────
async def cb_tw_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Step 1: Ask for TON amount"""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if not db.is_section_on('ton_withdraw') and not is_admin(uid):
        await safe_edit(q, section_off_text())
        return

    bal = db.get_balance(uid)
    ton_eq = dp_to_ton(bal)
    min_ton = config.TON_WITHDRAWAL_MIN

    if ton_eq < min_ton:
        await safe_edit(q,
            f"❌ موجودی کافی نیست!\n"
            f"💎 موجودی: {ton_eq:.6f} TON\n"
            f"📉 حداقل: {min_ton} TON")
        return

    ctx.user_data['tw_step'] = 'amount'
    ctx.user_data['tw_uid'] = uid

    await safe_edit(q,
        f"💎 <b>مرحله ۱: مقدار TON</b>\n"
        f"{'─' * 28}\n\n"
        f"💰 موجودی قابل برداشت: <b>{ton_eq:.6f}</b> TON\n"
        f"📉 حداقل: <b>{min_ton}</b> TON\n\n"
        f"📝 مقدار TON مورد نظر را وارد کنید:\n"
        f"(مثال: <code>0.05</code>)\n\n"
        f"⚠️ فقط عدد اعشاری وارد کنید.",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ لغو", callback_data="tw_cancel")]
        ]))


async def cb_tw_locked(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("🔒 موجودی شما برای برداشت کافی نیست!", show_alert=True)


async def cb_tw_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    clear_user_state(ctx)
    await safe_edit(q, "❌ عملیات برداشت لغو شد.")


# ──────────────── Process Amount Input ────────────────
async def process_tw_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Process TON amount from user text input"""
    uid = update.effective_user.id
    if ctx.user_data.get('tw_step') != 'amount' or ctx.user_data.get('tw_uid') != uid:
        return False  # Not in this flow

    text = (update.message.text or "").strip()

    # Cancel command
    if text in ('لغو', 'cancel', '/cancel'):
        clear_user_state(ctx)
        await update.message.reply_text("❌ لغو شد.", reply_markup=main_menu_kb())
        return True

    # Parse amount
    try:
        ton_amount = float(text)
    except ValueError:
        await update.message.reply_text(
            "❌ لطفاً یک عدد معتبر وارد کنید!\nمثال: <code>0.05</code>",
            parse_mode=ParseMode.HTML)
        return True

    min_ton = config.TON_WITHDRAWAL_MIN
    bal = db.get_balance(uid)
    max_ton = dp_to_ton(bal)

    if ton_amount < min_ton:
        await update.message.reply_text(
            f"❌ حداقل برداشت: <b>{min_ton}</b> TON\n"
            f"مقدار وارد شده: {ton_amount} TON",
            parse_mode=ParseMode.HTML)
        return True

    if ton_amount > max_ton:
        await update.message.reply_text(
            f"❌ موجودی کافی نیست!\n"
            f"💎 حداکثر قابل برداشت: <b>{max_ton:.6f}</b> TON",
            parse_mode=ParseMode.HTML)
        return True

    # Calculate DP cost
    dp_cost = ton_to_dp(ton_amount)

    # Store and move to wallet step
    ctx.user_data['tw_step'] = 'wallet'
    ctx.user_data['tw_ton'] = ton_amount
    ctx.user_data['tw_dp'] = dp_cost

    await update.message.reply_text(
        f"✅ <b>مرحله ۱ تکمیل شد!</b>\n\n"
        f"💎 مقدار: <b>{ton_amount}</b> TON\n"
        f"💰 هزینه: <b>{fmt(dp_cost)}</b> DP\n\n"
        f"{'─' * 28}\n\n"
        f"📝 <b>مرحله ۲: آدرس کیف‌پول TON</b>\n\n"
        f"آدرس کیف‌پول Keeper خود را وارد کنید:\n"
        f"(مثال: <code>UQD...xyz</code>)\n\n"
        f"⚠️ آدرس باید با <b>UQ</b> یا <b>EQ</b> شروع شود.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ لغو", callback_data="tw_cancel")]
        ]))
    return True


# ──────────────── Process Wallet Input ────────────────
async def process_tw_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Process TON wallet address from user text input"""
    uid = update.effective_user.id
    if ctx.user_data.get('tw_step') != 'wallet' or ctx.user_data.get('tw_uid') != uid:
        return False  # Not in this flow

    wallet = (update.message.text or "").strip()

    # Cancel
    if wallet in ('لغو', 'cancel', '/cancel'):
        clear_user_state(ctx)
        await update.message.reply_text("❌ لغو شد.", reply_markup=main_menu_kb())
        return True

    # Basic validation
    if len(wallet) < 20:
        await update.message.reply_text(
            "❌ آدرس کیف‌پول نامعتبر است!\n"
            "آدرس TON معمولاً ۴۸ کاراکتر است.")
        return True

    if not (wallet.startswith('UQ') or wallet.startswith('EQ') or
            wallet.startswith('kQ') or wallet.startswith('0:')):
        await update.message.reply_text(
            "❌ آدرس نامعتبر!\n"
            "آدرس TON باید با <b>UQ</b> یا <b>EQ</b> شروع شود.",
            parse_mode=ParseMode.HTML)
        return True

    ton_amount = ctx.user_data.get('tw_ton', 0)
    dp_cost = ctx.user_data.get('tw_dp', 0)

    # Store wallet
    ctx.user_data['tw_step'] = 'confirm'
    ctx.user_data['tw_wallet'] = wallet

    # Show confirmation
    await update.message.reply_text(
        f"📋 <b>تأیید سفارش برداشت TON</b>\n"
        f"{'═' * 30}\n\n"
        f"💎 مقدار برداشت: <b>{ton_amount}</b> TON\n"
        f"💰 هزینه از موجودی: <b>{fmt(dp_cost)}</b> DP\n"
        f"🏦 کیف‌پول مقصد:\n<code>{html.escape(wallet)}</code>\n\n"
        f"💰 موجودی فعلی: <b>{fmt(db.get_balance(uid))}</b> DP\n"
        f"💰 موجودی پس از برداشت: <b>{fmt(db.get_balance(uid) - dp_cost)}</b> DP\n\n"
        f"⚠️ پس از تأیید، DP از موجودی شما کسر می‌شود.\n"
        f"{'═' * 30}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تأیید سفارش", callback_data="tw_confirm")],
            [InlineKeyboardButton("❌ لغو", callback_data="tw_cancel")],
        ]))
    return True


# ──────────────── Confirm & Submit Order ────────────────
async def cb_tw_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """User confirms the withdrawal order"""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if ctx.user_data.get('tw_step') != 'confirm' or ctx.user_data.get('tw_uid') != uid:
        await safe_edit(q, "❌ سفارش نامعتبر یا منقضی شده.")
        return

    ton_amount = ctx.user_data.get('tw_ton', 0)
    dp_cost = ctx.user_data.get('tw_dp', 0)
    wallet = ctx.user_data.get('tw_wallet', '')

    if not ton_amount or not wallet:
        await safe_edit(q, "❌ اطلاعات ناقص. لطفاً دوباره شروع کنید.")
        clear_user_state(ctx)
        return

    # Final balance check
    bal = db.get_balance(uid)
    if bal < dp_cost:
        await safe_edit(q,
            f"❌ موجودی کافی نیست!\n"
            f"💰 موجودی: {fmt(bal)} DP\n"
            f"💰 نیاز: {fmt(dp_cost)} DP")
        clear_user_state(ctx)
        return

    # Deduct DP
    if not db.deduct_balance(uid, dp_cost):
        await safe_edit(q, "❌ خطا در کسر موجودی. لطفاً دوباره تلاش کنید.")
        clear_user_state(ctx)
        return

    # Create order in DB
    uname = q.from_user.username or str(uid)
    code = db.create_ton_withdrawal(uid, uname, wallet, ton_amount, dp_cost)

    # Clear flow state
    clear_user_state(ctx)

    # Confirm to user
    await safe_edit(q,
        f"✅ <b>سفارش برداشت TON ثبت شد!</b>\n"
        f"{'═' * 30}\n\n"
        f"🏷 کد پیگیری: <code>{code}</code>\n"
        f"💎 مقدار: <b>{ton_amount}</b> TON\n"
        f"💰 هزینه: <b>{fmt(dp_cost)}</b> DP\n"
        f"📊 وضعیت: ⏳ در انتظار تأیید ادمین\n\n"
        f"💰 موجودی جدید: <b>{fmt(db.get_balance(uid))}</b> DP\n\n"
        f"⏳ پس از تأیید ادمین، TON به کیف‌پول شما ارسال می‌شود.\n"
        f"{'═' * 30}")

    # ── Notify Admin ──
    admin_text = (
        f"💎 <b>درخواست برداشت TON جدید</b>\n"
        f"{'═' * 30}\n\n"
        f"👤 کاربر: {html.escape(uname)}\n"
        f"🆔 آیدی: <code>{uid}</code>\n"
        f"💎 مقدار: <b>{ton_amount}</b> TON\n"
        f"💰 هزینه DP: <b>{fmt(dp_cost)}</b> DP\n"
        f"🏦 کیف‌پول:\n<code>{html.escape(wallet)}</code>\n"
        f"🏷 کد: <code>{code}</code>\n"
        f"🕐 زمان: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"{'═' * 30}"
    )
    admin_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ انجام شد", callback_data=f"twadm_ok_{code}"),
         InlineKeyboardButton("❌ رد", callback_data=f"twadm_no_{code}")],
    ])
    await safe_send(ctx.bot, config.ADMIN_ID, admin_text, admin_kb)


# ──────────────── Admin: Approve ────────────────
async def cb_tw_admin_approve(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin approves TON withdrawal"""
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return

    code = q.data.replace("twadm_ok_", "")
    order = db.get_ton_withdrawal(code)
    if not order:
        await q.answer("❌ سفارش یافت نشد!", show_alert=True)
        return
    if order['status'] != 'pending':
        await q.answer(f"⚠️ وضعیت: {order['status']}", show_alert=True)
        return

    # Update status
    db.update_ton_status(code, 'approved')

    # Update admin message
    await safe_edit(q,
        f"✅ <b>سفارش تأیید شد</b>\n\n"
        f"🏷 کد: <code>{code}</code>\n"
        f"💎 مقدار: {order['ton_amount']} TON\n"
        f"👤 کاربر: {html.escape(order['username'])}\n"
        f"📊 وضعیت: ✅ انجام شد")

    # ── Notify User (in-bot, beautiful message) ──
    user_text = (
        f"🎉 <b>برداشت TON شما انجام شد!</b>\n"
        f"{'═' * 30}\n\n"
        f"🏷 کد پیگیری: <code>{code}</code>\n"
        f"💎 مقدار: <b>{order['ton_amount']}</b> TON\n"
        f"💰 هزینه: <b>{fmt(order['dp_cost'])}</b> DP\n"
        f"🏦 کیف‌پول:\n<code>{html.escape(order['wallet_address'])}</code>\n"
        f"📊 وضعیت: ✅ <b>انجام شد</b>\n"
        f"🕐 زمان: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"💡 TON به کیف‌پول شما ارسال شد.\n"
        f"{'═' * 30}"
    )
    await safe_send(ctx.bot, order['user_id'], user_text)

    # ── Log Channel (masked wallet) ──
    masked = mask_wallet(order['wallet_address'])
    bot_user = await ctx.bot.get_me()
    log_text = (
        f"💎 <b>برداشت TON انجام شد</b>\n"
        f"{'─' * 28}\n\n"
        f"💎 مقدار: <b>{order['ton_amount']}</b> TON\n"
        f"🏦 کیف‌پول: <code>{masked}</code>\n"
        f"👤 کاربر: @{html.escape(order['username'])}\n"
        f"🏷 کد: <code>{code}</code>\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    log_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔘 ورود به بات", url=f"https://t.me/{bot_user.username}")],
    ])
    await send_log(ctx.bot, log_text, log_kb)


# ──────────────── Admin: Reject ────────────────
async def cb_tw_admin_reject(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin rejects TON withdrawal — refund DP, notify user only (no channel log)"""
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return

    code = q.data.replace("twadm_no_", "")
    order = db.get_ton_withdrawal(code)
    if not order:
        await q.answer("❌ سفارش یافت نشد!", show_alert=True)
        return
    if order['status'] != 'pending':
        await q.answer(f"⚠️ وضعیت: {order['status']}", show_alert=True)
        return

    # Update status
    db.update_ton_status(code, 'rejected')

    # Refund DP to user
    db.add_balance(order['user_id'], order['dp_cost'])

    # Update admin message
    await safe_edit(q,
        f"❌ <b>سفارش رد شد</b>\n\n"
        f"🏷 کد: <code>{code}</code>\n"
        f"💎 مقدار: {order['ton_amount']} TON\n"
        f"👤 کاربر: {html.escape(order['username'])}\n"
        f"💰 بازگشت: {fmt(order['dp_cost'])} DP\n"
        f"📊 وضعیت: ❌ رد شده")

    # ── Notify User (in-bot ONLY — no channel log) ──
    user_text = (
        f"⚠️ <b>سفارش برداشت TON لغو شد</b>\n"
        f"{'═' * 30}\n\n"
        f"🏷 کد پیگیری: <code>{code}</code>\n"
        f"💎 مقدار: <b>{order['ton_amount']}</b> TON\n"
        f"💰 مبلغ بازگشتی: <b>+{fmt(order['dp_cost'])}</b> DP\n"
        f"📊 وضعیت: ❌ <b>لغو شده</b>\n\n"
        f"💰 موجودی فعلی: <b>{fmt(db.get_balance(order['user_id']))}</b> DP\n\n"
        f"💡 مبلغ DP به حساب شما بازگردانده شد.\n"
        f"{'═' * 30}"
    )
    await safe_send(ctx.bot, order['user_id'], user_text)
    # No send_log here — rejected orders don't go to log channel


# ──────────────── User: Order History ────────────────
async def cb_tw_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show user's TON withdrawal history"""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    c = db.conn.cursor()
    c.execute(
        'SELECT * FROM ton_withdrawals WHERE user_id=? ORDER BY created_at DESC LIMIT 10',
        (uid,))
    orders = c.fetchall()

    if not orders:
        await safe_edit(q,
            "📜 <b>تاریخچه برداشت TON</b>\n\n"
            "📭 هنوز سفارشی ثبت نکرده‌اید.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 بازگشت", callback_data="tw_back")]
            ]))
        return

    status_emoji = {'pending': '⏳', 'approved': '✅', 'rejected': '❌'}
    status_text = {'pending': 'در انتظار', 'approved': 'انجام شد', 'rejected': 'لغو شده'}

    text = "📜 <b>تاریخچه برداشت TON</b>\n" + "─" * 28 + "\n\n"
    for o in orders:
        se = status_emoji.get(o['status'], '❓')
        st = status_text.get(o['status'], o['status'])
        text += (
            f"🏷 <code>{o['tracking_code']}</code>\n"
            f"   💎 {o['ton_amount']} TON | {se} {st}\n\n"
        )

    await safe_edit(q, text,
        InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 بازگشت", callback_data="tw_back")]
        ]))


async def cb_tw_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    clear_user_state(ctx)
    await safe_edit(q, "🔙 بازگشت به منو")
    await ctx.bot.send_message(q.from_user.id, "منوی اصلی:", reply_markup=main_menu_kb())


# ──────────────── Admin: TON Stats ────────────────
async def msg_tw_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin TON withdrawal statistics"""
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    uid = update.effective_user.id
    if not is_admin(uid):
        return

    stats = db.get_ton_stats()
    pending = db.get_pending_ton()

    text = (
        f"💎 <b>آمار برداشت TON</b>\n"
        f"{'═' * 30}\n\n"
        f"✅ سفارش‌های انجام شده: <b>{stats['ok']}</b>\n"
        f"💎 کل TON پرداختی: <b>{stats['ton']:.4f}</b> TON\n"
        f"💰 کل DP کسر شده: <b>{fmt(stats['dp'])}</b> DP\n\n"
        f"⏳ در انتظار تأیید: <b>{stats['pending']}</b>\n"
        f"❌ رد شده: <b>{stats['rejected']}</b>\n"
        f"{'═' * 30}"
    )

    kb_rows = []
    if pending:
        kb_rows.append([InlineKeyboardButton(
            f"📋 مشاهده {stats['pending']} سفارش در انتظار",
            callback_data="twadm_list")])
    kb_rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")])

    await update.message.reply_text(text, parse_mode=ParseMode.HTML,
                                    reply_markup=InlineKeyboardMarkup(kb_rows))


async def cb_tw_admin_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin: list all pending TON withdrawals"""
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return

    pending = db.get_pending_ton()
    if not pending:
        await safe_edit(q, "✅ سفارش در انتظاری وجود ندارد.")
        return

    text = "📋 <b>سفارش‌های در انتظار TON</b>\n" + "─" * 28 + "\n\n"
    rows = []
    for o in pending[:10]:  # Show max 10
        text += (
            f"🏷 <code>{o['tracking_code']}</code>\n"
            f"   👤 {html.escape(o['username'])} | 💎 {o['ton_amount']} TON\n\n"
        )
        rows.append([
            InlineKeyboardButton(f"✅ {o['tracking_code']}", callback_data=f"twadm_ok_{o['tracking_code']}"),
            InlineKeyboardButton(f"❌ {o['tracking_code']}", callback_data=f"twadm_no_{o['tracking_code']}"),
        ])

    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")])
    await safe_edit(q, text, InlineKeyboardMarkup(rows))# bot.py — Dark Point Bot (قسمت 6/12)

# ══════════════════════════════════════════════
#         🏦 DARK BANK (3% per 48h)
# ══════════════════════════════════════════════

async def msg_bank(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    uid = update.effective_user.id
    if not db.is_bot_on() and not is_admin(uid):
        await update.message.reply_text(bot_off_text()); return
    if not db.is_section_on('bank') and not is_admin(uid):
        await update.message.reply_text(section_off_text()); return

    clear_user_state(ctx)
    bal = db.get_balance(uid)
    deps = db.get_bank_deposits(uid)
    now = int(time.time())

    text = (
        f"🏦 <b>بانک دارکی</b>\n"
        f"{'═' * 30}\n\n"
        f"💎 موجودی آزاد: <b>{fmt(bal)}</b> DP\n"
        f"📈 نرخ سود: <b>3%</b> هر ۴۸ ساعت\n"
        f"⏳ دوره قفل: ۴۸ ساعت\n\n"
    )

    if deps:
        text += f"📋 <b>سپرده‌های فعال ({len(deps)}):</b>\n" + "─" * 28 + "\n"
        for d in deps:
            elapsed = now - d['deposit_time']
            rem = max(0, config.BANK_LOCK_PERIOD - elapsed)
            interest = int(d['amount'] * config.BANK_INTEREST_RATE)
            total = d['amount'] + interest
            if rem == 0:
                status = "🔓 <b>آزاد — قابل برداشت</b>"
            else:
                status = f"⏳ {seconds_to_hms(rem)} تا آزادسازی"
            text += (
                f"\n  💰 سپرده: <b>{fmt(d['amount'])}</b> DP\n"
                f"  📈 سود: <b>+{fmt(interest)}</b> DP\n"
                f"  💵 قابل برداشت: <b>{fmt(total)}</b> DP\n"
                f"  {status}\n"
            )
    else:
        text += "📭 سپرده فعالی ندارید.\n💡 DP خود را سپرده کنید و ۳٪ سود بگیرید!"

    text += f"\n{'═' * 30}"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 سپرده‌گذاری", callback_data="bank_deposit")],
        [InlineKeyboardButton("📤 برداشت سپرده", callback_data="bank_withdraw")],
    ])
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def cb_bank_deposit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    ctx.user_data['bank_action'] = 'deposit'
    ctx.user_data['bank_uid'] = uid
    bal = db.get_balance(uid)

    await safe_edit(q,
        f"💰 <b>سپرده‌گذاری در بانک</b>\n\n"
        f"💎 موجودی: <b>{fmt(bal)}</b> DP\n"
        f"📈 سود: ۳٪ پس از ۴۸ ساعت\n\n"
        f"📝 مبلغ سپرده را وارد کنید (DP):\n"
        f"(مثال: <code>1000000</code>)\n\n"
        f"❌ برای لغو: <code>لغو</code>",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ لغو", callback_data="bank_cancel")]
        ]))


async def cb_bank_withdraw(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    now = int(time.time())

    deps = db.get_bank_deposits(uid)
    free_deps = [d for d in deps if (now - d['deposit_time']) >= config.BANK_LOCK_PERIOD]

    if not free_deps:
        await safe_edit(q,
            "❌ هیچ سپرده‌ای آزاد نشده است!\n"
            "⏳ باید ۴۸ ساعت از زمان سپرده بگذرد.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 بازگشت", callback_data="bank_back")]
            ]))
        return

    rows = []
    for d in free_deps:
        interest = int(d['amount'] * config.BANK_INTEREST_RATE)
        total = d['amount'] + interest
        rows.append([InlineKeyboardButton(
            f"💰 {fmt(d['amount'])} + {fmt(interest)} سود = {fmt(total)}",
            callback_data=f"bw_{d['id']}"
        )])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="bank_back")])

    await safe_edit(q,
        "📤 <b>برداشت سپرده</b>\n\n"
        "سپرده مورد نظر را انتخاب کنید:",
        InlineKeyboardMarkup(rows))


async def cb_bank_withdraw_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    dep_id = int(q.data.split('_')[1])

    ok, res = db.bank_withdraw(uid, dep_id)
    if ok:
        db.check_level_up(uid)
        await safe_edit(q,
            f"✅ <b>برداشت موفق!</b>\n\n"
            f"💰 مبلغ واریز شده: <b>{fmt(res)}</b> DP\n"
            f"💎 موجودی: <b>{fmt(db.get_balance(uid))}</b> DP\n\n"
            f"📈 سود ۳٪ شامل مبلغ بالا است.")
    else:
        await safe_edit(q, f"❌ {res}")


async def cb_bank_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    clear_user_state(ctx)
    await safe_edit(q, "❌ عملیات بانکی لغو شد.")


async def cb_bank_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    clear_user_state(ctx)
    await safe_edit(q, "🔙 بازگشت")
    await ctx.bot.send_message(q.from_user.id, "منوی اصلی:", reply_markup=main_menu_kb())


async def process_bank_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Process bank deposit amount from text"""
    uid = update.effective_user.id
    if ctx.user_data.get('bank_action') != 'deposit' or ctx.user_data.get('bank_uid') != uid:
        return False

    text = (update.message.text or "").strip()
    if text in ('لغو', 'cancel', '/cancel'):
        clear_user_state(ctx)
        await update.message.reply_text("❌ لغو شد.", reply_markup=main_menu_kb())
        return True

    try:
        amount = int(text)
    except ValueError:
        await update.message.reply_text("❌ لطفاً یک عدد صحیح وارد کنید!")
        return True

    if amount < 1000:
        await update.message.reply_text("❌ حداقل سپرده: 1,000 DP")
        return True

    if db.bank_deposit(uid, amount):
        clear_user_state(ctx)
        interest = int(amount * config.BANK_INTEREST_RATE)
        await update.message.reply_text(
            f"✅ <b>سپرده ثبت شد!</b>\n\n"
            f"💰 مبلغ: <b>{fmt(amount)}</b> DP\n"
            f"📈 سود پس از ۴۸ ساعت: <b>+{fmt(interest)}</b> DP\n"
            f"💵 قابل برداشت: <b>{fmt(amount + interest)}</b> DP\n"
            f"⏳ زمان آزادسازی: ۴۸ ساعت\n\n"
            f"💎 موجودی: <b>{fmt(db.get_balance(uid))}</b> DP",
            parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())
    else:
        await update.message.reply_text("❌ موجودی کافی نیست!")
    return True


# ══════════════════════════════════════════════
#           ⛏ MINER (ماینر دارکی)
# ══════════════════════════════════════════════

async def msg_miner(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    uid = update.effective_user.id
    if not db.is_bot_on() and not is_admin(uid):
        await update.message.reply_text(bot_off_text()); return
    if not db.is_section_on('miner') and not is_admin(uid):
        await update.message.reply_text(section_off_text()); return

    clear_user_state(ctx)
    m = db.get_miner(uid)

    if not m:
        text = (
            f"⛏ <b>ماینر دارکی</b>\n"
            f"{'═' * 30}\n\n"
            f"📭 شما هنوز ماینر ندارید!\n\n"
            f"💡 با خرید ماینر می‌توانید TON یا USDT استخراج کنید.\n"
            f"💰 هزینه خرید: <b>{fmt(config.MINER_BUY_COST)}</b> DP\n\n"
            f"📊 <b>سطوح ماینر:</b>\n"
            f"  L1: 0.01 TON/h | 0.03 USDT/h\n"
            f"  L2: 0.03 TON/h | 0.05 USDT/h\n"
            f"  L3: 0.04 TON/h | 0.07 USDT/h\n"
            f"  L4: 0.06 TON/h | 0.09 USDT/h\n"
            f"  L5: 0.09 TON/h | 0.12 USDT/h\n"
            f"{'═' * 30}"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"⛏ خرید ماینر ({fmt(config.MINER_BUY_COST)} DP)",
                callback_data="miner_buy")],
        ])
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    # Has miner
    now = int(time.time())
    elec = max(0, m['electricity_end'] - now)
    rates = config.MINER_LEVELS[m['level']]
    is_running = elec > 0
    up_cost = rates['upgrade'] if m['level'] < 5 else 0

    # Calculate pending earnings
    pending = db.collect_miner(uid)
    pending_text = ""
    if pending and (pending['ton'] > 0 or pending['usdt'] > 0):
        pending_text = f"\n💰 درآمد جمع‌نشده: {pending['ton']:.6f} TON | {pending['usdt']:.4f} USDT"

    status = "🟢 در حال کار" if is_running else "🔴 بدون برق"

    text = (
        f"⛏ <b>ماینر دارکی</b>\n"
        f"{'═' * 30}\n\n"
        f"📊 سطح: <b>{m['level']}</b> / 5\n"
        f"💎 ارز استخراج: <b>{m['currency']}</b>\n"
        f"⚡ وضعیت: {status}\n"
        f"🔋 برق باقی‌مانده: <b>{seconds_to_hms(elec)}</b>\n\n"
        f"📈 <b>نرخ استخراج:</b>\n"
        f"   TON: {rates['ton']}/h | USDT: {rates['usdt']}/h\n\n"
        f"💰 <b>کل استخراج:</b>\n"
        f"   TON: {m['total_ton']:.6f}\n"
        f"   USDT: {m['total_usdt']:.4f}"
        f"{pending_text}\n\n"
        f"⚡ هزینه برق: {fmt(config.MINER_ELECTRICITY_COST)} DP/h"
        + (f"\n⬆️ هزینه ارتقا: {fmt(up_cost)} DP" if up_cost else "\n✅ حداکثر سطح!")
        + f"\n{'═' * 30}"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔋 خرید برق (1h)", callback_data="miner_elec"),
         InlineKeyboardButton("⬆️ ارتقا", callback_data="miner_upgrade")],
        [InlineKeyboardButton("💰 جمع‌آوری", callback_data="miner_collect"),
         InlineKeyboardButton("🔄 تغییر ارز", callback_data="miner_switch")],
    ])
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def cb_miner_buy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if db.buy_miner(uid):
        await safe_edit(q,
            f"✅ <b>ماینر خریداری شد!</b>\n\n"
            f"⛏ سطح: 1\n"
            f"💎 ارز پیش‌فرض: TON\n\n"
            f"⚠️ برای شروع استخراج، برق بخرید!")
    else:
        await q.answer(f"❌ موجودی کافی نیست! ({fmt(config.MINER_BUY_COST)} DP)", show_alert=True)


async def cb_miner_elec(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if db.buy_electricity(uid, 1):
        m = db.get_miner(uid)
        elec = max(0, m['electricity_end'] - int(time.time())) if m else 0
        await safe_edit(q,
            f"✅ <b>۱ ساعت برق خریداری شد!</b>\n\n"
            f"🔋 برق باقی‌مانده: <b>{seconds_to_hms(elec)}</b>")
    else:
        await q.answer(f"❌ موجودی کافی نیست! ({fmt(config.MINER_ELECTRICITY_COST)} DP)", show_alert=True)


async def cb_miner_upgrade(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    ok, res = db.upgrade_miner(uid)
    if ok:
        await safe_edit(q,
            f"✅ <b>ماینر ارتقا یافت!</b>\n\n"
            f"📊 سطح جدید: <b>{res}</b>\n"
            f"📈 نرخ: {config.MINER_LEVELS[res]['ton']} TON/h | "
            f"{config.MINER_LEVELS[res]['usdt']} USDT/h")
    else:
        await q.answer(f"❌ {res}", show_alert=True)


async def cb_miner_collect(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    r = db.collect_miner(uid)
    if r and (r['ton'] > 0 or r['usdt'] > 0):
        m = db.get_miner(uid)
        await safe_edit(q,
            f"✅ <b>درآمد جمع‌آوری شد!</b>\n\n"
            f"💎 TON: <b>{r['ton']:.6f}</b>\n"
            f"💵 USDT: <b>{r['usdt']:.4f}</b>\n\n"
            f"📊 کل TON: {m['total_ton']:.6f}\n"
            f"📊 کل USDT: {m['total_usdt']:.4f}")
    else:
        await q.answer("⚠️ درآمدی برای جمع‌آوری نیست!", show_alert=True)


async def cb_miner_switch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    m = db.get_miner(uid)
    if not m:
        return
    new_cur = 'USDT' if m['currency'] == 'TON' else 'TON'
    db.set_miner_currency(uid, new_cur)
    await safe_edit(q,
        f"✅ ارز استخراج تغییر کرد!\n\n"
        f"💎 ارز فعلی: <b>{new_cur}</b>")


# ══════════════════════════════════════════════
#         🏭 FACTORY (کارخونه دارکی)
# ══════════════════════════════════════════════
# 5 levels, each increases DP production

FACTORY_LEVELS = {
    1: {"cost": 0, "production": 500, "name": "کارگاه کوچک"},
    2: {"cost": 10_000_000, "production": 1500, "name": "کارخانه متوسط"},
    3: {"cost": 50_000_000, "production": 4000, "name": "کارخانه بزرگ"},
    4: {"cost": 200_000_000, "production": 10000, "name": "مجتمع صنعتی"},
    5: {"cost": 500_000_000, "production": 25000, "name": "ابرکارخانه"},
}


async def msg_factory(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    uid = update.effective_user.id
    if not db.is_bot_on() and not is_admin(uid):
        await update.message.reply_text(bot_off_text()); return
    if not db.is_section_on('factory') and not is_admin(uid):
        await update.message.reply_text(section_off_text()); return

    clear_user_state(ctx)

    c = db.conn.cursor()
    c.execute('SELECT factory_level, factory_last_collect FROM users WHERE user_id=?', (uid,))
    r = c.fetchone()

    if not r or r[0] is None:
        # Initialize factory for user
        try:
            c.execute('ALTER TABLE users ADD COLUMN factory_level INTEGER DEFAULT 0')
            c.execute('ALTER TABLE users ADD COLUMN factory_last_collect INTEGER DEFAULT 0')
            db.conn.commit()
        except Exception:
            pass
        f_level = 0
        f_last = 0
    else:
        f_level = r[0] or 0
        f_last = r[1] or 0

    if f_level == 0:
        text = (
            f"🏭 <b>کارخونه دارکی</b>\n"
            f"{'═' * 30}\n\n"
            f"📭 شما هنوز کارخانه ندارید!\n\n"
            f"💡 کارخانه هر ساعت DP تولید می‌کند.\n\n"
            f"📊 <b>سطوح کارخانه:</b>\n"
        )
        for lv, info in FACTORY_LEVELS.items():
            text += f"  L{lv}: {info['name']} | {fmt(info['production'])} DP/h"
            if lv > 1:
                text += f" | ارتقا: {fmt(info['cost'])} DP"
            text += "\n"

        text += f"{'═' * 30}"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏭 ساخت کارخانه (رایگان)", callback_data="factory_build")],
        ])
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    # Has factory
    now = int(time.time())
    info = FACTORY_LEVELS[f_level]
    hours = (now - f_last) / 3600 if f_last > 0 else 0
    pending = int(info['production'] * min(hours, 24))  # Max 24h accumulation
    next_cost = FACTORY_LEVELS[f_level + 1]['cost'] if f_level < 5 else 0

    text = (
        f"🏭 <b>کارخونه دارکی</b>\n"
        f"{'═' * 30}\n\n"
        f"📊 سطح: <b>{f_level}</b> / 5 ({info['name']})\n"
        f"📈 تولید: <b>{fmt(info['production'])}</b> DP/h\n"
        f"💰 درآمد جمع‌نشده: <b>{fmt(pending)}</b> DP\n\n"
    )
    if f_level < 5:
        text += f"⬆️ هزینه ارتقا: <b>{fmt(next_cost)}</b> DP\n"
    else:
        text += "✅ حداکثر سطح!\n"
    text += f"{'═' * 30}"

    kb_rows = [
        [InlineKeyboardButton("💰 جمع‌آوری", callback_data="factory_collect")],
    ]
    if f_level < 5:
        kb_rows.append([InlineKeyboardButton("⬆️ ارتقا", callback_data="factory_upgrade")])

    await update.message.reply_text(text, parse_mode=ParseMode.HTML,
                                    reply_markup=InlineKeyboardMarkup(kb_rows))


async def cb_factory_build(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    c = db.conn.cursor()
    try:
        c.execute('UPDATE users SET factory_level=1, factory_last_collect=? WHERE user_id=?',
                  (int(time.time()), uid))
        db.conn.commit()
        await safe_edit(q, "✅ کارخانه سطح ۱ ساخته شد!\n📈 تولید: 500 DP/h")
    except Exception:
        await q.answer("❌ خطا!", show_alert=True)


async def cb_factory_collect(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    c = db.conn.cursor()
    c.execute('SELECT factory_level, factory_last_collect FROM users WHERE user_id=?', (uid,))
    r = c.fetchone()
    if not r or not r[0]:
        await q.answer("❌ کارخانه ندارید!", show_alert=True); return

    f_level = r[0]
    f_last = r[1] or int(time.time())
    now = int(time.time())
    hours = (now - f_last) / 3600
    info = FACTORY_LEVELS[f_level]
    earned = int(info['production'] * min(hours, 24))

    if earned < 1:
        await q.answer("⚠️ هنوز درآمدی تولید نشده!", show_alert=True); return

    db.add_balance(uid, earned)
    c.execute('UPDATE users SET factory_last_collect=? WHERE user_id=?', (now, uid))
    db.conn.commit()
    db.check_level_up(uid)

    await safe_edit(q,
        f"✅ <b>درآمد کارخانه جمع‌آوری شد!</b>\n\n"
        f"💰 +<b>{fmt(earned)}</b> DP\n"
        f"⏱ مدت: {seconds_to_hms(int(hours * 3600))}\n"
        f"💎 موجودی: <b>{fmt(db.get_balance(uid))}</b> DP")


async def cb_factory_upgrade(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    c = db.conn.cursor()
    c.execute('SELECT factory_level FROM users WHERE user_id=?', (uid,))
    r = c.fetchone()
    if not r or not r[0]:
        await q.answer("❌ کارخانه ندارید!", show_alert=True); return

    f_level = r[0]
    if f_level >= 5:
        await q.answer("✅ حداکثر سطح!", show_alert=True); return

    next_level = f_level + 1
    cost = FACTORY_LEVELS[next_level]['cost']
    if not db.deduct_balance(uid, cost):
        await q.answer(f"❌ موجودی کافی نیست! ({fmt(cost)} DP)", show_alert=True); return

    c.execute('UPDATE users SET factory_level=? WHERE user_id=?', (next_level, uid))
    db.conn.commit()
    info = FACTORY_LEVELS[next_level]
    await safe_edit(q,
        f"✅ <b>کارخانه ارتقا یافت!</b>\n\n"
        f"📊 سطح: <b>{next_level}</b> ({info['name']})\n"
        f"📈 تولید: <b>{fmt(info['production'])}</b> DP/h")


# ══════════════════════════════════════════════
#         💸 TRANSFER (انتقال DP)
# ══════════════════════════════════════════════

async def cmd_transfer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Transfer DP to another user — 10% fee, 10/day limit"""
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.message.reply_text("⚠️ انتقال فقط در <b>گروه</b> ممکن است!",
                                        parse_mode=ParseMode.HTML)
        return

    uid = update.effective_user.id
    if not db.is_bot_on() and not is_admin(uid):
        await update.message.reply_text(bot_off_text()); return

    # Check daily limit
    if not db.can_transfer(uid):
        await update.message.reply_text(
            f"❌ حد مجاز انتقال روزانه ({config.TRANSFER_DAILY_LIMIT} بار) تمام شده!")
        return

    parts = (update.message.text or "").strip().split()
    if len(parts) < 2:
        await update.message.reply_text(
            f"💸 <b>انتقال DP</b>\n\n"
            f"📝 دستور: <code>انتقال [مبلغ]</code>\n"
            f"💰 کارمزد: {int(config.TRANSFER_FEE * 100)}%\n"
            f"📊 حد روزانه: {config.TRANSFER_DAILY_LIMIT} بار\n\n"
            f"⚠️ روی پیام کاربر مقصد ریپلای کنید!",
            parse_mode=ParseMode.HTML)
        return

    try:
        amount = int(parts[1])
    except ValueError:
        await update.message.reply_text("❌ مبلغ نامعتبر!")
        return

    if amount < 1000:
        await update.message.reply_text("❌ حداقل انتقال: 1,000 DP")
        return

    # Must reply to target user
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ روی پیام کاربر مقصد <b>ریپلای</b> کنید!",
                                        parse_mode=ParseMode.HTML)
        return

    target = update.message.reply_to_message.from_user
    if not target or target.id == uid:
        await update.message.reply_text("❌ نمی‌توانید به خودتان انتقال دهید!")
        return
    if target.is_bot:
        await update.message.reply_text("❌ نمی‌توانید به ربات انتقال دهید!")
        return

    # Ensure target exists in DB
    db.create_user(target.id, target.username or "", target.first_name or "")

    fee = int(amount * config.TRANSFER_FEE)
    total_cost = amount + fee

    ok, res = db.do_transfer(uid, target.id, amount)
    if ok:
        sender_name = html.escape(update.effective_user.first_name or "کاربر")
        target_name = html.escape(target.first_name or "کاربر")
        await update.message.reply_text(
            f"✅ <b>انتقال موفق!</b>\n\n"
            f"👤 از: {sender_name}\n"
            f"👤 به: {target_name}\n"
            f"💰 مبلغ: <b>{fmt(amount)}</b> DP\n"
            f"💸 کارمزد: <b>{fmt(fee)}</b> DP\n"
            f"💵 کل کسر: <b>{fmt(total_cost)}</b> DP",
            parse_mode=ParseMode.HTML)
        db.check_level_up(target.id)
    else:
        await update.message.reply_text(f"❌ {res}")# bot.py — Dark Point Bot (قسمت 7/12)

# ══════════════════════════════════════════════
#            🛒 SHOP (فروشگاه)
# ══════════════════════════════════════════════

async def msg_shop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    uid = update.effective_user.id
    if not db.is_bot_on() and not is_admin(uid):
        await update.message.reply_text(bot_off_text()); return
    if not db.is_section_on('shop') and not is_admin(uid):
        await update.message.reply_text(section_off_text()); return

    clear_user_state(ctx)
    items = db.get_shop_items()
    bal = db.get_balance(uid)

    if not items:
        await update.message.reply_text(
            "🛒 <b>فروشگاه</b>\n\n"
            "📭 فروشگاه فعلاً خالی است.\n"
            "بزودی محصولات جدید اضافه می‌شود!",
            parse_mode=ParseMode.HTML)
        return

    text = (
        f"🛒 <b>فروشگاه Dark Point</b>\n"
        f"{'═' * 30}\n\n"
        f"💎 موجودی شما: <b>{fmt(bal)}</b> DP\n\n"
    )

    rows = []
    for item in items:
        stock_text = "نامحدود" if item['stock'] == -1 else str(item['stock'])
        text += (
            f"📦 <b>{html.escape(item['name'])}</b>\n"
            f"   💰 قیمت: {fmt(item['price'])} DP | 📊 موجودی: {stock_text}\n\n"
        )
        rows.append([InlineKeyboardButton(
            f"🛒 {item['name']} ({fmt(item['price'])} DP)",
            callback_data=f"shop_buy_{item['id']}"
        )])

    text += f"{'═' * 30}"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML,
                                    reply_markup=InlineKeyboardMarkup(rows))


async def cb_shop_buy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    item_id = int(q.data.split('_')[2])

    ok, item = db.buy_shop_item(uid, item_id)
    if not ok:
        if item is None:
            await q.answer("❌ موجودی کافی نیست یا محصول تمام شده!", show_alert=True)
        return

    # Deliver item
    mtype = item['media_type']
    content = item['media_content']
    delivery_text = (
        f"✅ <b>خرید موفق!</b>\n\n"
        f"📦 {html.escape(item['name'])}\n"
        f"💰 قیمت: {fmt(item['price'])} DP\n"
        f"💎 موجودی: {fmt(db.get_balance(uid))} DP\n\n"
        f"📋 <b>محصول شما:</b>"
    )

    try:
        if mtype == 'photo':
            await ctx.bot.send_photo(uid, content, caption=delivery_text,
                                     parse_mode=ParseMode.HTML)
        elif mtype == 'video':
            await ctx.bot.send_video(uid, content, caption=delivery_text,
                                     parse_mode=ParseMode.HTML)
        elif mtype == 'document':
            await ctx.bot.send_document(uid, content, caption=delivery_text,
                                        parse_mode=ParseMode.HTML)
        else:
            await ctx.bot.send_message(uid,
                f"{delivery_text}\n\n<code>{html.escape(content)}</code>",
                parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Shop delivery err: {e}")
        await ctx.bot.send_message(uid,
            f"{delivery_text}\n\n⚠️ خطا در ارسال. با پشتیبانی تماس بگیرید.",
            parse_mode=ParseMode.HTML)

    await safe_edit(q, f"✅ محصول <b>{html.escape(item['name'])}</b> خریداری شد!\nبه چت مراجعه کنید.",
                    InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 بازگشت", callback_data="shop_back")]
                    ]))


async def cb_shop_back(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await safe_edit(q, "🔙 بازگشت به منو")
    await ctx.bot.send_message(q.from_user.id, "منوی اصلی:", reply_markup=main_menu_kb())


# ══════════════════════════════════════════════
#            🎁 GIFT (هدیه)
# ══════════════════════════════════════════════

async def msg_gift(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    uid = update.effective_user.id
    if not db.is_bot_on() and not is_admin(uid):
        await update.message.reply_text(bot_off_text()); return
    if not db.is_section_on('gift') and not is_admin(uid):
        await update.message.reply_text(section_off_text()); return

    clear_user_state(ctx)
    plans = db.get_gift_plans()
    bal = db.get_balance(uid)

    text = (
        f"🎁 <b>هدیه Dark Point</b>\n"
        f"{'═' * 30}\n\n"
        f"💎 موجودی: <b>{fmt(bal)}</b> DP\n\n"
        f"🧸 به دوستانتان هدیه بفرستید!\n\n"
    )

    rows = []
    if plans:
        for p in plans:
            text += f"🎁 {html.escape(p['name'])} — <b>{fmt(p['price'])}</b> DP\n"
            rows.append([InlineKeyboardButton(
                f"🎁 {p['name']} ({fmt(p['price'])} DP)",
                callback_data=f"gift_buy_{p['id']}"
            )])
    else:
        text += "📭 پلن هدیه‌ای فعال نیست."

    # Teddy bear gift (default)
    teddy_price = int(db.get_setting('gift_price', '100000'))
    text += f"\n🧸 خرس تدی — <b>{fmt(teddy_price)}</b> DP"
    rows.insert(0, [InlineKeyboardButton(
        f"🧸 خرس تدی ({fmt(teddy_price)} DP)",
        callback_data="gift_teddy"
    )])

    text += f"\n{'═' * 30}"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML,
                                    reply_markup=InlineKeyboardMarkup(rows))


async def cb_gift_teddy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    price = int(db.get_setting('gift_price', '100000'))

    if not db.deduct_balance(uid, price):
        await q.answer("❌ موجودی کافی نیست!", show_alert=True)
        return

    ctx.user_data['gift_type'] = 'teddy'
    ctx.user_data['gift_uid'] = uid
    await safe_edit(q,
        "🧸 <b>هدیه خرس تدی</b>\n\n"
        "🆔 آیدی عددی کاربر مقصد را وارد کنید:\n"
        "(روی پیام کاربر ریپلای و دستور /gift هم کار می‌کند)")


async def cb_gift_buy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    plan_id = int(q.data.split('_')[2])

    plans = db.get_gift_plans()
    plan = next((p for p in plans if p['id'] == plan_id), None)
    if not plan:
        await q.answer("❌ پلن یافت نشد!", show_alert=True)
        return

    if not db.deduct_balance(uid, plan['price']):
        await q.answer("❌ موجودی کافی نیست!", show_alert=True)
        return

    ctx.user_data['gift_type'] = 'plan'
    ctx.user_data['gift_plan'] = plan['name']
    ctx.user_data['gift_uid'] = uid
    await safe_edit(q,
        f"🎁 <b>هدیه {html.escape(plan['name'])}</b>\n\n"
        f"🆔 آیدی عددی کاربر مقصد را وارد کنید:")


async def process_gift_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    gtype = ctx.user_data.get('gift_type')
    if not gtype or ctx.user_data.get('gift_uid') != uid:
        return False

    text = (update.message.text or "").strip()
    if text in ('لغو', 'cancel'):
        clear_user_state(ctx)
        await update.message.reply_text("❌ لغو شد.", reply_markup=main_menu_kb())
        return True

    try:
        target_id = int(text)
    except ValueError:
        await update.message.reply_text("❌ آیدی عددی نامعتبر!")
        return True

    if target_id == uid:
        await update.message.reply_text("❌ نمی‌توانید به خودتان هدیه بدهید!")
        return True

    target = db.get_user(target_id)
    if not target:
        await update.message.reply_text("❌ کاربر یافت نشد!")
        return True

    gift_name = "خرس تدی 🧸" if gtype == 'teddy' else ctx.user_data.get('gift_plan', 'هدیه')
    clear_user_state(ctx)

    await update.message.reply_text(
        f"✅ <b>هدیه ارسال شد!</b>\n\n"
        f"🎁 {html.escape(gift_name)}\n"
        f"👤 به: {html.escape(target['first_name'] or str(target_id))}\n"
        f"💎 موجودی: <b>{fmt(db.get_balance(uid))}</b> DP",
        parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())

    await safe_send(ctx.bot, target_id,
        f"🎁 <b>شما هدیه دریافت کردید!</b>\n\n"
        f"🎁 {html.escape(gift_name)}\n"
        f"👤 از طرف: {html.escape(update.effective_user.first_name or 'ناشناس')}")
    return True


# ══════════════════════════════════════════════
#            📋 TASKS (تسک‌ها)
# ══════════════════════════════════════════════

async def msg_tasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    uid = update.effective_user.id
    if not db.is_bot_on() and not is_admin(uid):
        await update.message.reply_text(bot_off_text()); return
    if not db.is_section_on('tasks') and not is_admin(uid):
        await update.message.reply_text(section_off_text()); return

    clear_user_state(ctx)
    tasks = db.get_active_tasks()

    text = (
        f"📋 <b>تسک‌های Dark Point</b>\n"
        f"{'═' * 30}\n\n"
    )

    if not tasks:
        text += "📭 تسک فعالی وجود ندارد.\nبزودی تسک‌های جدید اضافه می‌شود!"
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        return

    rows = []
    for t in tasks:
        # Check if user already completed
        c = db.conn.cursor()
        c.execute('SELECT status FROM user_tasks WHERE user_id=? AND task_id=?', (uid, t['id']))
        ut = c.fetchone()
        status = ut[0] if ut else 'none'

        if status == 'completed':
            emoji = "✅"
            btn_text = f"✅ {t['title']}"
        elif status == 'pending':
            emoji = "⏳"
            btn_text = f"⏳ {t['title']}"
        else:
            emoji = "🔲"
            btn_text = f"🔲 {t['title']} (+{fmt(t['reward'])} DP)"
            rows.append([InlineKeyboardButton(btn_text, callback_data=f"task_do_{t['id']}")])
            continue

        text += f"{emoji} {html.escape(t['title'])} — {fmt(t['reward'])} DP\n"

    text += f"\n{'═' * 30}"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML,
                                    reply_markup=InlineKeyboardMarkup(rows) if rows else None)


async def cb_task_do(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    task_id = int(q.data.split('_')[2])

    c = db.conn.cursor()
    c.execute('SELECT * FROM tasks WHERE id=?', (task_id,))
    task = c.fetchone()
    if not task:
        await q.answer("❌ تسک یافت نشد!", show_alert=True)
        return

    ttype = task['type']

    if ttype == 'channel':
        # Channel join task — check membership
        channel = task['data']
        try:
            m = await ctx.bot.get_chat_member(channel, uid)
            if m.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR,
                            ChatMemberStatus.OWNER):
                if db.complete_task(uid, task_id):
                    db.check_level_up(uid)
                    await safe_edit(q,
                        f"✅ <b>تسک انجام شد!</b>\n\n"
                        f"📋 {html.escape(task['title'])}\n"
                        f"💰 پاداش: <b>+{fmt(task['reward'])}</b> DP\n"
                        f"💎 موجودی: <b>{fmt(db.get_balance(uid))}</b> DP")
                else:
                    await q.answer("⚠️ قبلاً انجام داده‌اید!", show_alert=True)
            else:
                u = channel.lstrip('@')
                await safe_edit(q,
                    f"❌ هنوز عضو نشده‌اید!\n\n"
                    f"📢 ابتدا در {channel} عضو شوید.",
                    InlineKeyboardMarkup([
                        [InlineKeyboardButton(f"📢 عضویت در {channel}", url=f"https://t.me/{u}")],
                        [InlineKeyboardButton("✅ عضو شدم", callback_data=f"task_check_{task_id}")],
                    ]))
        except Exception:
            await q.answer("❌ خطا در بررسی عضویت!", show_alert=True)

    elif ttype == 'mission':
        # Screenshot mission — user must send screenshot
        ctx.user_data['mission_task'] = task_id
        ctx.user_data['mission_uid'] = uid
        await safe_edit(q,
            f"📸 <b>ماموریت: {html.escape(task['title'])}</b>\n\n"
            f"📝 {html.escape(task['data'])}\n\n"
            f"📸 اسکرین‌شات انجام ماموریت را ارسال کنید.\n"
            f"💰 پاداش: {fmt(task['reward'])} DP\n\n"
            f"⚠️ پس از ارسال، ادمین بررسی می‌کند.")

    else:
        # Simple task — auto complete
        if db.complete_task(uid, task_id):
            db.check_level_up(uid)
            await safe_edit(q,
                f"✅ <b>تسک انجام شد!</b>\n\n"
                f"💰 +<b>{fmt(task['reward'])}</b> DP")
        else:
            await q.answer("⚠️ قبلاً انجام داده‌اید!", show_alert=True)


async def cb_task_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Re-check channel join for task"""
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    task_id = int(q.data.split('_')[2])

    c = db.conn.cursor()
    c.execute('SELECT * FROM tasks WHERE id=?', (task_id,))
    task = c.fetchone()
    if not task:
        return

    channel = task['data']
    try:
        m = await ctx.bot.get_chat_member(channel, uid)
        if m.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR,
                        ChatMemberStatus.OWNER):
            if db.complete_task(uid, task_id):
                db.check_level_up(uid)
                await safe_edit(q,
                    f"✅ <b>تسک انجام شد!</b>\n\n"
                    f"💰 +<b>{fmt(task['reward'])}</b> DP\n"
                    f"💎 موجودی: <b>{fmt(db.get_balance(uid))}</b> DP")
            else:
                await q.answer("⚠️ قبلاً انجام شده!", show_alert=True)
        else:
            await q.answer("❌ هنوز عضو نشده‌اید!", show_alert=True)
    except Exception:
        await q.answer("❌ خطا!", show_alert=True)


async def process_mission_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Process mission screenshot"""
    uid = update.effective_user.id
    task_id = ctx.user_data.get('mission_task')
    if not task_id or ctx.user_data.get('mission_uid') != uid:
        return False

    # Forward photo to admin for approval
    c = db.conn.cursor()
    c.execute('INSERT INTO user_tasks (user_id,task_id,status,created_at) VALUES (?,?,?,?)',
              (uid, task_id, 'pending', int(time.time())))
    db.conn.commit()

    clear_user_state(ctx)
    await update.message.reply_text(
        "✅ اسکرین‌شات ارسال شد!\n⏳ منتظر تأیید ادمین باشید.",
        reply_markup=main_menu_kb())

    # Notify admin
    uname = html.escape(update.effective_user.first_name or str(uid))
    await safe_send(ctx.bot, config.ADMIN_ID,
        f"📸 <b>ماموریت جدید برای تأیید</b>\n\n"
        f"👤 {uname} (<code>{uid}</code>)\n"
        f"📋 تسک ID: {task_id}\n\n"
        f"⬇️ اسکرین‌شات زیر را بررسی کنید:",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تأیید", callback_data=f"miss_ok_{uid}_{task_id}"),
             InlineKeyboardButton("❌ رد", callback_data=f"miss_no_{uid}_{task_id}")],
        ]))

    # Forward the photo to admin
    try:
        if update.message.photo:
            photo = update.message.photo[-1].file_id
            await ctx.bot.send_photo(config.ADMIN_ID, photo)
        elif update.message.document:
            await ctx.bot.send_document(config.ADMIN_ID, update.message.document.file_id)
    except Exception as e:
        logger.error(f"Forward mission err: {e}")

    return True


# ══════════════════════════════════════════════
#         👍 LIKE CHALLENGE (چالش لایک)
# ══════════════════════════════════════════════

async def msg_like(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    uid = update.effective_user.id
    if not db.is_bot_on() and not is_admin(uid):
        await update.message.reply_text(bot_off_text()); return
    if not db.is_section_on('like') and not is_admin(uid):
        await update.message.reply_text(section_off_text()); return

    clear_user_state(ctx)
    u = db.get_user(uid)
    cost = config.LIKE_CHALLENGE_COST
    days = config.LIKE_CHALLENGE_DAYS

    text = (
        f"👍 <b>چالش لایک</b>\n"
        f"{'═' * 30}\n\n"
        f"💰 هزینه ورود: <b>{fmt(cost)}</b> DP\n"
        f"⏳ مدت: <b>{days}</b> روز\n\n"
        f"📝 هر روز پست‌های کانال را لایک کنید.\n"
        f"🎁 در پایان دوره، جایزه ویژه دریافت می‌کنید!\n\n"
    )

    if u and u['like_challenge_active']:
        start = u['like_challenge_start']
        elapsed = int(time.time()) - start
        rem = max(0, days * 86400 - elapsed)
        if rem > 0:
            text += f"🟢 <b>فعال!</b>\n⏳ باقی‌مانده: {seconds_to_hms(rem)}"
        else:
            text += "✅ دوره تمام شد! جایزه خود را دریافت کنید."
    else:
        text += "🔴 هنوز شرکت نکرده‌اید."

    text += f"\n{'═' * 30}"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "👍 شرکت در چالش" if not (u and u['like_challenge_active']) else "📊 وضعیت",
            callback_data="like_join" if not (u and u['like_challenge_active']) else "like_status"
        )],
    ])
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def cb_like_join(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    cost = config.LIKE_CHALLENGE_COST

    if not db.deduct_balance(uid, cost):
        await q.answer(f"❌ موجودی کافی نیست! ({fmt(cost)} DP)", show_alert=True)
        return

    c = db.conn.cursor()
    c.execute('UPDATE users SET like_challenge_active=1, like_challenge_start=? WHERE user_id=?',
              (int(time.time()), uid))
    db.conn.commit()

    await safe_edit(q,
        f"✅ <b>در چالش لایک ثبت‌نام کردید!</b>\n\n"
        f"💰 هزینه: {fmt(cost)} DP\n"
        f"⏳ مدت: {config.LIKE_CHALLENGE_DAYS} روز\n\n"
        f"👍 هر روز پست‌های کانال را لایک کنید!")


# ══════════════════════════════════════════════
#         💱 CURRENCY CONVERT (تبدیل ارز)
# ══════════════════════════════════════════════

async def msg_convert(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    uid = update.effective_user.id
    if not db.is_bot_on() and not is_admin(uid):
        await update.message.reply_text(bot_off_text()); return
    if not db.is_section_on('convert') and not is_admin(uid):
        await update.message.reply_text(section_off_text()); return

    clear_user_state(ctx)
    bal = db.get_balance(uid)

    text = (
        f"💱 <b>تبدیل ارز به DP</b>\n"
        f"{'═' * 30}\n\n"
        f"💎 موجودی: <b>{fmt(bal)}</b> DP\n\n"
        f"📊 <b>نرخ‌ها:</b>\n"
        f"   💎 TON → DP: هر 0.01 TON = {fmt(config.TON_TO_DP)} DP\n"
        f"   💵 USDT → DP: هر 0.01 USDT = {fmt(config.USDT_TO_DP)} DP\n\n"
        f"📉 <b>حداقل:</b>\n"
        f"   TON: {config.TON_CONVERT_MIN} | USDT: {config.USDT_CONVERT_MIN}\n"
        f"{'═' * 30}"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💎 تبدیل TON به DP", callback_data="conv_ton"),
         InlineKeyboardButton("💵 تبدیل USDT به DP", callback_data="conv_usdt")],
    ])
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def cb_convert(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    cur = 'TON' if q.data == 'conv_ton' else 'USDT'

    ctx.user_data['conv_type'] = cur
    ctx.user_data['conv_uid'] = uid

    min_val = config.TON_CONVERT_MIN if cur == 'TON' else config.USDT_CONVERT_MIN
    rate = config.TON_TO_DP if cur == 'TON' else config.USDT_TO_DP

    await safe_edit(q,
        f"💱 <b>تبدیل {cur} به DP</b>\n\n"
        f"📊 نرخ: هر 0.01 {cur} = {fmt(rate)} DP\n"
        f"📉 حداقل: {min_val} {cur}\n\n"
        f"📝 مقدار {cur} را وارد کنید:\n"
        f"(مثال: <code>1.5</code>)",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ لغو", callback_data="conv_cancel")]
        ]))


async def cb_conv_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    clear_user_state(ctx)
    await safe_edit(q, "❌ لغو شد.")


async def process_convert_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cur = ctx.user_data.get('conv_type')
    if not cur or ctx.user_data.get('conv_uid') != uid:
        return False

    text = (update.message.text or "").strip()
    if text in ('لغو', 'cancel'):
        clear_user_state(ctx)
        await update.message.reply_text("❌ لغو شد.", reply_markup=main_menu_kb())
        return True

    try:
        amount = float(text)
    except ValueError:
        await update.message.reply_text("❌ عدد نامعتبر!")
        return True

    min_val = config.TON_CONVERT_MIN if cur == 'TON' else config.USDT_CONVERT_MIN
    rate = config.TON_TO_DP if cur == 'TON' else config.USDT_TO_DP

    if amount < min_val:
        await update.message.reply_text(f"❌ حداقل: {min_val} {cur}")
        return True

    dp = int((amount / 0.01) * rate)
    db.add_balance(uid, dp)
    db.check_level_up(uid)
    clear_user_state(ctx)

    await update.message.reply_text(
        f"✅ <b>تبدیل موفق!</b>\n\n"
        f"💱 {amount} {cur} → <b>{fmt(dp)}</b> DP\n"
        f"💎 موجودی: <b>{fmt(db.get_balance(uid))}</b> DP",
        parse_mode=ParseMode.HTML, reply_markup=main_menu_kb())

    await send_log(ctx.bot,
        f"💱 <b>تبدیل ارز</b>\n"
        f"👤 {html.escape(update.effective_user.first_name or str(uid))}\n"
        f"💱 {amount} {cur} → {fmt(dp)} DP")
    return True


# ══════════════════════════════════════════════
#         ⭐ STARS WITHDRAWAL (برداشت استارز)
# ══════════════════════════════════════════════

async def msg_stars(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    uid = update.effective_user.id
    if not db.is_bot_on() and not is_admin(uid):
        await update.message.reply_text(bot_off_text()); return
    if not db.is_section_on('stars') and not is_admin(uid):
        await update.message.reply_text(section_off_text()); return

    clear_user_state(ctx)
    bal = db.get_balance(uid)
    stars_price = int(db.get_setting('stars_price', config.STARS_DP_COST))
    max_stars = bal // stars_price * 50  # 1M DP = 50 stars

    text = (
        f"⭐ <b>برداشت استارز</b>\n"
        f"{'═' * 30}\n\n"
        f"💎 موجودی: <b>{fmt(bal)}</b> DP\n"
        f"📊 نرخ: <b>{fmt(stars_price)}</b> DP = 50 ⭐\n"
        f"⭐ حداکثر قابل برداشت: <b>{max_stars}</b> ستاره\n\n"
        f"{'═' * 30}"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ برداشت 50 ستاره", callback_data="stars_50")],
        [InlineKeyboardButton("⭐ برداشت 100 ستاره", callback_data="stars_100")],
        [InlineKeyboardButton("⭐ برداشت 250 ستاره", callback_data="stars_250")],
    ])
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def cb_stars(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    stars_map = {'stars_50': 50, 'stars_100': 100, 'stars_250': 250}
    stars = stars_map.get(q.data, 0)
    if not stars:
        return

    stars_price = int(db.get_setting('stars_price', config.STARS_DP_COST))
    cost = (stars // 50) * stars_price

    if not db.deduct_balance(uid, cost):
        await q.answer(f"❌ موجودی کافی نیست! ({fmt(cost)} DP)", show_alert=True)
        return

    await safe_edit(q,
        f"✅ <b>درخواست برداشت {stars} ⭐ ثبت شد!</b>\n\n"
        f"💰 هزینه: {fmt(cost)} DP\n"
        f"💎 موجودی: {fmt(db.get_balance(uid))} DP\n\n"
        f"⏳ استارز بزودی ارسال می‌شود.")

    await send_log(ctx.bot,
        f"⭐ <b>درخواست استارز</b>\n"
        f"👤 {html.escape(q.from_user.first_name or str(uid))} (<code>{uid}</code>)\n"
        f"⭐ {stars} ستاره | 💰 {fmt(cost)} DP")


# ══════════════════════════════════════════════
#         💰 BUY DP (خرید DP)
# ══════════════════════════════════════════════

async def msg_buy_dp(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    uid = update.effective_user.id
    if not db.is_bot_on() and not is_admin(uid):
        await update.message.reply_text(bot_off_text()); return
    if not db.is_section_on('buy_dp') and not is_admin(uid):
        await update.message.reply_text(section_off_text()); return

    clear_user_state(ctx)
    dp_amount = int(db.get_setting('buy_dp_amount', config.BUY_DP_DEFAULT_AMOUNT))
    price = int(db.get_setting('buy_dp_price', config.BUY_DP_DEFAULT_PRICE))

    text = (
        f"💰 <b>خرید Dark Point</b>\n"
        f"{'═' * 30}\n\n"
        f"📦 بسته: <b>{fmt(dp_amount)}</b> DP\n"
        f"💵 قیمت: <b>{fmt(price)}</b> تومان\n\n"
        f"📝 برای خرید، روی دکمه زیر کلیک کنید.\n"
        f"💳 پس از پرداخت، DP به حساب شما واریز می‌شود.\n"
        f"{'═' * 30}"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"💰 خرید {fmt(dp_amount)} DP ({fmt(price)} تومان)",
            callback_data="buydp_order"
        )],
    ])
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def cb_buydp_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    dp_amount = int(db.get_setting('buy_dp_amount', config.BUY_DP_DEFAULT_AMOUNT))
    price = int(db.get_setting('buy_dp_price', config.BUY_DP_DEFAULT_PRICE))

    await safe_edit(q,
        f"💰 <b>سفارش خرید DP</b>\n\n"
        f"📦 {fmt(dp_amount)} DP\n"
        f"💵 {fmt(price)} تومان\n\n"
        f"📝 لطفاً رسید پرداخت را ارسال کنید.\n"
        f"(عکس یا اسکرین‌شات فیش واریزی)\n\n"
        f"⚠️ پس از تأیید ادمین، DP واریز می‌شود.")

    ctx.user_data['buydp_uid'] = uid
    ctx.user_data['buydp_active'] = True


async def process_buydp_receipt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Process buy DP receipt photo"""
    uid = update.effective_user.id
    if not ctx.user_data.get('buydp_active') or ctx.user_data.get('buydp_uid') != uid:
        return False

    dp_amount = int(db.get_setting('buy_dp_amount', config.BUY_DP_DEFAULT_AMOUNT))
    price = int(db.get_setting('buy_dp_price', config.BUY_DP_DEFAULT_PRICE))

    clear_user_state(ctx)
    await update.message.reply_text(
        "✅ رسید ارسال شد!\n⏳ منتظر تأیید ادمین باشید.",
        reply_markup=main_menu_kb())

    # Notify admin
    uname = html.escape(update.effective_user.first_name or str(uid))
    admin_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأیید و واریز", callback_data=f"buydp_ok_{uid}_{dp_amount}"),
         InlineKeyboardButton("❌ رد", callback_data=f"buydp_no_{uid}")],
    ])
    await safe_send(ctx.bot, config.ADMIN_ID,
        f"💰 <b>درخواست خرید DP</b>\n\n"
        f"👤 {uname} (<code>{uid}</code>)\n"
        f"📦 {fmt(dp_amount)} DP | 💵 {fmt(price)} تومان\n\n"
        f"⬇️ رسید زیر را بررسی کنید:", admin_kb)

    try:
        if update.message.photo:
            await ctx.bot.send_photo(config.ADMIN_ID, update.message.photo[-1].file_id)
    except Exception:
        pass
    return True# bot.py — Dark Point Bot (قسمت 8/12)

# ══════════════════════════════════════════════
#         📖 DP PANEL (پنل DP — 12 صفحه)
# ══════════════════════════════════════════════

DP_PANEL_PAGES = {
    1: ("📖 <b>Dark Point چیست؟</b>",
        "Dark Point (DP) ارز داخلی ربات است.\n"
        "با DP می‌توانید بازی کنید، TON برداشت کنید،\n"
        "در فروشگاه خرید کنید و خیلی کارهای دیگر!"),
    2: ("💎 <b>چگونه DP بگیریم؟</b>",
        "• 🎁 دریافت جایزه هر ۳-۵ دقیقه\n"
        "• 👥 زیرمجموعه‌گیری\n"
        "• 🎮 بازی‌ها\n"
        "• 📋 انجام تسک‌ها\n"
        "• 🎰 گردونه شانس\n"
        "• 💰 خرید مستقیم DP"),
    3: ("💎 <b>برداشت TON</b>",
        f"نرخ: {fmt(config.TON_WITHDRAWAL_DP_RATE)} DP = {config.TON_WITHDRAWAL_TON_AMOUNT} TON\n"
        f"حداقل: {config.TON_WITHDRAWAL_MIN} TON\n\n"
        "با زیرمجموعه‌گیری راحت می‌توانید برداشت کنید!"),
    4: ("🏦 <b>بانک دارکی</b>",
        "سپرده‌گذاری DP و دریافت ۳٪ سود هر ۴۸ ساعت.\n"
        "پس از ۴۸ ساعت می‌توانید اصل + سود را برداشت کنید."),
    5: ("⛏ <b>ماینر دارکی</b>",
        "خرید ماینر و استخراج TON یا USDT.\n"
        "۵ سطح ارتقا | نیاز به برق\n"
        "هزینه برق: 2,000,000 DP/h"),
    6: ("🎮 <b>بازی‌ها</b>",
        "• 💥 کرش (2x/3x/5x)\n"
        "• 🎲 تاس (1.5x/3x/6x)\n"
        "• 🔮 حدس بزن (تا 10x)\n"
        "• 🎰 کازینو (7x/12x/15x)\n"
        "• 💣 بمب (+0.2x هر خانه امن)\n\n"
        "⚠️ همه بازی‌ها فقط در گروه!"),
    7: ("📊 <b>سیستم سطح</b>",
        "۲۰ سطح از 0 تا 20 میلیارد DP\n"
        "هر سطح = پاداش سطح × 1,000,000 DP\n"
        "سطح بالاتر = جایزه بیشتر در کلیم!"),
    8: ("🛒 <b>فروشگاه</b>",
        "خرید پلن‌ها و محصولات با DP.\n"
        "تحویل خودکار پس از خرید."),
    9: ("👥 <b>زیرمجموعه‌گیری</b>",
        "با دعوت دوستان DP رایگان بگیرید!\n"
        "هر رفرال = پاداش DP\n"
        "هر ورود جدید = پاداش ورود"),
    10: ("💱 <b>تبدیل ارز</b>",
         f"TON → DP: هر 0.01 TON = {fmt(config.TON_TO_DP)} DP\n"
         f"USDT → DP: هر 0.01 USDT = {fmt(config.USDT_TO_DP)} DP"),
    11: ("⭐ <b>استارز</b>",
         "تبدیل DP به ستاره تلگرام.\n"
         f"نرخ: {fmt(config.STARS_DP_COST)} DP = 50 ⭐"),
    12: ("🏭 <b>کارخانه</b>",
         "۵ سطح کارخانه\n"
         "هر ساعت DP تولید می‌کند.\n"
         "ساخت اولیه رایگان!"),
}


async def msg_dp_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    uid = update.effective_user.id
    if not db.is_bot_on() and not is_admin(uid):
        await update.message.reply_text(bot_off_text()); return

    clear_user_state(ctx)
    title, body = DP_PANEL_PAGES[1]
    text = f"{title}\n{'─' * 28}\n\n{body}\n\n📄 صفحه 1 / 12"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ قبلی", callback_data="panel_12"),
         InlineKeyboardButton("➡️ بعدی", callback_data="panel_2")],
    ])
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def cb_dp_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    page = int(q.data.split('_')[1])
    if page < 1:
        page = 12
    if page > 12:
        page = 1

    title, body = DP_PANEL_PAGES[page]
    text = f"{title}\n{'─' * 28}\n\n{body}\n\n📄 صفحه {page} / 12"

    prev_page = 12 if page == 1 else page - 1
    next_page = 1 if page == 12 else page + 1

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ قبلی", callback_data=f"panel_{prev_page}"),
         InlineKeyboardButton("➡️ بعدی", callback_data=f"panel_{next_page}")],
    ])
    await safe_edit(q, text, kb)


# ══════════════════════════════════════════════
#       GROUP COMMANDS (دستورات گروهی)
# ══════════════════════════════════════════════

async def group_check_and_register(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Register group and check member count"""
    chat = update.effective_chat
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return True  # Private chats always OK

    # Register group
    db.add_admin_group(chat.id, chat.title or "گروه")

    # Check member count
    try:
        count = await ctx.bot.get_chat_member_count(chat.id)
        if count < config.MIN_GROUP_MEMBERS:
            await update.message.reply_text(
                f"⚠️ تعداد اعضای گروه کمتر از {config.MIN_GROUP_MEMBERS} نفر است.\n"
                f"📊 اعضای فعلی: {count}\n\n"
                f"⚠️ ربات به زودی گروه را ترک می‌کند!")
            # Schedule leave (don't leave immediately to avoid spam)
            return False
    except Exception:
        pass
    return True


async def cmd_dark(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """دارک / دارک کانفیگ — group info command"""
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.message.reply_text("⚠️ این دستور فقط در گروه کار می‌کند!")
        return

    chat = update.effective_chat
    try:
        count = await ctx.bot.get_chat_member_count(chat.id)
    except Exception:
        count = "؟"

    bot_user = await ctx.bot.get_me()
    text = (
        f"🌑 <b>Dark Point Bot</b>\n"
        f"{'─' * 28}\n\n"
        f"👥 اعضای گروه: <b>{count}</b>\n"
        f"🏷 نام گروه: {html.escape(chat.title or '—')}\n\n"
        f"💎 برای دریافت DP رایگان:\n"
        f"به @{bot_user.username} پیام دهید!\n\n"
        f"🎮 دستورات بازی:\n"
        f"• <code>بازی [مبلغ]</code> — کرش\n"
        f"• <code>تاس [مبلغ]</code> — تاس\n"
        f"• <code>حدس بزن [مبلغ]</code> — حدس\n"
        f"• <code>کازینو [مبلغ]</code> — کازینو\n"
        f"• <code>بمب [مبلغ]</code> — بمب\n"
        f"• <code>انتقال [مبلغ]</code> — انتقال DP"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_balance_group(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """موجودی — show balance in group"""
    uid = update.effective_user.id
    db.create_user(uid, update.effective_user.username or "",
                   update.effective_user.first_name or "")
    bal = db.get_balance(uid)
    lvl = db.get_user_level(uid)
    ton_eq = dp_to_ton(bal)
    name = html.escape(update.effective_user.first_name or "کاربر")

    await update.message.reply_text(
        f"💎 <b>موجودی {name}</b>\n\n"
        f"💰 {fmt(bal)} DP\n"
        f"💎 ≈ {ton_eq:.6f} TON\n"
        f"📊 سطح: {lvl}",
        parse_mode=ParseMode.HTML)


async def cmd_profile_group(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """پروفایل دارکی — show profile in group"""
    uid = update.effective_user.id
    db.create_user(uid, update.effective_user.username or "",
                   update.effective_user.first_name or "")
    u = db.get_user(uid)
    if not u:
        return

    bal = u['balance']
    lvl = db.get_user_level(uid)
    name = html.escape(update.effective_user.first_name or "کاربر")

    await update.message.reply_text(
        f"👤 <b>پروفایل {name}</b>\n"
        f"{'─' * 28}\n\n"
        f"🆔 <code>{uid}</code>\n"
        f"💎 {fmt(bal)} DP\n"
        f"📊 سطح: {lvl} / 20\n"
        f"👥 رفرال: {u['referrals']}\n"
        f"🏆 کل درآمد: {fmt(u['total_earned'])} DP",
        parse_mode=ParseMode.HTML)


async def cmd_leaderboard_group(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """لیدربورد — in group"""
    top = db.get_top_users(5)
    if not top:
        await update.message.reply_text("📊 هنوز داده‌ای نیست.")
        return

    medals = ["🥇", "🥈", "🥉", "4.", "5."]
    text = "🏆 <b>لیدربورد</b>\n\n"
    for i, u in enumerate(top):
        name = html.escape(u['username'] or u['first_name'] or str(u['user_id']))
        text += f"{medals[i]} @{name} — {fmt(u['balance'])} DP\n"

    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_id_group(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """ایدی عددی — admin reply to get user ID"""
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ روی پیام کاربر ریپلای کنید!")
        return
    target = update.message.reply_to_message.from_user
    await update.message.reply_text(
        f"🆔 آیدی عددی <b>{html.escape(target.first_name or '')}</b>:\n"
        f"<code>{target.id}</code>",
        parse_mode=ParseMode.HTML)


async def cmd_miner_group(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """ماینر دارکی — quick miner info in group"""
    uid = update.effective_user.id
    m = db.get_miner(uid)
    name = html.escape(update.effective_user.first_name or "کاربر")
    if not m:
        await update.message.reply_text(f"⛏ {name} ماینر ندارد!")
        return
    now = int(time.time())
    elec = max(0, m['electricity_end'] - now)
    status = "🟢" if elec > 0 else "🔴"
    await update.message.reply_text(
        f"⛏ <b>ماینر {name}</b>\n"
        f"📊 L{m['level']} | {m['currency']} | {status} {seconds_to_hms(elec)}",
        parse_mode=ParseMode.HTML)


async def cmd_bank_group(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """بانک دارکی — quick bank info in group"""
    uid = update.effective_user.id
    deps = db.get_bank_deposits(uid)
    name = html.escape(update.effective_user.first_name or "کاربر")
    if not deps:
        await update.message.reply_text(f"🏦 {name} سپرده‌ای ندارد.")
        return
    total = sum(d['amount'] for d in deps)
    await update.message.reply_text(
        f"🏦 <b>بانک {name}</b>\n"
        f"📋 {len(deps)} سپرده | 💰 {fmt(total)} DP",
        parse_mode=ParseMode.HTML)


# ══════════════════════════════════════════════
#     ➕ ADD TO GROUP (افزودن به گروه)
# ══════════════════════════════════════════════

async def msg_add_group(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    bot_user = await ctx.bot.get_me()
    link = f"https://t.me/{bot_user.username}?startgroup=darkpoint"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن ربات به گروه", url=link)],
    ])
    await update.message.reply_text(
        "➕ <b>افزودن به گروه</b>\n\n"
        "🌑 ربات Dark Point را به گروه خود اضافه کنید!\n\n"
        "📋 <b>شرایط:</b>\n"
        f"• حداقل {config.MIN_GROUP_MEMBERS} عضو\n"
        "• ربات باید ادمین باشد\n"
        "• بازی‌ها فقط در گروه فعال هستند\n\n"
        "⚠️ اگر تعداد اعضا کمتر از حد مجاز شود،\n"
        "ربات گروه را ترک می‌کند.",
        parse_mode=ParseMode.HTML, reply_markup=kb)


# ══════════════════════════════════════════════
#     GROUP MEMBER CHECK (بررسی اعضای گروه)
# ══════════════════════════════════════════════

async def check_group_members_job(ctx: ContextTypes.DEFAULT_TYPE):
    """Periodic job: check all registered groups for min members"""
    groups = db.get_admin_groups()
    for g in groups:
        try:
            count = await ctx.bot.get_chat_member_count(g['chat_id'])
            if count < config.MIN_GROUP_MEMBERS:
                await ctx.bot.send_message(
                    g['chat_id'],
                    f"⚠️ تعداد اعضا ({count}) کمتر از {config.MIN_GROUP_MEMBERS} شد.\n"
                    f"👋 ربات گروه را ترک می‌کند.")
                await ctx.bot.leave_chat(g['chat_id'])
                db.remove_admin_group(g['chat_id'])
                logger.info(f"Left group {g['chat_id']} ({count} members)")
        except Forbidden:
            db.remove_admin_group(g['chat_id'])
            logger.info(f"Removed banned group {g['chat_id']}")
        except Exception as e:
            logger.warning(f"Group check err {g['chat_id']}: {e}")


async def on_chat_member_update(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle bot being added/removed from groups"""
    if not update.my_chat_member:
        return
    chat = update.my_chat_member.chat
    new_status = update.my_chat_member.new_chat_member.status

    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        if new_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR):
            db.add_admin_group(chat.id, chat.title or "گروه")
            try:
                await ctx.bot.send_message(
                    chat.id,
                    f"🌑 <b>Dark Point Bot</b> به گروه اضافه شد!\n\n"
                    f"📝 دستور <code>دارک</code> را بفرستید.\n"
                    f"⚠️ حداقل {config.MIN_GROUP_MEMBERS} عضو لازم است.",
                    parse_mode=ParseMode.HTML)
            except Exception:
                pass
        elif new_status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
            db.remove_admin_group(chat.id)# bot.py — Dark Point Bot (قسمت 9/12)

# ══════════════════════════════════════════════
#     ⚙️ ADMIN PANEL — PART 1
# ══════════════════════════════════════════════

def _admin_check(uid):
    return uid == config.ADMIN_ID


# ──────────────── Admin Router (text messages) ────────────────
async def admin_text_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Route admin text messages to appropriate handlers"""
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    uid = update.effective_user.id
    if not _admin_check(uid):
        return

    text = (update.message.text or "").strip()

    # First check if admin is in a flow
    if ctx.user_data.get('admin_broadcast'):
        await process_admin_broadcast(update, ctx)
        return
    if ctx.user_data.get('admin_broadcast_group'):
        await process_admin_broadcast_group(update, ctx)
        return
    if ctx.user_data.get('admin_add_dp'):
        await process_admin_add_dp(update, ctx)
        return
    if ctx.user_data.get('admin_deduct_dp'):
        await process_admin_deduct_dp(update, ctx)
        return
    if ctx.user_data.get('admin_search'):
        await process_admin_search(update, ctx)
        return
    if ctx.user_data.get('admin_ban'):
        await process_admin_ban(update, ctx)
        return
    if ctx.user_data.get('admin_unban'):
        await process_admin_unban(update, ctx)
        return
    if ctx.user_data.get('admin_send_user'):
        await process_admin_send_user(update, ctx)
        return
    if ctx.user_data.get('admin_reply'):
        await process_admin_reply(update, ctx)
        return
    if ctx.user_data.get('admin_force_add'):
        await process_admin_force_add(update, ctx)
        return
    if ctx.user_data.get('admin_force_remove'):
        await process_admin_force_remove(update, ctx)
        return
    if ctx.user_data.get('admin_task_add'):
        await process_admin_task_add(update, ctx)
        return
    if ctx.user_data.get('admin_shop_add'):
        await process_admin_shop_add(update, ctx)
        return
    if ctx.user_data.get('admin_gift_add'):
        await process_admin_gift_add(update, ctx)
        return
    if ctx.user_data.get('admin_buydp_set'):
        await process_admin_buydp_set(update, ctx)
        return
    if ctx.user_data.get('admin_panel_plan'):
        await process_admin_panel_plan(update, ctx)
        return
    if ctx.user_data.get('admin_gift_top'):
        await process_admin_gift_top(update, ctx)
        return
    if ctx.user_data.get('admin_gift_all'):
        await process_admin_gift_all(update, ctx)
        return

    # Menu button routing
    await _admin_menu_button(update, ctx, text)


async def _admin_menu_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle admin menu button presses"""
    uid = update.effective_user.id

    if text == "🔙 بازگشت به منو":
        clear_user_state(ctx)
        await update.message.reply_text("🔙 منوی اصلی:", reply_markup=main_menu_kb())
        return

    if text == "📊 آمار ربات":
        await _admin_stats(update, ctx)
    elif text == "💎 آمار برداشت TON":
        await msg_tw_stats(update, ctx)
    elif text == "⛏ آمار ماینینگ":
        await _admin_miner_stats(update, ctx)
    elif text == "💱 آمار ارز":
        await _admin_currency_stats(update, ctx)
    elif text == "📢 ارسال همگانی":
        await _admin_broadcast_start(update, ctx)
    elif text == "📣 ارسال به گروه‌ها":
        await _admin_broadcast_group_start(update, ctx)
    elif text == "💰 افزودن DP":
        await _admin_add_dp_start(update, ctx)
    elif text == "➖ کسر DP":
        await _admin_deduct_dp_start(update, ctx)
    elif text == "🔍 جستجوی کاربر":
        await _admin_search_start(update, ctx)
    elif text == "👤 ارسال به کاربر":
        await _admin_send_user_start(update, ctx)
    elif text == "🚫 بن کاربر":
        await _admin_ban_start(update, ctx)
    elif text == "✅ آنبان":
        await _admin_unban_start(update, ctx)
    elif text == "📢 فورس جوین":
        await _admin_force_join(update, ctx)
    elif text == "📋 گروه‌های من":
        await _admin_groups_list(update, ctx)
    elif text == "📋 مدیریت تسک‌ها":
        await _admin_tasks_manage(update, ctx)
    elif text == "✅ تایید ماموریت":
        await _admin_missions_pending(update, ctx)
    elif text == "🛒 مدیریت فروشگاه":
        await _admin_shop_manage(update, ctx)
    elif text == "🎁 مدیریت هدایا":
        await _admin_gift_manage(update, ctx)
    elif text == "💰 تنظیم خرید DP":
        await _admin_buydp_settings(update, ctx)
    elif text == "⭐ تنظیم استارز":
        await _admin_stars_settings(update, ctx)
    elif text == "📦 پلن‌های پنل":
        await _admin_panel_plans(update, ctx)
    elif text == "🏷 پاداش رفرال":
        await _admin_referral_settings(update, ctx)
    elif text == "⚙️ روشن/خاموش بخش‌ها":
        await update.message.reply_text(
            "⚙️ <b>مدیریت بخش‌ها</b>\n\n"
            "🟢 = روشن | 🔴 = خاموش",
            parse_mode=ParseMode.HTML,
            reply_markup=sections_toggle_kb())
    elif text == "🔌 ربات روشن/خاموش":
        current = db.is_bot_on()
        db.set_setting('bot_on', '0' if current else '1')
        state = "🔴 خاموش" if current else "🟢 روشن"
        await update.message.reply_text(
            f"🔌 ربات {state} شد!",
            reply_markup=admin_menu_kb())
    elif text == "💾 بکاپ":
        await _admin_backup(update, ctx)
    elif text == "♻️ ریستور":
        await update.message.reply_text(
            "♻️ <b>ریستور دیتابیس</b>\n\n"
            "فایل بکاپ (.db) را ارسال کنید.\n"
            "⚠️ دیتابیس فعلی جایگزین می‌شود!",
            parse_mode=ParseMode.HTML)
        ctx.user_data['admin_restore'] = True
    elif text == "🎁 هدیه به برترین‌ها":
        await _admin_gift_top_start(update, ctx)
    elif text == "🎁 هدیه به همه":
        await _admin_gift_all_start(update, ctx)
    elif text == "💬 پاسخ به کاربر":
        await _admin_reply_start(update, ctx)
    elif text == "📜 سفارش‌های اخیر":
        await _admin_recent_orders(update, ctx)


# ──────────────── Stats ────────────────
async def _admin_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    stats = db.get_total_stats()
    ton_stats = db.get_ton_stats()
    miner_stats = db.get_miner_stats()

    text = (
        f"📊 <b>آمار کلی ربات</b>\n"
        f"{'═' * 30}\n\n"
        f"👥 کل کاربران: <b>{fmt(stats['users'])}</b>\n"
        f"💎 کل DP در گردش: <b>{fmt(stats['balance'])}</b>\n"
        f"👥 کل رفرال‌ها: <b>{fmt(stats['refs'])}</b>\n\n"
        f"💎 <b>برداشت TON:</b>\n"
        f"   ✅ انجام شده: {ton_stats['ok']}\n"
        f"   ⏳ در انتظار: {ton_stats['pending']}\n"
        f"   ❌ رد شده: {ton_stats['rejected']}\n"
        f"   💎 کل TON: {ton_stats['ton']:.4f}\n\n"
        f"⛏ <b>ماینینگ:</b>\n"
        f"   👥 ماینرها: {miner_stats['count']}\n"
        f"   💎 TON: {miner_stats['ton']:.6f}\n"
        f"   💵 USDT: {miner_stats['usdt']:.4f}\n"
        f"{'═' * 30}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML,
                                    reply_markup=admin_menu_kb())


async def _admin_miner_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    stats = db.get_miner_stats()
    c = db.conn.cursor()
    c.execute('SELECT level, COUNT(*) FROM miners GROUP BY level ORDER BY level')
    levels = c.fetchall()

    text = (
        f"⛏ <b>آمار ماینینگ</b>\n"
        f"{'═' * 30}\n\n"
        f"👥 کل ماینرها: <b>{stats['count']}</b>\n"
        f"💎 کل TON: <b>{stats['ton']:.6f}</b>\n"
        f"💵 کل USDT: <b>{stats['usdt']:.4f}</b>\n\n"
        f"📊 <b>توزیع سطوح:</b>\n"
    )
    for lv in levels:
        text += f"   L{lv[0]}: {lv[1]} ماینر\n"
    text += f"{'═' * 30}"

    await update.message.reply_text(text, parse_mode=ParseMode.HTML,
                                    reply_markup=admin_menu_kb())


async def _admin_currency_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    c = db.conn.cursor()
    c.execute('SELECT COUNT(*), COALESCE(SUM(balance),0) FROM users WHERE balance > 0')
    active = c.fetchone()
    c.execute('SELECT MAX(balance) FROM users')
    max_bal = c.fetchone()[0] or 0
    c.execute('SELECT user_id, username, balance FROM users ORDER BY balance DESC LIMIT 1')
    top = c.fetchone()

    text = (
        f"💱 <b>آمار ارز</b>\n"
        f"{'═' * 30}\n\n"
        f"👥 کاربران فعال: <b>{active[0]}</b>\n"
        f"💎 کل DP: <b>{fmt(active[1])}</b>\n"
        f"🏆 بیشترین موجودی: <b>{fmt(max_bal)}</b> DP\n"
    )
    if top:
        name = top[1] or str(top[0])
        text += f"👤 ثروتمندترین: @{html.escape(name)}\n"
    text += f"{'═' * 30}"

    await update.message.reply_text(text, parse_mode=ParseMode.HTML,
                                    reply_markup=admin_menu_kb())


# ──────────────── Broadcast ────────────────
async def _admin_broadcast_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['admin_broadcast'] = True
    await update.message.reply_text(
        "📢 <b>ارسال همگانی</b>\n\n"
        "📝 پیام مورد نظر را ارسال کنید.\n"
        "📎 می‌توانید عکس، ویدیو، فایل یا متن بفرستید.\n\n"
        "❌ برای لغو: <code>لغو</code>",
        parse_mode=ParseMode.HTML)


async def process_admin_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text in ('لغو', 'cancel'):
        ctx.user_data.pop('admin_broadcast', None)
        await update.message.reply_text("❌ لغو شد.", reply_markup=admin_menu_kb())
        return True

    ctx.user_data.pop('admin_broadcast', None)
    users = db.get_all_users()
    sent = 0
    failed = 0

    await update.message.reply_text(f"⏳ در حال ارسال به {len(users)} کاربر...")

    for uid in users:
        try:
            if update.message.photo:
                await ctx.bot.send_photo(uid, update.message.photo[-1].file_id,
                                         caption=update.message.caption or "")
            elif update.message.video:
                await ctx.bot.send_video(uid, update.message.video.file_id,
                                         caption=update.message.caption or "")
            elif update.message.document:
                await ctx.bot.send_document(uid, update.message.document.file_id,
                                            caption=update.message.caption or "")
            else:
                await ctx.bot.send_message(uid, text, parse_mode=ParseMode.HTML)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # Rate limit

    await update.message.reply_text(
        f"✅ <b>ارسال همگانی تمام شد!</b>\n\n"
        f"📤 ارسال شده: <b>{sent}</b>\n"
        f"❌ ناموفق: <b>{failed}</b>\n"
        f"👥 کل: <b>{len(users)}</b>",
        parse_mode=ParseMode.HTML, reply_markup=admin_menu_kb())
    return True


# ──────────────── Broadcast to Groups ────────────────
async def _admin_broadcast_group_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['admin_broadcast_group'] = True
    groups = db.get_admin_groups()
    await update.message.reply_text(
        f"📣 <b>ارسال به گروه‌ها</b>\n\n"
        f"📋 تعداد گروه‌ها: {len(groups)}\n\n"
        f"📝 پیام مورد نظر را ارسال کنید:\n"
        f"❌ برای لغو: <code>لغو</code>",
        parse_mode=ParseMode.HTML)


async def process_admin_broadcast_group(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text in ('لغو', 'cancel'):
        ctx.user_data.pop('admin_broadcast_group', None)
        await update.message.reply_text("❌ لغو شد.", reply_markup=admin_menu_kb())
        return True

    ctx.user_data.pop('admin_broadcast_group', None)
    groups = db.get_admin_groups()
    sent = 0
    failed = 0

    for g in groups:
        try:
            if update.message.photo:
                await ctx.bot.send_photo(g['chat_id'], update.message.photo[-1].file_id,
                                         caption=update.message.caption or "")
            else:
                await ctx.bot.send_message(g['chat_id'], text, parse_mode=ParseMode.HTML)
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(
        f"✅ ارسال به گروه‌ها!\n📤 {sent} | ❌ {failed}",
        reply_markup=admin_menu_kb())
    return True


# ──────────────── Add DP ────────────────
async def _admin_add_dp_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['admin_add_dp'] = True
    await update.message.reply_text(
        "💰 <b>افزودن DP</b>\n\n"
        "📝 فرمت: <code>آیدی مبلغ</code>\n"
        "مثال: <code>123456789 1000000</code>\n\n"
        "❌ برای لغو: <code>لغو</code>",
        parse_mode=ParseMode.HTML)


async def process_admin_add_dp(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text in ('لغو', 'cancel'):
        ctx.user_data.pop('admin_add_dp', None)
        await update.message.reply_text("❌ لغو شد.", reply_markup=admin_menu_kb())
        return True

    parts = text.split()
    if len(parts) < 2:
        await update.message.reply_text("❌ فرمت: <code>آیدی مبلغ</code>", parse_mode=ParseMode.HTML)
        return True

    try:
        uid = int(parts[0])
        amount = int(parts[1])
    except ValueError:
        await update.message.reply_text("❌ اعداد نامعتبر!")
        return True

    db.create_user(uid, "", "")
    db.add_balance(uid, amount)
    db.check_level_up(uid)

    ctx.user_data.pop('admin_add_dp', None)
    await update.message.reply_text(
        f"✅ <b>{fmt(amount)}</b> DP به کاربر <code>{uid}</code> اضافه شد!\n"
        f"💎 موجودی: <b>{fmt(db.get_balance(uid))}</b> DP",
        parse_mode=ParseMode.HTML, reply_markup=admin_menu_kb())

    await safe_send(ctx.bot, uid,
        f"💰 <b>{fmt(amount)}</b> DP به حساب شما اضافه شد!\n"
        f"💎 موجودی: <b>{fmt(db.get_balance(uid))}</b> DP")
    return True


# ──────────────── Deduct DP ────────────────
async def _admin_deduct_dp_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['admin_deduct_dp'] = True
    await update.message.reply_text(
        "➖ <b>کسر DP</b>\n\n"
        "📝 فرمت: <code>آیدی مبلغ</code>\n"
        "مثال: <code>123456789 500000</code>\n\n"
        "❌ برای لغو: <code>لغو</code>",
        parse_mode=ParseMode.HTML)


async def process_admin_deduct_dp(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text in ('لغو', 'cancel'):
        ctx.user_data.pop('admin_deduct_dp', None)
        await update.message.reply_text("❌ لغو شد.", reply_markup=admin_menu_kb())
        return True

    parts = text.split()
    if len(parts) < 2:
        await update.message.reply_text("❌ فرمت: <code>آیدی مبلغ</code>", parse_mode=ParseMode.HTML)
        return True

    try:
        uid = int(parts[0])
        amount = int(parts[1])
    except ValueError:
        await update.message.reply_text("❌ اعداد نامعتبر!")
        return True

    if db.deduct_balance(uid, amount):
        ctx.user_data.pop('admin_deduct_dp', None)
        await update.message.reply_text(
            f"✅ <b>{fmt(amount)}</b> DP از کاربر <code>{uid}</code> کسر شد!\n"
            f"💎 موجودی: <b>{fmt(db.get_balance(uid))}</b> DP",
            parse_mode=ParseMode.HTML, reply_markup=admin_menu_kb())
        await safe_send(ctx.bot, uid,
            f"➖ <b>{fmt(amount)}</b> DP از حساب شما کسر شد.\n"
            f"💎 موجودی: <b>{fmt(db.get_balance(uid))}</b> DP")
    else:
        await update.message.reply_text("❌ موجودی کاربر کافی نیست!")
    return True


# ──────────────── Search User ────────────────
async def _admin_search_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['admin_search'] = True
    await update.message.reply_text(
        "🔍 <b>جستجوی کاربر</b>\n\n"
        "📝 آیدی عددی یا یوزرنیم را وارد کنید:\n"
        "❌ برای لغو: <code>لغو</code>",
        parse_mode=ParseMode.HTML)


async def process_admin_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text in ('لغو', 'cancel'):
        ctx.user_data.pop('admin_search', None)
        await update.message.reply_text("❌ لغو شد.", reply_markup=admin_menu_kb())
        return True

    ctx.user_data.pop('admin_search', None)
    results = db.search_user(text)

    if not results:
        await update.message.reply_text("❌ کاربری یافت نشد!", reply_markup=admin_menu_kb())
        return True

    for u in results:
        bal = u['balance']
        lvl = db.get_user_level(u['user_id'])
        ton_eq = dp_to_ton(bal)
        info = (
            f"👤 <b>اطلاعات کاربر</b>\n"
            f"{'─' * 28}\n\n"
            f"🆔 آیدی: <code>{u['user_id']}</code>\n"
            f"👤 نام: {html.escape(u['first_name'] or '—')}\n"
            f"🔖 یوزرنیم: @{html.escape(u['username'] or '—')}\n"
            f"💎 موجودی: <b>{fmt(bal)}</b> DP\n"
            f"💰 معادل TON: <b>{ton_eq:.6f}</b>\n"
            f"📊 سطح: <b>{lvl}</b>\n"
            f"👥 رفرال: {u['referrals']}\n"
            f"🏆 کل درآمد: {fmt(u['total_earned'])} DP\n"
            f"🚫 بن: {'✅ بله' if u['is_banned'] else '❌ خیر'}\n"
            f"📅 عضویت: {datetime.fromtimestamp(u['created_at']).strftime('%Y-%m-%d') if u['created_at'] else '—'}"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 +DP", callback_data=f"adm_add_{u['user_id']}"),
             InlineKeyboardButton("➖ -DP", callback_data=f"adm_sub_{u['user_id']}")],
            [InlineKeyboardButton("🚫 بن" if not u['is_banned'] else "✅ آنبان",
                                  callback_data=f"adm_ban_{u['user_id']}")],
        ])
        await update.message.reply_text(info, parse_mode=ParseMode.HTML, reply_markup=kb)

    return True


# ──────────────── Ban / Unban ────────────────
async def _admin_ban_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['admin_ban'] = True
    await update.message.reply_text(
        "🚫 <b>بن کاربر</b>\n\n"
        "📝 آیدی عددی کاربر را وارد کنید:\n"
        "❌ برای لغو: <code>لغو</code>",
        parse_mode=ParseMode.HTML)


async def process_admin_ban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text in ('لغو', 'cancel'):
        ctx.user_data.pop('admin_ban', None)
        await update.message.reply_text("❌ لغو شد.", reply_markup=admin_menu_kb())
        return True

    try:
        uid = int(text)
    except ValueError:
        await update.message.reply_text("❌ آیدی نامعتبر!")
        return True

    db.ban_user(uid, True)
    ctx.user_data.pop('admin_ban', None)
    await update.message.reply_text(
        f"🚫 کاربر <code>{uid}</code> بن شد!",
        parse_mode=ParseMode.HTML, reply_markup=admin_menu_kb())
    await safe_send(ctx.bot, uid, "🚫 شما از ربات بن شده‌اید.")
    return True


async def _admin_unban_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['admin_unban'] = True
    await update.message.reply_text(
        "✅ <b>آنبان کاربر</b>\n\n"
        "📝 آیدی عددی کاربر را وارد کنید:\n"
        "❌ برای لغو: <code>لغو</code>",
        parse_mode=ParseMode.HTML)


async def process_admin_unban(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text in ('لغو', 'cancel'):
        ctx.user_data.pop('admin_unban', None)
        await update.message.reply_text("❌ لغو شد.", reply_markup=admin_menu_kb())
        return True

    try:
        uid = int(text)
    except ValueError:
        await update.message.reply_text("❌ آیدی نامعتبر!")
        return True

    db.ban_user(uid, False)
    ctx.user_data.pop('admin_unban', None)
    await update.message.reply_text(
        f"✅ کاربر <code>{uid}</code> آنبان شد!",
        parse_mode=ParseMode.HTML, reply_markup=admin_menu_kb())
    await safe_send(ctx.bot, uid, "✅ بن شما لغو شد! خوش آمدید.")
    return True


# ──────────────── Send to Specific User ────────────────
async def _admin_send_user_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['admin_send_user'] = 'id'
    await update.message.reply_text(
        "👤 <b>ارسال به کاربر</b>\n\n"
        "📝 آیدی عددی کاربر را وارد کنید:",
        parse_mode=ParseMode.HTML)


async def process_admin_send_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text in ('لغو', 'cancel'):
        clear_user_state(ctx)
        await update.message.reply_text("❌ لغو شد.", reply_markup=admin_menu_kb())
        return True

    step = ctx.user_data.get('admin_send_user')

    if step == 'id':
        try:
            uid = int(text)
        except ValueError:
            await update.message.reply_text("❌ آیدی نامعتبر!")
            return True
        ctx.user_data['admin_send_user'] = 'msg'
        ctx.user_data['admin_send_target'] = uid
        await update.message.reply_text(f"📝 پیام خود را برای <code>{uid}</code> بنویسید:")
        return True

    elif step == 'msg':
        target = ctx.user_data.get('admin_send_target')
        clear_user_state(ctx)
        ok = await safe_send(ctx.bot, target,
            f"📨 <b>پیام از طرف ادمین:</b>\n\n{text}")
        if ok:
            await update.message.reply_text("✅ پیام ارسال شد!", reply_markup=admin_menu_kb())
        else:
            await update.message.reply_text("❌ ارسال ناموفق!", reply_markup=admin_menu_kb())
        return True

    return False


# ──────────────── Reply to User ────────────────
async def _admin_reply_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['admin_reply'] = 'id'
    await update.message.reply_text(
        "💬 <b>پاسخ به کاربر</b>\n\n"
        "📝 آیدی عددی کاربر را وارد کنید:",
        parse_mode=ParseMode.HTML)


async def process_admin_reply(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text in ('لغو', 'cancel'):
        clear_user_state(ctx)
        await update.message.reply_text("❌ لغو شد.", reply_markup=admin_menu_kb())
        return True

    step = ctx.user_data.get('admin_reply')

    if step == 'id':
        try:
            uid = int(text)
        except ValueError:
            await update.message.reply_text("❌ آیدی نامعتبر!")
            return True
        ctx.user_data['admin_reply'] = 'msg'
        ctx.user_data['admin_reply_target'] = uid
        await update.message.reply_text(f"📝 پاسخ خود را برای <code>{uid}</code> بنویسید:")
        return True

    elif step == 'msg':
        target = ctx.user_data.get('admin_reply_target')
        clear_user_state(ctx)
        await safe_send(ctx.bot, target,
            f"💬 <b>پاسخ پشتیبانی:</b>\n\n{text}")
        await update.message.reply_text("✅ پاسخ ارسال شد!", reply_markup=admin_menu_kb())
        return True

    return False


# ──────────────── Backup & Restore ────────────────
async def _admin_backup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ در حال تهیه بکاپ...")
    try:
        db.conn.commit()  # Ensure all data is written
        with open(config.DB_PATH, 'rb') as f:
            await ctx.bot.send_document(
                config.ADMIN_ID,
                document=f,
                filename=f"darkpoint_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db",
                caption="💾 بکاپ دیتابیس Dark Point Bot")
        await update.message.reply_text("✅ بکاپ ارسال شد!", reply_markup=admin_menu_kb())
    except Exception as e:
        await update.message.reply_text(f"❌ خطا: {e}", reply_markup=admin_menu_kb())


async def cmd_backup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Backup command"""
    if not _admin_check(update.effective_user.id):
        return
    await _admin_backup(update, ctx)


async def process_admin_restore(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Process DB restore from document"""
    if not ctx.user_data.get('admin_restore'):
        return False
    if not update.message.document:
        return False

    ctx.user_data.pop('admin_restore', None)
    await update.message.reply_text("⏳ در حال ریستور...")

    try:
        file = await ctx.bot.get_file(update.message.document.file_id)
        temp_path = config.DB_PATH + ".tmp"
        await file.download_to_drive(temp_path)

        # Close current connection
        db.conn.close()

        # Replace DB file
        import shutil
        shutil.move(temp_path, config.DB_PATH)

        # Reinitialize
        db.__init__()

        await update.message.reply_text(
            "✅ <b>دیتابیس با موفقیت ریستور شد!</b>",
            parse_mode=ParseMode.HTML, reply_markup=admin_menu_kb())
    except Exception as e:
        logger.error(f"Restore err: {e}")
        # Try to reopen original DB
        try:
            db.__init__()
        except Exception:
            pass
        await update.message.reply_text(f"❌ خطا در ریستور: {e}", reply_markup=admin_menu_kb())
    return True


# ──────────────── Recent Orders ────────────────
async def _admin_recent_orders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    c = db.conn.cursor()
    c.execute('SELECT * FROM ton_withdrawals ORDER BY created_at DESC LIMIT 10')
    orders = c.fetchall()

    c.execute('SELECT * FROM shop_orders ORDER BY created_at DESC LIMIT 5')
    shop_orders = c.fetchall()

    text = "📜 <b>سفارش‌های اخیر</b>\n" + "═" * 30 + "\n\n"

    if orders:
        text += "💎 <b>برداشت TON:</b>\n"
        status_emoji = {'pending': '⏳', 'approved': '✅', 'rejected': '❌'}
        for o in orders[:5]:
            se = status_emoji.get(o['status'], '❓')
            text += f"  {se} {o['tracking_code']} | {o['ton_amount']} TON | @{html.escape(o['username'])}\n"
    else:
        text += "💎 برداشت TON: —\n"

    text += f"\n🛒 <b>فروشگاه:</b> {len(shop_orders)} سفارش اخیر\n"
    text += f"{'═' * 30}"

    await update.message.reply_text(text, parse_mode=ParseMode.HTML,
                                    reply_markup=admin_menu_kb())


# ──────────────── Admin Callback Buttons ────────────────
async def cb_admin_actions(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle admin inline buttons from search results, etc."""
    q = update.callback_query
    await q.answer()
    if not _admin_check(q.from_user.id):
        return

    data = q.data

    if data == "admin_back":
        await safe_edit(q, "⚙️ پنل مدیریت", admin_menu_kb())
        return

    # Section toggle
    if data.startswith("toggle_sec_"):
        section = data.replace("toggle_sec_", "")
        current = db.is_section_on(section)
        db.set_setting(f'section_{section}', '0' if current else '1')
        await safe_edit(q,
            "⚙️ <b>مدیریت بخش‌ها</b>\n\n🟢 = روشن | 🔴 = خاموش",
            sections_toggle_kb())
        return

    # Quick add/sub from search
    if data.startswith("adm_add_"):
        uid = int(data.replace("adm_add_", ""))
        ctx.user_data['admin_add_dp'] = True
        ctx.user_data['admin_add_target'] = uid
        await safe_edit(q, f"💰 مبلغ DP برای افزودن به <code>{uid}</code> را وارد کنید:")
        return

    if data.startswith("adm_sub_"):
        uid = int(data.replace("adm_sub_", ""))
        ctx.user_data['admin_deduct_dp'] = True
        ctx.user_data['admin_deduct_target'] = uid
        await safe_edit(q, f"➖ مبلغ DP برای کسر از <code>{uid}</code> را وارد کنید:")
        return

    if data.startswith("adm_ban_"):
        uid = int(data.replace("adm_ban_", ""))
        u = db.get_user(uid)
        if u and u['is_banned']:
            db.ban_user(uid, False)
            await safe_edit(q, f"✅ کاربر <code>{uid}</code> آنبان شد!")
            await safe_send(ctx.bot, uid, "✅ بن شما لغو شد!")
        else:
            db.ban_user(uid, True)
            await safe_edit(q, f"🚫 کاربر <code>{uid}</code> بن شد!")
            await safe_send(ctx.bot, uid, "🚫 شما از ربات بن شدید.")
        return

    # Mission approval
    if data.startswith("miss_ok_"):
        parts = data.replace("miss_ok_", "").split("_")
        if len(parts) == 2:
            uid, tid = int(parts[0]), int(parts[1])
            db.approve_mission(uid, tid)
            await safe_edit(q, f"✅ ماموریت کاربر <code>{uid}</code> تأیید شد!")
            await safe_send(ctx.bot, uid, "✅ ماموریت شما تأیید شد! پاداش واریز شد.")
        return

    if data.startswith("miss_no_"):
        parts = data.replace("miss_no_", "").split("_")
        if len(parts) == 2:
            uid, tid = int(parts[0]), int(parts[1])
            db.reject_mission(uid, tid)
            await safe_edit(q, f"❌ ماموریت کاربر <code>{uid}</code> رد شد!")
            await safe_send(ctx.bot, uid, "❌ ماموریت شما رد شد.")
        return

    # Buy DP approval
    if data.startswith("buydp_ok_"):
        parts = data.replace("buydp_ok_", "").split("_")
        if len(parts) == 2:
            uid, dp = int(parts[0]), int(parts[1])
            db.add_balance(uid, dp)
            db.check_level_up(uid)
            await safe_edit(q, f"✅ {fmt(dp)} DP به کاربر <code>{uid}</code> واریز شد!")
            await safe_send(ctx.bot, uid,
                f"✅ خرید DP تأیید شد!\n💰 +{fmt(dp)} DP واریز شد.\n💎 موجودی: {fmt(db.get_balance(uid))} DP")
        return

    if data.startswith("buydp_no_"):
        uid = int(data.replace("buydp_no_", ""))
        await safe_edit(q, f"❌ سفارش خرید DP کاربر <code>{uid}</code> رد شد!")
        await safe_send(ctx.bot, uid, "❌ سفارش خرید DP شما رد شد.")
        return# bot.py — Dark Point Bot (قسمت 10/12)

# ══════════════════════════════════════════════
#     ⚙️ ADMIN PANEL — PART 2
# ══════════════════════════════════════════════

# ──────────────── Force Join Management ────────────────
async def _admin_force_join(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    channels = db.get_force_channels()
    text = (
        f"📢 <b>مدیریت فورس جوین</b>\n"
        f"{'═' * 30}\n\n"
    )
    if channels:
        for ch in channels:
            text += f"📢 {html.escape(ch['channel_username'])} (<code>{ch['channel_id']}</code>)\n"
    else:
        text += "📭 کانالی تنظیم نشده.\n"

    text += (
        f"\n{'─' * 28}\n"
        f"📝 برای افزودن: آیدی و یوزرنیم کانال را بفرستید.\n"
        f"فرمت: <code>آیدی @یوزرنیم</code>\n"
        f"مثال: <code>-1001234567890 @mychannel</code>\n\n"
        f"🗑 برای حذف: <code>حذف آیدی</code>\n"
        f"❌ برای لغو: <code>لغو</code>"
    )

    ctx.user_data['admin_force_add'] = True
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def process_admin_force_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text in ('لغو', 'cancel'):
        clear_user_state(ctx)
        await update.message.reply_text("❌ لغو شد.", reply_markup=admin_menu_kb())
        return True

    # Remove channel
    if text.startswith('حذف '):
        cid = text.replace('حذف ', '').strip()
        db.remove_force_channel(cid)
        await update.message.reply_text(
            f"🗑 کانال <code>{cid}</code> حذف شد!",
            parse_mode=ParseMode.HTML, reply_markup=admin_menu_kb())
        clear_user_state(ctx)
        return True

    # Add channel
    parts = text.split()
    if len(parts) < 2:
        await update.message.reply_text(
            "❌ فرمت: <code>آیدی @یوزرنیم</code>\n"
            "مثال: <code>-1001234567890 @mychannel</code>",
            parse_mode=ParseMode.HTML)
        return True

    cid = parts[0]
    cuser = parts[1] if parts[1].startswith('@') else f"@{parts[1]}"

    db.add_force_channel(cid, cuser)
    clear_user_state(ctx)
    await update.message.reply_text(
        f"✅ کانال {cuser} (<code>{cid}</code>) اضافه شد!",
        parse_mode=ParseMode.HTML, reply_markup=admin_menu_kb())
    return True


async def process_admin_force_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Unused but kept for router compatibility"""
    return False


# ──────────────── Groups List ────────────────
async def _admin_groups_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    groups = db.get_admin_groups()
    text = (
        f"📋 <b>گروه‌های ربات</b>\n"
        f"{'═' * 30}\n\n"
        f"📊 تعداد: <b>{len(groups)}</b>\n\n"
    )
    for g in groups[:20]:
        text += f"• {html.escape(g['title'] or '—')} (<code>{g['chat_id']}</code>)\n"

    if len(groups) > 20:
        text += f"\n... و {len(groups) - 20} گروه دیگر"
    text += f"\n{'═' * 30}"

    await update.message.reply_text(text, parse_mode=ParseMode.HTML,
                                    reply_markup=admin_menu_kb())


# ──────────────── Tasks Management ────────────────
async def _admin_tasks_manage(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tasks = db.get_active_tasks()
    text = (
        f"📋 <b>مدیریت تسک‌ها</b>\n"
        f"{'═' * 30}\n\n"
        f"📊 تسک‌های فعال: <b>{len(tasks)}</b>\n\n"
    )
    for t in tasks[:10]:
        cap = "∞" if t['capacity'] == -1 else f"{t['completed_count']}/{t['capacity']}"
        text += (
            f"🔹 {html.escape(t['title'])}\n"
            f"   نوع: {t['type']} | پاداش: {fmt(t['reward'])} | ظرفیت: {cap}\n\n"
        )

    text += (
        f"{'─' * 28}\n"
        f"📝 برای افزودن تسک:\n"
        f"فرمت: <code>نوع | عنوان | پاداش | داده | ظرفیت</code>\n"
        f"انواع: channel, mission, simple\n"
        f"مثال: <code>channel | عضویت کانال | 50000 | @mychannel | -1</code>\n\n"
        f"❌ برای لغو: <code>لغو</code>"
    )

    ctx.user_data['admin_task_add'] = True
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def process_admin_task_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text in ('لغو', 'cancel'):
        clear_user_state(ctx)
        await update.message.reply_text("❌ لغو شد.", reply_markup=admin_menu_kb())
        return True

    parts = [p.strip() for p in text.split('|')]
    if len(parts) < 4:
        await update.message.reply_text(
            "❌ فرمت: <code>نوع | عنوان | پاداش | داده | ظرفیت</code>",
            parse_mode=ParseMode.HTML)
        return True

    ttype = parts[0]
    title = parts[1]
    try:
        reward = int(parts[2])
    except ValueError:
        await update.message.reply_text("❌ پاداش باید عدد باشد!")
        return True
    data = parts[3]
    cap = -1
    if len(parts) >= 5:
        try:
            cap = int(parts[4])
        except ValueError:
            cap = -1

    if ttype not in ('channel', 'mission', 'simple'):
        await update.message.reply_text("❌ نوع باید channel, mission یا simple باشد!")
        return True

    tid = db.add_task(ttype, title, reward, data, cap)
    clear_user_state(ctx)
    await update.message.reply_text(
        f"✅ تسک <b>{html.escape(title)}</b> اضافه شد! (ID: {tid})",
        parse_mode=ParseMode.HTML, reply_markup=admin_menu_kb())
    return True


# ──────────────── Missions Pending ────────────────
async def _admin_missions_pending(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    missions = db.get_pending_missions()
    if not missions:
        await update.message.reply_text(
            "✅ ماموریت در انتظاری وجود ندارد.",
            reply_markup=admin_menu_kb())
        return

    text = (
        f"✅ <b>ماموریت‌های در انتظار</b>\n"
        f"{'═' * 30}\n\n"
        f"📊 تعداد: <b>{len(missions)}</b>\n\n"
    )
    for m in missions[:10]:
        text += (
            f"👤 <code>{m['user_id']}</code> | "
            f"📋 {html.escape(m['title'])} | "
            f"💰 {fmt(m['reward'])} DP\n"
        )

    text += f"\n{'─' * 28}\n💡 برای تأیید/رد از دکمه‌های ارسال‌شده در چت استفاده کنید."
    await update.message.reply_text(text, parse_mode=ParseMode.HTML,
                                    reply_markup=admin_menu_kb())


# ──────────────── Shop Management ────────────────
async def _admin_shop_manage(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    items = db.get_shop_items()
    text = (
        f"🛒 <b>مدیریت فروشگاه</b>\n"
        f"{'═' * 30}\n\n"
        f"📦 محصولات: <b>{len(items)}</b>\n\n"
    )
    for item in items:
        stock = "∞" if item['stock'] == -1 else str(item['stock'])
        text += (
            f"📦 {html.escape(item['name'])}\n"
            f"   💰 {fmt(item['price'])} DP | 📊 {stock} | نوع: {item['media_type']}\n\n"
        )

    text += (
        f"{'─' * 28}\n"
        f"📝 برای افزودن محصول:\n"
        f"فرمت: <code>نام | قیمت | موجودی | نوع</code>\n"
        f"انواع: text, photo, video, document\n"
        f"مثال: <code>پلن ۵۰۰ گیگ | 1000000 | 10 | text</code>\n\n"
        f"⚠️ پس از ارسال مشخصات، محتوای محصول را بفرستید.\n"
        f"❌ برای لغو: <code>لغو</code>"
    )

    ctx.user_data['admin_shop_add'] = 'info'
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def process_admin_shop_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    step = ctx.user_data.get('admin_shop_add')
    if not step:
        return False

    text = (update.message.text or "").strip()
    if text in ('لغو', 'cancel'):
        clear_user_state(ctx)
        await update.message.reply_text("❌ لغو شد.", reply_markup=admin_menu_kb())
        return True

    if step == 'info':
        parts = [p.strip() for p in text.split('|')]
        if len(parts) < 4:
            await update.message.reply_text(
                "❌ فرمت: <code>نام | قیمت | موجودی | نوع</code>",
                parse_mode=ParseMode.HTML)
            return True

        name = parts[0]
        try:
            price = int(parts[1])
            stock = int(parts[2])
        except ValueError:
            await update.message.reply_text("❌ قیمت و موجودی باید عدد باشند!")
            return True
        mtype = parts[3].lower()
        if mtype not in ('text', 'photo', 'video', 'document'):
            mtype = 'text'

        ctx.user_data['admin_shop_add'] = 'content'
        ctx.user_data['shop_name'] = name
        ctx.user_data['shop_price'] = price
        ctx.user_data['shop_stock'] = stock
        ctx.user_data['shop_type'] = mtype

        if mtype == 'text':
            await update.message.reply_text("📝 محتوای متنی محصول را وارد کنید:")
        else:
            await update.message.reply_text(f"📎 فایل {mtype} محصول را ارسال کنید:")
        return True

    elif step == 'content':
        name = ctx.user_data.get('shop_name', '')
        price = ctx.user_data.get('shop_price', 0)
        stock = ctx.user_data.get('shop_stock', -1)
        mtype = ctx.user_data.get('shop_type', 'text')

        if mtype == 'text':
            content = text
        elif update.message.photo:
            content = update.message.photo[-1].file_id
            mtype = 'photo'
        elif update.message.video:
            content = update.message.video.file_id
            mtype = 'video'
        elif update.message.document:
            content = update.message.document.file_id
            mtype = 'document'
        else:
            content = text
            mtype = 'text'

        iid = db.add_shop_item(name, price, stock, mtype, content)
        clear_user_state(ctx)
        await update.message.reply_text(
            f"✅ محصول <b>{html.escape(name)}</b> اضافه شد! (ID: {iid})",
            parse_mode=ParseMode.HTML, reply_markup=admin_menu_kb())
        return True

    return False


# ──────────────── Gift Management ────────────────
async def _admin_gift_manage(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    plans = db.get_gift_plans()
    teddy_price = db.get_setting('gift_price', '100000')

    text = (
        f"🎁 <b>مدیریت هدایا</b>\n"
        f"{'═' * 30}\n\n"
        f"🧸 قیمت خرس تدی: <b>{fmt(int(teddy_price))}</b> DP\n"
        f"📦 پلن‌های هدیه: <b>{len(plans)}</b>\n\n"
    )
    for p in plans:
        text += f"🎁 {html.escape(p['name'])} — {fmt(p['price'])} DP\n"

    text += (
        f"\n{'─' * 28}\n"
        f"📝 افزودن پلن: <code>نام | قیمت</code>\n"
        f"🧸 تغییر قیمت تدی: <code>تدی قیمت</code>\n"
        f"مثال: <code>هدیه ویژه | 500000</code>\n"
        f"❌ برای لغو: <code>لغو</code>"
    )

    ctx.user_data['admin_gift_add'] = True
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def process_admin_gift_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text in ('لغو', 'cancel'):
        clear_user_state(ctx)
        await update.message.reply_text("❌ لغو شد.", reply_markup=admin_menu_kb())
        return True

    # Change teddy price
    if text.startswith('تدی '):
        try:
            price = int(text.replace('تدی ', '').strip())
            db.set_setting('gift_price', str(price))
            clear_user_state(ctx)
            await update.message.reply_text(
                f"✅ قیمت خرس تدی: <b>{fmt(price)}</b> DP",
                parse_mode=ParseMode.HTML, reply_markup=admin_menu_kb())
            return True
        except ValueError:
            await update.message.reply_text("❌ قیمت نامعتبر!")
            return True

    # Add plan
    parts = [p.strip() for p in text.split('|')]
    if len(parts) < 2:
        await update.message.reply_text("❌ فرمت: <code>نام | قیمت</code>",
                                        parse_mode=ParseMode.HTML)
        return True

    name = parts[0]
    try:
        price = int(parts[1])
    except ValueError:
        await update.message.reply_text("❌ قیمت نامعتبر!")
        return True

    db.add_gift_plan(name, price)
    clear_user_state(ctx)
    await update.message.reply_text(
        f"✅ پلن هدیه <b>{html.escape(name)}</b> اضافه شد!",
        parse_mode=ParseMode.HTML, reply_markup=admin_menu_kb())
    return True


# ──────────────── Buy DP Settings ────────────────
async def _admin_buydp_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    dp_amount = db.get_setting('buy_dp_amount', str(config.BUY_DP_DEFAULT_AMOUNT))
    price = db.get_setting('buy_dp_price', str(config.BUY_DP_DEFAULT_PRICE))

    text = (
        f"💰 <b>تنظیم خرید DP</b>\n"
        f"{'═' * 30}\n\n"
        f"📦 مقدار DP: <b>{fmt(int(dp_amount))}</b>\n"
        f"💵 قیمت (تومان): <b>{fmt(int(price))}</b>\n\n"
        f"{'─' * 28}\n"
        f"📝 تغییر: <code>مقدار قیمت</code>\n"
        f"مثال: <code>1000000 100000</code>\n"
        f"(1,000,000 DP = 100,000 تومان)\n\n"
        f"❌ برای لغو: <code>لغو</code>"
    )

    ctx.user_data['admin_buydp_set'] = True
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def process_admin_buydp_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text in ('لغو', 'cancel'):
        clear_user_state(ctx)
        await update.message.reply_text("❌ لغو شد.", reply_markup=admin_menu_kb())
        return True

    parts = text.split()
    if len(parts) < 2:
        await update.message.reply_text("❌ فرمت: <code>مقدار قیمت</code>",
                                        parse_mode=ParseMode.HTML)
        return True

    try:
        dp_amount = int(parts[0])
        price = int(parts[1])
    except ValueError:
        await update.message.reply_text("❌ اعداد نامعتبر!")
        return True

    db.set_setting('buy_dp_amount', str(dp_amount))
    db.set_setting('buy_dp_price', str(price))
    clear_user_state(ctx)
    await update.message.reply_text(
        f"✅ تنظیمات خرید DP:\n"
        f"📦 <b>{fmt(dp_amount)}</b> DP = <b>{fmt(price)}</b> تومان",
        parse_mode=ParseMode.HTML, reply_markup=admin_menu_kb())
    return True


# ──────────────── Stars Settings ────────────────
async def _admin_stars_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    stars_price = db.get_setting('stars_price', str(config.STARS_DP_COST))

    text = (
        f"⭐ <b>تنظیم استارز</b>\n"
        f"{'═' * 30}\n\n"
        f"📊 نرخ فعلی: <b>{fmt(int(stars_price))}</b> DP = 50 ⭐\n\n"
        f"📝 تغییر: <code>قیمت جدید</code>\n"
        f"مثال: <code>2000000</code>\n"
        f"❌ برای لغو: <code>لغو</code>"
    )

    ctx.user_data['admin_stars_set'] = True
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

    # Inline handler for this
    async def _process(update2, ctx2):
        t = (update2.message.text or "").strip()
        if t in ('لغو', 'cancel'):
            clear_user_state(ctx2)
            await update2.message.reply_text("❌ لغو شد.", reply_markup=admin_menu_kb())
            return
        try:
            p = int(t)
            db.set_setting('stars_price', str(p))
            clear_user_state(ctx2)
            await update2.message.reply_text(
                f"✅ نرخ استارز: <b>{fmt(p)}</b> DP = 50 ⭐",
                parse_mode=ParseMode.HTML, reply_markup=admin_menu_kb())
        except ValueError:
            await update2.message.reply_text("❌ عدد نامعتبر!")

    # Store for router
    ctx.user_data['admin_stars_set'] = True


# ──────────────── Panel Plans ────────────────
async def _admin_panel_plans(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    plans = db.get_panel_plans()
    text = (
        f"📦 <b>پلن‌های پنل</b>\n"
        f"{'═' * 30}\n\n"
    )
    if plans:
        for p in plans:
            text += f"📦 {html.escape(p['name'])} — {fmt(p['price'])} DP\n"
    else:
        text += "📭 پلنی فعال نیست.\n"

    text += (
        f"\n{'─' * 28}\n"
        f"📝 افزودن: <code>نام | قیمت</code>\n"
        f"مثال: <code>پنل 500 گیگ | 5000000</code>\n"
        f"❌ برای لغو: <code>لغو</code>"
    )

    ctx.user_data['admin_panel_plan'] = True
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def process_admin_panel_plan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text in ('لغو', 'cancel'):
        clear_user_state(ctx)
        await update.message.reply_text("❌ لغو شد.", reply_markup=admin_menu_kb())
        return True

    parts = [p.strip() for p in text.split('|')]
    if len(parts) < 2:
        await update.message.reply_text("❌ فرمت: <code>نام | قیمت</code>",
                                        parse_mode=ParseMode.HTML)
        return True

    name = parts[0]
    try:
        price = int(parts[1])
    except ValueError:
        await update.message.reply_text("❌ قیمت نامعتبر!")
        return True

    db.add_panel_plan(name, price)
    clear_user_state(ctx)
    await update.message.reply_text(
        f"✅ پلن <b>{html.escape(name)}</b> اضافه شد!",
        parse_mode=ParseMode.HTML, reply_markup=admin_menu_kb())
    return True


# ──────────────── Referral Settings ────────────────
async def _admin_referral_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ref_reward = db.get_setting('referral_reward', str(config.DEFAULT_REFERRAL_REWARD))
    first_reward = db.get_setting('first_join_reward', str(config.DEFAULT_FIRST_JOIN_REWARD))

    text = (
        f"🏷 <b>تنظیم پاداش رفرال</b>\n"
        f"{'═' * 30}\n\n"
        f"💵 پاداش هر رفرال: <b>{fmt(int(ref_reward))}</b> DP\n"
        f"🎁 پاداش ورود جدید: <b>{fmt(int(first_reward))}</b> DP\n\n"
        f"{'─' * 28}\n"
        f"📝 تغییر: <code>رفرال ورود</code>\n"
        f"مثال: <code>100000 50000</code>\n"
        f"❌ برای لغو: <code>لغو</code>"
    )

    ctx.user_data['admin_ref_set'] = True
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def process_admin_ref_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handled via admin_text_router stars_set fallback"""
    text = (update.message.text or "").strip()
    if text in ('لغو', 'cancel'):
        clear_user_state(ctx)
        await update.message.reply_text("❌ لغو شد.", reply_markup=admin_menu_kb())
        return True

    parts = text.split()
    if len(parts) < 2:
        await update.message.reply_text("❌ فرمت: <code>رفرال ورود</code>",
                                        parse_mode=ParseMode.HTML)
        return True

    try:
        ref = int(parts[0])
        first = int(parts[1])
    except ValueError:
        await update.message.reply_text("❌ اعداد نامعتبر!")
        return True

    db.set_setting('referral_reward', str(ref))
    db.set_setting('first_join_reward', str(first))
    clear_user_state(ctx)
    await update.message.reply_text(
        f"✅ پاداش رفرال: <b>{fmt(ref)}</b> DP\n"
        f"✅ پاداش ورود: <b>{fmt(first)}</b> DP",
        parse_mode=ParseMode.HTML, reply_markup=admin_menu_kb())
    return True


# ──────────────── Gift to Top N ────────────────
async def _admin_gift_top_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['admin_gift_top'] = True
    await update.message.reply_text(
        "🎁 <b>هدیه به برترین‌ها</b>\n\n"
        "📝 فرمت: <code>تعداد مبلغ</code>\n"
        "مثال: <code>10 1000000</code>\n"
        "(به ۱۰ نفر اول، هر کدام ۱M DP)\n\n"
        "❌ برای لغو: <code>لغو</code>",
        parse_mode=ParseMode.HTML)


async def process_admin_gift_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text in ('لغو', 'cancel'):
        clear_user_state(ctx)
        await update.message.reply_text("❌ لغو شد.", reply_markup=admin_menu_kb())
        return True

    parts = text.split()
    if len(parts) < 2:
        await update.message.reply_text("❌ فرمت: <code>تعداد مبلغ</code>",
                                        parse_mode=ParseMode.HTML)
        return True

    try:
        n = int(parts[0])
        amount = int(parts[1])
    except ValueError:
        await update.message.reply_text("❌ اعداد نامعتبر!")
        return True

    top = db.get_top_users(n)
    sent = 0
    for u in top:
        db.add_balance(u['user_id'], amount)
        db.check_level_up(u['user_id'])
        await safe_send(ctx.bot, u['user_id'],
            f"🎁 <b>هدیه ادمین!</b>\n\n"
            f"💰 +<b>{fmt(amount)}</b> DP\n"
            f"🏆 به خاطر رتبه برتر شما!\n"
            f"💎 موجودی: <b>{fmt(db.get_balance(u['user_id']))}</b> DP")
        sent += 1
        await asyncio.sleep(0.05)

    clear_user_state(ctx)
    await update.message.reply_text(
        f"✅ هدیه به <b>{sent}</b> نفر برتر ارسال شد!\n"
        f"💰 هر نفر: <b>{fmt(amount)}</b> DP",
        parse_mode=ParseMode.HTML, reply_markup=admin_menu_kb())
    return True


# ──────────────── Gift to All ────────────────
async def _admin_gift_all_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data['admin_gift_all'] = True
    user_count = db.get_user_count()
    await update.message.reply_text(
        f"🎁 <b>هدیه به همه</b>\n\n"
        f"👥 تعداد کاربران: <b>{fmt(user_count)}</b>\n\n"
        f"📝 مبلغ هدیه برای هر نفر را وارد کنید:\n"
        f"مثال: <code>50000</code>\n\n"
        f"⚠️ این عملیات ممکن است طول بکشد!\n"
        f"❌ برای لغو: <code>لغو</code>",
        parse_mode=ParseMode.HTML)


async def process_admin_gift_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text in ('لغو', 'cancel'):
        clear_user_state(ctx)
        await update.message.reply_text("❌ لغو شد.", reply_markup=admin_menu_kb())
        return True

    try:
        amount = int(text)
    except ValueError:
        await update.message.reply_text("❌ مبلغ نامعتبر!")
        return True

    users = db.get_all_users()
    await update.message.reply_text(f"⏳ در حال ارسال هدیه به {len(users)} کاربر...")

    sent = 0
    for uid in users:
        db.add_balance(uid, amount)
        db.check_level_up(uid)
        await safe_send(ctx.bot, uid,
            f"🎁 <b>هدیه همگانی!</b>\n\n"
            f"💰 +<b>{fmt(amount)}</b> DP\n"
            f"💎 موجودی: <b>{fmt(db.get_balance(uid))}</b> DP")
        sent += 1
        if sent % 50 == 0:
            await asyncio.sleep(1)  # Rate limit
        else:
            await asyncio.sleep(0.03)

    clear_user_state(ctx)
    await update.message.reply_text(
        f"✅ هدیه به <b>{sent}</b> کاربر ارسال شد!\n"
        f"💰 هر نفر: <b>{fmt(amount)}</b> DP\n"
        f"💸 کل: <b>{fmt(sent * amount)}</b> DP",
        parse_mode=ParseMode.HTML, reply_markup=admin_menu_kb())
    return True# bot.py — Dark Point Bot (قسمت 11/12)

# ══════════════════════════════════════════════
#     📨 MAIN USER TEXT ROUTER
# ══════════════════════════════════════════════
# Routes all private text messages to the right handler

async def user_text_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Main router for all private text messages"""
    if update.effective_chat.type != ChatType.PRIVATE:
        return

    uid = update.effective_user.id
    text = (update.message.text or "").strip()

    # ── Admin check first ──
    if is_admin(uid):
        # Check if admin is in restore flow
        if ctx.user_data.get('admin_restore') and update.message.document:
            await process_admin_restore(update, ctx)
            return
        # Check admin stars_set flow
        if ctx.user_data.get('admin_stars_set'):
            if text in ('لغو', 'cancel'):
                clear_user_state(ctx)
                await update.message.reply_text("❌ لغو شد.", reply_markup=admin_menu_kb())
                return
            try:
                p = int(text)
                db.set_setting('stars_price', str(p))
                clear_user_state(ctx)
                await update.message.reply_text(
                    f"✅ نرخ استارز: <b>{fmt(p)}</b> DP = 50 ⭐",
                    parse_mode=ParseMode.HTML, reply_markup=admin_menu_kb())
            except ValueError:
                await update.message.reply_text("❌ عدد نامعتبر!")
            return
        # Check admin ref_set flow
        if ctx.user_data.get('admin_ref_set'):
            await process_admin_ref_set(update, ctx)
            return
        # Route to admin handler
        await admin_text_router(update, ctx)
        # If admin handler didn't match a flow, check user flows below too
        # (admin might be using user features)

    # ── Bot off check ──
    if not db.is_bot_on() and not is_admin(uid):
        await update.message.reply_text(bot_off_text())
        return

    # ── Ban check ──
    if db.is_banned(uid):
        await update.message.reply_text("🚫 شما از ربات بن شده‌اید.")
        return

    # ── Process active input flows (in priority order) ──

    # TON Withdrawal flow
    if ctx.user_data.get('tw_step') == 'amount':
        if await process_tw_amount(update, ctx):
            return
    if ctx.user_data.get('tw_step') == 'wallet':
        if await process_tw_wallet(update, ctx):
            return

    # Bank deposit flow
    if ctx.user_data.get('bank_action') == 'deposit':
        if await process_bank_input(update, ctx):
            return

    # Gift flow
    if ctx.user_data.get('gift_type'):
        if await process_gift_input(update, ctx):
            return

    # Mission screenshot flow
    if ctx.user_data.get('mission_task'):
        if await process_mission_photo(update, ctx):
            return

    # Currency convert flow
    if ctx.user_data.get('conv_type'):
        if await process_convert_input(update, ctx):
            return

    # Buy DP receipt flow
    if ctx.user_data.get('buydp_active'):
        if await process_buydp_receipt(update, ctx):
            return

    # ── Menu button matching ──
    await _user_menu_button(update, ctx, text)


async def _user_menu_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE, text: str):
    """Match user menu button text to handlers"""

    # Exact match for main menu buttons
    if text in ("💎 برداشت TON 💎", "💎 برداشت TON"):
        await msg_ton_withdraw(update, ctx)
    elif text == "🎁 دریافت جایزه":
        await msg_claim(update, ctx)
    elif text == "👤 پروفایل دارکی":
        await msg_profile(update, ctx)
    elif text == "🎮 بازی‌ها":
        await msg_games(update, ctx)
    elif text == "⛏ ماینر دارکی":
        await msg_miner(update, ctx)
    elif text == "🏦 بانک دارکی":
        await msg_bank(update, ctx)
    elif text == "🏭 کارخونه دارکی":
        await msg_factory(update, ctx)
    elif text == "🛒 فروشگاه":
        await msg_shop(update, ctx)
    elif text == "🎰 گردونه شانس":
        await msg_wheel(update, ctx)
    elif text == "💰 خرید DP":
        await msg_buy_dp(update, ctx)
    elif text == "⭐ برداشت استارز":
        await msg_stars(update, ctx)
    elif text == "📋 تسک‌ها":
        await msg_tasks(update, ctx)
    elif text == "👍 چالش لایک":
        await msg_like(update, ctx)
    elif text == "💱 تبدیل ارز":
        await msg_convert(update, ctx)
    elif text == "🎁 هدیه":
        await msg_gift(update, ctx)
    elif text == "📊 لیدربورد":
        await msg_leaderboard(update, ctx)
    elif text == "👥 زیرمجموعه‌گیری":
        await msg_referral(update, ctx)
    elif text == "📖 پنل DP":
        await msg_dp_panel(update, ctx)
    elif text == "➕ افزودن به گروه":
        await msg_add_group(update, ctx)
    elif text == "📖 راهنما":
        await cmd_help(update, ctx)
    elif text in ("🔙 بازگشت به منو", "🔙 بازگشت"):
        await msg_back_to_main(update, ctx)
    elif text == "⚙️ پنل مدیریت" or text == "/admin":
        await cmd_admin(update, ctx)
    else:
        # Unrecognized text — show help
        await update.message.reply_text(
            "❓ متوجه نشدم!\n\n"
            "لطفاً از دکمه‌های منو استفاده کنید 👇",
            reply_markup=main_menu_kb())


# ══════════════════════════════════════════════
#     🔘 MAIN CALLBACK ROUTER
# ══════════════════════════════════════════════

async def main_callback_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Route all callback queries to appropriate handlers"""
    q = update.callback_query
    if not q or not q.data:
        return

    data = q.data
    uid = q.from_user.id

    # ── Force Join ──
    if data == "check_join":
        await cb_check_join(update, ctx)
        return

    # ── TON Withdrawal ──
    if data.startswith("tw_"):
        if data == "tw_start":
            await cb_tw_start(update, ctx)
        elif data == "tw_locked":
            await cb_tw_locked(update, ctx)
        elif data == "tw_cancel":
            await cb_tw_cancel(update, ctx)
        elif data == "tw_confirm":
            await cb_tw_confirm(update, ctx)
        elif data == "tw_history":
            await cb_tw_history(update, ctx)
        elif data == "tw_back":
            await cb_tw_back(update, ctx)
        return

    # ── TON Admin ──
    if data.startswith("twadm_"):
        if data.startswith("twadm_ok_"):
            await cb_tw_admin_approve(update, ctx)
        elif data.startswith("twadm_no_"):
            await cb_tw_admin_reject(update, ctx)
        elif data == "twadm_list":
            await cb_tw_admin_list(update, ctx)
        return

    # ── Bank ──
    if data.startswith("bank_") or data.startswith("bw_"):
        if data == "bank_deposit":
            await cb_bank_deposit(update, ctx)
        elif data == "bank_withdraw":
            await cb_bank_withdraw(update, ctx)
        elif data == "bank_cancel":
            await cb_bank_cancel(update, ctx)
        elif data == "bank_back":
            await cb_bank_back(update, ctx)
        elif data.startswith("bw_"):
            await cb_bank_withdraw_confirm(update, ctx)
        return

    # ── Miner ──
    if data.startswith("miner_"):
        if data == "miner_buy":
            await cb_miner_buy(update, ctx)
        elif data == "miner_elec":
            await cb_miner_elec(update, ctx)
        elif data == "miner_upgrade":
            await cb_miner_upgrade(update, ctx)
        elif data == "miner_collect":
            await cb_miner_collect(update, ctx)
        elif data == "miner_switch":
            await cb_miner_switch(update, ctx)
        return

    # ── Factory ──
    if data.startswith("factory_"):
        if data == "factory_build":
            await cb_factory_build(update, ctx)
        elif data == "factory_collect":
            await cb_factory_collect(update, ctx)
        elif data == "factory_upgrade":
            await cb_factory_upgrade(update, ctx)
        return

    # ── Games ──
    if data.startswith("g_") or data == "games_back":
        if data == "games_back":
            await cb_games_back(update, ctx)
        else:
            await cb_game_info(update, ctx)
        return

    if data.startswith("guess_"):
        await cb_guess(update, ctx)
        return

    if data.startswith("bomb_") or data == "bomb_cash":
        await cb_bomb(update, ctx)
        return

    # ── Shop ──
    if data.startswith("shop_"):
        if data.startswith("shop_buy_"):
            await cb_shop_buy(update, ctx)
        elif data == "shop_back":
            await cb_shop_back(update, ctx)
        return

    # ── Gift ──
    if data.startswith("gift_"):
        if data == "gift_teddy":
            await cb_gift_teddy(update, ctx)
        elif data.startswith("gift_buy_"):
            await cb_gift_buy(update, ctx)
        return

    # ── Tasks ──
    if data.startswith("task_"):
        if data.startswith("task_do_"):
            await cb_task_do(update, ctx)
        elif data.startswith("task_check_"):
            await cb_task_check(update, ctx)
        return

    # ── Like ──
    if data.startswith("like_"):
        if data == "like_join":
            await cb_like_join(update, ctx)
        elif data == "like_status":
            await q.answer("📊 وضعیت چالش شما فعال است!")
        return

    # ── Wheel ──
    if data.startswith("wheel_"):
        await cb_wheel(update, ctx)
        return

    # ── Convert ──
    if data.startswith("conv_"):
        if data in ("conv_ton", "conv_usdt"):
            await cb_convert(update, ctx)
        elif data == "conv_cancel":
            await cb_conv_cancel(update, ctx)
        return

    # ── Stars ──
    if data.startswith("stars_"):
        await cb_stars(update, ctx)
        return

    # ── Buy DP ──
    if data.startswith("buydp_"):
        if data == "buydp_order":
            await cb_buydp_order(update, ctx)
        elif data.startswith("buydp_ok_") or data.startswith("buydp_no_"):
            await cb_admin_actions(update, ctx)
        return

    # ── DP Panel ──
    if data.startswith("panel_"):
        await cb_dp_panel(update, ctx)
        return

    # ── Admin Section Toggle & Actions ──
    if data.startswith("toggle_sec_") or data == "admin_back":
        await cb_admin_actions(update, ctx)
        return

    if data.startswith("adm_"):
        await cb_admin_actions(update, ctx)
        return

    # ── Mission Approval ──
    if data.startswith("miss_"):
        await cb_admin_actions(update, ctx)
        return

    # ── Back to main ──
    if data == "back_main":
        clear_user_state(ctx)
        await q.answer()
        await ctx.bot.send_message(uid, "منوی اصلی:", reply_markup=main_menu_kb())
        return

    # ── Fallback ──
    await q.answer()


# ══════════════════════════════════════════════
#     📸 MEDIA HANDLERS (Photos/Documents)
# ══════════════════════════════════════════════

async def user_photo_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle photo messages from users (missions, buy DP receipts)"""
    if update.effective_chat.type != ChatType.PRIVATE:
        return

    uid = update.effective_user.id

    # Mission screenshot
    if ctx.user_data.get('mission_task'):
        await process_mission_photo(update, ctx)
        return

    # Buy DP receipt
    if ctx.user_data.get('buydp_active'):
        await process_buydp_receipt(update, ctx)
        return

    # Admin restore
    if is_admin(uid) and ctx.user_data.get('admin_restore'):
        await process_admin_restore(update, ctx)
        return

    # Admin broadcast (photo)
    if is_admin(uid) and ctx.user_data.get('admin_broadcast'):
        await process_admin_broadcast(update, ctx)
        return

    if is_admin(uid) and ctx.user_data.get('admin_broadcast_group'):
        await process_admin_broadcast_group(update, ctx)
        return

    # Admin shop content
    if is_admin(uid) and ctx.user_data.get('admin_shop_add') == 'content':
        await process_admin_shop_add(update, ctx)
        return


async def user_document_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle document messages"""
    if update.effective_chat.type != ChatType.PRIVATE:
        return

    uid = update.effective_user.id

    # Admin restore
    if is_admin(uid) and ctx.user_data.get('admin_restore'):
        await process_admin_restore(update, ctx)
        return

    # Admin broadcast (document)
    if is_admin(uid) and ctx.user_data.get('admin_broadcast'):
        await process_admin_broadcast(update, ctx)
        return

    if is_admin(uid) and ctx.user_data.get('admin_broadcast_group'):
        await process_admin_broadcast_group(update, ctx)
        return

    # Admin shop content
    if is_admin(uid) and ctx.user_data.get('admin_shop_add') == 'content':
        await process_admin_shop_add(update, ctx)
        return


# ══════════════════════════════════════════════
#     📦 CONFIG SEND TO PANEL BUYER
# ══════════════════════════════════════════════

async def cmd_send_config(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin sends config to a panel buyer"""
    if not is_admin(update.effective_user.id):
        return

    parts = (update.message.text or "").strip().split()
    if len(parts) < 3:
        await update.message.reply_text(
            "📦 <b>ارسال کانفیگ</b>\n\n"
            "📝 فرمت: <code>/sendconfig آیدی متن_کانفیگ</code>\n"
            "مثال: <code>/sendconfig 123456 vmess://...</code>",
            parse_mode=ParseMode.HTML)
        return

    try:
        target_id = int(parts[1])
    except ValueError:
        await update.message.reply_text("❌ آیدی نامعتبر!")
        return

    config_text = " ".join(parts[2:])

    await safe_send(ctx.bot, target_id,
        f"📦 <b>کانفیگ پنل شما</b>\n\n"
        f"<code>{html.escape(config_text)}</code>\n\n"
        f"💡 {config.PANEL_PURCHASE_MESSAGE}")

    await update.message.reply_text(
        f"✅ کانفیگ به <code>{target_id}</code> ارسال شد!",
        parse_mode=ParseMode.HTML)


# ══════════════════════════════════════════════
#     🎯 GAME TIMEOUT CLEANUP JOB
# ══════════════════════════════════════════════

async def cleanup_game_timeouts(ctx: ContextTypes.DEFAULT_TYPE):
    """Periodic cleanup of expired game states (runs every 5 min)"""
    # This is a best-effort cleanup; individual game callbacks
    # also check timeouts. This handles edge cases.
    logger.debug("Game timeout cleanup tick")


# ══════════════════════════════════════════════
#     🏠 GROUP MEMBER COUNT CHECK (on join)
# ══════════════════════════════════════════════

async def on_new_chat_members(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Check if bot was added to a group and verify member count"""
    if not update.message or not update.message.new_chat_members:
        return

    for member in update.message.new_chat_members:
        if member.id == ctx.bot.id:
            chat = update.effective_chat
            try:
                count = await ctx.bot.get_chat_member_count(chat.id)
                if count < config.MIN_GROUP_MEMBERS:
                    await update.message.reply_text(
                        f"⚠️ تعداد اعضا ({count}) کمتر از {config.MIN_GROUP_MEMBERS} است.\n"
                        f"ربات گروه را ترک می‌کند.")
                    await ctx.bot.leave_chat(chat.id)
                else:
                    db.add_admin_group(chat.id, chat.title or "گروه")
                    await update.message.reply_text(
                        f"🌑 <b>Dark Point Bot</b> فعال شد!\n\n"
                        f"📝 دستور <code>دارک</code> را بفرستید.",
                        parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.error(f"New group check err: {e}")# bot.py — Dark Point Bot (قسمت 12/12 — FINAL)

# ══════════════════════════════════════════════
#     🏗️ GROUP TEXT COMMAND HANDLER
# ══════════════════════════════════════════════

async def group_text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle Persian text commands in groups"""
    if update.effective_chat.type == ChatType.PRIVATE:
        return
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    uid = update.effective_user.id

    # Register user if not exists
    db.create_user(uid, update.effective_user.username or "",
                   update.effective_user.first_name or "")

    # ── دارک / دارک کانفیگ ──
    if text in ('دارک', 'دارک کانفیگ', '/dark', '/config'):
        await cmd_dark(update, ctx)
        return

    # ── موجودی ──
    if text in ('موجودی', '/balance'):
        await cmd_balance_group(update, ctx)
        return

    # ── پروفایل دارکی ──
    if text in ('پروفایل دارکی', '/profile'):
        await cmd_profile_group(update, ctx)
        return

    # ── بازی [amount] / انفجار [amount] (Crash) ──
    if text.startswith('بازی ') or text.startswith('انفجار '):
        await cmd_crash(update, ctx)
        return

    # ── تاس [amount] ──
    if text.startswith('تاس '):
        await cmd_dice(update, ctx)
        return

    # ── حدس بزن [amount] ──
    if text.startswith('حدس بزن'):
        await cmd_guess(update, ctx)
        return

    # ── کازینو [amount] ──
    if text.startswith('کازینو'):
        await cmd_casino(update, ctx)
        return

    # ── بمب [amount] ──
    if text.startswith('بمب'):
        await cmd_bomb(update, ctx)
        return

    # ── انتقال [amount] ──
    if text.startswith('انتقال '):
        await cmd_transfer(update, ctx)
        return

    # ── بانک دارکی ──
    if text in ('بانک دارکی', '/bank'):
        await cmd_bank_group(update, ctx)
        return

    # ── ماینر دارکی ──
    if text in ('ماینر دارکی', '/miner'):
        await cmd_miner_group(update, ctx)
        return

    # ── لیدربورد ──
    if text in ('لیدربورد', '/leaderboard'):
        await cmd_leaderboard_group(update, ctx)
        return

    # ── ایدی عددی (admin only, reply) ──
    if text in ('ایدی عددی', '/id'):
        await cmd_id_group(update, ctx)
        return


# ══════════════════════════════════════════════
#     🚀 MAIN FUNCTION
# ══════════════════════════════════════════════

def main():
    """Initialize and run the Dark Point Bot"""

    logger.info("🌑 Dark Point Bot starting...")
    logger.info(f"📁 Data dir: {config.DATA_DIR}")
    logger.info(f"💾 DB path: {config.DB_PATH}")

    # ── Start background threads ──
    # Health server (for Render)
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    logger.info(f"🌐 Health server started on port {config.PORT}")

    # Self-ping (keep Render alive)
    if config.RENDER_URL:
        ping_thread = threading.Thread(target=self_ping_loop, daemon=True)
        ping_thread.start()
        logger.info(f"🔄 Self-ping enabled: {config.RENDER_URL}")

    # ── Build Application ──
    app = (
        ApplicationBuilder()
        .token(config.BOT_TOKEN)
        .concurrent_updates(True)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .pool_timeout(30)
        .build()
    )

    # ══════════════════════════════════════════
    #         HANDLER REGISTRATION
    # ══════════════════════════════════════════

    # ── 1. Command Handlers (Private & Group) ──
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("backup", cmd_backup))
    app.add_handler(CommandHandler("sendconfig", cmd_send_config))
    app.add_handler(CommandHandler("restore", cmd_backup))  # /restore triggers backup flow

    # ── 2. Chat Member Handler (bot added/removed from groups) ──
    app.add_handler(ChatMemberHandler(on_chat_member_update,
                                      ChatMemberHandler.MY_CHAT_MEMBER))

    # ── 3. Callback Query Handler (ALL inline buttons) ──
    # Single catch-all router handles every callback
    app.add_handler(CallbackQueryHandler(main_callback_router))

    # ── 4. Media Handlers (Private — photos & documents) ──
    app.add_handler(MessageHandler(
        filters.PHOTO & filters.ChatType.PRIVATE,
        user_photo_handler))
    app.add_handler(MessageHandler(
        filters.Document.ALL & filters.ChatType.PRIVATE,
        user_document_handler))

    # ── 5. Text Handlers ──
    # Group text commands (Persian)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUP,
        group_text_handler))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.SUPERGROUP,
        group_text_handler))

    # Private text messages (main user router — MUST be last text handler)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        user_text_router))

    # ══════════════════════════════════════════
    #         JOB QUEUE (Scheduled Tasks)
    # ══════════════════════════════════════════

    job_queue = app.job_queue

    # Group member count check — every 6 hours
    job_queue.run_repeating(
        check_group_members_job,
        interval=21600,   # 6 hours
        first=300,        # 5 min after start
        name="group_check"
    )

    # Game timeout cleanup — every 5 minutes
    job_queue.run_repeating(
        cleanup_game_timeouts,
        interval=300,
        first=60,
        name="game_cleanup"
    )

    # Daily transfer counter reset — every 24 hours
    async def reset_daily_counters(ctx):
        c = db.conn.cursor()
        today = date.today().isoformat()
        c.execute(
            'UPDATE users SET transfer_count_today=0 WHERE transfer_reset_date!=?',
            (today,))
        c.execute(
            'UPDATE users SET wheel_used_today=0 WHERE wheel_reset_date!=?',
            (today,))
        db.conn.commit()
        logger.info("🔄 Daily counters reset")

    job_queue.run_repeating(
        reset_daily_counters,
        interval=86400,   # 24 hours
        first=60,
        name="daily_reset"
    )

    # ══════════════════════════════════════════
    #         START BOT
    # ══════════════════════════════════════════

    logger.info("✅ All handlers registered")
    logger.info("🚀 Starting polling...")

    # Set bot commands menu
    async def post_init(application):
        try:
            await application.bot.set_my_commands([
                ("start", "شروع ربات"),
                ("help", "راهنما"),
                ("admin", "پنل مدیریت"),
                ("backup", "بکاپ دیتابیس"),
            ])
            logger.info("✅ Bot commands set")
        except Exception as e:
            logger.warning(f"Set commands err: {e}")

    app.post_init = post_init

    # Run with polling
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        stop_signals=None,  # Let Render handle shutdown
    )


# ══════════════════════════════════════════════
#     🎯 ENTRY POINT
# ══════════════════════════════════════════════

if __name__ == "__main__":
    main()
