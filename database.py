# database.py - Database Manager for Dark Point Bot

import sqlite3
import time
import random
import string
import threading

class Database:
    def __init__(self, db_name="darkpoint.db"):
        self.db_name = db_name
        self.lock = threading.Lock()
        self.init_db()

    def get_conn(self):
        conn = sqlite3.connect(self.db_name, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        conn = self.get_conn()
        c = conn.cursor()

        # Users table
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            dark_points INTEGER DEFAULT 0,
            total_earned INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            referrer_id INTEGER DEFAULT 0,
            referral_count INTEGER DEFAULT 0,
            last_claim_time REAL DEFAULT 0,
            last_cooldown INTEGER DEFAULT 0,
            joined_channels INTEGER DEFAULT 0,
            captcha_verified INTEGER DEFAULT 0,
            created_at REAL DEFAULT 0,
            self_active INTEGER DEFAULT 0,
            self_activated_at REAL DEFAULT 0,
            like_challenge_active INTEGER DEFAULT 0,
            like_challenge_until REAL DEFAULT 0,
            factory_level INTEGER DEFAULT 0,
            factory_active INTEGER DEFAULT 0,
            factory_last_collect REAL DEFAULT 0,
            factory_last_maintenance REAL DEFAULT 0,
            bank_account INTEGER DEFAULT 0,
            bank_card TEXT DEFAULT '',
            bank_balance INTEGER DEFAULT 0,
            bank_deposit_time REAL DEFAULT 0,
            bank_interest_collected INTEGER DEFAULT 0,
            bought_dp INTEGER DEFAULT 0
        )''')

        # Games table
        c.execute('''CREATE TABLE IF NOT EXISTS games (
            game_id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER,
            amount INTEGER,
            status TEXT DEFAULT 'waiting',
            joiner_id INTEGER DEFAULT 0,
            winner_id INTEGER DEFAULT 0,
            loser_id INTEGER DEFAULT 0,
            chat_id INTEGER,
            message_id INTEGER,
            created_at REAL DEFAULT 0
        )''')

        # Transfers table
        c.execute('''CREATE TABLE IF NOT EXISTS transfers (
            transfer_id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_id INTEGER,
            to_id INTEGER,
            amount INTEGER,
            fee INTEGER,
            created_at REAL DEFAULT 0
        )''')

        # Panel orders
        c.execute('''CREATE TABLE IF NOT EXISTS panel_orders (
            order_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            plan_name TEXT,
            price INTEGER,
            status TEXT DEFAULT 'pending',
            config_data TEXT DEFAULT '',
            created_at REAL DEFAULT 0
        )''')

        # Gift orders
        c.execute('''CREATE TABLE IF NOT EXISTS gift_orders (
            order_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            gift_type TEXT,
            price INTEGER,
            status TEXT DEFAULT 'pending',
            created_at REAL DEFAULT 0
        )''')

        # Stars withdrawal orders
        c.execute('''CREATE TABLE IF NOT EXISTS stars_orders (
            order_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            target_id TEXT,
            target_type TEXT DEFAULT 'self',
            amount INTEGER,
            dp_cost INTEGER,
            status TEXT DEFAULT 'pending',
            created_at REAL DEFAULT 0
        )''')

        # Admin settings
        c.execute('''CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )''')

        # Custom panels
        c.execute('''CREATE TABLE IF NOT EXISTS custom_panels (
            panel_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            description TEXT,
            price INTEGER,
            data_limit TEXT,
            active INTEGER DEFAULT 1,
            created_at REAL DEFAULT 0
        )''')

        # Checks (personal checks by admin)
        c.execute('''CREATE TABLE IF NOT EXISTS checks (
            check_id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            amount INTEGER,
            claimed INTEGER DEFAULT 0,
            claimed_by INTEGER DEFAULT 0,
            created_at REAL DEFAULT 0
        )''')

        # Bank cards registry
        c.execute('''CREATE TABLE IF NOT EXISTS bank_cards (
            card_number TEXT PRIMARY KEY,
            user_id INTEGER
        )''')

        # Leaderboard cache
        c.execute('''CREATE TABLE IF NOT EXISTS groups (
            chat_id INTEGER PRIMARY KEY,
            title TEXT DEFAULT '',
            member_count INTEGER DEFAULT 0,
            bot_active INTEGER DEFAULT 1,
            added_at REAL DEFAULT 0
        )''')

        # Initialize default settings
        default_settings = {
            'gift_teddy_price': '750000',
            'gift_section_active': '1',
            'stars_section_active': '1',
            'stars_price': '1000000',
            'buy_dp_active': '1',
            'buy_dp_amount': '500000',
            'buy_dp_price_toman': '50000',
        }

        for key, value in default_settings.items():
            c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))

        conn.commit()
        conn.close()    # ============ USER METHODS ============

    def get_user(self, user_id):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = c.fetchone()
        conn.close()
        return user

    def create_user(self, user_id, username="", first_name="", referrer_id=0):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("""INSERT OR IGNORE INTO users 
            (user_id, username, first_name, referrer_id, created_at) 
            VALUES (?, ?, ?, ?, ?)""",
            (user_id, username, first_name, referrer_id, time.time()))
        conn.commit()
        conn.close()

    def update_user(self, user_id, **kwargs):
        conn = self.get_conn()
        c = conn.cursor()
        sets = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        vals = list(kwargs.values()) + [user_id]
        c.execute(f"UPDATE users SET {sets} WHERE user_id = ?", vals)
        conn.commit()
        conn.close()

    def add_dark_points(self, user_id, amount):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("UPDATE users SET dark_points = dark_points + ?, total_earned = total_earned + ? WHERE user_id = ?",
                      (amount, max(amount, 0), user_id))
            conn.commit()
            conn.close()

    def remove_dark_points(self, user_id, amount):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("UPDATE users SET dark_points = dark_points - ? WHERE user_id = ? AND dark_points >= ?",
                      (amount, user_id, amount))
            affected = c.rowcount
            conn.commit()
            conn.close()
            return affected > 0

    def get_balance(self, user_id):
        user = self.get_user(user_id)
        if user:
            return user['dark_points']
        return 0

    def get_level(self, user_id):
        user = self.get_user(user_id)
        if user:
            return user['level']
        return 1

    def check_and_update_level(self, user_id):
        from config import LEVEL_REQUIREMENTS, LEVEL_REWARDS
        user = self.get_user(user_id)
        if not user:
            return None, None

        current_level = user['level']
        total_earned = user['total_earned']
        new_level = current_level

        for lvl in range(20, 0, -1):
            if total_earned >= LEVEL_REQUIREMENTS.get(lvl, float('inf')):
                new_level = lvl
                break

        if new_level > current_level:
            reward = 0
            for lvl in range(current_level + 1, new_level + 1):
                reward += LEVEL_REWARDS.get(lvl, 0)

            self.update_user(user_id, level=new_level)
            if reward > 0:
                self.add_dark_points(user_id, reward)
            return new_level, reward
        return None, None

    def get_cooldown_remaining(self, user_id):
        user = self.get_user(user_id)
        if not user:
            return 0
        elapsed = time.time() - user['last_claim_time']
        cooldown = user['last_cooldown']
        remaining = cooldown - elapsed
        return max(0, remaining)

    def set_claim(self, user_id, cooldown):
        self.update_user(user_id, last_claim_time=time.time(), last_cooldown=cooldown)

    # ============ REFERRAL METHODS ============

    def add_referral(self, referrer_id):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id = ?", (referrer_id,))
        conn.commit()
        conn.close()

    def get_referral_count(self, user_id):
        user = self.get_user(user_id)
        if user:
            return user['referral_count']
        return 0

    # ============ LEADERBOARD ============

    def get_leaderboard(self, limit=100):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT user_id, username, first_name, dark_points, level FROM users ORDER BY dark_points DESC LIMIT ?", (limit,))
        rows = c.fetchall()
        conn.close()
        return rows

    # ============ GAME METHODS ============

    def create_game(self, creator_id, amount, chat_id, message_id):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("""INSERT INTO games (creator_id, amount, chat_id, message_id, created_at) 
                     VALUES (?, ?, ?, ?, ?)""",
                  (creator_id, amount, chat_id, message_id, time.time()))
        game_id = c.lastrowid
        conn.commit()
        conn.close()
        return game_id

    def get_game(self, game_id):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM games WHERE game_id = ?", (game_id,))
        game = c.fetchone()
        conn.close()
        return game

    def join_game(self, game_id, joiner_id):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("UPDATE games SET joiner_id = ?, status = 'playing' WHERE game_id = ? AND status = 'waiting'",
                  (joiner_id, game_id))
        affected = c.rowcount
        conn.commit()
        conn.close()
        return affected > 0

    def finish_game(self, game_id, winner_id, loser_id):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("UPDATE games SET winner_id = ?, loser_id = ?, status = 'finished' WHERE game_id = ?",
                  (winner_id, loser_id, game_id))
        conn.commit()
        conn.close()

    def cancel_game(self, game_id):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("UPDATE games SET status = 'cancelled' WHERE game_id = ?", (game_id,))
        conn.commit()
        conn.close()

    # ============ TRANSFER METHODS ============

    def record_transfer(self, from_id, to_id, amount, fee):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("""INSERT INTO transfers (from_id, to_id, amount, fee, created_at) 
                     VALUES (?, ?, ?, ?, ?)""",
                  (from_id, to_id, amount, fee, time.time()))
        conn.commit()
        conn.close()    # ============ SETTINGS METHODS ============

    def get_setting(self, key, default=""):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = c.fetchone()
        conn.close()
        if row:
            return row['value']
        return default

    def set_setting(self, key, value):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
        conn.commit()
        conn.close()

    # ============ CUSTOM PANELS ============

    def add_custom_panel(self, name, description, price, data_limit):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("""INSERT INTO custom_panels (name, description, price, data_limit, created_at) 
                     VALUES (?, ?, ?, ?, ?)""",
                  (name, description, price, data_limit, time.time()))
        panel_id = c.lastrowid
        conn.commit()
        conn.close()
        return panel_id

    def get_custom_panels(self):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM custom_panels WHERE active = 1 ORDER BY price ASC")
        rows = c.fetchall()
        conn.close()
        return rows

    def delete_custom_panel(self, panel_id):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("UPDATE custom_panels SET active = 0 WHERE panel_id = ?", (panel_id,))
        conn.commit()
        conn.close()

    # ============ GIFT ORDERS ============

    def create_gift_order(self, user_id, gift_type, price):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("""INSERT INTO gift_orders (user_id, gift_type, price, created_at) 
                     VALUES (?, ?, ?, ?)""",
                  (user_id, gift_type, price, time.time()))
        order_id = c.lastrowid
        conn.commit()
        conn.close()
        return order_id

    # ============ STARS ORDERS ============

    def create_stars_order(self, user_id, target_id, target_type, amount, dp_cost):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("""INSERT INTO stars_orders (user_id, target_id, target_type, amount, dp_cost, created_at) 
                     VALUES (?, ?, ?, ?, ?, ?)""",
                  (user_id, target_id, target_type, amount, dp_cost, time.time()))
        order_id = c.lastrowid
        conn.commit()
        conn.close()
        return order_id

    # ============ PANEL ORDERS ============

    def create_panel_order(self, user_id, plan_name, price, config_data=""):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("""INSERT INTO panel_orders (user_id, plan_name, price, config_data, created_at) 
                     VALUES (?, ?, ?, ?, ?)""",
                  (user_id, plan_name, price, config_data, time.time()))
        order_id = c.lastrowid
        conn.commit()
        conn.close()
        return order_id

    # ============ CHECK METHODS ============

    def create_check(self, amount):
        code = ''.join(random.choices(string.ascii_lowercase * 4 + string.digits, k=16))
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("INSERT INTO checks (code, amount, created_at) VALUES (?, ?, ?)",
                  (code, amount, time.time()))
        conn.commit()
        conn.close()
        return code

    def claim_check(self, code, user_id):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM checks WHERE code = ? AND claimed = 0", (code,))
        check = c.fetchone()
        if check:
            c.execute("UPDATE checks SET claimed = 1, claimed_by = ? WHERE code = ?",
                      (user_id, code))
            conn.commit()
            conn.close()
            return check['amount']
        conn.close()
        return None

    # ============ BANK METHODS ============

    def open_bank_account(self, user_id, card_number):
        conn = self.get_conn()
        c = conn.cursor()
        # Check if card exists
        c.execute("SELECT * FROM bank_cards WHERE card_number = ?", (card_number,))
        if c.fetchone():
            conn.close()
            return False
        c.execute("INSERT INTO bank_cards (card_number, user_id) VALUES (?, ?)", (card_number, user_id))
        c.execute("UPDATE users SET bank_account = 1, bank_card = ? WHERE user_id = ?", (card_number, user_id))
        conn.commit()
        conn.close()
        return True

    def bank_deposit(self, user_id, amount):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("SELECT dark_points FROM users WHERE user_id = ?", (user_id,))
            user = c.fetchone()
            if not user or user['dark_points'] < amount:
                conn.close()
                return False
            c.execute("""UPDATE users SET 
                dark_points = dark_points - ?,
                bank_balance = bank_balance + ?,
                bank_deposit_time = ?,
                bank_interest_collected = 0
                WHERE user_id = ?""",
                (amount, amount, time.time(), user_id))
            conn.commit()
            conn.close()
            return True

    def bank_withdraw(self, user_id):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("SELECT bank_balance, bank_deposit_time, bank_interest_collected FROM users WHERE user_id = ?", (user_id,))
            user = c.fetchone()
            if not user or user['bank_balance'] <= 0:
                conn.close()
                return 0, 0

            balance = user['bank_balance']
            deposit_time = user['bank_deposit_time']
            elapsed = time.time() - deposit_time

            interest = 0
            if elapsed >= 86400 and not user['bank_interest_collected']:
                interest = int(balance * 0.10)

            total = balance + interest
            c.execute("""UPDATE users SET 
                dark_points = dark_points + ?,
                bank_balance = 0,
                bank_deposit_time = 0,
                bank_interest_collected = 0
                WHERE user_id = ?""",
                (total, user_id))
            conn.commit()
            conn.close()
            return balance, interest

    def get_total_bank_balance(self):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT COALESCE(SUM(bank_balance), 0) as total FROM users WHERE bank_balance > 0")
        row = c.fetchone()
        conn.close()
        return row['total'] if row else 0

    def generate_bank_card(self):
        return ''.join(random.choices(string.digits, k=13))

    def card_exists(self, card_number):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM bank_cards WHERE card_number = ?", (card_number,))
        exists = c.fetchone() is not None
        conn.close()
        return exists

    # ============ FACTORY METHODS ============

    def open_factory(self, user_id):
        self.update_user(user_id,
            factory_level=1,
            factory_active=1,
            factory_last_collect=time.time(),
            factory_last_maintenance=time.time()
        )

    def upgrade_factory(self, user_id):
        user = self.get_user(user_id)
        if not user or user['factory_level'] >= 5:
            return False
        new_level = user['factory_level'] + 1
        self.update_user(user_id, factory_level=new_level)
        return True

    def collect_factory(self, user_id):
        from config import FACTORY_LEVELS
        user = self.get_user(user_id)
        if not user or not user['factory_active'] or user['factory_level'] == 0:
            return 0

        level = user['factory_level']
        mine_per_min = FACTORY_LEVELS[level]['mine_per_min']
        elapsed_min = (time.time() - user['factory_last_collect']) / 60.0
        mined = int(elapsed_min * mine_per_min)

        if mined > 0:
            self.add_dark_points(user_id, mined)
            self.update_user(user_id, factory_last_collect=time.time())

        return mined

    def factory_maintenance_due(self, user_id):
        from config import FACTORY_HOURLY_MAINTENANCE
        user = self.get_user(user_id)
        if not user or not user['factory_active']:
            return 0

        elapsed_hours = (time.time() - user['factory_last_maintenance']) / 3600.0
        hours_due = int(elapsed_hours)
        cost = hours_due * FACTORY_HOURLY_MAINTENANCE

        if cost > 0:
            if self.remove_dark_points(user_id, cost):
                self.update_user(user_id, factory_last_maintenance=time.time())
                return cost
            else:
                self.update_user(user_id, factory_active=0)
                return -1  # Factory shut down
        return 0

    # ============ GROUP METHODS ============

    def add_group(self, chat_id, title, member_count):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("""INSERT OR REPLACE INTO groups (chat_id, title, member_count, added_at) 
                     VALUES (?, ?, ?, ?)""",
                  (chat_id, title, member_count, time.time()))
        conn.commit()
        conn.close()

    def get_group(self, chat_id):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM groups WHERE chat_id = ?", (chat_id,))
        group = c.fetchone()
        conn.close()
        return group

    # ============ SELF BOT ============

    def activate_self(self, user_id):
        self.update_user(user_id, self_active=1, self_activated_at=time.time())

    def deactivate_self(self, user_id):
        self.update_user(user_id, self_active=0)

    def self_maintenance_due(self, user_id):
        from config import SELF_HOURLY_COST
        user = self.get_user(user_id)
        if not user or not user['self_active']:
            return 0

        elapsed_hours = (time.time() - user['self_activated_at']) / 3600.0
        hours_due = int(elapsed_hours)
        cost = hours_due * SELF_HOURLY_COST

        if cost > 0:
            if self.remove_dark_points(user_id, cost):
                self.update_user(user_id, self_activated_at=time.time())
                return cost
            else:
                self.deactivate_self(user_id)
                return -1
        return 0

    def get_all_users_count(self):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) as cnt FROM users")
        row = c.fetchone()
        conn.close()
        return row['cnt'] if row else 0

    def get_user_by_id(self, user_id):
        return self.get_user(user_id)