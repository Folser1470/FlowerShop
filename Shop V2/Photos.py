
"""
Простой скрипт для массовой загрузки фотографий товаров в базу данных
Без проверки на админа - загружает фото из папки
"""

import os
import psycopg2
import telebot
from telebot import types
import time

# Настройки
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "FlowerShop",
    "user": "postgres",
    "password": "1234567890"
}

BOT_TOKEN_SHOP = "8565390672:AAEy8y12wbbdfwbV5M3EOgZClq9RbCRfzqo"
bot = telebot.TeleBot(BOT_TOKEN_SHOP)

# ID чата, куда будут отправляться фото (для получения file_id)
# Можно использовать свой ID или ID тестового чата
TARGET_CHAT_ID = "1963178228"  # Замените на нужный ID

# Соответствие товаров и файлов (14 товаров)
PRODUCT_PHOTOS = {
    1: ("Амнезия", ["1_amnesia.jpg", "1_amnesia.jpeg", "1_amnesia.png", "1.jpg", "amnesia.jpg"]),
    2: ("АК-47", ["2_ak47.jpg", "2_ak47.jpeg", "2_ak47.png", "2.jpg", "ak47.jpg"]),
    3: ("White Widow", ["3_white_widow.jpg", "3_white_widow.jpeg", "3_white_widow.png", "3.jpg", "white_widow.jpg"]),
    4: ("Northern Lights",
        ["4_northern_lights.jpg", "4_northern_lights.jpeg", "4_northern_lights.png", "4.jpg", "northern_lights.jpg"]),
    5: ("Blue Dream", ["5_blue_dream.jpg", "5_blue_dream.jpeg", "5_blue_dream.png", "5.jpg", "blue_dream.jpg"]),
    6: ("OG Kush", ["6_og_kush.jpg", "6_og_kush.jpeg", "6_og_kush.png", "6.jpg", "og_kush.jpg"]),
    7: ("Sour Diesel", ["7_sour_diesel.jpg", "7_sour_diesel.jpeg", "7_sour_diesel.png", "7.jpg", "sour_diesel.jpg"]),
    8: ("Jack Herer", ["8_jack_herer.jpg", "8_jack_herer.jpeg", "8_jack_herer.png", "8.jpg", "jack_herer.jpg"]),
    9: ("Girl Scout Cookies",
        ["9_girl_scout_cookies.jpg", "9_girl_scout_cookies.jpeg", "9_girl_scout_cookies.png", "9.jpg",
         "girl_scout_cookies.jpg"]),
    10: ("Gorilla Glue",
         ["10_gorilla_glue.jpg", "10_gorilla_glue.jpeg", "10_gorilla_glue.png", "10.jpg", "gorilla_glue.jpg"]),
    11: ("Purple Haze",
         ["11_purple_haze.jpg", "11_purple_haze.jpeg", "11_purple_haze.png", "11.jpg", "purple_haze.jpg"]),
    12: ("Bubba Kush", ["12_bubba_kush.jpg", "12_bubba_kush.jpeg", "12_bubba_kush.png", "12.jpg", "bubba_kush.jpg"]),
    13: ("Super Silver Haze",
         ["13_super_silver_haze.jpg", "13_super_silver_haze.jpeg", "13_super_silver_haze.png", "13.jpg",
          "super_silver_haze.jpg"]),
    14: ("Critical Mass",
         ["14_critical_mass.jpg", "14_critical_mass.jpeg", "14_critical_mass.png", "14.jpg", "critical_mass.jpg"])
}


def get_conn():
    """Создает соединение с базой данных"""
    return psycopg2.connect(**DB_CONFIG)


def find_photo_file(product_id, photos_dir):
    """Находит файл фото для товара"""
    product_name, possible_filenames = PRODUCT_PHOTOS[product_id]

    for filename in possible_filenames:
        filepath = os.path.join(photos_dir, filename)
        if os.path.exists(filepath):
            return filepath, product_name

    # Пробуем найти любой файл с номером товара
    for file in os.listdir(photos_dir):
        if file.lower().startswith(f"{product_id}_") or file.lower().startswith(f"{product_id}."):
            return os.path.join(photos_dir, file), product_name

    # Ищем любой файл с названием товара
    product_name_lower = product_name.lower().replace(" ", "_")
    for file in os.listdir(photos_dir):
        if product_name_lower in file.lower():
            return os.path.join(photos_dir, file), product_name

    return None, product_name


