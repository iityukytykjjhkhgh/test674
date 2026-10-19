# database.py — Dark Point Bot Database (قسمت 1/3)
import sqlite3
import time
import uuid
import logging
from datetime import date

import config

logger = logging.getLogger(__name__)


class Database:
    def __init__(self):
        self.conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_db()

    # ══════════════════════════════════════════════
    #              SCHEMA & MIGRATION
    # ══════════════════════════════════════════════

    def _init_db(self):
        c = self.conn.cursor()

        # ── Users ──
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            balance INTEGER DEFAULT 0,
            total_earned INTEGER DEFAULT 0,
            referrals INTEGER DEFAULT 0,
            referred_by INTEGER DEFAULT 0,
            last_claim INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            created_at INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0,
            transfer_count_today INTEGER DEFAULT 0,
            transfer_reset_date TEXT DEFAULT '',
            wheel_used_today INTEGER DEFAULT 0,
            wheel_reset_date TEXT DEFAULT '',
            like_challenge_active INTEGER DEFAULT 0,
            like_challenge_start INTEGER DEFAULT 0,
            panel_purchased INTEGER DEFAULT 0,
            panel_plan TEXT DEFAULT '',
            factory_level INTEGER DEFAULT 0,
            factory_last_collect INTEGER DEFAULT 0
        )''')

        # ── Miners ──
        c.execute('''CREATE TABLE IF NOT EXISTS miners (
            user_id INTEGER PRIMARY KEY,
            level INTEGER DEFAULT 1,
            currency TEXT DEFAULT 'TON',
            electricity_end INTEGER DEFAULT 0,
            last_collect INTEGER DEFAULT 0,
            total_ton REAL DEFAULT 0.0,
            total_usdt REAL DEFAULT 0.0
        )''')

        # ── Bank Deposits ──
        c.execute('''CREATE TABLE IF NOT EXISTS bank_deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            deposit_time INTEGER NOT NULL,
            withdrawn INTEGER DEFAULT 0,
            interest_earned INTEGER DEFAULT 0
        )''')

        # ── TON Withdrawals (NEW) ──
        c.execute('''CREATE TABLE IF NOT EXISTS ton_withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT DEFAULT '',
            wallet_address TEXT NOT NULL,
            ton_amount REAL NOT NULL,
            dp_cost INTEGER NOT NULL,
            tracking_code TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at INTEGER DEFAULT 0
        )''')

        # ── Shop Items ──
        c.execute('''CREATE TABLE IF NOT EXISTS shop_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            stock INTEGER DEFAULT -1,
            media_type TEXT DEFAULT 'text',
            media_content TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1
        )''')

        # ── Shop Orders ──
        c.execute('''CREATE TABLE IF NOT EXISTS shop_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            created_at INTEGER DEFAULT 0
        )''')

        # ── Tasks ──
        c.execute('''CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            reward INTEGER DEFAULT 0,
            data TEXT DEFAULT '',
            capacity INTEGER DEFAULT -1,
            completed_count INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1
        )''')

        # ── User Tasks ──
        c.execute('''CREATE TABLE IF NOT EXISTS user_tasks (
            user_id INTEGER NOT NULL,
            task_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, task_id)
        )''')

        # ── Gift Plans ──
        c.execute('''CREATE TABLE IF NOT EXISTS gift_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            is_active INTEGER DEFAULT 1
        )''')

        # ── Settings (key-value store) ──
        c.execute('''CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        )''')

        # ── Force Join Channels ──
        c.execute('''CREATE TABLE IF NOT EXISTS force_join_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT NOT NULL,
            channel_username TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1
        )''')

        # ── Admin Groups ──
        c.execute('''CREATE TABLE IF NOT EXISTS admin_groups (
            chat_id INTEGER PRIMARY KEY,
            title TEXT DEFAULT '',
            added_at INTEGER DEFAULT 0
        )''')

        # ── Panel Plans ──
        c.execute('''CREATE TABLE IF NOT EXISTS panel_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            is_active INTEGER DEFAULT 1
        )''')

        self.conn.commit()

        # ── Auto-migrate missing columns ──
        self._migrate()

        # ── Insert default settings ──
        self._insert_defaults()

    def _migrate(self):
        """Add missing columns to existing tables without data loss"""
        c = self.conn.cursor()

        migrations = {
            'users': {
                'total_earned': 'INTEGER DEFAULT 0',
                'wheel_used_today': 'INTEGER DEFAULT 0',
                'wheel_reset_date': "TEXT DEFAULT ''",
                'like_challenge_active': 'INTEGER DEFAULT 0',
                'like_challenge_start': 'INTEGER DEFAULT 0',
                'panel_purchased': 'INTEGER DEFAULT 0',
                'panel_plan': "TEXT DEFAULT ''",
                'factory_level': 'INTEGER DEFAULT 0',
                'factory_last_collect': 'INTEGER DEFAULT 0',
            },
            'bank_deposits': {
                'interest_earned': 'INTEGER DEFAULT 0',
            },
            'ton_withdrawals': {
                'username': "TEXT DEFAULT ''",
            },
        }

        for table, columns in migrations.items():
            try:
                c.execute(f"PRAGMA table_info({table})")
                existing = {row[1] for row in c.fetchall()}
                for col, definition in columns.items():
                    if col not in existing:
                        try:
                            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
                            logger.info(f"✅ Migrated: {table}.{col}")
                        except Exception as e:
                            logger.warning(f"Migration {table}.{col}: {e}")
            except Exception as e:
                logger.warning(f"Migration check {table}: {e}")

        self.conn.commit()

    def _insert_defaults(self):
        """Insert default settings if not present"""
        defaults = {
            'bot_on': '1',
            'referral_reward': str(config.DEFAULT_REFERRAL_REWARD),
            'first_join_reward': str(config.DEFAULT_FIRST_JOIN_REWARD),
            'section_claim': '1',
            'section_games': '1',
            'section_miner': '1',
            'section_bank': '1',
            'section_shop': '1',
            'section_gift': '1',
            'section_stars': '1',
            'section_buy_dp': '1',
            'section_tasks': '1',
            'section_like': '1',
            'section_wheel': '1',
            'section_convert': '1',
            'section_leaderboard': '1',
            'section_ton_withdraw': '1',
            'section_factory': '1',
            'buy_dp_amount': str(config.BUY_DP_DEFAULT_AMOUNT),
            'buy_dp_price': str(config.BUY_DP_DEFAULT_PRICE),
            'stars_price': str(config.STARS_DP_COST),
            'gift_price': '100000',
        }
        c = self.conn.cursor()
        for key, value in defaults.items():
            c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)',
                      (key, value))
        self.conn.commit()

    # ══════════════════════════════════════════════
    #              SETTINGS (Key-Value)
    # ══════════════════════════════════════════════

    def get_setting(self, key, default=None):
        c = self.conn.cursor()
        c.execute('SELECT value FROM settings WHERE key = ?', (key,))
        row = c.fetchone()
        return row[0] if row else default

    def set_setting(self, key, value):
        c = self.conn.cursor()
        c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)',
                  (key, str(value)))
        self.conn.commit()

    def is_bot_on(self):
        return self.get_setting('bot_on', '1') == '1'

    def is_section_on(self, section):
        return self.get_setting(f'section_{section}', '1') == '1'

    def toggle_section(self, section):
        current = self.is_section_on(section)
        self.set_setting(f'section_{section}', '0' if current else '1')
        return not current

    # ══════════════════════════════════════════════
    #              USERS CRUD
    # ══════════════════════════════════════════════

    def get_user(self, uid):
        c = self.conn.cursor()
        c.execute('SELECT * FROM users WHERE user_id = ?', (uid,))
        return c.fetchone()

    def create_user(self, uid, username='', first_name='', ref_by=0):
        """Create user if not exists. Handle referral."""
        c = self.conn.cursor()
        c.execute('SELECT user_id FROM users WHERE user_id = ?', (uid,))
        if c.fetchone():
            return False  # Already exists

        c.execute('''INSERT INTO users
            (user_id, username, first_name, created_at, referred_by)
            VALUES (?, ?, ?, ?, ?)''',
            (uid, username or '', first_name or '', int(time.time()), ref_by))
        self.conn.commit()

        # Process referral
        if ref_by and ref_by != uid:
            ref_user = self.get_user(ref_by)
            if ref_user and not ref_user['is_banned']:
                ref_reward = int(self.get_setting('referral_reward',
                                                  config.DEFAULT_REFERRAL_REWARD))
                c.execute('''UPDATE users
                    SET referrals = referrals + 1,
                        balance = balance + ?,
                        total_earned = total_earned + ?
                    WHERE user_id = ?''', (ref_reward, ref_reward, ref_by))
                self.conn.commit()
        return True

    def update_username(self, uid, username, first_name):
        c = self.conn.cursor()
        c.execute('UPDATE users SET username = ?, first_name = ? WHERE user_id = ?',
                  (username or '', first_name or '', uid))
        self.conn.commit()

    def get_balance(self, uid):
        c = self.conn.cursor()
        c.execute('SELECT balance FROM users WHERE user_id = ?', (uid,))
        row = c.fetchone()
        return row[0] if row else 0

    def add_balance(self, uid, amount):
        if amount <= 0:
            return
        c = self.conn.cursor()
        c.execute('''UPDATE users
            SET balance = balance + ?,
                total_earned = total_earned + ?
            WHERE user_id = ?''', (amount, amount, uid))
        self.conn.commit()

    def deduct_balance(self, uid, amount):
        """Deduct balance. Returns True if successful."""
        if amount <= 0:
            return True
        c = self.conn.cursor()
        c.execute('''UPDATE users
            SET balance = balance - ?
            WHERE user_id = ? AND balance >= ?''', (amount, uid, amount))
        self.conn.commit()
        return c.rowcount > 0

    def set_balance(self, uid, amount):
        c = self.conn.cursor()
        c.execute('UPDATE users SET balance = ? WHERE user_id = ?', (amount, uid))
        self.conn.commit()

    def ban_user(self, uid, ban=True):
        c = self.conn.cursor()
        c.execute('UPDATE users SET is_banned = ? WHERE user_id = ?',
                  (1 if ban else 0, uid))
        self.conn.commit()

    def is_banned(self, uid):
        c = self.conn.cursor()
        c.execute('SELECT is_banned FROM users WHERE user_id = ?', (uid,))
        row = c.fetchone()
        return bool(row and row[0])

    def search_user(self, query):
        c = self.conn.cursor()
        try:
            uid = int(query)
            c.execute('SELECT * FROM users WHERE user_id = ?', (uid,))
        except (ValueError, TypeError):
            c.execute('SELECT * FROM users WHERE username LIKE ? OR first_name LIKE ?',
                      (f'%{query}%', f'%{query}%'))
        return c.fetchall()

    def get_all_users(self):
        c = self.conn.cursor()
        c.execute('SELECT user_id FROM users WHERE is_banned = 0')
        return [row[0] for row in c.fetchall()]

    def get_all_user_ids(self):
        """Including banned users"""
        c = self.conn.cursor()
        c.execute('SELECT user_id FROM users')
        return [row[0] for row in c.fetchall()]

    def get_user_count(self):
        c = self.conn.cursor()
        c.execute('SELECT COUNT(*) FROM users')
        return c.fetchone()[0]

    def get_active_user_count(self):
        c = self.conn.cursor()
        c.execute('SELECT COUNT(*) FROM users WHERE is_banned = 0')
        return c.fetchone()[0]

    def get_top_users(self, limit=10):
        c = self.conn.cursor()
        c.execute('''SELECT user_id, username, first_name, balance, total_earned
            FROM users
            WHERE is_banned = 0
            ORDER BY balance DESC
            LIMIT ?''', (limit,))
        return c.fetchall()

    # ══════════════════════════════════════════════
    #         LEVEL SYSTEM (20 Levels — NEW)
    # ══════════════════════════════════════════════

    def get_user_level(self, uid):
        """Calculate level based on current balance"""
        c = self.conn.cursor()
        c.execute('SELECT balance FROM users WHERE user_id = ?', (uid,))
        row = c.fetchone()
        if not row:
            return 1
        bal = row[0]
        level = 1
        for i, threshold in enumerate(config.LEVEL_THRESHOLDS):
            if bal >= threshold:
                level = i + 1
            else:
                break
        return min(level, 20)

    def check_level_up(self, uid):
        """Check and process level up. Returns (old_level, new_level) or None."""
        c = self.conn.cursor()
        c.execute('SELECT balance, level FROM users WHERE user_id = ?', (uid,))
        row = c.fetchone()
        if not row:
            return None

        bal = row[0]
        old_level = row[1] or 1
        new_level = 1

        for i, threshold in enumerate(config.LEVEL_THRESHOLDS):
            if bal >= threshold:
                new_level = i + 1
            else:
                break
        new_level = min(new_level, 20)

        if new_level > old_level:
            reward = config.get_level_reward(new_level)
            c.execute('''UPDATE users
                SET level = ?,
                    balance = balance + ?,
                    total_earned = total_earned + ?
                WHERE user_id = ?''', (new_level, reward, reward, uid))
            self.conn.commit()
            logger.info(f"🎉 User {uid} leveled up: {old_level} → {new_level} (+{reward} DP)")
            return old_level, new_level

        # Update level even if no change (in case balance dropped)
        if new_level != old_level:
            c.execute('UPDATE users SET level = ? WHERE user_id = ?', (new_level, uid))
            self.conn.commit()

        return None

    def get_level_info(self, uid):
        """Get detailed level info for user"""
        c = self.conn.cursor()
        c.execute('SELECT balance, level FROM users WHERE user_id = ?', (uid,))
        row = c.fetchone()
        if not row:
            return None

        bal = row[0]
        current_level = self.get_user_level(uid)
        next_level = min(current_level + 1, 20)

        if current_level >= 20:
            return {
                'level': 20,
                'max': True,
                'progress': 100,
                'next_threshold': 0,
                'remaining': 0,
            }

        cur_thresh = config.LEVEL_THRESHOLDS[current_level - 1]
        nxt_thresh = config.LEVEL_THRESHOLDS[current_level]
        progress = min(100, int((bal - cur_thresh) / max(1, nxt_thresh - cur_thresh) * 100))

        return {
            'level': current_level,
            'max': False,
            'progress': progress,
            'next_threshold': nxt_thresh,
            'remaining': max(0, nxt_thresh - bal),
            'next_reward': config.get_level_reward(next_level),
        }

    # ══════════════════════════════════════════════
    #              CLAIM (دریافت جایزه)
    # ══════════════════════════════════════════════

    def can_claim(self, uid):
        """Check if user can claim. Returns (can, remaining_seconds)."""
        c = self.conn.cursor()
        c.execute('SELECT last_claim FROM users WHERE user_id = ?', (uid,))
        row = c.fetchone()
        if not row or row[0] == 0:
            return True, 0

        now = int(time.time())
        elapsed = now - row[0]

        # Random cooldown between min and max
        import random
        cooldown = random.randint(config.CLAIM_COOLDOWN_MIN, config.CLAIM_COOLDOWN_MAX)

        if elapsed >= cooldown:
            return True, 0
        return False, cooldown - elapsed

    def do_claim(self, uid):
        """Process claim and return DP amount earned."""
        import random
        c = self.conn.cursor()
        c.execute('SELECT level FROM users WHERE user_id = ?', (uid,))
        row = c.fetchone()
        level = row[0] if row else 1

        bonus = (level - 1) * config.DP_PER_LEVEL
        amount = random.randint(
            config.BASE_CLAIM_MIN + bonus,
            config.BASE_CLAIM_MAX + bonus
        )

        now = int(time.time())
        c.execute('''UPDATE users
            SET balance = balance + ?,
                total_earned = total_earned + ?,
                last_claim = ?
            WHERE user_id = ?''', (amount, amount, now, uid))
        self.conn.commit()
        return amount# database.py — Dark Point Bot Database (قسمت 2/3)

    # ══════════════════════════════════════════════
    #         TRANSFER (انتقال DP — 10% fee)
    # ══════════════════════════════════════════════

    def can_transfer(self, uid):
        """Check if user can transfer (daily limit)."""
        c = self.conn.cursor()
        c.execute('SELECT transfer_count_today, transfer_reset_date FROM users WHERE user_id = ?',
                  (uid,))
        row = c.fetchone()
        if not row:
            return False

        today = date.today().isoformat()
        count = row[0] or 0
        reset_date = row[1] or ''

        if reset_date != today:
            c.execute('''UPDATE users
                SET transfer_count_today = 0,
                    transfer_reset_date = ?
                WHERE user_id = ?''', (today, uid))
            self.conn.commit()
            return True

        return count < config.TRANSFER_DAILY_LIMIT

    def do_transfer(self, from_uid, to_uid, amount):
        """
        Transfer DP between users.
        Fee = amount * TRANSFER_FEE (10%).
        Returns (success, message).
        """
        if amount <= 0:
            return False, "مبلغ نامعتبر"

        fee = int(amount * config.TRANSFER_FEE)
        total_cost = amount + fee

        # Deduct from sender (amount + fee)
        if not self.deduct_balance(from_uid, total_cost):
            return False, "موجودی کافی نیست"

        # Credit to receiver
        self.add_balance(to_uid, amount)

        # Increment daily counter
        c = self.conn.cursor()
        today = date.today().isoformat()
        c.execute('''UPDATE users
            SET transfer_count_today = transfer_count_today + 1,
                transfer_reset_date = ?
            WHERE user_id = ?''', (today, from_uid))
        self.conn.commit()

        return True, amount

    def get_transfer_remaining(self, uid):
        """Get remaining transfers today."""
        c = self.conn.cursor()
        c.execute('SELECT transfer_count_today, transfer_reset_date FROM users WHERE user_id = ?',
                  (uid,))
        row = c.fetchone()
        if not row:
            return config.TRANSFER_DAILY_LIMIT

        today = date.today().isoformat()
        if (row[1] or '') != today:
            return config.TRANSFER_DAILY_LIMIT

        return max(0, config.TRANSFER_DAILY_LIMIT - (row[0] or 0))

    # ══════════════════════════════════════════════
    #         MINER (ماینر دارکی — 5 levels)
    # ══════════════════════════════════════════════

    def get_miner(self, uid):
        c = self.conn.cursor()
        c.execute('SELECT * FROM miners WHERE user_id = ?', (uid,))
        return c.fetchone()

    def has_miner(self, uid):
        return self.get_miner(uid) is not None

    def buy_miner(self, uid):
        """Buy a new miner. Returns True if successful."""
        if self.has_miner(uid):
            return False  # Already has one

        if not self.deduct_balance(uid, config.MINER_BUY_COST):
            return False

        c = self.conn.cursor()
        c.execute('''INSERT INTO miners
            (user_id, level, currency, electricity_end, last_collect, total_ton, total_usdt)
            VALUES (?, 1, 'TON', 0, ?, 0.0, 0.0)''',
            (uid, int(time.time())))
        self.conn.commit()
        return True

    def upgrade_miner(self, uid):
        """Upgrade miner to next level. Returns (success, new_level_or_message)."""
        c = self.conn.cursor()
        c.execute('SELECT level FROM miners WHERE user_id = ?', (uid,))
        row = c.fetchone()

        if not row:
            return False, "ماینر ندارید"

        current_level = row[0]
        if current_level >= 5:
            return False, "حداکثر سطح"

        upgrade_cost = config.MINER_LEVELS[current_level]["upgrade"]
        if upgrade_cost <= 0:
            return False, "حداکثر سطح"

        if not self.deduct_balance(uid, upgrade_cost):
            return False, "موجودی کافی نیست"

        new_level = current_level + 1
        c.execute('UPDATE miners SET level = ? WHERE user_id = ?', (new_level, uid))
        self.conn.commit()
        return True, new_level

    def set_miner_currency(self, uid, currency):
        """Switch mining currency (TON or USDT)."""
        if currency not in ('TON', 'USDT'):
            return
        c = self.conn.cursor()
        c.execute('UPDATE miners SET currency = ? WHERE user_id = ?', (currency, uid))
        self.conn.commit()

    def buy_electricity(self, uid, hours=1):
        """Buy electricity for miner. Returns True if successful."""
        cost = config.MINER_ELECTRICITY_COST * hours
        if not self.deduct_balance(uid, cost):
            return False

        c = self.conn.cursor()
        c.execute('SELECT electricity_end FROM miners WHERE user_id = ?', (uid,))
        row = c.fetchone()
        if not row:
            return False

        now = int(time.time())
        current_end = row[0] or 0
        new_end = max(current_end, now) + (hours * 3600)

        c.execute('UPDATE miners SET electricity_end = ? WHERE user_id = ?', (new_end, uid))
        self.conn.commit()
        return True

    def get_electricity_remaining(self, uid):
        """Get remaining electricity in seconds."""
        c = self.conn.cursor()
        c.execute('SELECT electricity_end FROM miners WHERE user_id = ?', (uid,))
        row = c.fetchone()
        if not row:
            return 0
        return max(0, (row[0] or 0) - int(time.time()))

    def collect_miner(self, uid):
        """
        Collect mined TON/USDT.
        Returns dict with ton, usdt, hours — or None if no miner.
        """
        c = self.conn.cursor()
        c.execute('SELECT * FROM miners WHERE user_id = ?', (uid,))
        row = c.fetchone()
        if not row:
            return None

        now = int(time.time())
        last_collect = row['last_collect'] or now
        elec_end = row['electricity_end'] or 0

        # If no electricity, nothing to collect
        if elec_end <= now and last_collect >= elec_end:
            return {"ton": 0.0, "usdt": 0.0, "hours": 0.0}

        # Effective end = min(now, electricity_end)
        effective_end = min(now, elec_end) if elec_end > 0 else now
        hours = max(0, (effective_end - last_collect) / 3600.0)

        if hours < 0.001:
            return {"ton": 0.0, "usdt": 0.0, "hours": 0.0}

        rates = config.MINER_LEVELS[row['level']]
        ton_earned = 0.0
        usdt_earned = 0.0

        if row['currency'] == 'TON':
            ton_earned = round(rates['ton'] * hours, 8)
        else:
            usdt_earned = round(rates['usdt'] * hours, 6)

        c.execute('''UPDATE miners
            SET last_collect = ?,
                total_ton = total_ton + ?,
                total_usdt = total_usdt + ?
            WHERE user_id = ?''', (now, ton_earned, usdt_earned, uid))
        self.conn.commit()

        return {"ton": ton_earned, "usdt": usdt_earned, "hours": hours}

    def get_miner_stats(self):
        """Global miner statistics."""
        c = self.conn.cursor()
        c.execute('''SELECT
            COUNT(*),
            COALESCE(SUM(total_ton), 0),
            COALESCE(SUM(total_usdt), 0)
            FROM miners''')
        row = c.fetchone()
        return {
            "count": row[0],
            "ton": row[1],
            "usdt": row[2],
        }

    # ══════════════════════════════════════════════
    #         BANK (بانک — 3% per 48h)
    # ══════════════════════════════════════════════

    def bank_deposit(self, uid, amount):
        """Deposit DP into bank. Returns True if successful."""
        if amount <= 0:
            return False
        if not self.deduct_balance(uid, amount):
            return False

        c = self.conn.cursor()
        c.execute('''INSERT INTO bank_deposits
            (user_id, amount, deposit_time, withdrawn, interest_earned)
            VALUES (?, ?, ?, 0, 0)''',
            (uid, amount, int(time.time())))
        self.conn.commit()
        return True

    def bank_withdraw(self, uid, deposit_id):
        """
        Withdraw a bank deposit with interest.
        Returns (success, total_amount_or_message).
        """
        c = self.conn.cursor()
        c.execute('''SELECT * FROM bank_deposits
            WHERE id = ? AND user_id = ? AND withdrawn = 0''',
            (deposit_id, uid))
        row = c.fetchone()

        if not row:
            return False, "سپرده یافت نشد یا قبلاً برداشت شده"

        now = int(time.time())
        elapsed = now - row['deposit_time']

        if elapsed < config.BANK_LOCK_PERIOD:
            remaining = config.BANK_LOCK_PERIOD - elapsed
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60
            return False, f"⏳ {hours} ساعت و {minutes} دقیقه تا آزادسازی باقی مانده"

        # Calculate interest: 3% of deposit amount
        interest = int(row['amount'] * config.BANK_INTEREST_RATE)
        total = row['amount'] + interest

        c.execute('''UPDATE bank_deposits
            SET withdrawn = 1,
                interest_earned = ?
            WHERE id = ?''', (interest, deposit_id))
        self.conn.commit()

        self.add_balance(uid, total)
        return True, total

    def get_bank_deposits(self, uid):
        """Get all active (non-withdrawn) deposits for user."""
        c = self.conn.cursor()
        c.execute('''SELECT * FROM bank_deposits
            WHERE user_id = ? AND withdrawn = 0
            ORDER BY deposit_time DESC''', (uid,))
        return c.fetchall()

    def get_bank_deposit(self, deposit_id, uid):
        """Get a specific deposit."""
        c = self.conn.cursor()
        c.execute('''SELECT * FROM bank_deposits
            WHERE id = ? AND user_id = ?''', (deposit_id, uid))
        return c.fetchone()

    def get_total_bank_deposits(self):
        """Get total active deposits across all users."""
        c = self.conn.cursor()
        c.execute('''SELECT COUNT(*), COALESCE(SUM(amount), 0)
            FROM bank_deposits WHERE withdrawn = 0''')
        row = c.fetchone()
        return {"count": row[0], "total": row[1]}

    def get_deposit_interest(self, deposit):
        """Calculate pending interest for a deposit."""
        if deposit['withdrawn']:
            return deposit['interest_earned']
        return int(deposit['amount'] * config.BANK_INTEREST_RATE)

    def is_deposit_unlocked(self, deposit):
        """Check if deposit lock period has passed."""
        now = int(time.time())
        return (now - deposit['deposit_time']) >= config.BANK_LOCK_PERIOD

    def get_deposit_remaining_time(self, deposit):
        """Get remaining lock time in seconds."""
        now = int(time.time())
        remaining = config.BANK_LOCK_PERIOD - (now - deposit['deposit_time'])
        return max(0, remaining)

    # ══════════════════════════════════════════════
    #    TON WITHDRAWAL (برداشت TON — NEW)
    # ══════════════════════════════════════════════
    # Rate: 200,000,000 DP = 0.0005 TON
    # Min: 0.01 TON

    def create_ton_withdrawal(self, uid, username, wallet_address, ton_amount, dp_cost):
        """
        Create a new TON withdrawal order.
        DP should already be deducted before calling this.
        Returns tracking code.
        """
        code = f"TON-{uuid.uuid4().hex[:8].upper()}"
        c = self.conn.cursor()
        c.execute('''INSERT INTO ton_withdrawals
            (user_id, username, wallet_address, ton_amount, dp_cost,
             tracking_code, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)''',
            (uid, username or '', wallet_address, ton_amount, dp_cost,
             code, int(time.time())))
        self.conn.commit()
        return code

    def get_ton_withdrawal(self, tracking_code):
        """Get a specific withdrawal by tracking code."""
        c = self.conn.cursor()
        c.execute('SELECT * FROM ton_withdrawals WHERE tracking_code = ?',
                  (tracking_code,))
        return c.fetchone()

    def get_ton_withdrawal_by_id(self, wid):
        """Get a specific withdrawal by ID."""
        c = self.conn.cursor()
        c.execute('SELECT * FROM ton_withdrawals WHERE id = ?', (wid,))
        return c.fetchone()

    def update_ton_status(self, tracking_code, status):
        """
        Update withdrawal status.
        Valid statuses: 'pending', 'approved', 'rejected'
        """
        if status not in ('pending', 'approved', 'rejected'):
            return False
        c = self.conn.cursor()
        c.execute('UPDATE ton_withdrawals SET status = ? WHERE tracking_code = ?',
                  (status, tracking_code))
        self.conn.commit()
        return c.rowcount > 0

    def get_pending_ton(self):
        """Get all pending TON withdrawals."""
        c = self.conn.cursor()
        c.execute('''SELECT * FROM ton_withdrawals
            WHERE status = 'pending'
            ORDER BY created_at DESC''')
        return c.fetchall()

    def get_user_ton_history(self, uid, limit=10):
        """Get user's TON withdrawal history."""
        c = self.conn.cursor()
        c.execute('''SELECT * FROM ton_withdrawals
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?''', (uid, limit))
        return c.fetchall()

    def get_ton_stats(self):
        """Get global TON withdrawal statistics."""
        c = self.conn.cursor()

        # Approved
        c.execute('''SELECT COUNT(*),
            COALESCE(SUM(ton_amount), 0),
            COALESCE(SUM(dp_cost), 0)
            FROM ton_withdrawals WHERE status = 'approved' ''')
        approved = c.fetchone()

        # Pending
        c.execute('''SELECT COUNT(*) FROM ton_withdrawals
            WHERE status = 'pending' ''')
        pending = c.fetchone()[0]

        # Rejected
        c.execute('''SELECT COUNT(*) FROM ton_withdrawals
            WHERE status = 'rejected' ''')
        rejected = c.fetchone()[0]

        # Total
        c.execute('SELECT COUNT(*) FROM ton_withdrawals')
        total = c.fetchone()[0]

        return {
            "ok": approved[0],
            "ton": approved[1],
            "dp": approved[2],
            "pending": pending,
            "rejected": rejected,
            "total": total,
        }

    def get_ton_withdrawal_count(self, uid):
        """Get total withdrawal count for a user."""
        c = self.conn.cursor()
        c.execute('SELECT COUNT(*) FROM ton_withdrawals WHERE user_id = ?', (uid,))
        return c.fetchone()[0]

    def get_ton_withdrawal_total(self, uid):
        """Get total TON withdrawn by a user (approved only)."""
        c = self.conn.cursor()
        c.execute('''SELECT COALESCE(SUM(ton_amount), 0)
            FROM ton_withdrawals
            WHERE user_id = ? AND status = 'approved' ''', (uid,))
        return c.fetchone()[0]# database.py — Dark Point Bot Database (قسمت 3/3 — FINAL)

    # ══════════════════════════════════════════════
    #            SHOP (فروشگاه)
    # ══════════════════════════════════════════════

    def add_shop_item(self, name, price, stock=-1, media_type='text', media_content=''):
        """Add a new shop item. Returns item ID."""
        c = self.conn.cursor()
        c.execute('''INSERT INTO shop_items
            (name, price, stock, media_type, media_content, is_active)
            VALUES (?, ?, ?, ?, ?, 1)''',
            (name, price, stock, media_type, media_content))
        self.conn.commit()
        return c.lastrowid

    def get_shop_items(self, active_only=True):
        """Get shop items."""
        c = self.conn.cursor()
        if active_only:
            c.execute('SELECT * FROM shop_items WHERE is_active = 1 ORDER BY id ASC')
        else:
            c.execute('SELECT * FROM shop_items ORDER BY id ASC')
        return c.fetchall()

    def get_shop_item(self, item_id):
        """Get a single shop item by ID."""
        c = self.conn.cursor()
        c.execute('SELECT * FROM shop_items WHERE id = ?', (item_id,))
        return c.fetchone()

    def buy_shop_item(self, uid, item_id):
        """
        Buy a shop item.
        Returns (success, item_row_or_None).
        """
        c = self.conn.cursor()
        c.execute('SELECT * FROM shop_items WHERE id = ? AND is_active = 1', (item_id,))
        item = c.fetchone()

        if not item:
            return False, None

        if item['stock'] == 0:
            return False, None  # Out of stock

        if not self.deduct_balance(uid, item['price']):
            return False, None  # Insufficient balance

        # Decrease stock (if not unlimited)
        if item['stock'] > 0:
            c.execute('UPDATE shop_items SET stock = stock - 1 WHERE id = ?', (item_id,))

        # Record order
        c.execute('''INSERT INTO shop_orders (user_id, item_id, created_at)
            VALUES (?, ?, ?)''', (uid, item_id, int(time.time())))
        self.conn.commit()
        return True, item

    def deactivate_shop_item(self, item_id):
        c = self.conn.cursor()
        c.execute('UPDATE shop_items SET is_active = 0 WHERE id = ?', (item_id,))
        self.conn.commit()

    def update_shop_stock(self, item_id, stock):
        c = self.conn.cursor()
        c.execute('UPDATE shop_items SET stock = ? WHERE id = ?', (stock, item_id))
        self.conn.commit()

    def get_shop_orders(self, limit=20):
        """Get recent shop orders."""
        c = self.conn.cursor()
        c.execute('''SELECT so.*, si.name as item_name, si.price
            FROM shop_orders so
            LEFT JOIN shop_items si ON so.item_id = si.id
            ORDER BY so.created_at DESC
            LIMIT ?''', (limit,))
        return c.fetchall()

    # ══════════════════════════════════════════════
    #            TASKS (تسک‌ها)
    # ══════════════════════════════════════════════

    def add_task(self, task_type, title, reward, data='', capacity=-1):
        """Add a new task. Returns task ID."""
        c = self.conn.cursor()
        c.execute('''INSERT INTO tasks
            (type, title, reward, data, capacity, completed_count, is_active)
            VALUES (?, ?, ?, ?, ?, 0, 1)''',
            (task_type, title, reward, data, capacity))
        self.conn.commit()
        return c.lastrowid

    def get_active_tasks(self):
        """Get all active tasks with available capacity."""
        c = self.conn.cursor()
        c.execute('''SELECT * FROM tasks
            WHERE is_active = 1
              AND (capacity = -1 OR completed_count < capacity)
            ORDER BY id ASC''')
        return c.fetchall()

    def get_all_tasks(self):
        """Get all tasks including inactive."""
        c = self.conn.cursor()
        c.execute('SELECT * FROM tasks ORDER BY id DESC')
        return c.fetchall()

    def get_task(self, task_id):
        c = self.conn.cursor()
        c.execute('SELECT * FROM tasks WHERE id = ?', (task_id,))
        return c.fetchone()

    def complete_task(self, uid, task_id):
        """
        Mark task as completed for user and credit reward.
        Returns True if successful, False if already completed.
        """
        c = self.conn.cursor()

        # Check if already done
        c.execute('SELECT 1 FROM user_tasks WHERE user_id = ? AND task_id = ?',
                  (uid, task_id))
        if c.fetchone():
            return False

        # Get reward
        c.execute('SELECT reward, capacity, completed_count FROM tasks WHERE id = ?',
                  (task_id,))
        task = c.fetchone()
        if not task:
            return False

        # Check capacity
        if task['capacity'] != -1 and task['completed_count'] >= task['capacity']:
            return False

        # Record completion
        c.execute('''INSERT INTO user_tasks (user_id, task_id, status, created_at)
            VALUES (?, ?, 'completed', ?)''', (uid, task_id, int(time.time())))

        # Increment counter
        c.execute('UPDATE tasks SET completed_count = completed_count + 1 WHERE id = ?',
                  (task_id,))
        self.conn.commit()

        # Credit reward
        self.add_balance(uid, task['reward'])
        return True

    def get_user_task_status(self, uid, task_id):
        """Get user's status for a specific task."""
        c = self.conn.cursor()
        c.execute('SELECT status FROM user_tasks WHERE user_id = ? AND task_id = ?',
                  (uid, task_id))
        row = c.fetchone()
        return row[0] if row else None

    def get_pending_missions(self):
        """Get all pending mission submissions for admin review."""
        c = self.conn.cursor()
        c.execute('''SELECT ut.user_id, ut.task_id, t.title, t.reward, ut.created_at
            FROM user_tasks ut
            JOIN tasks t ON ut.task_id = t.id
            WHERE ut.status = 'pending'
            ORDER BY ut.created_at DESC''')
        return c.fetchall()

    def approve_mission(self, uid, task_id):
        """Admin approves a mission submission."""
        c = self.conn.cursor()
        c.execute('''UPDATE user_tasks
            SET status = 'completed'
            WHERE user_id = ? AND task_id = ? AND status = 'pending' ''',
            (uid, task_id))

        if c.rowcount > 0:
            c.execute('SELECT reward FROM tasks WHERE id = ?', (task_id,))
            task = c.fetchone()
            if task:
                self.add_balance(uid, task['reward'])
            c.execute('UPDATE tasks SET completed_count = completed_count + 1 WHERE id = ?',
                      (task_id,))
            self.conn.commit()
            return True
        self.conn.commit()
        return False

    def reject_mission(self, uid, task_id):
        """Admin rejects a mission submission."""
        c = self.conn.cursor()
        c.execute('DELETE FROM user_tasks WHERE user_id = ? AND task_id = ?',
                  (uid, task_id))
        self.conn.commit()
        return c.rowcount > 0

    def deactivate_task(self, task_id):
        c = self.conn.cursor()
        c.execute('UPDATE tasks SET is_active = 0 WHERE id = ?', (task_id,))
        self.conn.commit()

    # ══════════════════════════════════════════════
    #            GIFT PLANS (هدایا)
    # ══════════════════════════════════════════════

    def add_gift_plan(self, name, price):
        """Add a new gift plan. Returns plan ID."""
        c = self.conn.cursor()
        c.execute('''INSERT INTO gift_plans (name, price, is_active)
            VALUES (?, ?, 1)''', (name, price))
        self.conn.commit()
        return c.lastrowid

    def get_gift_plans(self, active_only=True):
        c = self.conn.cursor()
        if active_only:
            c.execute('SELECT * FROM gift_plans WHERE is_active = 1 ORDER BY price ASC')
        else:
            c.execute('SELECT * FROM gift_plans ORDER BY id ASC')
        return c.fetchall()

    def get_gift_plan(self, plan_id):
        c = self.conn.cursor()
        c.execute('SELECT * FROM gift_plans WHERE id = ?', (plan_id,))
        return c.fetchone()

    def deactivate_gift_plan(self, plan_id):
        c = self.conn.cursor()
        c.execute('UPDATE gift_plans SET is_active = 0 WHERE id = ?', (plan_id,))
        self.conn.commit()

    # ══════════════════════════════════════════════
    #        FORCE JOIN CHANNELS (فورس جوین)
    # ══════════════════════════════════════════════

    def add_force_channel(self, channel_id, channel_username):
        """Add a force-join channel."""
        c = self.conn.cursor()
        # Check if already exists
        c.execute('SELECT id FROM force_join_channels WHERE channel_id = ?', (channel_id,))
        existing = c.fetchone()
        if existing:
            c.execute('''UPDATE force_join_channels
                SET channel_username = ?, is_active = 1
                WHERE channel_id = ?''', (channel_username, channel_id))
        else:
            c.execute('''INSERT INTO force_join_channels
                (channel_id, channel_username, is_active)
                VALUES (?, ?, 1)''', (channel_id, channel_username))
        self.conn.commit()

    def get_force_channels(self):
        """Get all active force-join channels."""
        c = self.conn.cursor()
        c.execute('SELECT * FROM force_join_channels WHERE is_active = 1')
        return c.fetchall()

    def remove_force_channel(self, channel_id):
        """Deactivate a force-join channel."""
        c = self.conn.cursor()
        c.execute('UPDATE force_join_channels SET is_active = 0 WHERE channel_id = ?',
                  (str(channel_id),))
        self.conn.commit()
        return c.rowcount > 0

    def get_all_force_channels(self):
        """Get all channels including inactive."""
        c = self.conn.cursor()
        c.execute('SELECT * FROM force_join_channels ORDER BY id ASC')
        return c.fetchall()

    # ══════════════════════════════════════════════
    #        ADMIN GROUPS (گروه‌های ادمین)
    # ══════════════════════════════════════════════

    def add_admin_group(self, chat_id, title=''):
        """Register or update a group."""
        c = self.conn.cursor()
        c.execute('''INSERT OR REPLACE INTO admin_groups
            (chat_id, title, added_at)
            VALUES (?, ?, ?)''',
            (chat_id, title or '', int(time.time())))
        self.conn.commit()

    def get_admin_groups(self):
        """Get all registered groups."""
        c = self.conn.cursor()
        c.execute('SELECT * FROM admin_groups ORDER BY added_at DESC')
        return c.fetchall()

    def remove_admin_group(self, chat_id):
        """Remove a group from tracking."""
        c = self.conn.cursor()
        c.execute('DELETE FROM admin_groups WHERE chat_id = ?', (chat_id,))
        self.conn.commit()
        return c.rowcount > 0

    def get_admin_group_count(self):
        c = self.conn.cursor()
        c.execute('SELECT COUNT(*) FROM admin_groups')
        return c.fetchone()[0]

    # ══════════════════════════════════════════════
    #        PANEL PLANS (پلن‌های پنل)
    # ══════════════════════════════════════════════

    def add_panel_plan(self, name, price):
        """Add a new panel plan. Returns plan ID."""
        c = self.conn.cursor()
        c.execute('''INSERT INTO panel_plans (name, price, is_active)
            VALUES (?, ?, 1)''', (name, price))
        self.conn.commit()
        return c.lastrowid

    def get_panel_plans(self, active_only=True):
        c = self.conn.cursor()
        if active_only:
            c.execute('SELECT * FROM panel_plans WHERE is_active = 1 ORDER BY price ASC')
        else:
            c.execute('SELECT * FROM panel_plans ORDER BY id ASC')
        return c.fetchall()

    def get_panel_plan(self, plan_id):
        c = self.conn.cursor()
        c.execute('SELECT * FROM panel_plans WHERE id = ?', (plan_id,))
        return c.fetchone()

    def deactivate_panel_plan(self, plan_id):
        c = self.conn.cursor()
        c.execute('UPDATE panel_plans SET is_active = 0 WHERE id = ?', (plan_id,))
        self.conn.commit()

    def set_user_panel(self, uid, plan_name):
        """Mark user as having purchased a panel plan."""
        c = self.conn.cursor()
        c.execute('''UPDATE users
            SET panel_purchased = 1, panel_plan = ?
            WHERE user_id = ?''', (plan_name, uid))
        self.conn.commit()

    # ══════════════════════════════════════════════
    #        GLOBAL STATISTICS (آمار کلی)
    # ══════════════════════════════════════════════

    def get_total_stats(self):
        """Get overall bot statistics."""
        c = self.conn.cursor()

        c.execute('''SELECT
            COUNT(*),
            COALESCE(SUM(balance), 0),
            COALESCE(SUM(referrals), 0),
            COALESCE(SUM(total_earned), 0)
            FROM users''')
        users = c.fetchone()

        c.execute('SELECT COUNT(*) FROM users WHERE is_banned = 1')
        banned = c.fetchone()[0]

        c.execute('SELECT COUNT(*) FROM users WHERE created_at > ?',
                  (int(time.time()) - 86400,))
        today_users = c.fetchone()[0]

        c.execute('SELECT COUNT(*) FROM users WHERE created_at > ?',
                  (int(time.time()) - 86400 * 7,))
        week_users = c.fetchone()[0]

        return {
            "users": users[0],
            "balance": users[1],
            "refs": users[2],
            "total_earned": users[3],
            "banned": banned,
            "today": today_users,
            "week": week_users,
        }

    def get_currency_stats(self):
        """Get currency distribution stats."""
        c = self.conn.cursor()

        c.execute('SELECT COUNT(*), COALESCE(SUM(balance), 0) FROM users WHERE balance > 0')
        active = c.fetchone()

        c.execute('SELECT MAX(balance) FROM users')
        max_bal = c.fetchone()[0] or 0

        c.execute('SELECT AVG(balance) FROM users WHERE balance > 0')
        avg_bal = c.fetchone()[0] or 0

        c.execute('''SELECT user_id, username, balance
            FROM users ORDER BY balance DESC LIMIT 1''')
        top = c.fetchone()

        return {
            "active_users": active[0],
            "total_dp": active[1],
            "max_balance": max_bal,
            "avg_balance": int(avg_bal),
            "top_user": top,
        }

    def get_comprehensive_stats(self):
        """Get all stats in one call for admin dashboard."""
        return {
            "total": self.get_total_stats(),
            "miners": self.get_miner_stats(),
            "ton": self.get_ton_stats(),
            "bank": self.get_total_bank_deposits(),
            "currency": self.get_currency_stats(),
            "groups": self.get_admin_group_count(),
        }

    # ══════════════════════════════════════════════
    #        UTILITY METHODS
    # ══════════════════════════════════════════════

    def reset_daily_counters(self):
        """Reset daily counters for all users (called by job queue)."""
        c = self.conn.cursor()
        today = date.today().isoformat()
        c.execute('''UPDATE users
            SET transfer_count_today = 0
            WHERE transfer_reset_date != ?''', (today,))
        c.execute('''UPDATE users
            SET wheel_used_today = 0
            WHERE wheel_reset_date != ?''', (today,))
        self.conn.commit()

    def get_db_size(self):
        """Get database file size in bytes."""
        import os
        try:
            return os.path.getsize(config.DB_PATH)
        except OSError:
            return 0

    def vacuum(self):
        """Optimize database."""
        self.conn.execute("VACUUM")

    def close(self):
        """Close database connection."""
        try:
            self.conn.close()
        except Exception:
            pass
