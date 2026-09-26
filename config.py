# config.py - Dark Point Bot Configuration

# ⚠️ هشدار: این توکن فاش شده است. پس از تست حتماً آن را ریست کنید!
BOT_TOKEN = "8519305274:AAGF5rrvS9jLG2Lct3UqqaTcMLxjRHHIONA"

# آیدی عددی شما به عنوان ادمین اصلی ربات
ADMIN_IDS = [8248647747]

# آیدی پشتیبانی ربات
SUPPORT_USERNAME = "@kanfingfreesup"

# آیدی کانال لاگ (حتماً ربات را در این کانال ادمین کنید)
LOG_CHANNEL_ID = -1001234567890

# تنظیمات پنل سنایی (در صورت عدم استفاده، مقادیر پیش‌فرض بمانند)
PANEL_URL = "https://your-panel-url.com"
PANEL_API_KEYS = {"snai": "9a80695b6e3fdfdae22ec69dc110b954"}
PANEL_INBOUND_ID = 32063619

# قیمت‌های پیش‌فرض پلن‌ها به دارک پوینت
DEFAULT_PANEL_PRICES = {
    "snai_500gb": 400000,
    "snai_800gb": 600000,
    "snai_1tb": 1000000,
}

# تنظیمات جوایز و قیمت‌ها
DEFAULT_GIFT_TEDDY_PRICE = 750000
DEFAULT_STARS_PRICE = 1000000
STARS_AMOUNT = 50
LIKE_CHALLENGE_COST = 30000
REFERRAL_REWARD = 30000

# تنظیمات بانک دارکی
BANK_OPEN_COST = 20000
BANK_INTEREST_RATE = 0.10
BANK_INTEREST_PERIOD = 86400

# تنظیمات کارخونه دارکی
FACTORY_OPEN_COST = 100000
FACTORY_HOURLY_MAINTENANCE = 80
FACTORY_LEVELS = {
    1: {"mine_per_min": 10, "upgrade_cost": 50000},
    2: {"mine_per_min": 25, "upgrade_cost": 80000},
    3: {"mine_per_min": 40, "upgrade_cost": 100000},
    4: {"mine_per_min": 50, "upgrade_cost": 250000},
    5: {"mine_per_min": 100, "upgrade_cost": 0},
}

# تنظیمات بازی تفریحی گروهی
MIN_GAME_AMOUNT = 100
TRANSFER_FEE = 0.10
MIN_GROUP_MEMBERS = 30

# تنظیمات بازی انفجار
CRASH_MIN_BET = 500
CRASH_MAX_BET = 500000
CRASH_MIN_MULTIPLIER = 1.1
CRASH_MAX_MULTIPLIER = 15.0

# نیازهای ارتقا سطح (مجموع دارک پوینت کسب شده)
LEVEL_REQUIREMENTS = {
    1: 0, 2: 20000, 3: 40000, 4: 80000, 5: 150000,
    6: 200000, 7: 300000, 8: 500000, 9: 800000, 10: 1000000,
    11: 1500000, 12: 1800000, 13: 2000000, 14: 2500000, 15: 3000000,
    16: 4000000, 17: 6000000, 18: 10000000, 19: 15000000, 20: 20000000,
}

# هدیه ارتقا به سطح جدید
LEVEL_REWARDS = {
    2: 2000, 3: 2000, 4: 5000, 5: 6000, 6: 8000, 7: 10000,
    8: 12000, 9: 15000, 10: 30000, 11: 11000, 12: 12000, 13: 13000,
    14: 14000, 15: 15000, 16: 16000, 17: 17000, 18: 18000, 19: 19000, 20: 20000,
}

# مقدار بیس دریافت دارک پوینت در گروه
BASE_MIN_DP = 100
BASE_MAX_DP = 250
DP_INCREASE_PER_LEVEL = 40
MIN_COOLDOWN = 180
MAX_COOLDOWN = 300

# عنوان سطوح ربات
LEVEL_TITLES = {
    1: "🌑 تاریکی‌نشین", 2: "🌒 سایه‌پرداز", 3: "🌓 شب‌گرد",
    4: "🌔 ماه‌جو", 5: "🌕 ستاره‌شناس", 6: "⭐ فرمانده تاریکی",
    7: "🌟 شوالیه سایه", 8: "💫 لرد تاریکی", 9: "✨ شاهزاده سایه‌ها",
    10: "🥈 نقره‌ای", 11: "🥇 طلایی", 12: "💎 الماسی",
    13: "👑 پادشاه تاریکی", 14: "🏆 افسانه‌ای", 15: "🔮 جادوگر سایه",
    16: "🐉 اژدهای تاریک", 17: "⚡ رعد تاریکی", 18: "🌪 طوفان سایه",
    19: "🔥 آتشین تاریک", 20: "🏴 امپراتور تاریکی",
}

# شناسه استیکرهای تزیینی ربات (خالی گذاشته شده تا ارور تداخل ایجاد نکند)
STICKERS = {
    "earn": "",
    "levelup": "",
    "game": "",
    "profile": "",
    "bank": "",
    "factory": "",
    "welcome": "",
    "stars": "",
    "crash": "",
    "money": "",
    "broadcast": "",
}

# مشخصات خرید مستقیم دارک پوینت
BUY_DP_AMOUNT = 500000
BUY_DP_PRICE_TOMAN = 50000
