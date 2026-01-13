# shop_bot.py — рефералка, промокоды, авто-скидка 3% по реф-ссылке и кнопка "Оплатить заказ"

import telebot
from telebot import types
import psycopg2
from datetime import datetime

# ------------ НАСТРОЙКИ ------------
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "FlowerShop",
    "user": "postgres",
    "password": "1234567890"
}

BOT_TOKEN_SHOP = "8565390672:AAEy8y12wbbdfwbV5M3EOgZClq9RbCRfzqo"

ADMIN_CHAT_ID = 123456789

SUPPORT_BOT_USERNAME = "weeeeeeeetsup_bot"
ADMIN_BOT_USERNAME = "weeeeeeeetADM_bot"

bot = telebot.TeleBot(BOT_TOKEN_SHOP)

# ------------ Глобальные состояния ------------
user_state: dict[int, str] = {}
TRANSIENT: dict[int, dict] = {}


# ------------ Утилиты БД ------------
def get_conn():
    return psycopg2.connect(**DB_CONFIG)


def get_or_create_user_by_tg(tg_id, username=None, first_name=None, last_name=None, ref_code=None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE tg_id = %s", (tg_id,))
    row = cur.fetchone()
    if row:
        user_id = row[0]
    else:
        gen_ref = str(tg_id)
        cur.execute(
            "INSERT INTO users (tg_id, username, first_name, last_name, ref_code) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (tg_id, username, first_name, last_name, gen_ref)
        )
        user_id = cur.fetchone()[0]
        conn.commit()
    if ref_code:
        try:
            cur.execute("SELECT id FROM users WHERE ref_code = %s", (ref_code,))
            ref = cur.fetchone()
            if ref:
                referrer_id = ref[0]
                if referrer_id != user_id:
                    cur.execute(
                        "SELECT 1 FROM referrals WHERE referrer_id=%s AND referee_id=%s",
                        (referrer_id, user_id)
                    )
                    if not cur.fetchone():
                        cur.execute(
                            "INSERT INTO referrals (referrer_id, referee_id) VALUES (%s,%s)",
                            (referrer_id, user_id)
                        )
                        conn.commit()
        except Exception:
            pass
    cur.close()
    conn.close()
    return user_id


def get_user_id_by_tg(tg_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE tg_id = %s", (tg_id,))
    r = cur.fetchone()
    cur.close()
    conn.close()
    return r[0] if r else None


def get_cart_items(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT c.product_id, p.name, c.quantity, c.price
        FROM cart_items c 
        JOIN products p ON p.id = c.product_id
        WHERE c.user_id = %s 
        ORDER BY c.id
    """, (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_order(order_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT payment_method, total_amount, status 
        FROM orders 
        WHERE id = %s
    """, (order_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


# ------------ ПРОМОКОДЫ ------------
def validate_promo_code(code: str):
    """
    Возвращает (valid: bool, discount: float, error: str | None)
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, discount_percent, max_uses, uses_count, is_active, expires_at 
        FROM promo_codes 
        WHERE LOWER(code) = LOWER(%s)
    """, (code,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return False, 0.0, "Промокод не найден."

    promo_id, discount, max_uses, uses_count, is_active, expires_at = row

    if not is_active:
        return False, 0.0, "Промокод неактивен."
    if expires_at and expires_at < datetime.now():
        return False, 0.0, "Срок действия промокода истёк."
    if max_uses is not None and uses_count >= max_uses:
        return False, 0.0, "Лимит использования промокода исчерпан."

    return True, float(discount), None


def apply_promo_to_cart(user_id: int, promo_code: str):
    """
    Применяет промокод к корзине пользователя.
    Возвращает (success: bool, message: str, applied_code: str | None)
    """
    valid, discount, error = validate_promo_code(promo_code)
    if not valid:
        return False, error, None

    conn = get_conn()
    cur = conn.cursor()

    # проверяем, использовал ли уже этот промокод
    cur.execute("""
        SELECT 1 
        FROM user_promo_uses up 
        JOIN promo_codes pc ON pc.id = up.promo_code_id
        WHERE up.user_id = %s AND LOWER(pc.code) = LOWER(%s)
    """, (user_id, promo_code))
    if cur.fetchone():
        cur.close()
        conn.close()
        return False, "Вы уже использовали этот промокод.", None

    # получаем id промокода
    cur.execute("SELECT id, discount_percent FROM promo_codes WHERE LOWER(code) = LOWER(%s)", (promo_code,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return False, "Промокод не найден.", None

    promo_id, discount_db = row
    discount_value = float(discount_db)

    # применяем скидку к корзине
    cur.execute("""
        UPDATE cart_items 
        SET price = ROUND(price * (1 - %s/100.0), 2)
        WHERE user_id = %s
    """, (discount_value, user_id))

    # записываем использование промокода
    cur.execute("""
        INSERT INTO user_promo_uses (user_id, promo_code_id, order_id)
        VALUES (%s, %s, NULL)
    """, (user_id, promo_id))

    # увеличиваем счётчик использований
    cur.execute("""
        UPDATE promo_codes 
        SET uses_count = uses_count + 1
        WHERE id = %s
    """, (promo_id,))

    conn.commit()
    cur.close()
    conn.close()

    return True, f"✅ Промокод применён. Скидка {discount_value:.0f}%.", promo_code.upper()


# ------------ Клавиатуры ------------
def kb_main():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(types.KeyboardButton("🛒 Покупка"))
    markup.row(types.KeyboardButton("💬 Отзывы"), types.KeyboardButton("👥 Реферальная система"))
    markup.row(types.KeyboardButton(f"🛟 Поддержка (@{SUPPORT_BOT_USERNAME})"))
    markup.row(types.KeyboardButton("📦 Мои заказы"))
    return markup


def kb_purchase():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(types.KeyboardButton("📍 Выбрать город"), types.KeyboardButton("📦 Товары"))
    markup.row(types.KeyboardButton("🛒 Корзина"), types.KeyboardButton("⬅️ Назад"))
    return markup


def kb_products_list(items):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for pid, name in items:
        markup.row(types.KeyboardButton(f"🆔{pid} {name}"))
    markup.row(types.KeyboardButton("⬅️ Назад в Покупку"))
    return markup


def kb_product_detail(prices):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for qty, price in prices:
        markup.row(types.KeyboardButton(f"{qty} шт. — {price:.0f}₽"))
    markup.row(types.KeyboardButton("⬅️ К товарам"))
    return markup


def kb_cart():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(types.KeyboardButton("🎟 Промокод"))
    markup.row(types.KeyboardButton("✅ Оформить заказ"), types.KeyboardButton("🗑 Очистить корзину"))
    markup.row(types.KeyboardButton("⬅️ Назад в Покупку"))
    return markup


def kb_pay_order(order_id: int):
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            "💳 Оплатить заказ",
            callback_data=f"pay_{order_id}"
        )
    )
    return markup


# ------------ /start ------------
@bot.message_handler(commands=['start'])
def cmd_start(message):
    parts = message.text.split(maxsplit=1)
    ref_code = parts[1].strip() if len(parts) == 2 else None

    tg = message.from_user
    get_or_create_user_by_tg(
        tg.id, tg.username, tg.first_name, tg.last_name, ref_code=ref_code
    )

    # если человек пришёл по реферальной ссылке (start=<ref_code>) — ставим флаг авто-скидки
    if ref_code:
        TRANSIENT[message.chat.id] = TRANSIENT.get(message.chat.id, {})
        TRANSIENT[message.chat.id]['ref_discount_pending'] = True
        TRANSIENT[message.chat.id]['ref_code'] = ref_code

    user_state[message.chat.id] = 'main'
    bot.send_message(message.chat.id, "Здравствуйте! Главное меню:", reply_markup=kb_main())


# ------------ Мои заказы ------------
def get_user_orders(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, status, total_amount, unread_by_user, created_at
        FROM orders
        WHERE user_id = %s
        ORDER BY created_at DESC
        LIMIT 10
    """, (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def mark_orders_read_for_user(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE orders SET unread_by_user = FALSE WHERE user_id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()


def show_user_orders(chat_id: int, user_id: int):
    rows = get_user_orders(user_id)
    if not rows:
        bot.send_message(chat_id, "У вас пока нет заказов.", reply_markup=kb_main())
        return

    # Общий список
    lines = []
    for oid, status, total, unread, created in rows:
        badge = " 🔔" if unread else ""
        dt = created.strftime("%d.%m %H:%M") if created else "-"
        lines.append(f"#{oid} — {status} — {total:.0f}₽ — {dt}{badge}")

    text = "Ваши заказы:\n\n" + "\n".join(lines)
    bot.send_message(chat_id, text, reply_markup=kb_main())

    # Отдельные сообщения с кнопкой оплаты для заказов, ожидающих оплаты
    for oid, status, total, unread, created in rows:
        if status == "ожидает оплаты":
            msg = (
                f"Заказ #{oid}\n"
                f"Сумма к оплате: {total:.0f}₽\n"
                f"Статус: {status}"
            )
            bot.send_message(chat_id, msg, reply_markup=kb_pay_order(oid))

    mark_orders_read_for_user(user_id)


# ------------ Callback: оплата заказа ------------
@bot.callback_query_handler(func=lambda c: c.data.startswith("pay_"))
def cb_pay_order(call: telebot.types.CallbackQuery):
    try:
        order_id = int(call.data.split("_")[1])
    except (IndexError, ValueError):
        bot.answer_callback_query(call.id, "Некорректный ID заказа.")
        return

    row = get_order(order_id)
    if not row:
        bot.answer_callback_query(call.id, "Заказ не найден.")
        return

    method, total, status = row

    if status != "ожидает оплаты":
        bot.answer_callback_query(call.id, "Этот заказ уже не требует оплаты.")
        return

    if method == "SBP":
        pay_info = "Реквизиты СБП: 2200 0000 0000 0000"
    elif method == "YUMONEY":
        pay_info = "ЮMoney кошелёк: 4100 0000 0000 000"
    else:
        pay_info = "USDT TRC20: TXXXXXXXXXXXXXXXXXXX"

    text = (
        f"Повторная оплата заказа #{order_id}.\n"
        f"Сумма: {total:.0f}₽\n\n"
        f"{pay_info}\n\n"
        f"После оплаты обязательно напишите @{ADMIN_BOT_USERNAME} "
        f"и отправьте ID заказа!"
    )

    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, text)


# ------------ Главный роутер ------------
@bot.message_handler(func=lambda m: True)
def text_router(message):
    txt = (message.text or "").strip()
    chat = message.chat.id
    state = user_state.get(chat, 'main')

    # универсальный "назад"
    if txt in ("⬅️ Назад", "⬅️ Назад в Покупку", "⬅️ К товарам"):
        user_state[chat] = 'main'
        bot.send_message(chat, "Главное меню:", reply_markup=kb_main())
        return

    # MAIN
    if state == 'main':
        if txt == "🛒 Покупка":
            user_state[chat] = 'purchase_menu'
            bot.send_message(chat, "Покупка — выберите:", reply_markup=kb_purchase())
            return

        if txt == "💬 Отзывы":
            user_state[chat] = 'reviews'
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.row("📝 Оставить отзыв", "👀 Посмотреть отзывы")
            markup.row("⬅️ Назад")
            bot.send_message(chat, "Раздел отзывов:", reply_markup=markup)
            return

        if txt == "👥 Реферальная система":
            tg = message.from_user
            uid = get_user_id_by_tg(tg.id)
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT ref_code, ref_balance FROM users WHERE id = %s", (uid,))
            rc, bal = cur.fetchone()
            cur.close()
            conn.close()
            bot.send_message(
                chat,
                f"Ваш промокод: {rc}\n"
                f"Бонусный баланс: {float(bal):.2f} ₽\n\n"
                f"Ваша реферальная ссылка:\n"
                f"https://t.me/{bot.get_me().username}?start={rc}",
                reply_markup=kb_main()
            )
            return

        if "Поддержка" in txt:
            bot.send_message(
                chat,
                f"Связаться с поддержкой можно здесь:\nhttps://t.me/{SUPPORT_BOT_USERNAME}",
                reply_markup=kb_main()
            )
            return

        if txt == "📦 Мои заказы":
            uid = get_user_id_by_tg(message.from_user.id)
            show_user_orders(chat, uid)
            return

    # PURCHASE MENU
    if state == 'purchase_menu':
        if txt == "📍 Выбрать город":
            user_state[chat] = 'choose_city'
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            for city in ["Москва", "Санкт-Петербург", "Казань", "Новосибирск", "Екатеринбург", "Саратов", "Другое"]:
                markup.row(city)
            markup.row("⬅️ Назад")
            bot.send_message(chat, "Выберите город:", reply_markup=markup)
            return

        if txt == "📦 Товары":
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT id, name FROM products WHERE is_active = TRUE ORDER BY id")
            rows = cur.fetchall()
            cur.close()
            conn.close()

            if not rows:
                bot.send_message(chat, "Товары не добавлены.", reply_markup=kb_purchase())
                return

            user_state[chat] = 'products'
            TRANSIENT[chat] = {'product_list': [r[0] for r in rows]}
            bot.send_message(chat, "Выберите товар:", reply_markup=kb_products_list(rows))
            return

        if txt == "🛒 Корзина":
            uid = get_user_id_by_tg(message.from_user.id)
            items = get_cart_items(uid)
            if not items:
                bot.send_message(chat, "Корзина пустая.", reply_markup=kb_purchase())
                return

            # авто-скидка 3% для зашедших по реферальной ссылке (один раз)
            tr = TRANSIENT.get(chat, {})
            if tr.get('ref_discount_pending'):
                success, msg_text, applied_code = apply_promo_to_cart(uid, "REF3")
                if success:
                    tr['promo_code'] = applied_code
                    tr['ref_discount_pending'] = False
                    TRANSIENT[chat] = tr
                    bot.send_message(chat, msg_text)
                    # перечитываем корзину уже со скидкой
                    items = get_cart_items(uid)
                else:
                    tr['ref_discount_pending'] = False
                    TRANSIENT[chat] = tr

            text = "🛒 Ваша корзина:\n\n"
            total = 0
            for pid, name, qty, price in items:
                text += f"{name} — {qty} шт. — {price:.0f}₽\n"
                total += float(price)
            text += f"\nИтого: {total:.0f}₽"

            user_state[chat] = 'cart'
            bot.send_message(chat, text, reply_markup=kb_cart())
            return

        if txt == "⬅️ Назад":
            user_state[chat] = 'main'
            bot.send_message(chat, "Главное меню:", reply_markup=kb_main())
            return

    # CHOOSE CITY
    if state == 'choose_city':
        city = txt
        uid = get_user_id_by_tg(message.from_user.id)
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE users SET city = %s WHERE id = %s", (city, uid))
        conn.commit()
        cur.close()
        conn.close()
        bot.send_message(chat, f"Город сохранён: {city}", reply_markup=kb_purchase())
        user_state[chat] = 'purchase_menu'
        return

    # PRODUCTS LIST
    if state == 'products' and txt.startswith("🆔"):
        pid = int(txt.split()[0].lstrip("🆔"))
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT name, description FROM products WHERE id=%s", (pid,))
        row = cur.fetchone()
        cur.execute("SELECT quantity, price FROM product_prices WHERE product_id=%s ORDER BY quantity", (pid,))
        prices = cur.fetchall()
        cur.close()
        conn.close()

        user_state[chat] = f'product_{pid}'
        TRANSIENT[chat] = {'product_id': pid}

        bot.send_message(
            chat,
            f"{row[0]}\n\n{row[1]}\n\nВыберите количество:",
            reply_markup=kb_product_detail(prices)
        )
        return

    # PRODUCT DETAIL
    if state.startswith('product_') and "шт." in txt:
        qty = int(txt.split()[0])
        pid = TRANSIENT.get(chat, {}).get('product_id')

        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT price FROM product_prices WHERE product_id=%s AND quantity=%s", (pid, qty))
        price = cur.fetchone()[0]

        uid = get_user_id_by_tg(message.from_user.id)
        cur.execute(
            "INSERT INTO cart_items (user_id, product_id, quantity, price) VALUES (%s,%s,%s,%s)",
            (uid, pid, qty, price)
        )
        conn.commit()
        cur.close()
        conn.close()

        bot.send_message(chat, "Товар добавлен в корзину.", reply_markup=kb_purchase())
        user_state[chat] = 'purchase_menu'
        TRANSIENT.pop(chat, None)
        return

    # CART
    if state == 'cart':
        uid = get_user_id_by_tg(message.from_user.id)

        if txt == "🗑 Очистить корзину":
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("DELETE FROM cart_items WHERE user_id=%s", (uid,))
            conn.commit()
            cur.close()
            conn.close()

            bot.send_message(chat, "Корзина очищена.", reply_markup=kb_purchase())
            user_state[chat] = 'purchase_menu'
            return

        if txt == "🎟 Промокод":
            user_state[chat] = 'promo_input'
            bot.send_message(chat, "Введите промокод:", reply_markup=kb_cart())
            return

        if txt == "✅ Оформить заказ":
            items = get_cart_items(uid)
            if not items:
                bot.send_message(chat, "Корзина пустая.", reply_markup=kb_purchase())
                user_state[chat] = 'purchase_menu'
                return

            total = sum(float(i[3]) for i in items)

            user_state[chat] = 'checkout'
            TRANSIENT[chat] = {
                'checkout_total': total,
                'promo_code': TRANSIENT.get(chat, {}).get('promo_code')
            }

            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.row("💳 СБП", "🪙 ЮMoney")
            markup.row("₿ Криптовалюта", "⬅️ Назад в Покупку")

            bot.send_message(chat, f"Итог: {total:.0f}₽\nВыберите способ оплаты:", reply_markup=markup)
            return

    # PROMO INPUT
    if state == 'promo_input':
        uid = get_user_id_by_tg(message.from_user.id)
        success, msg_text, applied_code = apply_promo_to_cart(uid, txt)

        if success and applied_code:
            items = get_cart_items(uid)
            text = msg_text + "\n\n🛒 Ваша корзина:\n\n"
            total = 0
            for pid, name, qty, price in items:
                text += f"{name} — {qty} шт. — {price:.0f}₽\n"
                total += float(price)
            text += f"\nИтого: {total:.0f}₽"

            tr = TRANSIENT.get(chat, {})
            tr['promo_code'] = applied_code
            TRANSIENT[chat] = tr

            bot.send_message(chat, text, reply_markup=kb_cart())
        else:
            bot.send_message(chat, f"❌ {msg_text}", reply_markup=kb_cart())

        user_state[chat] = 'cart'
        return

    # CHECKOUT
    if state == 'checkout':
        method_map = {
            "💳 СБП": "SBP",
            "🪙 ЮMoney": "YUMONEY",
            "₿ Криптовалюта": "CRYPTO"
        }

        if txt in method_map:
            method = method_map[txt]
            uid = get_user_id_by_tg(message.from_user.id)
            items = get_cart_items(uid)
            total = sum(float(i[3]) for i in items)

            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT city, username FROM users WHERE id=%s", (uid,))
            city, username = cur.fetchone()

            promo_code = TRANSIENT.get(chat, {}).get('promo_code')

            cur.execute(
                "INSERT INTO orders (user_id, city, total_amount, payment_method, status, "
                "unread_by_admin, unread_by_user, promo_code) "
                "VALUES (%s,%s,%s,%s,%s, TRUE, FALSE, %s) RETURNING id",
                (uid, city, total, method, "ожидает оплаты", promo_code)
            )
            order_id = cur.fetchone()[0]

            for p_id, name, qty, price in items:
                cur.execute(
                    "INSERT INTO order_items (order_id, product_id, quantity, price) VALUES (%s,%s,%s,%s)",
                    (order_id, p_id, qty, price)
                )

            cur.execute("DELETE FROM cart_items WHERE user_id=%s", (uid,))
            conn.commit()
            cur.close()
            conn.close()

            if method == "SBP":
                pay_info = "Реквизиты СБП: 2200 0000 0000 0000"
            elif method == "YUMONEY":
                pay_info = "ЮMoney кошелёк: 4100 0000 0000 000"
            else:
                pay_info = "USDT TRC20: TXXXXXXXXXXXXXXXXXXX"

            promo_line = f"\nПромокод: {promo_code}" if promo_code else ""

            bot.send_message(
                chat,
                f"Заказ #{order_id} создан.\nСумма: {total:.0f}₽{promo_line}\n\n"
                f"{pay_info}\n\n"
                f"После оплаты обязательно напишите @{ADMIN_BOT_USERNAME} и отправьте ID заказа!",
                reply_markup=kb_main()
            )

            # уведомление админу
            try:
                text_to_admin = (
                    f"🆕 Новый заказ #{order_id}\n"
                    f"👤 user_id: {uid}, username: @{username or 'user'}\n"
                    f"🏙 Город: {city}\n"
                    f"💳 Способ оплаты: {method}\n"
                    f"💵 Сумма: {total:.0f}₽\n"
                    f"🎟 Промокод: {promo_code or 'нет'}\n\n"
                    f"Позиции:\n"
                )
                for p_id, name, qty, price in items:
                    text_to_admin += f"- {name} — {qty} шт. — {price:.0f}₽\n"

                bot.send_message(ADMIN_CHAT_ID, text_to_admin)
            except Exception:
                pass

            user_state[chat] = 'main'
            TRANSIENT.pop(chat, None)
            return

    # REVIEWS
    if state == 'reviews':
        if txt == "📝 Оставить отзыв":
            user_state[chat] = 'reviews_leave'
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.row("⬅️ Назад")
            bot.send_message(chat, "Введите ваш отзыв:", reply_markup=markup)
            return

        if txt == "👀 Посмотреть отзывы":
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("""
                SELECT u.username, r.review_text, r.created_at
                FROM reviews r 
                JOIN users u ON u.id = r.user_id
                ORDER BY r.created_at DESC LIMIT 10
            """)
            rows = cur.fetchall()
            cur.close()
            conn.close()

            text = "Отзывы:\n\n" + "\n\n".join(
                f"@{r[0] or 'user'}: {r[1]} ({r[2].strftime('%d.%m.%Y')})"
                for r in rows
            ) if rows else "Отзывов нет."

            bot.send_message(chat, text, reply_markup=kb_main())
            user_state[chat] = 'main'
            return

    if state == 'reviews_leave' and txt != "⬅️ Назад":
        uid = get_user_id_by_tg(message.from_user.id)
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("INSERT INTO reviews (user_id, review_text) VALUES (%s,%s)", (uid, txt))
        conn.commit()
        cur.close()
        conn.close()

        bot.send_message(chat, "Спасибо! Отзыв сохранён.", reply_markup=kb_main())
        user_state[chat] = 'main'
        return

    # FALLBACK
    bot.send_message(chat, "Не понял команду. Главное меню:", reply_markup=kb_main())
    user_state[chat] = 'main'


if __name__ == "__main__":
    print("Shop bot started...")
    bot.infinity_polling(skip_pending=True)
