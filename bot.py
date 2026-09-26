# bot.py - Dark Point Bot (Render Ready)

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
    ReplyKeyboardMarkup, ChatMember
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

CAPTCHA_VERIFY = 100

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
    if user.username:
        return f"@{user.username}"
    return f"[{user.first_name}](tg://user?id={user.id})"

async def check_force_join(user_id, context):
    channels = db.get_force_channels()
    if not channels:
        return True
    for ch in channels:
        try:
            member = await context.bot.get_chat_member(ch['channel_username'], user_id)
            if member.status in ['left', 'kicked']:
                return False
        except:
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

def is_admin(user_id):
    return user_id in ADMIN_IDS

# ============ KEEP-ALIVE ============

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        html = f"""
        <html><head><title>Dark Point Bot</title></head>
        <body style="background:#000;color:#0f0;text-align:center;font-family:Arial;padding:50px;">
        <h1>🏴 Dark Point Bot</h1><h2>✅ Alive!</h2>
        <p>{time.strftime('%Y-%m-%d %H:%M:%S')}</p>
        </body></html>"""# ============ START & MENU ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    if db.is_banned(user.id):
        await update.message.reply_text("❌ شما از ربات مسدود شده‌اید.")
        return

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
                f"🔐 *تایید هویت* 🔐\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"لطفاً برای احراز هویت جواب این سوال را ارسال کنید:\n\n"
                f"❓ `{captcha_q}` = ?\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💡 _فقط عدد صحیح را بفرستید_",
                parse_mode=ParseMode.MARKDOWN
            )
            return CAPTCHA_VERIFY

    db.update_last_active(user.id)

    if args and args[0].startswith("check_"):
        code = args[0].replace("check_", "")
        amount = db.claim_check(code, user.id)
        if amount:
            db.add_dark_points(user.id, amount)
            try:
                await update.message.reply_sticker(STICKERS.get('money', ''))
            except:
                pass
            await update.message.reply_text(
                f"🎁 *چک شخصی فعال شد!*\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"💰 مبلغ دریافتی: `{format_number(amount)}` DP\n"
                f"✅ به موجودی شما اضافه شد\n"
                f"━━━━━━━━━━━━━━━━━━",
                parse_mode=ParseMode.MARKDOWN
            )
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        admin_id,
                        f"📋 چک فعال شد\n👤 `{user.id}`\n💰 `{format_number(amount)}` DP",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except:
                    pass
            return
        else:
            await update.message.reply_text("❌ این چک قبلاً استفاده شده یا نامعتبر است.")
            return

    # Check force join
    joined = await check_force_join(user.id, context)
    if not joined:
        channels = db.get_force_channels()
        channels_text = "\n".join([f"🔗 {ch['channel_username']}" for ch in channels])
        kb = [[InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_join_main")]]
        await update.message.reply_text(
            f"📢 *عضویت اجباری*\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"برای استفاده از ربات، عضو کانال‌های زیر شوید:\n\n"
            f"{channels_text}\n\n"
            f"━━━━━━━━━━━━━━━━━━",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(kb)
        )
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
            f"❌ *جواب اشتباه!*\n\n❓ سوال جدید: `{captcha_q}` = ?",
            parse_mode=ParseMode.MARKDOWN
        )
        return CAPTCHA_VERIFY

    joined = await check_force_join(user.id, context)
    if not joined:
        channels = db.get_force_channels()
        channels_text = "\n".join([f"🔗 {ch['channel_username']}" for ch in channels])
        kb = [[InlineKeyboardButton("✅ عضو شدم", callback_data="check_join_ref")]]
        await update.message.reply_text(
            f"📢 *ابتدا در کانال‌ها عضو شوید:*\n\n{channels_text}",
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
                f"🎉 *زیرمجموعه جدید!*\n\n💰 +{format_number(REFERRAL_REWARD)} DP دریافت کردید!",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
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
        await query.answer("❌ هنوز عضو نشدی!", show_alert=True)
        return
    await show_main_menu(update, context, query=query)


async def check_join_ref_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                f"🎉 *زیرمجموعه جدید!*\n💰 +{format_number(REFERRAL_REWARD)} DP!",
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

    db.update_last_active(user.id)
    balance = db_user['dark_points']
    level = db_user['level']
    title = get_level_title(level)

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
        f"🏴 *به دنیای دارک پوینت خوش آمدی!* 🏴\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 نام: *{user.first_name}*\n"
        f"🆔 شماره کاربری: `{user.id}`\n"
        f"💎 موجودی: `{format_number(balance)}` DP\n"
        f"📊 سطح: {level} | {title}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⭐ _هر 1,000,000 DP = 50 استارز رایگان!_\n"
        f"🎁 _با زیرمجموعه‌گیری DP رایگان بگیر!_"
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
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))# ============ DARK POINT MENU ============

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
        f"🏴 *پنل دارک پوینت* 🏴\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💎 موجودی: `{format_number(balance)}` DP\n"
        f"📊 سطح: {level} | {title}\n"
    )
    if next_req:
        text += f"📈 تا سطح بعد: `{format_number(needed)}` DP\n"
    else:
        text += f"🏆 حداکثر سطح!\n"

    text += (
        f"\n👥 زیرمجموعه: {user['referral_count'] if user else 0}\n"
        f"📊 کل دریافتی: `{format_number(user['total_earned'] if user else 0)}` DP\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💡 _برای اطلاعات کامل روی توضیحات بزنید_"
    )

    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))


