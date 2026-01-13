"""
Создание полной базы данных FlowerShop для Telegram ботов
Выполните: python create_db.py
"""

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import sys
from pathlib import Path

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "user": "postgres",
    "password": "1234567890"
}

DB_NAME = "FlowerShop"

# Полный SQL скрипт для создания БД
SQL_SCRIPT = """
-- ========================================
-- ПОЛНАЯ БАЗА ДАННЫХ FlowerShop для 3 ботов
-- shop_bot + support_bot + admin_bot
-- ========================================

-- 1. Создание таблиц пользователей (ОСНОВА)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    tg_id BIGINT UNIQUE NOT NULL,
    username VARCHAR(255),
    first_name VARCHAR(255),
    last_name VARCHAR(255),
    ref_code VARCHAR(50) UNIQUE NOT NULL,
    city VARCHAR(100),
    ref_balance DECIMAL(10,2) DEFAULT 0.00,
    is_blocked BOOLEAN DEFAULT FALSE,
    blocked_by BIGINT,
    blocked_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Таблица товаров (с фото)
CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(100),
    weight_unit VARCHAR(10) DEFAULT 'гр', -- 'гр' для граммов
    photo_file_id VARCHAR(255), -- ID файла в Telegram
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Цены товаров (по количеству/весу)
CREATE TABLE IF NOT EXISTS product_prices (
    id SERIAL PRIMARY KEY,
    product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
    quantity DECIMAL(10,2) NOT NULL, -- может быть дробным: 0.5, 1, 1.5, 2, 3, 5
    price DECIMAL(10,2) NOT NULL,
    UNIQUE(product_id, quantity)
);

-- 4. Корзина пользователей
CREATE TABLE IF NOT EXISTS cart_items (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
    quantity DECIMAL(10,2) NOT NULL, -- дробное количество
    price DECIMAL(10,2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5. Промокоды
CREATE TABLE IF NOT EXISTS promo_codes (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    discount_percent DECIMAL(5,2) NOT NULL CHECK (discount_percent >= 0 AND discount_percent <= 100),
    max_uses INTEGER,
    uses_count INTEGER DEFAULT 0 CHECK (uses_count >= 0),
    is_active BOOLEAN DEFAULT TRUE,
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 6. Использования промокодов
CREATE TABLE IF NOT EXISTS user_promo_uses (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    promo_code_id INTEGER REFERENCES promo_codes(id) ON DELETE CASCADE,
    order_id INTEGER,
    used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, promo_code_id)
);

-- 7. Реферальные связи
CREATE TABLE IF NOT EXISTS referrals (
    id SERIAL PRIMARY KEY,
    referrer_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    referee_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(referrer_id, referee_id)
);

-- 8. Администраторы
CREATE TABLE IF NOT EXISTS admin (
    id SERIAL PRIMARY KEY,
    tg_id BIGINT UNIQUE NOT NULL,
    username VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 9. Персонал поддержки
CREATE TABLE IF NOT EXISTS support_staff (
    id SERIAL PRIMARY KEY,
    tg_id BIGINT UNIQUE NOT NULL,
    username VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 10. Тикеты поддержки
CREATE TABLE IF NOT EXISTS support_tickets (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    status VARCHAR(20) DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'closed')),
    last_message TIMESTAMP NOT NULL,
    unread_by_support BOOLEAN DEFAULT FALSE,
    unread_by_user BOOLEAN DEFAULT FALSE,
    locked_by BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 11. Сообщения тикетов
CREATE TABLE IF NOT EXISTS support_messages (
    id SERIAL PRIMARY KEY,
    ticket_id INTEGER REFERENCES support_tickets(id) ON DELETE CASCADE,
    from_user BOOLEAN NOT NULL,
    message_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 12. Заказы (с полями доставки для admin_bot)
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    city VARCHAR(100),
    total_amount DECIMAL(10,2) NOT NULL,
    payment_method VARCHAR(20) NOT NULL,
    status VARCHAR(50) DEFAULT 'ожидает оплаты',
    unread_by_admin BOOLEAN DEFAULT TRUE,
    unread_by_user BOOLEAN DEFAULT TRUE,
    promo_code VARCHAR(50),
    delivery_info TEXT,
    delivery_photo_file_id VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 13. Позиции заказов
CREATE TABLE IF NOT EXISTS order_items (
    id SERIAL PRIMARY KEY,
    order_id INTEGER REFERENCES orders(id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
    quantity DECIMAL(10,2) NOT NULL, -- дробное количество
    price DECIMAL(10,2) NOT NULL
);

-- 14. Отзывы
CREATE TABLE IF NOT EXISTS reviews (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    review_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 15. Платежи ЮKassa
CREATE TABLE IF NOT EXISTS yookassa_payments (
    id SERIAL PRIMARY KEY,
    order_id INTEGER REFERENCES orders(id) ON DELETE CASCADE,
    payment_id VARCHAR(100) UNIQUE NOT NULL, -- ID платежа в ЮKassa
    status VARCHAR(50) DEFAULT 'pending',
    amount DECIMAL(10,2) NOT NULL,
    currency VARCHAR(10) DEFAULT 'RUB',
    payment_url TEXT, -- Ссылка для оплаты
    confirmation_token TEXT, -- Токен для подтверждения
    paid_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ========================================
-- ИНДЕКСЫ ДЛЯ ОПТИМИЗАЦИИ (ВАЖНО!)
-- ========================================
CREATE INDEX IF NOT EXISTS idx_users_tg_id ON users(tg_id);
CREATE INDEX IF NOT EXISTS idx_users_ref_code ON users(ref_code);
CREATE INDEX IF NOT EXISTS idx_users_blocked ON users(is_blocked);
CREATE INDEX IF NOT EXISTS idx_cart_user ON cart_items(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_unread_admin ON orders(unread_by_admin);
CREATE INDEX IF NOT EXISTS idx_promo_code_lower ON promo_codes(LOWER(code));
CREATE INDEX IF NOT EXISTS idx_support_tickets_user ON support_tickets(user_id);
CREATE INDEX IF NOT EXISTS idx_support_tickets_status ON support_tickets(status);
CREATE INDEX IF NOT EXISTS idx_support_tickets_unread_support ON support_tickets(unread_by_support);
CREATE INDEX IF NOT EXISTS idx_admin_tg_id ON admin(tg_id);
CREATE INDEX IF NOT EXISTS idx_support_messages_ticket ON support_messages(ticket_id);
CREATE INDEX IF NOT EXISTS idx_yookassa_payment_id ON yookassa_payments(payment_id);
CREATE INDEX IF NOT EXISTS idx_yookassa_order_id ON yookassa_payments(order_id);

-- ========================================
-- НАЧАЛЬНЫЕ ДАННЫЕ (ТЕСТОВЫЕ)
-- ========================================
-- Администратор (ADMIN_CHAT_ID из ботов)
INSERT INTO admin (tg_id, username, is_active) VALUES 
(123456789, 'weeeeeeeetADM_bot', TRUE)
ON CONFLICT (tg_id) DO NOTHING;

-- Персонал поддержки
INSERT INTO support_staff (tg_id, username) VALUES 
(123456789, 'weeeeeeeetADM_bot')
ON CONFLICT (tg_id) DO NOTHING;

-- Тестовый пользователь
INSERT INTO users (tg_id, username, first_name, ref_code, city) VALUES 
(999999999, 'test_user', 'Тестовый', 'test999', 'Москва')
ON CONFLICT (tg_id) DO NOTHING;

-- 14 видов товаров (цветов)
INSERT INTO products (name, description, category, weight_unit, photo_file_id, is_active) VALUES 
('Амнезия', 'Популярный сорт с долгим эффектом', 'Сатива', 'гр', NULL, TRUE),
('АК-47', 'Классический сорт, сбалансированный эффект', 'Гибрид', 'гр', NULL, TRUE),
('White Widow', 'Белый налет, мощный эффект', 'Гибрид', 'гр', NULL, TRUE),
('Northern Lights', 'Индика, расслабляющий эффект', 'Индика', 'гр', NULL, TRUE),
('Blue Dream', 'Сладкий вкус, креативный эффект', 'Гибрид', 'гр', NULL, TRUE),
('OG Kush', 'Земляной вкус, сильный эффект', 'Гибрид', 'гр', NULL, TRUE),
('Sour Diesel', 'Цитрусовый вкус, энергетический эффект', 'Сатива', 'гр', NULL, TRUE),
('Jack Herer', 'Пряный вкус, ясный эффект', 'Сатива', 'гр', NULL, TRUE),
('Girl Scout Cookies', 'Сладкий вкус, мощный эффект', 'Гибрид', 'гр', NULL, TRUE),
('Gorilla Glue', 'Очень липкий, сильный эффект', 'Гибрид', 'гр', NULL, TRUE),
('Purple Haze', 'Фиолетовые оттенки, психоделический эффект', 'Сатива', 'гр', NULL, TRUE),
('Bubba Kush', 'Сладкий, расслабляющий эффект', 'Индика', 'гр', NULL, TRUE),
('Super Silver Haze', 'Энергичный, долгий эффект', 'Сатива', 'гр', NULL, TRUE),
('Critical Mass', 'Большая урожайность, расслабляющий эффект', 'Индика', 'гр', NULL, TRUE)
ON CONFLICT DO NOTHING;

-- Цены для товаров (дробные граммы: 0.5, 1, 1.5, 2, 3, 5)
INSERT INTO product_prices (product_id, quantity, price) VALUES 
-- Амнезия
(1, 0.5, 800.00),
(1, 1.0, 1500.00),
(1, 1.5, 2200.00),
(1, 2.0, 2800.00),
(1, 3.0, 4000.00),
(1, 5.0, 6500.00),

-- АК-47
(2, 0.5, 750.00),
(2, 1.0, 1400.00),
(2, 1.5, 2100.00),
(2, 2.0, 2700.00),
(2, 3.0, 3800.00),
(2, 5.0, 6200.00),

-- White Widow
(3, 0.5, 850.00),
(3, 1.0, 1600.00),
(3, 1.5, 2300.00),
(3, 2.0, 2900.00),
(3, 3.0, 4200.00),
(3, 5.0, 6800.00),

-- Northern Lights
(4, 0.5, 700.00),
(4, 1.0, 1300.00),
(4, 1.5, 1900.00),
(4, 2.0, 2500.00),
(4, 3.0, 3500.00),
(4, 5.0, 5800.00),

-- Blue Dream
(5, 0.5, 800.00),
(5, 1.0, 1500.00),
(5, 1.5, 2200.00),
(5, 2.0, 2800.00),
(5, 3.0, 4000.00),
(5, 5.0, 6500.00),

-- OG Kush
(6, 0.5, 900.00),
(6, 1.0, 1700.00),
(6, 1.5, 2400.00),
(6, 2.0, 3100.00),
(6, 3.0, 4500.00),
(6, 5.0, 7200.00),

-- Sour Diesel
(7, 0.5, 750.00),
(7, 1.0, 1400.00),
(7, 1.5, 2100.00),
(7, 2.0, 2700.00),
(7, 3.0, 3800.00),
(7, 5.0, 6200.00),

-- Jack Herer
(8, 0.5, 800.00),
(8, 1.0, 1500.00),
(8, 1.5, 2200.00),
(8, 2.0, 2800.00),
(8, 3.0, 4000.00),
(8, 5.0, 6500.00),

-- Girl Scout Cookies
(9, 0.5, 850.00),
(9, 1.0, 1600.00),
(9, 1.5, 2300.00),
(9, 2.0, 2900.00),
(9, 3.0, 4200.00),
(9, 5.0, 6800.00),

-- Gorilla Glue
(10, 0.5, 900.00),
(10, 1.0, 1700.00),
(10, 1.5, 2400.00),
(10, 2.0, 3100.00),
(10, 3.0, 4500.00),
(10, 5.0, 7200.00),

-- Purple Haze
(11, 0.5, 700.00),
(11, 1.0, 1300.00),
(11, 1.5, 1900.00),
(11, 2.0, 2500.00),
(11, 3.0, 3500.00),
(11, 5.0, 5800.00),

-- Bubba Kush
(12, 0.5, 750.00),
(12, 1.0, 1400.00),
(12, 1.5, 2100.00),
(12, 2.0, 2700.00),
(12, 3.0, 3800.00),
(12, 5.0, 6200.00),

-- Super Silver Haze
(13, 0.5, 800.00),
(13, 1.0, 1500.00),
(13, 1.5, 2200.00),
(13, 2.0, 2800.00),
(13, 3.0, 4000.00),
(13, 5.0, 6500.00),

-- Critical Mass
(14, 0.5, 650.00),
(14, 1.0, 1200.00),
(14, 1.5, 1800.00),
(14, 2.0, 2400.00),
(14, 3.0, 3300.00),
(14, 5.0, 5500.00)
ON CONFLICT DO NOTHING;

-- Промокоды
INSERT INTO promo_codes (code, discount_percent, max_uses, is_active) VALUES 
('REF3', 3.0, NULL, TRUE),
('WELCOME10', 10.0, 100, TRUE),
('FLOWER20', 20.0, 50, TRUE),
('SUMMER15', 15.0, 200, TRUE)
ON CONFLICT DO NOTHING;

-- Тестовый заказ
DO $$
DECLARE 
    test_user_id INTEGER;
    test_order_id INTEGER;
BEGIN
    SELECT id INTO test_user_id FROM users WHERE tg_id = 999999999;

    IF test_user_id IS NOT NULL THEN
        INSERT INTO orders (user_id, city, total_amount, payment_method, status, unread_by_admin)
        VALUES (test_user_id, 'Москва', 1500.00, 'YOOKASSA', 'ожидает оплаты', TRUE)
        RETURNING id INTO test_order_id;

        INSERT INTO order_items (order_id, product_id, quantity, price) 
        VALUES (test_order_id, 1, 1.0, 1500.00);
    END IF;
END $$;

-- Успешное завершение
SELECT '✅ База данных FlowerShop создана успешно! Всего 15 таблиц.' as status;
"""


