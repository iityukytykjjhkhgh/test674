# bot.py - Dark Point Telegram Bot - Main File (Render Ready)

import os
import logging
import time
import random
import string
import math
import asyncio
import json
import re
import threading
import requests
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    ChatMember, BotCommand
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters, ChatMemberHandler
)
from telegram.constants import ParseMode, ChatAction

from config import *
from database import Database

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

db = Database()

# Conversation states
(
    ADMIN_ADD_DP_USER, ADMIN_ADD_DP_AMOUNT,
    ADMIN_CREATE_PANEL_NAME, ADMIN_CREATE_PANEL_DESC, 
    ADMIN_CREATE_PANEL_PRICE, ADMIN_CREATE_PANEL_DATA,
    ADMIN_SET_GIFT_PRICE, ADMIN_SET_STARS_PRICE,
    ADMIN_CHECK_AMOUNT,
    ADMIN_ADD_GIFT_PLAN_NAME, ADMIN_ADD_GIFT_PLAN_PRICE,
    TRANSFER_AMOUNT_REPLY, TRANSFER_CONFIRM,
    BANK_CUSTOM_CARD, BANK_DEPOSIT_AMOUNT,
    STARS_OTHER_ACCOUNT,
    BUY_PANEL_CONFIRM,
    GIFT_ORDER_CONFIRM,
    CAPTCHA_VERIFY,
) = range(19)


# ============ HELPER FUNCTIONS ============

def format_number(num):
    return "{:,}".format(num)

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
    if user.username:
        return f"@{user.username}"
    return f"[{user.first_name}](tg://user?id={user.id})"

async def check_force_join(user_id, context):
    for channel in FORCE_JOIN_CHANNELS:
        try:
            member = await context.bot.get_chat_member(channel, user_id)
            if member.status in ['left', 'kicked']:
                return False
        except Exception:
            continue
    return True

async def send_log(context, text, reply_markup=None):
    try:
        await context.bot.send_message(
            LOG_CHANNEL_ID, text, 
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Log error: {e}")


# ============ RENDER KEEP-ALIVE SYSTEM ============

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        html = """
        <html>
        <head><title>Dark Point Bot</title></head>
        <body style="background:#000;color:#fff;text-align:center;font-family:Arial;padding:50px;">
            <h1>🏴 Dark Point Bot</h1>
            <h2>✅ Bot is Alive and Running!</h2>
            <p>Server Time: """ + time.strftime('%Y-%m-%d %H:%M:%S') + """</p>
        </body>
        </html>
        """
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args):
        return

def start_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        logger.info(f"🌐 Health Check Server running on port {port}")
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
    except Exception as e:
        logger.error(f"Health server error: {e}")

async def send_self_ping(context: ContextTypes.DEFAULT_TYPE):
    url = os.environ.get("RENDER_EXTERNAL_URL")
    if not url:
        logger.info("RENDER_EXTERNAL_URL not set. Skipping self-ping.")
        return
    try:
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 DarkPointBot'}
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            if response.status == 200:
                logger.info("🟢 Self-ping successful! Bot kept alive.")
    except Exception as e:
        logger.error(f"🔴 Self-ping failed: {e}")# ============ START & MAIN MENU ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    existing = db.get_user(user.id)
    if not existing:
        referrer_id = 0
        if args and args[0].startswith("ref_"):
            try:
                referrer_id = int(args[0].replace("ref_", ""))
                if referrer_id == user.id:
                    referrer_id = 0
            except:
                referrer_id = 0

        db.create_user(user.id, user.username or "", user.first_name or "", referrer_id)

        if referrer_id > 0:
            context.user_data['pending_referrer'] = referrer_id
            captcha_q, captcha_a = generate_captcha()
            context.user_data['captcha_answer'] = captcha_a

            await update.message.reply_text(
                f"🔐 *تایید هویت*\n\n"
                f"لطفاً جواب این سوال رو بفرست:\n\n"
                f"❓ `{captcha_q}` = ?\n\n"
                f"_برای تایید زیرمجموعه شدن باید کپچا رو حل کنید_",
                parse_mode=ParseMode.MARKDOWN
            )
            return CAPTCHA_VERIFY

    if args and args[0].startswith("check_"):
        code = args[0].replace("check_", "")
        amount = db.claim_check(code, user.id)
        if amount:
            db.add_dark_points(user.id, amount)
            await update.message.reply_text(
                f"🎁 *چک شخصی فعال شد!*\n\n"
                f"💰 مبلغ: `{format_number(amount)}` دارک پوینت\n"
                f"✅ به موجودی شما اضافه شد!",
                parse_mode=ParseMode.MARKDOWN
            )
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        admin_id,
                        f"📋 *چک شخصی فعال شد*\n\n"
                        f"👤 کاربر: `{user.id}`\n"
                        f"💰 مبلغ: `{format_number(amount)}` DP\n"
                        f"🔗 کد: `{code}`",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except:
                    pass
            return
        else:
            await update.message.reply_text("❌ این چک قبلاً استفاده شده یا نامعتبر است.")
            return

    await show_main_menu(update, context)


async def captcha_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        answer = int(update.message.text.strip())
    except:
        await update.message.reply_text("❌ لطفاً فقط عدد بفرستید.")
        return CAPTCHA_VERIFY

    correct = context.user_data.get('captcha_answer')
    referrer_id = context.user_data.get('pending_referrer', 0)

    if answer != correct:
        captcha_q, captcha_a = generate_captcha()
        context.user_data['captcha_answer'] = captcha_a
        await update.message.reply_text(
            f"❌ *جواب اشتباه!*\n\nسوال جدید:\n❓ `{captcha_q}` = ?",
            parse_mode=ParseMode.MARKDOWN
        )
        return CAPTCHA_VERIFY

    joined = await check_force_join(user.id, context)
    if not joined:
        channels_text = "\n".join([f"🔗 {ch}" for ch in FORCE_JOIN_CHANNELS])
        kb = [[InlineKeyboardButton("✅ عضو شدم", callback_data="check_join_ref")]]
        await update.message.reply_text(
            f"📢 *ابتدا در کانال‌های زیر عضو شوید:*\n\n{channels_text}\n\n"
            f"سپس دکمه زیر را بزنید.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return ConversationHandler.END

    if referrer_id > 0:
        db.add_referral(referrer_id)
        db.add_dark_points(referrer_id, REFERRAL_REWARD)
        try:
            await context.bot.send_message(
                referrer_id,
                f"🎉 *زیرمجموعه جدید!*\n\n"
                f"👤 یک کاربر جدید با لینک شما عضو شد\n"
                f"💰 +{format_number(REFERRAL_REWARD)} دارک پوینت دریافت کردید!",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            pass

    context.user_data.pop('captcha_answer', None)
    context.user_data.pop('pending_referrer', None)

    await show_main_menu(update, context)
    return ConversationHandler.END


async def check_join_ref_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    joined = await check_force_join(user.id, context)
    if not joined:
        await query.answer("❌ هنوز عضو نشدی!", show_alert=True)
        return

    referrer_id = context.user_data.get('pending_referrer', 0)
    if referrer_id > 0:
        db.add_referral(referrer_id)
        db.add_dark_points(referrer_id, REFERRAL_REWARD)
        try:
            await context.bot.send_message(
                referrer_id,
                f"🎉 *زیرمجموعه جدید!*\n\n"
                f"💰 +{format_number(REFERRAL_REWARD)} دارک پوینت!",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
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

    balance = db_user['dark_points']
    level = db_user['level']
    title = get_level_title(level)

    bot_username = (await context.bot.get_me()).username

    keyboard = [
        [InlineKeyboardButton("⭐ برداشت استارز ⭐", callback_data="stars_withdraw")],
        [
            InlineKeyboardButton("🏴 دارک پوینت", callback_data="dark_point_menu"),
            InlineKeyboardButton("🛒 خرید پنل", callback_data="buy_panel"),
        ],
        [
            InlineKeyboardButton("🎁 گیفت رایگان", callback_data="free_gift"),
            InlineKeyboardButton("💰 خرید دارک پوینت", callback_data="buy_dp"),
        ],
        [
            InlineKeyboardButton("👥 زیرمجموعه‌گیری", callback_data="referral_menu"),
            InlineKeyboardButton("🏆 لیدربورد", callback_data="leaderboard"),
        ],
        [
            InlineKeyboardButton("📡 سلف", callback_data="self_menu"),
            InlineKeyboardButton("❤️ چالش لایکی", callback_data="like_challenge"),
        ],
        [InlineKeyboardButton("➕ افزودن به گروه", url=f"https://t.me/{bot_username}?startgroup=true")],
    ]

    text = (
        f"🏴 *به ربات دارک پوینت خوش آمدید!*\n\n"
        f"👤 *{user.first_name}*\n"
        f"🆔 شماره کاربری: `{user.id}`\n"
        f"💰 موجودی: `{format_number(balance)}` DP\n"
        f"📊 سطح: {level} | {title}\n\n"
        f"_دارک پوینت جمع کن، استارز بگیر!_ ⭐"
    )

    if query:
        try:
            await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
        except:
            await query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        try:
            await update.message.reply_sticker(STICKERS.get('welcome', ''))
        except:
            pass
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))


# ============ DARK POINT MENU ============

async def dark_point_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("📖 توضیحات کامل", callback_data="dp_info_1")],
        [InlineKeyboardButton("🔗 لینک زیرمجموعه‌گیری", callback_data="get_ref_link")],
        [InlineKeyboardButton("🏆 لیدربورد", callback_data="leaderboard")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
    ]

    user = db.get_user(query.from_user.id)
    balance = user['dark_points'] if user else 0
    level = user['level'] if user else 1
    title = get_level_title(level)
    next_req = get_next_level_requirement(level)
    needed = max(0, (next_req or 0) - (user['total_earned'] if user else 0))

    text = (
        f"🏴 *دارک پوینت*\n\n"
        f"💰 موجودی: `{format_number(balance)}` DP\n"
        f"📊 سطح: {level} | {title}\n"
    )
    if next_req:
        text += f"📈 تا سطح بعد: `{format_number(needed)}` DP\n"
    else:
        text += f"🏆 شما به بالاترین سطح رسیده‌اید!\n"

    text += (
        f"\n👥 زیرمجموعه‌ها: {user['referral_count'] if user else 0}\n"
        f"📊 کل دریافتی: `{format_number(user['total_earned'] if user else 0)}` DP\n\n"
        f"_برای اطلاعات بیشتر روی توضیحات کامل بزنید_"
    )

    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))


