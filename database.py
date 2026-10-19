# ═══════════════════════════════════════════════════════════
#  database.py — Dark Point Bot Database
#  SECTION 1/3 — Imports, Schema, Users, Level, Settings
# ═══════════════════════════════════════════════════════════

import os
import sqlite3
import logging
from datetime import datetime
import config

logger = logging.getLogger(__name__)


class Database:
    """کلاس اصلی دیتابیس دارک پوینت"""

    def __init__(self):
        # مسیر دیتابیس (Render Persistent Disk)
        data_dir = os.environ.get("DATA_DIR", ".")
        os.makedirs(data_dir, exist_ok=True)
        self.db_path = os.path.join(data_dir, "bot.db")

        logger.info(f"📁 Data dir: {data_dir}")
        logger.info(f"💾 DB path: {self.db_path}")

        # اتصال
        self.conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            isolation_level=None,  # autocommit
        )
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")

        # ساخت جداول و مهاجرت
        self._create_tables()
        self._migrate()

        logger.info("✅ Database initialized")

    # ══════════════════════════════════════════════════════
    #  ساخت جداول اولیه
    # ══════════════════════════════════════════════════════
    def _create_tables(self):
        """ساخت تمام جداول اگر وجود نداشته باشند"""

        # ── کاربران ──
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                first_name TEXT DEFAULT '',
                balance INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                referred_by INTEGER DEFAULT 0,
                banned INTEGER DEFAULT 0,
                joined_at TEXT,
                last_claim INTEGER DEFAULT 0,
                claim_cooldown INTEGER DEFAULT 0,
                last_wheel INTEGER DEFAULT 0,
                bank_balance INTEGER DEFAULT 0,
                bank_lock_until INTEGER DEFAULT 0,
                bank_last_interest INTEGER DEFAULT 0,
                miner_level INTEGER DEFAULT 0,
                miner_currency TEXT DEFAULT 'ton',
                miner_last_collect INTEGER DEFAULT 0,
                ton_balance REAL DEFAULT 0.0,
                usdt_balance REAL DEFAULT 0.0,
                factory_level INTEGER DEFAULT 1,
                factory_last_collect INTEGER DEFAULT 0
            )
        """)

        # ── تنظیمات ──
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # ── گروه‌ها ──
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS groups (
                chat_id INTEGER PRIMARY KEY,
                title TEXT,
                members INTEGER DEFAULT 0,
                joined_at TEXT
            )
        """)

        # ── انتقال‌ها ──
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER,
                date TEXT
            )
        """)

        # ── برداشت TON ──
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS ton_withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                wallet TEXT NOT NULL,
                ton_amount REAL NOT NULL,
                dp_cost INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                processed_at TEXT
            )
        """)

        # ── فروشگاه ──
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS shop_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                price INTEGER DEFAULT 0,
                stock INTEGER DEFAULT 0,
                content TEXT DEFAULT '',
                file_id TEXT DEFAULT '',
                file_type TEXT DEFAULT '',
                active INTEGER DEFAULT 1
            )
        """)

        # ── پلن‌های هدیه ──
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS gift_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                price INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1
            )
        """)

        # ── ماموریت‌ها ──
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                type TEXT DEFAULT 'channel',
                reward INTEGER DEFAULT 0,
                link TEXT DEFAULT '',
                channel_id TEXT DEFAULT '',
                active INTEGER DEFAULT 1
            )
        """)

        # ── ماموریت‌های انجام‌شده کاربر ──
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS user_tasks (
                user_id INTEGER,
                task_id INTEGER,
                completed_at TEXT,
                UNIQUE(user_id, task_id)
            )
        """)

        # ── لایک چلنج ──
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS like_challenges (
                user_id INTEGER PRIMARY KEY,
                end_date TEXT,
                active INTEGER DEFAULT 1
            )
        """)

        # ── فورس‌جوین ──
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS force_join (
                channel_id TEXT PRIMARY KEY,
                title TEXT
            )
        """)

        # ── سفارشات ستاره ──
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS star_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                dp_cost INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TEXT
            )
        """)

        # ── سفارشات خرید DP ──
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS buy_dp_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                dp_amount INTEGER,
                price INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TEXT
            )
        """)

    # ══════════════════════════════════════════════════════
    #  مهاجرت (Migration) — ALTER جدید‌ترین ستون‌ها
    # ══════════════════════════════════════════════════════
    def _migrate(self):
        """
        افزودن ستون‌های جدید به جدول users اگر وجود نداشته باشند.
        اجرای بی‌خطر — در صورت وجود ستون، نادیده می‌گیرد.
        """
        new_columns = [
            ("username", "TEXT DEFAULT ''"),
            ("first_name", "TEXT DEFAULT ''"),
            ("balance", "INTEGER DEFAULT 0"),
            ("level", "INTEGER DEFAULT 1"),
            ("referred_by", "INTEGER DEFAULT 0"),
            ("banned", "INTEGER DEFAULT 0"),
            ("joined_at", "TEXT"),
            ("last_claim", "INTEGER DEFAULT 0"),
            ("claim_cooldown", "INTEGER DEFAULT 0"),
            ("last_wheel", "INTEGER DEFAULT 0"),
            ("bank_balance", "INTEGER DEFAULT 0"),
            ("bank_lock_until", "INTEGER DEFAULT 0"),
            ("bank_last_interest", "INTEGER DEFAULT 0"),
            ("miner_level", "INTEGER DEFAULT 0"),
            ("miner_currency", "TEXT DEFAULT 'ton'"),
            ("miner_last_collect", "INTEGER DEFAULT 0"),
            ("ton_balance", "REAL DEFAULT 0.0"),
            ("usdt_balance", "REAL DEFAULT 0.0"),
            ("factory_level", "INTEGER DEFAULT 1"),
            ("factory_last_collect", "INTEGER DEFAULT 0"),
        ]

        # گرفتن ستون‌های موجود
        try:
            existing = [
                row[1] for row in
                self.conn.execute("PRAGMA table_info(users)").fetchall()
            ]
        except Exception:
            existing = []

        # افزودن ستون‌های جدید
        for col, typ in new_columns:
            if col not in existing:
                try:
                    self.conn.execute(
                        f"ALTER TABLE users ADD COLUMN {col} {typ}"
                    )
                    logger.info(f"✅ Added column: users.{col}")
                except Exception as e:
                    logger.debug(f"⚠️ Column {col} skip: {e}")

        # مقادیر پیش‌فرض تنظیمات
        defaults = {
            "bot_on": "1",
            "buy_dp_amount": str(config.BUY_DP_DEFAULT_AMOUNT),
            "buy_dp_price": str(config.BUY_DP_DEFAULT_PRICE),
            "referral_reward": str(config.DEFAULT_REFERRAL_REWARD),
            "first_join_reward": str(config.DEFAULT_FIRST_JOIN_REWARD),
            "stars_amount": "50",
            "stars_on": "1",
            # 15 بخش قابل toggle (همه روشن به صورت پیش‌فرض)
            "sec_ton_withdraw": "1",
            "sec_buy_dp": "1",
            "sec_gift": "1",
            "sec_shop": "1",
            "sec_stars": "1",
            "sec_wheel": "1",
            "sec_bank": "1",
            "sec_claim": "1",
            "sec_referral": "1",
            "sec_tasks": "1",
            "sec_like": "1",
            "sec_convert": "1",
            "sec_panel": "1",
            # بازی‌ها و سیستم‌های گروهی
            "sec_crash": "1",
            "sec_dice": "1",
            "sec_guess": "1",
            "sec_casino": "1",
            "sec_bomb": "1",
            "sec_miner": "1",
            "sec_factory": "1",
            "sec_transfer": "1",
        }
        for key, val in defaults.items():
            try:
                existing_val = self.conn.execute(
                    "SELECT value FROM settings WHERE key=?", (key,)
                ).fetchone()
                if not existing_val:
                    self.conn.execute(
                        "INSERT INTO settings (key, value) VALUES (?,?)",
                        (key, val)
                    )
            except Exception as e:
                logger.debug(f"⚠️ Setting {key}: {e}")

        logger.info("✅ Migration completed")

    # ══════════════════════════════════════════════════════
    #  کاربران
    # ══════════════════════════════════════════════════════
    def add_user(self, user_id, username="", first_name="", referred_by=None):
        """ثبت کاربر جدید + جایزه ریفرال"""
        # چک وجود کاربر
        c = self.conn.execute(
            "SELECT user_id FROM users WHERE user_id=?", (user_id,)
        )
        if c.fetchone():
            # کاربر موجود — فقط آپدیت نام و یوزرنیم
            self.conn.execute(
                "UPDATE users SET username=?, first_name=? WHERE user_id=?",
                (username, first_name, user_id)
            )
            return False

        # کاربر جدید
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # جایزه عضویت اول
        first_join = int(self.get_setting(
            "first_join_reward",
            str(config.DEFAULT_FIRST_JOIN_REWARD)
        ))

        ref_id = referred_by if referred_by else 0

        self.conn.execute("""
            INSERT INTO users
            (user_id, username, first_name, balance, level,
             referred_by, joined_at)
            VALUES (?, ?, ?, ?, 1, ?, ?)
        """, (user_id, username, first_name, first_join, ref_id, now))

        # جایزه ریفرال
        if ref_id:
            ref_reward = int(self.get_setting(
                "referral_reward",
                str(config.DEFAULT_REFERRAL_REWARD)
            ))
            self.add_balance(ref_id, ref_reward)
            logger.info(f"🤝 Referral: {ref_id} +{ref_reward} DP from {user_id}")

        return True

    def get_user(self, user_id):
        """دریافت اطلاعات کامل کاربر"""
        c = self.conn.execute(
            "SELECT * FROM users WHERE user_id=?", (user_id,)
        )
        row = c.fetchone()
        return dict(row) if row else None

    def get_user_by_username(self, username):
        """جستجوی کاربر بر اساس یوزرنیم"""
        c = self.conn.execute(
            "SELECT * FROM users WHERE username=? COLLATE NOCASE",
            (username,)
        )
        row = c.fetchone()
        return dict(row) if row else None

    def add_balance(self, user_id, amount):
        """
        اضافه (یا کسر با مقدار منفی) DP از موجودی کاربر.
        خودکار سطح را بروزرسانی می‌کند.
        """
        self.conn.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id=?",
            (amount, user_id)
        )
        # بروزرسانی سطح
        self._update_level(user_id)

    def set_balance(self, user_id, amount):
        """تنظیم موجودی به مقدار دقیق"""
        self.conn.execute(
            "UPDATE users SET balance=? WHERE user_id=?",
            (amount, user_id)
        )
        self._update_level(user_id)

    def set_ban(self, user_id, status):
        """بن یا آنبن کردن کاربر"""
        self.conn.execute(
            "UPDATE users SET banned=? WHERE user_id=?",
            (status, user_id)
        )

    # ══════════════════════════════════════════════════════
    #  سیستم سطح‌بندی (20 سطح)
    # ══════════════════════════════════════════════════════
    def _update_level(self, user_id):
        """
        بروزرسانی خودکار سطح کاربر بر اساس موجودی.
        در صورت ارتقا، جایزه سطح × 1,000,000 اضافه می‌شود.
        """
        u = self.conn.execute(
            "SELECT balance, level FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()
        if not u:
            return

        balance = u["balance"]
        current_lvl = u["level"]

        # محاسبه سطح جدید بر اساس LEVEL_THRESHOLDS
        new_lvl = current_lvl
        for i, threshold in enumerate(config.LEVEL_THRESHOLDS, start=1):
            if balance >= threshold:
                new_lvl = i
            else:
                break

        # محدود به حداکثر 20
        new_lvl = min(new_lvl, 20)

        # اگر ارتقا یافت
        if new_lvl > current_lvl:
            # جایزه هر سطح جدید
            total_reward = 0
            for lvl in range(current_lvl + 1, new_lvl + 1):
                reward = config.get_level_reward(lvl)
                total_reward += reward

            self.conn.execute(
                "UPDATE users SET level=?, balance = balance + ? "
                "WHERE user_id=?",
                (new_lvl, total_reward, user_id)
            )
            logger.info(
                f"⬆️ Level up: user={user_id} "
                f"{current_lvl} → {new_lvl} (+{total_reward} DP)"
            )

    # ══════════════════════════════════════════════════════
    #  کلیم و گردونه
    # ══════════════════════════════════════════════════════
    def set_last_claim(self, user_id, ts):
        """ثبت زمان آخرین کلیم"""
        self.conn.execute(
            "UPDATE users SET last_claim=? WHERE user_id=?",
            (ts, user_id)
        )

    def set_claim_cooldown(self, user_id, cd):
        """تنظیم کولداون کلیم (ثانیه)"""
        self.conn.execute(
            "UPDATE users SET claim_cooldown=? WHERE user_id=?",
            (cd, user_id)
        )

    def set_last_wheel(self, user_id, ts):
        """ثبت زمان آخرین گردونه"""
        self.conn.execute(
            "UPDATE users SET last_wheel=? WHERE user_id=?",
            (ts, user_id)
        )

    # ══════════════════════════════════════════════════════
    #  ریفرال و لیدربورد
    # ══════════════════════════════════════════════════════
    def get_referral_count(self, user_id):
        """تعداد زیرمجموعه‌های یک کاربر"""
        c = self.conn.execute(
            "SELECT COUNT(*) FROM users WHERE referred_by=?",
            (user_id,)
        )
        return c.fetchone()[0]

    def get_top_users(self, n=10):
        """n نفر برتر بر اساس موجودی"""
        c = self.conn.execute(
            "SELECT user_id, username, first_name, balance, level "
            "FROM users WHERE banned=0 "
            "ORDER BY balance DESC LIMIT ?",
            (n,)
        )
        return [dict(r) for r in c.fetchall()]

    # ══════════════════════════════════════════════════════
    #  آمار کلی
    # ══════════════════════════════════════════════════════
    def get_total_users(self):
        """کل تعداد کاربران"""
        c = self.conn.execute("SELECT COUNT(*) FROM users")
        return c.fetchone()[0]

    def get_total_balance(self):
        """مجموع DP در گردش"""
        c = self.conn.execute(
            "SELECT COALESCE(SUM(balance), 0) FROM users"
        )
        return c.fetchone()[0]

    def get_today_new_users(self):
        """کاربران جدید امروز"""
        today = datetime.now().strftime("%Y-%m-%d")
        c = self.conn.execute(
            "SELECT COUNT(*) FROM users WHERE joined_at LIKE ?",
            (f"{today}%",)
        )
        return c.fetchone()[0]

    def get_all_user_ids(self):
        """لیست آیدی همه کاربران غیر بن‌شده (برای broadcast)"""
        c = self.conn.execute(
            "SELECT user_id FROM users WHERE banned=0"
        )
        return [r[0] for r in c.fetchall()]

    # ══════════════════════════════════════════════════════
    #  تنظیمات (settings)
    # ══════════════════════════════════════════════════════
    def get_setting(self, key, default=""):
        """خواندن یک تنظیم"""
        try:
            c = self.conn.execute(
                "SELECT value FROM settings WHERE key=?", (key,)
            )
            row = c.fetchone()
            return row[0] if row else default
        except Exception:
            return default

    def set_setting(self, key, value):
        """ذخیره یک تنظیم"""
        self.conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, str(value))
        )

    def is_section_on(self, section):
        """آیا بخش روشن است؟"""
        val = self.get_setting(f"sec_{section}", "1")
        return val == "1"

    def set_section(self, section, on: bool):
        """روشن/خاموش کردن بخش"""
        self.set_setting(f"sec_{section}", "1" if on else "0")    # ──────────────────────────────────────────────
    #  🏦  DARK BANK
    # ──────────────────────────────────────────────
    def add_bank_balance(self, user_id: int, amount: int):
        self.conn.execute(
            "UPDATE users SET bank_balance = bank_balance + ? WHERE user_id = ?",
            (amount, user_id),
        )

    def set_bank_balance(self, user_id: int, amount: int):
        self.conn.execute(
            "UPDATE users SET bank_balance = ? WHERE user_id = ?",
            (amount, user_id),
        )

    def set_bank_lock(self, user_id: int, lock_until: int):
        self.conn.execute(
            "UPDATE users SET bank_lock_until = ? WHERE user_id = ?",
            (lock_until, user_id),
        )

    def set_bank_last_interest(self, user_id: int, ts: int):
        self.conn.execute(
            "UPDATE users SET bank_last_interest = ? WHERE user_id = ?",
            (ts, user_id),
        )

    # ──────────────────────────────────────────────
    #  ⛏️  MINER
    # ──────────────────────────────────────────────
    def set_miner_level(self, user_id: int, level: int):
        self.conn.execute(
            "UPDATE users SET miner_level = ? WHERE user_id = ?",
            (level, user_id),
        )

    def set_miner_currency(self, user_id: int, currency: str):
        self.conn.execute(
            "UPDATE users SET miner_currency = ? WHERE user_id = ?",
            (currency, user_id),
        )

    def set_miner_last_collect(self, user_id: int, ts: int):
        self.conn.execute(
            "UPDATE users SET miner_last_collect = ? WHERE user_id = ?",
            (ts, user_id),
        )

    def add_ton_balance(self, user_id: int, amount: float):
        self.conn.execute(
            "UPDATE users SET ton_balance = ton_balance + ? WHERE user_id = ?",
            (amount, user_id),
        )

    def add_usdt_balance(self, user_id: int, amount: float):
        self.conn.execute(
            "UPDATE users SET usdt_balance = usdt_balance + ? WHERE user_id = ?",
            (amount, user_id),
        )

    # ──────────────────────────────────────────────
    #  🏭  FACTORY
    # ──────────────────────────────────────────────
    def set_factory_level(self, user_id: int, level: int):
        self.conn.execute(
            "UPDATE users SET factory_level = ? WHERE user_id = ?",
            (level, user_id),
        )

    def set_factory_last_collect(self, user_id: int, ts: int):
        self.conn.execute(
            "UPDATE users SET factory_last_collect = ? WHERE user_id = ?",
            (ts, user_id),
        )

    # ──────────────────────────────────────────────
    #  💸  TRANSFER
    # ──────────────────────────────────────────────
    def get_transfer_count_today(self, user_id: int) -> int:
        today_start = int(datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp())
        row = self.conn.execute(
            "SELECT COUNT(*) FROM transfers WHERE from_id = ? AND created_at >= ?",
            (user_id, today_start),
        ).fetchone()
        return row[0] if row else 0

    def add_transfer_record(self, from_id: int, to_id: int,
                            amount: int, fee: int):
        self.conn.execute(
            "INSERT INTO transfers (from_id, to_id, amount, fee, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (from_id, to_id, amount, fee, int(time.time())),
        )

    # ──────────────────────────────────────────────
    #  💎  TON WITHDRAWALS
    # ──────────────────────────────────────────────
    def add_ton_withdrawal(self, user_id: int, dp_amount: int,
                           ton_amount: float, wallet: str,
                           status: str = "pending") -> int:
        cur = self.conn.execute(
            "INSERT INTO ton_withdrawals "
            "(user_id, dp_amount, ton_amount, wallet, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, dp_amount, ton_amount, wallet, status,
             int(time.time())),
        )
        return cur.lastrowid

    def get_pending_ton_withdrawals(self) -> list:
        rows = self.conn.execute(
            "SELECT id, user_id, dp_amount, ton_amount, wallet, "
            "       status, created_at "
            "FROM ton_withdrawals "
            "WHERE status = 'pending' "
            "ORDER BY created_at ASC",
        ).fetchall()
        return [dict(r) for r in rows]

    def set_ton_withdrawal_status(self, withdrawal_id: int, status: str):
        self.conn.execute(
            "UPDATE ton_withdrawals SET status = ? WHERE id = ?",
            (status, withdrawal_id),
        )

    def get_ton_withdrawal_stats(self) -> dict:
        total = self.conn.execute(
            "SELECT COUNT(*) FROM ton_withdrawals"
        ).fetchone()[0]
        pending = self.conn.execute(
            "SELECT COUNT(*) FROM ton_withdrawals WHERE status='pending'"
        ).fetchone()[0]
        approved = self.conn.execute(
            "SELECT COUNT(*) FROM ton_withdrawals WHERE status='approved'"
        ).fetchone()[0]
        rejected = self.conn.execute(
            "SELECT COUNT(*) FROM ton_withdrawals WHERE status='rejected'"
        ).fetchone()[0]
        total_ton = self.conn.execute(
            "SELECT COALESCE(SUM(ton_amount),0) FROM ton_withdrawals "
            "WHERE status='approved'"
        ).fetchone()[0]
        total_dp = self.conn.execute(
            "SELECT COALESCE(SUM(dp_amount),0) FROM ton_withdrawals "
            "WHERE status='approved'"
        ).fetchone()[0]
        return {
            "total": total,
            "pending": pending,
            "approved": approved,
            "rejected": rejected,
            "total_ton": total_ton,
            "total_dp": total_dp,
        }

    # ──────────────────────────────────────────────
    #  👥  GROUPS
    # ──────────────────────────────────────────────
    def add_group(self, chat_id: int, title: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO groups (chat_id, title, added_at) "
            "VALUES (?, ?, ?)",
            (chat_id, title, int(time.time())),
        )

    def remove_group(self, chat_id: int):
        self.conn.execute(
            "DELETE FROM groups WHERE chat_id = ?", (chat_id,)
        )

    def get_all_groups(self) -> list:
        rows = self.conn.execute(
            "SELECT chat_id, title, added_at FROM groups"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_total_groups(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM groups"
        ).fetchone()[0]    # ──────────────────────────────────────────────
    #  🛒  SHOP PLANS
    # ──────────────────────────────────────────────
    def get_shop_plans(self, active_only: bool = True) -> list:
        if active_only:
            rows = self.conn.execute(
                "SELECT * FROM shop_plans WHERE active = 1 "
                "ORDER BY price ASC"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM shop_plans ORDER BY price ASC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_shop_plan(self, plan_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM shop_plans WHERE id = ?", (plan_id,)
        ).fetchone()
        return dict(row) if row else None

    def add_shop_plan(self, name: str, description: str,
                      price: int, stock: int = -1) -> int:
        cur = self.conn.execute(
            "INSERT INTO shop_plans "
            "(name, description, price, stock, active, created_at) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (name, description, price, stock, int(time.time())),
        )
        return cur.lastrowid

    def remove_shop_plan(self, plan_id: int):
        self.conn.execute(
            "DELETE FROM shop_plans WHERE id = ?", (plan_id,)
        )

    def set_plan_stock(self, plan_id: int, stock: int):
        self.conn.execute(
            "UPDATE shop_plans SET stock = ? WHERE id = ?",
            (stock, plan_id),
        )

    def decrease_plan_stock(self, plan_id: int) -> bool:
        """Returns True if stock was available and decreased."""
        plan = self.get_shop_plan(plan_id)
        if not plan:
            return False
        if plan["stock"] == -1:          # unlimited
            return True
        if plan["stock"] <= 0:
            return False
        self.conn.execute(
            "UPDATE shop_plans SET stock = stock - 1 WHERE id = ?",
            (plan_id,),
        )
        return True

    def set_plan_active(self, plan_id: int, active: bool):
        self.conn.execute(
            "UPDATE shop_plans SET active = ? WHERE id = ?",
            (1 if active else 0, plan_id),
        )

    # ──────────────────────────────────────────────
    #  🎁  GIFT PLANS
    # ──────────────────────────────────────────────
    def get_gift_plans(self, active_only: bool = True) -> list:
        if active_only:
            rows = self.conn.execute(
                "SELECT * FROM gift_plans WHERE active = 1 "
                "ORDER BY dp_amount ASC"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM gift_plans ORDER BY dp_amount ASC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_gift_plan(self, plan_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM gift_plans WHERE id = ?", (plan_id,)
        ).fetchone()
        return dict(row) if row else None

    def add_gift_plan(self, name: str, dp_amount: int,
                      price: int) -> int:
        cur = self.conn.execute(
            "INSERT INTO gift_plans "
            "(name, dp_amount, price, active, created_at) "
            "VALUES (?, ?, ?, 1, ?)",
            (name, dp_amount, price, int(time.time())),
        )
        return cur.lastrowid

    def remove_gift_plan(self, plan_id: int):
        self.conn.execute(
            "DELETE FROM gift_plans WHERE id = ?", (plan_id,)
        )

    def set_gift_plan_active(self, plan_id: int, active: bool):
        self.conn.execute(
            "UPDATE gift_plans SET active = ? WHERE id = ?",
            (1 if active else 0, plan_id),
        )

    # ──────────────────────────────────────────────
    #  📋  TASKS / MISSIONS
    # ──────────────────────────────────────────────
    def get_active_tasks(self) -> list:
        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE active = 1 "
            "ORDER BY reward DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_task(self, task_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return dict(row) if row else None

    def add_task(self, title: str, description: str,
                 reward: int, link: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO tasks "
            "(title, description, reward, link, active, created_at) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (title, description, reward, link, int(time.time())),
        )
        return cur.lastrowid

    def remove_task(self, task_id: int):
        self.conn.execute(
            "DELETE FROM tasks WHERE id = ?", (task_id,)
        )
        self.conn.execute(
            "DELETE FROM user_tasks WHERE task_id = ?", (task_id,)
        )

    def set_task_active(self, task_id: int, active: bool):
        self.conn.execute(
            "UPDATE tasks SET active = ? WHERE id = ?",
            (1 if active else 0, task_id),
        )

    def is_task_completed(self, user_id: int, task_id: int) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM user_tasks "
            "WHERE user_id = ? AND task_id = ?",
            (user_id, task_id),
        ).fetchone()
        return row is not None

    def complete_task(self, user_id: int, task_id: int):
        self.conn.execute(
            "INSERT OR IGNORE INTO user_tasks (user_id, task_id, completed_at) "
            "VALUES (?, ?, ?)",
            (user_id, task_id, int(time.time())),
        )

    def get_user_completed_tasks(self, user_id: int) -> list:
        rows = self.conn.execute(
            "SELECT task_id FROM user_tasks WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        return [r["task_id"] for r in rows]

    # ──────────────────────────────────────────────
    #  👍  LIKE CHALLENGE
    # ──────────────────────────────────────────────
    def get_like_challenge(self, user_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM like_challenges "
            "WHERE user_id = ? AND active = 1 "
            "ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None

    def set_like_challenge(self, user_id: int, target_likes: int,
                           cost: int, deadline: int) -> int:
        # Deactivate old challenges
        self.conn.execute(
            "UPDATE like_challenges SET active = 0 WHERE user_id = ?",
            (user_id,),
        )
        cur = self.conn.execute(
            "INSERT INTO like_challenges "
            "(user_id, target_likes, current_likes, cost, deadline, active) "
            "VALUES (?, ?, 0, ?, ?, 1)",
            (user_id, target_likes, cost, deadline),
        )
        return cur.lastrowid

    def update_like_progress(self, challenge_id: int, current_likes: int):
        self.conn.execute(
            "UPDATE like_challenges SET current_likes = ? WHERE id = ?",
            (current_likes, challenge_id),
        )

    def deactivate_like_challenge(self, challenge_id: int):
        self.conn.execute(
            "UPDATE like_challenges SET active = 0 WHERE id = ?",
            (challenge_id,),
        )

    # ──────────────────────────────────────────────
    #  🔗  FORCE JOIN CHANNELS
    # ──────────────────────────────────────────────
    def get_force_join_channels(self) -> list:
        rows = self.conn.execute(
            "SELECT * FROM force_join WHERE active = 1"
        ).fetchall()
        return [dict(r) for r in rows]

    def add_force_join_channel(self, username: str, title: str) -> int:
        cur = self.conn.execute(
            "INSERT OR REPLACE INTO force_join "
            "(channel_username, channel_title, active) "
            "VALUES (?, ?, 1)",
            (username, title),
        )
        return cur.lastrowid

    def remove_force_join_channel(self, channel_id: int):
        self.conn.execute(
            "DELETE FROM force_join WHERE id = ?", (channel_id,)
        )

    def set_force_join_active(self, channel_id: int, active: bool):
        self.conn.execute(
            "UPDATE force_join SET active = ? WHERE id = ?",
            (1 if active else 0, channel_id),
        )

    # ──────────────────────────────────────────────
    #  ⭐  STAR ORDERS
    # ──────────────────────────────────────────────
    def add_star_order(self, user_id: int, stars_amount: int,
                       dp_amount: int) -> int:
        cur = self.conn.execute(
            "INSERT INTO star_orders "
            "(user_id, stars_amount, dp_amount, status, created_at) "
            "VALUES (?, ?, ?, 'pending', ?)",
            (user_id, stars_amount, dp_amount, int(time.time())),
        )
        return cur.lastrowid

    def set_star_order_status(self, order_id: int, status: str):
        self.conn.execute(
            "UPDATE star_orders SET status = ? WHERE id = ?",
            (status, order_id),
        )

    def get_pending_star_orders(self) -> list:
        rows = self.conn.execute(
            "SELECT * FROM star_orders WHERE status = 'pending' "
            "ORDER BY created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    # ──────────────────────────────────────────────
    #  💰  BUY DP ORDERS
    # ──────────────────────────────────────────────
    def add_buy_dp_order(self, user_id: int, dp_amount: int,
                         price: int) -> int:
        cur = self.conn.execute(
            "INSERT INTO buy_dp_orders "
            "(user_id, dp_amount, price, status, created_at) "
            "VALUES (?, ?, ?, 'pending', ?)",
            (user_id, dp_amount, price, int(time.time())),
        )
        return cur.lastrowid

    def set_buy_dp_order_status(self, order_id: int, status: str):
        self.conn.execute(
            "UPDATE buy_dp_orders SET status = ? WHERE id = ?",
            (status, order_id),
        )

    def get_pending_buy_dp_orders(self) -> list:
        rows = self.conn.execute(
            "SELECT * FROM buy_dp_orders WHERE status = 'pending' "
            "ORDER BY created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    # ──────────────────────────────────────────────
    #  🔧  UTILITY
    # ──────────────────────────────────────────────
    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
