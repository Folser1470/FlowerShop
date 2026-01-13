
# shop_bot.py — рефералка, промокоды, авто-скидка 3% по реф-ссылке, ЮKassa оплата
# Поддержка дробных граммов (0.5, 1, 1.5, 2, 3, 5 гр), 14 товаров, 21 город

import telebot
from telebot import types
import psycopg2
from datetime import datetime
import uuid
import requests
import json
import time
import base64

# ------------ НАСТРОЙКИ ------------
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "FlowerShop",
    "user": "postgres",
    "password": "1234567890"
}

BOT_TOKEN_SHOP = "8565390672:AAEy8y12wbbdfwbV5M3EOgZClq9RbCRfzqo"

ADMIN_CHAT_ID = 1963178228

SUPPORT_BOT_USERNAME = "BoelSupport1337_Bot"
ADMIN_BOT_USERNAME = "BoelAdmin1337_Bot"

# Настройки ЮKassa (ЗАМЕНИТЕ НА ВАШИ ДАННЫЕ!)
YOOKASSA_SHOP_ID = "1162451"
YOOKASSA_SECRET_KEY = "test_s_t5pPL2HPmy7oLFXIDLFhwnz8jJpCLt4Kfd3vbNWCcyU"
YOOKASSA_API_URL = "https://api.yookassa.ru/v3/"

# Список всех 21 городов
ALL_CITIES = [
    "Саратов", "Москва", "Питер", "Екб", "Новосибирск",
    "Казань", "Нижний Новгород", "Самара", "Краснодар",
    "Челябинск", "Омск", "Ростов-на-Дону", "Уфа", "Пермь",
    "Сочи", "Калининград", "Владивосток", "Иркутск",
    "Красноярск", "Томск", "Тюмень"
]

bot = telebot.TeleBot(BOT_TOKEN_SHOP)

# ------------ Глобальные состояния ------------
user_state: dict[int, str] = {}
TRANSIENT: dict[int, dict] = {}