INFO_PAGES = {
    1: (
        "📖 *توضیحات دارک پوینت - صفحه 1/7*\n\n"
        "🏴 *دارک پوینت چیست؟*\n\n"
        "دارک پوینت واحد پولی اختصاصی این ربات است.\n"
        "با جمع‌آوری دارک پوینت می‌توانید:\n\n"
        "⭐ استارز تلگرام برداشت کنید\n"
        "🛒 پنل VPN خریداری کنید\n"
        "🎁 گیفت تدی رایگان بگیرید\n"
        "🎮 در بازی‌ها شرکت کنید\n"
        "🏭 کارخونه دارکی بسازید\n"
        "🏦 در بانک دارکی سرمایه‌گذاری کنید\n\n"
        "⭐ هر 1,000,000 DP = 50 استارز\n"
    ),
    2: (
        "📖 *توضیحات دارک پوینت - صفحه 2/7*\n\n"
        "💰 *نحوه دریافت دارک پوینت:*\n\n"
        "1️⃣ *کلمه دارک در گروه:*\n"
        "در گروهی که ربات حضور دارد کلمه `دارک` یا `دارک کانفیگ` بنویسید\n"
        "بسته به سطحتان بین 100 تا 250+ DP دریافت می‌کنید\n"
        "هر سطح بالاتر 40 DP بیشتر!\n\n"
        "2️⃣ *زیرمجموعه‌گیری:*\n"
        "هر زیرمجموعه = 30,000 DP\n\n"
        "3️⃣ *کارخونه دارکی:*\n"
        "با افتتاح کارخونه خودکار DP ماین کنید\n\n"
        "4️⃣ *بانک دارکی:*\n"
        "سرمایه‌گذاری کنید و 10% سود بگیرید\n\n"
        "5️⃣ *بازی:*\n"
        "با نوشتن `بازی` + مبلغ در گروه\n"
    ),
    3: (
        "📖 *توضیحات دارک پوینت - صفحه 3/7*\n\n"
        "📊 *سیستم سطح‌بندی:*\n\n"
        "سطح 1: 0 DP 🌑\n"
        "سطح 2: 20,000 DP 🌒\n"
        "سطح 3: 40,000 DP 🌓\n"
        "سطح 4: 80,000 DP 🌔\n"
        "سطح 5: 150,000 DP 🌕\n"
        "سطح 6: 200,000 DP ⭐\n"
        "سطح 7: 300,000 DP 🌟\n"
        "سطح 8: 500,000 DP 💫\n"
        "سطح 9: 800,000 DP ✨\n"
        "سطح 10: 1,000,000 DP 🥈\n"
        "سطح 11-20: تا 20,000,000 DP 🏴\n\n"
        "هر سطح جایزه ارتقا دارد!\n"
    ),
    4: (
        "📖 *توضیحات دارک پوینت - صفحه 4/7*\n\n"
        "🏭 *کارخونه دارکی:*\n\n"
        "💵 هزینه افتتاح: 100,000 DP\n"
        "🔧 هزینه نگهداری: ساعتی 80 DP\n\n"
        "📊 *سطوح کارخونه:*\n"
        "سطح 1: دقیقه‌ای 10 DP ماین\n"
        "سطح 2: دقیقه‌ای 25 DP (ارتقا: 50K)\n"
        "سطح 3: دقیقه‌ای 40 DP (ارتقا: 80K)\n"
        "سطح 4: دقیقه‌ای 50 DP (ارتقا: 100K)\n"
        "سطح 5: دقیقه‌ای 100 DP (ارتقا: 250K)\n\n"
        "⚠️ اگر موجودی نگهداری نداشته باشید کارخونه متوقف می‌شود\n"
    ),
    5: (
        "📖 *توضیحات دارک پوینت - صفحه 5/7*\n\n"
        "🏦 *بانک دارکی:*\n\n"
        "💵 هزینه افتتاح حساب: 20,000 DP\n"
        "📈 سود 24 ساعته: 10%\n\n"
        "• شماره کارت 13 رقمی دریافت کنید\n"
        "• مبلغ دلخواه واریز کنید\n"
        "• بعد از 24 ساعت با 10% سود برداشت کنید\n\n"
        "🎮 *بازی:*\n"
        "• در گروه بنویسید: `بازی 1000`\n"
        "• بازی 2 نفره است\n"
        "• برنده 2 برابر مبلغ دریافت می‌کند\n"
        "• برنده کاملاً تصادفی انتخاب می‌شود\n"
    ),
    6: (
        "📖 *توضیحات دارک پوینت - صفحه 6/7*\n\n"
        "💸 *انتقال دارک پوینت:*\n\n"
        "روش 1: روی پیام ریپلای کنید و بنویسید:\n"
        "`انتقال 20000`\n\n"
        "روش 2: در گروه بنویسید:\n"
        "`انتقال 20000 به 123456789`\n\n"
        "⚠️ 10% کارمزد از انتقال‌دهنده کسر می‌شود\n\n"
        "📡 *سلف:*\n"
        "💵 فعال‌سازی: 1,000 DP\n"
        "🔧 نگهداری: ساعتی 600 DP\n\n"
        "❤️ *چالش لایکی:*\n"
        "💵 فعال‌سازی 7 روزه: 30,000 DP\n"
    ),
    7: (
        "📖 *توضیحات دارک پوینت - صفحه 7/7*\n\n"
        "⭐ *برداشت استارز:*\n\n"
        "هر 1,000,000 DP = 50 استارز\n"
        "کاملاً رایگان با زیرمجموعه‌گیری!\n\n"
        "🎁 *گیفت رایگان:*\n"
        "گیفت تدی تلگرام با دارک پوینت\n\n"
        "🔗 *دستورات گروهی:*\n"
        "• `دارک` - دریافت DP\n"
        "• `دارک کانفیگ` - دریافت DP\n"
        "• `موجودی` - مشاهده موجودی\n"
        "• `پروفایل دارکی` - پروفایل کامل\n"
        "• `بازی 1000` - ایجاد بازی\n"
        "• `انتقال 1000` - انتقال DP\n"
        "• `بانک دارکی` - بانک\n"
        "• `کارخونه دارکی` - کارخونه\n"
        "• `لیدربورد` - جدول برترین‌ها\n"
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
    if page < 7:
        buttons.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"dp_info_{page+1}"))

    keyboard = [buttons] if buttons else []
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="dark_point_menu")])

    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))# ============ GROUP HANDLERS ============