INFO_PAGES = {
    1: (
        "📖 *دارک پوینت - صفحه 1/8* 📖\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🏴 *دارک پوینت چیست؟*\n\n"
        "واحد پولی اختصاصی این ربات که با آن می‌توانید:\n\n"
        "⭐ استارز تلگرام برداشت کنید\n"
        "🛒 پنل VPN خریداری کنید\n"
        "🎁 گیفت تدی رایگان بگیرید\n"
        "🎮 در بازی‌ها شرکت کنید\n"
        "💥 بازی انفجار انجام دهید\n"
        "🏭 کارخونه دارکی بسازید\n"
        "🏦 در بانک سرمایه‌گذاری کنید\n\n"
        "⭐ *هر 1,000,000 DP = 50 استارز*"
    ),
    2: (
        "📖 *دارک پوینت - صفحه 2/8* 📖\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "💰 *نحوه کسب دارک پوینت:*\n\n"
        "1️⃣ *کلمه دارک در گروه:*\n"
        "در گروه بنویسید: `دارک` یا `دارک کانفیگ`\n"
        "سطح 1: بین 100 تا 250 DP\n"
        "هر سطح بالاتر: +40 DP اضافه\n\n"
        "2️⃣ *زیرمجموعه‌گیری:*\n"
        "هر زیرمجموعه = 30,000 DP\n\n"
        "3️⃣ *کارخونه دارکی:*\n"
        "خودکار DP ماین می‌کند\n\n"
        "4️⃣ *بانک دارکی:*\n"
        "سود 10% در 24 ساعت"
    ),
    3: (
        "📖 *دارک پوینت - صفحه 3/8* 📖\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "📊 *سیستم 20 سطحی:*\n\n"
        "سطح 1: 0 DP 🌑\n"
        "سطح 5: 150K DP 🌕\n"
        "سطح 10: 1M DP 🥈\n"
        "سطح 15: 3M DP 🔮\n"
        "سطح 20: 20M DP 🏴\n\n"
        "🎁 *هر سطح جایزه ارتقا دارد*"
    ),
    4: (
        "📖 *دارک پوینت - صفحه 4/8* 📖\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🏭 *کارخونه دارکی:*\n\n"
        "💵 افتتاح: 100,000 DP\n"
        "🔧 نگهداری: ساعتی 80 DP\n\n"
        "سطح 1: دقیقه‌ای 10 DP\n"
        "سطح 2: دقیقه‌ای 25 DP\n"
        "سطح 3: دقیقه‌ای 40 DP\n"
        "سطح 4: دقیقه‌ای 50 DP\n"
        "سطح 5: دقیقه‌ای 100 DP\n\n"
        "دستور در گروه: `کارخونه دارکی`"
    ),
    5: (
        "📖 *دارک پوینت - صفحه 5/8* 📖\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🏦 *بانک دارکی:*\n"
        "💵 افتتاح: 20,000 DP\n"
        "📈 سود: 10% در 24 ساعت\n"
        "دستور: `بانک دارکی`\n\n"
        "🎮 *بازی 2 نفره:*\n"
        "دستور: `بازی 1000`\n"
        "جایزه: 2 برابر مبلغ"
    ),
    6: (
        "📖 *دارک پوینت - صفحه 6/8* 📖\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "💸 *انتقال دارک پوینت:*\n\n"
        "روش 1: ریپلای + `انتقال 1000`\n"
        "روش 2: `انتقال 1000 به 123456`\n\n"
        "⚠️ کارمزد: 10%\n\n"
        "❤️ *چالش لایکی:*\n"
        "7 روزه: 30,000 DP"
    ),
    7: (
        "📖 *دارک پوینت - صفحه 7/8* 📖\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "⭐ *برداشت استارز:*\n"
        "هر 1M DP = 50 استارز\n"
        "کاملاً رایگان با زیرمجموعه!\n\n"
        "🎁 *گیفت رایگان:*\n"
        "گیفت تدی تلگرام\n\n"
        "📝 *دستورات گروه:*\n"
        "• `دارک`\n"
        "• `موجودی`\n"
        "• `پروفایل دارکی`\n"
        "• `بازی 1000`\n"
        "• `انتقال 1000`\n"
        "• `بانک دارکی`\n"
        "• `کارخونه دارکی`"
    ),
    8: (
        "📖 *دارک پوینت - صفحه 8/8* 📖\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "💥 *بازی انفجار:*\n\n"
        "یکی از پرهیجان‌ترین بازی‌ها!\n\n"
        "🎯 نحوه بازی:\n"
        "1. مبلغ شرط را وارد کنید\n"
        "2. ضریب رشد می‌کند\n"
        "3. قبل از انفجار Cash Out کنید\n"
        "4. اگر منفجر شد، بازی را باختید\n\n"
        "💰 برد = مبلغ × ضریب\n"
        "⚠️ حداقل: 500 DP\n"
        "⚠️ حداکثر: 500K DP\n\n"
        "🎲 _ضریب انفجار کاملاً تصادفی_"
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
                    "🏴 *ربات دارک پوینت فعال شد!* 🏴\n"
                    "━━━━━━━━━━━━━━━━━━\n\n"
                    "📝 *دستورات:*\n"
                    "• `دارک` - دریافت DP\n"
                    "• `دارک کانفیگ` - دریافت DP\n"
                    "• `موجودی` - مشاهده موجودی\n"
                    "• `پروفایل دارکی` - پروفایل\n"
                    "• `بازی [مبلغ]` - بازی\n"
                    "• `انفجار [مبلغ]` - بازی انفجار\n"
                    "• `انتقال [مبلغ]` - انتقال\n"
                    "• `بانک دارکی` - بانک\n"
                    "• `کارخونه دارکی` - کارخونه\n"
                    "• `لیدربورد` - جدول برترین‌ها",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Error: {e}")


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
            f"⏳ *صبر کنید!* ⏳\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"⏰ {mins} دقیقه و {secs} ثانیه تا دریافت بعدی\n\n"
            f"💡 _صبر کلید موفقیت است!_ 🌟",
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
        f"✨🏴 *دارک پوینت دریافت شد!* 🏴✨\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 کاربر: *{user.first_name}*\n"
        f"💎 دریافتی: +`{format_number(earned)}` DP 🎉\n"
        f"📊 سطح: {level} | {get_level_title(level)}\n"
        f"💰 موجودی جدید: `{format_number(db.get_balance(user.id))}` DP\n\n"
        f"⏰ دریافت بعدی: {cd_mins}m {cd_secs}s\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🌟 _برای بیشتر گرفتن سطح رو ببر بالا!_"
    )

    if new_level:
        text += (
            f"\n\n🎊 *ارتقا به سطح {new_level}!* 🎊\n"
            f"🏅 عنوان جدید: {get_level_title(new_level)}\n"
            f"🎁 جایزه: +`{format_number(reward)}` DP"
        )
        try:
            await update.message.reply_sticker(STICKERS.get('levelup', ''))
        except:
            pass

    bot_username = (await context.bot.get_me()).username
    kb = [[InlineKeyboardButton("🏴 ورود به ربات دارک پوینت", url=f"https://t.me/{bot_username}")]]
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


async def handle_balance_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    balance = db.get_balance(user.id)
    level = db.get_level(user.id)

    bot_username = (await context.bot.get_me()).username
    kb = [[InlineKeyboardButton("🏴 ربات دارک پوینت", url=f"https://t.me/{bot_username}")]]
    await update.message.reply_text(
        f"💎✨ *موجودی دارک پوینت* ✨💎\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 {user.first_name}\n"
        f"🆔 `{user.id}`\n\n"
        f"💰 موجودی: `{format_number(balance)}` DP\n"
        f"📊 سطح: {level} | {get_level_title(level)}\n"
        f"━━━━━━━━━━━━━━━━━━",
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
        factory_info = f"🏭 کارخونه: سطح {f_level} ({mine_rate} DP/min)\n"

    bank_info = ""
    if u['bank_account']:
        bank_info = f"🏦 موجودی بانک: `{format_number(u['bank_balance'])}` DP\n"

    stars_price = int(db.get_setting('stars_price', '1000000'))
    stars_can = balance // stars_price
    if stars_can > 0:
        stars_text = f"⭐ قابل برداشت: {stars_can * 50} استارز\n"
    else:
        stars_text = f"⭐ تا استارز: `{format_number(stars_price - balance)}` DP\n"

    crash_played = u['crash_games_played']
    crash_won = u['crash_games_won']
    win_rate = int((crash_won / crash_played * 100) if crash_played > 0 else 0)

    try:
        await update.message.reply_sticker(STICKERS.get('profile', ''))
    except:
        pass

    text = (
        f"🏴✨ *پروفایل دارکی* ✨🏴\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 نام: *{user.first_name}*\n"
        f"🆔 شماره: `{user.id}`\n"
        f"📛 یوزر: @{user.username or 'ندارد'}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 موجودی: `{format_number(balance)}` DP\n"
        f"📊 سطح: {level} | {title}\n"
    )

    if next_req:
        text += f"📈 تا سطح {level+1}: `{format_number(needed)}` DP\n"
    else:
        text += f"🏆 حداکثر سطح!\n"

    text += (
        f"📊 کل دریافتی: `{format_number(total)}` DP\n"
        f"👥 زیرمجموعه: {refs}\n"
        f"{stars_text}"
        f"{factory_info}"
        f"{bank_info}"
        f"💥 انفجار: {crash_won}/{crash_played} ({win_rate}%)\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏴 _دارک پوینت | قدرت تاریکی_"
    )

    bot_username = (await context.bot.get_me()).username
    kb = [[InlineKeyboardButton("🏴 ربات دارک پوینت", url=f"https://t.me/{bot_username}")]]
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))# ============ GAME (2 PLAYERS) ============