# ------------ Утилиты ЮKassa ------------
def create_yookassa_payment(order_id: int, amount: float, description: str = "Оплата заказа"):
    """Создание платежа в ЮKassa"""
    # Кодируем авторизацию в base64
    auth_string = f"{YOOKASSA_SHOP_ID}:{YOOKASSA_SECRET_KEY}"
    auth_encoded = base64.b64encode(auth_string.encode()).decode()

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {auth_encoded}",
        "Idempotence-Key": str(uuid.uuid4())
    }

    # Формируем payload для ЮKassa
    payload = {
        "amount": {
            "value": f"{amount:.2f}",
            "currency": "RUB"
        },
        "payment_method_data": {
            "type": "bank_card"
        },
        "confirmation": {
            "type": "redirect",
            "return_url": f"https://t.me/{bot.get_me().username}"
        },
        "capture": True,
        "description": f"{description} #{order_id}",
        "metadata": {
            "order_id": order_id,
            "telegram_id": "from_bot"
        }
    }

    try:
        print(f"🔄 Создание платежа для заказа #{order_id}, сумма: {amount} RUB")
        print(f"📤 Отправка запроса к ЮKassa API...")

        response = requests.post(
            f"{YOOKASSA_API_URL}payments",
            headers=headers,
            data=json.dumps(payload),
            timeout=30
        )

        print(f"📥 Ответ от ЮKassa: статус {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            payment_id = data["id"]
            confirmation_url = data["confirmation"]["confirmation_url"]

            print(f"✅ Платеж создан: {payment_id}")
            print(f"🔗 Ссылка для оплаты: {confirmation_url}")

            # Сохраняем в БД
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()
            cur.execute("""
                        INSERT INTO yookassa_payments
                            (order_id, payment_id, status, amount, payment_url, confirmation_token)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """, (order_id, payment_id, "pending", amount, confirmation_url, ""))
            conn.commit()
            cur.close()
            conn.close()

            return True, payment_id, confirmation_url
        else:
            error_msg = f"Ошибка API: {response.status_code}"
            try:
                error_data = response.json()
                if "description" in error_data:
                    error_msg = f"{error_msg} - {error_data['description']}"
                print(f"❌ Ответ от ЮKassa: {error_data}")
            except:
                print(f"❌ Не удалось распарсить ответ: {response.text[:200]}")
            return False, None, error_msg

    except requests.exceptions.Timeout:
        error_msg = "Таймаут подключения к ЮKassa (30 сек)"
        print(f"❌ {error_msg}")
        return False, None, error_msg
    except requests.exceptions.ConnectionError:
        error_msg = "Ошибка подключения к ЮKassa"
        print(f"❌ {error_msg}")
        return False, None, error_msg
    except Exception as e:
        error_msg = f"Неожиданная ошибка: {str(e)}"
        print(f"❌ {error_msg}")
        return False, None, error_msg


def check_yookassa_payment(payment_id: str):
    """Проверка статуса платежа в ЮKassa"""
    # Кодируем авторизацию в base64
    auth_string = f"{YOOKASSA_SHOP_ID}:{YOOKASSA_SECRET_KEY}"
    auth_encoded = base64.b64encode(auth_string.encode()).decode()

    headers = {
        "Authorization": f"Basic {auth_encoded}"
    }

    try:
        print(f"🔄 Проверка платежа {payment_id}...")

        response = requests.get(
            f"{YOOKASSA_API_URL}payments/{payment_id}",
            headers=headers,
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            status = data["status"]
            paid = data.get("paid", False)

            print(f"📊 Статус платежа {payment_id}: {status}, paid: {paid}")

            # Обновляем статус в БД
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()

            if paid and status == "succeeded":
                print(f"✅ Платеж {payment_id} успешно оплачен")
                cur.execute("""
                            UPDATE yookassa_payments
                            SET status  = 'succeeded',
                                paid_at = NOW()
                            WHERE payment_id = %s
                            """, (payment_id,))

                # Получаем order_id и обновляем статус заказа
                cur.execute("SELECT order_id FROM yookassa_payments WHERE payment_id = %s", (payment_id,))
                order_id_row = cur.fetchone()
                if order_id_row:
                    order_id = order_id_row[0]
                    cur.execute("UPDATE orders SET status = 'оплачен' WHERE id = %s", (order_id,))
                    print(f"✅ Обновлен статус заказа #{order_id} на 'оплачен'")

                conn.commit()
                cur.close()
                conn.close()
                return True, "оплачен"

            elif status == "canceled":
                print(f"❌ Платеж {payment_id} отменен")
                cur.execute("UPDATE yookassa_payments SET status = 'canceled' WHERE payment_id = %s", (payment_id,))
                conn.commit()
                cur.close()
                conn.close()
                return False, "отменен"

            else:
                print(f"🔄 Платеж {payment_id} в статусе: {status}")
                cur.close()
                conn.close()
                return False, status

    except Exception as e:
        print(f"❌ Ошибка проверки платежа {payment_id}: {str(e)}")
        return False, f"Ошибка проверки: {str(e)}"


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
                SELECT c.product_id, p.name, c.quantity, c.price, p.photo_file_id
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


def get_product_with_photo(product_id: int):
    """Получение информации о товаре с фото"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
                SELECT name, description, category, photo_file_id
                FROM products
                WHERE id = %s
                """, (product_id,))
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
                WHERE up.user_id = %s
                  AND LOWER(pc.code) = LOWER(%s)
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
                SET price = ROUND(price * (1 - %s / 100.0), 2)
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
    """Клавиатура с дробными граммами"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for qty, price in prices:
        if qty % 1 == 0:
            qty_str = f"{int(qty)} гр"
        else:
            qty_str = f"{qty} гр"
        markup.row(types.KeyboardButton(f"{qty_str} — {price:.0f}₽"))
    markup.row(types.KeyboardButton("⬅️ К товарам"))
    return markup


def kb_cart():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(types.KeyboardButton("🎟 Промокод"))
    markup.row(types.KeyboardButton("✅ Оформить заказ"), types.KeyboardButton("🗑 Очистить корзину"))
    markup.row(types.KeyboardButton("⬅️ Назад в Покупку"))
    return markup


def kb_payment_methods():
    """Клавиатура выбора способа оплаты"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(types.KeyboardButton("💳 ЮKassa (карта)"), types.KeyboardButton("💳 СБП"))
    markup.row(types.KeyboardButton("🪙 ЮMoney"), types.KeyboardButton("₿ Криптовалюта"))
    markup.row(types.KeyboardButton("⬅️ Назад в Покупку"))
    return markup


def kb_cities():
    """Клавиатура с 21 городом"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    buttons = []
    for city in ALL_CITIES:
        buttons.append(types.KeyboardButton(city))

    # Разбиваем на строки по 3 города
    for i in range(0, len(buttons), 3):
        markup.row(*buttons[i:i + 3])

    markup.row(types.KeyboardButton("⬅️ Назад"))
    return markup


def kb_pay_order_yookassa(order_id: int, payment_url: str):
    """Кнопка для оплаты через ЮKassa"""
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            "💳 Оплатить картой (ЮKassa)",
            url=payment_url
        )
    )
    markup.add(
        types.InlineKeyboardButton(
            "✅ Я оплатил",
            callback_data=f"check_payment_{order_id}"
        )
    )
    return markup


def kb_pay_order_other(order_id: int):
    """Кнопка для других способов оплаты"""
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            "💳 Оплатить заказ",
            callback_data=f"pay_{order_id}"
        )
    )
    return markup


def kb_try_again_yookassa(order_id: int):
    """Кнопка для повторной попытки оплаты через ЮKassa"""
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton(
            "🔄 Повторить попытку оплаты",
            callback_data=f"retry_yookassa_{order_id}"
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
                ORDER BY created_at DESC LIMIT 10
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
            # Проверяем, есть ли платеж ЮKassa для этого заказа
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("""
                        SELECT payment_url
                        FROM yookassa_payments
                        WHERE order_id = %s
                          AND status = 'pending'
                        """, (oid,))
            yookassa_row = cur.fetchone()
            cur.close()
            conn.close()

            msg = (
                f"Заказ #{oid}\n"
                f"Сумма к оплате: {total:.0f}₽\n"
                f"Статус: {status}"
            )

            if yookassa_row:
                # Отправляем кнопку ЮKassa
                bot.send_message(chat_id, msg, reply_markup=kb_pay_order_yookassa(oid, yookassa_row[0]))
            else:
                # Отправляем обычную кнопку оплаты
                bot.send_message(chat_id, msg, reply_markup=kb_pay_order_other(oid))

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
    elif method == "CRYPTO":
        pay_info = "USDT TRC20: TXXXXXXXXXXXXXXXXXXX"
    else:
        pay_info = "Обратитесь к администратору для оплаты."

    text = (
        f"Повторная оплата заказа #{order_id}.\n"
        f"Сумма: {total:.0f}₽\n\n"
        f"{pay_info}\n\n"
        f"После оплаты обязательно напишите @{ADMIN_BOT_USERNAME} "
        f"и отправьте ID заказа!"
    )

    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, text)


@bot.callback_query_handler(func=lambda c: c.data.startswith("check_payment_"))
def cb_check_payment(call: telebot.types.CallbackQuery):
    """Проверка оплаты через ЮKassa"""
    try:
        order_id = int(call.data.split("_")[2])
    except (IndexError, ValueError):
        bot.answer_callback_query(call.id, "Некорректный ID заказа.")
        return

    # Проверяем статус платежа
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
                SELECT payment_id
                FROM yookassa_payments
                WHERE order_id = %s
                  AND status IN ('pending', 'succeeded')
                """, (order_id,))
    payment_row = cur.fetchone()

    if not payment_row:
        bot.answer_callback_query(call.id, "Платеж не найден.")
        cur.close()
        conn.close()
        return

    payment_id = payment_row[0]
    cur.close()
    conn.close()

    # Проверяем статус в ЮKassa
    success, status = check_yookassa_payment(payment_id)

    if success and status == "оплачен":
        bot.answer_callback_query(call.id, "✅ Оплата подтверждена! Спасибо за заказ!")

        # Обновляем сообщение
        try:
            bot.edit_message_text(
                f"✅ Заказ #{order_id} оплачен!\n"
                f"Ожидайте, с вами свяжутся для уточнения деталей.",
                call.message.chat.id,
                call.message.message_id
            )
        except:
            pass

        # Уведомляем админа
        try:
            bot.send_message(ADMIN_CHAT_ID, f"✅ Заказ #{order_id} оплачен через ЮKassa!")
        except:
            pass

    elif status == "отменен":
        bot.answer_callback_query(call.id, "❌ Платеж отменен.")
    else:
        bot.answer_callback_query(call.id, f"⌛ Платеж в обработке. Статус: {status}")


