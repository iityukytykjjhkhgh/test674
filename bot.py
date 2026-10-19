# bot.py — Dark Point Bot (قسمت 1/12) — Glass Buttons Edition
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
    ReplyKeyboardRemove,
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


# ══════════════════════════════════════════════
#       KEEP-ALIVE (Render Web Service)
# ══════════════════════════════════════════════

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


# ══════════════════════════════════════════════
#              HELPERS
# ══════════════════════════════════════════════

def fmt(n):
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
    return (dp / config.TON_WITHDRAWAL_DP_RATE) * config.TON_WITHDRAWAL_TON_AMOUNT


def ton_to_dp(ton):
    return int((ton / config.TON_WITHDRAWAL_TON_AMOUNT) * config.TON_WITHDRAWAL_DP_RATE)


def mask_wallet(addr):
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
    """Safe edit message — tries edit first, falls back to send"""
    try:
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=kb,
            disable_web_page_preview=True)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            try:
                await query.message.reply_text(
                    text, parse_mode=ParseMode.HTML, reply_markup=kb,
                    disable_web_page_preview=True)
            except Exception:
                pass
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
    """Clear all input flow flags"""
    for k in list(ctx.user_data.keys()):
        if k.startswith(('tw_', 'bank_', 'buy_', 'transfer_',
                         'admin_', 'shop_', 'task_', 'gift_',
                         'force_', 'panel_', 'send_', 'addrm_',
                         'search_', 'ban_', 'reply_', 'guess_',
                         'bomb_', 'set_', 'edit_', 'conv_',
                         'buydp_', 'mission_', 'ref_')):
            ctx.user_data.pop(k, None)


# ══════════════════════════════════════════════
#       🎛️ GLASS MENUS (Inline Keyboards)
# ══════════════════════════════════════════════

def main_menu_kb():
    """منوی اصلی شیشه‌ای — فقط آیتم‌های PV (بازی/ماینر/کارخانه فقط گروهی)"""
    rows = [
        [InlineKeyboardButton("💎 برداشت TON", callback_data="menu_ton_withdraw")],
        [
            InlineKeyboardButton("💰 خرید DP", callback_data="menu_buy_dp"),
            InlineKeyboardButton("🎁 هدیه", callback_data="menu_gift"),
        ],
        [
            InlineKeyboardButton("🛒 فروشگاه", callback_data="menu_shop"),
            InlineKeyboardButton("⭐ ستاره", callback_data="menu_stars"),
        ],
        [
            InlineKeyboardButton("🎡 گردونه", callback_data="menu_wheel"),
            InlineKeyboardButton("🏦 بانک دارکی", callback_data="menu_bank"),
        ],
        [
            InlineKeyboardButton("📊 پروفایل", callback_data="menu_profile"),
            InlineKeyboardButton("🎯 کلیم", callback_data="menu_claim"),
        ],
        [
            InlineKeyboardButton("🤝 زیرمجموعه‌گیری", callback_data="menu_referral"),
            InlineKeyboardButton("📋 ماموریت‌ها", callback_data="menu_tasks"),
        ],
        [
            InlineKeyboardButton("👍 لایک چلنج", callback_data="menu_like"),
            InlineKeyboardButton("💱 تبدیل ارز", callback_data="menu_convert"),
        ],
        [
            InlineKeyboardButton("📖 پنل DP", callback_data="menu_panel"),
        ],
    ]
    return InlineKeyboardMarkup(rows)


def back_to_main_kb():
    """Just a 'back to main' button"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="back_main")]
    ])


def admin_menu_kb():
    """Admin panel — ALL GLASS INLINE BUTTONS"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 آمار ربات", callback_data="adm_stats"),
         InlineKeyboardButton("💎 آمار برداشت TON", callback_data="adm_ton_stats")],
        [InlineKeyboardButton("⛏ آمار ماینینگ", callback_data="adm_miner_stats"),
         InlineKeyboardButton("💱 آمار ارز", callback_data="adm_currency_stats")],
        [InlineKeyboardButton("📢 ارسال همگانی", callback_data="adm_broadcast"),
         InlineKeyboardButton("📣 ارسال به گروه‌ها", callback_data="adm_broadcast_g")],
        [InlineKeyboardButton("💰 افزودن DP", callback_data="adm_add_dp"),
         InlineKeyboardButton("➖ کسر DP", callback_data="adm_sub_dp")],
        [InlineKeyboardButton("🔍 جستجوی کاربر", callback_data="adm_search"),
         InlineKeyboardButton("👤 ارسال به کاربر", callback_data="adm_send_user")],
        [InlineKeyboardButton("🚫 بن کاربر", callback_data="adm_ban"),
         InlineKeyboardButton("✅ آنبان", callback_data="adm_unban")],
        [InlineKeyboardButton("📢 فورس جوین", callback_data="adm_force"),
         InlineKeyboardButton("📋 گروه‌های من", callback_data="adm_groups")],
        [InlineKeyboardButton("📋 مدیریت تسک‌ها", callback_data="adm_tasks"),
         InlineKeyboardButton("✅ تایید ماموریت", callback_data="adm_missions")],
        [InlineKeyboardButton("🛒 مدیریت فروشگاه", callback_data="adm_shop"),
         InlineKeyboardButton("🎁 مدیریت هدایا", callback_data="adm_gift")],
        [InlineKeyboardButton("💰 تنظیم خرید DP", callback_data="adm_buydp"),
         InlineKeyboardButton("⭐ تنظیم استارز", callback_data="adm_stars_set")],
        [InlineKeyboardButton("📦 پلن‌های پنل", callback_data="adm_panel_plans"),
         InlineKeyboardButton("🏷 پاداش رفرال", callback_data="adm_ref")],
        [InlineKeyboardButton("⚙️ روشن/خاموش بخش‌ها", callback_data="adm_sections"),
         InlineKeyboardButton("🔌 ربات روشن/خاموش", callback_data="adm_bot_toggle")],
        [InlineKeyboardButton("💾 بکاپ", callback_data="adm_backup"),
         InlineKeyboardButton("♻️ ریستور", callback_data="adm_restore")],
        [InlineKeyboardButton("🎁 هدیه به برترین‌ها", callback_data="adm_gift_top"),
         InlineKeyboardButton("🎁 هدیه به همه", callback_data="adm_gift_all")],
        [InlineKeyboardButton("💬 پاسخ به کاربر", callback_data="adm_reply"),
         InlineKeyboardButton("📜 سفارش‌های اخیر", callback_data="adm_orders")],
        [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="back_main")],
    ])


def sections_toggle_kb():
    """Section on/off toggles"""
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


def cancel_only_kb():
    """Just a cancel button"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ لغو", callback_data="cancel_action")]
    ])


def back_only_kb(callback="back_main"):
    """Just a back button with custom callback"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت", callback_data=callback)]
    ])# ═══════════════════════════════════════════════════════════
#  SECTION 2/12 — /start, Welcome, Force Join, Main Menu, Cancel
# ═══════════════════════════════════════════════════════════

# ── /start ──────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ورود کاربر — ثبت‌نام + چک فورس‌جوین + نمایش منو"""
    user = update.effective_user
    if not user:
        return
    uid = user.id
    username = user.username or ""
    first_name = user.first_name or "کاربر"

    # ربات خاموش؟ (ادمین استثنا)
    if db.get_setting("bot_on", "1") != "1" and not is_admin(uid):
        await safe_send(update, bot_off_text())
        return

    # ریفرال
    ref_id = None
    if context.args:
        try:
            ref_id = int(context.args[0])
            if ref_id == uid:
                ref_id = None
        except (ValueError, TypeError):
            ref_id = None

    # ثبت / به‌روزرسانی کاربر
    db.add_user(uid, username, first_name, ref_id)

    # فورس‌جوین
    if not await check_force_join(update, context, uid):
        return

    await send_welcome(update, context, uid, first_name)


# ── خوش‌آمدگویی ────────────────────────────────────────────
async def send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       uid: int, first_name: str):
    """پیام خوش‌آمد + منوی شیشه‌ای اصلی"""
    u = db.get_user(uid)
    bal = u["balance"] if u else 0
    lvl = u["level"] if u else 1

    text = (
        f"👋 سلام <b>{html.escape(first_name)}</b> عزیز!\n"
        f"به <b>دارک پوینت</b> خوش اومدی 🖤\n\n"
        f"💰 موجودی: <code>{fmt(bal)}</code> DP\n"
        f"📊 سطح: <b>{lvl}</b>\n\n"
        f"از منوی زیر انتخاب کن 👇"
    )
    if update.callback_query:
        await safe_edit(update, text, reply_markup=main_menu_kb())
    else:
        await safe_send(update, text, reply_markup=main_menu_kb())


# ── چک عضویت (دکمه «عضو شدم») ────────────────────────────
async def cb_check_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    if await check_force_join(update, context, uid, silent=True):
        await send_welcome(update, context, uid,
                           query.from_user.first_name or "کاربر")
    else:
        await query.answer("❌ هنوز عضو همه کانال‌ها نشدی!", show_alert=True)


# ── پنل ادمین ──────────────────────────────────────────────
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    text = (
        "⚙️ <b>پنل مدیریت دارک پوینت</b>\n\n"
        "از منوی زیر انتخاب کنید:"
    )
    await safe_send(update, text, reply_markup=admin_menu_kb())


# ── راهنما ─────────────────────────────────────────────────
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 <b>راهنمای دارک پوینت</b>\n\n"
        "🔹 در PV از منوی شیشه‌ای استفاده کنید\n"
        "🔹 در گروه از دستورات زیر:\n\n"
        "<b>🎮 دستورات گروهی:</b>\n"
        "• <code>بازی [مبلغ]</code> — انفجار\n"
        "• <code>تاس [مبلغ]</code> — تاس\n"
        "• <code>حدس بزن [مبلغ]</code> — حدس عدد\n"
        "• <code>کازینو [مبلغ]</code> — کازینو\n"
        "• <code>بمب [مبلغ]</code> — بمب (4×4)\n"
        "• <code>ماینر دارکی</code> — ماینر\n"
        "• <code>کارخانه دارکی</code> — کارخانه\n"
        "• <code>انتقال [مبلغ]</code> — انتقال DP\n"
        "• <code>موجودی</code> — موجودی\n"
        "• <code>پروفایل دارکی</code> — پروفایل\n"
        "• <code>لیدربورد</code> — جدول رتبه‌بندی\n"
        "• <code>دارک</code> — منوی گروه\n"
        "• <code>دارک کانفیگ</code> — دریافت کانفیگ\n"
        "• <code>ایدی عددی</code> — آیدی (ریپلای)"
    )
    await safe_send(update, text)


# ── بازگشت به منوی اصلی ──────────────────────────────────
async def cb_back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    clear_user_state(context)
    await send_welcome(update, context, query.from_user.id,
                       query.from_user.first_name or "کاربر")


# ── لغو عملیات ────────────────────────────────────────────
async def cb_cancel_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("❌ لغو شد")
    clear_user_state(context)
    await send_welcome(update, context, query.from_user.id,
                       query.from_user.first_name or "کاربر")


# ── روتر منوی اصلی ────────────────────────────────────────
async def cb_main_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """هدایت دکمه‌های منوی اصلی به هندلر مربوطه"""
    query = update.callback_query
    data = query.data
    uid = query.from_user.id

    # چک خاموشی ربات
    if db.get_setting("bot_on", "1") != "1" and not is_admin(uid):
        await query.answer(bot_off_text(), show_alert=True)
        return

    # نگاشت دکمه → کلید بخش در دیتابیس
    SECTION_MAP = {
        "menu_ton_withdraw": "ton_withdraw",
        "menu_buy_dp":       "buy_dp",
        "menu_gift":         "gift",
        "menu_shop":         "shop",
        "menu_stars":        "stars",
        "menu_wheel":        "wheel",
        "menu_bank":         "bank",
        "menu_profile":      None,      # همیشه روشن
        "menu_claim":        "claim",
        "menu_referral":     "referral",
        "menu_tasks":        "tasks",
        "menu_like":         "like",
        "menu_convert":      "convert",
        "menu_panel":        "panel",
    }

    sec_key = SECTION_MAP.get(data)
    if sec_key and not db.is_section_on(sec_key):
        await query.answer(section_off_text(), show_alert=True)
        return

    await query.answer()

    # ── هدایت مستقیم به هندلر (تعریف‌شده در بخش‌های 3-8) ──
    if data == "menu_ton_withdraw":
        await handle_ton_withdraw_menu(update, context)
    elif data == "menu_buy_dp":
        await handle_buy_dp(update, context)
    elif data == "menu_gift":
        await handle_gift_menu(update, context)
    elif data == "menu_shop":
        await handle_shop_menu(update, context)
    elif data == "menu_stars":
        await handle_stars(update, context)
    elif data == "menu_wheel":
        await handle_wheel(update, context)
    elif data == "menu_bank":
        await handle_bank_menu(update, context)
    elif data == "menu_profile":
        await handle_profile(update, context)
    elif data == "menu_claim":
        await handle_claim(update, context)
    elif data == "menu_referral":
        await handle_referral(update, context)
    elif data == "menu_tasks":
        await handle_tasks(update, context)
    elif data == "menu_like":
        await handle_like(update, context)
    elif data == "menu_convert":
        await handle_convert_menu(update, context)
    elif data == "menu_panel":
        await handle_panel(update, context)# ═══════════════════════════════════════════════════════════
#  SECTION 3/12 — Profile, Claim, Referral, Leaderboard, Wheel
# ═══════════════════════════════════════════════════════════

import random
from datetime import datetime, timedelta

# ── پروفایل ────────────────────────────────────────────────
async def handle_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    u = db.get_user(uid)
    if not u:
        await query.answer("❌ کاربر یافت نشد", show_alert=True)
        return

    bal = u["balance"]
    lvl = u["level"]
    ref_count = db.get_referral_count(uid)
    bank_bal = u.get("bank_balance", 0)
    miner_lvl = u.get("miner_level", 0)
    factory_lvl = u.get("factory_level", 1)
    ton_bal = u.get("ton_balance", 0.0)

    # محاسبه XP برای سطح بعدی
    if lvl < 20:
        next_xp = config.LEVEL_THRESHOLDS[lvl]
        cur_xp = config.LEVEL_THRESHOLDS[lvl - 1]
        progress = bal - cur_xp
        needed = next_xp - cur_xp
        pct = min(100, int(progress / needed * 100)) if needed > 0 else 100
        bar_len = 10
        filled = int(bar_len * pct / 100)
        bar = "█" * filled + "░" * (bar_len - filled)
        lvl_text = (
            f"📊 سطح: <b>{lvl}</b> / 20\n"
            f"📈 پیشرفت: [{bar}] {pct}%\n"
            f"🎯 تا سطح بعدی: <code>{fmt(needed - progress)}</code> DP"
        )
    else:
        lvl_text = "📊 سطح: <b>20 (حداکثر)</b> 🏆"

    text = (
        f"👤 <b>پروفایل دارکی</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🆔 آیدی: <code>{uid}</code>\n"
        f"👤 نام: {html.escape(query.from_user.first_name or 'کاربر')}\n"
        f"🏷 یوزرنیم: @{html.escape(query.from_user.username or '—')}\n\n"
        f"💰 موجودی DP: <code>{fmt(bal)}</code>\n"
        f"💎 موجودی TON: <code>{ton_bal:.4f}</code>\n"
        f"🏦 بانک: <code>{fmt(bank_bal)}</code>\n\n"
        f"{lvl_text}\n\n"
        f"⛏ ماینر: سطح {miner_lvl}\n"
        f"🏭 کارخانه: سطح {factory_lvl}\n"
        f"🤝 زیرمجموعه: {ref_count} نفر\n"
        f"━━━━━━━━━━━━━━━"
    )
    await safe_edit(update, text, reply_markup=back_to_main_kb())


# ── کلیم ───────────────────────────────────────────────────
async def handle_claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    u = db.get_user(uid)
    if not u:
        return

    now = int(datetime.now().timestamp())
    last_claim = u.get("last_claim", 0)
    cooldown = u.get("claim_cooldown", 240)

    # اگر اولین بار است، کولداون تصادفی تعیین کن
    if cooldown == 0:
        cooldown = random.randint(180, 300)
        db.set_claim_cooldown(uid, cooldown)

    remaining = (last_claim + cooldown) - now
    if remaining > 0:
        h, m, s = seconds_to_hms(remaining)
        text = (
            f"⏳ <b>کلیم</b>\n\n"
            f"هنوز وقتش نرسیده!\n"
            f"⏰ زمان باقی‌مانده: <b>{h}:{m:02d}:{s:02d}</b>\n\n"
            f"💡 هرچه سطح بالاتر، جایزه بیشتر!"
        )
        await safe_edit(update, text, reply_markup=back_to_main_kb())
        return

    # محاسبه جایزه
    lvl = u["level"]
    base = random.randint(100, 250)
    bonus = 40 * (lvl - 1)
    reward = base + bonus

    db.add_balance(uid, reward)
    db.set_last_claim(uid, now)

    # کولداون جدید تصادفی
    new_cd = random.randint(180, 300)
    db.set_claim_cooldown(uid, new_cd)

    text = (
        f"🎯 <b>کلیم موفق!</b>\n\n"
        f"💰 جایزه پایه: <code>{fmt(base)}</code> DP\n"
        f"📊 بونوس سطح {lvl}: <code>+{fmt(bonus)}</code> DP\n"
        f"━━━━━━━━━━━━━━━\n"
        f"✅ مجموع: <b>{fmt(reward)}</b> DP\n\n"
        f"⏰ کلیم بعدی: {new_cd // 60} دقیقه دیگه"
    )
    await safe_edit(update, text, reply_markup=back_to_main_kb())


# ── زیرمجموعه‌گیری ────────────────────────────────────────
async def handle_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id

    ref_reward = int(db.get_setting("referral_reward",
                                    str(config.DEFAULT_REFERRAL_REWARD)))
    first_join = int(db.get_setting("first_join_reward",
                                    str(config.DEFAULT_FIRST_JOIN_REWARD)))
    ref_count = db.get_referral_count(uid)
    bot_username = context.bot.username or "DarkPointBot"

    text = (
        f"🤝 <b>زیرمجموعه‌گیری</b>\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"🎁 جایزه هر زیرمجموعه: <code>{fmt(ref_reward)}</code> DP\n"
        f"🎉 جایزه عضویت اول: <code>{fmt(first_join)}</code> DP\n"
        f"👥 تعداد زیرمجموعه‌ها: <b>{ref_count}</b> نفر\n\n"
        f"📎 لینک اختصاصی شما:\n"
        f"<code>https://t.me/{bot_username}?start={uid}</code>\n\n"
        f"💡 این لینک رو برای دوستات بفرست و DP رایگان بگیر!\n"
        f"💎 با زیرمجموعه‌گیری راحت می‌توانید برداشت TON کنید!"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📤 اشتراک لینک",
            url=f"https://t.me/share/url?url=https://t.me/{bot_username}?start={uid}"
                 f"&text=🖤 بیا دارک پوینت، DP رایگان بگیر!"
        )],
        [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="back_main")],
    ])
    await safe_edit(update, text, reply_markup=kb)