async def handle_create_game(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: int):
    user = update.effective_user
    chat = update.effective_chat

    if amount < MIN_GAME_AMOUNT:
        await update.message.reply_text(f"❌ حداقل مبلغ بازی: {format_number(MIN_GAME_AMOUNT)} DP")
        return

    balance = db.get_balance(user.id)
    if balance < amount:
        await update.message.reply_text(
            f"❌ *موجودی ناکافی!*\n💰 موجودی: `{format_number(balance)}` DP\n💵 نیاز: `{format_number(amount)}` DP",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    db.remove_dark_points(user.id, amount)

    try:
        await update.message.reply_sticker(STICKERS.get('game', ''))
    except:
        pass

    msg = await update.message.reply_text(
        f"🎮✨ *بازی جدید ایجاد شد!* ✨🎮\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 سازنده: {get_user_display(user)}\n"
        f"💰 مبلغ ورود: `{format_number(amount)}` DP\n"
        f"🏆 جایزه برنده: `{format_number(amount * 2)}` DP\n\n"
        f"⏳ منتظر حریف...\n"
        f"━━━━━━━━━━━━━━━━━━",
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

    await query.edit_message_text(
        f"🎮✨ *نتیجه بازی!* ✨🎮\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🏆 *برنده:* {winner_display}\n"
        f"💰 جایزه: +`{format_number(prize)}` DP\n"
        f"💎 موجودی جدید: `{format_number(db.get_balance(winner_id))}` DP\n\n"
        f"💔 *بازنده:* {loser_display}\n"
        f"💎 موجودی جدید: `{format_number(db.get_balance(loser_id))}` DP\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎲 _برنده کاملاً تصادفی_",
        parse_mode=ParseMode.MARKDOWN
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
        f"❌ *بازی لغو شد*\n💰 `{format_number(game['amount'])}` DP بازگردانده شد",
        parse_mode=ParseMode.MARKDOWN
    )


# ============ CRASH GAME (ANFEJAR) ============

def generate_crash_point():
    """Generate a random crash point with realistic distribution"""
    r = random.random()
    if r < 0.35:  # 35% chance early crash
        return round(random.uniform(1.01, 1.5), 2)
    elif r < 0.70:  # 35% chance normal
        return round(random.uniform(1.5, 3.0), 2)
    elif r < 0.90:  # 20% chance good
        return round(random.uniform(3.0, 6.0), 2)
    else:  # 10% chance huge
        return round(random.uniform(6.0, CRASH_MAX_MULTIPLIER), 2)


async def crash_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    active = db.get_setting('crash_active', '1')
    if active != '1':
        await query.answer("❌ این بخش موقتاً خاموش می‌باشد", show_alert=True)
        return

    balance = db.get_balance(user.id)
    u = db.get_user(user.id)

    text = (
        f"💥✨ *بازی انفجار* ✨💥\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 *چطور بازی کنیم؟*\n\n"
        f"1️⃣ در گروه بنویسید:\n"
        f"`انفجار [مبلغ]`\n\n"
        f"مثال: `انفجار 1000`\n\n"
        f"2️⃣ ضریب از 1x شروع می‌شود\n"
        f"3️⃣ قبل از انفجار Cash Out کنید\n"
        f"4️⃣ برد = مبلغ × ضریب\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 موجودی: `{format_number(balance)}` DP\n"
        f"💥 بازی‌ها: {u['crash_games_played']}\n"
        f"🏆 بردها: {u['crash_games_won']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ حداقل: {format_number(CRASH_MIN_BET)} DP\n"
        f"⚠️ حداکثر: {format_number(CRASH_MAX_BET)} DP"
    )

    kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


async def handle_crash_game_group(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: int):
    user = update.effective_user

    active = db.get_setting('crash_active', '1')
    if active != '1':
        await update.message.reply_text("❌ بازی انفجار موقتاً خاموش است.")
        return

    if amount < CRASH_MIN_BET:
        await update.message.reply_text(f"❌ حداقل مبلغ: {format_number(CRASH_MIN_BET)} DP")
        return

    if amount > CRASH_MAX_BET:
        await update.message.reply_text(f"❌ حداکثر مبلغ: {format_number(CRASH_MAX_BET)} DP")
        return

    balance = db.get_balance(user.id)
    if balance < amount:
        await update.message.reply_text(
            f"❌ موجودی ناکافی!\n💰 موجودی: `{format_number(balance)}` DP",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    db.remove_dark_points(user.id, amount)
    crash_point = generate_crash_point()

    try:
        await update.message.reply_sticker(STICKERS.get('crash', ''))
    except:
        pass

    msg = await update.message.reply_text(
        f"💥 *بازی انفجار شروع شد!* 💥\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 بازیکن: {get_user_display(user)}\n"
        f"💰 شرط: `{format_number(amount)}` DP\n\n"
        f"🚀 ضریب: `1.00x`\n\n"
        f"⚡️ آماده شوید...",
        parse_mode=ParseMode.MARKDOWN
    )

    game_id = db.create_crash_game(user.id, amount, crash_point, update.effective_chat.id, msg.message_id)

    await msg.edit_text(
        f"💥 *بازی انفجار زنده* 💥\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 بازیکن: {get_user_display(user)}\n"
        f"💰 شرط: `{format_number(amount)}` DP\n\n"
        f"🚀 ضریب: `1.00x`\n"
        f"💎 برد فعلی: `{format_number(amount)}` DP",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 برداشت (Cash Out)", callback_data=f"crash_out_{game_id}")]
        ])
    )

    # Start the crash animation
    asyncio.create_task(run_crash_game(context, game_id, user.id, amount, crash_point, msg.chat_id, msg.message_id))


async def run_crash_game(context, game_id, user_id, bet, crash_point, chat_id, message_id):
    """Animate the crash game"""
    current = 1.00
    step = 0.1
    delay = 1.5

    while current < crash_point:
        # Check if user cashed out
        g = db.get_crash_game(game_id)
        if not g or g['status'] != 'playing':
            return

        await asyncio.sleep(delay)
        current = round(current + step, 2)
        
        if current >= crash_point:
            current = crash_point

        # Increase step as multiplier grows for excitement
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

        # Get user info for display
        try:
            user_obj = await context.bot.get_chat(user_id)
            user_display = f"@{user_obj.username}" if user_obj.username else user_obj.first_name
        except:
            user_display = str(user_id)

        try:
            await context.bot.edit_message_text(
                f"💥 *بازی انفجار زنده* 💥\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"👤 بازیکن: {user_display}\n"
                f"💰 شرط: `{format_number(bet)}` DP\n\n"
                f"🚀 ضریب: `{current}x` 📈\n"
                f"💎 برد فعلی: `{format_number(potential_win)}` DP",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"💰 برداشت {current}x", callback_data=f"crash_out_{game_id}")]
                ])
            )
        except Exception as e:
            logger.error(f"Crash edit error: {e}")

        if current >= crash_point:
            break

    # Game ended (crashed)
    g = db.get_crash_game(game_id)
    if g and g['status'] == 'playing':
        db.crash_game_lost(game_id)
        db.increment_crash_stats(user_id, won=False)

        try:
            user_obj = await context.bot.get_chat(user_id)
            user_display = f"@{user_obj.username}" if user_obj.username else user_obj.first_name
        except:
            user_display = str(user_id)

        try:
            await context.bot.edit_message_text(
                f"💥💥💥 *منفجر شد!* 💥💥💥\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"👤 بازیکن: {user_display}\n"
                f"💰 شرط: `{format_number(bet)}` DP\n\n"
                f"💥 ضریب انفجار: `{crash_point}x`\n"
                f"😔 نتیجه: باختی!\n\n"
                f"💎 موجودی: `{format_number(db.get_balance(user_id))}` DP\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🎲 _دفعه بعد شانس بیشتری داری!_",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode=ParseMode.MARKDOWN
            )
        except:
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

    # Extract current multiplier from message
    msg_text = query.message.text
    match = re.search(r'ضریب: `([\d.]+)x`', msg_text)
    if not match:
        await query.answer("❌ خطا در محاسبه!", show_alert=True)
        return

    current_mult = float(match.group(1))
    win_amount = int(g['bet_amount'] * current_mult)
    profit = win_amount - g['bet_amount']

    if db.cashout_crash_game(game_id, current_mult, profit):
        db.add_dark_points(user.id, win_amount)
        db.increment_crash_stats(user.id, won=True)

        try:
            user_obj = await context.bot.get_chat(user.id)
            user_display = f"@{user_obj.username}" if user_obj.username else user_obj.first_name
        except:
            user_display = str(user.id)

        await query.answer(f"✅ برداشت شد! +{format_number(win_amount)} DP", show_alert=True)

        await query.edit_message_text(
            f"🎉🏆 *برنده شدی!* 🏆🎉\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 بازیکن: {user_display}\n"
            f"💰 شرط: `{format_number(g['bet_amount'])}` DP\n\n"
            f"💎 ضریب برداشت: `{current_mult}x`\n"
            f"🏆 برد شما: `{format_number(win_amount)}` DP\n"
            f"📈 سود خالص: +`{format_number(profit)}` DP\n\n"
            f"💰 موجودی: `{format_number(db.get_balance(user.id))}` DP\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🎯 _در زمان درست خارج شدی!_",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await query.answer("❌ خطا!", show_alert=True)# ============ TRANSFER ============

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
                await update.message.reply_text("❌ به خودتان نمی‌توانید!")
                return

            fee = int(amount * TRANSFER_FEE)
            total_cost = amount + fee
            balance = db.get_balance(user.id)

            if balance < total_cost:
                await update.message.reply_text(
                    f"❌ *موجودی ناکافی!*\n"
                    f"💰 مبلغ: `{format_number(amount)}` DP\n"
                    f"💸 کارمزد: `{format_number(fee)}` DP\n"
                    f"📊 کل: `{format_number(total_cost)}` DP\n"
                    f"💎 موجودی: `{format_number(balance)}` DP",
                    parse_mode=ParseMode.MARKDOWN
                )
                return

            if not db.remove_dark_points(user.id, total_cost):
                await update.message.reply_text("❌ خطا!")
                return

            db.add_dark_points(target_id, amount)
            db.record_transfer(user.id, target_id, amount, fee)

            target = update.message.reply_to_message.from_user
            target_display = f"@{target.username}" if target.username else f"`{target.id}`"

            await update.message.reply_text(
                f"✅✨ *انتقال موفق!* ✨✅\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"💰 مبلغ: `{format_number(amount)}` DP\n"
                f"💸 کارمزد: `{format_number(fee)}` DP\n"
                f"👤 مقصد: {target_display}\n"
                f"💎 موجودی: `{format_number(db.get_balance(user.id))}` DP",
                parse_mode=ParseMode.MARKDOWN
            )
            try:
                await context.bot.send_message(
                    target_id,
                    f"💰 *دارک پوینت دریافت کردید!*\n💰 `{format_number(amount)}` DP از {get_user_display(user)}",
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
            await update.message.reply_text("❌ به خودتان نمی‌توانید!")
            return

        target_user = db.get_user(target_id)
        if not target_user:
            await update.message.reply_text("❌ کاربر یافت نشد!")
            return

        fee = int(amount * TRANSFER_FEE)
        total_cost = amount + fee
        balance = db.get_balance(user.id)

        if balance < total_cost:
            await update.message.reply_text(
                f"❌ نیاز: `{format_number(total_cost)}` DP\n💎 دارید: `{format_number(balance)}` DP",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if not db.remove_dark_points(user.id, total_cost):
            return

        db.add_dark_points(target_id, amount)
        db.record_transfer(user.id, target_id, amount, fee)

        await update.message.reply_text(
            f"✅ *انتقال موفق!*\n💰 `{format_number(amount)}` DP → `{target_id}`\n💎 موجودی: `{format_number(db.get_balance(user.id))}` DP",
            parse_mode=ParseMode.MARKDOWN
        )
        try:
            await context.bot.send_message(
                target_id,
                f"💰 *دارک پوینت دریافت شد!*\n💰 `{format_number(amount)}` DP",
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
        kb = [[InlineKeyboardButton("🏦 افتتاح حساب (20K DP)", callback_data="bank_open")]]
        await update.message.reply_text(
            f"🏦✨ *بانک دارکی* ✨🏦\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"❌ شما حسابی ندارید\n\n"
            f"💵 افتتاح: `20,000` DP\n"
            f"📈 سود: 10% در 24 ساعت\n\n"
            f"🏦 کل بانک: `{format_number(total_bank)}` DP\n"
            f"━━━━━━━━━━━━━━━━━━",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(kb)
        )
    else:
        elapsed = time.time() - u['bank_deposit_time'] if u['bank_deposit_time'] > 0 else 0
        interest_ready = elapsed >= 86400 and u['bank_balance'] > 0
        potential = int(u['bank_balance'] * 0.10) if interest_ready else 0

        buttons = []
        if u['bank_balance'] == 0:
            buttons.append([InlineKeyboardButton("💰 واریز", callback_data="bank_deposit")])
        else:
            if interest_ready:
                buttons.append([InlineKeyboardButton("💸 برداشت (با سود)", callback_data="bank_withdraw")])
            else:
                remaining = max(0, 86400 - elapsed)
                h = int(remaining // 3600)
                m = int((remaining % 3600) // 60)
                buttons.append([InlineKeyboardButton(f"⏰ {h}h {m}m تا سود", callback_data="bank_wait")])
            buttons.append([InlineKeyboardButton("💰 واریز بیشتر", callback_data="bank_deposit")])

        text = (
            f"🏦✨ *بانک دارکی* ✨🏦\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"💳 کارت: `{u['bank_card']}`\n"
            f"💰 موجودی: `{format_number(u['bank_balance'])}` DP\n"
        )
        if potential > 0:
            text += f"📈 سود آماده: +`{format_number(potential)}` DP\n"
        text += f"\n🏦 کل بانک: `{format_number(total_bank)}` DP\n━━━━━━━━━━━━━━━━━━"

        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))


async def bank_open_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if db.get_balance(user.id) < BANK_OPEN_COST:
        await query.answer(f"❌ نیاز: {format_number(BANK_OPEN_COST)} DP", show_alert=True)
        return

    kb = [
        [InlineKeyboardButton("🎲 خودکار", callback_data="bank_auto_card")],
        [InlineKeyboardButton("✏️ دلخواه", callback_data="bank_custom_card")],
    ]
    await query.edit_message_text(
        f"🏦 *افتتاح حساب*\n\n🎲 خودکار یا ✏️ دلخواه؟",
        parse_mode=ParseMode.MARKDOWN,
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
        f"✅ *حساب افتتاح شد!*\n💳 `{card}`\n💵 هزینه: `{format_number(BANK_OPEN_COST)}` DP",
        parse_mode=ParseMode.MARKDOWN
    )


async def bank_custom_card_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_bank_card'] = True
    await query.edit_message_text(
        "✏️ *کارت دلخواه*\n\n13 رقم انگلیسی به پیوی ربات بفرست",
        parse_mode=ParseMode.MARKDOWN
    )


async def bank_deposit_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_bank_deposit'] = True
    balance = db.get_balance(query.from_user.id)
    await query.edit_message_text(
        f"💰 *واریز*\n💎 موجودی: `{format_number(balance)}` DP\n\nمبلغ را به پیوی بفرست:",
        parse_mode=ParseMode.MARKDOWN
    )


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
        f"✅ *برداشت موفق*\n💰 اصل: `{format_number(balance)}` DP\n📈 سود: +`{format_number(interest)}` DP\n💎 کل: `{format_number(total)}` DP",
        parse_mode=ParseMode.MARKDOWN
    )


async def bank_wait_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("⏰ 24 ساعت صبر کنید", show_alert=True)


# ============ FACTORY ============

async def handle_factory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = db.get_user(user.id)

    try:
        await update.message.reply_sticker(STICKERS.get('factory', ''))
    except:
        pass

    if not u['factory_active'] and u['factory_level'] == 0:
        kb = [[InlineKeyboardButton(f"🏭 افتتاح ({format_number(FACTORY_OPEN_COST)} DP)", callback_data="factory_open")]]
        await update.message.reply_text(
            f"🏭✨ *کارخونه دارکی* ✨🏭\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"❌ کارخونه ندارید\n\n"
            f"💵 افتتاح: `{format_number(FACTORY_OPEN_COST)}` DP\n"
            f"🔧 نگهداری: ساعتی 80 DP\n\n"
            f"📊 *سطوح:*\n"
            f"سطح 1: 10 DP/min\n"
            f"سطح 2: 25 DP/min\n"
            f"سطح 3: 40 DP/min\n"
            f"سطح 4: 50 DP/min\n"
            f"سطح 5: 100 DP/min\n"
            f"━━━━━━━━━━━━━━━━━━",
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
            f"⬆️ ارتقا به {f_level+1} ({format_number(upgrade_cost)} DP)",
            callback_data="factory_upgrade"
        )])
    buttons.append([InlineKeyboardButton("💰 جمع‌آوری", callback_data="factory_collect")])

    status = "✅ فعال" if u['factory_active'] else "❌ غیرفعال"
    text = (
        f"🏭✨ *کارخونه دارکی* ✨🏭\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 سطح: {f_level}\n"
        f"⚡ نرخ: {mine_rate} DP/min\n"
        f"📋 وضعیت: {status}\n"
    )
    if mined > 0:
        text += f"💰 جمع‌آوری: +`{format_number(mined)}` DP\n"
    if maintenance == -1:
        text += f"\n⚠️ کارخونه بخاطر ناکافی بودن موجودی متوقف!\n"
    text += f"\n💎 موجودی: `{format_number(db.get_balance(user.id))}` DP\n━━━━━━━━━━━━━━━━━━"

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))


