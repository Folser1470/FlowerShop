# admin_bot.py
import telebot
from telebot import types
import psycopg2
import logging

ADMIN_BOT_TOKEN = "8195028424:AAFBI74NxM_aE6XRcOUm0VZ8R5GyastnBho"

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "FlowerShop",
    "user": "postgres",
    "password": "1234567890"
}

bot = telebot.TeleBot(ADMIN_BOT_TOKEN, parse_mode="HTML")

admin_state: dict[int, dict] = {}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ------------ БД ------------
def db_connect():
    return psycopg2.connect(**DB_CONFIG)


def is_admin(tg_id: int) -> bool:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM admin WHERE tg_id = %s AND is_active = TRUE LIMIT 1", (tg_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return bool(row)


def get_unread_orders_for_admin(limit: int = 50):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT 
            o.id,
            o.user_id,
            COALESCE(o.city, ''),
            COALESCE(o.payment_method, ''),
            COALESCE(o.total_amount, 0),
            COALESCE(o.status, ''),
            u.tg_id,
            COALESCE(u.username, '')
        FROM orders o
        JOIN users u ON u.id = o.user_id
        WHERE o.unread_by_admin = TRUE
        ORDER BY o.id
        LIMIT %s
    """, (limit,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_orders_waiting_address(limit: int = 50):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT 
            o.id,
            o.user_id,
            COALESCE(o.city, ''),
            COALESCE(o.payment_method, ''),
            COALESCE(o.total_amount, 0),
            COALESCE(o.status, ''),
            u.tg_id,
            COALESCE(u.username, '')
        FROM orders o
        JOIN users u ON u.id = o.user_id
        WHERE o.status = 'ожидает адреса'
        ORDER BY o.id
        LIMIT %s
    """, (limit,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_order(order_id: int):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT 
            o.id,
            o.user_id,
            COALESCE(o.city, ''),
            COALESCE(o.payment_method, ''),
            COALESCE(o.total_amount, 0),
            COALESCE(o.status, ''),
            COALESCE(o.delivery_info, ''),
            COALESCE(o.delivery_photo_file_id, ''),
            o.unread_by_admin,
            o.unread_by_user,
            u.tg_id,
            COALESCE(u.username, '')
        FROM orders o
        JOIN users u ON u.id = o.user_id
        WHERE o.id = %s
    """, (order_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def update_order_status(order_id: int, new_status: str):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("UPDATE orders SET status = %s WHERE id = %s", (new_status, order_id))
    conn.commit()
    cur.close()
    conn.close()


def mark_order_read_by_admin(order_id: int):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("UPDATE orders SET unread_by_admin = FALSE WHERE id = %s", (order_id,))
    conn.commit()
    cur.close()
    conn.close()


def mark_order_unread_for_user(order_id: int):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("UPDATE orders SET unread_by_user = TRUE WHERE id = %s", (order_id,))
    conn.commit()
    cur.close()
    conn.close()


def save_delivery_info(order_id: int, text: str | None, photo_file_id: str | None):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        UPDATE orders
        SET 
            delivery_info = COALESCE(%s, delivery_info),
            delivery_photo_file_id = COALESCE(%s, delivery_photo_file_id),
            status = 'готов к выдаче'
        WHERE id = %s
    """, (text, photo_file_id, order_id))
    conn.commit()
    cur.close()
    conn.close()


# ------------ Клавиатуры ------------
def kb_admin_main():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(types.KeyboardButton("📥 Непрочитанные заказы"))
    kb.row(types.KeyboardButton("📦 Заказы (ждут адрес)"))
    kb.row(types.KeyboardButton("🔎 Найти заказ по ID"))
    return kb


def kb_order_actions(order_id: int):
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("📨 Отправить адрес покупателю", callback_data=f"sendaddr_{order_id}")
    )
    kb.add(
        types.InlineKeyboardButton("⚙️ Изменить статус", callback_data=f"chstatus_{order_id}")
    )
    return kb


def kb_status_choice(order_id: int):
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("ожидает оплаты", callback_data=f"status_{order_id}_ожидает оплаты"),
        types.InlineKeyboardButton("ожидает адреса", callback_data=f"status_{order_id}_ожидает адреса"),
    )
    kb.add(
        types.InlineKeyboardButton("готов к выдаче", callback_data=f"status_{order_id}_готов к выдаче"),
        types.InlineKeyboardButton("отменён", callback_data=f"status_{order_id}_отменён"),
    )
    return kb


