# database.py - Database Manager

import os
import sqlite3
import time
import random
import string
import threading

class Database:
    def __init__(self):
        # بررسی دسترسی نوشتن و انتخاب بهترین مسیر
        data_dir = os.environ.get('DATA_DIR', '.')
        db_file = "darkpoint.db"
        
        try:
            if data_dir != '.' and os.path.exists(data_dir):
                test_path = os.path.join(data_dir, "perm_test.tmp")
                with open(test_path, 'w') as f:
                    f.write("test")
                os.remove(test_path)
                self.db_name = os.path.join(data_dir, db_file)
            else:
                self.db_name = db_file
        except Exception:
            self.db_name = db_file

        print(f"📁 Database connected at: {self.db_name}")
        self.lock = threading.Lock()
        self.init_db()

    def get_conn(self):
        conn = sqlite3.connect(self.db_name, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()

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
                bought_dp INTEGER DEFAULT 0,
                is_banned INTEGER DEFAULT 0,
                crash_games_played INTEGER DEFAULT 0,
                crash_games_won INTEGER DEFAULT 0,
                last_active REAL DEFAULT 0
            )''')

            # اضافه کردن فیلدهای جدید در صورت آپدیت دیتابیس
            c.execute("PRAGMA table_info(users)")
            existing_cols = [row[1] for row in c.fetchall()]
            
            needed_cols = {
                'is_banned': 'INTEGER DEFAULT 0',
                'crash_games_played': 'INTEGER DEFAULT 0',
                'crash_games_won': 'INTEGER DEFAULT 0',
                'last_active': 'REAL DEFAULT 0',
                'dark_points': 'INTEGER DEFAULT 0',
                'total_earned': 'INTEGER DEFAULT 0',
                'level': 'INTEGER DEFAULT 1',
                'bank_balance': 'INTEGER DEFAULT 0',
                'bank_account': 'INTEGER DEFAULT 0',
                'bank_card': "TEXT DEFAULT ''",
                'bank_deposit_time': 'REAL DEFAULT 0',
                'bank_interest_collected': 'INTEGER DEFAULT 0',
                'factory_level': 'INTEGER DEFAULT 0',
                'factory_active': 'INTEGER DEFAULT 0',
                'factory_last_collect': 'REAL DEFAULT 0',
                'factory_last_maintenance': 'REAL DEFAULT 0',
                'like_challenge_active': 'INTEGER DEFAULT 0',
                'like_challenge_until': 'REAL DEFAULT 0',
                'bought_dp': 'INTEGER DEFAULT 0',
                'referral_count': 'INTEGER DEFAULT 0',
                'last_claim_time': 'REAL DEFAULT 0',
                'last_cooldown': 'INTEGER DEFAULT 0',
            }
            for col, col_type in needed_cols.items():
                if col not in existing_cols:
                    try:
                        c.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
                    except Exception:
                        pass

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

            c.execute('''CREATE TABLE IF NOT EXISTS crash_games (
                game_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                bet_amount INTEGER,
                crash_point REAL,
                cashed_out REAL DEFAULT 0,
                profit INTEGER DEFAULT 0,
                status TEXT DEFAULT 'playing',
                chat_id INTEGER,
                message_id INTEGER,
                created_at REAL DEFAULT 0
            )''')

            c.execute('''CREATE TABLE IF NOT EXISTS transfers (
                transfer_id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_id INTEGER,
                to_id INTEGER,
                amount INTEGER,
                fee INTEGER,
                created_at REAL DEFAULT 0
            )''')

            c.execute('''CREATE TABLE IF NOT EXISTS panel_orders (
                order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                plan_name TEXT,
                price INTEGER,
                status TEXT DEFAULT 'pending',
                config_data TEXT DEFAULT '',
                created_at REAL DEFAULT 0
            )''')

            c.execute('''CREATE TABLE IF NOT EXISTS gift_orders (
                order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                gift_type TEXT,
                price INTEGER,
                status TEXT DEFAULT 'pending',
                created_at REAL DEFAULT 0
            )''')

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

            c.execute('''CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )''')

            c.execute('''CREATE TABLE IF NOT EXISTS custom_panels (
                panel_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                description TEXT,
                price INTEGER,
                data_limit TEXT,
                active INTEGER DEFAULT 1,
                created_at REAL DEFAULT 0
            )''')

            c.execute('''CREATE TABLE IF NOT EXISTS checks (
                check_id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE,
                amount INTEGER,
                claimed INTEGER DEFAULT 0,
                claimed_by INTEGER DEFAULT 0,
                created_at REAL DEFAULT 0
            )''')

            c.execute('''CREATE TABLE IF NOT EXISTS bank_cards (
                card_number TEXT PRIMARY KEY,
                user_id INTEGER
            )''')

            c.execute('''CREATE TABLE IF NOT EXISTS groups (
                chat_id INTEGER PRIMARY KEY,
                title TEXT DEFAULT '',
                member_count INTEGER DEFAULT 0,
                bot_active INTEGER DEFAULT 1,
                added_at REAL DEFAULT 0
            )''')

            c.execute('''CREATE TABLE IF NOT EXISTS force_channels (
                channel_id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_username TEXT UNIQUE,
                channel_title TEXT DEFAULT '',
                active INTEGER DEFAULT 1,
                added_at REAL DEFAULT 0
            )''')

            default_settings = {
                'gift_teddy_price': '750000',
                'gift_section_active': '1',
                'stars_section_active': '1',
                'stars_price': '1000000',
                'buy_dp_active': '1',
                'buy_dp_amount': '500000',
                'buy_dp_price_toman': '50000',
                'crash_active': '1',
            }

            for key, value in default_settings.items():
                c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))

            conn.commit()
            conn.close()

    def get_user(self, user_id):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = c.fetchone()
        conn.close()
        return user

    def create_user(self, user_id, username="", first_name="", referrer_id=0):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("""INSERT OR IGNORE INTO users 
                (user_id, username, first_name, referrer_id, created_at, last_active) 
                VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, username or "", first_name or "", referrer_id, time.time(), time.time()))
            conn.commit()
            conn.close()

    def update_user(self, user_id, **kwargs):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            sets = ", ".join([f"{k} = ?" for k in kwargs.keys()])
            vals = list(kwargs.values()) + [user_id]
            c.execute(f"UPDATE users SET {sets} WHERE user_id = ?", vals)
            conn.commit()
            conn.close()

    def update_last_active(self, user_id):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("UPDATE users SET last_active = ? WHERE user_id = ?", (time.time(), user_id))
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
        if user and 'dark_points' in user.keys():
            return user['dark_points']
        return 0

    def get_level(self, user_id):
        user = self.get_user(user_id)
        if user and 'level' in user.keys():
            return user['level']
        return 1

    def ban_user(self, user_id):
        self.update_user(user_id, is_banned=1)

    def unban_user(self, user_id):
        self.update_user(user_id, is_banned=0)

    def is_banned(self, user_id):
        u = self.get_user(user_id)
        if u and 'is_banned' in u.keys():
            return u['is_banned'] == 1
        return False

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
        return max(0, cooldown - elapsed)

    def set_claim(self, user_id, cooldown):
        self.update_user(user_id, last_claim_time=time.time(), last_cooldown=cooldown)

    def add_referral(self, referrer_id):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id = ?", (referrer_id,))
            conn.commit()
            conn.close()

    def get_referral_count(self, user_id):
        user = self.get_user(user_id)
        if user and 'referral_count' in user.keys():
            return user['referral_count']
        return 0

    def get_leaderboard(self, limit=100):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT user_id, username, first_name, dark_points, level FROM users WHERE is_banned = 0 ORDER BY dark_points DESC LIMIT ?", (limit,))
        rows = c.fetchall()
        conn.close()
        return rows

    def get_all_user_ids(self):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE is_banned = 0")
        rows = c.fetchall()
        conn.close()
        return [r['user_id'] for r in rows]

    def create_game(self, creator_id, amount, chat_id, message_id):
        with self.lock:
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
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("UPDATE games SET joiner_id = ?, status = 'playing' WHERE game_id = ? AND status = 'waiting'",
                      (joiner_id, game_id))
            affected = c.rowcount
            conn.commit()
            conn.close()
            return affected > 0

    def finish_game(self, game_id, winner_id, loser_id):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("UPDATE games SET winner_id = ?, loser_id = ?, status = 'finished' WHERE game_id = ?",
                      (winner_id, loser_id, game_id))
            conn.commit()
            conn.close()

    def cancel_game(self, game_id):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("UPDATE games SET status = 'cancelled' WHERE game_id = ?", (game_id,))
            conn.commit()
            conn.close()

    def create_crash_game(self, user_id, bet, crash_point, chat_id, message_id):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("""INSERT INTO crash_games (user_id, bet_amount, crash_point, chat_id, message_id, created_at) 
                         VALUES (?, ?, ?, ?, ?, ?)""",
                      (user_id, bet, crash_point, chat_id, message_id, time.time()))
            gid = c.lastrowid
            conn.commit()
            conn.close()
            return gid

    def get_crash_game(self, game_id):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM crash_games WHERE game_id = ?", (game_id,))
        g = c.fetchone()
        conn.close()
        return g

    def cashout_crash_game(self, game_id, multiplier, profit):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("UPDATE crash_games SET cashed_out = ?, profit = ?, status = 'won' WHERE game_id = ? AND status = 'playing'",
                      (multiplier, profit, game_id))
            affected = c.rowcount
            conn.commit()
            conn.close()
            return affected > 0

    def crash_game_lost(self, game_id):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("UPDATE crash_games SET status = 'lost' WHERE game_id = ?", (game_id,))
            conn.commit()
            conn.close()

    def increment_crash_stats(self, user_id, won=False):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            if won:
                c.execute("UPDATE users SET crash_games_played = crash_games_played + 1, crash_games_won = crash_games_won + 1 WHERE user_id = ?", (user_id,))
            else:
                c.execute("UPDATE users SET crash_games_played = crash_games_played + 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()

    def record_transfer(self, from_id, to_id, amount, fee):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("""INSERT INTO transfers (from_id, to_id, amount, fee, created_at) 
                         VALUES (?, ?, ?, ?, ?)""",
                      (from_id, to_id, amount, fee, time.time()))
            conn.commit()
            conn.close()

    def get_setting(self, key, default=""):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = c.fetchone()
        conn.close()
        return row['value'] if row else default

    def set_setting(self, key, value):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
            conn.commit()
            conn.close()

    def add_force_channel(self, username, title=""):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            try:
                c.execute("INSERT INTO force_channels (channel_username, channel_title, added_at) VALUES (?, ?, ?)",
                          (username, title, time.time()))
                conn.commit()
                success = True
            except Exception:
                success = False
            conn.close()
            return success

    def remove_force_channel(self, channel_id):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("DELETE FROM force_channels WHERE channel_id = ?", (channel_id,))
            conn.commit()
            conn.close()

    def get_force_channels(self):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM force_channels WHERE active = 1")
        rows = c.fetchall()
        conn.close()
        return rows

    def add_custom_panel(self, name, description, price, data_limit):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("""INSERT INTO custom_panels (name, description, price, data_limit, created_at) 
                         VALUES (?, ?, ?, ?, ?)""",
                      (name, description, price, data_limit, time.time()))
            pid = c.lastrowid
            conn.commit()
            conn.close()
            return pid

    def get_custom_panels(self):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM custom_panels WHERE active = 1 ORDER BY price ASC")
        rows = c.fetchall()
        conn.close()
        return rows

    def create_gift_order(self, user_id, gift_type, price):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("""INSERT INTO gift_orders (user_id, gift_type, price, created_at) 
                         VALUES (?, ?, ?, ?)""",
                      (user_id, gift_type, price, time.time()))
            oid = c.lastrowid
            conn.commit()
            conn.close()
            return oid

    def create_stars_order(self, user_id, target_id, target_type, amount, dp_cost):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("""INSERT INTO stars_orders (user_id, target_id, target_type, amount, dp_cost, created_at) 
                         VALUES (?, ?, ?, ?, ?, ?)""",
                  (user_id, target_id, target_type, amount, dp_cost, time.time()))
            oid = c.lastrowid
            conn.commit()
            conn.close()
            return oid

    def create_panel_order(self, user_id, plan_name, price, config_data=""):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("""INSERT INTO panel_orders (user_id, plan_name, price, config_data, created_at) 
                         VALUES (?, ?, ?, ?, ?)""",
                      (user_id, plan_name, price, config_data, time.time()))
            oid = c.lastrowid
            conn.commit()
            conn.close()
            return oid

    def create_check(self, amount):
        code = ''.join(random.choices(string.ascii_lowercase * 4 + string.digits, k=16))
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("INSERT INTO checks (code, amount, created_at) VALUES (?, ?, ?)",
                      (code, amount, time.time()))
            conn.commit()
            conn.close()
            return code

    def claim_check(self, code, user_id):
        with self.lock:
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

    def open_bank_account(self, user_id, card_number):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
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
                return -1
        return 0

    def add_group(self, chat_id, title, member_count):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("""INSERT OR REPLACE INTO groups (chat_id, title, member_count, added_at) 
                         VALUES (?, ?, ?, ?)""",
                      (chat_id, title, member_count, time.time()))
            conn.commit()
            conn.close()

    def get_stats(self):
        conn = self.get_conn()
        c = conn.cursor()
        stats = {}
        c.execute("SELECT COUNT(*) as cnt FROM users")
        stats['total_users'] = c.fetchone()['cnt']
        c.execute("SELECT COUNT(*) as cnt FROM users WHERE is_banned = 1")
        stats['banned_users'] = c.fetchone()['cnt']
        threshold = time.time() - (7 * 86400)
        c.execute("SELECT COUNT(*) as cnt FROM users WHERE last_active > ?", (threshold,))
        stats['active_7d'] = c.fetchone()['cnt']
        today = time.time() - 86400
        c.execute("SELECT COUNT(*) as cnt FROM users WHERE created_at > ?", (today,))
        stats['new_today'] = c.fetchone()['cnt']
        c.execute("SELECT COALESCE(SUM(dark_points), 0) as total FROM users")
        stats['total_dp'] = c.fetchone()['total']
        c.execute("SELECT COALESCE(SUM(bank_balance), 0) as total FROM users")
        stats['total_bank'] = c.fetchone()['total']
        c.execute("SELECT COUNT(*) as cnt FROM panel_orders")
        stats['panel_orders'] = c.fetchone()['cnt']
        c.execute("SELECT COUNT(*) as cnt FROM gift_orders")
        stats['gift_orders'] = c.fetchone()['cnt']
        c.execute("SELECT COUNT(*) as cnt FROM stars_orders")
        stats['stars_orders'] = c.fetchone()['cnt']
        c.execute("SELECT COUNT(*) as cnt FROM crash_games WHERE status = 'won'")
        stats['crash_won'] = c.fetchone()['cnt']
        c.execute("SELECT COUNT(*) as cnt FROM crash_games WHERE status = 'lost'")
        stats['crash_lost'] = c.fetchone()['cnt']
        conn.close()
        return stats