# ── لیدربورد ──────────────────────────────────────────────
async def handle_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لیدربورد — از گروه یا PV قابل فراخوانی"""
    top = db.get_top_users(10)
    if not top:
        text = "📊 <b>لیدربورد</b>\n\nهنوز کاربری ثبت نشده!"
    else:
        lines = ["📊 <b>لیدربورد دارک پوینت</b>", "━━━━━━━━━━━━━━━", ""]
        medals = ["🥇", "🥈", "🥉"]
        for i, row in enumerate(top):
            rank = medals[i] if i < 3 else f"#{i+1}"
            name = html.escape(row["first_name"] or "کاربر")
            bal = fmt(row["balance"])
            lvl = row.get("level", 1)
            lines.append(f"{rank} {name} — <code>{bal}</code> DP (سطح {lvl})")
        text = "\n".join(lines)

    if update.callback_query:
        await safe_edit(update, text, reply_markup=back_to_main_kb())
    else:
        await safe_send(update, text)


# ── گردونه ─────────────────────────────────────────────────
async def handle_wheel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    u = db.get_user(uid)
    if not u:
        return

    now = int(datetime.now().timestamp())
    last_wheel = u.get("last_wheel", 0)
    today_start = int(datetime.now().replace(
        hour=0, minute=0, second=0, microsecond=0).timestamp())

    # چک استفاده رایگان امروز
    free_used = last_wheel >= today_start
    extra_cost = config.WHEEL_EXTRA_COST

    if free_used:
        # گردونه اضافی با هزینه
        if u["balance"] < extra_cost:
            text = (
                f"🎡 <b>گردونه</b>\n\n"
                f"✅ گردونه رایگان امروز رو زدی!\n"
                f"💰 هزینه گردونه اضافه: <code>{fmt(extra_cost)}</code> DP\n"
                f"❌ موجودی کافی نیست!"
            )
            await safe_edit(update, text, reply_markup=back_to_main_kb())
            return

        db.add_balance(uid, -extra_cost)
        cost_text = f"💸 هزینه: <code>{fmt(extra_cost)}</code> DP"
    else:
        cost_text = "🆓 رایگان روزانه!"

    # جایزه تصادفی
    prize = random.randint(config.WHEEL_FREE_MIN, config.WHEEL_FREE_MAX)
    # گرد کردن به نزدیک‌ترین 1000
    prize = round(prize / 1000) * 1000

    db.add_balance(uid, prize)
    db.set_last_wheel(uid, now)

    # ایموجی بر اساس جایزه
    if prize >= 80_000:
        emoji = "🏆"
        msg = "جکپات زدی!"
    elif prize >= 50_000:
        emoji = "🎉"
        msg = "عالی بود!"
    elif prize >= 20_000:
        emoji = "😊"
        msg = "بد نبود!"
    else:
        emoji = "😅"
        msg = "دفعه بعد بهتره!"

    text = (
        f"🎡 <b>گردونه دارکی</b>\n\n"
        f"🎰 {emoji} {msg}\n\n"
        f"💰 جایزه: <b>{fmt(prize)}</code> DP\n"
        f"{cost_text}\n\n"
        f"🔄 فردا دوباره رایگان بزن!"
    )
    await safe_edit(update, text, reply_markup=back_to_main_kb())# ═══════════════════════════════════════════════════════════
#  SECTION 4/12 — Group Games (Crash, Dice, Guess, Casino, Bomb)
# ═══════════════════════════════════════════════════════════

import random
from datetime import datetime

# ── ذخیره وضعیت بازی‌ها ───────────────────────────────────
bomb_games = {}     # (chat_id, user_id) -> dict
guess_games = {}    # (chat_id, user_id) -> dict

# ── کمکی: استخراج مبلغ شرط ────────────────────────────────
def parse_bet(text: str, min_bet: int, max_bet: int = None):
    """استخراج مبلغ از متن دستور. برمی‌گرداند (amount, error)."""
    parts = text.strip().split()
    if len(parts) < 2:
        return None, (
            f"❌ مبلغ را وارد کنید!\n"
            f"مثال: <code>{parts[0]} {fmt(min_bet)}</code>"
        )
    try:
        amount = int(parts[1])
    except ValueError:
        return None, "❌ مبلغ باید عدد باشد!"
    if amount < min_bet:
        return None, f"❌ حداقل مبلغ: <code>{fmt(min_bet)}</code> DP"
    if max_bet and amount > max_bet:
        return None, f"❌ حداکثر مبلغ: <code>{fmt(max_bet)}</code> DP"
    return amount, None


# ══════════════════════════════════════════════════════════
#  1. 🚀 انفجار / بازی  (Crash) — فقط گروه
# ══════════════════════════════════════════════════════════
async def cmd_crash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private":
        await safe_send(update, "⚠️ این بازی فقط در گروه فعال است!")
        return

    uid = update.effective_user.id
    amount, err = parse_bet(
        update.message.text, config.CRASH_MIN_BET, config.CRASH_MAX_BET
    )
    if err:
        await safe_send(update, err)
        return

    u = db.get_user(uid)
    if not u or u["balance"] < amount:
        await safe_send(update, "❌ موجودی کافی نیست!")
        return

    db.add_balance(uid, -amount)
    name = html.escape(update.effective_user.first_name or "کاربر")

    msg = await update.message.reply_text(
        f"🚀 <b>انفجار {name}</b>\n"
        f"💰 شرط: <code>{fmt(amount)}</code> DP\n\n"
        f"🎰 در حال چرخش..."
    )

    dice = await context.bot.send_dice(
        chat_id=chat.id, emoji="🎰",
        reply_to_message_id=update.message.message_id,
    )

    val = dice.dice.value
    if val == 64:      # seven seven seven
        mult, em = 5.0, "🏆"
    elif val == 43:    # lemon
        mult, em = 3.0, "🎉"
    elif val == 22:    # grape
        mult, em = 2.0, "😊"
    else:              # bar = باخت
        mult, em = 0.0, "💥"

    if mult > 0:
        win = int(amount * mult)
        db.add_balance(uid, win)
        result = (
            f"{em} <b>انفجار {name}</b>\n"
            f"💰 شرط: <code>{fmt(amount)}</code> DP\n"
            f"📈 ضریب: <b>{mult}x</b>\n"
            f"✅ برد: <b>{fmt(win)}</b> DP"
        )
    else:
        result = (
            f"💥 <b>انفجار {name}</b>\n"
            f"💰 شرط: <code>{fmt(amount)}</code> DP\n"
            f"❌ باختی! ضریب: <b>0x</b>"
        )
    await msg.edit_text(result, parse_mode="HTML")


# ══════════════════════════════════════════════════════════
#  2. 🎲 تاس  (Dice) — فقط گروه
# ══════════════════════════════════════════════════════════
async def cmd_dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private":
        await safe_send(update, "⚠️ این بازی فقط در گروه فعال است!")
        return

    uid = update.effective_user.id
    amount, err = parse_bet(update.message.text, config.DICE_MIN_BET)
    if err:
        await safe_send(update, err)
        return

    u = db.get_user(uid)
    if not u or u["balance"] < amount:
        await safe_send(update, "❌ موجودی کافی نیست!")
        return

    db.add_balance(uid, -amount)
    name = html.escape(update.effective_user.first_name or "کاربر")

    msg = await update.message.reply_text(
        f"🎲 <b>تاس {name}</b>\n"
        f"💰 شرط: <code>{fmt(amount)}</code> DP\n\n"
        f"🎲 در حال پرتاب..."
    )

    dice = await context.bot.send_dice(
        chat_id=chat.id, emoji="🎲",
        reply_to_message_id=update.message.message_id,
    )

    val = dice.dice.value
    if val == 6:
        mult = 6.0
    elif val == 5:
        mult = 3.0
    elif val == 4:
        mult = 1.5
    else:
        mult = 0.0

    if mult > 0:
        win = int(amount * mult)
        db.add_balance(uid, win)
        result = (
            f"🎲 <b>تاس {name}</b>\n"
            f"🎯 عدد: <b>{val}</b>\n"
            f"💰 شرط: <code>{fmt(amount)}</code> DP\n"
            f"📈 ضریب: <b>{mult}x</b>\n"
            f"✅ برد: <b>{fmt(win)}</b> DP"
        )
    else:
        result = (
            f"🎲 <b>تاس {name}</b>\n"
            f"🎯 عدد: <b>{val}</b>\n"
            f"💰 شرط: <code>{fmt(amount)}</code> DP\n"
            f"❌ باختی!"
        )
    await msg.edit_text(result, parse_mode="HTML")


# ══════════════════════════════════════════════════════════
#  3. 🔢 حدس بزن  (Guess) — فقط گروه
# ══════════════════════════════════════════════════════════
async def cmd_guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private":
        await safe_send(update, "⚠️ این بازی فقط در گروه فعال است!")
        return

    uid = update.effective_user.id
    amount, err = parse_bet(update.message.text, config.GUESS_MIN_BET)
    if err:
        await safe_send(update, err)
        return

    u = db.get_user(uid)
    if not u or u["balance"] < amount:
        await safe_send(update, "❌ موجودی کافی نیست!")
        return

    # چک بازی فعال قبلی
    key = (chat.id, uid)
    if key in guess_games:
        if int(datetime.now().timestamp()) - guess_games[key]["time"] < GAME_TIMEOUT:
            await safe_send(update, "⚠️ یک بازی حدس فعال داری! اول تمومش کن.")
            return
        del guess_games[key]

    db.add_balance(uid, -amount)
    secret = random.randint(1, 4)
    guess_games[key] = {
        "secret": secret,
        "bet": amount,
        "time": int(datetime.now().timestamp()),
    }

    name = html.escape(update.effective_user.first_name or "کاربر")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("1️⃣", callback_data="gs_1"),
        InlineKeyboardButton("2️⃣", callback_data="gs_2"),
        InlineKeyboardButton("3️⃣", callback_data="gs_3"),
        InlineKeyboardButton("4️⃣", callback_data="gs_4"),
    ]])
    await update.message.reply_text(
        f"🔢 <b>حدس بزن {name}</b>\n"
        f"💰 شرط: <code>{fmt(amount)}</code> DP\n\n"
        f"یک عدد از 1 تا 4 انتخاب کن!\n"
        f"⏰ مهلت: {GAME_TIMEOUT // 60} دقیقه\n\n"
        f"🏆 دقیق = 10x  |  🥈 نزدیک = 5x\n"
        f"🥉 نزدیک‌تر = 2.5x  |  👍 دور = 1.2x",
        reply_markup=kb,
    )


async def cb_guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """هندلر دکمه‌های حدس بزن"""
    query = update.callback_query
    uid = query.from_user.id
    chat_id = query.message.chat_id
    key = (chat_id, uid)

    if key not in guess_games:
        await query.answer("⚠️ بازی فعالی نداری!", show_alert=True)
        return

    game = guess_games[key]
    now = int(datetime.now().timestamp())
    if now - game["time"] > GAME_TIMEOUT:
        del guess_games[key]
        await query.answer("⏰ وقتت تموم شد!", show_alert=True)
        await safe_edit(update, "⏰ <b>زمان بازی حدس تمام شد!</b>")
        return

    await query.answer()
    choice = int(query.data.split("_")[1])
    secret = game["secret"]
    bet = game["bet"]
    del guess_games[key]

    distance = abs(choice - secret)
    if distance == 0:
        mult, label = 10.0, "🏆 دقیقاً درست!"
    elif distance == 1:
        mult, label = 5.0, "🥈 خیلی نزدیک!"
    elif distance == 2:
        mult, label = 2.5, "🥉 نزدیک بود!"
    else:
        mult, label = 1.2, "👍 حداقل یه چیزی!"

    win = int(bet * mult)
    db.add_balance(uid, win)
    name = html.escape(query.from_user.first_name or "کاربر")

    await safe_edit(update, (
        f"🔢 <b>نتیجه حدس {name}</b>\n"
        f"🎯 عدد مخفی: <b>{secret}</b>  |  انتخاب تو: <b>{choice}</b>\n"
        f"{label}\n\n"
        f"💰 شرط: <code>{fmt(bet)}</code> DP\n"
        f"📈 ضریب: <b>{mult}x</b>\n"
        f"✅ برد: <b>{fmt(win)}</b> DP"
    ))


# ══════════════════════════════════════════════════════════
#  4. 🎰 کازینو  (Casino) — فقط گروه
# ══════════════════════════════════════════════════════════
async def cmd_casino(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private":
        await safe_send(update, "⚠️ این بازی فقط در گروه فعال است!")
        return

    uid = update.effective_user.id
    amount, err = parse_bet(update.message.text, config.CASINO_MIN_BET)
    if err:
        await safe_send(update, err)
        return

    u = db.get_user(uid)
    if not u or u["balance"] < amount:
        await safe_send(update, "❌ موجودی کافی نیست!")
        return

    db.add_balance(uid, -amount)
    name = html.escape(update.effective_user.first_name or "کاربر")

    msg = await update.message.reply_text(
        f"🎰 <b>کازینو {name}</b>\n"
        f"💰 شرط: <code>{fmt(amount)}</code> DP\n\n"
        f"🎰 در حال چرخش..."
    )

    dice = await context.bot.send_dice(
        chat_id=chat.id, emoji="🎰",
        reply_to_message_id=update.message.message_id,
    )

    val = dice.dice.value
    if val == 64:      # seven = 15x
        mult, em = 15.0, "🏆"
    elif val == 43:    # lemon = 12x
        mult, em = 12.0, "🎉"
    elif val == 22:    # grape = 7x
        mult, em = 7.0, "😊"
    else:
        mult, em = 0.0, "💥"

    if mult > 0:
        win = int(amount * mult)
        db.add_balance(uid, win)
        result = (
            f"{em} <b>کازینو {name}</b>\n"
            f"💰 شرط: <code>{fmt(amount)}</code> DP\n"
            f"📈 ضریب: <b>{mult}x</b>\n"
            f"✅ برد: <b>{fmt(win)}</b> DP"
        )
    else:
        result = (
            f"💥 <b>کازینو {name}</b>\n"
            f"💰 شرط: <code>{fmt(amount)}</code> DP\n"
            f"❌ باختی!"
        )
    await msg.edit_text(result, parse_mode="HTML")


# ══════════════════════════════════════════════════════════
#  5. 💣 بمب  (Bomb 4×4) — فقط گروه
# ══════════════════════════════════════════════════════════
async def cmd_bomb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private":
        await safe_send(update, "⚠️ این بازی فقط در گروه فعال است!")
        return

    uid = update.effective_user.id
    amount, err = parse_bet(update.message.text, config.BOMB_MIN_BET)
    if err:
        await safe_send(update, err)
        return

    u = db.get_user(uid)
    if not u or u["balance"] < amount:
        await safe_send(update, "❌ موجودی کافی نیست!")
        return

    key = (chat.id, uid)
    if key in bomb_games:
        if int(datetime.now().timestamp()) - bomb_games[key]["time"] < GAME_TIMEOUT:
            await safe_send(update, "⚠️ یک بازی بمب فعال داری! اول تمومش کن.")
            return
        del bomb_games[key]

    db.add_balance(uid, -amount)

    # ساخت گرید 4×4 با 6 بمب
    bombs = set(random.sample(range(16), config.BOMB_COUNT))
    bomb_games[key] = {
        "bombs": bombs,
        "revealed": set(),
        "bet": amount,
        "time": int(datetime.now().timestamp()),
    }

    name = html.escape(update.effective_user.first_name or "کاربر")
    grid_text, kb = _build_bomb_grid(bomb_games[key])

    await update.message.reply_text(
        f"💣 <b>بمب {name}</b>\n"
        f"💰 شرط: <code>{fmt(amount)}</code> DP\n"
        f"📈 ضریب: <b>1.0x</b>\n\n"
        f"{grid_text}\n"
        f"⚠️ 6 بمب مخفی! هر خانه امن = +0.2x\n"
        f"⏰ مهلت: {GAME_TIMEOUT // 60} دقیقه",
        reply_markup=kb,
    )


def _build_bomb_grid(game):
    """ساخت متن گرید + دکمه‌های اینلاین"""
    bombs = game["bombs"]
    revealed = game["revealed"]
    lines, rows_kb = [], []

    for r in range(config.BOMB_GRID_SIZE):
        line, btns = "", []
        for c in range(config.BOMB_GRID_SIZE):
            idx = r * config.BOMB_GRID_SIZE + c
            if idx in revealed:
                if idx in bombs:
                    line += "💣"
                    btns.append(InlineKeyboardButton("💣", callback_data="bmb_x"))
                else:
                    line += "🟩"
                    btns.append(InlineKeyboardButton("🟩", callback_data="bmb_x"))
            else:
                line += "⬜"
                btns.append(
                    InlineKeyboardButton(f"{idx+1}", callback_data=f"bmb_{idx}")
                )
        lines.append(line)
        rows_kb.append(btns)

    # دکمه نقد کردن (بعد از حداقل 1 خانه امن)
    safe_count = len(revealed - bombs)
    if safe_count > 0:
        mult = 1.0 + safe_count * config.BOMB_MULTIPLIER_STEP
        rows_kb.append([
            InlineKeyboardButton(
                f"💰 نقد کردن ({mult:.1f}x)", callback_data="bmb_cash"
            )
        ])

    return "\n".join(lines), InlineKeyboardMarkup(rows_kb)


async def cb_bomb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """هندلر دکمه‌های بازی بمب"""
    query = update.callback_query
    uid = query.from_user.id
    chat_id = query.message.chat_id
    key = (chat_id, uid)

    if key not in bomb_games:
        await query.answer("⚠️ بازی فعالی نداری!", show_alert=True)
        return

    game = bomb_games[key]
    now = int(datetime.now().timestamp())
    if now - game["time"] > GAME_TIMEOUT:
        del bomb_games[key]
        await query.answer("⏰ وقتت تموم شد!", show_alert=True)
        await safe_edit(update, "⏰ <b>زمان بازی بمب تمام شد!</b>")
        return

    data = query.data
    name = html.escape(query.from_user.first_name or "کاربر")

    # ── دکمه خالی (خانه قبلاً باز شده) ──
    if data == "bmb_x":
        await query.answer()
        return

    # ── نقد کردن ──
    if data == "bmb_cash":
        safe_count = len(game["revealed"] - game["bombs"])
        if safe_count == 0:
            await query.answer("⚠️ اول حداقل یک خانه امن باز کن!", show_alert=True)
            return
        await query.answer()
        mult = 1.0 + safe_count * config.BOMB_MULTIPLIER_STEP
        win = int(game["bet"] * mult)
        bet = game["bet"]
        del bomb_games[key]

        # نمایش نهایی همه خانه‌ها
        game["revealed"] = set(range(16))
        grid_text, _ = _build_bomb_grid(game)

        await safe_edit(update, (
            f"💰 <b>نقد کردی {name}!</b>\n"
            f"📈 ضریب: <b>{mult:.1f}x</b>\n"
            f"💰 شرط: <code>{fmt(bet)}</code> DP\n"
            f"✅ برد: <b>{fmt(win)}</b> DP\n\n"
            f"{grid_text}"
        ))
        return

    # ── باز کردن خانه ──
    await query.answer()
    tile = int(data.split("_")[1])
    if tile in game["revealed"]:
        return

    game["revealed"].add(tile)

    if tile in game["bombs"]:
        # 💥 بوم!
        bet = game["bet"]
        del bomb_games[key]
        game["revealed"] = set(range(16))
        grid_text, _ = _build_bomb_grid(game)

        await safe_edit(update, (
            f"💥 <b>بوم! {name}</b>\n"
            f"💰 شرط: <code>{fmt(bet)}</code> DP\n"
            f"❌ باختی!\n\n"
            f"{grid_text}"
        ))
    else:
        # 🟩 امن
        safe_count = len(game["revealed"] - game["bombs"])
        mult = 1.0 + safe_count * config.BOMB_MULTIPLIER_STEP
        grid_text, kb = _build_bomb_grid(game)

        await safe_edit(update, (
            f"💣 <b>بمب {name}</b>\n"
            f"💰 شرط: <code>{fmt(game['bet'])}</code> DP\n"
            f"📈 ضریب: <b>{mult:.1f}x</b>  |  🟩 امن: {safe_count}\n\n"
            f"{grid_text}"
        ), reply_markup=kb)# ═══════════════════════════════════════════════════════════
#  SECTION 5/12 — TON Withdrawal (Full Flow)
# ═══════════════════════════════════════════

import re
from datetime import datetime

# ── ثابت‌ها ────────────────────────────────────────────────
TON_WALLET_REGEX = re.compile(
    r"^(EQ[A-Za-z0-9_-]{46}|UQ[A-Za-z0-9_-]{46})$"
)

# ── مرحله 1: منوی برداشت TON ─────────────────────────────
async def handle_ton_withdraw_menu(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE):
    """نمایش اطلاعات برداشت + دکمه شروع"""
    query = update.callback_query
    uid = query.from_user.id
    u = db.get_user(uid)
    if not u:
        return

    dp_rate = config.TON_WITHDRAWAL_DP_RATE
    ton_amt = config.TON_WITHDRAWAL_TON_AMOUNT
    min_ton = config.TON_WITHDRAWAL_MIN
    bal = u["balance"]
    ton_bal = u.get("ton_balance", 0.0)

    # محاسبه حداکثر قابل برداشت
    max_ton = (bal / dp_rate) * ton_amt

    text = (
        f"💎 <b>برداشت TON</b>\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"💰 نرخ تبدیل:\n"
        f"   <code>{fmt(dp_rate)}</code> DP = <code>{ton_amt}</code> TON\n\n"
        f"📊 حداقل برداشت: <code>{min_ton}</code> TON\n"
        f"💳 موجودی TON شما: <code>{ton_bal:.4f}</code> TON\n"
        f"💰 موجودی DP شما: <code>{fmt(bal)}</code> DP\n"
        f"📈 حداکثر قابل برداشت: <code>{max_ton:.4f}</code> TON\n\n"
        f"💡 <i>با زیرمجموعه‌گیری راحت می‌توانید برداشت کنید</i>\n\n"
        f"⚠️ آدرس کیف پول TON باید فرمت EQ یا UQ باشد."
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📤 درخواست برداشت", callback_data="ton_start"
        )],
        [InlineKeyboardButton(
            "🔙 بازگشت به منو", callback_data="back_main"
        )],
    ])
    await safe_edit(update, text, reply_markup=kb)


# ── مرحله 2: شروع — درخواست آدرس کیف پول ────────────────
async def cb_ton_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    u = db.get_user(uid)

    # چک حداقل موجودی
    min_dp = (config.TON_WITHDRAWAL_MIN / config.TON_WITHDRAWAL_TON_AMOUNT
              ) * config.TON_WITHDRAWAL_DP_RATE
    if not u or u["balance"] < min_dp:
        await safe_edit(update, (
            f"❌ <b>موجودی کافی نیست!</b>\n\n"
            f"حداقل <code>{fmt(int(min_dp))}</code> DP نیاز دارید.\n"
            f"💡 با زیرمجموعه‌گیری راحت می‌توانید برداشت کنید!"
        ), reply_markup=back_to_main_kb())
        return

    context.user_data["state"] = "ton_wallet"
    context.user_data["ton_step"] = 1

    text = (
        f"💎 <b>برداشت TON — مرحله 1/3</b>\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"📬 آدرس کیف پول TON خود را ارسال کنید:\n\n"
        f"⚠️ فرمت معتبر: <code>EQ...</code> یا <code>UQ...</code>\n"
        f"(48 کاراکتر)\n\n"
        f"❌ از آدرس صرافی استفاده نکنید!"
    )
    await safe_edit(update, text, reply_markup=cancel_only_kb())


# ── هندلر متن: دریافت آدرس کیف پول ──────────────────────
async def msg_ton_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت آدرس کیف پول TON از کاربر"""
    if context.user_data.get("state") != "ton_wallet":
        return

    uid = update.effective_user.id
    wallet = update.message.text.strip()

    # اعتبارسنجی آدرس
    if not TON_WALLET_REGEX.match(wallet):
        await safe_send(update, (
            "❌ <b>آدرس نامعتبر!</b>\n\n"
            "آدرس TON باید با <code>EQ</code> یا <code>UQ</code> شروع شود\n"
            "و 48 کاراکتر باشد.\n\n"
            "🔄 دوباره ارسال کنید:"
        ))
        return

    context.user_data["ton_wallet"] = wallet
    context.user_data["state"] = "ton_amount"
    context.user_data["ton_step"] = 2

    u = db.get_user(uid)
    max_ton = (u["balance"] / config.TON_WITHDRAWAL_DP_RATE
               ) * config.TON_WITHDRAWAL_TON_AMOUNT

    await safe_send(update, (
        f"💎 <b>برداشت TON — مرحله 2/3</b>\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"✅ آدرس کیف پول ثبت شد!\n\n"
        f"💰 حداقل: <code>{config.TON_WITHDRAWAL_MIN}</code> TON\n"
        f"📈 حداکثر: <code>{max_ton:.4f}</code> TON\n\n"
        f"🔢 مبلغ برداشت (به TON) را ارسال کنید:\n"
        f"مثال: <code>0.05</code>"
    ), reply_markup=cancel_only_kb())