def upload_photo_to_telegram(photo_path, product_id, product_name):
    """Загружает фото в Telegram и возвращает file_id"""
    try:
        if not os.path.exists(photo_path):
            print(f"❌ Файл не найден: {photo_path}")
            return None

        print(f"📤 Загружаю: {os.path.basename(photo_path)}")

        with open(photo_path, 'rb') as photo:
            # Отправляем фото в указанный чат
            msg = bot.send_photo(
                chat_id=TARGET_CHAT_ID,
                photo=photo,
                caption=f"#{product_id} {product_name}"
            )

            # Ждем немного, чтобы Telegram обработал фото
            time.sleep(1)

            # Получаем file_id из ответа Telegram
            if msg.photo:
                # Берем самое большое фото (последний элемент в списке)
                file_id = msg.photo[-1].file_id
                print(f"   ✅ Получен file_id: {file_id[:20]}...")
                return file_id
            else:
                print(f"   ❌ Не удалось получить file_id")
                return None

    except Exception as e:
        print(f"   ❌ Ошибка загрузки: {str(e)}")
        return None


def save_photo_to_db(product_id, file_id):
    """Сохраняет file_id в базу данных"""
    conn = get_conn()
    cur = conn.cursor()

    try:
        cur.execute(
            "UPDATE products SET photo_file_id = %s WHERE id = %s",
            (file_id, product_id)
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"   ❌ Ошибка сохранения в БД: {str(e)}")
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()


def process_photos(photos_dir="product_photos"):
    """Основная функция обработки фото"""
    print("=" * 60)
    print("🌸 МАССОВАЯ ЗАГРУЗКА ФОТОГРАФИЙ ТОВАРОВ")
    print("=" * 60)

    # Проверяем существование директории
    if not os.path.exists(photos_dir):
        print(f"\n❌ Папка '{photos_dir}' не найдена!")
        print(f"Создайте папку '{photos_dir}' и поместите туда фото.")
        print("\nОжидаемые имена файлов (можно использовать другие):")
        for pid, (name, files) in PRODUCT_PHOTOS.items():
            print(f"  Товар #{pid:2d} ({name:25}) → {files[0]}")
        return

    print(f"\n📁 Папка с фото: {os.path.abspath(photos_dir)}")
    print(f"📊 Найдено файлов: {len(os.listdir(photos_dir))}")

    # Показываем список файлов в папке
    print("\n📋 Файлы в папке:")
    for i, filename in enumerate(sorted(os.listdir(photos_dir)), 1):
        print(f"  {i:2d}. {filename}")

    print("\n" + "=" * 60)
    print("🚀 НАЧИНАЮ ЗАГРУЗКУ...")
    print("=" * 60)

    successful = 0
    failed = 0
    skipped = 0

    # Обрабатываем каждый товар
    for product_id in range(1, 15):  # 1-14
        print(f"\n🔹 Товар #{product_id}")

        # Находим файл фото
        photo_path, product_name = find_photo_file(product_id, photos_dir)

        if not photo_path:
            print(f"   ⚠️  Фото не найдено для товара #{product_id} - {product_name}")
            skipped += 1
            continue

        # Загружаем фото в Telegram
        file_id = upload_photo_to_telegram(photo_path, product_id, product_name)

        if not file_id:
            print(f"   ❌ Не удалось загрузить фото")
            failed += 1
            continue

        # Сохраняем в БД
        if save_photo_to_db(product_id, file_id):
            print(f"   ✅ Успешно сохранено: {product_name}")
            successful += 1
        else:
            failed += 1

    # Выводим статистику
    print("\n" + "=" * 60)
    print("📊 РЕЗУЛЬТАТЫ ЗАГРУЗКИ")
    print("=" * 60)
    print(f"✅ Успешно: {successful}")
    print(f"❌ Ошибки: {failed}")
    print(f"⚠️  Пропущено: {skipped}")
    print(f"📦 Всего товаров: 14")

    if successful > 0:
        print(f"\n🎉 Загружено фото для {successful} товаров!")
    else:
        print(f"\n😞 Не удалось загрузить ни одного фото")


def show_current_status():
    """Показывает текущий статус фото в базе данных"""
    print("\n" + "=" * 60)
    print("📋 ТЕКУЩИЙ СТАТУС ФОТОГРАФИЙ В БАЗЕ ДАННЫХ")
    print("=" * 60)

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
                SELECT id,
                       name,
                       CASE
                           WHEN photo_file_id IS NULL THEN '❌ НЕТ ФОТО'
                           ELSE '✅ ЕСТЬ ФОТО'
                           END as status,
                       photo_file_id
                FROM products
                ORDER BY id
                """)

    products = cur.fetchall()

    print("\nID  | НАЗВАНИЕ ТОВАРА                  | СТАТУС      | FILE_ID")
    print("-" * 80)

    for product_id, name, status, file_id in products:
        # Обрезаем длинные названия
        name_display = name[:28] + "..." if len(name) > 28 else name.ljust(31)

        # Обрезаем file_id для отображения
        if file_id:
            file_id_display = file_id[:20] + "..." if len(file_id) > 20 else file_id.ljust(23)
        else:
            file_id_display = "-".ljust(23)

        print(f"{product_id:3d} | {name_display} | {status:11} | {file_id_display}")

    # Статистика
    with_photo = sum(1 for p in products if p[3] is not None)
    without_photo = len(products) - with_photo

    print("\n" + "=" * 60)
    print(f"📊 СТАТИСТИКА: {with_photo} с фото, {without_photo} без фото")
    print("=" * 60)

    cur.close()
    conn.close()


def test_photo_display():
    """Тестирует отображение фото"""
    print("\n" + "=" * 60)
    print("🖼  ТЕСТИРОВАНИЕ ОТОБРАЖЕНИЯ ФОТО")
    print("=" * 60)

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
                SELECT id, name, photo_file_id
                FROM products
                WHERE photo_file_id IS NOT NULL
                ORDER BY id LIMIT 3
                """)

    products_with_photos = cur.fetchall()

    if not products_with_photos:
        print("😞 Нет товаров с фото для тестирования")
        return

    print(f"\nОтправляю фото для теста в чат ID: {TARGET_CHAT_ID}")

    for product_id, name, file_id in products_with_photos:
        try:
            bot.send_photo(
                chat_id=TARGET_CHAT_ID,
                photo=file_id,
                caption=f"ТЕСТ: #{product_id} - {name}"
            )
            print(f"✅ Отправлено фото для товара #{product_id}: {name}")
            time.sleep(1)  # Пауза между отправками
        except Exception as e:
            print(f"❌ Ошибка отправки для товара #{product_id}: {str(e)}")

    cur.close()
    conn.close()

    print("\n✅ Тестирование завершено. Проверьте чат.")