async def on_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            try:
                count = await context.bot.get_chat_member_count(chat.id)
                if count < MIN_GROUP_MEMBERS:
                    await update.message.reply_text(
                        f"❌ *گروه باید حداقل {MIN_GROUP_MEMBERS} عضو داشته باشد!*\n"
                        f"👥 اعضای فعلی: {count}",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    await context.bot.leave_chat(chat.id)
                    return
                db.add_group(chat.id, chat.title, count)
                await update.message.reply_text(
                    "🏴 *ربات دارک پوینت فعال شد!*\n\n"
                    "📝 دستورات:\n"
                    "• `دارک` - دریافت دارک پوینت\n"
                    "• `موجودی` - مشاهده موجودی\n"
                    "• `پروفایل دارکی` - پروفایل\n"
                    "• `بازی [مبلغ]` - شروع بازی\n"
                    "• `بانک دارکی` - بانک\n"
                    "• `کارخونه دارکی` - کارخونه\n",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Error in new chat: {e}")


async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    user = update.effective_user
    chat = update.effective_chat

    if chat.type not in ['group', 'supergroup']:
        return

    if not db.get_user(user.id):
        db.create_user(user.id, user.username or "", user.first_name or "")

    u = db.get_user(user.id)
    if u and u['factory_active']:
        db.factory_maintenance_due(user.id)
    if u and u['self_active']:
        db.self_maintenance_due(user.id)

    if text in ['دارک', 'دارک کانفیگ']:
        await handle_dark_claim(update, context)
        return

    if text == 'موجودی':
        await handle_balance_check(update, context)
        return

    if text == 'پروفایل دارکی':
        await handle_dark_profile(update, context)
        return

    if text.startswith('بازی'):
        parts = text.split()
        if len(parts) >= 2:
            try:
                amount = int(parts[1])
                await handle_create_game(update, context, amount)
            except ValueError:
                pass
        return

    if text.startswith('انتقال '):
        await handle_transfer(update, context)
        return

    if text == 'بانک دارکی':
        await handle_bank(update, context)
        return

    if text == 'کارخونه دارکی':
        await handle_factory(update, context)
        return

    if text == 'لیدربورد':
        await handle_leaderboard_group(update, context)
        return


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
            f"⏳ *صبر کنید!*\n\n"
            f"⏰ {mins} دقیقه و {secs} ثانیه تا دریافت بعدی\n"
            f"💡 _صبوری کلید موفقیته!_",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    level = u['level']
    min_dp, max_dp = get_dp_range(level)
    earned = random.randint(min_dp, max_dp)
    cooldown = get_random_cooldown()

    db.add_dark_points(user.id, earned)
    db.set_claim(user.id, cooldown)

    new_level, reward = db.check_and_update_level(user.id)

    cd_mins = cooldown // 60
    cd_secs = cooldown % 60

    try:
        await update.message.reply_sticker(STICKERS.get('earn', ''))
    except:
        pass

    text = (
        f"🏴 *دارک پوینت دریافت شد!*\n\n"
        f"👤 {user.first_name}\n"
        f"💰 +`{format_number(earned)}` دارک پوینت\n"
        f"📊 سطح: {level} | {get_level_title(level)}\n"
        f"💎 موجودی جدید: `{format_number(db.get_balance(user.id))}` DP\n\n"
        f"⏰ دریافت بعدی: {cd_mins} دقیقه و {cd_secs} ثانیه"
    )

    if new_level:
        text += (
            f"\n\n🎉 *ارتقا به سطح {new_level}!* 🎉\n"
            f"🏅 {get_level_title(new_level)}\n"
            f"🎁 جایزه ارتقا: +`{format_number(reward)}` DP"
        )
        try:
            await update.message.reply_sticker(STICKERS.get('levelup', ''))
        except:
            pass

    kb = [[InlineKeyboardButton("🏴 ربات دارک پوینت", url=f"https://t.me/{(await context.bot.get_me()).username}")]]
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


async def handle_balance_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    balance = db.get_balance(user.id)
    level = db.get_level(user.id)

    kb = [[InlineKeyboardButton("🏴 ربات دارک پوینت", url=f"https://t.me/{(await context.bot.get_me()).username}")]]
    await update.message.reply_text(
        f"💰 *موجودی دارک پوینت*\n\n"
        f"👤 {user.first_name}\n"
        f"💎 موجودی: `{format_number(balance)}` DP\n"
        f"📊 سطح: {level} | {get_level_title(level)}",
        parse_mode=ParseMode.MARKDOWN,
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

    factory_info = ""
    if u['factory_active']:
        f_level = u['factory_level']
        mine_rate = FACTORY_LEVELS[f_level]['mine_per_min']
        factory_info = f"\n🏭 کارخونه سطح {f_level} | دقیقه‌ای {mine_rate} DP"

    bank_info = ""
    if u['bank_account']:
        bank_info = f"\n🏦 حساب بانکی: `{u['bank_card']}`\n💰 موجودی بانک: `{format_number(u['bank_balance'])}` DP"

    stars_price = int(db.get_setting('stars_price', '1000000'))
    stars_can = balance // stars_price
    if stars_can > 0:
        stars_text = f"\n⭐ قابل برداشت: {stars_can * 50} استارز"
    else:
        stars_text = f"\n⭐ تا برداشت استارز: `{format_number(stars_price - balance)}` DP نیاز"

    try:
        await update.message.reply_sticker(STICKERS.get('profile', ''))
    except:
        pass

    text = (
        f"🏴 *پروفایل دارکی*\n"
        f"{'━' * 25}\n\n"
        f"👤 نام: *{user.first_name}*\n"
        f"🆔 شماره کاربری: `{user.id}`\n"
        f"📛 یوزرنیم: @{user.username or 'ندارد'}\n\n"
        f"💰 موجودی: `{format_number(balance)}` DP\n"
        f"📊 سطح: {level} | {title}\n"
    )

    if next_req:
        text += f"📈 تا سطح {level+1}: `{format_number(needed)}` DP\n"
    else:
        text += f"🏆 حداکثر سطح!\n"

    text += (
        f"📊 کل دریافتی: `{format_number(total)}` DP\n"
        f"👥 زیرمجموعه‌ها: {refs}\n"
        f"{stars_text}"
        f"{factory_info}"
        f"{bank_info}\n\n"
        f"{'━' * 25}\n"
        f"🏴 _دارک پوینت | قدرت تاریکی_"
    )

    kb = [[InlineKeyboardButton("🏴 ربات دارک پوینت", url=f"https://t.me/{(await context.bot.get_me()).username}")]]
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


# ============ GAME ============

async def handle_create_game(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: int):
    user = update.effective_user
    chat = update.effective_chat

    if amount < MIN_GAME_AMOUNT:
        await update.message.reply_text(f"❌ حداقل مبلغ بازی {format_number(MIN_GAME_AMOUNT)} DP است.")
        return

    balance = db.get_balance(user.id)
    if balance < amount:
        await update.message.reply_text(
            f"❌ *موجودی ناکافی!*\n"
            f"💰 موجودی شما: `{format_number(balance)}` DP\n"
            f"💵 مبلغ بازی: `{format_number(amount)}` DP",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    db.remove_dark_points(user.id, amount)

    try:
        await update.message.reply_sticker(STICKERS.get('game', ''))
    except:
        pass

    msg = await update.message.reply_text(
        f"🎮 *بازی جدید!*\n\n"
        f"👤 سازنده: {get_user_display(user)}\n"
        f"💰 مبلغ ورود: `{format_number(amount)}` DP\n"
        f"🏆 جایزه برنده: `{format_number(amount * 2)}` DP\n\n"
        f"⏳ منتظر حریف...",
        parse_mode=ParseMode.MARKDOWN,
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
        await query.answer("❌ این بازی تمام شده!", show_alert=True)
        return

    if user.id == game['creator_id']:
        await query.answer("❌ نمی‌توانید به بازی خودتان بپیوندید!", show_alert=True)
        return

    amount = game['amount']
    balance = db.get_balance(user.id)
    if balance < amount:
        await query.answer(f"❌ موجودی ناکافی! نیاز: {format_number(amount)} DP", show_alert=True)
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

    try:
        winner_info = await context.bot.get_chat(winner_id)
        winner_display = f"@{winner_info.username}" if winner_info.username else f"`{winner_id}`"
    except:
        winner_display = f"`{winner_id}`"

    try:
        loser_info = await context.bot.get_chat(loser_id)
        loser_display = f"@{loser_info.username}" if loser_info.username else f"`{loser_id}`"
    except:
        loser_display = f"`{loser_id}`"

    winner_balance = db.get_balance(winner_id)
    loser_balance = db.get_balance(loser_id)

    await query.edit_message_text(
        f"🎮 *نتیجه بازی!*\n\n"
        f"{'━' * 25}\n"
        f"🏆 *برنده:* {winner_display}\n"
        f"💰 جایزه: +`{format_number(prize)}` DP\n"
        f"💎 موجودی جدید: `{format_number(winner_balance)}` DP\n\n"
        f"💔 *بازنده:* {loser_display}\n"
        f"💎 موجودی جدید: `{format_number(loser_balance)}` DP\n"
        f"{'━' * 25}\n\n"
        f"🎲 _برنده بصورت کاملاً تصادفی انتخاب شد_",
        parse_mode=ParseMode.MARKDOWN
    )


async def cancel_game_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    game_id = int(query.data.split("_")[-1])

    game = db.get_game(game_id)
    if not game:
        await query.answer("❌ بازی یافت نشد!", show_alert=True)
        return

    if user.id != game['creator_id']:
        await query.answer("❌ فقط سازنده می‌تواند لغو کند!", show_alert=True)
        return

    if game['status'] != 'waiting':
        await query.answer("❌ بازی قبلاً شروع شده!", show_alert=True)
        return

    db.add_dark_points(game['creator_id'], game['amount'])
    db.cancel_game(game_id)

    await query.edit_message_text(
        f"❌ *بازی لغو شد*\n\n💰 مبلغ `{format_number(game['amount'])}` DP بازگردانده شد.",
        parse_mode=ParseMode.MARKDOWN
    )# ============ TRANSFER ============

async def handle_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()

    if update.message.reply_to_message:
        parts = text.split()
        if len(parts) >= 2:
            try:
                amount = int(parts[1])
            except:
                await update.message.reply_text("❌ مبلغ نامعتبر!")
                return

            target_id = update.message.reply_to_message.from_user.id
            if target_id == user.id:
                await update.message.reply_text("❌ نمی‌توانید به خودتان انتقال دهید!")
                return

            fee = int(amount * TRANSFER_FEE)
            total_cost = amount + fee
            balance = db.get_balance(user.id)

            if balance < total_cost:
                await update.message.reply_text(
                    f"❌ *موجودی ناکافی!*\n"
                    f"💰 مبلغ انتقال: `{format_number(amount)}` DP\n"
                    f"💸 کارمزد 10%: `{format_number(fee)}` DP\n"
                    f"📊 کل نیاز: `{format_number(total_cost)}` DP\n"
                    f"💎 موجودی شما: `{format_number(balance)}` DP",
                    parse_mode=ParseMode.MARKDOWN
                )
                return

            if not db.remove_dark_points(user.id, total_cost):
                await update.message.reply_text("❌ خطا در انتقال!")
                return

            db.add_dark_points(target_id, amount)
            db.record_transfer(user.id, target_id, amount, fee)

            target = update.message.reply_to_message.from_user
            target_display = f"@{target.username}" if target.username else f"`{target.id}`"

            await update.message.reply_text(
                f"✅ *انتقال موفق!*\n\n"
                f"💰 مبلغ: `{format_number(amount)}` DP\n"
                f"💸 کارمزد: `{format_number(fee)}` DP\n"
                f"👤 مقصد: {target_display}\n"
                f"💎 موجودی جدید شما: `{format_number(db.get_balance(user.id))}` DP",
                parse_mode=ParseMode.MARKDOWN
            )

            try:
                await context.bot.send_message(
                    target_id,
                    f"💰 *دارک پوینت دریافت کردید!*\n\n"
                    f"👤 از: {get_user_display(user)}\n"
                    f"💰 مبلغ: `{format_number(amount)}` DP\n"
                    f"💎 موجودی جدید: `{format_number(db.get_balance(target_id))}` DP",
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                pass
            return

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

        fee = int(amount * TRANSFER_FEE)
        total_cost = amount + fee
        balance = db.get_balance(user.id)

        if balance < total_cost:
            await update.message.reply_text(
                f"❌ *موجودی ناکافی!*\n"
                f"📊 کل نیاز: `{format_number(total_cost)}` DP\n"
                f"💎 موجودی شما: `{format_number(balance)}` DP",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if not db.remove_dark_points(user.id, total_cost):
            await update.message.reply_text("❌ خطا!")
            return

        db.add_dark_points(target_id, amount)
        db.record_transfer(user.id, target_id, amount, fee)

        await update.message.reply_text(
            f"✅ *انتقال موفق!*\n\n"
            f"💰 مبلغ: `{format_number(amount)}` DP\n"
            f"💸 کارمزد: `{format_number(fee)}` DP\n"
            f"👤 مقصد: `{target_id}`\n"
            f"💎 موجودی جدید: `{format_number(db.get_balance(user.id))}` DP",
            parse_mode=ParseMode.MARKDOWN
        )

        try:
            await context.bot.send_message(
                target_id,
                f"💰 *دارک پوینت دریافت شد!*\n\n"
                f"💰 مبلغ: `{format_number(amount)}` DP\n"
                f"💎 موجودی جدید: `{format_number(db.get_balance(target_id))}` DP",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            pass


# ============ BANK ============

async def handle_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = db.get_user(user.id)

    try:
        await update.message.reply_sticker(STICKERS.get('bank', ''))
    except:
        pass

    total_bank = db.get_total_bank_balance()

    if not u['bank_account']:
        kb = [[InlineKeyboardButton("🏦 افتتاح حساب (20,000 DP)", callback_data="bank_open")]]
        await update.message.reply_text(
            f"🏦 *بانک دارکی*\n\n"
            f"❌ شما حسابی در بانک دارکی ندارید\n\n"
            f"💵 هزینه افتتاح: `20,000` DP\n"
            f"📈 سود 24 ساعته: 10%\n\n"
            f"🏦 موجودی کل بانک: `{format_number(total_bank)}` DP\n\n"
            f"_افتتاح حساب کنید و سرمایه‌گذاری کنید!_",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(kb)
        )
    else:
        elapsed = time.time() - u['bank_deposit_time'] if u['bank_deposit_time'] > 0 else 0
        interest_ready = elapsed >= 86400 and u['bank_balance'] > 0 and not u['bank_interest_collected']
        potential_interest = int(u['bank_balance'] * 0.10) if interest_ready else 0

        buttons = []
        if u['bank_balance'] == 0:
            buttons.append([InlineKeyboardButton("💰 واریز دارک پوینت", callback_data="bank_deposit")])
        else:
            if interest_ready:
                buttons.append([InlineKeyboardButton("💸 برداشت (با سود)", callback_data="bank_withdraw")])
            else:
                remaining = max(0, 86400 - elapsed) if u['bank_balance'] > 0 else 0
                hours = int(remaining // 3600)
                mins = int((remaining % 3600) // 60)
                buttons.append([InlineKeyboardButton(f"⏰ {hours}h {mins}m تا سود", callback_data="bank_wait")])
            buttons.append([InlineKeyboardButton("💰 واریز بیشتر", callback_data="bank_deposit")])

        text = (
            f"🏦 *بانک دارکی*\n"
            f"{'━' * 25}\n\n"
            f"💳 شماره کارت: `{u['bank_card']}`\n"
            f"💰 موجودی بانک: `{format_number(u['bank_balance'])}` DP\n"
        )
        if potential_interest > 0:
            text += f"📈 سود آماده: +`{format_number(potential_interest)}` DP\n"
        text += (
            f"\n🏦 موجودی کل بانک: `{format_number(total_bank)}` DP\n"
            f"{'━' * 25}"
        )

        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))


async def bank_open_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    balance = db.get_balance(user.id)
    if balance < BANK_OPEN_COST:
        await query.answer(f"❌ موجودی ناکافی! نیاز: {format_number(BANK_OPEN_COST)} DP", show_alert=True)
        return

    kb = [
        [InlineKeyboardButton("🎲 خودکار بساز", callback_data="bank_auto_card")],
        [InlineKeyboardButton("✏️ شماره کارت دلخواه", callback_data="bank_custom_card")],
    ]
    await query.edit_message_text(
        f"🏦 *افتتاح حساب بانک دارکی*\n\n"
        f"برای افتتاح حساب یک شماره کارت بسازید:\n\n"
        f"🎲 خودکار: سیستم یک شماره 13 رقمی تصادفی می‌سازد\n"
        f"✏️ دلخواه: شماره 13 رقمی دلخواهتان را بفرستید",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def bank_auto_card_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    balance = db.get_balance(user.id)
    if balance < BANK_OPEN_COST:
        await query.answer("❌ موجودی ناکافی!", show_alert=True)
        return

    card = db.generate_bank_card()
    while db.card_exists(card):
        card = db.generate_bank_card()

    db.remove_dark_points(user.id, BANK_OPEN_COST)
    db.open_bank_account(user.id, card)

    await query.edit_message_text(
        f"✅ *حساب بانک دارکی افتتاح شد!*\n\n"
        f"💳 شماره کارت شما: `{card}`\n"
        f"💵 هزینه افتتاح: `{format_number(BANK_OPEN_COST)}` DP\n\n"
        f"_اکنون می‌توانید واریز کنید و سود بگیرید!_",
        parse_mode=ParseMode.MARKDOWN
    )


async def bank_custom_card_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_bank_card'] = True

    await query.edit_message_text(
        "✏️ *شماره کارت دلخواه*\n\n"
        "یک شماره 13 رقمی تشکیل شده از اعداد انگلیسی بفرستید\n"
        "⚠️ نباید قبلاً ثبت شده باشد\n\n"
        "_به پیوی ربات بفرستید_",
        parse_mode=ParseMode.MARKDOWN
    )


async def bank_deposit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_bank_deposit'] = True

    balance = db.get_balance(query.from_user.id)
    await query.edit_message_text(
        f"💰 *واریز به بانک دارکی*\n\n"
        f"💎 موجودی فعلی: `{format_number(balance)}` DP\n\n"
        f"مبلغ مورد نظر برای واریز را به پیوی ربات بفرستید:",
        parse_mode=ParseMode.MARKDOWN
    )


async def bank_withdraw_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    balance, interest = db.bank_withdraw(user.id)
    total = balance + interest

    if total == 0:
        await query.answer("❌ موجودی بانکی ندارید!", show_alert=True)
        return

    await query.edit_message_text(
        f"✅ *برداشت از بانک دارکی*\n\n"
        f"💰 اصل سپرده: `{format_number(balance)}` DP\n"
        f"📈 سود 10%: +`{format_number(interest)}` DP\n"
        f"💎 کل دریافتی: `{format_number(total)}` DP\n\n"
        f"✅ به موجودی شما اضافه شد!\n"
        f"💎 موجودی جدید: `{format_number(db.get_balance(user.id))}` DP",
        parse_mode=ParseMode.MARKDOWN
    )


async def bank_wait_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("⏰ سود شما هنوز آماده نیست. لطفاً 24 ساعت صبر کنید.", show_alert=True)


# ============ FACTORY ============

async def handle_factory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = db.get_user(user.id)

    try:
        await update.message.reply_sticker(STICKERS.get('factory', ''))
    except:
        pass

    if not u['factory_active'] and u['factory_level'] == 0:
        kb = [[InlineKeyboardButton(f"🏭 افتتاح کارخونه ({format_number(FACTORY_OPEN_COST)} DP)", callback_data="factory_open")]]
        await update.message.reply_text(
            f"🏭 *کارخونه دارکی*\n\n"
            f"❌ شما کارخونه‌ای ندارید\n\n"
            f"💵 هزینه افتتاح: `{format_number(FACTORY_OPEN_COST)}` DP\n"
            f"🔧 هزینه نگهداری: ساعتی {FACTORY_HOURLY_MAINTENANCE} DP\n\n"
            f"📊 *سطوح کارخونه:*\n"
            f"سطح 1: دقیقه‌ای 10 DP\n"
            f"سطح 2: دقیقه‌ای 25 DP\n"
            f"سطح 3: دقیقه‌ای 40 DP\n"
            f"سطح 4: دقیقه‌ای 50 DP\n"
            f"سطح 5: دقیقه‌ای 100 DP\n",
            parse_mode=ParseMode.MARKDOWN,
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

    status = "✅ فعال" if u['factory_active'] else "❌ غیرفعال (موجودی نگهداری ناکافی)"

    text = (
        f"🏭 *کارخونه دارکی*\n"
        f"{'━' * 25}\n\n"
        f"📊 سطح کارخونه: {f_level}\n"
        f"⚡ نرخ استخراج: {mine_rate} DP/دقیقه\n"
        f"📋 وضعیت: {status}\n"
    )
    if mined > 0:
        text += f"💰 جمع‌آوری شده: +`{format_number(mined)}` DP\n"
    if maintenance == -1:
        text += f"\n⚠️ کارخونه بخاطر کمبود موجودی متوقف شد!\n"
    text += f"\n💎 موجودی: `{format_number(db.get_balance(user.id))}` DP\n{'━' * 25}"

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))


async def factory_open_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    balance = db.get_balance(user.id)
    if balance < FACTORY_OPEN_COST:
        await query.answer(f"❌ موجودی ناکافی! نیاز: {format_number(FACTORY_OPEN_COST)} DP", show_alert=True)
        return

    db.remove_dark_points(user.id, FACTORY_OPEN_COST)
    db.open_factory(user.id)

    await query.edit_message_text(
        f"✅ *کارخونه دارکی افتتاح شد!*\n\n"
        f"📊 سطح: 1\n"
        f"⚡ نرخ استخراج: 10 DP/دقیقه\n"
        f"💵 هزینه: `{format_number(FACTORY_OPEN_COST)}` DP\n\n"
        f"_کارخونه شروع به ماین کرد!_",
        parse_mode=ParseMode.MARKDOWN
    )


async def factory_upgrade_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    u = db.get_user(user.id)
    if not u or u['factory_level'] >= 5:
        await query.answer("❌ حداکثر سطح!", show_alert=True)
        return

    upgrade_cost = FACTORY_LEVELS[u['factory_level']]['upgrade_cost']
    if db.get_balance(user.id) < upgrade_cost:
        await query.answer(f"❌ موجودی ناکافی! نیاز: {format_number(upgrade_cost)} DP", show_alert=True)
        return

    db.collect_factory(user.id)
    db.remove_dark_points(user.id, upgrade_cost)
    db.upgrade_factory(user.id)

    new_level = u['factory_level'] + 1
    new_rate = FACTORY_LEVELS[new_level]['mine_per_min']

    await query.edit_message_text(
        f"⬆️ *کارخونه ارتقا یافت!*\n\n"
        f"📊 سطح جدید: {new_level}\n"
        f"⚡ نرخ جدید: {new_rate} DP/دقیقه\n"
        f"💵 هزینه ارتقا: `{format_number(upgrade_cost)}` DP\n"
        f"💎 موجودی: `{format_number(db.get_balance(user.id))}` DP",
        parse_mode=ParseMode.MARKDOWN
    )


async def factory_collect_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    mined = db.collect_factory(user.id)
    db.factory_maintenance_due(user.id)

    await query.answer(f"💰 {format_number(mined)} DP جمع‌آوری شد!", show_alert=True)# ============ STARS WITHDRAWAL ============

async def stars_withdraw_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    active = db.get_setting('stars_section_active', '1')
    if active != '1':
        await query.answer("❌ این بخش موقتاً خاموش می‌باشد", show_alert=True)
        return

    stars_price = int(db.get_setting('stars_price', '1000000'))
    balance = db.get_balance(user.id)
    can_withdraw = balance >= stars_price
    needed = max(0, stars_price - balance)

    text = (
        f"⭐ *برداشت استارز*\n"
        f"{'━' * 25}\n\n"
        f"💎 موجودی شما: `{format_number(balance)}` DP\n"
        f"⭐ هر {format_number(stars_price)} DP = {STARS_AMOUNT} استارز\n\n"
    )

    if can_withdraw:
        text += (
            f"✅ *شما می‌توانید {STARS_AMOUNT} استارز برداشت کنید!*\n\n"
            f"🎉 _کاملاً رایگان با زیرمجموعه‌گیری!_\n"
            f"_استارز بگیرید و اکانتتان را خاص کنید!_ ⭐"
        )
        kb = [
            [InlineKeyboardButton(f"⭐ برداشت {STARS_AMOUNT} استارز", callback_data="stars_do_withdraw")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
        ]
    else:
        text += (
            f"❌ موجودی ناکافی\n"
            f"📈 `{format_number(needed)}` DP دیگر نیاز دارید\n\n"
            f"💡 _با زیرمجموعه‌گیری رایگان استارز بگیرید!_\n"
            f"👥 هر زیرمجموعه = {format_number(REFERRAL_REWARD)} DP"
        )
        kb = [
            [InlineKeyboardButton("👥 زیرمجموعه‌گیری", callback_data="referral_menu")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
        ]

    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


async def stars_do_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    kb = [
        [InlineKeyboardButton("👤 همین اکانتم", callback_data="stars_self")],
        [InlineKeyboardButton("👥 اکانت دیگه", callback_data="stars_other")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="stars_withdraw")],
    ]

    await query.edit_message_text(
        f"⭐ *برداشت {STARS_AMOUNT} استارز*\n\n"
        f"برای همین اکانت می‌خواهید یا اکانت دیگه؟",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def stars_self_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    stars_price = int(db.get_setting('stars_price', '1000000'))
    if not db.remove_dark_points(user.id, stars_price):
        await query.answer("❌ موجودی ناکافی!", show_alert=True)
        return

    order_id = db.create_stars_order(user.id, str(user.id), 'self', STARS_AMOUNT, stars_price)

    await query.edit_message_text(
        f"✅ *سفارش برداشت استارز ثبت شد!*\n\n"
        f"⭐ تعداد: {STARS_AMOUNT} استارز\n"
        f"👤 مقصد: همین اکانت (`{user.id}`)\n"
        f"💵 هزینه: `{format_number(stars_price)}` DP\n\n"
        f"⏳ _بزودی واریز می‌شود_",
        parse_mode=ParseMode.MARKDOWN
    )

    user_display = f"@{user.username}" if user.username else f"`{user.id}`"
    bot_username = (await context.bot.get_me()).username
    log_kb = [[InlineKeyboardButton("🤖 ورود به ربات", url=f"https://t.me/{bot_username}")]]
    await send_log(context,
        f"⭐ *سفارش جدید برداشت استارز*\n\n"
        f"👤 کاربر: {user_display}\n"
        f"🆔 شماره کاربری: `{user.id}`\n"
        f"⭐ تعداد: {STARS_AMOUNT} استارز\n"
        f"📍 مقصد: `{user.id}`\n"
        f"💵 هزینه: `{format_number(stars_price)}` DP",
        reply_markup=InlineKeyboardMarkup(log_kb)
    )

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"⭐ *سفارش برداشت استارز*\n\n"
                f"👤 `{user.id}`\n"
                f"⭐ {STARS_AMOUNT} استارز\n"
                f"📍 مقصد: `{user.id}` (خودش)",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            pass


async def stars_other_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_stars_target'] = True

    await query.edit_message_text(
        "👥 *اکانت دیگه*\n\n"
        "آیدی اکانتی که می‌خواهید استارز براش واریز بشه رو به پیوی ربات بفرستید:\n\n"
        "_مثال: @username یا شماره عددی_",
        parse_mode=ParseMode.MARKDOWN
    )


# ============ FREE GIFT ============

async def free_gift_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    active = db.get_setting('gift_section_active', '1')
    if active != '1':
        await query.answer("❌ این بخش موقتاً خاموش می‌باشد", show_alert=True)
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
        f"🎁 *گیفت رایگان*\n"
        f"{'━' * 25}\n\n"
        f"🧸 *گیفت تدی تلگرام*\n"
        f"💰 قیمت: `{format_number(gift_price)}` DP\n"
        f"💎 موجودی شما: `{format_number(balance)}` DP\n\n"
        f"هر `{format_number(gift_price)}` DP = یک گیفت تدی 🧸\n\n"
        f"🆓 _رایگان! با زیرمجموعه‌گیری گیفت تدی بگیرید!_\n"
        f"👥 هر زیرمجموعه = {format_number(REFERRAL_REWARD)} DP\n"
    )

    buttons = []
    if can_buy:
        buttons.append([InlineKeyboardButton("🧸 سفارش گیفت تدی", callback_data="order_gift_teddy")])
    else:
        needed = gift_price - balance
        text += f"\n📈 `{format_number(needed)}` DP دیگر نیاز دارید\n"

    for plan in plans:
        plan_num = plan['key'].split('_')[2]
        name = plan['value']
        price = int(db.get_setting(f'gift_plan_{plan_num}_price', '0'))
        if price > 0:
            buttons.append([InlineKeyboardButton(f"🎁 {name} ({format_number(price)} DP)", callback_data=f"order_gift_custom_{plan_num}")])

    buttons.append([InlineKeyboardButton("👥 زیرمجموعه‌گیری", callback_data="referral_menu")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])

    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))


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
        f"✅ *سفارش گیفت تدی ثبت شد!*\n\n"
        f"🧸 گیفت تدی تلگرام\n"
        f"💵 هزینه: `{format_number(gift_price)}` DP\n"
        f"🆔 شماره سفارش: {order_id}\n\n"
        f"⏳ _بزودی ارسال می‌شود_",
        parse_mode=ParseMode.MARKDOWN
    )

    bot_username = (await context.bot.get_me()).username
    log_kb = [[InlineKeyboardButton("🤖 ورود به ربات", url=f"https://t.me/{bot_username}")]]
    await send_log(context,
        f"🧸 *سفارش جدید گیفت تدی تلگرام*\n\n"
        f"👤 شماره کاربری: `{user.id}`\n"
        f"💵 هزینه: `{format_number(gift_price)}` DP",
        reply_markup=InlineKeyboardMarkup(log_kb)
    )

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"🧸 *سفارش گیفت تدی*\n\n"
                f"👤 `{user.id}`\n"
                f"💵 `{format_number(gift_price)}` DP",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
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
        f"✅ *سفارش ثبت شد!*\n\n"
        f"🎁 {name}\n"
        f"💵 هزینه: `{format_number(price)}` DP\n\n"
        f"⏳ _بزودی ارسال می‌شود_",
        parse_mode=ParseMode.MARKDOWN
    )

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"🎁 *سفارش گیفت*: {name}\n👤 `{user.id}`\n💵 `{format_number(price)}` DP",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            pass


# ============ BUY DARK POINTS ============

async def buy_dp_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    active = db.get_setting('buy_dp_active', '1')
    if active != '1':
        await query.answer("❌ این بخش موقتاً خاموش می‌باشد", show_alert=True)
        return

    dp_amount = int(db.get_setting('buy_dp_amount', '500000'))
    price_toman = int(db.get_setting('buy_dp_price_toman', '50000'))

    user = query.from_user
    u = db.get_user(user.id)
    already_bought = u['bought_dp'] if u else 0

    try:
        await context.bot.send_sticker(query.message.chat_id, STICKERS.get('stars', ''))
    except:
        pass

    text = (
        f"💰 *خرید دارک پوینت*\n"
        f"{'━' * 25}\n\n"
        f"💎 هر `{format_number(dp_amount)}` دارک پوینت\n"
        f"💵 قیمت: `{format_number(price_toman)}` تومان\n\n"
    )

    if already_bought:
        text += "⚠️ شما قبلاً خرید کرده‌اید. بقیه را باید زیرمجموعه‌گیری کنید!\n"
    else:
        text += "✅ هر نفر فقط یکبار می‌تواند خرید کند\n"

    text += f"\n👥 _بقیه‌اش رو باید زیرمجموعه‌گیری کنید!_\n"

    kb = [
        [InlineKeyboardButton("📩 پشتیبانی", url=f"https://t.me/{SUPPORT_USERNAME.replace('@', '')}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
    ]

    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


# ============ LEADERBOARD ============

async def leaderboard_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    rows = db.get_leaderboard(100)

    text = "🏆 *لیدربورد دارک پوینت*\n"
    text += f"{'━' * 25}\n\n"

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}

    for i, row in enumerate(rows[:20], 1):
        medal = medals.get(i, f"{i}.")
        name = row['first_name'] or row['username'] or str(row['user_id'])
        text += f"{medal} *{name}* - `{format_number(row['dark_points'])}` DP\n"

    if len(rows) > 20:
        text += f"\n_... و {len(rows) - 20} نفر دیگر_\n"

    text += f"\n{'━' * 25}\n🏆 _100 نفر برتر نمایش داده می‌شوند_"

    kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


async def handle_leaderboard_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.get_leaderboard(10)
    text = "🏆 *لیدربورد دارک پوینت*\n\n"
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, row in enumerate(rows, 1):
        medal = medals.get(i, f"{i}.")
        name = row['first_name'] or str(row['user_id'])
        text += f"{medal} {name} - `{format_number(row['dark_points'])}` DP\n"

    kb = [[InlineKeyboardButton("🏴 ربات دارک پوینت", url=f"https://t.me/{(await context.bot.get_me()).username}")]]
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))# ============ REFERRAL ============

async def referral_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    bot_username = (await context.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref_{user.id}"
    ref_count = db.get_referral_count(user.id)

    text = (
        f"👥 *زیرمجموعه‌گیری*\n"
        f"{'━' * 25}\n\n"
        f"🔗 لینک اختصاصی شما:\n`{ref_link}`\n\n"
        f"👥 تعداد زیرمجموعه‌ها: {ref_count}\n"
        f"💰 پاداش هر زیرمجموعه: {format_number(REFERRAL_REWARD)} DP\n"
        f"💎 کل درآمد از زیرمجموعه: `{format_number(ref_count * REFERRAL_REWARD)}` DP\n\n"
        f"📋 *شرایط:*\n"
        f"• حل کپچای ریاضی ✅\n"
        f"• عضویت در همه کانال‌ها ✅\n\n"
        f"_لینک را به اشتراک بگذارید و دارک پوینت بگیرید!_"
    )

    kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


# ============ SELF ============

async def self_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    u = db.get_user(user.id)

    if u['self_active']:
        maintenance = db.self_maintenance_due(user.id)
        text = (
            f"📡 *سلف فعال است*\n\n"
            f"💵 هزینه نگهداری: ساعتی {SELF_HOURLY_COST} DP\n"
            f"💎 موجودی: `{format_number(db.get_balance(user.id))}` DP"
        )
        kb = [
            [InlineKeyboardButton("❌ غیرفعال‌سازی", callback_data="self_deactivate")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
        ]
    else:
        text = (
            f"📡 *سلف*\n\n"
            f"💵 هزینه فعال‌سازی: {format_number(SELF_ACTIVATION_COST)} DP\n"
            f"🔧 هزینه نگهداری: ساعتی {SELF_HOURLY_COST} DP\n"
            f"💎 موجودی: `{format_number(db.get_balance(user.id))}` DP"
        )
        kb = [
            [InlineKeyboardButton(f"✅ فعال‌سازی ({format_number(SELF_ACTIVATION_COST)} DP)", callback_data="self_activate")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
        ]

    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


async def self_activate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if not db.remove_dark_points(user.id, SELF_ACTIVATION_COST):
        await query.answer("❌ موجودی ناکافی!", show_alert=True)
        return

    db.activate_self(user.id)
    await query.edit_message_text(
        f"✅ *سلف فعال شد!*\n💵 هزینه: `{format_number(SELF_ACTIVATION_COST)}` DP\n"
        f"🔧 نگهداری: ساعتی {SELF_HOURLY_COST} DP",
        parse_mode=ParseMode.MARKDOWN
    )


async def self_deactivate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()
    db.deactivate_self(user.id)
    await query.edit_message_text("❌ *سلف غیرفعال شد.*", parse_mode=ParseMode.MARKDOWN)


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
            f"❤️ *چالش لایکی فعال است*\n\n"
            f"⏰ زمان باقیمانده: {days} روز و {hours} ساعت"
        )
        kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
    else:
        text = (
            f"❤️ *چالش لایکی*\n\n"
            f"💵 هزینه فعال‌سازی 7 روزه: {format_number(LIKE_CHALLENGE_COST)} DP\n"
            f"💎 موجودی: `{format_number(db.get_balance(user.id))}` DP"
        )
        kb = [
            [InlineKeyboardButton(f"✅ فعال‌سازی ({format_number(LIKE_CHALLENGE_COST)} DP)", callback_data="like_activate")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
        ]

    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


async def like_activate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if not db.remove_dark_points(user.id, LIKE_CHALLENGE_COST):
        await query.answer("❌ موجودی ناکافی!", show_alert=True)
        return

    until = time.time() + (7 * 86400)
    db.update_user(user.id, like_challenge_active=1, like_challenge_until=until)

    await query.edit_message_text(
        f"✅ *چالش لایکی فعال شد!*\n💵 هزینه: `{format_number(LIKE_CHALLENGE_COST)}` DP\n⏰ مدت: 7 روز",
        parse_mode=ParseMode.MARKDOWN
    )


# ============ BUY PANEL (VPN) ============

async def buy_panel_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    buttons = [
        [InlineKeyboardButton(f"🛒 سنایی 500GB ({format_number(DEFAULT_PANEL_PRICES['snai_500gb'])} DP)",
                              callback_data="panel_buy_snai_500gb")],
        [InlineKeyboardButton(f"🛒 سنایی 800GB ({format_number(DEFAULT_PANEL_PRICES['snai_800gb'])} DP)",
                              callback_data="panel_buy_snai_800gb")],
        [InlineKeyboardButton(f"🛒 سنایی 1TB ({format_number(DEFAULT_PANEL_PRICES['snai_1tb'])} DP)",
                              callback_data="panel_buy_snai_1tb")],
    ]

    custom = db.get_custom_panels()
    for panel in custom:
        buttons.append([InlineKeyboardButton(
            f"🛒 {panel['name']} ({format_number(panel['price'])} DP)",
            callback_data=f"panel_buy_custom_{panel['panel_id']}"
        )])

    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])

    balance = db.get_balance(query.from_user.id)
    text = (
        f"🛒 *خرید پنل VPN*\n"
        f"{'━' * 25}\n\n"
        f"💎 موجودی شما: `{format_number(balance)}` DP\n\n"
        f"_یک پلن انتخاب کنید:_"
    )

    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))


async def panel_buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        plan_key = f"custom_{panel_id}"
    else:
        plan_key = data.replace("panel_buy_", "")
        if plan_key == "snai_500gb":
            name = "سنایی 500GB"
            price = DEFAULT_PANEL_PRICES['snai_500gb']
        elif plan_key == "snai_800gb":
            name = "سنایی 800GB"
            price = DEFAULT_PANEL_PRICES['snai_800gb']
        elif plan_key == "snai_1tb":
            name = "سنایی 1TB"
            price = DEFAULT_PANEL_PRICES['snai_1tb']
        else:
            await query.answer("❌ پلن نامعتبر!", show_alert=True)
            return

    await query.answer()

    if not db.remove_dark_points(user.id, price):
        await query.answer("❌ موجودی ناکافی!", show_alert=True)
        return

    config_data = ""
    try:
        config_data = create_panel_config(plan_key, user.id)
    except Exception as e:
        logger.error(f"Panel API error: {e}")
        config_data = "خطا در ساخت - با پشتیبانی تماس بگیرید"

    order_id = db.create_panel_order(user.id, name, price, config_data)

    await query.edit_message_text(
        f"✅ *خرید پنل موفق!*\n\n"
        f"🛒 پلن: {name}\n"
        f"💵 هزینه: `{format_number(price)}` DP\n"
        f"📋 شماره سفارش: {order_id}\n\n"
        f"🔐 *کانفیگ شما:*\n`{config_data}`\n\n"
        f"💎 موجودی جدید: `{format_number(db.get_balance(user.id))}` DP",
        parse_mode=ParseMode.MARKDOWN
    )

    bot_username = (await context.bot.get_me()).username
    log_kb = [[InlineKeyboardButton("🤖 ورود به ربات", url=f"https://t.me/{bot_username}")]]
    await send_log(context,
        f"🛒 *خرید پنل جدید*\n\n"
        f"👤 `{user.id}`\n"
        f"📦 {name}\n"
        f"💵 `{format_number(price)}` DP",
        reply_markup=InlineKeyboardMarkup(log_kb)
    )


def create_panel_config(plan_key, user_id):
    try:
        if 'snai_500gb' in plan_key:
            data_gb = 500
        elif 'snai_800gb' in plan_key:
            data_gb = 800
        elif 'snai_1tb' in plan_key or '1tb' in plan_key.lower():
            data_gb = 1024
        else:
            data_gb = 100

        email = f"dark_{user_id}_{int(time.time())}"
        data_bytes = data_gb * 1024 * 1024 * 1024
        expire_days = 30
        expire_time = int((time.time() + expire_days * 86400) * 1000)

        api_url = f"{PANEL_URL}/panel/api/inbounds/addClient"
        headers = {"Content-Type": "application/json"}

        client_data = {
            "id": PANEL_INBOUND_ID,
            "settings": json.dumps({
                "clients": [{
                    "id": str(user_id) + str(int(time.time())),
                    "alterId": 0,
                    "email": email,
                    "limitIp": 2,
                    "totalGB": data_bytes,
                    "expiryTime": expire_time,
                    "enable": True,
                }]
            })
        }

        login_url = f"{PANEL_URL}/panel/api/login"
        session = requests.Session()
        session.post(login_url, data={"username": "admin", "password": "admin"}, timeout=10)

        resp = session.post(api_url, json=client_data, headers=headers, timeout=10)
        if resp.status_code == 200:
            return f"کانفیگ {email} ساخته شد - {data_gb}GB"
        else:
            return f"Config: {email} | {data_gb}GB | Status: pending"

    except Exception as e:
        logger.error(f"Panel config error: {e}")
        return f"dark_{user_id}_{int(time.time())} | pending setup"# ============ ADMIN PANEL ============

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return

    total_users = db.get_all_users_count()

    kb = [
        [InlineKeyboardButton("💰 افزودن DP به کاربر", callback_data="admin_add_dp")],
        [InlineKeyboardButton("📦 ساخت پلن پنل", callback_data="admin_create_panel")],
        [InlineKeyboardButton("💵 تغییر قیمت گیفت", callback_data="admin_set_gift_price")],
        [InlineKeyboardButton("⭐ تغییر قیمت استارز", callback_data="admin_set_stars_price")],
        [
            InlineKeyboardButton("🎁 گیفت: روشن/خاموش", callback_data="admin_toggle_gift"),
            InlineKeyboardButton("⭐ استارز: روشن/خاموش", callback_data="admin_toggle_stars"),
        ],
        [InlineKeyboardButton("💰 خرید DP: روشن/خاموش", callback_data="admin_toggle_buydp")],
        [InlineKeyboardButton("📝 ساخت چک شخصی", callback_data="admin_create_check")],
        [InlineKeyboardButton("🎁 افزودن پلن گیفت", callback_data="admin_add_gift_plan")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
    ]

    gift_status = "✅" if db.get_setting('gift_section_active', '1') == '1' else "❌"
    stars_status = "✅" if db.get_setting('stars_section_active', '1') == '1' else "❌"
    buydp_status = "✅" if db.get_setting('buy_dp_active', '1') == '1' else "❌"

    text = (
        f"🛡 *پنل ادمین*\n"
        f"{'━' * 25}\n\n"
        f"👥 تعداد کاربران: {total_users}\n"
        f"🎁 گیفت رایگان: {gift_status}\n"
        f"⭐ برداشت استارز: {stars_status}\n"
        f"💰 خرید DP: {buydp_status}\n"
    )

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


async def admin_add_dp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id not in ADMIN_IDS:
        await query.answer("❌", show_alert=True)
        return
    await query.answer()
    context.user_data['admin_action'] = 'add_dp'
    await query.edit_message_text("👤 شماره کاربری کاربر را بفرستید:", parse_mode=ParseMode.MARKDOWN)


async def admin_add_dp_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        return

    action = context.user_data.get('admin_action')

    if action == 'add_dp':
        if 'admin_target_user' not in context.user_data:
            try:
                target_id = int(update.message.text.strip())
                context.user_data['admin_target_user'] = target_id
                await update.message.reply_text(f"💰 چقدر DP اضافه بشه به `{target_id}`؟", parse_mode=ParseMode.MARKDOWN)
                return
            except:
                await update.message.reply_text("❌ شماره نامعتبر!")
                context.user_data.pop('admin_action', None)
                return
        else:
            try:
                amount = int(update.message.text.strip())
                target_id = context.user_data['admin_target_user']

                if not db.get_user(target_id):
                    db.create_user(target_id)

                db.add_dark_points(target_id, amount)
                new_balance = db.get_balance(target_id)

                await update.message.reply_text(
                    f"✅ *DP اضافه شد!*\n\n"
                    f"👤 کاربر: `{target_id}`\n"
                    f"💰 مقدار: +`{format_number(amount)}` DP\n"
                    f"💎 موجودی جدید: `{format_number(new_balance)}` DP",
                    parse_mode=ParseMode.MARKDOWN
                )

                try:
                    await context.bot.send_message(
                        target_id,
                        f"💰 *دارک پوینت دریافت کردید!*\n\n"
                        f"➕ `{format_number(amount)}` DP توسط ادمین اضافه شد\n"
                        f"💎 موجودی جدید: `{format_number(new_balance)}` DP",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except:
                    pass

                context.user_data.pop('admin_action', None)
                context.user_data.pop('admin_target_user', None)
                return
            except:
                await update.message.reply_text("❌ مقدار نامعتبر!")
                context.user_data.pop('admin_action', None)
                context.user_data.pop('admin_target_user', None)
                return

    elif action == 'create_panel':
        step = context.user_data.get('panel_step', 'name')
        if step == 'name':
            context.user_data['panel_name'] = update.message.text.strip()
            context.user_data['panel_step'] = 'desc'
            await update.message.reply_text("📝 توضیحات پلن:")
        elif step == 'desc':
            context.user_data['panel_desc'] = update.message.text.strip()
            context.user_data['panel_step'] = 'price'
            await update.message.reply_text("💰 قیمت (دارک پوینت):")
        elif step == 'price':
            try:
                price = int(update.message.text.strip())
                context.user_data['panel_price'] = price
                context.user_data['panel_step'] = 'data'
                await update.message.reply_text("📊 حجم دیتا (مثلاً 500GB):")
            except:
                await update.message.reply_text("❌ عدد بفرستید!")
        elif step == 'data':
            data_limit = update.message.text.strip()
            panel_id = db.add_custom_panel(
                context.user_data['panel_name'],
                context.user_data['panel_desc'],
                context.user_data['panel_price'],
                data_limit
            )
            await update.message.reply_text(
                f"✅ *پلن ساخته شد!*\n\n"
                f"📦 نام: {context.user_data['panel_name']}\n"
                f"💰 قیمت: {format_number(context.user_data['panel_price'])} DP\n"
                f"📊 حجم: {data_limit}",
                parse_mode=ParseMode.MARKDOWN
            )
            context.user_data.pop('admin_action', None)
            context.user_data.pop('panel_step', None)
            context.user_data.pop('panel_name', None)
            context.user_data.pop('panel_desc', None)
            context.user_data.pop('panel_price', None)

    elif action == 'set_gift_price':
        try:
            price = int(update.message.text.strip())
            db.set_setting('gift_teddy_price', str(price))
            await update.message.reply_text(
                f"✅ قیمت گیفت تدی تغییر کرد: `{format_number(price)}` DP",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            await update.message.reply_text("❌ عدد نامعتبر!")
        context.user_data.pop('admin_action', None)

    elif action == 'set_stars_price':
        try:
            price = int(update.message.text.strip())
            db.set_setting('stars_price', str(price))
            await update.message.reply_text(
                f"✅ قیمت {STARS_AMOUNT} استارز تغییر کرد: `{format_number(price)}` DP",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            await update.message.reply_text("❌ عدد نامعتبر!")
        context.user_data.pop('admin_action', None)

    elif action == 'create_check':
        try:
            amount = int(update.message.text.strip())
            code = db.create_check(amount)
            bot_username = (await context.bot.get_me()).username
            link = f"https://t.me/{bot_username}?start=check_{code}"
            await update.message.reply_text(
                f"✅ *چک شخصی ساخته شد!*\n\n"
                f"💰 مبلغ: `{format_number(amount)}` DP\n"
                f"🔗 لینک:\n`{link}`\n\n"
                f"⚠️ فقط یک نفر می‌تواند استفاده کند",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            await update.message.reply_text("❌ عدد نامعتبر!")
        context.user_data.pop('admin_action', None)

    elif action == 'add_gift_plan':
        step = context.user_data.get('gift_plan_step', 'name')
        if step == 'name':
            context.user_data['gift_plan_name'] = update.message.text.strip()
            context.user_data['gift_plan_step'] = 'price'
            await update.message.reply_text("💰 قیمت پلن (دارک پوینت):")
        elif step == 'price':
            try:
                price = int(update.message.text.strip())
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
                    f"✅ *پلن گیفت اضافه شد!*\n\n"
                    f"🎁 نام: {name}\n"
                    f"💰 قیمت: {format_number(price)} DP",
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                await update.message.reply_text("❌ عدد نامعتبر!")
            context.user_data.pop('admin_action', None)
            context.user_data.pop('gift_plan_step', None)
            context.user_data.pop('gift_plan_name', None)


async def admin_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    if user.id not in ADMIN_IDS:
        await query.answer("❌", show_alert=True)
        return

    data = query.data

    if data == "admin_add_dp":
        await admin_add_dp(update, context)

    elif data == "admin_create_panel":
        await query.answer()
        context.user_data['admin_action'] = 'create_panel'
        context.user_data['panel_step'] = 'name'
        await query.edit_message_text("📦 *ساخت پلن پنل*\n\nنام پلن:", parse_mode=ParseMode.MARKDOWN)

    elif data == "admin_set_gift_price":
        await query.answer()
        context.user_data['admin_action'] = 'set_gift_price'
        await query.edit_message_text("💵 قیمت جدید گیفت تدی (DP):", parse_mode=ParseMode.MARKDOWN)

    elif data == "admin_set_stars_price":
        await query.answer()
        context.user_data['admin_action'] = 'set_stars_price'
        await query.edit_message_text(f"⭐ قیمت جدید {STARS_AMOUNT} استارز (DP):", parse_mode=ParseMode.MARKDOWN)

    elif data == "admin_toggle_gift":
        current = db.get_setting('gift_section_active', '1')
        new_val = '0' if current == '1' else '1'
        db.set_setting('gift_section_active', new_val)
        status = "✅ روشن" if new_val == '1' else "❌ خاموش"
        await query.answer(f"گیفت رایگان: {status}", show_alert=True)

    elif data == "admin_toggle_stars":
        current = db.get_setting('stars_section_active', '1')
        new_val = '0' if current == '1' else '1'
        db.set_setting('stars_section_active', new_val)
        status = "✅ روشن" if new_val == '1' else "❌ خاموش"
        await query.answer(f"برداشت استارز: {status}", show_alert=True)

    elif data == "admin_toggle_buydp":
        current = db.get_setting('buy_dp_active', '1')
        new_val = '0' if current == '1' else '1'
        db.set_setting('buy_dp_active', new_val)
        status = "✅ روشن" if new_val == '1' else "❌ خاموش"
        await query.answer(f"خرید DP: {status}", show_alert=True)

    elif data == "admin_create_check":
        await query.answer()
        context.user_data['admin_action'] = 'create_check'
        await query.edit_message_text("📝 *ساخت چک شخصی*\n\nمبلغ چک (DP):", parse_mode=ParseMode.MARKDOWN)

    elif data == "admin_add_gift_plan":
        await query.answer()
        context.user_data['admin_action'] = 'add_gift_plan'
        context.user_data['gift_plan_step'] = 'name'
        await query.edit_message_text("🎁 *افزودن پلن گیفت*\n\nنام پلن:", parse_mode=ParseMode.MARKDOWN)# ============ PRIVATE MESSAGE HANDLER ============

async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip() if update.message.text else ""

    if not text:
        return

    if user.id in ADMIN_IDS and 'admin_action' in context.user_data:
        await admin_add_dp_handler(update, context)
        return

    if context.user_data.get('awaiting_bank_card'):
        if len(text) != 13 or not text.isdigit():
            await update.message.reply_text("❌ شماره کارت باید 13 رقم و فقط اعداد انگلیسی باشد!")
            return

        if db.card_exists(text):
            await update.message.reply_text("❌ این شماره کارت قبلاً ثبت شده! یک شماره دیگر بفرستید.")
            return

        if not db.remove_dark_points(user.id, BANK_OPEN_COST):
            await update.message.reply_text("❌ موجودی ناکافی!")
            context.user_data.pop('awaiting_bank_card', None)
            return

        db.open_bank_account(user.id, text)
        context.user_data.pop('awaiting_bank_card', None)

        await update.message.reply_text(
            f"✅ *حساب بانک دارکی افتتاح شد!*\n\n"
            f"💳 شماره کارت: `{text}`\n"
            f"💵 هزینه: `{format_number(BANK_OPEN_COST)}` DP",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if context.user_data.get('awaiting_bank_deposit'):
        try:
            amount = int(text)
            if amount <= 0:
                await update.message.reply_text("❌ مبلغ نامعتبر!")
                return

            if db.bank_deposit(user.id, amount):
                context.user_data.pop('awaiting_bank_deposit', None)
                await update.message.reply_text(
                    f"✅ *واریز به بانک دارکی*\n\n"
                    f"💰 مبلغ: `{format_number(amount)}` DP\n"
                    f"📈 سود 10% بعد از 24 ساعت\n"
                    f"💎 موجودی کیف پول: `{format_number(db.get_balance(user.id))}` DP",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text("❌ موجودی ناکافی!")
        except:
            await update.message.reply_text("❌ فقط عدد بفرستید!")
        return

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
            f"✅ *سفارش استارز ثبت شد!*\n\n"
            f"⭐ تعداد: {STARS_AMOUNT} استارز\n"
            f"👤 مقصد: `{target}`\n"
            f"💵 هزینه: `{format_number(stars_price)}` DP\n\n"
            f"⏳ _بزودی واریز می‌شود_",
            parse_mode=ParseMode.MARKDOWN
        )

        bot_username = (await context.bot.get_me()).username
        log_kb = [[InlineKeyboardButton("🤖 ورود به ربات", url=f"https://t.me/{bot_username}")]]
        await send_log(context,
            f"⭐ *سفارش استارز - اکانت دیگه*\n\n"
            f"👤 سفارش‌دهنده: `{user.id}`\n"
            f"📍 مقصد: `{target}`\n"
            f"⭐ {STARS_AMOUNT} استارز",
            reply_markup=InlineKeyboardMarkup(log_kb)
        )

        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    admin_id,
                    f"⭐ *سفارش استارز*\n👤 `{user.id}`\n📍 مقصد: `{target}`\n⭐ {STARS_AMOUNT}",
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                pass
        return


# ============ MAIN CALLBACK ROUTER ============

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data == "main_menu":
        await show_main_menu(update, context, query=query)
    elif data == "dark_point_menu":
        await dark_point_menu(update, context)
    elif data.startswith("dp_info_"):
        await dp_info_page(update, context)
    elif data == "referral_menu":
        await referral_menu(update, context)
    elif data == "get_ref_link":
        await referral_menu(update, context)
    elif data == "stars_withdraw":
        await stars_withdraw_menu(update, context)
    elif data == "stars_do_withdraw":
        await stars_do_withdraw(update, context)
    elif data == "stars_self":
        await stars_self_callback(update, context)
    elif data == "stars_other":
        await stars_other_callback(update, context)
    elif data == "free_gift":
        await free_gift_menu(update, context)
    elif data == "order_gift_teddy":
        await order_gift_teddy(update, context)
    elif data.startswith("order_gift_custom_"):
        await order_gift_custom(update, context)
    elif data == "buy_dp":
        await buy_dp_menu(update, context)
    elif data == "leaderboard":
        await leaderboard_menu(update, context)
    elif data == "self_menu":
        await self_menu(update, context)
    elif data == "self_activate":
        await self_activate_callback(update, context)
    elif data == "self_deactivate":
        await self_deactivate_callback(update, context)
    elif data == "like_challenge":
        await like_challenge_menu(update, context)
    elif data == "like_activate":
        await like_activate_callback(update, context)
    elif data == "buy_panel":
        await buy_panel_menu(update, context)
    elif data.startswith("panel_buy_"):
        await panel_buy_callback(update, context)
    elif data.startswith("join_game_"):
        await join_game_callback(update, context)
    elif data.startswith("cancel_game_"):
        await cancel_game_callback(update, context)
    elif data == "bank_open":
        await bank_open_callback(update, context)
    elif data == "bank_auto_card":
        await bank_auto_card_callback(update, context)
    elif data == "bank_custom_card":
        await bank_custom_card_callback(update, context)
    elif data == "bank_deposit":
        await bank_deposit_callback(update, context)
    elif data == "bank_withdraw":
        await bank_withdraw_callback(update, context)
    elif data == "bank_wait":
        await bank_wait_callback(update, context)
    elif data == "factory_open":
        await factory_open_callback(update, context)
    elif data == "factory_upgrade":
        await factory_upgrade_callback(update, context)
    elif data == "factory_collect":
        await factory_collect_callback(update, context)
    elif data == "check_join_ref":
        await check_join_ref_callback(update, context)
    elif data.startswith("admin_"):
        await admin_callbacks(update, context)


# ============ PERIODIC TASKS ============

async def periodic_maintenance(context: ContextTypes.DEFAULT_TYPE):
    conn = db.get_conn()
    c = conn.cursor()

    c.execute("SELECT user_id FROM users WHERE factory_active = 1")
    factory_users = c.fetchall()
    for fu in factory_users:
        db.factory_maintenance_due(fu['user_id'])

    c.execute("SELECT user_id FROM users WHERE self_active = 1")
    self_users = c.fetchall()
    for su in self_users:
        db.self_maintenance_due(su['user_id'])

    conn.close()


# ============ MAIN ============

def main():
    """Start the bot with Render Keep-Alive System"""
    
    # 1. روشن کردن وب سرور برای Render (بسیار مهم)
    start_health_check_server()

    # 2. ساخت اپلیکیشن
    application = Application.builder().token(BOT_TOKEN).build()

    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))

    # Callback query handler
    application.add_handler(CallbackQueryHandler(callback_router))

    # Group message handler
    application.add_handler(MessageHandler(
        filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
        handle_group_message
    ))

    # Private message handler
    application.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
        handle_private_message
    ))

    # New chat members
    application.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS,
        on_new_chat_members
    ))

    # 3. تسک‌های دوره‌ای
    application.job_queue.run_repeating(periodic_maintenance, interval=300, first=10)
    
    # 4. سیستم Keep-Alive - هر 8 دقیقه یک بار خودپینگ
    application.job_queue.run_repeating(send_self_ping, interval=480, first=60)

    print("🏴 Dark Point Bot is running with Keep-Alive system on Render...")
    application.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