# ------------ /start ------------
@bot.message_handler(commands=['start'])
def cmd_start(message: telebot.types.Message):
    tg_id = message.from_user.id

    if not is_admin(tg_id):
        bot.send_message(
            message.chat.id,
            "✅ Заказ принят.\nС вами скоро свяжутся и вышлют адрес."
        )
        return

    bot.send_message(
        message.chat.id,
        "🔧 Меню администратора заказов:",
        reply_markup=kb_admin_main()
    )


# ------------ Меню админа ------------
@bot.message_handler(func=lambda m: m.text == "📥 Непрочитанные заказы")
def show_unread_orders(message: telebot.types.Message):
    if not is_admin(message.from_user.id):
        return

    rows = get_unread_orders_for_admin()
    if not rows:
        bot.send_message(message.chat.id, "📭 Непрочитанных заказов нет.", reply_markup=kb_admin_main())
        return

    for r in rows:
        order_id, user_id, city, pay_method, total_amount, status, user_tg, username = r
        text = (
            f"🆕 <b>Заказ #{order_id}</b>\n"
            f"👤 user_id: <code>{user_id}</code>, tg_id: <code>{user_tg}</code>, "
            f"username: @{username or 'user'}\n"
            f"🏙 Город: <b>{city}</b>\n"
            f"💳 Оплата: <b>{pay_method}</b>\n"
            f"💵 Сумма: <b>{total_amount:.0f}₽</b>\n"
            f"📌 Статус: <b>{status}</b>\n"
            f"🔔 Непрочитанный"
        )
        bot.send_message(message.chat.id, text, reply_markup=kb_order_actions(order_id))


@bot.message_handler(func=lambda m: m.text == "📦 Заказы (ждут адрес)")
def show_orders_waiting_address(message: telebot.types.Message):
    if not is_admin(message.from_user.id):
        return

    rows = get_orders_waiting_address()
    if not rows:
        bot.send_message(
            message.chat.id,
            "📭 Нет заказов со статусом <b>ожидает адреса</b>.",
            reply_markup=kb_admin_main()
        )
        return

    for r in rows:
        order_id, user_id, city, pay_method, total_amount, status, user_tg, username = r
        text = (
            f"📦 <b>Заказ #{order_id}</b>\n"
            f"👤 user_id: <code>{user_id}</code>, tg_id: <code>{user_tg}</code>, "
            f"username: @{username or 'user'}\n"
            f"🏙 Город: <b>{city}</b>\n"
            f"💳 Оплата: <b>{pay_method}</b>\n"
            f"💵 Сумма: <b>{total_amount:.0f}₽</b>\n"
            f"📌 Статус: <b>{status}</b>"
        )
        bot.send_message(message.chat.id, text, reply_markup=kb_order_actions(order_id))


@bot.message_handler(func=lambda m: m.text == "🔎 Найти заказ по ID")
def ask_order_id(message: telebot.types.Message):
    if not is_admin(message.from_user.id):
        return

    bot.send_message(message.chat.id, "Введите <b>ID заказа</b>:", reply_markup=kb_admin_main())
    bot.register_next_step_handler(message, handle_order_id_input)


def handle_order_id_input(message: telebot.types.Message):
    if not is_admin(message.from_user.id):
        return

    try:
        order_id = int(message.text.strip())
    except ValueError:
        bot.send_message(message.chat.id, "❌ Неверный ID.", reply_markup=kb_admin_main())
        return

    row = get_order(order_id)
    if not row:
        bot.send_message(message.chat.id, "❌ Заказ не найден.", reply_markup=kb_admin_main())
        return

    order_id, user_id, city, pay_method, total_amount, status, del_info, del_photo_id, unread_a, unread_u, user_tg, username = row
    mark_order_read_by_admin(order_id)

    badge = " 🔔" if unread_a else ""
    text = (
        f"📄 <b>Заказ #{order_id}</b>{badge}\n\n"
        f"👤 user_id: <code>{user_id}</code>, tg_id: <code>{user_tg}</code>, "
        f"username: @{username or 'user'}\n"
        f"🏙 Город: <b>{city}</b>\n"
        f"💳 Оплата: <b>{pay_method}</b>\n"
        f"💵 Сумма: <b>{total_amount:.0f}₽</b>\n"
        f"📌 Статус: <b>{status}</b>\n\n"
        f"🚚 Доставка: {del_info or '—'}"
    )
    bot.send_message(message.chat.id, text, reply_markup=kb_order_actions(order_id))