def create_sample_photos():
    """Создает образец структуры папки с фото"""
    sample_dir = "product_photos_sample"

    if os.path.exists(sample_dir):
        print(f"\n⚠️  Папка '{sample_dir}' уже существует")
        return

    os.makedirs(sample_dir, exist_ok=True)

    print(f"\n📁 Создаю образец структуры в папке: {sample_dir}")
    print("\nСозданы пустые файлы-заглушки:")

    for product_id, (name, possible_files) in PRODUCT_PHOTOS.items():
        # Берем первое имя файла из списка возможных
        filename = possible_files[0]
        filepath = os.path.join(sample_dir, filename)

        # Создаем пустой файл
        with open(filepath, 'w') as f:
            f.write(f"Это заглушка для фото товара #{product_id} - {name}\n")
            f.write(f"Замените этот файл реальным фото!")

        print(f"  ✅ {filename}")

    print(f"\n📝 Теперь замените файлы в папке '{sample_dir}' реальными фото")
    print(f"   и переименуйте папку в 'product_photos' или укажите путь к ней")


if __name__ == "__main__":
    print("=" * 60)
    print("🌸 FLOWERSHOP: ЗАГРУЗКА ФОТОГРАФИЙ ТОВАРОВ")
    print("=" * 60)

    # Проверяем соединение с базой данных
    try:
        conn = get_conn()
        conn.close()
        print("✅ Соединение с базой данных: ОК")
    except Exception as e:
        print(f"❌ Ошибка подключения к базе данных: {e}")
        print("Проверьте настройки DB_CONFIG в скрипте")
        exit(1)

    # Проверяем токен бота
    try:
        bot_info = bot.get_me()
        print(f"✅ Бот: @{bot_info.username} ({bot_info.first_name})")
    except Exception as e:
        print(f"❌ Ошибка подключения к боту: {e}")
        print("Проверьте BOT_TOKEN_SHOP в скрипте")
        exit(1)

    while True:
        print("\n" + "=" * 60)
        print("📌 ГЛАВНОЕ МЕНЮ")
        print("=" * 60)
        print("1. 📤 Загрузить фото из папки 'product_photos'")
        print("2. 📋 Показать текущий статус фото")
        print("3. 🖼  Протестировать отображение фото")
        print("4. 📁 Создать образец структуры папки")
        print("5. ❌ Выход")

        choice = input("\n👉 Выберите действие (1-5): ").strip()

        if choice == "1":
            # Спрашиваем путь к папке
            default_dir = "product_photos"
            custom_dir = input(f"Введите путь к папке с фото [по умолчанию: {default_dir}]: ").strip()
            photos_dir = custom_dir if custom_dir else default_dir

            # Запрашиваем подтверждение
            print(f"\n⚠️  Вы уверены, что хотите загрузить фото из папки: {photos_dir}")
            confirm = input("Фото будут отправлены в Telegram и сохранены в БД (y/N): ").strip().lower()

            if confirm == 'y':
                process_photos(photos_dir)
            else:
                print("❌ Отменено")

        elif choice == "2":
            show_current_status()

        elif choice == "3":
            print(f"\n⚠️  Фото будут отправлены в чат ID: {TARGET_CHAT_ID}")
            confirm = input("Продолжить? (y/N): ").strip().lower()
            if confirm == 'y':
                test_photo_display()

        elif choice == "4":
            create_sample_photos()

        elif choice == "5":
            print("\n👋 Выход из программы...")
            break

        else:
            print("❌ Неверный выбор. Попробуйте снова.")

        # Пауза перед следующим выбором
        input("\nНажмите Enter чтобы продолжить...")
