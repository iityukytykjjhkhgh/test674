# database.py - Database Manager Ultimate Version

import os
import sqlite3
import time
import random
import string
import threading

class Database:
    def __init__(self):
        # استفاده از دیسک دائمی رندر
        data_dir = os.environ.get('DATA_DIR', '/var/data')
        
        if not os.path.exists(data_dir):
            try:
                os.makedirs(data_dir, exist_ok=True)
            except Exception:
                data_dir = '.'

        self.db_name = os.path.join(data_dir, "darkpoint.db")
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

            # ============ USERS TABLE ============
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
                last_active REAL DEFAULT 0,
                first_reward_claimed INTEGER DEFAULT 0,
                last_wheel_spin REAL DEFAULT 0,
                completed_tasks TEXT DEFAULT '',
                transfer_count_today INTEGER DEFAULT 0,
                last_transfer_day REAL DEFAULT 0
            )''')

            # Auto-Migration USERS
            c.execute("PRAGMA table_info(users)")
            existing_cols = [row[1] for row in c.fetchall()]
            needed_cols = {
                'is_banned': 'INTEGER DEFAULT 0',
                'crash_games_played': 'INTEGER DEFAULT 0',
                'crash_games_won': 'INTEGER DEFAULT 0',
                'last_active': 'REAL DEFAULT 0',
                'first_reward_claimed': 'INTEGER DEFAULT 0',
                'last_wheel_spin': 'REAL DEFAULT 0',
                'completed_tasks': "TEXT DEFAULT ''",
                'transfer_count_today': 'INTEGER DEFAULT 0',
                'last_transfer_day': 'REAL DEFAULT 0',
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

            # ============ GAMES ============
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

            # ============ ORDERS ============
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

            # ============ SETTINGS ============
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

            # ============ GROUPS ============
            c.execute('''CREATE TABLE IF NOT EXISTS groups (
                chat_id INTEGER PRIMARY KEY,
                title TEXT DEFAULT '',
                member_count INTEGER DEFAULT 0,
                bot_active INTEGER DEFAULT 1,
                is_admin INTEGER DEFAULT 0,
                added_at REAL DEFAULT 0
            )''')

            c.execute("PRAGMA table_info(groups)")
            group_cols = [row[1] for row in c.fetchall()]
            if 'is_admin' not in group_cols:
                try:
                    c.execute("ALTER TABLE groups ADD COLUMN is_admin INTEGER DEFAULT 0")
                except Exception:
                    pass

            c.execute('''CREATE TABLE IF NOT EXISTS force_channels (
                channel_id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_username TEXT UNIQUE,
                channel_title TEXT DEFAULT '',
                active INTEGER DEFAULT 1,
                added_at REAL DEFAULT 0
            )''')

            # ============ TASKS ============
            c.execute('''CREATE TABLE IF NOT EXISTS tasks (
                task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT DEFAULT 'channel',
                channel_username TEXT DEFAULT '',
                channel_title TEXT DEFAULT '',
                description TEXT DEFAULT '',
                reward INTEGER DEFAULT 0,
                capacity INTEGER DEFAULT 0,
                completed_count INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1,
                created_at REAL DEFAULT 0
            )''')

            c.execute("PRAGMA table_info(tasks)")
            task_cols = [row[1] for row in c.fetchall()]
            if 'task_type' not in task_cols:
                try: c.execute("ALTER TABLE tasks ADD COLUMN task_type TEXT DEFAULT 'channel'")
                except: pass
            if 'description' not in task_cols:
                try: c.execute("ALTER TABLE tasks ADD COLUMN description TEXT DEFAULT ''")
                except: pass
            if 'capacity' not in task_cols:
                try: c.execute("ALTER TABLE tasks ADD COLUMN capacity INTEGER DEFAULT 0")
                except: pass
            if 'completed_count' not in task_cols:
                try: c.execute("ALTER TABLE tasks ADD COLUMN completed_count INTEGER DEFAULT 0")
                except: pass

            c.execute('''CREATE TABLE IF NOT EXISTS mission_requests (
                request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                task_id INTEGER,
                status TEXT DEFAULT 'pending',
                admin_note TEXT DEFAULT '',
                created_at REAL DEFAULT 0
            )''')

            c.execute('''CREATE TABLE IF NOT EXISTS broadcast_logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                message_type TEXT,
                total_users INTEGER,
                sent_count INTEGER,
                failed_count INTEGER,
                created_at REAL DEFAULT 0
            )''')

            # ============ MINER ============
            c.execute('''CREATE TABLE IF NOT EXISTS miners (
                user_id INTEGER PRIMARY KEY,
                miner_level INTEGER DEFAULT 0,
                is_mining INTEGER DEFAULT 0,
                mining_currency TEXT DEFAULT '',
                electricity_hours REAL DEFAULT 0,
                last_mining_start REAL DEFAULT 0,
                last_update_time REAL DEFAULT 0,
                ton_balance REAL DEFAULT 0,
                usdt_balance REAL DEFAULT 0,
                total_ton_mined REAL DEFAULT 0,
                total_usdt_mined REAL DEFAULT 0,
                total_ton_converted REAL DEFAULT 0,
                total_usdt_converted REAL DEFAULT 0,
                created_at REAL DEFAULT 0
            )''')

            # ============ SHOP ============
            c.execute('''CREATE TABLE IF NOT EXISTS shop_plans (
                plan_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                description TEXT DEFAULT '',
                price INTEGER,
                content_type TEXT DEFAULT 'text',
                content_data TEXT DEFAULT '',
                content_file_id TEXT DEFAULT '',
                stock INTEGER DEFAULT -1,
                sold_count INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1,
                created_at REAL DEFAULT 0
            )''')

            c.execute('''CREATE TABLE IF NOT EXISTS shop_orders (
                order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                plan_id INTEGER,
                plan_name TEXT,
                price INTEGER,
                created_at REAL DEFAULT 0
            )''')

            # ============ CURRENCY CONVERSIONS ============
            c.execute('''CREATE TABLE IF NOT EXISTS currency_conversions (
                conversion_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                currency TEXT,
                amount REAL,
                dp_received INTEGER,
                created_at REAL DEFAULT 0
            )''')

            # ============ DEFAULT SETTINGS ============
            default_settings = {
                'gift_teddy_price': '750000',
                'gift_section_active': '1',
                'stars_section_active': '1',
                'stars_price': '1000000',
                'buy_dp_active': '1',
                'buy_dp_amount': '500000',
                'buy_dp_price_toman': '50000',
                'crash_active': '1',
                'dice_active': '1',
                'guess_active': '1',
                'casino_active': '1',
                'bomb_active': '1',
                'wheel_active': '1',
                'football_active': '1',
                'referral_reward': '30000',
                'first_join_reward': '50000',
                'tasks_active': '1',
                'buy_panel_active': '1',
                'bot_active': '1',
                'miner_active': '1',
                'shop_active': '1',
                'convert_active': '1',
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
        return max(0, user['last_cooldown'] - elapsed)

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

    def claim_first_reward(self, user_id):
        u = self.get_user(user_id)
        if not u or u['first_reward_claimed']:
            return False
        from config import FIRST_JOIN_REWARD
        reward = int(self.get_setting('first_join_reward', str(FIRST_JOIN_REWARD)))
        self.add_dark_points(user_id, reward)
        self.update_user(user_id, first_reward_claimed=1)
        return reward

    def can_transfer(self, user_id):
        from config import MAX_DAILY_TRANSFERS
        u = self.get_user(user_id)
        if not u:
            return False, 0
        now = time.time()
        last_day = u['last_transfer_day']
        count = u['transfer_count_today']
        if now - last_day >= 86400:
            self.update_user(user_id, transfer_count_today=0, last_transfer_day=now)
            return True, MAX_DAILY_TRANSFERS
        if count >= MAX_DAILY_TRANSFERS:
            remaining = 86400 - (now - last_day)
            return False, remaining
        return True, MAX_DAILY_TRANSFERS - count

    def increment_transfer_count(self, user_id):
        u = self.get_user(user_id)
        if not u:
            return
        now = time.time()
        last_day = u['last_transfer_day']
        if now - last_day >= 86400:
            self.update_user(user_id, transfer_count_today=1, last_transfer_day=now)
        else:
            self.update_user(user_id, transfer_count_today=u['transfer_count_today'] + 1)

    # ============ WHEEL ============
    def can_spin_wheel_free(self, user_id):
        u = self.get_user(user_id)
        if not u:
            return False, 0
        from config import WHEEL_FREE_INTERVAL
        elapsed = time.time() - u['last_wheel_spin']
        if elapsed >= WHEEL_FREE_INTERVAL:
            return True, 0
        return False, WHEEL_FREE_INTERVAL - elapsed

    def set_wheel_spin_time(self, user_id):
        self.update_user(user_id, last_wheel_spin=time.time())

    # ============ TASKS ============
    def add_task(self, task_type, channel_username, channel_title, description, reward, capacity=0):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("""INSERT INTO tasks (task_type, channel_username, channel_title, description, reward, capacity, created_at) 
                         VALUES (?, ?, ?, ?, ?, ?, ?)""",
                      (task_type, channel_username, channel_title, description, reward, capacity, time.time()))
            tid = c.lastrowid
            conn.commit()
            conn.close()
            return tid

    def get_tasks(self, task_type=None, only_active=True):
        conn = self.get_conn()
        c = conn.cursor()
        if task_type:
            if only_active:
                c.execute("SELECT * FROM tasks WHERE active = 1 AND task_type = ? ORDER BY task_id ASC", (task_type,))
            else:
                c.execute("SELECT * FROM tasks WHERE task_type = ? ORDER BY task_id ASC", (task_type,))
        else:
            if only_active:
                c.execute("SELECT * FROM tasks WHERE active = 1 ORDER BY task_id ASC")
            else:
                c.execute("SELECT * FROM tasks ORDER BY task_id ASC")
        rows = c.fetchall()
        conn.close()
        return rows

    def get_task(self, task_id):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
        t = c.fetchone()
        conn.close()
        return t

    def delete_task(self, task_id):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            conn.commit()
            conn.close()

    def increment_task_completed(self, task_id):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("UPDATE tasks SET completed_count = completed_count + 1 WHERE task_id = ?", (task_id,))
            conn.commit()
            conn.close()

    def is_task_full(self, task_id):
        t = self.get_task(task_id)
        if not t or t['capacity'] == 0:
            return False
        return t['completed_count'] >= t['capacity']

    def is_task_completed(self, user_id, task_id):
        u = self.get_user(user_id)
        if not u:
            return False
        completed = u['completed_tasks'] or ''
        return str(task_id) in completed.split(',')

    def mark_task_completed(self, user_id, task_id):
        u = self.get_user(user_id)
        if not u:
            return
        completed = u['completed_tasks'] or ''
        tasks_list = completed.split(',') if completed else []
        if str(task_id) not in tasks_list:
            tasks_list.append(str(task_id))
            self.update_user(user_id, completed_tasks=','.join(tasks_list))
            self.increment_task_completed(task_id)

    # ============ MISSION REQUESTS ============
    def create_mission_request(self, user_id, task_id):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("""INSERT INTO mission_requests (user_id, task_id, created_at) 
                         VALUES (?, ?, ?)""",
                      (user_id, task_id, time.time()))
            rid = c.lastrowid
            conn.commit()
            conn.close()
            return rid

    def get_mission_request(self, request_id):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM mission_requests WHERE request_id = ?", (request_id,))
        r = c.fetchone()
        conn.close()
        return r

    def approve_mission_request(self, request_id):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("UPDATE mission_requests SET status = 'approved' WHERE request_id = ?", (request_id,))
            conn.commit()
            conn.close()

    def reject_mission_request(self, request_id):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("UPDATE mission_requests SET status = 'rejected' WHERE request_id = ?", (request_id,))
            conn.commit()
            conn.close()

    def has_pending_mission_request(self, user_id, task_id):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM mission_requests WHERE user_id = ? AND task_id = ? AND status = 'pending'", (user_id, task_id))
        r = c.fetchone()
        conn.close()
        return r is not None

    # ============ GAMES ============
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
            conn.close()    # ============ SETTINGS ============
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

    # ============ FORCE CHANNELS ============
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

    # ============ CUSTOM PANELS ============
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

    def get_all_custom_panels(self):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM custom_panels ORDER BY panel_id ASC")
        rows = c.fetchall()
        conn.close()
        return rows

    def delete_custom_panel(self, panel_id):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("DELETE FROM custom_panels WHERE panel_id = ?", (panel_id,))
            conn.commit()
            conn.close()

    # ============ ORDERS ============
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

    # ============ BANK ============
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
            c.execute("""UPDATE users SET dark_points = dark_points - ?,
                bank_balance = bank_balance + ?, bank_deposit_time = ?, bank_interest_collected = 0
                WHERE user_id = ?""", (amount, amount, time.time(), user_id))
            conn.commit()
            conn.close()
            return True

    def bank_withdraw(self, user_id):
        from config import BANK_INTEREST_RATE
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("SELECT bank_balance, bank_deposit_time, bank_interest_collected FROM users WHERE user_id = ?", (user_id,))
            user = c.fetchone()
            if not user or user['bank_balance'] <= 0:
                conn.close()
                return 0, 0
            balance = user['bank_balance']
            elapsed = time.time() - user['bank_deposit_time']
            interest = int(balance * BANK_INTEREST_RATE) if elapsed >= 86400 and not user['bank_interest_collected'] else 0
            total = balance + interest
            c.execute("""UPDATE users SET dark_points = dark_points + ?,
                bank_balance = 0, bank_deposit_time = 0, bank_interest_collected = 0 WHERE user_id = ?""",
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

    # ============ FACTORY ============
    def open_factory(self, user_id):
        self.update_user(user_id, factory_level=1, factory_active=1,
                         factory_last_collect=time.time(), factory_last_maintenance=time.time())

    def reactivate_factory(self, user_id):
        u = self.get_user(user_id)
        if not u or u['factory_level'] == 0:
            return False
        self.update_user(user_id, factory_active=1,
                         factory_last_collect=time.time(), factory_last_maintenance=time.time())
        return True

    def upgrade_factory(self, user_id):
        user = self.get_user(user_id)
        if not user or user['factory_level'] >= 5:
            return False
        self.update_user(user_id, factory_level=user['factory_level'] + 1)
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

    # ============ GROUPS ============
    def add_or_update_group(self, chat_id, title, member_count, is_admin=0):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("""INSERT OR REPLACE INTO groups (chat_id, title, member_count, is_admin, added_at) 
                         VALUES (?, ?, ?, ?, ?)""",
                      (chat_id, title, member_count, is_admin, time.time()))
            conn.commit()
            conn.close()

    def get_all_groups(self):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM groups ORDER BY added_at DESC")
        rows = c.fetchall()
        conn.close()
        return rows

    def get_admin_groups(self):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM groups WHERE is_admin = 1")
        rows = c.fetchall()
        conn.close()
        return rows

    def update_group_admin_status(self, chat_id, is_admin):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("UPDATE groups SET is_admin = ? WHERE chat_id = ?", (is_admin, chat_id))
            conn.commit()
            conn.close()

    def get_all_users_count(self):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) as cnt FROM users")
        row = c.fetchone()
        conn.close()
        return row['cnt'] if row else 0

    def log_broadcast(self, admin_id, msg_type, total, sent, failed):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("""INSERT INTO broadcast_logs (admin_id, message_type, total_users, sent_count, failed_count, created_at) 
                         VALUES (?, ?, ?, ?, ?, ?)""",
                      (admin_id, msg_type, total, sent, failed, time.time()))
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
        c.execute("SELECT COUNT(*) as cnt FROM groups WHERE is_admin = 1")
        stats['admin_groups'] = c.fetchone()['cnt']
        c.execute("SELECT COUNT(*) as cnt FROM groups")
        stats['total_groups'] = c.fetchone()['cnt']
        c.execute("SELECT COUNT(*) as cnt FROM shop_orders")
        stats['shop_orders'] = c.fetchone()['cnt']
        conn.close()
        return stats

    def search_user_by_username(self, username):
        conn = self.get_conn()
        c = conn.cursor()
        username = username.replace("@", "")
        c.execute("SELECT * FROM users WHERE username = ?", (username,))
        u = c.fetchone()
        conn.close()
        return u

    # ============ MINER METHODS ============
    def get_miner(self, user_id):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM miners WHERE user_id = ?", (user_id,))
        m = c.fetchone()
        conn.close()
        return m

    def create_miner(self, user_id):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("""INSERT OR IGNORE INTO miners 
                (user_id, miner_level, created_at, last_update_time) 
                VALUES (?, 1, ?, ?)""",
                (user_id, time.time(), time.time()))
            conn.commit()
            conn.close()

    def update_miner(self, user_id, **kwargs):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            sets = ", ".join([f"{k} = ?" for k in kwargs.keys()])
            vals = list(kwargs.values()) + [user_id]
            c.execute(f"UPDATE miners SET {sets} WHERE user_id = ?", vals)
            conn.commit()
            conn.close()

    def upgrade_miner(self, user_id):
        miner = self.get_miner(user_id)
        if not miner or miner['miner_level'] >= 5:
            return False
        new_level = miner['miner_level'] + 1
        self.update_miner(user_id, miner_level=new_level)
        return True

    def add_electricity(self, user_id, hours):
        miner = self.get_miner(user_id)
        if not miner:
            return False
        new_hours = miner['electricity_hours'] + hours
        self.update_miner(user_id, electricity_hours=new_hours)
        return True

    def start_mining(self, user_id, currency):
        self.update_miner(user_id,
            is_mining=1,
            mining_currency=currency,
            last_mining_start=time.time(),
            last_update_time=time.time()
        )

    def stop_mining(self, user_id):
        self.update_mining_balance(user_id)
        self.update_miner(user_id, is_mining=0, mining_currency='')

    def update_mining_balance(self, user_id):
        from config import MINER_LEVELS
        miner = self.get_miner(user_id)
        if not miner or not miner['is_mining']:
            return 0

        now = time.time()
        elapsed_hours = (now - miner['last_update_time']) / 3600.0

        if elapsed_hours > miner['electricity_hours']:
            elapsed_hours = miner['electricity_hours']

        if elapsed_hours <= 0:
            if miner['is_mining']:
                self.update_miner(user_id, is_mining=0, electricity_hours=0, mining_currency='')
            return 0

        level = miner['miner_level']
        if level == 0:
            return 0

        rates = MINER_LEVELS[level]
        currency = miner['mining_currency']

        mined = 0
        if currency == 'ton':
            mined = elapsed_hours * rates['ton_per_hour']
            new_balance = miner['ton_balance'] + mined
            new_total = miner['total_ton_mined'] + mined
            self.update_miner(user_id,
                ton_balance=new_balance,
                total_ton_mined=new_total,
                electricity_hours=max(0, miner['electricity_hours'] - elapsed_hours),
                last_update_time=now
            )
        elif currency == 'usdt':
            mined = elapsed_hours * rates['usdt_per_hour']
            new_balance = miner['usdt_balance'] + mined
            new_total = miner['total_usdt_mined'] + mined
            self.update_miner(user_id,
                usdt_balance=new_balance,
                total_usdt_mined=new_total,
                electricity_hours=max(0, miner['electricity_hours'] - elapsed_hours),
                last_update_time=now
            )

        updated_miner = self.get_miner(user_id)
        if updated_miner['electricity_hours'] <= 0.001:
            self.update_miner(user_id, is_mining=0, mining_currency='', electricity_hours=0)

        return mined

    def convert_ton_to_dp(self, user_id, ton_amount):
        from config import TON_TO_DP_RATE
        miner = self.get_miner(user_id)
        if not miner or miner['ton_balance'] < ton_amount:
            return 0
        dp_received = int((ton_amount / 0.01) * TON_TO_DP_RATE)
        self.update_miner(user_id,
            ton_balance=miner['ton_balance'] - ton_amount,
            total_ton_converted=miner['total_ton_converted'] + ton_amount
        )
        self.add_dark_points(user_id, dp_received)
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("""INSERT INTO currency_conversions (user_id, currency, amount, dp_received, created_at) 
                         VALUES (?, ?, ?, ?, ?)""",
                      (user_id, 'ton', ton_amount, dp_received, time.time()))
            conn.commit()
            conn.close()
        return dp_received

    def convert_usdt_to_dp(self, user_id, usdt_amount):
        from config import USDT_TO_DP_RATE
        miner = self.get_miner(user_id)
        if not miner or miner['usdt_balance'] < usdt_amount:
            return 0
        dp_received = int((usdt_amount / 0.01) * USDT_TO_DP_RATE)
        self.update_miner(user_id,
            usdt_balance=miner['usdt_balance'] - usdt_amount,
            total_usdt_converted=miner['total_usdt_converted'] + usdt_amount
        )
        self.add_dark_points(user_id, dp_received)
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("""INSERT INTO currency_conversions (user_id, currency, amount, dp_received, created_at) 
                         VALUES (?, ?, ?, ?, ?)""",
                      (user_id, 'usdt', usdt_amount, dp_received, time.time()))
            conn.commit()
            conn.close()
        return dp_received

    def get_total_mining_stats(self):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT COALESCE(SUM(ton_balance), 0) as total FROM miners")
        total_ton_current = c.fetchone()['total']
        c.execute("SELECT COALESCE(SUM(usdt_balance), 0) as total FROM miners")
        total_usdt_current = c.fetchone()['total']
        c.execute("SELECT COALESCE(SUM(total_ton_mined), 0) as total FROM miners")
        total_ton_all = c.fetchone()['total']
        c.execute("SELECT COALESCE(SUM(total_usdt_mined), 0) as total FROM miners")
        total_usdt_all = c.fetchone()['total']
        c.execute("SELECT COALESCE(SUM(total_ton_converted), 0) as total FROM miners")
        total_ton_conv = c.fetchone()['total']
        c.execute("SELECT COALESCE(SUM(total_usdt_converted), 0) as total FROM miners")
        total_usdt_conv = c.fetchone()['total']
        c.execute("SELECT COUNT(*) as cnt FROM miners")
        total_miners = c.fetchone()['cnt']
        c.execute("SELECT COUNT(*) as cnt FROM miners WHERE is_mining = 1")
        active_miners = c.fetchone()['cnt']
        conn.close()
        return {
            'total_ton_current': total_ton_current,
            'total_usdt_current': total_usdt_current,
            'total_ton_all': total_ton_all,
            'total_usdt_all': total_usdt_all,
            'total_ton_converted': total_ton_conv,
            'total_usdt_converted': total_usdt_conv,
            'total_miners': total_miners,
            'active_miners': active_miners,
        }

    # ============ SHOP METHODS ============
    def add_shop_plan(self, name, description, price, content_type, content_data, content_file_id='', stock=-1):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("""INSERT INTO shop_plans 
                (name, description, price, content_type, content_data, content_file_id, stock, created_at) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (name, description, price, content_type, content_data, content_file_id, stock, time.time()))
            pid = c.lastrowid
            conn.commit()
            conn.close()
            return pid

    def get_shop_plans(self, only_active=True):
        conn = self.get_conn()
        c = conn.cursor()
        if only_active:
            c.execute("SELECT * FROM shop_plans WHERE active = 1 ORDER BY plan_id ASC")
        else:
            c.execute("SELECT * FROM shop_plans ORDER BY plan_id ASC")
        rows = c.fetchall()
        conn.close()
        return rows

    def get_shop_plan(self, plan_id):
        conn = self.get_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM shop_plans WHERE plan_id = ?", (plan_id,))
        p = c.fetchone()
        conn.close()
        return p

    def delete_shop_plan(self, plan_id):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("DELETE FROM shop_plans WHERE plan_id = ?", (plan_id,))
            conn.commit()
            conn.close()

    def increment_shop_sold(self, plan_id):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("UPDATE shop_plans SET sold_count = sold_count + 1 WHERE plan_id = ?", (plan_id,))
            c.execute("UPDATE shop_plans SET stock = stock - 1 WHERE plan_id = ? AND stock > 0", (plan_id,))
            conn.commit()
            conn.close()

    def create_shop_order(self, user_id, plan_id, plan_name, price):
        with self.lock:
            conn = self.get_conn()
            c = conn.cursor()
            c.execute("""INSERT INTO shop_orders (user_id, plan_id, plan_name, price, created_at) 
                         VALUES (?, ?, ?, ?, ?)""",
                      (user_id, plan_id, plan_name, price, time.time()))
            oid = c.lastrowid
            conn.commit()
            conn.close()
            return oid