# ── هندلر متن: دریافت مبلغ برداشت ────────────────────────
async def msg_ton_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت مبلغ برداشت و نمایش تأیید نهایی"""
    if context.user_data.get("state") != "ton_amount":
        return

    uid = update.effective_user.id
    text = update.message.text.strip()

    # اعتبارسنجی مبلغ
    try:
        amount = float(text)
    except ValueError:
        await safe_send(update, (
            "❌ مبلغ نامعتبر! فقط عدد وارد کنید.\n"
            "مثال: <code>0.05</code>"
        ))
        return

    if amount < config.TON_WITHDRAWAL_MIN:
        await safe_send(update, (
            f"❌ حداقل برداشت <code>{config.TON_WITHDRAWAL_MIN}</code> TON است!"
        ))
        return

    # محاسبه DP مورد نیاز
    dp_needed = int(
        (amount / config.TON_WITHDRAWAL_TON_AMOUNT)
        * config.TON_WITHDRAWAL_DP_RATE
    )

    u = db.get_user(uid)
    if not u or u["balance"] < dp_needed:
        max_ton = (u["balance"] / config.TON_WITHDRAWAL_DP_RATE
                   ) * config.TON_WITHDRAWAL_TON_AMOUNT
        await safe_send(update, (
            f"❌ <b>موجودی کافی نیست!</b>\n\n"
            f"نیاز: <code>{fmt(dp_needed)}</code> DP\n"
            f"موجودی: <code>{fmt(u['balance'])}</code> DP\n"
            f"حداکثر قابل برداشت: <code>{max_ton:.4f}</code> TON\n\n"
            f"🔄 مبلغ کمتری وارد کنید:"
        ))
        return

    # ذخیره و نمایش تأیید
    context.user_data["ton_amount"] = amount
    context.user_data["ton_dp_cost"] = dp_needed
    context.user_data["state"] = "ton_confirm"
    context.user_data["ton_step"] = 3

    wallet = context.user_data["ton_wallet"]
    masked = mask_wallet(wallet)

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ تأیید برداشت", callback_data="ton_confirm_yes"
            ),
            InlineKeyboardButton(
                "❌ لغو", callback_data="ton_confirm_no"
            ),
        ],
    ])

    await safe_send(update, (
        f"💎 <b>تأیید برداشت TON</b>\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"📬 کیف پول: <code>{masked}</code>\n"
        f"💎 مبلغ: <code>{amount:.4f}</code> TON\n"
        f"💰 هزینه: <code>{fmt(dp_needed)}</code> DP\n"
        f"📊 موجودی فعلی: <code>{fmt(u['balance'])}</code> DP\n"
        f"📊 موجودی بعد: <code>{fmt(u['balance'] - dp_needed)}</code> DP\n\n"
        f"⚠️ <b>آدرس کیف پول را چک کنید!</b>\n"
        f"پس از تأیید، قابل بازگشت نیست."
    ), reply_markup=kb)


# ── تأیید نهایی برداشت ───────────────────────────────────
async def cb_ton_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    uid = query.from_user.id

    # ── لغو ──
    if data == "ton_confirm_no":
        await query.answer("❌ لغو شد")
        clear_user_state(context)
        await send_welcome(update, context, uid,
                           query.from_user.first_name or "کاربر")
        return

    # ── تأیید ──
    if data != "ton_confirm_yes":
        return

    await query.answer()

    wallet = context.user_data.get("ton_wallet", "")
    amount = context.user_data.get("ton_amount", 0.0)
    dp_cost = context.user_data.get("ton_dp_cost", 0)

    if not wallet or amount <= 0 or dp_cost <= 0:
        await safe_edit(update, "❌ خطا در اطلاعات. دوباره تلاش کنید.",
                        reply_markup=back_to_main_kb())
        clear_user_state(context)
        return

    # چک مجدد موجودی (جلوگیری از race condition)
    u = db.get_user(uid)
    if not u or u["balance"] < dp_cost:
        await safe_edit(update, (
            "❌ <b>موجودی کافی نیست!</b>\n"
            "ممکن است موجودی شما تغییر کرده باشد."
        ), reply_markup=back_to_main_kb())
        clear_user_state(context)
        return

    # کسر DP
    db.add_balance(uid, -dp_cost)

    # ثبت درخواست برداشت
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.add_ton_withdrawal(uid, wallet, amount, dp_cost, now_str)

    # ارسال به کانال لاگ
    masked = mask_wallet(wallet)
    username = query.from_user.username or "—"
    first_name = html.escape(query.from_user.first_name or "کاربر")

    log_text = (
        f"💎 <b>درخواست برداشت TON جدید</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 کاربر: {first_name}\n"
        f"🏷 یوزرنیم: @{html.escape(username)}\n"
        f"🆔 آیدی: <code>{uid}</code>\n\n"
        f"📬 کیف پول: <code>{masked}</code>\n"
        f"💎 مبلغ: <code>{amount:.4f}</code> TON\n"
        f"💰 هزینه DP: <code>{fmt(dp_cost)}</code> DP\n"
        f"📊 موجودی باقی: <code>{fmt(u['balance'] - dp_cost)}</code> DP\n\n"
        f"🕐 زمان: {now_str}\n"
        f"━━━━━━━━━━━━━━━"
    )
    await send_log(context, log_text)

    # پیام موفقیت به کاربر
    clear_user_state(context)
    await safe_edit(update, (
        f"✅ <b>درخواست برداشت ثبت شد!</b>\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"💎 مبلغ: <code>{amount:.4f}</code> TON\n"
        f"📬 کیف پول: <code>{masked}</code>\n"
        f"💰 کسر شده: <code>{fmt(dp_cost)}</code> DP\n\n"
        f"⏳ درخواست شما در صف بررسی است.\n"
        f"معمولاً ظرف 24 ساعت پردازش می‌شود.\n\n"
        f"💡 <i>با زیرمجموعه‌گیری راحت می‌توانید برداشت کنید!</i>"
    ), reply_markup=back_to_main_kb())# ═══════════════════════════════════════════════════════════
#  SECTION 6/12 — Bank, Miner, Factory, Transfer
# ═══════════════════════════════════════════════════════════

import math
from datetime import datetime

# ── ثابت‌های ماینر ────────────────────────────────────────
MINER_LEVELS = {
    1: {"ton": 0.01, "usdt": 0.03, "upgrade_cost": 20_000_000},
    2: {"ton": 0.03, "usdt": 0.05, "upgrade_cost": 100_000_000},
    3: {"ton": 0.04, "usdt": 0.07, "upgrade_cost": 300_000_000},
    4: {"ton": 0.06, "usdt": 0.09, "upgrade_cost": 500_000_000},
    5: {"ton": 0.09, "usdt": 0.12, "upgrade_cost": None},
}

FACTORY_LEVELS = {
    1: {"cost": 0,             "production": 500},
    2: {"cost": 10_000_000,    "production": 1_500},
    3: {"cost": 50_000_000,    "production": 4_000},
    4: {"cost": 200_000_000,   "production": 10_000},
    5: {"cost": 500_000_000,   "production": 25_000},
}


# ══════════════════════════════════════════════════════════
#  1. 🏦 بانک دارکی  (PV — شیشه‌ای)
# ══════════════════════════════════════════════════════════
async def handle_bank_menu(update: Update,
                           context: ContextTypes.DEFAULT_TYPE):
    """منوی بانک: موجودی، سود، واریز، برداشت"""
    query = update.callback_query
    uid = query.from_user.id
    u = db.get_user(uid)
    if not u:
        return

    bank_bal = u.get("bank_balance", 0)
    bank_lock = u.get("bank_lock_until", 0)
    now = int(datetime.now().timestamp())
    lock_remain = max(0, bank_lock - now)

    # محاسبه سود انباشته
    last_interest = u.get("bank_last_interest", 0)
    hours_since = (now - last_interest) / 3600 if last_interest else 0
    periods = int(hours_since / 48)
    accrued = 0
    if periods > 0 and bank_bal > 0:
        accrued = int(bank_bal * config.BANK_INTEREST_RATE * periods)

    if lock_remain > 0:
        h, m, s = seconds_to_hms(lock_remain)
        lock_text = f"🔒 قفل: <b>{h}:{m:02d}:{s:02d}</b>"
    else:
        lock_text = "🔓 قفل: <b>باز</b>"

    text = (
        f"🏦 <b>بانک دارکی</b>\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"💰 موجودی بانک: <code>{fmt(bank_bal)}</code> DP\n"
        f"📈 سود انباشته: <code>+{fmt(accrued)}</code> DP\n"
        f"💹 نرخ سود: <b>3%</b> هر 48 ساعت\n"
        f"{lock_text}\n\n"
        f"💡 واریز → 48 ساعت قفل → برداشت با سود!"
    )

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💳 واریز", callback_data="bank_deposit"),
            InlineKeyboardButton("💸 برداشت", callback_data="bank_withdraw"),
        ],
        [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="back_main")],
    ])
    await safe_edit(update, text, reply_markup=kb)


async def cb_bank_deposit(update: Update,
                          context: ContextTypes.DEFAULT_TYPE):
    """شروع واریز به بانک"""
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "bank_deposit"
    await safe_edit(update, (
        "🏦 <b>واریز به بانک</b>\n\n"
        "💰 مبلغ واریز (DP) را ارسال کنید:\n"
        "مثال: <code>1000000</code>"
    ), reply_markup=cancel_only_kb())


async def msg_bank_deposit(update: Update,
                           context: ContextTypes.DEFAULT_TYPE):
    """دریافت مبلغ واریز"""
    if context.user_data.get("state") != "bank_deposit":
        return

    uid = update.effective_user.id
    try:
        amount = int(update.message.text.strip())
    except ValueError:
        await safe_send(update, "❌ مبلغ باید عدد باشد!")
        return

    if amount <= 0:
        await safe_send(update, "❌ مبلغ باید مثبت باشد!")
        return

    u = db.get_user(uid)
    if not u or u["balance"] < amount:
        await safe_send(update, "❌ موجودی کافی نیست!")
        return

    # کسر از موجودی + اضافه به بانک
    db.add_balance(uid, -amount)
    db.add_bank_balance(uid, amount)

    # قفل 48 ساعته
    lock_until = int(datetime.now().timestamp()) + config.BANK_LOCK_PERIOD
    db.set_bank_lock(uid, lock_until)
    db.set_bank_last_interest(uid, int(datetime.now().timestamp()))

    clear_user_state(context)
    await safe_send(update, (
        f"✅ <b>واریز موفق!</b>\n\n"
        f"💰 مبلغ: <code>{fmt(amount)}</code> DP\n"
        f"🏦 موجودی بانک: <code>{fmt(u.get('bank_balance', 0) + amount)}</code> DP\n"
        f"🔒 قفل: 48 ساعت\n\n"
        f"💡 بعد از 48 ساعت، 3% سود دریافت می‌کنید!"
    ), reply_markup=back_to_main_kb())


async def cb_bank_withdraw(update: Update,
                           context: ContextTypes.DEFAULT_TYPE):
    """برداشت از بانک (اصل + سود)"""
    query = update.callback_query
    uid = query.from_user.id
    u = db.get_user(uid)
    if not u:
        return

    bank_bal = u.get("bank_balance", 0)
    if bank_bal <= 0:
        await query.answer("❌ موجودی بانک خالی است!", show_alert=True)
        return

    now = int(datetime.now().timestamp())
    lock_until = u.get("bank_lock_until", 0)
    if now < lock_until:
        h, m, s = seconds_to_hms(lock_until - now)
        await query.answer(
            f"🔒 قفل تا {h}:{m:02d}:{s:02d} دیگه!", show_alert=True
        )
        return

    # محاسبه سود
    last_interest = u.get("bank_last_interest", 0)
    hours_since = (now - last_interest) / 3600 if last_interest else 0
    periods = int(hours_since / 48)
    interest = int(bank_bal * config.BANK_INTEREST_RATE * periods) if periods > 0 else 0
    total = bank_bal + interest

    # انتقال به موجودی
    db.add_balance(uid, total)
    db.set_bank_balance(uid, 0)
    db.set_bank_lock(uid, 0)
    db.set_bank_last_interest(uid, 0)

    await query.answer()
    await safe_edit(update, (
        f"✅ <b>برداشت از بانک موفق!</b>\n\n"
        f"💰 اصل: <code>{fmt(bank_bal)}</code> DP\n"
        f"📈 سود: <code>+{fmt(interest)}</code> DP\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💵 مجموع: <b>{fmt(total)}</b> DP"
    ), reply_markup=back_to_main_kb())


# ══════════════════════════════════════════════════════════
#  2. ⛏ ماینر دارکی  (فقط گروه)
# ══════════════════════════════════════════════════════════
async def cmd_miner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private":
        await safe_send(update, "⚠️ ماینر فقط در گروه فعال است!")
        return

    uid = update.effective_user.id
    u = db.get_user(uid)
    if not u:
        return

    miner_lvl = u.get("miner_level", 0)

    # ── ماینر ندارد ──
    if miner_lvl == 0:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"⛏ خرید ماینر ({fmt(config.MINER_BUY_COST)} DP)",
                callback_data="miner_buy"
            )]
        ])
        await update.message.reply_text(
            f"⛏ <b>ماینر دارکی</b>\n\n"
            f"❌ شما ماینر ندارید!\n\n"
            f"💰 هزینه خرید: <code>{fmt(config.MINER_BUY_COST)}</code> DP\n"
            f"📈 درآمد سطح 1: 0.01 TON یا 0.03 USDT در ساعت\n"
            f"⚡ هزینه برق: <code>{fmt(config.MINER_ELECTRICITY_COST)}</code> DP/h\n\n"
            f"💡 ماینر 5 سطح دارد. هرچه بالاتر، درآمد بیشتر!",
            reply_markup=kb,
        )
        return

    # ── ماینر دارد → منو ──
    info = MINER_LEVELS[miner_lvl]
    currency = u.get("miner_currency", "ton")
    cur_label = "TON" if currency == "ton" else "USDT"
    income = info[cur_label]

    # محاسبه درآمد قابل جمع‌آوری
    last_collect = u.get("miner_last_collect", 0)
    now = int(datetime.now().timestamp())
    hours = (now - last_collect) / 3600 if last_collect else 0
    gross_income = income * hours
    electricity = config.MINER_ELECTRICITY_COST * hours
    net_dp = gross_income - electricity  # خالص (ممکن است منفی)

    # نمایش درآمد بر اساس ارز انتخابی
    if currency == "ton":
        income_display = f"{gross_income:.4f} TON"
    else:
        income_display = f"{gross_income:.4f} USDT"

    upgrade_text = ""
    if miner_lvl < 5:
        next_info = MINER_LEVELS[miner_lvl + 1]
        upgrade_text = (
            f"\n⬆️ ارتقا به سطح {miner_lvl + 1}: "
            f"<code>{fmt(next_info['upgrade_cost'])}</code> DP"
        )
    else:
        upgrade_text = "\n🏆 حداکثر سطح!"

    text = (
        f"⛏ <b>ماینر دارکی</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📊 سطح: <b>{miner_lvl}</b> / 5\n"
        f"💱 ارز: <b>{cur_label}</b>\n"
        f"📈 درآمد: <code>{income}</code> {cur_label}/h\n"
        f"⚡ برق: <code>{fmt(config.MINER_ELECTRICITY_COST)}</code> DP/h\n\n"
        f"💰 درآمد قابل جمع: <code>{income_display}</code>\n"
        f"⚡ هزینه برق: <code>{fmt(int(electricity))}</code> DP"
        f"{upgrade_text}"
    )

    kb_rows = [
        [
            InlineKeyboardButton("💰 جمع‌آوری", callback_data="miner_collect"),
            InlineKeyboardButton("💱 تغییر ارز", callback_data="miner_switch"),
        ],
    ]
    if miner_lvl < 5:
        kb_rows.append([
            InlineKeyboardButton("⬆️ ارتقا", callback_data="miner_upgrade")
        ])
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb_rows))


async def cb_miner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """هندلر دکمه‌های ماینر"""
    query = update.callback_query
    data = query.data
    uid = query.from_user.id
    u = db.get_user(uid)
    if not u:
        return

    # ── خرید ماینر ──
    if data == "miner_buy":
        if u["balance"] < config.MINER_BUY_COST:
            await query.answer("❌ موجودی کافی نیست!", show_alert=True)
            return
        await query.answer()
        db.add_balance(uid, -config.MINER_BUY_COST)
        db.set_miner_level(uid, 1)
        db.set_miner_currency(uid, "ton")
        db.set_miner_last_collect(uid, int(datetime.now().timestamp()))
        await safe_edit(update, (
            f"✅ <b>ماینر خریداری شد!</b>\n\n"
            f"⛏ سطح: 1\n"
            f"💱 ارز: TON\n"
            f"📈 درآمد: 0.01 TON/h\n"
            f"⚡ برق: {fmt(config.MINER_ELECTRICITY_COST)} DP/h\n\n"
            f"💡 دستور <code>ماینر دارکی</code> را بزنید!"
        ))
        return

    miner_lvl = u.get("miner_level", 0)
    if miner_lvl == 0:
        await query.answer("❌ اول ماینر بخرید!", show_alert=True)
        return

    # ── جمع‌آوری ──
    if data == "miner_collect":
        await query.answer()
        info = MINER_LEVELS[miner_lvl]
        currency = u.get("miner_currency", "ton")
        income_rate = info[currency]
        last_collect = u.get("miner_last_collect", 0)
        now = int(datetime.now().timestamp())
        hours = (now - last_collect) / 3600 if last_collect else 0

        if hours < 0.1:
            await safe_edit(update, "⏳ هنوز درآمدی جمع نشده!")
            return

        gross = income_rate * hours
        elec_dp = int(config.MINER_ELECTRICITY_COST * hours)

        # کسر برق از موجودی DP
        if u["balance"] < elec_dp:
            await safe_edit(update, (
                f"❌ <b>موجودی DP کافی برای برق نیست!</b>\n\n"
                f"⚡ هزینه برق: <code>{fmt(elec_dp)}</code> DP\n"
                f"💰 موجودی: <code>{fmt(u['balance'])}</code> DP\n\n"
                f"💡 ماینر بدون برق کار نمی‌کند!"
            ))
            return

        db.add_balance(uid, -elec_dp)
        db.set_miner_last_collect(uid, now)

        # اضافه درآمد به موجودی TON/USDT
        if currency == "ton":
            db.add_ton_balance(uid, gross)
            cur_label = "TON"
        else:
            db.add_usdt_balance(uid, gross)
            cur_label = "USDT"

        await safe_edit(update, (
            f"✅ <b>جمع‌آوری موفق!</b>\n\n"
            f"💰 درآمد: <code>{gross:.4f}</code> {cur_label}\n"
            f"⚡ برق: <code>-{fmt(elec_dp)}</code> DP\n"
            f"⏱ مدت: {hours:.1f} ساعت"
        ))
        return

    # ── تغییر ارز ──
    if data == "miner_switch":
        await query.answer()
        cur = u.get("miner_currency", "ton")
        new_cur = "usdt" if cur == "ton" else "ton"
        db.set_miner_currency(uid, new_cur)
        label = "USDT" if new_cur == "usdt" else "TON"
        await safe_edit(update, f"✅ ارز ماینر به <b>{label}</b> تغییر کرد!")
        return

    # ── ارتقا ──
    if data == "miner_upgrade":
        if miner_lvl >= 5:
            await query.answer("🏆 حداکثر سطح!", show_alert=True)
            return
        await query.answer()
        next_info = MINER_LEVELS[miner_lvl + 1]
        cost = next_info["upgrade_cost"]
        if u["balance"] < cost:
            await safe_edit(update, (
                f"❌ موجودی کافی نیست!\n"
                f"نیاز: <code>{fmt(cost)}</code> DP"
            ))
            return
        db.add_balance(uid, -cost)
        db.set_miner_level(uid, miner_lvl + 1)
        await safe_edit(update, (
            f"✅ <b>ماینر ارتقا یافت!</b>\n\n"
            f"⛏ سطح: <b>{miner_lvl + 1}</b>\n"
            f"📈 TON: {next_info['ton']}/h\n"
            f"📈 USDT: {next_info['usdt']}/h"
        ))
        return


# ══════════════════════════════════════════════════════════
#  3. 🏭 کارخانه دارکی  (فقط گروه)
# ══════════════════════════════════════════════════════════
async def cmd_factory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private":
        await safe_send(update, "⚠️ کارخانه فقط در گروه فعال است!")
        return

    uid = update.effective_user.id
    u = db.get_user(uid)
    if not u:
        return

    fac_lvl = u.get("factory_level", 1)
    info = FACTORY_LEVELS[fac_lvl]
    last_collect = u.get("factory_last_collect", 0)
    now = int(datetime.now().timestamp())
    hours = (now - last_collect) / 3600 if last_collect else 0
    pending = int(info["production"] * hours)

    upgrade_text = ""
    if fac_lvl < 5:
        next_info = FACTORY_LEVELS[fac_lvl + 1]
        upgrade_text = (
            f"\n⬆️ ارتقا به سطح {fac_lvl + 1}: "
            f"<code>{fmt(next_info['cost'])}</code> DP"
        )
    else:
        upgrade_text = "\n🏆 حداکثر سطح!"

    text = (
        f"🏭 <b>کارخانه دارکی</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📊 سطح: <b>{fac_lvl}</b> / 5\n"
        f"📈 تولید: <code>{fmt(info['production'])}</code> DP/h\n"
        f"💰 قابل جمع: <code>{fmt(pending)}</code> DP\n"
        f"⏱ از آخرین جمع: {hours:.1f} ساعت"
        f"{upgrade_text}"
    )

    kb_rows = [
        [InlineKeyboardButton("💰 جمع‌آوری", callback_data="fac_collect")],
    ]
    if fac_lvl < 5:
        kb_rows.append([
            InlineKeyboardButton("⬆️ ارتقا", callback_data="fac_upgrade")
        ])
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb_rows))


async def cb_factory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """هندلر دکمه‌های کارخانه"""
    query = update.callback_query
    data = query.data
    uid = query.from_user.id
    u = db.get_user(uid)
    if not u:
        return

    fac_lvl = u.get("factory_level", 1)
    info = FACTORY_LEVELS[fac_lvl]

    # ── جمع‌آوری ──
    if data == "fac_collect":
        await query.answer()
        last_collect = u.get("factory_last_collect", 0)
        now = int(datetime.now().timestamp())
        hours = (now - last_collect) / 3600 if last_collect else 0
        pending = int(info["production"] * hours)

        if pending < 1:
            await safe_edit(update, "⏳ هنوز تولیدی جمع نشده!")
            return

        db.add_balance(uid, pending)
        db.set_factory_last_collect(uid, now)
        await safe_edit(update, (
            f"✅ <b>جمع‌آوری کارخانه!</b>\n\n"
            f"💰 تولید: <code>+{fmt(pending)}</code> DP\n"
            f"⏱ مدت: {hours:.1f} ساعت"
        ))
        return

    # ── ارتقا ──
    if data == "fac_upgrade":
        if fac_lvl >= 5:
            await query.answer("🏆 حداکثر سطح!", show_alert=True)
            return
        await query.answer()
        next_info = FACTORY_LEVELS[fac_lvl + 1]
        cost = next_info["cost"]
        if u["balance"] < cost:
            await safe_edit(update, (
                f"❌ موجودی کافی نیست!\n"
                f"نیاز: <code>{fmt(cost)}</code> DP"
            ))
            return
        db.add_balance(uid, -cost)
        db.set_factory_level(uid, fac_lvl + 1)
        db.set_factory_last_collect(uid, int(datetime.now().timestamp()))
        await safe_edit(update, (
            f"✅ <b>کارخانه ارتقا یافت!</b>\n\n"
            f"🏭 سطح: <b>{fac_lvl + 1}</b>\n"
            f"📈 تولید: <code>{fmt(next_info['production'])}</code> DP/h"
        ))
        return


# ══════════════════════════════════════════════════════════
#  4. 💸 انتقال  (فقط گروه — ریپلای)
# ══════════════════════════════════════════════════════════
async def cmd_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private":
        await safe_send(update, "⚠️ انتقال فقط در گروه فعال است!")
        return

    uid = update.effective_user.id
    msg = update.message

    # چک ریپلای
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await safe_send(update, (
            "❌ <b>روی کاربر مقصد ریپلای کنید!</b>\n\n"
            "مثال: ریپلای روی پیام کاربر + <code>انتقال 100000</code>"
        ))
        return

    target_id = msg.reply_to_message.from_user.id
    if target_id == uid:
        await safe_send(update, "❌ نمی‌توانید به خودتان انتقال دهید!")
        return
    if target_id == context.bot.id:
        await safe_send(update, "❌ نمی‌توانید به ربات انتقال دهید!")
        return

    # استخراج مبلغ
    amount, err = parse_bet(msg.text, 1000)
    if err:
        await safe_send(update, err)
        return

    # چک محدودیت روزانه
    daily_count = db.get_transfer_count_today(uid)
    if daily_count >= config.TRANSFER_DAILY_LIMIT:
        await safe_send(update, (
            f"❌ <b>محدودیت روزانه!</b>\n"
            f"حداکثر {config.TRANSFER_DAILY_LIMIT} انتقال در روز."
        ))
        return

    # چک موجودی (مبلغ + کارمزد)
    fee = int(amount * config.TRANSFER_FEE)
    total_cost = amount + fee
    u = db.get_user(uid)
    if not u or u["balance"] < total_cost:
        await safe_send(update, (
            f"❌ موجودی کافی نیست!\n"
            f"💰 مبلغ: <code>{fmt(amount)}</code> DP\n"
            f"💸 کارمزد (10%): <code>{fmt(fee)}</code> DP\n"
            f"📊 نیاز: <code>{fmt(total_cost)}</code> DP"
        ))
        return

    # ثبت مقصد
    target_user = msg.reply_to_message.from_user
    db.add_user(target_id, target_user.username or "",
                target_user.first_name or "کاربر", None)

    # انجام انتقال
    db.add_balance(uid, -total_cost)
    db.add_balance(target_id, amount)
    db.add_transfer_record(uid)

    sender = html.escape(update.effective_user.first_name or "کاربر")
    receiver = html.escape(target_user.first_name or "کاربر")

    await safe_send(update, (
        f"✅ <b>انتقال موفق!</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 فرستنده: {sender}\n"
        f"👤 گیرنده: {receiver}\n"
        f"💰 مبلغ: <code>{fmt(amount)}</code> DP\n"
        f"💸 کارمزد: <code>{fmt(fee)}</code> DP\n"
        f"📊 کسر شده: <code>{fmt(total_cost)}</code> DP\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🔄 انتقال‌های امروز: {daily_count + 1}/{config.TRANSFER_DAILY_LIMIT}"
    ))# ═══════════════════════════════════════════════════════════
#  SECTION 7/12 — Shop, Gift, Tasks, Like, Convert, Stars, BuyDP
# ═══════════════════════════════════════════════════════════

from datetime import datetime, timedelta

# ══════════════════════════════════════════════════════════
#  1. 🛒 فروشگاه  (PV — شیشه‌ای)
# ══════════════════════════════════════════════════════════
async def handle_shop_menu(update: Update,
                           context: ContextTypes.DEFAULT_TYPE):
    """نمایش پلن‌های فروشگاه"""
    query = update.callback_query
    uid = query.from_user.id

    plans = db.get_shop_plans()
    if not plans:
        await safe_edit(update, (
            "🛒 <b>فروشگاه</b>\n\n"
            "❌ فعلاً پلنی موجود نیست!"
        ), reply_markup=back_to_main_kb())
        return

    lines = ["🛒 <b>فروشگاه دارک پوینت</b>", "━━━━━━━━━━━━━━━", ""]
    kb_rows = []

    for p in plans:
        pid = p["id"]
        name = html.escape(p["name"])
        price = p["price"]
        stock = p["stock"]
        lines.append(
            f"📦 <b>{name}</b>\n"
            f"   💰 <code>{fmt(price)}</code> DP"
            f"  |  📊 موجودی: {stock}"
        )
        if stock > 0:
            kb_rows.append([
                InlineKeyboardButton(
                    f"🛒 {name} — {fmt(price)} DP",
                    callback_data=f"shop_buy_{pid}"
                )
            ])
        else:
            lines.append("   ❌ ناموجود")

    kb_rows.append(
        [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="back_main")]
    )
    await safe_edit(update, "\n".join(lines),
                    reply_markup=InlineKeyboardMarkup(kb_rows))


async def cb_shop_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """خرید پلن از فروشگاه"""
    query = update.callback_query
    uid = query.from_user.id
    pid = int(query.data.split("_")[2])

    plan = db.get_shop_plan(pid)
    if not plan:
        await query.answer("❌ پلن یافت نشد!", show_alert=True)
        return
    if plan["stock"] <= 0:
        await query.answer("❌ این پلن ناموجود است!", show_alert=True)
        return

    u = db.get_user(uid)
    if not u or u["balance"] < plan["price"]:
        await query.answer("❌ موجودی کافی نیست!", show_alert=True)
        return

    await query.answer()
    db.add_balance(uid, -plan["price"])
    db.decrease_plan_stock(pid)

    # ارسال کانفیگ / محتوا
    content = plan.get("content", "")
    if content:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=(
                    f"✅ <b>خرید موفق!</b>\n\n"
                    f"📦 {html.escape(plan['name'])}\n"
                    f"━━━━━━━━━━━━━━━\n\n"
                    f"{content}\n\n"
                    f"💡 ادمین کانفیگ رو از پنل سنایی بزودی ارسال می‌کند"
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    # اگر فایل دارد
    file_id = plan.get("file_id", "")
    file_type = plan.get("file_type", "")
    if file_id:
        try:
            if file_type == "photo":
                await context.bot.send_photo(uid, file_id)
            elif file_type == "video":
                await context.bot.send_video(uid, file_id)
            elif file_type == "document":
                await context.bot.send_document(uid, file_id)
        except Exception:
            pass

    await safe_edit(update, (
        f"✅ <b>خرید موفق!</b>\n\n"
        f"📦 {html.escape(plan['name'])}\n"
        f"💰 هزینه: <code>{fmt(plan['price'])}</code> DP\n\n"
        f"💡 ادمین کانفیگ رو از پنل سنایی بزودی ارسال می‌کند"
    ), reply_markup=back_to_main_kb())

    # لاگ
    await send_log(context, (
        f"🛒 <b>خرید فروشگاه</b>\n"
        f"👤 {html.escape(query.from_user.first_name or 'کاربر')} "
        f"(@{html.escape(query.from_user.username or '—')})\n"
        f"📦 {html.escape(plan['name'])} — <code>{fmt(plan['price'])}</code> DP"
    ))


# ══════════════════════════════════════════════════════════
#  2. 🎁 هدیه  (PV — شیشه‌ای)
# ══════════════════════════════════════════════════════════
async def handle_gift_menu(update: Update,
                           context: ContextTypes.DEFAULT_TYPE):
    """منوی هدیه: خرس تدی + پلن‌های سفارشی"""
    query = update.callback_query

    gift_plans = db.get_gift_plans()
    lines = [
        "🎁 <b>هدیه دارک پوینت</b>",
        "━━━━━━━━━━━━━━━",
        "",
        "🧸 <b>خرس تدی</b>",
        "   یک هدیه ویژه برای دوستانت!",
        "",
    ]
    kb_rows = [
        [InlineKeyboardButton("🧸 ارسال خرس تدی", callback_data="gift_teddy")]
    ]

    for gp in gift_plans:
        gname = html.escape(gp["name"])
        gprice = gp["price"]
        lines.append(
            f"🎀 <b>{gname}</b>\n"
            f"   💰 <code>{fmt(gprice)}</code> DP"
        )
        kb_rows.append([
            InlineKeyboardButton(
                f"🎁 {gname} — {fmt(gprice)} DP",
                callback_data=f"gift_buy_{gp['id']}"
            )
        ])

    kb_rows.append(
        [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="back_main")]
    )
    await safe_edit(update, "\n".join(lines),
                    reply_markup=InlineKeyboardMarkup(kb_rows))


async def cb_gift_teddy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ارسال خرس تدی — درخواست آیدی گیرنده"""
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "gift_teddy_target"
    await safe_edit(update, (
        "🧸 <b>ارسال خرس تدی</b>\n\n"
        "🆔 آیدی عددی کاربر مقصد را ارسال کنید:\n"
        "(کاربر می‌تواند با دستور <code>ایدی عددی</code> آیدی خود را ببیند)"
    ), reply_markup=cancel_only_kb())