async def factory_open_cb(update, context):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if db.get_balance(user.id) < FACTORY_OPEN_COST:
        await query.answer(f"❌ نیاز: {format_number(FACTORY_OPEN_COST)} DP", show_alert=True)
        return

    db.remove_dark_points(user.id, FACTORY_OPEN_COST)
    db.open_factory(user.id)
    await query.edit_message_text(
        f"✅ *کارخونه افتتاح شد!*\n📊 سطح: 1\n⚡ 10 DP/min",
        parse_mode=ParseMode.MARKDOWN
    )


async def factory_upgrade_cb(update, context):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    u = db.get_user(user.id)
    if not u or u['factory_level'] >= 5:
        await query.answer("❌ حداکثر!", show_alert=True)
        return

    upgrade_cost = FACTORY_LEVELS[u['factory_level']]['upgrade_cost']
    if db.get_balance(user.id) < upgrade_cost:
        await query.answer(f"❌ نیاز: {format_number(upgrade_cost)}", show_alert=True)
        return

    db.collect_factory(user.id)
    db.remove_dark_points(user.id, upgrade_cost)
    db.upgrade_factory(user.id)
    new_level = u['factory_level'] + 1
    new_rate = FACTORY_LEVELS[new_level]['mine_per_min']

    await query.edit_message_text(
        f"⬆️ *ارتقا یافت!*\n📊 سطح: {new_level}\n⚡ {new_rate} DP/min",
        parse_mode=ParseMode.MARKDOWN
    )