# ------------ Callback-кнопки ------------
@bot.callback_query_handler(func=lambda c: c.data.startswith("sendaddr_"))
def cb_sendaddr(call: telebot.types.CallbackQuery):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "Нет доступа.")
        return

    admin_id = call.message.chat.id
    order_id = int(call.data.split("_")[1])

    row = get_order(order_id)
    if not row:
        bot.answer_callback_query(call.id, "Заказ не найден.")
        return

    order_id, user_id, city, pay_method, total_amount, status, del_info, del_photo_id, unread_a, unread_u, user_tg, username = row
    mark_order_read_by_admin(order_id)

    admin_state[admin_id] = {
        "order_id": order_id,
        "user_tg_id": user_tg,
        "step": "waiting_address"
    }

    bot.answer_callback_query(call.id)
    bot.send_message(
        admin_id,
        f"✉️ Отправка адреса для заказа #{order_id}.\n\n"
        f"Отправьте текст или фото с подписью — оно уйдёт покупателю."
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("chstatus_"))
def cb_change_status(call: telebot.types.CallbackQuery):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "Нет доступа.")
        return

    order_id = int(call.data.split("_")[1])
    row = get_order(order_id)
    if not row:
        bot.answer_callback_query(call.id, "Заказ не найден.")
        return

    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        f"Выберите новый статус для заказа #{order_id}:",
        reply_markup=kb_status_choice(order_id)
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("status_"))
def cb_set_status(call: telebot.types.CallbackQuery):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "Нет доступа.")
        return

    parts = call.data.split("_", 2)
    order_id = int(parts[1])
    new_status = parts[2]

    update_order_status(order_id, new_status)
    mark_order_read_by_admin(order_id)
    bot.answer_callback_query(call.id, "Статус обновлён.")

    row = get_order(order_id)
    if not row:
        bot.send_message(call.message.chat.id, "Статус обновлён, но заказ не найден.")
        return

    order_id, user_id, city, pay_method, total_amount, status, del_info, del_photo_id, unread_a, unread_u, user_tg, username = row
    text = (
        f"✅ Статус заказа #{order_id} изменён.\n"
        f"Текущий статус: <b>{status}</b>"
    )
    bot.send_message(call.message.chat.id, text, reply_markup=kb_order_actions(order_id))


# ------------ Приём адреса от админа ------------
@bot.message_handler(content_types=['text', 'photo', 'document', 'video'])
def receive_address_or_text(message: telebot.types.Message):
    admin_id = message.chat.id

    if admin_id not in admin_state:
        return

    state = admin_state[admin_id]
    if state.get("step") != "waiting_address":
        return

    order_id = state["order_id"]
    user_tg_id = state["user_tg_id"]

    # пересылаем сообщение покупателю
    bot.copy_message(
        chat_id=user_tg_id,
        from_chat_id=message.chat.id,
        message_id=message.message_id
    )

    # сохраняем инфу
    delivery_text = None
    photo_file_id = None

    if message.content_type == "photo":
        photo_file_id = message.photo[-1].file_id
        delivery_text = message.caption or ""
    elif message.content_type == "text":
        delivery_text = message.text or ""

    save_delivery_info(order_id, text=delivery_text, photo_file_id=photo_file_id)
    mark_order_unread_for_user(order_id)
    mark_order_read_by_admin(order_id)

    bot.send_message(
        admin_id,
        f"✅ Сообщение отправлено пользователю.\n"
        f"Заказ #{order_id} переведён в статус <b>готов к выдаче</b>.",
        reply_markup=kb_admin_main()
    )

    del admin_state[admin_id]


if __name__ == "__main__":
    logger.info("Admin bot started...")
    bot.infinity_polling(skip_pending=True)