async def msg_gift_teddy_target(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    """دریافت آیدی مقصد خرس تدی"""
    if context.user_data.get("state") != "gift_teddy_target":
        return

    try:
        target_id = int(update.message.text.strip())
    except ValueError:
        await safe_send(update, "❌ آیدی باید عدد باشد!")
        return

    if target_id == update.effective_user.id:
        await safe_send(update, "❌ نمی‌توانید به خودتان هدیه دهید!")
        return

    clear_user_state(context)
    sender = html.escape(update.effective_user.first_name or "کاربر")

    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                f"🧸 <b>یک خرس تدی از {sender}!</b>\n\n"
                f"🖤 دوستت یادت بود!"
            ),
            parse_mode="HTML",
        )
        await safe_send(update, "✅ خرس تدی ارسال شد! 🧸",
                        reply_markup=back_to_main_kb())
    except Exception:
        await safe_send(update,
                        "❌ ارسال نشد. آیدی را چک کنید.",
                        reply_markup=back_to_main_kb())


async def cb_gift_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """خرید پلن هدیه"""
    query = update.callback_query
    uid = query.from_user.id
    gid = int(query.data.split("_")[2])

    gp = db.get_gift_plan(gid)
    if not gp:
        await query.answer("❌ یافت نشد!", show_alert=True)
        return

    u = db.get_user(uid)
    if not u or u["balance"] < gp["price"]:
        await query.answer("❌ موجودی کافی نیست!", show_alert=True)
        return

    await query.answer()
    context.user_data["state"] = "gift_plan_target"
    context.user_data["gift_plan_id"] = gid
    await safe_edit(update, (
        f"🎁 <b>هدیه: {html.escape(gp['name'])}</b>\n"
        f"💰 هزینه: <code>{fmt(gp['price'])}</code> DP\n\n"
        f"🆔 آیدی عددی کاربر مقصد را ارسال کنید:"
    ), reply_markup=cancel_only_kb())


