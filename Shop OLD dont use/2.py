# support_bot.py - ПОЛНАЯ ВЕРСИЯ с блокировкой пользователей

import telebot
from telebot import types
import psycopg2
import time

# ------------ НАСТРОЙКИ ------------
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "FlowerShop",
    "user": "postgres",
    "password": "1234567890"
}

BOT_TOKEN_SUPPORT = "8568991857:AAFBze2tyzOnUcUQooO7atJlRs1JVruORPw"
bot = telebot.TeleBot(BOT_TOKEN_SUPPORT)

# Состояния
OPEN = {}  # админы: chat_id -> ticket data
USER_STATE = {}  # пользователи: chat_id -> ticket data


def get_conn():
    return psycopg2.connect(**DB_CONFIG)


# ---------- ПРОВЕРКА АДМИНА ----------
def is_admin(tg_id: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM admin WHERE tg_id = %s AND is_active = TRUE LIMIT 1", (tg_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return bool(row)


# ---------- БЛОКИРОВКА ПОЛЬЗОВАТЕЛЕЙ ----------
def is_user_blocked(user_id: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT is_blocked FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return bool(row[0]) if row else False


def check_user_blocked(user_id: int, chat_id: int):
    if is_user_blocked(user_id):
        bot.send_message(chat_id,
                         "❌ Вы заблокированы и не можете создавать тикеты.\n"
                         "Обратитесь к администрации.")
        return True
    return False


def block_user(user_id: int, admin_tg_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
                UPDATE users
                SET is_blocked = TRUE,
                    blocked_by = %s,
                    blocked_at = NOW()
                WHERE id = %s
                """, (admin_tg_id, user_id))
    conn.commit()
    cur.close()
    conn.close()


def unblock_user(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
                UPDATE users
                SET is_blocked = FALSE,
                    blocked_by = NULL,
                    blocked_at = NULL
                WHERE id = %s
                """, (user_id,))
    conn.commit()
    cur.close()
    conn.close()


# ---------- DB ФУНКЦИИ ТИКЕТОВ ----------
def list_unread_tickets(limit=50):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
                SELECT t.id, u.tg_id, COALESCE(u.username, ''), t.last_message
                FROM support_tickets t
                         JOIN users u ON u.id = t.user_id
                WHERE t.unread_by_support = TRUE
                  AND t.status IN ('open', 'in_progress')
                ORDER BY t.last_message DESC LIMIT %s
                """, (limit,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_ticket_and_user(ticket_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
                SELECT t.id, t.user_id, u.tg_id, COALESCE(u.username, ''), t.status, t.locked_by
                FROM support_tickets t
                         JOIN users u ON u.id = t.user_id
                WHERE t.id = %s
                """, (ticket_id,))
    r = cur.fetchone()
    cur.close()
    conn.close()
    return r


def get_messages(ticket_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT from_user, message_text, created_at FROM support_messages WHERE ticket_id = %s ORDER BY created_at",
        (ticket_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def set_ticket_read_for_support(ticket_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE support_tickets SET unread_by_support = FALSE WHERE id = %s", (ticket_id,))
    conn.commit()
    cur.close()
    conn.close()


def set_ticket_locked(ticket_id, operator_tg):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE support_tickets SET locked_by = %s, status = 'in_progress' WHERE id = %s",
                (operator_tg, ticket_id))
    conn.commit()
    cur.close()
    conn.close()


def set_ticket_unlocked(ticket_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE support_tickets SET locked_by = NULL WHERE id = %s", (ticket_id,))
    conn.commit()
    cur.close()
    conn.close()


def close_ticket(ticket_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE support_tickets SET status = 'closed' WHERE id = %s", (ticket_id,))
    conn.commit()
    cur.close()
    conn.close()


def get_or_create_user(tg_user):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE tg_id = %s", (tg_user.id,))
    row = cur.fetchone()
    if row:
        user_id = row[0]
    else:
        gen_ref = str(tg_user.id)  # ✅ ИСПРАВЛЕНИЕ ref_code
        cur.execute("""
                    INSERT INTO users (tg_id, username, first_name, last_name, ref_code)
                    VALUES (%s, %s, %s, %s, %s) RETURNING id
                    """, (tg_user.id, tg_user.username, tg_user.first_name, tg_user.last_name, gen_ref))
        user_id = cur.fetchone()[0]
        conn.commit()
    cur.close()
    conn.close()
    return user_id


def create_ticket_for_user(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
                INSERT INTO support_tickets (user_id, status, last_message, unread_by_support, unread_by_user,
                                             locked_by)
                VALUES (%s, 'open', NOW(), TRUE, FALSE, NULL) RETURNING id
                """, (user_id,))
    ticket_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return ticket_id


def list_user_tickets(user_id, limit=10):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, status, last_message FROM support_tickets WHERE user_id = %s ORDER BY last_message DESC LIMIT %s",
        (user_id, limit))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def insert_support_message(ticket_id, from_user, text):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO support_messages (ticket_id, from_user, message_text) VALUES (%s,%s,%s)",
                (ticket_id, from_user, text))
    if from_user:
        cur.execute("UPDATE support_tickets SET last_message = NOW(), unread_by_support = TRUE WHERE id = %s",
                    (ticket_id,))
    else:
        cur.execute("UPDATE support_tickets SET last_message = NOW(), unread_by_user = TRUE WHERE id = %s",
                    (ticket_id,))
    conn.commit()
    cur.close()
    conn.close()


# ---------- КЛАВИАТУРЫ ----------
def kb_admin_main():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(types.KeyboardButton("📥 Входящие"))
    kb.row(types.KeyboardButton("🔎 Поиск по ID"), types.KeyboardButton("🧾 Закрытые"))
    kb.row(types.KeyboardButton("🚫 Заблокированные"), types.KeyboardButton("🔒 Блокировка юзера"))
    return kb


def kb_ticket_actions(in_work, ticket_id):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    if not in_work:
        kb.row(types.KeyboardButton("🟢 Взять в работу"))
    else:
        kb.row(types.KeyboardButton("✉️ Ответить"))
        kb.row(types.KeyboardButton("🔒 Закрыть тикет"), types.KeyboardButton("🚫 Заблокировать юзера"))
        kb.row(types.KeyboardButton("🔓 Освободить"))
    kb.row(types.KeyboardButton("⬅️ Назад"))
    return kb


def kb_user_main():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(types.KeyboardButton("🆕 Новый тикет"))
    kb.row(types.KeyboardButton("📜 Мои тикеты"))
    return kb


# ---------- /start ----------
@bot.message_handler(commands=['start'])
def cmd_start(message):
    tg_id = message.from_user.id
    tg_user = message.from_user

    if is_admin(tg_id):
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id FROM support_staff WHERE tg_id = %s", (tg_id,))
        if not cur.fetchone():
            cur.execute("INSERT INTO support_staff (tg_id, username) VALUES (%s,%s)",
                        (tg_id, tg_user.username))
            conn.commit()
        cur.close()
        conn.close()
        bot.send_message(message.chat.id, "🔧 Меню поддержки:", reply_markup=kb_admin_main())
    else:
        user_id = get_or_create_user(tg_user)
        if check_user_blocked(user_id, message.chat.id):
            return
        bot.send_message(message.chat.id, "👤 Меню пользователя:", reply_markup=kb_user_main())


# ========================================
# ✅ КРИТИЧЕСКИ ВАЖНЫЙ ПОРЯДОК ХЕНДЛЕРОВ:
# 1. ТОЧНЫЕ кнопки ПОЛЬЗОВАТЕЛЕЙ (ПЕРВЫМИ!)
# 2. ТОЧНЫЕ кнопки АДМИНОВ
# 3. СОСТОЯНИЯ
# 4. БЛОКИРОВКА (НОВЫЕ)
# 5. FALLBACK ПОСЛЕДНИМ
# ========================================

# ---------- 1. ПОЛЬЗОВАТЕЛЬСКИЕ КНОПКИ ----------
@bot.message_handler(func=lambda m: m.text == "🆕 Новый тикет")
def user_new_ticket(message):
    tg = message.from_user
    user_id = get_or_create_user(tg)

    if check_user_blocked(user_id, message.chat.id):
        return

    ticket_id = create_ticket_for_user(user_id)
    USER_STATE[message.chat.id] = {"mode": "writing", "ticket_id": ticket_id}

    bot.send_message(message.chat.id,
                     f"✅ Создан тикет #{ticket_id}\n\n"
                     f"📝 Напишите описание проблемы.\n"
                     f"Для завершения отправьте: *ГОТОВО*",
                     reply_markup=None, parse_mode='Markdown')


@bot.message_handler(func=lambda m: m.text == "📜 Мои тикеты")
def user_my_tickets(message):
    tg = message.from_user
    user_id = get_or_create_user(tg)

    if check_user_blocked(user_id, message.chat.id):
        return

    rows = list_user_tickets(user_id)
    if not rows:
        bot.send_message(message.chat.id, "📭 У вас нет тикетов.", reply_markup=kb_user_main())
        return

    lines = [f"#{r[0]} — {r[1]} — {r[2].strftime('%d.%m %H:%M') if r[2] else '-'}" for r in rows]
    bot.send_message(message.chat.id, "📋 Ваши тикеты:\n\n" + "\n".join(lines), reply_markup=kb_user_main())


# ---------- 2. АДМИНСКИЕ КНОПКИ ----------
@bot.message_handler(func=lambda m: m.text == "📥 Входящие")
def show_incoming(message):
    if not is_admin(message.from_user.id): return
    rows = list_unread_tickets()
    if not rows:
        bot.send_message(message.chat.id, "📭 Нет непрочитанных.", reply_markup=kb_admin_main())
        return
    text = "📥 Непрочитанные:\n\n" + "\n".join(
        [f"ID {r[0]} — @{r[2] or 'user'} ({r[1]}) — {r[3].strftime('%d.%m %H:%M')}" for r in rows])
    bot.send_message(message.chat.id, text)
    bot.send_message(message.chat.id, "🔍 Введите ID тикета:")
    bot.register_next_step_handler_by_chat_id(message.chat.id, open_ticket_handler)


@bot.message_handler(func=lambda m: m.text == "🔎 Поиск по ID")
def ask_id(message):
    if not is_admin(message.from_user.id): return
    bot.send_message(message.chat.id, "🔍 Введите ID тикета или TG ID:")
    bot.register_next_step_handler(message, open_ticket_handler)


@bot.message_handler(func=lambda m: m.text == "🧾 Закрытые")
def closed_list(message):
    if not is_admin(message.from_user.id): return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
                SELECT t.id, u.tg_id, COALESCE(u.username, ''), t.last_message
                FROM support_tickets t
                         JOIN users u ON u.id = t.user_id
                WHERE t.status = 'closed'
                ORDER BY t.last_message DESC LIMIT 50
                """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        bot.send_message(message.chat.id, "📭 Нет закрытых.", reply_markup=kb_admin_main())
        return
    text = "🧾 Закрытые:\n\n" + "\n".join(
        [f"ID {r[0]} — @{r[2] or 'user'} ({r[1]}) — {r[3].strftime('%d.%m %H:%M')}" for r in rows])
    bot.send_message(message.chat.id, text, reply_markup=kb_admin_main())


# ---------- 3. СОСТОЯНИЯ ----------
@bot.message_handler(func=lambda m: m.chat.id in USER_STATE)
def user_writing_ticket(message):
    chat_id = message.chat.id
    state = USER_STATE[chat_id]
    ticket_id = state["ticket_id"]
    txt = message.text.strip().lower()

    if txt == "готово":
        del USER_STATE[chat_id]
        bot.send_message(chat_id, f"✅ Тикет #{ticket_id} отправлен в поддержку!", reply_markup=kb_user_main())
        return

    insert_support_message(ticket_id, True, message.text)
    bot.send_message(chat_id, "📝 Добавлено. Продолжайте или *ГОТОВО*", parse_mode='Markdown')


@bot.message_handler(func=lambda m: m.chat.id in OPEN and is_admin(m.from_user.id))
def admin_ticket_actions(message):
    txt = message.text.strip()
    chat = message.chat.id
    store = OPEN[chat]
    ticket_id = store["ticket_id"]

    if txt == "🟢 Взять в работу":
        set_ticket_locked(ticket_id, message.from_user.id)
        OPEN[chat]["locked_by"] = message.from_user.id
        bot.send_message(chat, f"✅ #{ticket_id} взят в работу", reply_markup=kb_ticket_actions(True, ticket_id))

    elif txt == "✉️ Ответить":
        bot.send_message(chat, "💭 Ответ:")
        bot.register_next_step_handler_by_chat_id(chat, lambda m: answer_and_send(m, ticket_id, store["user_tg"], chat))

    elif txt == "🔒 Закрыть тикет":
        close_ticket(ticket_id)
        set_ticket_unlocked(ticket_id)
        del OPEN[chat]
        bot.send_message(chat, f"✅ #{ticket_id} закрыт", reply_markup=kb_admin_main())

    elif txt == "🔓 Освободить":
        set_ticket_unlocked(ticket_id)
        OPEN[chat]["locked_by"] = None
        bot.send_message(chat, f"🔓 #{ticket_id} освобождён", reply_markup=kb_ticket_actions(False, ticket_id))

    elif txt == "🚫 Заблокировать юзера":
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM support_tickets WHERE id = %s", (ticket_id,))
        user_id = cur.fetchone()[0]
        cur.close()
        conn.close()
        block_user(user_id, message.from_user.id)
        bot.send_message(chat, f"✅ Пользователь из тикета #{ticket_id} заблокирован!")

    elif txt == "⬅️ Назад":
        del OPEN[chat]
        bot.send_message(chat, "🔧 Меню поддержки:", reply_markup=kb_admin_main())


# ---------- Админ: открытие тикета ----------
def open_ticket_handler(message):
    if not is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "❌ Нет доступа", reply_markup=kb_user_main())
        return

    txt = message.text.strip()
    tid = None
    try:
        tid = int(txt)
    except:
        try:
            tg_search = int(txt)
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("""
                        SELECT t.id
                        FROM support_tickets t
                                 JOIN users u ON u.id = t.user_id
                        WHERE u.tg_id = %s
                        ORDER BY t.last_message DESC LIMIT 1
                        """, (tg_search,))
            r = cur.fetchone()
            cur.close()
            conn.close()
            tid = r[0] if r else None
        except:
            tid = None

    if not tid:
        bot.send_message(message.chat.id, "❌ Не найден", reply_markup=kb_admin_main())
        return

    row = get_ticket_and_user(tid)
    if not row:
        bot.send_message(message.chat.id, "❌ Тикет не найден", reply_markup=kb_admin_main())
        return

    ticket_id, _, user_tg, username, status, locked_by = row
    msgs = get_messages(ticket_id)
    set_ticket_read_for_support(ticket_id)

    OPEN[message.chat.id] = {"ticket_id": ticket_id, "user_tg": user_tg, "locked_by": locked_by}

    text = f"💬 #{ticket_id} ({status})\n\n"
    for fr, mtext, dt in msgs:
        who = "👤" if fr else "🔧"
        text += f"{who} ({dt.strftime('%d.%m %H:%M')}):\n{mtext}\n\n"

    bot.send_message(message.chat.id, text)
    bot.send_message(message.chat.id, "Действия:", reply_markup=kb_ticket_actions(bool(locked_by), ticket_id))


def answer_and_send(message, ticket_id, user_tg, chat_id):
    text = message.text.strip()
    if not text:
        bot.send_message(chat_id, "❌ Отмена", reply_markup=kb_ticket_actions(True, ticket_id))
        return
    insert_support_message(ticket_id, False, text)
    try:
        bot.send_message(user_tg, f"📩 #{ticket_id}:\n\n{text}")
    except:
        print("Ошибка отправки пользователю")
    bot.send_message(chat_id, "✅ Отправлено", reply_markup=kb_ticket_actions(True, ticket_id))


# ---------- 4. НОВЫЕ ХЕНДЛЕРЫ БЛОКИРОВКИ ----------
@bot.message_handler(func=lambda m: m.text == "🚫 Заблокированные")
def show_blocked_users(message):
    if not is_admin(message.from_user.id): return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
                SELECT u.tg_id, u.username, u.blocked_at, a.username as blocker
                FROM users u
                         LEFT JOIN admin a ON a.tg_id = u.blocked_by
                WHERE u.is_blocked = TRUE
                ORDER BY u.blocked_at DESC LIMIT 20
                """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        bot.send_message(message.chat.id, "👥 Нет заблокированных.", reply_markup=kb_admin_main())
        return

    text = "🚫 Заблокированные:\n\n" + "\n".join(
        [f"@{r[1] or 'user'} ({r[0]}) — {r[2].strftime('%d.%m')} — @{r[3] or 'admin'}" for r in rows]
    )
    bot.send_message(message.chat.id, text, reply_markup=kb_admin_main())


@bot.message_handler(func=lambda m: m.text == "🔒 Блокировка юзера")
def ask_block_user(message):
    if not is_admin(message.from_user.id): return
    bot.send_message(message.chat.id, "🔍 Введите TG ID или username для блокировки:")
    bot.register_next_step_handler(message, handle_block_user)


def handle_block_user(message):
    if not is_admin(message.from_user.id): return

    txt = message.text.strip()
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
                SELECT id
                FROM users
                WHERE tg_id = %s
                   OR username = %s
                   OR username ILIKE %s
                """, (txt, txt, f"%{txt}%"))
    row = cur.fetchone()

    if not row:
        bot.send_message(message.chat.id, "❌ Пользователь не найден.", reply_markup=kb_admin_main())
        return

    user_id = row[0]
    block_user(user_id, message.from_user.id)
    bot.send_message(message.chat.id, f"✅ Пользователь заблокирован!", reply_markup=kb_admin_main())


# ---------- 5. FALLBACK ----------
@bot.message_handler(func=lambda m: True)
def fallback(message):
    if message.chat.id in OPEN and is_admin(message.from_user.id): return
    if message.chat.id in USER_STATE: return

    if is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "🔧 Выберите:", reply_markup=kb_admin_main())
    else:
        bot.send_message(message.chat.id, "👤 Выберите:", reply_markup=kb_user_main())


if __name__ == "__main__":
    print("🚀 Support bot started...")
    bot.infinity_polling()
