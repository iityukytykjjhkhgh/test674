# config.py — Dark Point Bot Configuration
import os

BOT_TOKEN = "8519305274:AAGF5rrvS9jLG2Lct3UqqaTcMLxjRHHIONA"
ADMIN_ID = 8248647747
LOG_CHANNEL = -1004482670552

DATA_DIR = os.environ.get("DATA_DIR", ".")
DB_PATH = os.path.join(DATA_DIR, "bot.db")

# ── Currency & Claim ──
BASE_CLAIM_MIN = 100
BASE_CLAIM_MAX = 250
CLAIM_COOLDOWN_MIN = 180
CLAIM_COOLDOWN_MAX = 300
DP_PER_LEVEL = 40

# ── TON Withdrawal (NEW) ──
TON_WITHDRAWAL_DP_RATE = 200_000_000   # 200M DP
TON_WITHDRAWAL_TON_AMOUNT = 0.0005     # = 0.0005 TON
TON_WITHDRAWAL_MIN = 0.01              # min 0.01 TON

# ── Dark Bank (UPDATED) ──
BANK_INTEREST_RATE = 0.03              # 3% per 48 h
BANK_LOCK_PERIOD = 48 * 3600           # 48 hours

# ── Bomb Game (UPDATED) ──
BOMB_MULTIPLIER_STEP = 0.2
BOMB_GRID_SIZE = 4
BOMB_COUNT = 6

# ── Level System (NEW 20-level) ──
LEVEL_THRESHOLDS = [
    0,              # L1
    20_000_000,     # L2
    50_000_000,     # L3
    100_000_000,    # L4
    250_000_000,    # L5
    400_000_000,    # L6
    800_000_000,    # L7
    1_000_000_000,  # L8
    1_300_000_000,  # L9
    1_500_000_000,  # L10
    1_800_000_000,  # L11
    2_000_000_000,  # L12
    2_500_000_000,  # L13
    3_000_000_000,  # L14
    4_000_000_000,  # L15
    5_000_000_000,  # L16
    8_000_000_000,  # L17
    12_000_000_000, # L18
    15_000_000_000, # L19
    20_000_000_000, # L20
]

def get_level_reward(level):
    """Level N reward = N × 1,000,000 DP"""
    return level * 1_000_000

# ── Game Limits ──
CRASH_MIN_BET = 500
CRASH_MAX_BET = 500_000
DICE_MIN_BET = 15_000
GUESS_MIN_BET = 30_000
CASINO_MIN_BET = 25_000
BOMB_MIN_BET = 35_000
GAME_TIMEOUT = 600

# ── Transfer ──
TRANSFER_FEE = 0.10
TRANSFER_DAILY_LIMIT = 10

# ── Miner ──
MINER_BUY_COST = 5_000_000
MINER_LEVELS = {
    1: {"ton": 0.01, "usdt": 0.03, "upgrade": 20_000_000},
    2: {"ton": 0.03, "usdt": 0.05, "upgrade": 100_000_000},
    3: {"ton": 0.04, "usdt": 0.07, "upgrade": 300_000_000},
    4: {"ton": 0.06, "usdt": 0.09, "upgrade": 500_000_000},
    5: {"ton": 0.09, "usdt": 0.12, "upgrade": 0},
}
MINER_ELECTRICITY_COST = 2_000_000

# ── Currency Conversion ──
TON_TO_DP = 100_000
USDT_TO_DP = 50_000
TON_CONVERT_MIN = 0.7
USDT_CONVERT_MIN = 2.0

# ── Stars ──
STARS_DP_COST = 1_000_000

# ── Referral ──
DEFAULT_REFERRAL_REWARD = 50_000
DEFAULT_FIRST_JOIN_REWARD = 50_000

# ── Like Challenge ──
LIKE_CHALLENGE_COST = 30_000
LIKE_CHALLENGE_DAYS = 7

# ── Wheel ──
WHEEL_FREE_MIN = 5_000
WHEEL_FREE_MAX = 100_000
WHEEL_EXTRA_COST = 50_000

# ── Buy DP Defaults ──
BUY_DP_DEFAULT_AMOUNT = 500_000
BUY_DP_DEFAULT_PRICE = 50_000

# ── Group ──
MIN_GROUP_MEMBERS = 30

# ── Messages ──
BOT_OFF_MESSAGE = "ربات موقتاً از طرف پشتیبانی خاموش شده"
SECTION_OFF_MESSAGE = "این بخش موقتاً خاموش می‌باشد"
PANEL_PURCHASE_MESSAGE = "ادمین کانفیگ رو از پنل سنایی بزودی ارسال می‌کند"

# ── Stickers (disabled) ──
STICKER_WELCOME = ""
STICKER_WIN = ""
STICKER_LOSE = ""

# ── Server ──
PORT = int(os.environ.get("PORT", 8080))
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