async def msg_gift_plan_target(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
    """دریافت آیدی مقصد پلن هدیه"""
    if context.user_data.get("state") != "gift_plan_target":
        return

    uid = update.effective_user.id
    try:
        target_id = int(update.message.text.strip())
    except ValueError:
        await safe_send(update, "❌ آیدی باید عدد باشد!")
        return

    gid = context.user_data.get("gift_plan_id")
    gp = db.get_gift_plan(gid)
    if not gp:
        clear_user_state(context)
        return

    u = db.get_user(uid)
    if not u or u["balance"] < gp["price"]:
        await safe_send(update, "❌ موجودی کافی نیست!")
        clear_user_state(context)
        return

    db.add_balance(uid, -gp["price"])
    clear_user_state(context)

    sender = html.escape(update.effective_user.first_name or "کاربر")
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                f"🎁 <b>هدیه از {sender}!</b>\n\n"
                f"🎀 {html.escape(gp['name'])}\n"
                f"💡 ادمین کانفیگ رو از پنل سنایی بزودی ارسال می‌کند"
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass

    await safe_send(update, (
        f"✅ <b>هدیه ارسال شد!</b>\n\n"
        f"🎀 {html.escape(gp['name'])}\n"
        f"💰 هزینه: <code>{fmt(gp['price'])}</code> DP"
    ), reply_markup=back_to_main_kb())


# ══════════════════════════════════════════════════════════
#  3. 📋 ماموریت‌ها  (PV — شیشه‌ای)
# ══════════════════════════════════════════════════════════
async def handle_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش ماموریت‌های فعال"""
    query = update.callback_query
    uid = query.from_user.id

    tasks = db.get_active_tasks()
    if not tasks:
        await safe_edit(update, (
            "📋 <b>ماموریت‌ها</b>\n\n"
            "✅ فعلاً ماموریتی فعال نیست!"
        ), reply_markup=back_to_main_kb())
        return

    lines = ["📋 <b>ماموریت‌های دارک پوینت</b>", "━━━━━━━━━━━━━━━", ""]
    kb_rows = []

    for t in tasks:
        tid = t["id"]
        tname = html.escape(t["name"])
        reward = t["reward"]
        ttype = t.get("type", "channel")
        completed = db.is_task_completed(uid, tid)

        if completed:
            lines.append(f"✅ {tname} — <code>{fmt(reward)}</code> DP")
        else:
            lines.append(f"⬜ {tname} — <code>{fmt(reward)}</code> DP")
            if ttype == "channel":
                link = t.get("link", "")
                if link:
                    kb_rows.append([
                        InlineKeyboardButton(f"🔗 {tname}", url=link)
                    ])
                kb_rows.append([
                    InlineKeyboardButton(
                        f"✅ انجام دادم — {tname}",
                        callback_data=f"task_check_{tid}"
                    )
                ])
            elif ttype == "screenshot":
                kb_rows.append([
                    InlineKeyboardButton(
                        f"📸 ارسال اسکرین‌شات — {tname}",
                        callback_data=f"task_ss_{tid}"
                    )
                ])

    kb_rows.append(
        [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="back_main")]
    )
    await safe_edit(update, "\n".join(lines),
                    reply_markup=InlineKeyboardMarkup(kb_rows))


async def cb_task_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """چک انجام ماموریت کانال"""
    query = update.callback_query
    uid = query.from_user.id
    tid = int(query.data.split("_")[2])

    task = db.get_task(tid)
    if not task:
        await query.answer("❌ ماموریت یافت نشد!", show_alert=True)
        return

    # چک عضویت در کانال ماموریت
    channel = task.get("channel_id", "")
    if channel:
        try:
            member = await context.bot.get_chat_member(
                chat_id=int(channel), user_id=uid
            )
            if member.status not in ("member", "administrator", "creator"):
                await query.answer(
                    "❌ هنوز عضو کانال نشدی!", show_alert=True
                )
                return
        except Exception:
            await query.answer(
                "⚠️ خطا در بررسی. بعداً تلاش کنید.", show_alert=True
            )
            return

    await query.answer("✅ ماموریت انجام شد!")
    db.complete_task(uid, tid)
    db.add_balance(uid, task["reward"])

    await safe_edit(update, (
        f"✅ <b>ماموریت تکمیل شد!</b>\n\n"
        f"📋 {html.escape(task['name'])}\n"
        f"💰 جایزه: <code>+{fmt(task['reward'])}</code> DP"
    ), reply_markup=back_to_main_kb())


async def cb_task_screenshot(update: Update,
                             context: ContextTypes.DEFAULT_TYPE):
    """شروع ماموریت اسکرین‌شات"""
    query = update.callback_query
    await query.answer()
    tid = int(query.data.split("_")[2])
    context.user_data["state"] = "task_screenshot"
    context.user_data["task_id"] = tid
    await safe_edit(update, (
        "📸 <b>ماموریت اسکرین‌شات</b>\n\n"
        "لطفاً اسکرین‌شات انجام ماموریت را ارسال کنید.\n"
        "⏳ پس از تأیید ادمین، جایزه واریز می‌شود."
    ), reply_markup=cancel_only_kb())


async def msg_task_screenshot(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    """دریافت اسکرین‌شات ماموریت"""
    if context.user_data.get("state") != "task_screenshot":
        return

    uid = update.effective_user.id
    tid = context.user_data.get("task_id")
    msg = update.message

    # دریافت فایل
    file_id = None
    if msg.photo:
        file_id = msg.photo[-1].file_id
        ftype = "photo"
    elif msg.document:
        file_id = msg.document.file_id
        ftype = "document"
    else:
        await safe_send(update, "❌ لطفاً عکس یا فایل ارسال کنید!")
        return

    # ارسال به ادمین برای تأیید
    username = html.escape(update.effective_user.username or "—")
    first_name = html.escape(update.effective_user.first_name or "کاربر")

    try:
        admin_id = config.ADMIN_ID
        await context.bot.send_photo(
            chat_id=admin_id,
            photo=file_id,
            caption=(
                f"📸 <b>اسکرین‌شات ماموریت</b>\n"
                f"👤 {first_name} (@{username})\n"
                f"🆔 <code>{uid}</code>\n"
                f"📋 ماموریت #{tid}\n\n"
                f"✅ تأیید: /approve_task {uid} {tid}\n"
                f"❌ رد: /reject_task {uid} {tid}"
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass

    clear_user_state(context)
    await safe_send(update, (
        "✅ <b>اسکرین‌شات ارسال شد!</b>\n\n"
        "⏳ منتظر تأیید ادمین باشید."
    ), reply_markup=back_to_main_kb())


# ══════════════════════════════════════════════════════════
#  4. 👍 لایک چلنج  (PV — شیشه‌ای)
# ══════════════════════════════════════════════════════════
async def handle_like(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    u = db.get_user(uid)
    if not u:
        return

    like_info = db.get_like_challenge(uid)
    cost = config.LIKE_CHALLENGE_COST
    days = config.LIKE_CHALLENGE_DAYS

    if like_info and like_info.get("active"):
        end = like_info.get("end_date", "")
        await safe_edit(update, (
            f"👍 <b>لایک چلنج</b>\n\n"
            f"✅ چلنج فعال!\n"
            f"📅 پایان: {end}\n\n"
            f"💡 هر روز لایک بگیر و DP ببر!"
        ), reply_markup=back_to_main_kb())
        return

    if u["balance"] < cost:
        await safe_edit(update, (
            f"👍 <b>لایک چلنج</b>\n\n"
            f"💰 هزینه: <code>{fmt(cost)}</code> DP\n"
            f"📅 مدت: {days} روز\n"
            f"❌ موجودی کافی نیست!"
        ), reply_markup=back_to_main_kb())
        return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"👍 شروع چلنج ({fmt(cost)} DP)", callback_data="like_start"
        )],
        [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="back_main")],
    ])
    await safe_edit(update, (
        f"👍 <b>لایک چلنج</b>\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"💰 هزینه: <code>{fmt(cost)}</code> DP\n"
        f"📅 مدت: <b>{days} روز</b>\n\n"
        f"💡 هر روز لایک‌های پستت رو بشمار\n"
        f"و جایزه DP بگیر!"
    ), reply_markup=kb)


async def cb_like_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    u = db.get_user(uid)
    cost = config.LIKE_CHALLENGE_COST

    if not u or u["balance"] < cost:
        await query.answer("❌ موجودی کافی نیست!", show_alert=True)
        return

    await query.answer()
    db.add_balance(uid, -cost)
    end_date = (datetime.now() + timedelta(
        days=config.LIKE_CHALLENGE_DAYS)).strftime("%Y-%m-%d")
    db.set_like_challenge(uid, end_date)

    await safe_edit(update, (
        f"✅ <b>لایک چلنج شروع شد!</b>\n\n"
        f"💰 هزینه: <code>{fmt(cost)}</code> DP\n"
        f"📅 پایان: <b>{end_date}</b>\n\n"
        f"💡 هر روز اسکرین‌شات لایک‌ها رو بفرست!"
    ), reply_markup=back_to_main_kb())


# ══════════════════════════════════════════════════════════
#  5. 💱 تبدیل ارز  (PV — شیشه‌ای)
# ══════════════════════════════════════════════════════════
async def handle_convert_menu(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    u = db.get_user(uid)
    if not u:
        return

    ton_bal = u.get("ton_balance", 0.0)
    usdt_bal = u.get("usdt_balance", 0.0)

    text = (
        f"💱 <b>تبدیل ارز</b>\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"💎 TON: <code>{ton_bal:.4f}</code>\n"
        f"💵 USDT: <code>{usdt_bal:.4f}</code>\n\n"
        f"📊 نرخ‌ها:\n"
        f"   0.01 TON = <code>{fmt(config.TON_TO_DP)}</code> DP\n"
        f"   0.01 USDT = <code>{fmt(config.USDT_TO_DP)}</code> DP\n\n"
        f"📌 حداقل:\n"
        f"   TON: <code>{config.TON_CONVERT_MIN}</code>\n"
        f"   USDT: <code>{config.USDT_CONVERT_MIN}</code>"
    )

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💎 TON → DP", callback_data="conv_ton"),
            InlineKeyboardButton("💵 USDT → DP", callback_data="conv_usdt"),
        ],
        [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="back_main")],
    ])
    await safe_edit(update, text, reply_markup=kb)


async def cb_convert_start(update: Update,
                           context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data == "conv_ton":
        context.user_data["state"] = "convert_ton"
        cur = "TON"
        minimum = config.TON_CONVERT_MIN
    else:
        context.user_data["state"] = "convert_usdt"
        cur = "USDT"
        minimum = config.USDT_CONVERT_MIN

    await safe_edit(update, (
        f"💱 <b>تبدیل {cur} به DP</b>\n\n"
        f"🔢 مبلغ {cur} را ارسال کنید:\n"
        f"حداقل: <code>{minimum}</code> {cur}\n"
        f"مثال: <code>1.5</code>"
    ), reply_markup=cancel_only_kb())


async def msg_convert_amount(update: Update,
                             context: ContextTypes.DEFAULT_TYPE):
    """دریافت مبلغ تبدیل"""
    state = context.user_data.get("state")
    if state not in ("convert_ton", "convert_usdt"):
        return

    uid = update.effective_user.id
    u = db.get_user(uid)
    if not u:
        return

    try:
        amount = float(update.message.text.strip())
    except ValueError:
        await safe_send(update, "❌ مبلغ نامعتبر! فقط عدد.")
        return

    if state == "convert_ton":
        if amount < config.TON_CONVERT_MIN:
            await safe_send(update,
                            f"❌ حداقل {config.TON_CONVERT_MIN} TON!")
            return
        if u.get("ton_balance", 0) < amount:
            await safe_send(update, "❌ موجودی TON کافی نیست!")
            return
        dp = int((amount / 0.01) * config.TON_TO_DP)
        db.add_ton_balance(uid, -amount)
        cur = "TON"
    else:
        if amount < config.USDT_CONVERT_MIN:
            await safe_send(update,
                            f"❌ حداقل {config.USDT_CONVERT_MIN} USDT!")
            return
        if u.get("usdt_balance", 0) < amount:
            await safe_send(update, "❌ موجودی USDT کافی نیست!")
            return
        dp = int((amount / 0.01) * config.USDT_TO_DP)
        db.add_usdt_balance(uid, -amount)
        cur = "USDT"

    db.add_balance(uid, dp)
    clear_user_state(context)

    await safe_send(update, (
        f"✅ <b>تبدیل موفق!</b>\n\n"
        f"💱 {amount:.4f} {cur} → <code>{fmt(dp)}</code> DP\n"
        f"💰 موجودی DP: <code>{fmt(u['balance'] + dp)}</code>"
    ), reply_markup=back_to_main_kb())


# ══════════════════════════════════════════════════════════
#  6. ⭐ ستاره  (PV — شیشه‌ای)
# ══════════════════════════════════════════════════════════
async def handle_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    u = db.get_user(uid)
    if not u:
        return

    stars_on = db.get_setting("stars_on", "1")
    if stars_on != "1":
        await safe_edit(update, section_off_text(),
                        reply_markup=back_to_main_kb())
        return

    dp_cost = config.STARS_DP_COST
    stars_amount = int(db.get_setting("stars_amount", "50"))

    text = (
        f"⭐ <b>خرید ستاره تلگرام</b>\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"💰 هزینه: <code>{fmt(dp_cost)}</code> DP\n"
        f"⭐ تعداد: <b>{stars_amount}</b> ستاره\n\n"
        f"💡 ستاره‌ها برای حمایت از کانال‌ها استفاده می‌شوند."
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"⭐ خرید {stars_amount} ستاره", callback_data="stars_buy"
        )],
        [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="back_main")],
    ])
    await safe_edit(update, text, reply_markup=kb)


async def cb_stars_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    u = db.get_user(uid)
    dp_cost = config.STARS_DP_COST

    if not u or u["balance"] < dp_cost:
        await query.answer("❌ موجودی کافی نیست!", show_alert=True)
        return

    await query.answer()
    db.add_balance(uid, -dp_cost)

    # ثبت سفارش ستاره (ادمین دستی ارسال می‌کند)
    stars_amount = int(db.get_setting("stars_amount", "50"))
    await send_log(context, (
        f"⭐ <b>سفارش ستاره جدید</b>\n"
        f"👤 {html.escape(query.from_user.first_name or 'کاربر')} "
        f"(@{html.escape(query.from_user.username or '—')})\n"
        f"🆔 <code>{uid}</code>\n"
        f"⭐ تعداد: {stars_amount}\n"
        f"💰 هزینه: <code>{fmt(dp_cost)}</code> DP"
    ))

    await safe_edit(update, (
        f"✅ <b>سفارش ستاره ثبت شد!</b>\n\n"
        f"⭐ {stars_amount} ستاره\n"
        f"💰 هزینه: <code>{fmt(dp_cost)}</code> DP\n\n"
        f"⏳ ادمین بزودی ستاره‌ها را ارسال می‌کند."
    ), reply_markup=back_to_main_kb())


# ══════════════════════════════════════════════════════════
#  7. 💰 خرید DP  (PV — شیشه‌ای)
# ══════════════════════════════════════════════════════════
async def handle_buy_dp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    dp_amount = int(db.get_setting("buy_dp_amount",
                                   str(config.BUY_DP_DEFAULT_AMOUNT)))
    price_toman = int(db.get_setting("buy_dp_price",
                                     str(config.BUY_DP_DEFAULT_PRICE)))

    text = (
        f"💰 <b>خرید Dark Point</b>\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"📦 بسته: <code>{fmt(dp_amount)}</code> DP\n"
        f"💵 قیمت: <code>{fmt(price_toman)}</code> تومان\n\n"
        f"💡 برای خرید، روی دکمه زیر بزنید\n"
        f"و رسید پرداخت را ارسال کنید."
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "💳 درخواست خرید", callback_data="buydp_start"
        )],
        [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="back_main")],
    ])
    await safe_edit(update, text, reply_markup=kb)


async def cb_buydp_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "buydp_receipt"

    dp_amount = int(db.get_setting("buy_dp_amount",
                                   str(config.BUY_DP_DEFAULT_AMOUNT)))
    price_toman = int(db.get_setting("buy_dp_price",
                                     str(config.BUY_DP_DEFAULT_PRICE)))

    await safe_edit(update, (
        f"💳 <b>پرداخت</b>\n\n"
        f"📦 <code>{fmt(dp_amount)}</code> DP\n"
        f"💵 <code>{fmt(price_toman)}</code> تومان\n\n"
        f"💳 شماره کارت:\n"
        f"<code>6037 9975 9911 6644</code>\n"
        f"به نام: <b>دارک پوینت</b>\n\n"
        f"📸 پس از واریز، رسید پرداخت را ارسال کنید."
    ), reply_markup=cancel_only_kb())


async def msg_buydp_receipt(update: Update,
                            context: ContextTypes.DEFAULT_TYPE):
    """دریافت رسید پرداخت خرید DP"""
    if context.user_data.get("state") != "buydp_receipt":
        return

    uid = update.effective_user.id
    msg = update.message

    file_id = None
    if msg.photo:
        file_id = msg.photo[-1].file_id
    elif msg.document:
        file_id = msg.document.file_id

    if not file_id:
        await safe_send(update, "❌ لطفاً عکس رسید را ارسال کنید!")
        return

    dp_amount = int(db.get_setting("buy_dp_amount",
                                   str(config.BUY_DP_DEFAULT_AMOUNT)))
    price_toman = int(db.get_setting("buy_dp_price",
                                     str(config.BUY_DP_DEFAULT_PRICE)))
    username = html.escape(update.effective_user.username or "—")
    first_name = html.escape(update.effective_user.first_name or "کاربر")

    # ارسال رسید به ادمین
    try:
        await context.bot.send_photo(
            chat_id=config.ADMIN_ID,
            photo=file_id,
            caption=(
                f"💳 <b>رسید خرید DP</b>\n"
                f"👤 {first_name} (@{username})\n"
                f"🆔 <code>{uid}</code>\n"
                f"📦 {fmt(dp_amount)} DP — {fmt(price_toman)} تومان\n\n"
                f"✅ تأیید: /approve_buydp {uid} {dp_amount}\n"
                f"❌ رد: /reject_buydp {uid}"
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass

    clear_user_state(context)
    await safe_send(update, (
        "✅ <b>رسید ارسال شد!</b>\n\n"
        "⏳ پس از تأیید ادمین، DP واریز می‌شود."
    ), reply_markup=back_to_main_kb())## 📦 بخش 8/12 — پنل DP، دستورات گروهی، افزودن به گروه

```python
# ═══════════════════════════════════════════════════════════
#  SECTION 8/12 — DP Panel, Group Commands, Add to Group
# ═══════════════════════════════════════════════════════════

from datetime import datetime

# ══════════════════════════════════════════════════════════
#  1. 📖 پنل DP  (PV — شیشه‌ای — 12 صفحه)
# ══════════════════════════════════════════════════════════

PANEL_PAGES = [
    # صفحه 1
    (
        "📖 <b>پنل دارک پوینت — صفحه 1/12</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🖤 <b>دارک پوینت (DP) چیست؟</b>\n\n"
        "DP ارز دیجیتال اختصاصی ربات دارک پوینت است.\n"
        "با DP می‌توانید بازی کنید، خرید کنید، ماینر داشته باشید\n"
        "و حتی TON برداشت کنید!"
    ),
    # صفحه 2
    (
        "📖 <b>پنل DP — صفحه 2/12</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🎯 <b>کلیم (Claim)</b>\n\n"
        "هر 3-5 دقیقه می‌توانید DP رایگان دریافت کنید.\n"
        "پایه: 100-250 DP\n"
        "بونوس: 40 × (سطح - 1)\n"
        "هرچه سطح بالاتر، جایزه بیشتر!"
    ),
    # صفحه 3
    (
        "📖 <b>پنل DP — صفحه 3/12</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🤝 <b>زیرمجموعه‌گیری</b>\n\n"
        "لینک اختصاصی خود را بفرستید.\n"
        "هر کاربر جدید = 50,000 DP برای شما!\n"
        "💡 با زیرمجموعه‌گیری راحت می‌توانید برداشت TON کنید!"
    ),
    # صفحه 4
    (
        "📖 <b>پنل DP — صفحه 4/12</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🎮 <b>بازی‌ها (فقط گروه)</b>\n\n"
        "🚀 انفجار: 2x / 3x / 5x\n"
        "🎲 تاس: 1.5x / 3x / 6x\n"
        "🔢 حدس: 1.2x / 2.5x / 5x / 10x\n"
        "🎰 کازینو: 7x / 12x / 15x\n"
        "💣 بمب: +0.2x هر خانه امن"
    ),
    # صفحه 5
    (
        "📖 <b>پنل DP — صفحه 5/12</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "💎 <b>برداشت TON</b>\n\n"
        "200,000,000 DP = 0.0005 TON\n"
        "حداقل برداشت: 0.01 TON\n"
        "آدرس کیف پول TON لازم است."
    ),
    # صفحه 6
    (
        "📖 <b>پنل DP — صفحه 6/12</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🏦 <b>بانک دارکی</b>\n\n"
        "DP خود را واریز کنید.\n"
        "48 ساعت قفل → 3% سود!\n"
        "پول بی‌دردسر 😎"
    ),
    # صفحه 7
    (
        "📖 <b>پنل DP — صفحه 7/12</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "⛏ <b>ماینر دارکی</b>\n\n"
        "5 سطح — درآمد TON یا USDT\n"
        "هزینه برق: 2,000,000 DP/h\n"
        "خرید ماینر: 5,000,000 DP\n"
        "فقط در گروه فعال است."
    ),
    # صفحه 8
    (
        "📖 <b>پنل DP — صفحه 8/12</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🏭 <b>کارخانه دارکی</b>\n\n"
        "5 سطح — تولید 500 تا 25,000 DP/h\n"
        "سطح 1 رایگان!\n"
        "فقط در گروه فعال است."
    ),
    # صفحه 9
    (
        "📖 <b>پنل DP — صفحه 9/12</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "💸 <b>انتقال DP</b>\n\n"
        "ریپلای روی کاربر + دستور انتقال\n"
        "کارمزد: 10%\n"
        "محدودیت: 10 بار در روز\n"
        "فقط در گروه."
    ),
    # صفحه 10
    (
        "📖 <b>پنل DP — صفحه 10/12</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🛒 <b>فروشگاه</b>\n\n"
        "پلن‌های مختلف قابل خرید با DP.\n"
        "خرید = دریافت خودکار کانفیگ!\n"
        "💡 ادمین کانفیگ رو بزودی ارسال می‌کند."
    ),
    # صفحه 11
    (
        "📖 <b>پنل DP — صفحه 11/12</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🎡 <b>گردونه شانس</b>\n\n"
        "هر روز 1 بار رایگان!\n"
        "جایزه: 5,000 تا 100,000 DP\n"
        "گردونه اضافی: 50,000 DP"
    ),
    # صفحه 12
    (
        "📖 <b>پنل DP — صفحه 12/12</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "📊 <b>سیستم سطح‌بندی</b>\n\n"
        "20 سطح! هر سطح = سطح × 1,000,000 DP جایزه.\n"
        "سطح بالاتر = کلیم بیشتر + امکانات بیشتر!\n\n"
        "🖤 دارک پوینت، بی‌نهایت سرگرمی!"
    ),
]


async def handle_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش صفحه اول پنل DP"""
    await show_panel_page(update, context, 0)


async def show_panel_page(update: Update,
                          context: ContextTypes.DEFAULT_TYPE, page: int):
    """نمایش صفحه مشخص از پنل"""
    if page < 0 or page >= len(PANEL_PAGES):
        page = 0

    text = PANEL_PAGES[page]
    btns = []

    if page > 0:
        btns.append(
            InlineKeyboardButton("◀️ قبلی", callback_data=f"panel_{page - 1}")
        )
    if page < len(PANEL_PAGES) - 1:
        btns.append(
            InlineKeyboardButton("بعدی ▶️", callback_data=f"panel_{page + 1}")
        )

    kb_rows = []
    if btns:
        kb_rows.append(btns)
    kb_rows.append(
        [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="back_main")]
    )

    if update.callback_query:
        await safe_edit(update, text, reply_markup=InlineKeyboardMarkup(kb_rows))
    else:
        await safe_send(update, text, reply_markup=InlineKeyboardMarkup(kb_rows))


async def cb_panel_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """هندلر ناوبری صفحات پنل"""
    query = update.callback_query
    await query.answer()
    page = int(query.data.split("_")[1])
    await show_panel_page(update, context, page)


# ══════════════════════════════════════════════════════════
#  2. 📱 دستورات گروهی (متنی)
# ══════════════════════════════════════════════════════════

async def cmd_group_balance(update: Update,
                            context: ContextTypes.DEFAULT_TYPE):
    """موجودی — گروه"""
    uid = update.effective_user.id
    u = db.get_user(uid)
    if not u:
        db.add_user(uid, update.effective_user.username or "",
                    update.effective_user.first_name or "", None)
        u = db.get_user(uid)
    name = html.escape(update.effective_user.first_name or "کاربر")
    await safe_send(update, (
        f"💰 <b>موجودی {name}</b>\n\n"
        f"💎 DP: <code>{fmt(u['balance'])}</code>\n"
        f"📊 سطح: {u.get('level', 1)}"
    ))


async def cmd_group_profile(update: Update,
                            context: ContextTypes.DEFAULT_TYPE):
    """پروفایل دارکی — گروه"""
    uid = update.effective_user.id
    u = db.get_user(uid)
    if not u:
        db.add_user(uid, update.effective_user.username or "",
                    update.effective_user.first_name or "", None)
        u = db.get_user(uid)

    name = html.escape(update.effective_user.first_name or "کاربر")
    ref_count = db.get_referral_count(uid)
    await safe_send(update, (
        f"👤 <b>پروفایل {name}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🆔 <code>{uid}</code>\n"
        f"💰 DP: <code>{fmt(u['balance'])}</code>\n"
        f"📊 سطح: {u.get('level', 1)}\n"
        f"🏦 بانک: <code>{fmt(u.get('bank_balance', 0))}</code>\n"
        f"⛏ ماینر: سطح {u.get('miner_level', 0)}\n"
        f"🏭 کارخانه: سطح {u.get('factory_level', 1)}\n"
        f"🤝 زیرمجموعه: {ref_count} نفر"
    ))


async def cmd_group_leaderboard(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    """لیدربورد — گروه"""
    await handle_leaderboard(update, context)


async def cmd_group_dark(update: Update,
                         context: ContextTypes.DEFAULT_TYPE):
    """دارک — منوی گروه"""
    chat = update.effective_chat
    if chat.type == "private":
        return

    text = (
        "🖤 <b>منوی دارک پوینت</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🎮 <b>بازی‌ها:</b>\n"
        "• <code>بازی [مبلغ]</code>\n"
        "• <code>تاس [مبلغ]</code>\n"
        "• <code>حدس بزن [مبلغ]</code>\n"
        "• <code>کازینو [مبلغ]</code>\n"
        "• <code>بمب [مبلغ]</code>\n\n"
        "⛏ <b>سیستم‌ها:</b>\n"
        "• <code>ماینر دارکی</code>\n"
        "• <code>کارخانه دارکی</code>\n"
        "• <code>بانک دارکی</code>\n"
        "• <code>انتقال [مبلغ]</code>\n\n"
        "📊 <b>اطلاعات:</b>\n"
        "• <code>موجودی</code>\n"
        "• <code>پروفایل دارکی</code>\n"
        "• <code>لیدربورد</code>"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🤖 ربات در PV", url=f"https://t.me/{context.bot.username}"
        )],
    ])
    await safe_send(update, text, reply_markup=kb)