async def factory_collect_cb(update, context):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    mined = db.collect_factory(user.id)
    db.factory_maintenance_due(user.id)
    await query.answer(f"💰 {format_number(mined)} DP جمع شد!", show_alert=True)# ============ STARS ============

async def stars_withdraw_menu(update, context):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if db.get_setting('stars_section_active', '1') != '1':
        await query.answer("❌ موقتاً خاموش", show_alert=True)
        return

    stars_price = int(db.get_setting('stars_price', '1000000'))
    balance = db.get_balance(user.id)
    can_withdraw = balance >= stars_price

    try:
        await context.bot.send_sticker(query.message.chat_id, STICKERS.get('stars', ''))
    except:
        pass

    text = (
        f"⭐✨ *برداشت استارز* ✨⭐\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💎 موجودی: `{format_number(balance)}` DP\n"
        f"⭐ نرخ: `{format_number(stars_price)}` DP = {STARS_AMOUNT} استارز\n\n"
    )

    if can_withdraw:
        text += f"✅ می‌توانی {STARS_AMOUNT} استارز برداشت کنی!\n\n🎉 _رایگان با زیرمجموعه‌گیری!_"
        kb = [
            [InlineKeyboardButton(f"⭐ برداشت {STARS_AMOUNT} استارز", callback_data="stars_do")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
        ]
    else:
        needed = stars_price - balance
        text += f"❌ نیاز: `{format_number(needed)}` DP بیشتر"
        kb = [
            [InlineKeyboardButton("👥 زیرمجموعه‌گیری", callback_data="referral_menu")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
        ]

    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


async def stars_do(update, context):
    query = update.callback_query
    await query.answer()
    kb = [
        [InlineKeyboardButton("👤 همین اکانتم", callback_data="stars_self")],
        [InlineKeyboardButton("👥 اکانت دیگه", callback_data="stars_other")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="stars_withdraw")],
    ]
    await query.edit_message_text(
        f"⭐ *برداشت {STARS_AMOUNT} استارز*\n\nبرای کدام اکانت؟",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def stars_self_cb(update, context):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    stars_price = int(db.get_setting('stars_price', '1000000'))
    if not db.remove_dark_points(user.id, stars_price):
        await query.answer("❌ ناکافی!", show_alert=True)
        return

    db.create_stars_order(user.id, str(user.id), 'self', STARS_AMOUNT, stars_price)

    await query.edit_message_text(
        f"✅ *سفارش ثبت شد!*\n⭐ {STARS_AMOUNT} استارز → `{user.id}`\n⏳ بزودی واریز",
        parse_mode=ParseMode.MARKDOWN
    )

    user_display = f"@{user.username}" if user.username else f"`{user.id}`"
    bot_username = (await context.bot.get_me()).username
    log_kb = [[InlineKeyboardButton("🤖 ورود به ربات", url=f"https://t.me/{bot_username}")]]
    await send_log(context,
        f"⭐ *سفارش برداشت استارز*\n👤 {user_display}\n🆔 `{user.id}`\n⭐ {STARS_AMOUNT}\n📍 مقصد: `{user.id}`",
        reply_markup=InlineKeyboardMarkup(log_kb)
    )
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, f"⭐ سفارش استارز\n👤 `{user.id}`\n⭐ {STARS_AMOUNT}", parse_mode=ParseMode.MARKDOWN)
        except:
            pass


async def stars_other_cb(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data['awaiting_stars_target'] = True
    await query.edit_message_text(
        "👥 *اکانت دیگه*\n\nآیدی اکانت مقصد را به پیوی بفرست:",
        parse_mode=ParseMode.MARKDOWN
    )


# ============ FREE GIFT ============

async def free_gift_menu(update, context):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if db.get_setting('gift_section_active', '1') != '1':
        await query.answer("❌ موقتاً خاموش", show_alert=True)
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
        f"🎁✨ *گیفت رایگان* ✨🎁\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🧸 *گیفت تدی تلگرام*\n"
        f"💰 قیمت: `{format_number(gift_price)}` DP\n"
        f"💎 موجودی: `{format_number(balance)}` DP\n\n"
        f"🆓 _رایگان با زیرمجموعه‌گیری!_"
    )

    buttons = []
    if can_buy:
        buttons.append([InlineKeyboardButton("🧸 سفارش گیفت تدی", callback_data="order_gift_teddy")])

    for plan in plans:
        plan_num = plan['key'].split('_')[2]
        name = plan['value']
        price = int(db.get_setting(f'gift_plan_{plan_num}_price', '0'))
        if price > 0:
            buttons.append([InlineKeyboardButton(f"🎁 {name} ({format_number(price)} DP)", callback_data=f"order_gift_custom_{plan_num}")])

    buttons.append([InlineKeyboardButton("👥 زیرمجموعه‌گیری", callback_data="referral_menu")])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])

    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))


async def order_gift_teddy(update, context):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    gift_price = int(db.get_setting('gift_teddy_price', '750000'))
    if not db.remove_dark_points(user.id, gift_price):
        await query.answer("❌ ناکافی!", show_alert=True)
        return

    order_id = db.create_gift_order(user.id, 'teddy', gift_price)
    await query.edit_message_text(
        f"✅ *سفارش تدی ثبت شد!*\n🆔 {order_id}\n💵 `{format_number(gift_price)}` DP",
        parse_mode=ParseMode.MARKDOWN
    )

    bot_username = (await context.bot.get_me()).username
    log_kb = [[InlineKeyboardButton("🤖 ورود به ربات", url=f"https://t.me/{bot_username}")]]
    await send_log(context,
        f"🧸 *سفارش گیفت تدی*\n👤 `{user.id}`\n💵 `{format_number(gift_price)}`",
        reply_markup=InlineKeyboardMarkup(log_kb)
    )
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, f"🧸 گیفت تدی\n👤 `{user.id}`", parse_mode=ParseMode.MARKDOWN)
        except:
            pass


async def order_gift_custom(update, context):
    query = update.callback_query
    user = query.from_user
    plan_num = query.data.split("_")[-1]

    name = db.get_setting(f'gift_plan_{plan_num}_name', 'نامشخص')
    price = int(db.get_setting(f'gift_plan_{plan_num}_price', '0'))

    if not db.remove_dark_points(user.id, price):
        await query.answer("❌ ناکافی!", show_alert=True)
        return

    db.create_gift_order(user.id, name, price)
    await query.answer()
    await query.edit_message_text(f"✅ *سفارش ثبت شد!*\n🎁 {name}", parse_mode=ParseMode.MARKDOWN)

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, f"🎁 {name}\n👤 `{user.id}`", parse_mode=ParseMode.MARKDOWN)
        except:
            pass


# ============ BUY DP ============