@bot.callback_query_handler(func=lambda c: c.data.startswith("retry_yookassa_"))
def cb_retry_yookassa(call: telebot.types.CallbackQuery):
    """Повторная попытка создания платежа ЮKassa"""
    try:
        order_id = int(call.data.split("_")[2])
    except (IndexError, ValueError):
        bot.answer_callback_query(call.id, "Некорректный ID заказа.")
        return

    # Получаем информацию о заказе
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT total_amount FROM orders WHERE id = %s", (order_id,))
    order_row = cur.fetchone()

    if not order_row:
        bot.answer_callback_query(call.id, "Заказ не найден.")
        cur.close()
        conn.close()
        return

    total = order_row[0]
    cur.close()
    conn.close()

    # Пытаемся создать платеж снова
    success, payment_id, payment_url_or_error = create_yookassa_payment(
        order_id, total, f"Оплата заказа #{order_id} (повторная попытка)"
    )

    if success and payment_url_or_error:
        bot.answer_callback_query(call.id, "✅ Новая платежная ссылка создана!")

        text = (
            f"🔄 Повторная попытка оплаты заказа #{order_id}\n"
            f"💰 Сумма: {total:.0f}₽\n\n"
            f"Нажмите кнопку ниже для оплаты.\n"
            f"После оплаты нажмите '✅ Я оплатил'."
        )

        try:
            bot.edit_message_text(
                text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=kb_pay_order_yookassa(order_id, payment_url_or_error)
            )
        except:
            bot.send_message(
                call.message.chat.id,
                text,
                reply_markup=kb_pay_order_yookassa(order_id, payment_url_or_error)
            )
    else:
        error_details = payment_url_or_error if payment_url_or_error else "Неизвестная ошибка"
        bot.answer_callback_query(call.id, f"❌ Ошибка: {error_details}")

        text = (
            f"❌ Не удалось создать платежную ссылку для заказа #{order_id}\n"
            f"Причина: {error_details}\n\n"
            f"Пожалуйста, выберите другой способ оплаты из меню."
        )

        try:
            bot.edit_message_text(
                text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=kb_try_again_yookassa(order_id)
            )
        except:
            bot.send_message(
                call.message.chat.id,
                text,
                reply_markup=kb_try_again_yookassa(order_id)
            )


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
            bot.send_message(chat, "Выберите город из списка:", reply_markup=kb_cities())
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
            for pid, name, qty, price, photo_id in items:
                if qty % 1 == 0:
                    qty_str = f"{int(qty)} гр"
                else:
                    qty_str = f"{qty} гр"
                text += f"{name} — {qty_str} — {price:.0f}₽\n"
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
    if state == 'choose_city' and txt in ALL_CITIES:
        city = txt
        uid = get_user_id_by_tg(message.from_user.id)
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE users SET city = %s WHERE id = %s", (city, uid))
        conn.commit()
        cur.close()
        conn.close()
        bot.send_message(chat, f"✅ Город сохранён: {city}", reply_markup=kb_purchase())
        user_state[chat] = 'purchase_menu'
        return

    # PRODUCTS LIST
    if state == 'products' and txt.startswith("🆔"):
        try:
            pid = int(txt.split()[0].lstrip("🆔"))
        except:
            bot.send_message(chat, "Неверный формат товара.", reply_markup=kb_purchase())
            return

        conn = get_conn()
        cur = conn.cursor()

        # Получаем информацию о товаре
        cur.execute("SELECT name, description, category, photo_file_id FROM products WHERE id=%s", (pid,))
        row = cur.fetchone()

        if not row:
            bot.send_message(chat, "Товар не найден.", reply_markup=kb_purchase())
            cur.close()
            conn.close()
            return

        name, description, category, photo_file_id = row

        # Получаем цены для дробных граммов
        cur.execute("SELECT quantity, price FROM product_prices WHERE product_id=%s ORDER BY quantity", (pid,))
        prices = cur.fetchall()
        cur.close()
        conn.close()

        user_state[chat] = f'product_{pid}'
        TRANSIENT[chat] = {'product_id': pid}

        # Формируем описание товара
        product_text = f"🌸 <b>{name}</b>\n"
        if category:
            product_text += f"📊 Категория: {category}\n\n"
        product_text += f"📝 {description}\n\n"
        product_text += "📦 <b>Доступные фасовки:</b>\n"

        for qty, price in prices:
            if qty % 1 == 0:
                qty_str = f"{int(qty)} гр"
            else:
                qty_str = f"{qty} гр"
            product_text += f"  • {qty_str} — {price:.0f}₽\n"

        # Отправляем фото товара, если оно есть
        if photo_file_id:
            try:
                bot.send_photo(chat, photo_file_id, caption=product_text,
                               reply_markup=kb_product_detail(prices), parse_mode="HTML")
            except:
                bot.send_message(chat, product_text, reply_markup=kb_product_detail(prices), parse_mode="HTML")
        else:
            bot.send_message(chat, product_text, reply_markup=kb_product_detail(prices), parse_mode="HTML")
        return

    # PRODUCT DETAIL
    if state.startswith('product_') and "гр" in txt:
        try:
            # Извлекаем количество из текста (например: "0.5 гр — 800₽")
            # Разделяем строку по пробелу и берем первую часть
            parts = txt.split()
            if "гр" in parts[0]:
                qty_str = parts[0].replace("гр", "").strip()
            else:
                qty_str = parts[0]

            # Пробуем преобразовать в float, так как могут быть дробные значения
            qty = float(qty_str)
        except ValueError:
            bot.send_message(chat, "Неверный формат количества.", reply_markup=kb_purchase())
            return
        except Exception as e:
            print(f"Ошибка при парсинге количества: {e}")
            bot.send_message(chat, "Ошибка обработки количества.", reply_markup=kb_purchase())
            return

        pid = TRANSIENT.get(chat, {}).get('product_id')

        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT price FROM product_prices WHERE product_id=%s AND quantity=%s", (pid, qty))
        price_row = cur.fetchone()

        if not price_row:
            bot.send_message(chat, "Выбранная фасовка не найдена.", reply_markup=kb_purchase())
            cur.close()
            conn.close()
            return

        price = price_row[0]

        uid = get_user_id_by_tg(message.from_user.id)
        cur.execute(
            "INSERT INTO cart_items (user_id, product_id, quantity, price) VALUES (%s,%s,%s,%s)",
            (uid, pid, qty, price)
        )
        conn.commit()
        cur.close()
        conn.close()

        bot.send_message(chat, "✅ Товар добавлен в корзину.", reply_markup=kb_purchase())
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

            bot.send_message(chat, "✅ Корзина очищена.", reply_markup=kb_purchase())
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

            bot.send_message(chat, f"💰 Итоговая сумма: {total:.0f}₽\nВыберите способ оплаты:",
                             reply_markup=kb_payment_methods())
            return

    # PROMO INPUT
    if state == 'promo_input':
        uid = get_user_id_by_tg(message.from_user.id)
        success, msg_text, applied_code = apply_promo_to_cart(uid, txt)

        if success and applied_code:
            items = get_cart_items(uid)
            text = msg_text + "\n\n🛒 Ваша корзина:\n\n"
            total = 0
            for pid, name, qty, price, photo_id in items:
                if qty % 1 == 0:
                    qty_str = f"{int(qty)} гр"
                else:
                    qty_str = f"{qty} гр"
                text += f"{name} — {qty_str} — {price:.0f}₽\n"
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
            "💳 ЮKassa (карта)": "YOOKASSA",
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
            city_row = cur.fetchone()

            if not city_row:
                bot.send_message(chat, "❌ Сначала выберите город.", reply_markup=kb_purchase())
                user_state[chat] = 'purchase_menu'
                cur.close()
                conn.close()
                return

            city, username = city_row

            promo_code = TRANSIENT.get(chat, {}).get('promo_code')

            # Создаем заказ
            cur.execute(
                "INSERT INTO orders (user_id, city, total_amount, payment_method, status, "
                "unread_by_admin, unread_by_user, promo_code) "
                "VALUES (%s,%s,%s,%s,%s, TRUE, FALSE, %s) RETURNING id",
                (uid, city, total, method, "ожидает оплаты", promo_code)
            )
            order_id = cur.fetchone()[0]

            # Добавляем товары в заказ
            for p_id, name, qty, price, photo_id in items:
                cur.execute(
                    "INSERT INTO order_items (order_id, product_id, quantity, price) VALUES (%s,%s,%s,%s)",
                    (order_id, p_id, qty, price)
                )

            # Очищаем корзину
            cur.execute("DELETE FROM cart_items WHERE user_id=%s", (uid,))
            conn.commit()
            cur.close()
            conn.close()

            # Обработка в зависимости от метода оплаты
            if method == "YOOKASSA":
                # Создаем платеж в ЮKassa
                success, payment_id, payment_url_or_error = create_yookassa_payment(
                    order_id, total, f"Оплата заказа #{order_id}"
                )

                if success and payment_url_or_error:
                    # Отправляем пользователю ссылку для оплаты
                    text = (
                        f"✅ Заказ #{order_id} создан!\n"
                        f"💰 Сумма: {total:.0f}₽\n"
                        f"🏙 Город: {city}\n"
                        f"💳 Способ оплаты: ЮKassa (банковская карта)\n\n"
                        f"Нажмите кнопку ниже для оплаты.\n"
                        f"После оплаты нажмите '✅ Я оплатил'."
                    )

                    bot.send_message(
                        chat,
                        text,
                        reply_markup=kb_pay_order_yookassa(order_id, payment_url_or_error)
                    )
                else:
                    # Если не удалось создать платеж, предлагаем другие способы
                    error_details = payment_url_or_error if payment_url_or_error else "Неизвестная ошибка"
                    text = (
                        f"✅ Заказ #{order_id} создан!\n"
                        f"💰 Сумма: {total:.0f}₽\n"
                        f"🏙 Город: {city}\n"
                        f"💳 Способ оплаты: ЮKassa (банковская карта)\n\n"
                        f"⚠️ <b>Не удалось создать платежную ссылку</b>\n"
                        f"Причина: {error_details}\n\n"
                        f"Пожалуйста, выберите другой способ оплаты:"
                    )

                    # Предлагаем другие способы оплаты
                    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
                    markup.row(types.KeyboardButton("💳 СБП"))
                    markup.row(types.KeyboardButton("🪙 ЮMoney"), types.KeyboardButton("₿ Криптовалюта"))
                    markup.row(types.KeyboardButton("⬅️ Назад в Покупку"))

                    bot.send_message(chat, text, reply_markup=markup, parse_mode="HTML")

                    # Сохраняем order_id для повторной попытки
                    TRANSIENT[chat]['failed_yookassa_order'] = order_id
                    TRANSIENT[chat]['failed_yookassa_total'] = total

            else:
                # Для других способов оплаты
                if method == "SBP":
                    pay_info = "Реквизиты СБП: 2200 0000 0000 0000"
                elif method == "YUMONEY":
                    pay_info = "ЮMoney кошелёк: 4100 0000 0000 000"
                else:
                    pay_info = "USDT TRC20: TXXXXXXXXXXXXXXXXXXX"

                promo_line = f"\n🎟 Промокод: {promo_code}" if promo_code else ""

                text = (
                    f"✅ Заказ #{order_id} создан!\n"
                    f"💰 Сумма: {total:.0f}₽{promo_line}\n"
                    f"🏙 Город: {city}\n\n"
                    f"{pay_info}\n\n"
                    f"📞 После оплаты обязательно напишите @{ADMIN_BOT_USERNAME} и отправьте ID заказа!"
                )

                bot.send_message(chat, text, reply_markup=kb_main())
                bot.send_message(chat, f"Для оплаты заказа #{order_id}:",
                                 reply_markup=kb_pay_order_other(order_id))

            # Уведомление админу
            try:
                text_to_admin = (
                    f"🆕 Новый заказ #{order_id}\n"
                    f"👤 user_id: {uid}, username: @{username or 'user'}\n"
                    f"🏙 Город: {city}\n"
                    f"💳 Способ оплаты: {method}\n"
                    f"💵 Сумма: {total:.0f}₽\n"
                    f"🎟 Промокод: {promo_code or 'нет'}\n\n"
                    f"📦 Позиции:\n"
                )
                for p_id, name, qty, price, photo_id in items:
                    if qty % 1 == 0:
                        qty_str = f"{int(qty)} гр"
                    else:
                        qty_str = f"{qty} гр"
                    text_to_admin += f"- {name} — {qty_str} — {price:.0f}₽\n"

                bot.send_message(ADMIN_CHAT_ID, text_to_admin)
            except Exception as e:
                print(f"Ошибка отправки админу: {e}")

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

            text = "🌸 Отзывы покупателей:\n\n" + "\n\n".join(
                f"👤 @{r[0] or 'user'}:\n{r[1]}\n📅 {r[2].strftime('%d.%m.%Y')}"
                for r in rows
            ) if rows else "Отзывов пока нет. Будьте первым!"

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

        bot.send_message(chat, "✅ Спасибо! Ваш отзыв сохранён.", reply_markup=kb_main())
        user_state[chat] = 'main'
        return

    # FALLBACK
    bot.send_message(chat, "Не понял команду. Главное меню:", reply_markup=kb_main())
    user_state[chat] = 'main'


if __name__ == "__main__":
    print("🌸 Shop bot started...")
    print(f"🏙 Поддерживается {len(ALL_CITIES)} городов")
    print(f"📦 14 видов товаров с дробными граммами")
    print(f"💳 Интеграция с ЮKassa")
    print(f"🔑 Shop ID: {YOOKASSA_SHOP_ID}")
    bot.infinity_polling(skip_pending=True)