async def cmd_group_dark_config(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    """دارک کانفیگ — درخواست کانفیگ از گروه"""
    uid = update.effective_user.id
    name = html.escape(update.effective_user.first_name or "کاربر")
    username = html.escape(update.effective_user.username or "—")

    await send_log(context, (
        f"📦 <b>درخواست کانفیگ از گروه</b>\n"
        f"👤 {name} (@{username})\n"
        f"🆔 <code>{uid}</code>\n"
        f"📍 گروه: {html.escape(update.effective_chat.title or '—')}"
    ))

    await safe_send(update, (
        f"✅ {name}، درخواست کانفیگ ثبت شد!\n"
        f"💡 ادمین کانفیگ رو از پنل سنایی بزودی ارسال می‌کند"
    ))


async def cmd_group_bank(update: Update,
                         context: ContextTypes.DEFAULT_TYPE):
    """بانک دارکی — گروه"""
    chat = update.effective_chat
    if chat.type == "private":
        return

    uid = update.effective_user.id
    u = db.get_user(uid)
    if not u:
        return

    bank_bal = u.get("bank_balance", 0)
    name = html.escape(update.effective_user.first_name or "کاربر")
    await safe_send(update, (
        f"🏦 <b>بانک {name}</b>\n\n"
        f"💰 موجودی بانک: <code>{fmt(bank_bal)}</code> DP\n"
        f"💹 سود: 3% هر 48 ساعت\n\n"
        f"💡 واریز و برداشت از PV ربات."
    ))


async def cmd_group_numeric_id(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
    """ایدی عددی — ریپلای (فقط ادمین) یا خود کاربر"""
    msg = update.message
    uid = update.effective_user.id

    if msg.reply_to_message and msg.reply_to_message.from_user:
        if not is_admin(uid):
            await safe_send(update, "❌ فقط ادمین می‌تواند ایدی دیگران را ببیند!")
            return
        target = msg.reply_to_message.from_user
        await safe_send(update, (
            f"🆔 <b>ایدی عددی</b>\n\n"
            f"👤 {html.escape(target.first_name or 'کاربر')}\n"
            f"🆔 <code>{target.id}</code>"
        ))
    else:
        await safe_send(update, (
            f"🆔 <b>ایدی عددی شما</b>\n\n"
            f"<code>{uid}</code>"
        ))


# ══════════════════════════════════════════════════════════
#  3. ➕ افزودن ربات به گروه + چک عضو
# ══════════════════════════════════════════════════════════

async def handle_new_chat_member(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE):
    """وقتی ربات به گروه اضافه می‌شود"""
    chat = update.effective_chat
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            # بررسی تعداد اعضا
            try:
                count = await context.bot.get_chat_member_count(chat.id)
            except Exception:
                count = 0

            if count < config.MIN_GROUP_MEMBERS:
                await safe_send(update, (
                    f"❌ <b>گروه حداقل {config.MIN_GROUP_MEMBERS} عضو نیاز دارد!</b>\n\n"
                    f"📊 اعضای فعلی: {count}\n"
                    f"👋 ربات خارج می‌شود..."
                ))
                try:
                    await context.bot.leave_chat(chat.id)
                except Exception:
                    pass
                return

            # بررسی ادمین بودن ربات
            try:
                bot_member = await context.bot.get_chat_member(
                    chat.id, context.bot.id
                )
                if bot_member.status not in ("administrator", "creator"):
                    await safe_send(update, (
                        "⚠️ <b>لطفاً ربات را ادمین کنید!</b>\n\n"
                        "ربات بدون دسترسی ادمین نمی‌تواند کار کند."
                    ))
            except Exception:
                pass

            # ثبت گروه
            db.add_group(chat.id, chat.title or "بدون نام", count)
            await safe_send(update, (
                f"✅ <b>سلام! ربات دارک پوینت فعال شد!</b>\n\n"
                f"📊 اعضا: {count}\n"
                f"💡 دستور <code>دارک</code> را بزنید!"
            ))

            await send_log(context, (
                f"➕ <b>ربات به گروه اضافه شد</b>\n"
                f"📍 {html.escape(chat.title or '—')}\n"
                f"🆔 <code>{chat.id}</code>\n"
                f"📊 اعضا: {count}"
            ))


async def handle_left_chat_member(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    """وقتی ربات از گروه خارج می‌شود"""
    chat = update.effective_chat
    if update.message.left_chat_member:
        if update.message.left_chat_member.id == context.bot.id:
            db.remove_group(chat.id)
            await send_log(context, (
                f"➖ <b>ربات از گروه خارج شد</b>\n"
                f"📍 {html.escape(chat.title or '—')}\n"
                f"🆔 <code>{chat.id}</code>"
            ))


async def periodic_group_check(context: ContextTypes.DEFAULT_TYPE):
    """چک دوره‌ای اعضای گروه‌ها (هر 6 ساعت)"""
    groups = db.get_all_groups()
    for g in groups:
        gid = g["chat_id"]
        try:
            count = await context.bot.get_chat_member_count(gid)
            if count < config.MIN_GROUP_MEMBERS:
                try:
                    await context.bot.send_message(
                        chat_id=gid,
                        text=(
                            f"⚠️ <b>تعداد اعضا از {config.MIN_GROUP_MEMBERS} نفر کمتر شد!</b>\n"
                            f"📊 فعلی: {count}\n"
                            f"👋 ربات خارج می‌شود..."
                        ),
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
                try:
                    await context.bot.leave_chat(gid)
                except Exception:
                    pass
                db.remove_group(gid)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════
#  4. 👤 دستورات ادمین ساده (تأیید خرید/ماموریت)
# ══════════════════════════════════════════════════════════

async def cmd_approve_buydp(update: Update,
                            context: ContextTypes.DEFAULT_TYPE):
    """تأیید خرید DP — /approve_buydp [uid] [amount]"""
    if not is_admin(update.effective_user.id):
        return
    try:
        parts = update.message.text.split()
        uid = int(parts[1])
        amount = int(parts[2])
    except (IndexError, ValueError):
        await safe_send(update, "❌ فرمت: /approve_buydp UID AMOUNT")
        return

    db.add_balance(uid, amount)
    try:
        await context.bot.send_message(
            chat_id=uid,
            text=(
                f"✅ <b>خرید DP تأیید شد!</b>\n\n"
                f"💰 <code>+{fmt(amount)}</code> DP به حسابتان اضافه شد."
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await safe_send(update, f"✅ {fmt(amount)} DP به {uid} اضافه شد.")


async def cmd_reject_buydp(update: Update,
                           context: ContextTypes.DEFAULT_TYPE):
    """رد خرید DP — /reject_buydp [uid]"""
    if not is_admin(update.effective_user.id):
        return
    try:
        uid = int(update.message.text.split()[1])
    except (IndexError, ValueError):
        await safe_send(update, "❌ فرمت: /reject_buydp UID")
        return

    try:
        await context.bot.send_message(
            chat_id=uid,
            text="❌ <b>خرید DP رد شد!</b>\nدر صورت مشکل با ادمین تماس بگیرید.",
            parse_mode="HTML",
        )
    except Exception:
        pass
    await safe_send(update, f"❌ خرید {uid} رد شد.")


async def cmd_approve_task(update: Update,
                           context: ContextTypes.DEFAULT_TYPE):
    """تأیید ماموریت اسکرین‌شات — /approve_task [uid] [tid]"""
    if not is_admin(update.effective_user.id):
        return
    try:
        parts = update.message.text.split()
        uid = int(parts[1])
        tid = int(parts[2])
    except (IndexError, ValueError):
        await safe_send(update, "❌ فرمت: /approve_task UID TID")
        return

    task = db.get_task(tid)
    if not task:
        await safe_send(update, "❌ ماموریت یافت نشد!")
        return

    db.complete_task(uid, tid)
    db.add_balance(uid, task["reward"])

    try:
        await context.bot.send_message(
            chat_id=uid,
            text=(
                f"✅ <b>ماموریت تأیید شد!</b>\n\n"
                f"📋 {html.escape(task['name'])}\n"
                f"💰 <code>+{fmt(task['reward'])}</code> DP"
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await safe_send(update, f"✅ ماموریت #{tid} برای {uid} تأیید شد.")


async def cmd_reject_task(update: Update,
                          context: ContextTypes.DEFAULT_TYPE):
    """رد ماموریت — /reject_task [uid] [tid]"""
    if not is_admin(update.effective_user.id):
        return
    try:
        parts = update.message.text.split()
        uid = int(parts[1])
    except (IndexError, ValueError):
        await safe_send(update, "❌ فرمت: /reject_task UID TID")
        return

    try:
        await context.bot.send_message(
            chat_id=uid,
            text="❌ <b>ماموریت رد شد!</b>\nلطفاً دوباره تلاش کنید.",
            parse_mode="HTML",
        )
    except Exception:
        pass
    await safe_send(update, f"❌ ماموریت برای {uid} رد شد.")
```

---

### 📌 متدهای دیتابیس مورد نیاز

```python
# ── گروه‌ها ──
def add_group(self, chat_id, title, members):
    self.conn.execute(
        "INSERT OR REPLACE INTO groups (chat_id, title, members, joined_at) "
        "VALUES (?,?,?,?)",
        (chat_id, title, members, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    self.conn.commit()

def remove_group(self, chat_id):
    self.conn.execute("DELETE FROM groups WHERE chat_id=?", (chat_id,))
    self.conn.commit()

def get_all_groups(self):
    c = self.conn.execute("SELECT * FROM groups")
    return [dict(r) for r in c.fetchall()]
```

### 📌 جدول (در `_migrate`)

```python
self.conn.execute("""
    CREATE TABLE IF NOT EXISTS groups (
        chat_id INTEGER PRIMARY KEY,
        title TEXT,
        members INTEGER DEFAULT 0,
        joined_at TEXT
    )
""")
```

---


import io
import shutil
from datetime import datetime

# ══════════════════════════════════════════════════════════
#  1. 📊 آمار ربات
# ══════════════════════════════════════════════════════════
async def adm_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    total_users = db.get_total_users()
    total_groups = db.get_total_groups()
    total_dp = db.get_total_balance()
    total_ton_w = db.get_ton_withdrawal_stats()
    today_users = db.get_today_new_users()
    bot_status = "🟢 روشن" if db.get_setting("bot_on", "1") == "1" else "🔴 خاموش"

    text = (
        f"📊 <b>آمار دارک پوینت</b>\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"👥 کل کاربران: <b>{fmt(total_users)}</b>\n"
        f"📥 کاربران امروز: <b>{fmt(today_users)}</b>\n"
        f"👥 کل گروه‌ها: <b>{total_groups}</b>\n"
        f"💰 کل DP در گردش: <code>{fmt(total_dp)}</code>\n\n"
        f"💎 <b>برداشت TON:</b>\n"
        f"   ⏳ در انتظار: {total_ton_w.get('total', 0)} درخواست "
        f"({total_ton_w.get('total_ton', 0):.4f} TON)\n"
        f"   ✅ انجام شده: {total_ton_w.get('done', 0)} درخواست "
        f"({total_ton_w.get('done_ton', 0):.4f} TON)\n\n"
        f"🤖 وضعیت ربات: {bot_status}"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 بروزرسانی", callback_data="adm_stats")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="adm_back")],
    ])
    await safe_edit(update, text, reply_markup=kb)


# ══════════════════════════════════════════════════════════
#  2. 📢 پخش پیام (Broadcast)
# ══════════════════════════════════════════════════════════
async def adm_broadcast_menu(update: Update,
                             context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    text = (
        "📢 <b>پخش پیام</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "نوع پخش را انتخاب کنید:"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 کپی", callback_data="bc_copy"),
            InlineKeyboardButton("↗️ فوروارد", callback_data="bc_fwd"),
        ],
        [InlineKeyboardButton("👥 پخش گروه‌ها", callback_data="bc_groups")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="adm_back")],
    ])
    await safe_edit(update, text, reply_markup=kb)


async def cb_bc_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data == "bc_copy":
        context.user_data["state"] = "bc_copy"
        mode = "کپی"
    elif data == "bc_fwd":
        context.user_data["state"] = "bc_fwd"
        mode = "فوروارد"
    elif data == "bc_groups":
        context.user_data["state"] = "bc_groups"
        mode = "گروه‌ها"
    else:
        return

    await safe_edit(update, (
        f"📢 <b>پخش {mode}</b>\n\n"
        f"پیام مورد نظر را ارسال کنید:\n"
        f"(متن، عکس، ویدیو، فایل)"
    ), reply_markup=cancel_only_kb())


async def msg_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت پیام پخش و ارسال به همه"""
    state = context.user_data.get("state")
    if state not in ("bc_copy", "bc_fwd", "bc_groups"):
        return

    uid = update.effective_user.id
    if not is_admin(uid):
        return

    msg = update.message
    mode = state

    # تعیین لیست مقصد
    if mode == "bc_groups":
        targets = [g["chat_id"] for g in db.get_all_groups()]
        label = "گروه"
    else:
        targets = db.get_all_user_ids()
        label = "کاربر"

    total = len(targets)
    if total == 0:
        clear_user_state(context)
        await safe_send(update, "❌ مقصدی یافت نشد!")
        return

    await safe_send(update, (
        f"⏳ <b>در حال پخش...</b>\n"
        f"📊 مقصد: {fmt(total)} {label}"
    ))

    success, fail = 0, 0
    for target_id in targets:
        try:
            if mode == "bc_fwd":
                await msg.forward(chat_id=target_id)
            else:
                # کپی محتوا
                if msg.text:
                    await context.bot.send_message(
                        target_id, msg.text, parse_mode="HTML"
                    )
                elif msg.photo:
                    await context.bot.send_photo(
                        target_id, msg.photo[-1].file_id,
                        caption=msg.caption, parse_mode="HTML"
                    )
                elif msg.video:
                    await context.bot.send_video(
                        target_id, msg.video.file_id,
                        caption=msg.caption, parse_mode="HTML"
                    )
                elif msg.document:
                    await context.bot.send_document(
                        target_id, msg.document.file_id,
                        caption=msg.caption, parse_mode="HTML"
                    )
                elif msg.audio:
                    await context.bot.send_audio(
                        target_id, msg.audio.file_id,
                        caption=msg.caption, parse_mode="HTML"
                    )
                else:
                    continue
            success += 1
        except Exception:
            fail += 1

        # جلوگیری از فلود
        import asyncio
        await asyncio.sleep(0.05)

    clear_user_state(context)
    await safe_send(update, (
        f"✅ <b>پخش تمام شد!</b>\n\n"
        f"📊 کل: {fmt(total)}\n"
        f"✅ موفق: {fmt(success)}\n"
        f"❌ ناموفق: {fmt(fail)}"
    ), reply_markup=back_to_main_kb())


# ══════════════════════════════════════════════════════════
#  3. ➕ اضافه / ➖ کسر DP
# ══════════════════════════════════════════════════════════
async def adm_add_dp_menu(update: Update,
                          context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "adm_add_dp"
    await safe_edit(update, (
        "➕ <b>اضافه کردن DP</b>\n\n"
        "فرمت: <code>آیدی مبلغ</code>\n"
        "مثال: <code>123456789 1000000</code>"
    ), reply_markup=cancel_only_kb())


async def adm_deduct_dp_menu(update: Update,
                             context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "adm_deduct_dp"
    await safe_edit(update, (
        "➖ <b>کسر کردن DP</b>\n\n"
        "فرمت: <code>آیدی مبلغ</code>\n"
        "مثال: <code>123456789 500000</code>"
    ), reply_markup=cancel_only_kb())


async def msg_adm_dp_op(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اجرای اضافه/کسر DP"""
    state = context.user_data.get("state")
    if state not in ("adm_add_dp", "adm_deduct_dp"):
        return

    try:
        parts = update.message.text.strip().split()
        target_id = int(parts[0])
        amount = int(parts[1])
    except (ValueError, IndexError):
        await safe_send(update, "❌ فرمت: <code>آیدی مبلغ</code>")
        return

    u = db.get_user(target_id)
    if not u:
        await safe_send(update, f"❌ کاربر <code>{target_id}</code> یافت نشد!")
        return

    if state == "adm_add_dp":
        db.add_balance(target_id, amount)
        action = "اضافه"
        emoji = "➕"
    else:
        if u["balance"] < amount:
            await safe_send(update,
                            f"❌ موجودی کاربر فقط <code>{fmt(u['balance'])}</code> DP است!")
            return
        db.add_balance(target_id, -amount)
        action = "کسر"
        emoji = "➖"

    new_bal = u["balance"] + (amount if state == "adm_add_dp" else -amount)
    clear_user_state(context)

    await safe_send(update, (
        f"{emoji} <b>{action} DP موفق!</b>\n\n"
        f"👤 کاربر: <code>{target_id}</code>\n"
        f"💰 مبلغ: <code>{fmt(amount)}</code> DP\n"
        f"📊 موجودی جدید: <code>{fmt(new_bal)}</code> DP"
    ), reply_markup=back_to_main_kb())

    # اطلاع به کاربر
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                f"{emoji} <b>موجودی شما تغییر کرد!</b>\n\n"
                f"💰 {action}: <code>{fmt(amount)}</code> DP\n"
                f"📊 موجودی: <code>{fmt(new_bal)}</code> DP"
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass


# ══════════════════════════════════════════════════════════
#  4. 🔍 جستجوی کاربر
# ══════════════════════════════════════════════════════════
async def adm_search_menu(update: Update,
                          context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "adm_search"
    await safe_edit(update, (
        "🔍 <b>جستجوی کاربر</b>\n\n"
        "آیدی عددی یا یوزرنیم را ارسال کنید:"
    ), reply_markup=cancel_only_kb())


async def msg_adm_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "adm_search":
        return

    query_text = update.message.text.strip()
    clear_user_state(context)

    # جستجو بر اساس آیدی
    try:
        uid = int(query_text)
        u = db.get_user(uid)
    except ValueError:
        # جستجو بر اساس یوزرنیم
        u = db.get_user_by_username(query_text.lstrip("@"))
        uid = u["user_id"] if u else None

    if not u:
        await safe_send(update, "❌ کاربر یافت نشد!",
                        reply_markup=back_to_main_kb())
        return

    ref_count = db.get_referral_count(uid)
    ban_status = "🔴 بن" if u.get("banned", 0) else "🟢 آزاد"

    text = (
        f"🔍 <b>نتیجه جستجو</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🆔 آیدی: <code>{uid}</code>\n"
        f"👤 نام: {html.escape(u.get('first_name', '—'))}\n"
        f"🏷 یوزرنیم: @{html.escape(u.get('username', '—'))}\n"
        f"💰 DP: <code>{fmt(u['balance'])}</code>\n"
        f"💎 TON: <code>{u.get('ton_balance', 0):.4f}</code>\n"
        f"🏦 بانک: <code>{fmt(u.get('bank_balance', 0))}</code>\n"
        f"📊 سطح: {u.get('level', 1)}\n"
        f"🤝 زیرمجموعه: {ref_count}\n"
        f"🚫 وضعیت: {ban_status}\n"
        f"📅 عضویت: {u.get('joined_at', '—')}"
    )

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ DP", callback_data=f"adm_qadd_{uid}"),
            InlineKeyboardButton("➖ DP", callback_data=f"adm_qded_{uid}"),
        ],
        [
            InlineKeyboardButton("🚫 بن", callback_data=f"adm_ban_{uid}"),
            InlineKeyboardButton("✅ آنبن", callback_data=f"adm_unban_{uid}"),
        ],
        [InlineKeyboardButton("💬 ارسال پیام", callback_data=f"adm_send_{uid}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="adm_back")],
    ])
    await safe_send(update, text, reply_markup=kb)


async def cb_quick_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اضافه سریع DP از پروفایل کاربر"""
    query = update.callback_query
    await query.answer()
    uid = int(query.data.split("_")[2])
    context.user_data["state"] = "adm_add_dp"
    context.user_data["quick_target"] = uid
    await safe_edit(update, (
        f"➕ <b>اضافه DP به <code>{uid}</code></b>\n\n"
        f"مبلغ را ارسال کنید:"
    ), reply_markup=cancel_only_kb())


async def cb_quick_deduct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """کسر سریع DP از پروفایل کاربر"""
    query = update.callback_query
    await query.answer()
    uid = int(query.data.split("_")[2])
    context.user_data["state"] = "adm_deduct_dp"
    context.user_data["quick_target"] = uid
    await safe_edit(update, (
        f"➖ <b>کسر DP از <code>{uid}</code></b>\n\n"
        f"مبلغ را ارسال کنید:"
    ), reply_markup=cancel_only_kb())


# ══════════════════════════════════════════════════════════
#  5. 🚫 بن / آنبن
# ══════════════════════════════════════════════════════════
async def adm_ban_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "adm_ban"
    await safe_edit(update, (
        "🚫 <b>بن کاربر</b>\n\n"
        "آیدی عددی کاربر را ارسال کنید:"
    ), reply_markup=cancel_only_kb())


async def adm_unban_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "adm_unban"
    await safe_edit(update, (
        "✅ <b>آنبن کاربر</b>\n\n"
        "آیدی عددی کاربر را ارسال کنید:"
    ), reply_markup=cancel_only_kb())


async def msg_adm_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    if state not in ("adm_ban", "adm_unban"):
        return

    try:
        uid = int(update.message.text.strip())
    except ValueError:
        await safe_send(update, "❌ آیدی باید عدد باشد!")
        return

    u = db.get_user(uid)
    if not u:
        await safe_send(update, f"❌ کاربر <code>{uid}</code> یافت نشد!")
        return

    clear_user_state(context)

    if state == "adm_ban":
        db.set_ban(uid, 1)
        action = "بن"
        emoji = "🚫"
    else:
        db.set_ban(uid, 0)
        action = "آنبن"
        emoji = "✅"

    await safe_send(update, (
        f"{emoji} <b>کاربر {action} شد!</b>\n\n"
        f"🆔 <code>{uid}</code>\n"
        f"👤 {html.escape(u.get('first_name', '—'))}"
    ), reply_markup=back_to_main_kb())


async def cb_ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بن سریع از پروفایل"""
    query = update.callback_query
    data = query.data
    uid = int(data.split("_")[2])

    if "ban" in data and "unban" not in data:
        db.set_ban(uid, 1)
        await query.answer("🚫 بن شد!")
    else:
        db.set_ban(uid, 0)
        await query.answer("✅ آنبن شد!")

    await adm_stats(update, context)


# ══════════════════════════════════════════════════════════
#  6. 💬 ارسال پیام به کاربر
# ══════════════════════════════════════════════════════════
async def cb_send_to_user(update: Update,
                          context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = int(query.data.split("_")[2])
    context.user_data["state"] = "adm_send_msg"
    context.user_data["send_target"] = uid
    await safe_edit(update, (
        f"💬 <b>ارسال پیام به <code>{uid}</code></b>\n\n"
        f"پیام خود را ارسال کنید:"
    ), reply_markup=cancel_only_kb())


async def msg_send_to_user(update: Update,
                           context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "adm_send_msg":
        return

    target = context.user_data.get("send_target")
    if not target:
        return

    msg = update.message
    clear_user_state(context)

    try:
        if msg.text:
            await context.bot.send_message(
                target,
                f"📨 <b>پیام از ادمین:</b>\n\n{msg.text}",
                parse_mode="HTML",
            )
        elif msg.photo:
            await context.bot.send_photo(
                target, msg.photo[-1].file_id,
                caption=f"📨 <b>پیام از ادمین:</b>\n\n{msg.caption or ''}",
                parse_mode="HTML",
            )
        else:
            await msg.forward(chat_id=target)
        await safe_send(update, "✅ پیام ارسال شد!",
                        reply_markup=back_to_main_kb())
    except Exception as e:
        await safe_send(update, f"❌ ارسال نشد: {e}",
                        reply_markup=back_to_main_kb())


# ══════════════════════════════════════════════════════════
#  7. 💾 بکاپ / بازیابی دیتابیس
# ══════════════════════════════════════════════════════════
async def adm_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    db_path = db.db_path
    if not os.path.exists(db_path):
        await safe_edit(update, "❌ فایل دیتابیس یافت نشد!")
        return

    try:
        with open(db_path, "rb") as f:
            await context.bot.send_document(
                chat_id=query.from_user.id,
                document=f,
                filename=f"darkpoint_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db",
                caption=(
                    f"💾 <b>بکاپ دیتابیس</b>\n"
                    f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"👥 {fmt(db.get_total_users())} کاربر"
                ),
                parse_mode="HTML",
            )
        await safe_edit(update, "✅ بکاپ ارسال شد!",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔙 بازگشت", callback_data="adm_back")]
                        ]))
    except Exception as e:
        await safe_edit(update, f"❌ خطا: {e}")


async def adm_restore_menu(update: Update,
                           context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "adm_restore"
    await safe_edit(update, (
        "♻️ <b>بازیابی دیتابیس</b>\n\n"
        "⚠️ <b>هشدار:</b> دیتابیس فعلی جایگزین می‌شود!\n\n"
        "فایل بکاپ (.db) را ارسال کنید:"
    ), reply_markup=cancel_only_kb())


async def msg_restore_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "adm_restore":
        return

    msg = update.message
    if not msg.document:
        await safe_send(update, "❌ لطفاً فایل .db ارسال کنید!")
        return

    if not msg.document.file_name.endswith(".db"):
        await safe_send(update, "❌ فقط فایل .db مجاز است!")
        return

    await safe_send(update, "⏳ در حال بازیابی...")

    try:
        file = await context.bot.get_file(msg.document.file_id)
        db_path = db.db_path

        # بکاپ قبل از بازیابی
        backup_path = db_path + ".pre_restore"
        if os.path.exists(db_path):
            shutil.copy2(db_path, backup_path)

        # دانلود و جایگزینی
        await file.download_to_drive(db_path)

        # ری‌اینیت دیتابیس (بدون global db)
        db.__init__()

        clear_user_state(context)
        await safe_send(update, (
            "✅ <b>دیتابیس بازیابی شد!</b>\n\n"
            f"👥 کاربران: {fmt(db.get_total_users())}\n"
            f"📁 بکاپ قبلی: <code>.pre_restore</code>"
        ), reply_markup=back_to_main_kb())

    except Exception as e:
        clear_user_state(context)
        await safe_send(update, f"❌ خطا در بازیابی: {e}")


# ══════════════════════════════════════════════════════════
#  8. 🤖 روشن/خاموش ربات
# ══════════════════════════════════════════════════════════
async def adm_toggle_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    current = db.get_setting("bot_on", "1")
    new_val = "0" if current == "1" else "1"
    db.set_setting("bot_on", new_val)

    status = "🟢 روشن" if new_val == "1" else "🔴 خاموش"
    await safe_edit(update, (
        f"🤖 <b>وضعیت ربات تغییر کرد!</b>\n\n"
        f"وضعیت فعلی: {status}"
    ), reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت", callback_data="adm_back")]
    ]))


# ══════════════════════════════════════════════════════════
#  9. 📦 سفارشات اخیر
# ══════════════════════════════════════════════════════════
async def adm_recent_orders(update: Update,
                            context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    orders = db.get_ton_withdrawal_stats()
    text = (
        f"📦 <b>سفارشات برداشت TON</b>\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"⏳ در انتظار: {orders.get('total', 0)}\n"
        f"💎 مجموع TON: {orders.get('total_ton', 0):.4f}\n"
        f"💰 مجموع DP: {fmt(int(orders.get('total_dp', 0)))}\n\n"
        f"✅ انجام شده: {orders.get('done', 0)}\n"
        f"💎 مجموع TON: {orders.get('done_ton', 0):.4f}"
    )

    await safe_edit(update, text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت", callback_data="adm_back")]
    ]))# ═══════════════════════════════════════════════════════════
#  SECTION 10/12 — Admin Panel Part 2
#  ForceJoin, Tasks, Shop, Gift, Settings, Plans, Referral,
#  Gift Top/All, Reply, Config Send
# ═══════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════
#  1. 🔗 فورس‌جوین
# ══════════════════════════════════════════════════════════
async def adm_forcejoin_menu(update: Update,
                             context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    channels = db.get_force_join_channels()
    lines = [
        "🔗 <b>مدیریت فورس‌جوین</b>",
        "━━━━━━━━━━━━━━━", "",
    ]
    if channels:
        for ch in channels:
            lines.append(
                f"📌 {html.escape(ch.get('title', ch['channel_id']))}\n"
                f"   🆔 <code>{ch['channel_id']}</code>"
            )
    else:
        lines.append("❌ کانالی ثبت نشده!")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن کانال", callback_data="fj_add")],
        [InlineKeyboardButton("➖ حذف کانال", callback_data="fj_remove")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="adm_back")],
    ])
    await safe_edit(update, "\n".join(lines), reply_markup=kb)


async def cb_fj_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "fj_add"
    await safe_edit(update, (
        "➕ <b>افزودن کانال فورس‌جوین</b>\n\n"
        "فرمت: <code>آیدی_کانال نام</code>\n"
        "مثال: <code>-1001234567890 کانال دارک</code>\n\n"
        "⚠️ ربات باید ادمین کانال باشد!"
    ), reply_markup=cancel_only_kb())


async def msg_fj_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "fj_add":
        return

    parts = update.message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await safe_send(update, "❌ فرمت: <code>آیدی نام</code>")
        return

    channel_id = parts[0]
    title = parts[1]

    try:
        # چک ادمین بودن ربات
        member = await context.bot.get_chat_member(
            int(channel_id), context.bot.id
        )
        if member.status not in ("administrator", "creator"):
            await safe_send(update, "❌ ربات ادمین این کانال نیست!")
            return
    except Exception:
        await safe_send(update, "❌ آیدی کانال نامعتبر یا ربات عضو نیست!")
        return

    db.add_force_join_channel(channel_id, title)
    clear_user_state(context)
    await safe_send(update, (
        f"✅ <b>کانال اضافه شد!</b>\n\n"
        f"📌 {html.escape(title)}\n"
        f"🆔 <code>{channel_id}</code>"
    ), reply_markup=back_to_main_kb())


async def cb_fj_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "fj_remove"
    await safe_edit(update, (
        "➖ <b>حذف کانال فورس‌جوین</b>\n\n"
        "آیدی کانال را ارسال کنید:"
    ), reply_markup=cancel_only_kb())


async def msg_fj_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "fj_remove":
        return

    channel_id = update.message.text.strip()
    db.remove_force_join_channel(channel_id)
    clear_user_state(context)
    await safe_send(update, f"✅ کانال <code>{channel_id}</code> حذف شد!",
                    reply_markup=back_to_main_kb())


# ══════════════════════════════════════════════════════════
#  2. 📋 مدیریت ماموریت‌ها
# ══════════════════════════════════════════════════════════
async def adm_tasks_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    tasks = db.get_active_tasks()
    lines = ["📋 <b>مدیریت ماموریت‌ها</b>", "━━━━━━━━━━━━━━━", ""]
    if tasks:
        for t in tasks:
            lines.append(
                f"#{t['id']} {html.escape(t['name'])} "
                f"— <code>{fmt(t['reward'])}</code> DP [{t.get('type', 'channel')}]"
            )
    else:
        lines.append("❌ ماموریتی فعال نیست!")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن ماموریت", callback_data="task_add")],
        [InlineKeyboardButton("➖ حذف ماموریت", callback_data="task_remove")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="adm_back")],
    ])
    await safe_edit(update, "\n".join(lines), reply_markup=kb)


async def cb_task_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "task_add_name"
    await safe_edit(update, (
        "➕ <b>افزودن ماموریت</b>\n\n"
        "<b>مرحله 1/4:</b> نام ماموریت را ارسال کنید:\n"
        "مثال: <code>عضویت در کانال دارک</code>"
    ), reply_markup=cancel_only_kb())


async def msg_task_add_flow(update: Update,
                            context: ContextTypes.DEFAULT_TYPE):
    """فلو چندمرحله‌ای افزودن ماموریت"""
    state = context.user_data.get("state")
    if not state or not state.startswith("task_add"):
        return

    text = update.message.text.strip()

    if state == "task_add_name":
        context.user_data["task_name"] = text
        context.user_data["state"] = "task_add_type"
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔗 کانال", callback_data="ttype_channel"),
                InlineKeyboardButton("📸 اسکرین‌شات", callback_data="ttype_ss"),
            ],
            [InlineKeyboardButton("❌ لغو", callback_data="cancel_action")],
        ])
        await safe_send(update, (
            f"✅ نام: <b>{html.escape(text)}</b>\n\n"
            f"<b>مرحله 2/4:</b> نوع ماموریت:"
        ), reply_markup=kb)

    elif state == "task_add_reward":
        try:
            reward = int(text)
        except ValueError:
            await safe_send(update, "❌ مبلغ باید عدد باشد!")
            return
        context.user_data["task_reward"] = reward
        ttype = context.user_data.get("task_type", "channel")
        if ttype == "channel":
            context.user_data["state"] = "task_add_link"
            await safe_send(update, (
                f"✅ جایزه: <code>{fmt(reward)}</code> DP\n\n"
                f"<b>مرحله 4/4:</b> لینک کانال را ارسال کنید:\n"
                f"مثال: <code>https://t.me/darkpoint</code>"
            ), reply_markup=cancel_only_kb())
        else:
            # اسکرین‌شات — بدون لینک
            db.add_task(
                context.user_data["task_name"],
                ttype, reward, "", ""
            )
            clear_user_state(context)
            await safe_send(update, "✅ ماموریت اسکرین‌شات اضافه شد!",
                            reply_markup=back_to_main_kb())

    elif state == "task_add_link":
        link = text
        channel_id = context.user_data.get("task_channel_id", "")
        db.add_task(
            context.user_data["task_name"],
            "channel",
            context.user_data["task_reward"],
            link, channel_id
        )
        clear_user_state(context)
        await safe_send(update, "✅ ماموریت کانال اضافه شد!",
                        reply_markup=back_to_main_kb())


async def cb_task_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """انتخاب نوع ماموریت"""
    query = update.callback_query
    await query.answer()
    if query.data == "ttype_channel":
        context.user_data["task_type"] = "channel"
        context.user_data["state"] = "task_add_channel"
        await safe_edit(update, (
            f"✅ نوع: <b>کانال</b>\n\n"
            f"<b>مرحله 3/4:</b> آیدی عددی کانال را ارسال کنید:\n"
            f"مثال: <code>-1001234567890</code>\n"
            f"(اگر ندارید، 0 بزنید)"
        ), reply_markup=cancel_only_kb())
    else:
        context.user_data["task_type"] = "screenshot"
        context.user_data["state"] = "task_add_reward"
        await safe_edit(update, (
            f"✅ نوع: <b>اسکرین‌شات</b>\n\n"
            f"<b>مرحله 3/4:</b> مبلغ جایزه (DP) را ارسال کنید:"
        ), reply_markup=cancel_only_kb())


async def msg_task_channel_id(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "task_add_channel":
        return
    context.user_data["task_channel_id"] = update.message.text.strip()
    context.user_data["state"] = "task_add_reward"
    await safe_send(update, (
        "✅ آیدی کانال ثبت شد!\n\n"
        "<b>مرحله 4/4:</b> مبلغ جایزه (DP) را ارسال کنید:"
    ), reply_markup=cancel_only_kb())


async def cb_task_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "task_remove"
    await safe_edit(update, (
        "➖ <b>حذف ماموریت</b>\n\n"
        "شماره ماموریت (ID) را ارسال کنید:"
    ), reply_markup=cancel_only_kb())


async def msg_task_remove(update: Update,
                          context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "task_remove":
        return
    try:
        tid = int(update.message.text.strip())
    except ValueError:
        await safe_send(update, "❌ عدد وارد کنید!")
        return
    db.remove_task(tid)
    clear_user_state(context)
    await safe_send(update, f"✅ ماموریت #{tid} حذف شد!",
                    reply_markup=back_to_main_kb())


# ══════════════════════════════════════════════════════════
#  3. 🛒 مدیریت فروشگاه
# ══════════════════════════════════════════════════════════
async def adm_shop_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    plans = db.get_shop_plans()
    lines = ["🛒 <b>مدیریت فروشگاه</b>", "━━━━━━━━━━━━━━━", ""]
    if plans:
        for p in plans:
            lines.append(
                f"#{p['id']} {html.escape(p['name'])} "
                f"— <code>{fmt(p['price'])}</code> DP "
                f"(موجودی: {p['stock']})"
            )
    else:
        lines.append("❌ پلنی نیست!")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن پلن", callback_data="shop_add")],
        [InlineKeyboardButton("➖ حذف پلن", callback_data="shop_remove")],
        [InlineKeyboardButton("📦 ویرایش موجودی", callback_data="shop_stock")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="adm_back")],
    ])
    await safe_edit(update, "\n".join(lines), reply_markup=kb)


async def cb_shop_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "shop_add_name"
    await safe_edit(update, (
        "➕ <b>افزودن پلن فروشگاه</b>\n\n"
        "<b>مرحله 1/4:</b> نام پلن را ارسال کنید:\n"
        "مثال: <code>کانفیگ 1 ماهه</code>"
    ), reply_markup=cancel_only_kb())


async def msg_shop_add_flow(update: Update,
                            context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    if not state or not state.startswith("shop_add"):
        return

    text = update.message.text.strip()

    if state == "shop_add_name":
        context.user_data["shop_name"] = text
        context.user_data["state"] = "shop_add_price"
        await safe_send(update, (
            f"✅ نام: <b>{html.escape(text)}</b>\n\n"
            f"<b>مرحله 2/4:</b> قیمت (DP) را ارسال کنید:"
        ), reply_markup=cancel_only_kb())

    elif state == "shop_add_price":
        try:
            price = int(text)
        except ValueError:
            await safe_send(update, "❌ عدد وارد کنید!")
            return
        context.user_data["shop_price"] = price
        context.user_data["state"] = "shop_add_stock"
        await safe_send(update, (
            f"✅ قیمت: <code>{fmt(price)}</code> DP\n\n"
            f"<b>مرحله 3/4:</b> تعداد موجودی را ارسال کنید:"
        ), reply_markup=cancel_only_kb())

    elif state == "shop_add_stock":
        try:
            stock = int(text)
        except ValueError:
            await safe_send(update, "❌ عدد وارد کنید!")
            return
        context.user_data["shop_stock"] = stock
        context.user_data["state"] = "shop_add_content"
        await safe_send(update, (
            f"✅ موجودی: <b>{stock}</b>\n\n"
            f"<b>مرحله 4/4:</b> محتوای پلن (کانفیگ) را ارسال کنید:\n"
            f"(متن یا فایل)"
        ), reply_markup=cancel_only_kb())


async def msg_shop_content(update: Update,
                           context: ContextTypes.DEFAULT_TYPE):
    """دریافت محتوای پلن (متن یا فایل)"""
    if context.user_data.get("state") != "shop_add_content":
        return

    msg = update.message
    content = msg.text or msg.caption or ""
    file_id = ""
    file_type = ""

    if msg.photo:
        file_id = msg.photo[-1].file_id
        file_type = "photo"
    elif msg.video:
        file_id = msg.video.file_id
        file_type = "video"
    elif msg.document:
        file_id = msg.document.file_id
        file_type = "document"

    db.add_shop_plan(
        context.user_data["shop_name"],
        context.user_data["shop_price"],
        context.user_data["shop_stock"],
        content, file_id, file_type
    )
    clear_user_state(context)
    await safe_send(update, "✅ پلن فروشگاه اضافه شد!",
                    reply_markup=back_to_main_kb())


async def cb_shop_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "shop_remove"
    await safe_edit(update, (
        "➖ <b>حذف پلن</b>\n\nشماره پلن (ID) را ارسال کنید:"
    ), reply_markup=cancel_only_kb())


async def msg_shop_remove(update: Update,
                          context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "shop_remove":
        return
    try:
        pid = int(update.message.text.strip())
    except ValueError:
        await safe_send(update, "❌ عدد وارد کنید!")
        return
    db.remove_shop_plan(pid)
    clear_user_state(context)
    await safe_send(update, f"✅ پلن #{pid} حذف شد!",
                    reply_markup=back_to_main_kb())


async def cb_shop_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "shop_edit_stock"
    await safe_edit(update, (
        "📦 <b>ویرایش موجودی</b>\n\n"
        "فرمت: <code>ID تعداد</code>\n"
        "مثال: <code>1 50</code>"
    ), reply_markup=cancel_only_kb())


async def msg_shop_stock(update: Update,
                         context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "shop_edit_stock":
        return
    try:
        parts = update.message.text.strip().split()
        pid = int(parts[0])
        stock = int(parts[1])
    except (ValueError, IndexError):
        await safe_send(update, "❌ فرمت: <code>ID تعداد</code>")
        return
    db.set_plan_stock(pid, stock)
    clear_user_state(context)
    await safe_send(update, f"✅ موجودی پلن #{pid} = {stock}",
                    reply_markup=back_to_main_kb())


# ══════════════════════════════════════════════════════════
#  4. 🎁 مدیریت هدیه
# ══════════════════════════════════════════════════════════
async def adm_gift_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    plans = db.get_gift_plans()
    lines = ["🎁 <b>مدیریت هدایا</b>", "━━━━━━━━━━━━━━━", ""]
    if plans:
        for gp in plans:
            lines.append(
                f"#{gp['id']} {html.escape(gp['name'])} "
                f"— <code>{fmt(gp['price'])}</code> DP"
            )
    else:
        lines.append("❌ پلن هدیه‌ای نیست!")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن", callback_data="gift_add")],
        [InlineKeyboardButton("➖ حذف", callback_data="gift_remove")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="adm_back")],
    ])
    await safe_edit(update, "\n".join(lines), reply_markup=kb)


async def cb_gift_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "gift_add_name"
    await safe_edit(update, (
        "➕ <b>افزودن پلن هدیه</b>\n\n"
        "فرمت: <code>نام قیمت</code>\n"
        "مثال: <code>هدیه ویژه 100000</code>"
    ), reply_markup=cancel_only_kb())


async def msg_gift_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "gift_add_name":
        return
    parts = update.message.text.strip().rsplit(maxsplit=1)
    if len(parts) < 2:
        await safe_send(update, "❌ فرمت: <code>نام قیمت</code>")
        return
    try:
        price = int(parts[1])
    except ValueError:
        await safe_send(update, "❌ قیمت باید عدد باشد!")
        return
    db.add_gift_plan(parts[0], price)
    clear_user_state(context)
    await safe_send(update, f"✅ پلن هدیه <b>{html.escape(parts[0])}</b> اضافه شد!",
                    reply_markup=back_to_main_kb())


async def cb_gift_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "gift_remove"
    await safe_edit(update, "➖ <b>حذف پلن هدیه</b>\n\nID را ارسال کنید:",
                    reply_markup=cancel_only_kb())


async def msg_gift_remove(update: Update,
                          context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "gift_remove":
        return
    try:
        gid = int(update.message.text.strip())
    except ValueError:
        await safe_send(update, "❌ عدد وارد کنید!")
        return
    db.remove_gift_plan(gid)
    clear_user_state(context)
    await safe_send(update, f"✅ پلن هدیه #{gid} حذف شد!",
                    reply_markup=back_to_main_kb())


# ══════════════════════════════════════════════════════════
#  5. ⚙️ تنظیمات بخش‌ها (15 بخش خاموش/روشن)
# ══════════════════════════════════════════════════════════
async def adm_sections_menu(update: Update,
                            context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await safe_edit(update,
                    "⚙️ <b>تنظیمات بخش‌ها</b>\n\nوضعیت هر بخش را تغییر دهید:",
                    reply_markup=sections_toggle_kb())


async def cb_toggle_section(update: Update,
                            context: ContextTypes.DEFAULT_TYPE):
    """تغییر وضعیت یک بخش"""
    query = update.callback_query
    section = query.data.replace("toggle_sec_", "")

    current = db.is_section_on(section)
    db.set_section(section, not current)

    await query.answer(
        f"{'🟢 روشن' if not current else '🔴 خاموش'} شد!"
    )
    # بروزرسانی کیبورد
    await safe_edit(update,
                    "⚙️ <b>تنظیمات بخش‌ها</b>\n\nوضعیت هر بخش را تغییر دهید:",
                    reply_markup=sections_toggle_kb())


# ══════════════════════════════════════════════════════════
#  6. 📦 تنظیمات خرید DP + ستاره + ریفرال
# ══════════════════════════════════════════════════════════
async def adm_settings_menu(update: Update,
                            context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    dp_amt = db.get_setting("buy_dp_amount",
                            str(config.BUY_DP_DEFAULT_AMOUNT))
    dp_price = db.get_setting("buy_dp_price",
                              str(config.BUY_DP_DEFAULT_PRICE))
    ref_reward = db.get_setting("referral_reward",
                                str(config.DEFAULT_REFERRAL_REWARD))
    first_join = db.get_setting("first_join_reward",
                                str(config.DEFAULT_FIRST_JOIN_REWARD))
    stars_amt = db.get_setting("stars_amount", "50")

    text = (
        f"⚙️ <b>تنظیمات</b>\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"💰 <b>خرید DP:</b>\n"
        f"   بسته: <code>{fmt(int(dp_amt))}</code> DP\n"
        f"   قیمت: <code>{fmt(int(dp_price))}</code> تومان\n\n"
        f"🤝 <b>ریفرال:</b>\n"
        f"   جایزه: <code>{fmt(int(ref_reward))}</code> DP\n"
        f"   عضویت اول: <code>{fmt(int(first_join))}</code> DP\n\n"
        f"⭐ <b>ستاره:</b>\n"
        f"   تعداد: <b>{stars_amt}</b> ستاره"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 ویرایش خرید DP", callback_data="set_buydp")],
        [InlineKeyboardButton("🤝 ویرایش ریفرال", callback_data="set_ref")],
        [InlineKeyboardButton("⭐ ویرایش ستاره", callback_data="set_stars")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="adm_back")],
    ])
    await safe_edit(update, text, reply_markup=kb)


async def cb_set_buydp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "set_buydp"
    await safe_edit(update, (
        "💰 <b>ویرایش خرید DP</b>\n\n"
        "فرمت: <code>مبلغDP قیمتToman</code>\n"
        "مثال: <code>500000 50000</code>"
    ), reply_markup=cancel_only_kb())


async def msg_set_buydp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "set_buydp":
        return
    try:
        parts = update.message.text.strip().split()
        dp_amt = int(parts[0])
        price = int(parts[1])
    except (ValueError, IndexError):
        await safe_send(update, "❌ فرمت: <code>مبلغDP قیمت</code>")
        return
    db.set_setting("buy_dp_amount", str(dp_amt))
    db.set_setting("buy_dp_price", str(price))
    clear_user_state(context)
    await safe_send(update, (
        f"✅ <b>خرید DP بروزرسانی شد!</b>\n"
        f"📦 <code>{fmt(dp_amt)}</code> DP = <code>{fmt(price)}</code> تومان"
    ), reply_markup=back_to_main_kb())


async def cb_set_ref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "set_ref"
    await safe_edit(update, (
        "🤝 <b>ویرایش ریفرال</b>\n\n"
        "فرمت: <code>جایزه عضویت_اول</code>\n"
        "مثال: <code>50000 50000</code>"
    ), reply_markup=cancel_only_kb())


async def msg_set_ref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "set_ref":
        return
    try:
        parts = update.message.text.strip().split()
        ref = int(parts[0])
        first = int(parts[1])
    except (ValueError, IndexError):
        await safe_send(update, "❌ فرمت: <code>جایزه عضویت_اول</code>")
        return
    db.set_setting("referral_reward", str(ref))
    db.set_setting("first_join_reward", str(first))
    clear_user_state(context)
    await safe_send(update, (
        f"✅ <b>ریفرال بروزرسانی شد!</b>\n"
        f"🤝 جایزه: <code>{fmt(ref)}</code> DP\n"
        f"🎉 عضویت اول: <code>{fmt(first)}</code> DP"
    ), reply_markup=back_to_main_kb())


async def cb_set_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "set_stars"
    await safe_edit(update, (
        "⭐ <b>ویرایش ستاره</b>\n\n"
        "تعداد ستاره را ارسال کنید:\n"
        "مثال: <code>50</code>"
    ), reply_markup=cancel_only_kb())


async def msg_set_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "set_stars":
        return
    try:
        amt = int(update.message.text.strip())
    except ValueError:
        await safe_send(update, "❌ عدد وارد کنید!")
        return
    db.set_setting("stars_amount", str(amt))
    clear_user_state(context)
    await safe_send(update, f"✅ ستاره: <b>{amt}</b> عدد",
                    reply_markup=back_to_main_kb())


# ══════════════════════════════════════════════════════════
#  7. 🎁 گیفت به N نفر برتر / همه
# ══════════════════════════════════════════════════════════
async def adm_gift_top_menu(update: Update,
                            context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "gift_top"
    await safe_edit(update, (
        "🎁 <b>هدیه به N نفر برتر</b>\n\n"
        "فرمت: <code>تعداد مبلغ</code>\n"
        "مثال: <code>10 100000</code>\n"
        "(10 نفر برتر، هرکدام 100K DP)"
    ), reply_markup=cancel_only_kb())


async def msg_gift_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "gift_top":
        return
    try:
        parts = update.message.text.strip().split()
        n = int(parts[0])
        amount = int(parts[1])
    except (ValueError, IndexError):
        await safe_send(update, "❌ فرمت: <code>تعداد مبلغ</code>")
        return

    top = db.get_top_users(n)
    count = 0
    for u in top:
        db.add_balance(u["user_id"], amount)
        try:
            await context.bot.send_message(
                chat_id=u["user_id"],
                text=(
                    f"🎁 <b>هدیه ویژه!</b>\n\n"
                    f"💰 <code>+{fmt(amount)}</code> DP به حساب شما اضافه شد!\n"
                    f"🏆 به عنوان یکی از {n} نفر برتر!"
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass
        count += 1

    clear_user_state(context)
    await safe_send(update, (
        f"✅ <b>هدیه ارسال شد!</b>\n\n"
        f"👥 {count} نفر\n"
        f"💰 هرکدام: <code>{fmt(amount)}</code> DP\n"
        f"📊 مجموع: <code>{fmt(count * amount)}</code> DP"
    ), reply_markup=back_to_main_kb())


async def adm_gift_all_menu(update: Update,
                            context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "gift_all"
    await safe_edit(update, (
        "🎁 <b>هدیه به همه کاربران</b>\n\n"
        "⚠️ مبلغ هدیه (DP) را ارسال کنید:\n"
        "مثال: <code>10000</code>"
    ), reply_markup=cancel_only_kb())


async def msg_gift_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "gift_all":
        return
    try:
        amount = int(update.message.text.strip())
    except ValueError:
        await safe_send(update, "❌ عدد وارد کنید!")
        return

    users = db.get_all_user_ids()
    count = 0
    for uid in users:
        db.add_balance(uid, amount)
        count += 1

    clear_user_state(context)
    await safe_send(update, (
        f"✅ <b>هدیه به همه ارسال شد!</b>\n\n"
        f"👥 {fmt(count)} کاربر\n"
        f"💰 هرکدام: <code>{fmt(amount)}</code> DP\n"
        f"📊 مجموع: <code>{fmt(count * amount)}</code> DP"
    ), reply_markup=back_to_main_kb())


# ══════════════════════════════════════════════════════════
#  8. 📦 ارسال کانفیگ به خریدار پنل
# ══════════════════════════════════════════════════════════
async def adm_send_config_menu(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["state"] = "send_config_uid"
    await safe_edit(update, (
        "📦 <b>ارسال کانفیگ</b>\n\n"
        "آیدی عددی کاربر را ارسال کنید:"
    ), reply_markup=cancel_only_kb())


async def msg_send_config_uid(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "send_config_uid":
        return
    try:
        uid = int(update.message.text.strip())
    except ValueError:
        await safe_send(update, "❌ آیدی عددی وارد کنید!")
        return
    context.user_data["config_target"] = uid
    context.user_data["state"] = "send_config_content"
    await safe_send(update, (
        f"✅ آیدی: <code>{uid}</code>\n\n"
        f"حالا کانفیگ را ارسال کنید (متن/عکس/فایل):"
    ), reply_markup=cancel_only_kb())


async def msg_send_config_content(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != "send_config_content":
        return

    target = context.user_data.get("config_target")
    if not target:
        return

    msg = update.message
    clear_user_state(context)

    try:
        if msg.text:
            await context.bot.send_message(
                target,
                f"📦 <b>کانفیگ شما:</b>\n\n{msg.text}",
                parse_mode="HTML",
            )
        elif msg.photo:
            await context.bot.send_photo(
                target, msg.photo[-1].file_id,
                caption=f"📦 <b>کانفیگ شما:</b>\n\n{msg.caption or ''}",
                parse_mode="HTML",
            )
        elif msg.document:
            await context.bot.send_document(
                target, msg.document.file_id,
                caption=f"📦 <b>کانفیگ شما:</b>\n\n{msg.caption or ''}",
                parse_mode="HTML",
            )
        else:
            await msg.forward(chat_id=target)

        await safe_send(update, "✅ کانفیگ ارسال شد!",
                        reply_markup=back_to_main_kb())
    except Exception as e:
        await safe_send(update, f"❌ ارسال نشد: {e}",
                        reply_markup=back_to_main_kb())# ═══════════════════════════════════════════════════════════
#  SECTION 11/12 — User Router, Callback Router, Media Handlers
# ═══════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════
#  1. 📨 روتر پیام‌های متنی کاربر
# ══════════════════════════════════════════════════════════
async def msg_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    روتر مرکزی پیام‌های متنی.
    بر اساس state در context.user_data پیام را هدایت می‌کند.
    اگر state خاصی نباشد، پیام را نادیده می‌گیرد.
    """
    if not update.message or not update.message.text:
        return

    uid = update.effective_user.id
    if not is_admin(uid) and db.get_setting("bot_on", "1") != "1":
        return

    state = context.user_data.get("state", "")

    # ── برداشت TON ──
    if state == "ton_wallet":
        await msg_ton_wallet(update, context)
    elif state == "ton_amount":
        await msg_ton_amount(update, context)

    # ── بانک ──
    elif state == "bank_deposit":
        await msg_bank_deposit(update, context)

    # ── هدیه ──
    elif state == "gift_teddy_target":
        await msg_gift_teddy_target(update, context)
    elif state == "gift_plan_target":
        await msg_gift_plan_target(update, context)

    # ── ماموریت ──
    elif state == "task_screenshot":
        await msg_task_screenshot(update, context)

    # ── تبدیل ارز ──
    elif state in ("convert_ton", "convert_usdt"):
        await msg_convert_amount(update, context)

    # ── خرید DP ──
    elif state == "buydp_receipt":
        await msg_buydp_receipt(update, context)

    # ── ادمین: پخش ──
    elif state in ("bc_copy", "bc_fwd", "bc_groups"):
        await msg_broadcast(update, context)

    # ── ادمین: اضافه/کسر DP ──
    elif state in ("adm_add_dp", "adm_deduct_dp"):
        # چک quick_target (از پروفایل کاربر)
        quick = context.user_data.get("quick_target")
        if quick:
            # فقط مبلغ بگیر
            try:
                amount = int(update.message.text.strip())
            except ValueError:
                await safe_send(update, "❌ عدد وارد کنید!")
                return
            u = db.get_user(quick)
            if not u:
                clear_user_state(context)
                await safe_send(update, "❌ کاربر یافت نشد!")
                return
            if state == "adm_add_dp":
                db.add_balance(quick, amount)
                await safe_send(update,
                    f"✅ <code>{fmt(amount)}</code> DP به <code>{quick}</code> اضافه شد.",
                    reply_markup=back_to_main_kb())
            else:
                if u["balance"] < amount:
                    await safe_send(update, "❌ موجودی کافی نیست!")
                    return
                db.add_balance(quick, -amount)
                await safe_send(update,
                    f"✅ <code>{fmt(amount)}</code> DP از <code>{quick}</code> کسر شد.",
                    reply_markup=back_to_main_kb())
            clear_user_state(context)
        else:
            await msg_adm_dp_op(update, context)

    # ── ادمین: جستجو ──
    elif state == "adm_search":
        await msg_adm_search(update, context)

    # ── ادمین: بن/آنبن ──
    elif state in ("adm_ban", "adm_unban"):
        await msg_adm_ban(update, context)

    # ── ادمین: ارسال پیام ──
    elif state == "adm_send_msg":
        await msg_send_to_user(update, context)

    # ── ادمین: بازیابی DB ──
    elif state == "adm_restore":
        await msg_restore_db(update, context)

    # ── ادمین: فورس‌جوین ──
    elif state == "fj_add":
        await msg_fj_add(update, context)
    elif state == "fj_remove":
        await msg_fj_remove(update, context)

    # ── ادمین: ماموریت‌ها ──
    elif state == "task_add_name":
        await msg_task_add_flow(update, context)
    elif state == "task_add_channel":
        await msg_task_channel_id(update, context)
    elif state == "task_add_reward":
        await msg_task_add_flow(update, context)
    elif state == "task_add_link":
        await msg_task_add_flow(update, context)
    elif state == "task_remove":
        await msg_task_remove(update, context)

    # ── ادمین: فروشگاه ──
    elif state in ("shop_add_name", "shop_add_price", "shop_add_stock"):
        await msg_shop_add_flow(update, context)
    elif state == "shop_add_content":
        await msg_shop_content(update, context)
    elif state == "shop_remove":
        await msg_shop_remove(update, context)
    elif state == "shop_edit_stock":
        await msg_shop_stock(update, context)

    # ── ادمین: هدیه ──
    elif state == "gift_add_name":
        await msg_gift_add(update, context)
    elif state == "gift_remove":
        await msg_gift_remove(update, context)

    # ── ادمین: تنظیمات ──
    elif state == "set_buydp":
        await msg_set_buydp(update, context)
    elif state == "set_ref":
        await msg_set_ref(update, context)
    elif state == "set_stars":
        await msg_set_stars(update, context)

    # ── ادمین: گیفت ──
    elif state == "gift_top":
        await msg_gift_top(update, context)
    elif state == "gift_all":
        await msg_gift_all(update, context)

    # ── ادمین: ارسال کانفیگ ──
    elif state == "send_config_uid":
        await msg_send_config_uid(update, context)
    elif state == "send_config_content":
        await msg_send_config_content(update, context)


# ══════════════════════════════════════════════════════════
#  2. 🖱 روتر کالبک‌ها (دکمه‌های شیشه‌ای)
# ══════════════════════════════════════════════════════════
async def cb_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    روتر مرکزی کالبک‌ها.
    بر اساس prefix دکمه، هندلر مناسب را فراخوانی می‌کند.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    data = query.data
    uid = query.from_user.id

    # ── چک خاموشی ربات (به جز ادمین) ──
    if not is_admin(uid) and db.get_setting("bot_on", "1") != "1":
        await query.answer(bot_off_text(), show_alert=True)
        return

    # ── چک بن ──
    u = db.get_user(uid)
    if u and u.get("banned", 0) and not is_admin(uid):
        await query.answer("🚫 شما بن شده‌اید!", show_alert=True)
        return

    # ══════════════════════════════════════════════════════
    #  منوی اصلی و ناوبری
    # ══════════════════════════════════════════════════════
    if data.startswith("menu_"):
        await cb_main_router(update, context)
    elif data == "back_main":
        await cb_back_main(update, context)
    elif data == "cancel_action":
        await cb_cancel_action(update, context)
    elif data == "check_join":
        await cb_check_join(update, context)

    # ══════════════════════════════════════════════════════
    #  برداشت TON (بخش 5)
    # ══════════════════════════════════════════════════════
    elif data == "ton_start":
        await cb_ton_start(update, context)
    elif data in ("ton_confirm_yes", "ton_confirm_no"):
        await cb_ton_confirm(update, context)

    # ══════════════════════════════════════════════════════
    #  بانک (بخش 6)
    # ══════════════════════════════════════════════════════
    elif data == "bank_deposit":
        await cb_bank_deposit(update, context)
    elif data == "bank_withdraw":
        await cb_bank_withdraw(update, context)

    # ══════════════════════════════════════════════════════
    #  ماینر (بخش 6)
    # ══════════════════════════════════════════════════════
    elif data in ("miner_buy", "miner_collect", "miner_switch", "miner_upgrade"):
        await cb_miner(update, context)

    # ══════════════════════════════════════════════════════
    #  کارخانه (بخش 6)
    # ══════════════════════════════════════════════════════
    elif data in ("fac_collect", "fac_upgrade"):
        await cb_factory(update, context)

    # ══════════════════════════════════════════════════════
    #  بازی‌ها (بخش 4)
    # ══════════════════════════════════════════════════════
    elif data.startswith("gs_"):
        await cb_guess(update, context)
    elif data.startswith("bmb_"):
        await cb_bomb(update, context)

    # ══════════════════════════════════════════════════════
    #  فروشگاه (بخش 7)
    # ══════════════════════════════════════════════════════
    elif data.startswith("shop_buy_"):
        await cb_shop_buy(update, context)

    # ══════════════════════════════════════════════════════
    #  هدیه (بخش 7)
    # ══════════════════════════════════════════════════════
    elif data == "gift_teddy":
        await cb_gift_teddy(update, context)
    elif data.startswith("gift_buy_"):
        await cb_gift_buy(update, context)

    # ══════════════════════════════════════════════════════
    #  ماموریت‌ها (بخش 7)
    # ══════════════════════════════════════════════════════
    elif data.startswith("task_check_"):
        await cb_task_check(update, context)
    elif data.startswith("task_ss_"):
        await cb_task_screenshot(update, context)

    # ══════════════════════════════════════════════════════
    #  لایک (بخش 7)
    # ══════════════════════════════════════════════════════
    elif data == "like_start":
        await cb_like_start(update, context)

    # ══════════════════════════════════════════════════════
    #  تبدیل ارز (بخش 7)
    # ══════════════════════════════════════════════════════
    elif data in ("conv_ton", "conv_usdt"):
        await cb_convert_start(update, context)

    # ══════════════════════════════════════════════════════
    #  ستاره (بخش 7)
    # ══════════════════════════════════════════════════════
    elif data == "stars_buy":
        await cb_stars_buy(update, context)

    # ══════════════════════════════════════════════════════
    #  خرید DP (بخش 7)
    # ══════════════════════════════════════════════════════
    elif data == "buydp_start":
        await cb_buydp_start(update, context)

    # ══════════════════════════════════════════════════════
    #  پنل DP (بخش 8)
    # ══════════════════════════════════════════════════════
    elif data.startswith("panel_"):
        await cb_panel_page(update, context)

    # ══════════════════════════════════════════════════════
    #  ادمین: منو و ناوبری (بخش 9-10)
    # ══════════════════════════════════════════════════════
    elif data == "adm_back":
        await cmd_admin(update, context)

    elif data == "adm_stats":
        await adm_stats(update, context)

    elif data == "adm_toggle_bot":
        await adm_toggle_bot(update, context)

    elif data == "adm_broadcast":
        await adm_broadcast_menu(update, context)
    elif data in ("bc_copy", "bc_fwd", "bc_groups"):
        await cb_bc_start(update, context)

    elif data == "adm_add_dp":
        await adm_add_dp_menu(update, context)
    elif data == "adm_deduct_dp":
        await adm_deduct_dp_menu(update, context)

    elif data == "adm_search":
        await adm_search_menu(update, context)
    elif data.startswith("adm_qadd_"):
        await cb_quick_add(update, context)
    elif data.startswith("adm_qded_"):
        await cb_quick_deduct(update, context)

    elif data == "adm_ban":
        await adm_ban_menu(update, context)
    elif data == "adm_unban":
        await adm_unban_menu(update, context)
    elif data.startswith("adm_ban_"):
        await cb_ban_user(update, context)
    elif data.startswith("adm_unban_"):
        await cb_ban_user(update, context)

    elif data.startswith("adm_send_"):
        await cb_send_to_user(update, context)

    elif data == "adm_backup":
        await adm_backup(update, context)
    elif data == "adm_restore":
        await adm_restore_menu(update, context)

    elif data == "adm_orders":
        await adm_recent_orders(update, context)

    # ── فورس‌جوین (بخش 10) ──
    elif data == "adm_forcejoin":
        await adm_forcejoin_menu(update, context)
    elif data == "fj_add":
        await cb_fj_add(update, context)
    elif data == "fj_remove":
        await cb_fj_remove(update, context)

    # ── ماموریت‌ها (بخش 10) ──
    elif data == "adm_tasks":
        await adm_tasks_menu(update, context)
    elif data == "task_add":
        await cb_task_add(update, context)
    elif data == "task_remove":
        await cb_task_remove(update, context)
    elif data in ("ttype_channel", "ttype_ss"):
        await cb_task_type(update, context)

    # ── فروشگاه (بخش 10) ──
    elif data == "adm_shop":
        await adm_shop_menu(update, context)
    elif data == "shop_add":
        await cb_shop_add(update, context)
    elif data == "shop_remove":
        await cb_shop_remove(update, context)
    elif data == "shop_stock":
        await cb_shop_stock(update, context)

    # ── هدیه (بخش 10) ──
    elif data == "adm_gift":
        await adm_gift_menu(update, context)
    elif data == "gift_add":
        await cb_gift_add(update, context)
    elif data == "gift_remove":
        await cb_gift_remove(update, context)

    # ── بخش‌ها (بخش 10) ──
    elif data == "adm_sections":
        await adm_sections_menu(update, context)
    elif data.startswith("toggle_sec_"):
        await cb_toggle_section(update, context)

    # ── تنظیمات (بخش 10) ──
    elif data == "adm_settings":
        await adm_settings_menu(update, context)
    elif data == "set_buydp":
        await cb_set_buydp(update, context)
    elif data == "set_ref":
        await cb_set_ref(update, context)
    elif data == "set_stars":
        await cb_set_stars(update, context)

    # ── گیفت (بخش 10) ──
    elif data == "adm_gift_top":
        await adm_gift_top_menu(update, context)
    elif data == "adm_gift_all":
        await adm_gift_all_menu(update, context)

    # ── ارسال کانفیگ (بخش 10) ──
    elif data == "adm_send_config":
        await adm_send_config_menu(update, context)

    # ── ناشناخته ──
    else:
        await query.answer("⚠️ دکمه نامعتبر!", show_alert=True)


# ══════════════════════════════════════════════════════════
#  3. 📸 هندلر مدیا (عکس/فایل/ویدیو)
# ══════════════════════════════════════════════════════════
async def media_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    روتر پیام‌های مدیا (عکس، ویدیو، فایل).
    فقط زمانی فعال است که state خاصی تنظیم شده باشد.
    """
    state = context.user_data.get("state", "")
    if not state:
        return

    # ── ماموریت: اسکرین‌شات ──
    if state == "task_screenshot":
        await msg_task_screenshot(update, context)

    # ── خرید DP: رسید ──
    elif state == "buydp_receipt":
        await msg_buydp_receipt(update, context)

    # ── ادمین: پخش ──
    elif state in ("bc_copy", "bc_fwd", "bc_groups"):
        await msg_broadcast(update, context)

    # ── ادمین: بازیابی DB ──
    elif state == "adm_restore":
        await msg_restore_db(update, context)

    # ── ادمین: محتوای پلن فروشگاه ──
    elif state == "shop_add_content":
        await msg_shop_content(update, context)

    # ── ادمین: ارسال پیام ──
    elif state == "adm_send_msg":
        await msg_send_to_user(update, context)

    # ── ادمین: ارسال کانفیگ ──
    elif state == "send_config_content":
        await msg_send_config_content(update, context)


# ══════════════════════════════════════════════════════════
#  4. 👥 هندلر پیام‌های گروهی (فیلتر گروه)
# ══════════════════════════════════════════════════════════
async def group_msg_router(update: Update,
                           context: ContextTypes.DEFAULT_TYPE):
    """
    روتر پیام‌های گروهی.
    فقط دستورات متنی گروهی را پردازش می‌کند.
    """
    chat = update.effective_chat
    if not chat or chat.type == "private":
        return

    msg = update.message
    if not msg or not msg.text:
        return

    text = msg.text.strip()
    uid = update.effective_user.id

    # چک بن
    u = db.get_user(uid)
    if u and u.get("banned", 0):
        return

    # ── دستورات گروهی ──
    lower = text.lower()

    if lower.startswith("بازی ") or lower.startswith("انفجار "):
        if db.is_section_on("crash"):
            await cmd_crash(update, context)
        else:
            await safe_send(update, section_off_text())

    elif lower.startswith("تاس "):
        if db.is_section_on("dice"):
            await cmd_dice(update, context)
        else:
            await safe_send(update, section_off_text())

    elif lower.startswith("حدس بزن "):
        if db.is_section_on("guess"):
            await cmd_guess(update, context)
        else:
            await safe_send(update, section_off_text())

    elif lower.startswith("کازینو "):
        if db.is_section_on("casino"):
            await cmd_casino(update, context)
        else:
            await safe_send(update, section_off_text())

    elif lower.startswith("بمب "):
        if db.is_section_on("bomb"):
            await cmd_bomb(update, context)
        else:
            await safe_send(update, section_off_text())

    elif lower == "ماینر دارکی":
        if db.is_section_on("miner"):
            await cmd_miner(update, context)
        else:
            await safe_send(update, section_off_text())

    elif lower == "کارخانه دارکی":
        if db.is_section_on("factory"):
            await cmd_factory(update, context)
        else:
            await safe_send(update, section_off_text())

    elif lower.startswith("انتقال "):
        if db.is_section_on("transfer"):
            await cmd_transfer(update, context)
        else:
            await safe_send(update, section_off_text())

    elif lower == "موجودی":
        await cmd_group_balance(update, context)

    elif lower == "پروفایل دارکی":
        await cmd_group_profile(update, context)

    elif lower == "لیدربورد":
        await cmd_group_leaderboard(update, context)

    elif lower == "دارک":
        await cmd_group_dark(update, context)

    elif lower == "دارک کانفیگ":
        await cmd_group_dark_config(update, context)

    elif lower == "بانک دارکی":
        await cmd_group_bank(update, context)

    elif lower == "ایدی عددی":
        await cmd_group_numeric_id(update, context)# ═══════════════════════════════════════════════════════════
#  SECTION 12/12 — main(), Handler Registration, Startup
# ═══════════════════════════════════════════════════════════

import os
import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
#  تابع اصلی
# ══════════════════════════════════════════════════════════
def main():
    """راه‌اندازی ربات دارک پوینت"""

    # ── لاگ ──
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=logging.INFO,
    )

    # ── توکن ──
    token = config.BOT_TOKEN
    if not token or token == "YOUR_BOT_TOKEN_HERE":
        logger.error("❌ توکن ربات در config.py تنظیم نشده!")
        return

    # ── ساخت اپلیکیشن ──
    app = Application.builder().token(token).build()

    # ══════════════════════════════════════════════════════
    #  1. دستورات PV (CommandHandler)
    # ══════════════════════════════════════════════════════

    # /start — ورود + ریفرال
    app.add_handler(CommandHandler("start", cmd_start,
                                   filters=filters.ChatType.PRIVATE))

    # /admin — پنل ادمین
    app.add_handler(CommandHandler("admin", cmd_admin,
                                   filters=filters.ChatType.PRIVATE))

    # /help — راهنما
    app.add_handler(CommandHandler("help", cmd_help))

    # ══════════════════════════════════════════════════════
    #  2. دستورات ادمین سریع (PV)
    # ══════════════════════════════════════════════════════
    app.add_handler(CommandHandler("approve_buydp", cmd_approve_buydp,
                                   filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("reject_buydp", cmd_reject_buydp,
                                   filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("approve_task", cmd_approve_task,
                                   filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("reject_task", cmd_reject_task,
                                   filters=filters.ChatType.PRIVATE))

    # ══════════════════════════════════════════════════════
    #  3. رویدادهای گروه (عضویت / خروج)
    # ══════════════════════════════════════════════════════
    app.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS,
        handle_new_chat_member
    ))
    app.add_handler(MessageHandler(
        filters.StatusUpdate.LEFT_CHAT_MEMBER,
        handle_left_chat_member
    ))

    # ══════════════════════════════════════════════════════
    #  4. کالبک‌ها (دکمه‌های شیشه‌ای) — همه چت‌ها
    # ══════════════════════════════════════════════════════
    app.add_handler(CallbackQueryHandler(cb_router))

    # ══════════════════════════════════════════════════════
    #  5. پیام‌های گروهی (دستورات متنی)
    # ══════════════════════════════════════════════════════
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
        group_msg_router
    ))

    # ══════════════════════════════════════════════════════
    #  6. پیام‌های PV — مدیا (عکس/فایل/ویدیو)
    # ══════════════════════════════════════════════════════
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & (
            filters.PHOTO | filters.VIDEO | filters.Document.ALL
        ),
        media_router
    ))

    # ══════════════════════════════════════════════════════
    #  7. پیام‌های PV — متن (روتر state)
    # ══════════════════════════════════════════════════════
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
        msg_router
    ))

    # ══════════════════════════════════════════════════════
    #  8. جاب‌های دوره‌ای (JobQueue)
    # ══════════════════════════════════════════════════════
    job_queue = app.job_queue

    # چک اعضای گروه‌ها هر 6 ساعت
    job_queue.run_repeating(
        periodic_group_check,
        interval=6 * 3600,
        first=300,  # 5 دقیقه بعد از استارت
        name="group_check",
    )

    # ══════════════════════════════════════════════════════
    #  9. استارت‌آپ و اجرا
    # ══════════════════════════════════════════════════════

    # ── Keep-Alive (سرور HTTP + Self-Ping) ──
    port = int(os.environ.get("PORT", 8080))
    url = os.environ.get("RENDER_EXTERNAL_URL", "")

    # راه‌اندازی سرور سلامت در ترد جداگانه
    import threading
    health_thread = threading.Thread(
        target=run_health_server, args=(port,), daemon=True
    )
    health_thread.start()
    logger.info(f"🏥 Health server on port {port}")

    # ── اجرا ──
    if url:
        # Webhook mode (Render)
        webhook_url = f"{url}/webhook"
        logger.info(f"🌐 Webhook: {webhook_url}")

        # Self-ping برای جلوگیری از sleep
        job_queue.run_repeating(
            lambda ctx: self_ping_loop(url),
            interval=480,
            first=60,
            name="self_ping",
        )

        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path="webhook",
            webhook_url=webhook_url,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        # Polling mode (لوکال)
        logger.info("🔄 Polling mode (local)")
        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )


# ══════════════════════════════════════════════════════════
#  نقطه ورود
# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    main()