async def buy_dp_menu(update, context):
    query = update.callback_query
    await query.answer()

    if db.get_setting('buy_dp_active', '1') != '1':
        await query.answer("❌ موقتاً خاموش", show_alert=True)
        return

    dp_amount = int(db.get_setting('buy_dp_amount', '500000'))
    price_toman = int(db.get_setting('buy_dp_price_toman', '50000'))

    text = (
        f"💰✨ *خرید دارک پوینت* ✨💰\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💎 هر `{format_number(dp_amount)}` DP\n"
        f"💵 قیمت: `{format_number(price_toman)}` تومان\n\n"
        f"⚠️ هر نفر فقط یکبار می‌تواند\n"
        f"👥 _بقیه‌اش با زیرمجموعه‌گیری_\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    kb = [
        [InlineKeyboardButton("📩 پشتیبانی", url=f"https://t.me/{SUPPORT_USERNAME.replace('@', '')}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
    ]
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


# ============ LEADERBOARD ============

async def leaderboard_menu(update, context):
    query = update.callback_query
    await query.answer()

    rows = db.get_leaderboard(100)
    text = "🏆✨ *لیدربورد دارک پوینت* ✨🏆\n━━━━━━━━━━━━━━━━━━\n\n"
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}

    for i, row in enumerate(rows[:25], 1):
        medal = medals.get(i, f"`{i}.`")
        name = row['first_name'] or row['username'] or str(row['user_id'])
        text += f"{medal} *{name}* - `{format_number(row['dark_points'])}` DP\n"

    if len(rows) > 25:
        text += f"\n_...و {len(rows) - 25} نفر دیگر_"

    text += "\n━━━━━━━━━━━━━━━━━━\n🏆 _100 نفر برتر_"

    kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


async def handle_leaderboard_group(update, context):
    rows = db.get_leaderboard(10)
    text = "🏆 *لیدربورد*\n━━━━━━━━━━━━━━━━━━\n\n"
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for i, row in enumerate(rows, 1):
        medal = medals.get(i, f"{i}.")
        name = row['first_name'] or str(row['user_id'])
        text += f"{medal} {name} - `{format_number(row['dark_points'])}` DP\n"

    bot_username = (await context.bot.get_me()).username
    kb = [[InlineKeyboardButton("🏴 ربات", url=f"https://t.me/{bot_username}")]]
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


# ============ REFERRAL ============

async def referral_menu(update, context):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    bot_username = (await context.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref_{user.id}"
    ref_count = db.get_referral_count(user.id)

    text = (
        f"👥✨ *زیرمجموعه‌گیری* ✨👥\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🔗 لینک شما:\n`{ref_link}`\n\n"
        f"👥 زیرمجموعه: {ref_count}\n"
        f"💰 هر زیرمجموعه: {format_number(REFERRAL_REWARD)} DP\n"
        f"💎 کل درآمد: `{format_number(ref_count * REFERRAL_REWARD)}` DP\n\n"
        f"📋 *شرایط:*\n"
        f"• حل کپچا ✅\n"
        f"• عضویت در کانال‌ها ✅\n"
        f"━━━━━━━━━━━━━━━━━━"
    )

    kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


# ============ LIKE CHALLENGE ============

async def like_challenge_menu(update, context):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    u = db.get_user(user.id)

    if u['like_challenge_active'] and u['like_challenge_until'] > time.time():
        remaining = u['like_challenge_until'] - time.time()
        days = int(remaining // 86400)
        hours = int((remaining % 86400) // 3600)
        text = f"❤️ *چالش لایکی فعال*\n⏰ {days} روز و {hours} ساعت"
        kb = [[InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]]
    else:
        text = (
            f"❤️✨ *چالش لایکی* ✨❤️\n━━━━━━━━━━━━━━━━━━\n\n"
            f"💵 7 روزه: {format_number(LIKE_CHALLENGE_COST)} DP\n"
            f"💎 موجودی: `{format_number(db.get_balance(user.id))}` DP"
        )
        kb = [
            [InlineKeyboardButton(f"✅ فعال‌سازی ({format_number(LIKE_CHALLENGE_COST)})", callback_data="like_activate")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
        ]

    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


async def like_activate_cb(update, context):
    query = update.callback_query
    user = query.from_user
    await query.answer()

    if not db.remove_dark_points(user.id, LIKE_CHALLENGE_COST):
        await query.answer("❌ ناکافی!", show_alert=True)
        return

    db.update_user(user.id, like_challenge_active=1, like_challenge_until=time.time() + (7 * 86400))
    await query.edit_message_text(
        f"✅ *چالش لایکی فعال شد!*\n💵 `{format_number(LIKE_CHALLENGE_COST)}` DP\n⏰ 7 روز",
        parse_mode=ParseMode.MARKDOWN
    )


# ============ BUY PANEL ============

async def buy_panel_menu(update, context):
    query = update.callback_query
    await query.answer()

    buttons = [
        [InlineKeyboardButton(f"🛒 سنایی 500GB ({format_number(DEFAULT_PANEL_PRICES['snai_500gb'])} DP)", callback_data="panel_buy_snai_500gb")],
        [InlineKeyboardButton(f"🛒 سنایی 800GB ({format_number(DEFAULT_PANEL_PRICES['snai_800gb'])} DP)", callback_data="panel_buy_snai_800gb")],
        [InlineKeyboardButton(f"🛒 سنایی 1TB ({format_number(DEFAULT_PANEL_PRICES['snai_1tb'])} DP)", callback_data="panel_buy_snai_1tb")],
    ]

    for panel in db.get_custom_panels():
        buttons.append([InlineKeyboardButton(
            f"🛒 {panel['name']} ({format_number(panel['price'])} DP)",
            callback_data=f"panel_buy_custom_{panel['panel_id']}"
        )])

    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])
    balance = db.get_balance(query.from_user.id)
    text = f"🛒✨ *خرید پنل VPN* ✨🛒\n━━━━━━━━━━━━━━━━━━\n\n💎 موجودی: `{format_number(balance)}` DP\n\n_انتخاب کنید:_"
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))


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
            await query.answer("❌ یافت نشد!", show_alert=True)
            return
        name = panel['name']
        price = panel['price']
        plan_key = f"custom_{panel_id}"
    else:
        plan_key = data.replace("panel_buy_", "")
        prices = {"snai_500gb": ("سنایی 500GB", DEFAULT_PANEL_PRICES['snai_500gb']),
                  "snai_800gb": ("سنایی 800GB", DEFAULT_PANEL_PRICES['snai_800gb']),
                  "snai_1tb": ("سنایی 1TB", DEFAULT_PANEL_PRICES['snai_1tb'])}
        if plan_key not in prices:
            await query.answer("❌", show_alert=True)
            return
        name, price = prices[plan_key]

    await query.answer()
    if not db.remove_dark_points(user.id, price):
        await query.answer("❌ ناکافی!", show_alert=True)
        return

    config_data = create_panel_config(plan_key, user.id)
    order_id = db.create_panel_order(user.id, name, price, config_data)

    await query.edit_message_text(
        f"✅✨ *خرید موفق!* ✨✅\n━━━━━━━━━━━━━━━━━━\n\n"
        f"🛒 {name}\n💵 `{format_number(price)}` DP\n🆔 {order_id}\n\n"
        f"🔐 کانفیگ:\n`{config_data}`",
        parse_mode=ParseMode.MARKDOWN
    )
    bot_username = (await context.bot.get_me()).username
    log_kb = [[InlineKeyboardButton("🤖 ورود به ربات", url=f"https://t.me/{bot_username}")]]
    await send_log(context, f"🛒 *خرید پنل*\n👤 `{user.id}`\n📦 {name}\n💵 `{format_number(price)}`", reply_markup=InlineKeyboardMarkup(log_kb))


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
        return f"Config: {email} | {data_gb}GB | pending activation"
    except Exception as e:
        return f"dark_{user_id}_{int(time.time())} | pending"# ============ ADMIN PANEL ============

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return

    stats = db.get_stats()

    kb = [
        [InlineKeyboardButton("📊 آمار کامل ربات", callback_data="adm_stats")],
        [
            InlineKeyboardButton("📢 پیام همگانی", callback_data="adm_broadcast_msg"),
            InlineKeyboardButton("📤 فوروارد همگانی", callback_data="adm_broadcast_fwd"),
        ],
        [
            InlineKeyboardButton("💰 افزودن DP", callback_data="adm_add_dp"),
            InlineKeyboardButton("💸 کم کردن DP", callback_data="adm_remove_dp"),
        ],
        [
            InlineKeyboardButton("🔍 جستجوی کاربر", callback_data="adm_search_user"),
            InlineKeyboardButton("🚫 بن/آنبن", callback_data="adm_ban_user"),
        ],
        [
            InlineKeyboardButton("📢 کانال‌های اجباری", callback_data="adm_channels"),
        ],
        [
            InlineKeyboardButton("📦 ساخت پلن پنل", callback_data="adm_create_panel"),
            InlineKeyboardButton("🎁 افزودن پلن گیفت", callback_data="adm_add_gift_plan"),
        ],
        [
            InlineKeyboardButton("💵 تغییر قیمت گیفت", callback_data="adm_set_gift_price"),
            InlineKeyboardButton("⭐ تغییر قیمت استارز", callback_data="adm_set_stars_price"),
        ],
        [
            InlineKeyboardButton(f"🎁 گیفت: {'✅' if db.get_setting('gift_section_active','1')=='1' else '❌'}", callback_data="adm_toggle_gift"),
            InlineKeyboardButton(f"⭐ استارز: {'✅' if db.get_setting('stars_section_active','1')=='1' else '❌'}", callback_data="adm_toggle_stars"),
        ],
        [
            InlineKeyboardButton(f"💰 خرید DP: {'✅' if db.get_setting('buy_dp_active','1')=='1' else '❌'}", callback_data="adm_toggle_buydp"),
            InlineKeyboardButton(f"💥 انفجار: {'✅' if db.get_setting('crash_active','1')=='1' else '❌'}", callback_data="adm_toggle_crash"),
        ],
        [InlineKeyboardButton("📝 ساخت چک شخصی", callback_data="adm_create_check")],
        [InlineKeyboardButton("🎁 هدیه به همه کاربران", callback_data="adm_gift_all")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
    ]

    text = (
        f"🛡✨ *پنل ادمین* ✨🛡\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 کل کاربران: {stats['total_users']}\n"
        f"✅ فعال 7 روزه: {stats['active_7d']}\n"
        f"🆕 امروز: {stats['new_today']}\n"
        f"🚫 بن شده: {stats['banned_users']}\n"
        f"💎 کل DP: `{format_number(stats['total_dp'])}`\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


async def admin_stats(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()
    stats = db.get_stats()
    text = (
        f"📊✨ *آمار کامل ربات* ✨📊\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 *کاربران:*\n"
        f"  • کل: {stats['total_users']}\n"
        f"  • فعال 7 روزه: {stats['active_7d']}\n"
        f"  • جدید امروز: {stats['new_today']}\n"
        f"  • بن شده: {stats['banned_users']}\n\n"
        f"💰 *مالی:*\n"
        f"  • کل DP در گردش: `{format_number(stats['total_dp'])}`\n"
        f"  • کل موجودی بانک: `{format_number(stats['total_bank'])}`\n\n"
        f"📦 *سفارشات:*\n"
        f"  • پنل: {stats['panel_orders']}\n"
        f"  • گیفت: {stats['gift_orders']}\n"
        f"  • استارز: {stats['stars_orders']}\n\n"
        f"💥 *انفجار:*\n"
        f"  • برد: {stats['crash_won']}\n"
        f"  • باخت: {stats['crash_lost']}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    kb = [[InlineKeyboardButton("🔙 پنل ادمین", callback_data="adm_back")]]
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


# ============ BROADCAST ============

async def adm_broadcast_msg(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()
    context.user_data['admin_action'] = 'broadcast_msg'
    await query.edit_message_text(
        "📢 *پیام همگانی*\n\nپیام مورد نظر را ارسال کنید (متن، عکس، ویدیو یا هر چیز):\n\n_/cancel لغو_",
        parse_mode=ParseMode.MARKDOWN
    )


async def adm_broadcast_fwd(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()
    context.user_data['admin_action'] = 'broadcast_fwd'
    await query.edit_message_text(
        "📤 *فوروارد همگانی*\n\nپیامی که می‌خواهی فوروارد بشه رو ارسال کن:",
        parse_mode=ParseMode.MARKDOWN
    )


async def do_broadcast(update, context, mode='copy'):
    admin_id = update.effective_user.id
    users = db.get_all_user_ids()
    total = len(users)
    sent = 0
    failed = 0

    status_msg = await update.message.reply_text(f"⏳ در حال ارسال به {total} کاربر...")

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
            failed += 1

        # Update progress every 20 users
        if (sent + failed) % 20 == 0:
            try:
                await status_msg.edit_text(
                    f"⏳ در حال ارسال...\n"
                    f"✅ موفق: {sent}\n"
                    f"❌ ناموفق: {failed}\n"
                    f"📊 پیشرفت: {sent+failed}/{total}"
                )
            except:
                pass
        await asyncio.sleep(0.05)

    db.log_broadcast(admin_id, mode, total, sent, failed)

    try:
        await update.message.reply_sticker(STICKERS.get('broadcast', ''))
    except:
        pass

    await status_msg.edit_text(
        f"✅ *ارسال کامل شد!*\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 کل کاربران: {total}\n"
        f"✅ ارسال موفق: {sent}\n"
        f"❌ ارسال ناموفق: {failed}\n"
        f"📈 درصد موفقیت: {int(sent/total*100 if total else 0)}%\n"
        f"━━━━━━━━━━━━━━━━━━",
        parse_mode=ParseMode.MARKDOWN
    )


# ============ CHANNELS MANAGEMENT ============

async def adm_channels(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()

    channels = db.get_force_channels()
    text = f"📢✨ *کانال‌های عضویت اجباری* ✨📢\n━━━━━━━━━━━━━━━━━━\n\n"
    
    if not channels:
        text += "❌ هیچ کانالی ثبت نشده\n"
    else:
        for ch in channels:
            text += f"• {ch['channel_username']}\n"
    
    text += "\n━━━━━━━━━━━━━━━━━━"

    kb = [
        [InlineKeyboardButton("➕ افزودن کانال", callback_data="adm_add_channel")],
    ]
    for ch in channels:
        kb.append([InlineKeyboardButton(f"🗑 حذف {ch['channel_username']}", callback_data=f"adm_del_ch_{ch['channel_id']}")])
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="adm_back")])

    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(kb))


async def adm_add_channel(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    await query.answer()
    context.user_data['admin_action'] = 'add_channel'
    await query.edit_message_text(
        "➕ *افزودن کانال*\n\nیوزرنیم کانال را با @ بفرست:\n\n_مثال: @mychannel_",
        parse_mode=ParseMode.MARKDOWN
    )


async def adm_del_channel(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        return
    channel_id = int(query.data.split("_")[-1])
    db.remove_force_channel(channel_id)
    await query.answer("✅ حذف شد", show_alert=True)
    await adm_channels(update, context)


# ============ ADMIN CALLBACKS ============

async def admin_callbacks(update, context):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌", show_alert=True)
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
        await adm_add_channel(update, context)
    elif data.startswith("adm_del_ch_"):
        await adm_del_channel(update, context)
    elif data == "adm_add_dp":
        await query.answer()
        context.user_data['admin_action'] = 'add_dp'
        await query.edit_message_text("💰 شماره کاربری را بفرست:")
    elif data == "adm_remove_dp":
        await query.answer()
        context.user_data['admin_action'] = 'remove_dp'
        await query.edit_message_text("💸 شماره کاربری را بفرست:")
    elif data == "adm_search_user":
        await query.answer()
        context.user_data['admin_action'] = 'search_user'
        await query.edit_message_text("🔍 شماره کاربری یا @username را بفرست:")
    elif data == "adm_ban_user":
        await query.answer()
        context.user_data['admin_action'] = 'ban_user'
        await query.edit_message_text("🚫 شماره کاربری برای بن/آنبن:")
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
        await query.edit_message_text("📝 مبلغ چک (DP):")
    elif data == "adm_add_gift_plan":
        await query.answer()
        context.user_data['admin_action'] = 'add_gift_plan'
        context.user_data['gift_plan_step'] = 'name'
        await query.edit_message_text("🎁 نام پلن گیفت:")
    elif data == "adm_gift_all":
        await query.answer()
        context.user_data['admin_action'] = 'gift_all'
        await query.edit_message_text("🎁 مقدار DP هدیه به همه (به همه کاربران):")# ============ PRIVATE MESSAGE HANDLER ============

async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if db.is_banned(user.id):
        return

    if not db.get_user(user.id):
        db.create_user(user.id, user.username or "", user.first_name or "")
    
    db.update_last_active(user.id)

    # Admin actions with any content (broadcast)
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

    # Cancel command
    if text.lower() in ['/cancel', 'لغو', 'cancel']:
        context.user_data.clear()
        await update.message.reply_text("✅ لغو شد.")
        return

    # Admin text-based actions
    if is_admin(user.id) and 'admin_action' in context.user_data:
        await handle_admin_text(update, context)
        return

    # Bank card
    if context.user_data.get('awaiting_bank_card'):
        if len(text) != 13 or not text.isdigit():
            await update.message.reply_text("❌ باید 13 رقم انگلیسی باشد!")
            return
        if db.card_exists(text):
            await update.message.reply_text("❌ این کارت قبلاً ثبت شده!")
            return
        if not db.remove_dark_points(user.id, BANK_OPEN_COST):
            await update.message.reply_text("❌ ناکافی!")
            context.user_data.pop('awaiting_bank_card', None)
            return
        db.open_bank_account(user.id, text)
        context.user_data.pop('awaiting_bank_card', None)
        await update.message.reply_text(
            f"✅ *حساب افتتاح شد!*\n💳 `{text}`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # Bank deposit
    if context.user_data.get('awaiting_bank_deposit'):
        try:
            amount = int(text)
            if amount <= 0:
                await update.message.reply_text("❌ نامعتبر!")
                return
            if db.bank_deposit(user.id, amount):
                context.user_data.pop('awaiting_bank_deposit', None)
                await update.message.reply_text(
                    f"✅ *واریز موفق*\n💰 `{format_number(amount)}` DP\n📈 24 ساعت صبر برای سود",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text("❌ ناکافی!")
        except:
            await update.message.reply_text("❌ عدد بفرست!")
        return

    # Stars target
    if context.user_data.get('awaiting_stars_target'):
        target = text.strip().replace("@", "")
        stars_price = int(db.get_setting('stars_price', '1000000'))
        if not db.remove_dark_points(user.id, stars_price):
            await update.message.reply_text("❌ ناکافی!")
            context.user_data.pop('awaiting_stars_target', None)
            return
        db.create_stars_order(user.id, target, 'other', STARS_AMOUNT, stars_price)
        context.user_data.pop('awaiting_stars_target', None)
        await update.message.reply_text(
            f"✅ *سفارش ثبت شد!*\n⭐ {STARS_AMOUNT} → `{target}`",
            parse_mode=ParseMode.MARKDOWN
        )
        bot_username = (await context.bot.get_me()).username
        log_kb = [[InlineKeyboardButton("🤖 ورود", url=f"https://t.me/{bot_username}")]]
        await send_log(context, f"⭐ سفارش استارز (اکانت دیگه)\n👤 `{user.id}`\n📍 `{target}`", reply_markup=InlineKeyboardMarkup(log_kb))
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(admin_id, f"⭐ سفارش\n👤 `{user.id}`\n📍 `{target}`", parse_mode=ParseMode.MARKDOWN)
            except:
                pass
        return


async def handle_admin_text(update, context):
    user = update.effective_user
    text = update.message.text.strip()
    action = context.user_data.get('admin_action')

    if action == 'add_channel':
        username = text.strip()
        if not username.startswith('@'):
            username = '@' + username
        try:
            chat = await context.bot.get_chat(username)
            title = chat.title or username
            if db.add_force_channel(username, title):
                await update.message.reply_text(f"✅ کانال {username} اضافه شد!")
            else:
                await update.message.reply_text("❌ کانال قبلاً اضافه شده!")
        except Exception as e:
            await update.message.reply_text(f"❌ خطا: مطمئن شوید ربات ادمین کانال است.\n{e}")
        context.user_data.pop('admin_action', None)
        return

    if action == 'add_dp':
        if 'admin_target_user' not in context.user_data:
            try:
                target_id = int(text)
                context.user_data['admin_target_user'] = target_id
                await update.message.reply_text(f"💰 چقدر به `{target_id}` اضافه شود؟", parse_mode=ParseMode.MARKDOWN)
                return
            except:
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
                await update.message.reply_text(
                    f"✅ *اضافه شد!*\n👤 `{target_id}`\n💰 +`{format_number(amount)}` DP",
                    parse_mode=ParseMode.MARKDOWN
                )
                try:
                    await context.bot.send_message(
                        target_id,
                        f"🎁 *دارک پوینت هدیه!*\n➕ +`{format_number(amount)}` DP توسط ادمین",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except:
                    pass
            except:
                await update.message.reply_text("❌ نامعتبر!")
            context.user_data.clear()
            return

    if action == 'remove_dp':
        if 'admin_target_user' not in context.user_data:
            try:
                context.user_data['admin_target_user'] = int(text)
                await update.message.reply_text("💸 چقدر کم شود؟")
                return
            except:
                context.user_data.clear()
                return
        else:
            try:
                amount = int(text)
                target_id = context.user_data['admin_target_user']
                db.remove_dark_points(target_id, amount)
                await update.message.reply_text(f"✅ کم شد: -{format_number(amount)} از `{target_id}`", parse_mode=ParseMode.MARKDOWN)
            except:
                await update.message.reply_text("❌ نامعتبر!")
            context.user_data.clear()
            return

    if action == 'search_user':
        u = None
        try:
            uid = int(text)
            u = db.get_user(uid)
        except:
            u = db.search_user_by_username(text)
        
        if not u:
            await update.message.reply_text("❌ کاربر یافت نشد!")
        else:
            banned = "🚫 بن شده" if u['is_banned'] else "✅ فعال"
            await update.message.reply_text(
                f"👤 *اطلاعات کاربر*\n━━━━━━━━━━━━\n\n"
                f"🆔 `{u['user_id']}`\n"
                f"📛 @{u['username'] or 'ندارد'}\n"
                f"👤 {u['first_name']}\n"
                f"💰 موجودی: `{format_number(u['dark_points'])}` DP\n"
                f"📊 سطح: {u['level']}\n"
                f"👥 زیرمجموعه: {u['referral_count']}\n"
                f"📊 وضعیت: {banned}",
                parse_mode=ParseMode.MARKDOWN
            )
        context.user_data.clear()
        return

    if action == 'ban_user':
        try:
            target_id = int(text)
            u = db.get_user(target_id)
            if not u:
                await update.message.reply_text("❌ یافت نشد!")
            else:
                if u['is_banned']:
                    db.unban_user(target_id)
                    await update.message.reply_text(f"✅ آنبن شد: `{target_id}`", parse_mode=ParseMode.MARKDOWN)
                else:
                    db.ban_user(target_id)
                    await update.message.reply_text(f"🚫 بن شد: `{target_id}`", parse_mode=ParseMode.MARKDOWN)
        except:
            await update.message.reply_text("❌ نامعتبر!")
        context.user_data.clear()
        return

    if action == 'create_panel':
        step = context.user_data.get('panel_step')
        if step == 'name':
            context.user_data['panel_name'] = text
            context.user_data['panel_step'] = 'desc'
            await update.message.reply_text("📝 توضیحات:")
        elif step == 'desc':
            context.user_data['panel_desc'] = text
            context.user_data['panel_step'] = 'price'
            await update.message.reply_text("💰 قیمت (DP):")
        elif step == 'price':
            try:
                context.user_data['panel_price'] = int(text)
                context.user_data['panel_step'] = 'data'
                await update.message.reply_text("📊 حجم دیتا:")
            except:
                await update.message.reply_text("❌ عدد!")
        elif step == 'data':
            db.add_custom_panel(
                context.user_data['panel_name'],
                context.user_data['panel_desc'],
                context.user_data['panel_price'],
                text
            )
            await update.message.reply_text(f"✅ پلن `{context.user_data['panel_name']}` ساخته شد!", parse_mode=ParseMode.MARKDOWN)
            context.user_data.clear()
        return

    if action == 'set_gift_price':
        try:
            db.set_setting('gift_teddy_price', str(int(text)))
            await update.message.reply_text(f"✅ قیمت جدید: `{format_number(int(text))}` DP", parse_mode=ParseMode.MARKDOWN)
        except:
            await update.message.reply_text("❌")
        context.user_data.clear()
        return

    if action == 'set_stars_price':
        try:
            db.set_setting('stars_price', str(int(text)))
            await update.message.reply_text(f"✅ قیمت: `{format_number(int(text))}` DP", parse_mode=ParseMode.MARKDOWN)
        except:
            await update.message.reply_text("❌")
        context.user_data.clear()
        return

    if action == 'create_check':
        try:
            amount = int(text)
            code = db.create_check(amount)
            bot_username = (await context.bot.get_me()).username
            link = f"https://t.me/{bot_username}?start=check_{code}"
            await update.message.reply_text(
                f"✅ *چک ساخته شد!*\n💰 `{format_number(amount)}` DP\n🔗 `{link}`",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            await update.message.reply_text("❌")
        context.user_data.clear()
        return

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
                await update.message.reply_text(f"✅ پلن {name} با قیمت {format_number(price)} DP اضافه شد!")
            except:
                await update.message.reply_text("❌")
            context.user_data.clear()
        return

    if action == 'gift_all':
        try:
            amount = int(text)
            users = db.get_all_user_ids()
            for uid in users:
                db.add_dark_points(uid, amount)
            await update.message.reply_text(
                f"✅ *هدیه ارسال شد!*\n💰 `{format_number(amount)}` DP به {len(users)} کاربر",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            await update.message.reply_text("❌ نامعتبر!")
        context.user_data.clear()
        return# ============ CALLBACK ROUTER ============

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
    elif data.startswith("order_gift_custom_"):
        await order_gift_custom(update, context)
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


# ============ PERIODIC TASKS ============

async def periodic_maintenance(context: ContextTypes.DEFAULT_TYPE):
    conn = db.get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE factory_active = 1")
    for row in c.fetchall():
        db.factory_maintenance_due(row['user_id'])
    conn.close()


# ============ MAIN ============

def main():
    start_health_server()

    application = Application.builder().token(BOT_TOKEN).build()

    # Conversation for captcha
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CAPTCHA_VERIFY: [MessageHandler(filters.TEXT & ~filters.COMMAND, captcha_verify)],
        },
        fallbacks=[CommandHandler("cancel", start)],
    )
    application.add_handler(conv_handler)

    application.add_handler(CommandHandler("admin", admin_panel))

    application.add_handler(CallbackQueryHandler(callback_router))

    # Group messages
    application.add_handler(MessageHandler(
        filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
        handle_group_message
    ))

    # Private messages (all types for broadcast)
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
    application.job_queue.run_repeating(periodic_maintenance, interval=300, first=10)
    application.job_queue.run_repeating(self_ping, interval=480, first=60)

    print("🏴 Dark Point Bot Running...")
    application.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
        self.wfile.write(html.encode("utf-8"))
    def log_message(self, format, *args):
        return

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        logger.info(f"🌐 Health server on port {port}")
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
            if r.status == 200:
                logger.info("🟢 Self-ping OK")
    except Exception as e:
        logger.error(f"Ping failed: {e}")
