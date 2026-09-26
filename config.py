# config.py - Dark Point Bot Configuration

BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"

# Admin IDs
ADMIN_IDS = [123456789]  # آیدی عددی ادمین

# Support
SUPPORT_USERNAME = "@kanfingfreesup"

# Channels for force join
FORCE_JOIN_CHANNELS = [
    "@channel1",
    "@channel2",
]

# Log channel
LOG_CHANNEL_ID = -1001234567890  # آیدی کانال لاگ

# Panel API Settings
PANEL_URL = "https://your-panel-url.com"
PANEL_API_KEYS = {
    "snai": "9a80695b6e3fdfdae22ec69dc110b954"
}
PANEL_INBOUND_ID = 32063619

# Default prices (Dark Points)
DEFAULT_PANEL_PRICES = {
    "snai_500gb": 400000,
    "snai_800gb": 600000,
    "snai_1tb": 1000000,
}

# Gift prices
DEFAULT_GIFT_TEDDY_PRICE = 750000

# Stars withdrawal
DEFAULT_STARS_PRICE = 1000000  # 1M DP = 50 Stars
STARS_AMOUNT = 50

# Self bot cost
SELF_ACTIVATION_COST = 1000
SELF_HOURLY_COST = 600

# Like challenge cost (7 days)
LIKE_CHALLENGE_COST = 30000

# Referral reward
REFERRAL_REWARD = 30000

# Bank
BANK_OPEN_COST = 20000
BANK_INTEREST_RATE = 0.10  # 10%
BANK_INTEREST_PERIOD = 86400  # 24 hours in seconds

# Factory
FACTORY_OPEN_COST = 100000
FACTORY_HOURLY_MAINTENANCE = 80
FACTORY_LEVELS = {
    1: {"mine_per_min": 10, "upgrade_cost": 50000},
    2: {"mine_per_min": 25, "upgrade_cost": 80000},
    3: {"mine_per_min": 40, "upgrade_cost": 100000},
    4: {"mine_per_min": 50, "upgrade_cost": 250000},
    5: {"mine_per_min": 100, "upgrade_cost": 0},  # Max level
}

# Game settings
MIN_GAME_AMOUNT = 100
TRANSFER_FEE = 0.10  # 10%

# Group minimum members
MIN_GROUP_MEMBERS = 30

# Level requirements (total DP needed to reach level)
LEVEL_REQUIREMENTS = {
    1: 0,
    2: 20000,
    3: 40000,
    4: 80000,
    5: 150000,
    6: 200000,
    7: 300000,
    8: 500000,
    9: 800000,
    10: 1000000,
    11: 1500000,
    12: 1800000,
    13: 2000000,
    14: 2500000,
    15: 3000000,
    16: 4000000,
    17: 6000000,
    18: 10000000,
    19: 15000000,
    20: 20000000,
}

# Level up rewards
LEVEL_REWARDS = {
    2: 2000,
    3: 2000,
    4: 5000,
    5: 6000,
    6: 8000,
    7: 10000,
    8: 12000,
    9: 15000,
    10: 30000,  # Silver level
    11: 11000,
    12: 12000,
    13: 13000,
    14: 14000,
    15: 15000,
    16: 16000,
    17: 17000,
    18: 18000,
    19: 19000,
    20: 20000,
}

# Dark point earning per claim
BASE_MIN_DP = 100
BASE_MAX_DP = 250
DP_INCREASE_PER_LEVEL = 40

# Cooldown (seconds)
MIN_COOLDOWN = 180  # 3 minutes
MAX_COOLDOWN = 300  # 5 minutes

# Level titles
LEVEL_TITLES = {
    1: "🌑 تاریکی‌نشین",
    2: "🌒 سایه‌پرداز",
    3: "🌓 شب‌گرد",
    4: "🌔 ماه‌جو",
    5: "🌕 ستاره‌شناس",
    6: "⭐ فرمانده تاریکی",
    7: "🌟 شوالیه سایه",
    8: "💫 لرد تاریکی",
    9: "✨ شاهزاده سایه‌ها",
    10: "🥈 نقره‌ای",
    11: "🥇 طلایی",
    12: "💎 الماسی",
    13: "👑 پادشاه تاریکی",
    14: "🏆 افسانه‌ای",
    15: "🔮 جادوگر سایه",
    16: "🐉 اژدهای تاریک",
    17: "⚡ رعد تاریکی",
    18: "🌪 طوفان سایه",
    19: "🔥 آتشین تاریک",
    20: "🏴 امپراتور تاریکی",
}

# Stickers
STICKERS = {
    "earn": "CAACAgIAAxkBAAEBjQ1mF0X0AAECzQABQsMZCX9QR6NPDdUAAjEAA1advQoVAAFEzMXWaIY0BA",
    "levelup": "CAACAgIAAxkBAAEBjQ9mF0YKOgxhGgvWnzl3VPf_9e_VcAACMgADWp29ChSqXJZzUh3HNAQ",
    "game": "CAACAgIAAxkBAAEBjRFmF0YfthWxS8GN3z_QZHN2M7BLcAACMwADWp29CsuU-3BH9Pl1NAQ",
    "profile": "CAACAgIAAxkBAAEBjRNmF0Y0qK3IPgrlIFo6Yx1S-4excAACNAADWp29CkPZl_v0e3I3NAQ",
    "bank": "CAACAgIAAxkBAAEBjRVmF0ZJxDt_c-V6Xt3oL7p7LGx1cAACNQADWp29Ch7T7eDm1xG7NAQ",
    "factory": "CAACAgIAAxkBAAEBjRdmF0ZdR5M9lQNlA_sFvVEOlXKEcAACNgADWp29CuWNrYXQi3YKNAQ",
    "welcome": "CAACAgIAAxkBAAEBjRlmF0ZxfGtPU1yrB7yIXwuJ3rd1cAACNwADWp29CpYz1K5h8tXBNAQ",
    "stars": "CAACAgIAAxkBAAEBjRtmF0aFQ5qIHEGNl2hJxxO3OGx1cAACOAADWp29CjKlzd3-QAABYQ0E",
}

# Buy DP settings
BUY_DP_AMOUNT = 500000
BUY_DP_PRICE_TOMAN = 50000