def create_database():
    """Создание базы данных и выполнение скрипта"""
    print("🚀 Создание базы данных FlowerShop...")

    # 1. Подключение к PostgreSQL (без указания dbname)
    conn = psycopg2.connect(**DB_CONFIG)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()

    try:
        # 2. Создание базы данных
        print("📁 Создание базы данных 'FlowerShop'...")
        cur.execute(f"CREATE DATABASE \"{DB_NAME}\"")
        print("✅ База данных создана!")

        # 3. Подключение к новой базе
        print("🔧 Подключение к FlowerShop и создание таблиц...")
        db_conn = psycopg2.connect(dbname=DB_NAME, **DB_CONFIG)
        db_cur = db_conn.cursor()

        # 4. Выполнение полного скрипта
        db_cur.execute(SQL_SCRIPT)
        db_conn.commit()

        print("✅ Все таблицы, индексы и тестовые данные созданы!")
        print("📊 Проверка созданных таблиц:")
        db_cur.execute("""
                       SELECT tablename
                       FROM pg_tables
                       WHERE schemaname = 'public'
                       ORDER BY tablename
                       """)
        tables = [row[0] for row in db_cur.fetchall()]
        print(f"   ✅ Создано таблиц: {len(tables)}")
        for table in tables:
            print(f"   📋 {table}")

    except psycopg2.errors.DuplicateDatabase:
        print("⚠️  База данных FlowerShop уже существует. Обновляем схему...")
        db_conn = psycopg2.connect(dbname=DB_NAME, **DB_CONFIG)
        db_cur = db_conn.cursor()
        db_cur.execute(SQL_SCRIPT)
        db_conn.commit()
        print("✅ Схема обновлена!")

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        sys.exit(1)

    finally:
        cur.close()
        conn.close()
        if 'db_conn' in locals():
            db_cur.close()
            db_conn.close()


def test_connection():
    """Тест подключения к готовой базе"""
    print("\n🔍 Тестируем подключение...")
    try:
        conn = psycopg2.connect(dbname=DB_NAME, **DB_CONFIG)
        cur = conn.cursor()
        cur.execute("SELECT 1")
        print("✅ Подключение успешно!")
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
        return False


if __name__ == "__main__":
    print("🌸 Создание базы данных для Telegram ботов FlowerShop")
    print("=" * 60)

    create_database()

    if test_connection():
        print("\n🎉 ВСЁ ГОТОВО!")
        print("\n📋 Теперь можно запускать ботов:")
        print("   python shop_bot.py")
        print("   python support_bot.py")
        print("   python admin_bot.py")
        print("\n🔧 Админ TG_ID: 123456789")
        print("   Тестовый пользователь TG_ID: 999999999")
        print("\n📦 14 товаров создано с дробными граммами (0.5, 1, 1.5, 2, 3, 5 гр)")
        print("🏙  Города доступны: все 21 город")
    else:
        print("\n❌ Ошибка финального теста!")
