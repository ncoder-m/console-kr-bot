import asyncio
import logging
import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime, timedelta , timezone
import pytz
import os
from dotenv import load_dotenv
load_dotenv()
# ---- ОТПРАВКА НА ПОЧТУ ----
import aiosmtplib
from email.mime.text import MIMEText
from email.header import Header
# 🔥 Импортируем планировщик задач
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")  # !!! ЗАМЕНИТЕ НА ВАШ TELEGRAM ID (можно узнать у @userinfobot)
DB_NAME = "bot_database.db"

SMTP_HOST = os.getenv("SMTP_HOST")          # Для Яндекса: "smtp.yandex.ru"
SMTP_PORT = os.getenv("SMTP_PORT")                  # Стандартный защищенный порт SSL
SMTP_USER = os.getenv("SMTP_USER") # Почта, С КОТОРОЙ бот будет отправлять письма
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")    # !!! Пароль приложения (не обычный пароль от почты!)
TARGET_EMAIL = os.getenv("TARGET_EMAIL") # Почта, НА КОТОРУЮ должны приходить заявки

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

scheduler = AsyncIOScheduler(timezone=pytz.utc)


class QuizStates(StatesGroup):
    weight = State()
    length = State()
    lifting_height = State()
    phone = State()

# ---------------------------------------------------------------------------
# ФУНКЦИЯ АВТОДОГРЕВА (Вызывается планировщиком автоматически)
# ---------------------------------------------------------------------------
# async def send_reminder(bot_instance, user_id: int):
#     async with aiosqlite.connect(DB_NAME) as db:
#         # Проверяем, заполнил ли пользователь телефон (если заполнил, там будет статус 'completed')
#         async with db.execute(
#             "SELECT last_state FROM users WHERE user_id = ?", (user_id,)
#         ) as cursor:
#             row = await cursor.fetchone()
            
#     # Если пользователь до сих пор находится в состоянии ожидания телефона
#     if row and row[0] == "phone":
#         try:
#             # Меняем статус в БД, чтобы не слать догрев повторно
#             async with aiosqlite.connect(DB_NAME) as db:
#                 await db.execute(
#                     "UPDATE users SET last_state = 'reminded' WHERE user_id = ?", (user_id,)
#                 )
#                 await db.commit()

#             # Отправляем сообщение-напоминание
#             start_kb = ReplyKeyboardMarkup(
#                 keyboard=[[KeyboardButton(text="🏗️ Начать расчет стоимости")]],
#                 resize_keyboard=True
#             )
#             await bot_instance.send_message(
#                 chat_id=user_id,
#                 text="⏳ Вы остановились на последнем шаге расчета кран-балки!\n\n"
#                      "Инженер уже подготовил прайс-лист и готов составить смету. "
#                      "Нажмите /start, чтобы завершить расчет и отправить контакты.",
#                 reply_markup=start_kb
#             )
#             logging.info(f"Отправлено автоматическое напоминание пользователю {user_id}")
#         except Exception as e:
#             logging.error(f"Не удалось отправить напоминание: {e}")
async def send_reminder(bot_instance, user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        # Проверяем состояние пользователя
        async with db.execute(
            "SELECT last_state FROM users WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        
        # Если пользователь до сих пор находится в состоянии ожидания телефона
        if row and row[0] == "phone":
            try:
                # ОБНОВЛЯЕМ статус, используя ТЕКУЩЕЕ соединение db
                await db.execute(
                    "UPDATE users SET last_state = 'reminded' WHERE user_id = ?", 
                    (user_id,)
                )
                await db.commit()
                
                # Отправляем сообщение-напоминание
                start_kb = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="🏗️ Начать расчет стоимости")]],
                resize_keyboard=True
            )
                await bot_instance.send_message(
                chat_id=user_id,
                text="⏳ Вы остановились на последнем шаге расчета кран-балки!\n\n"
                     "Менеджер уже подготовил предложение и готов отправить его Вам. "
                     "Нажмите /start, чтобы завершить расчет и отправить контакты.",
                reply_markup=start_kb
            )
                logging.info(f"Отправлено автоматическое напоминание пользователю {user_id}")
                
            except Exception as e:
                logging.error(f"Не удалось отправить напоминание для {user_id}: {e}")
            
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                source TEXT,
                weight TEXT,
                length TEXT,
                lifting_height TEXT,
                phone TEXT,
                last_state TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

# Функция для быстрого обновления статуса пользователя в БД
async def update_db_status(user_id: int, state_name: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET last_state = ? WHERE user_id = ?", (state_name, user_id))
        await db.commit()

# ШАГ 1: Старт
@dp.message(Command("start"))
async def cmd_start(message: Message, command: CommandObject, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    username = message.from_user.username
    traffic_source = command.args if command.args else "organic"

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user_exists = await cursor.fetchone()
        
        if not user_exists:
            await db.execute(
                "INSERT INTO users (user_id, username, source, last_state) VALUES (?, ?, ?, ?)",
                (user_id, username, traffic_source, "start")
            )
            await db.commit()
        else:
            await db.execute("UPDATE users SET last_state = ? WHERE user_id = ?", ("start", user_id))
            await db.commit()

    start_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🏗️ Начать расчет стоимости")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer(
        "Приветствуем! Этот бот рассчитает стоимость козлового крана.",
        reply_markup=start_kb
    )

# ШАГ 2: Квиз - Вес
@dp.message(F.text == "🏗️ Начать расчет стоимости")
async def start_quiz(message: Message, state: FSMContext):
    await state.set_state(QuizStates.weight)
    await update_db_status(message.from_user.id, "weight") # Фиксируем шаг в БД
    
    weight_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="1 тонна"), KeyboardButton(text="2 тонны")],
            [KeyboardButton(text="3,2 тонны"), KeyboardButton(text="5 тонн")],
            [KeyboardButton(text="6,3 тонны"), KeyboardButton(text="10 тонн")],
            [KeyboardButton(text="12,5 тонн"), KeyboardButton(text="16 тонн")]
        ],
        resize_keyboard=True
    )
    await message.answer("Шаг 1 из 3:\nУкажите грузоподъемность крана:", reply_markup=weight_kb)

# ШАГ 3: Квиз - Длина
@dp.message(QuizStates.weight)
async def process_weight(message: Message, state: FSMContext):
    await state.update_data(chosen_weight=message.text)
    await state.set_state(QuizStates.length)
    await update_db_status(message.from_user.id, "length") # Фиксируем шаг в БД
    
    length_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="10 метров"), KeyboardButton(text="12 метров")],
            [KeyboardButton(text="16 метров"), KeyboardButton(text="20 метров")],
            [KeyboardButton(text="25 метров"), KeyboardButton(text="32 метра")]
        ],
        resize_keyboard=True
    )
    await message.answer("Шаг 2 из 3:\nУкажите длину пролета (в метрах):", reply_markup=length_kb)
    
# ШАГ 3,5: Квиз - Высота пролёта крана
@dp.message(QuizStates.length)
async def process_lifting_height(message: Message, state: FSMContext):
    await state.update_data(chosen_lifting_height=message.text)
    await state.set_state(QuizStates.lifting_height)
    await update_db_status(message.from_user.id, "lifting_height") # Фиксируем шаг в БД
    
    lifting_height_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="3 метра"), KeyboardButton(text="6 метров")],
            [KeyboardButton(text="9 метров"), KeyboardButton(text="12 метров")],
            [KeyboardButton(text="18 метров"), KeyboardButton(text="Без тали")]
        ],
        resize_keyboard=True
    )
    await message.answer("Шаг 3 из 3:\nУкажите высоту подъёма (в метрах):", reply_markup=lifting_height_kb)

# ШАГ 4: Квиз - Длина (Здесь включается таймер догрева)
@dp.message(QuizStates.lifting_height)
async def process_length(message: Message, state: FSMContext):
    await state.update_data(chosen_length=message.text)
    await state.set_state(QuizStates.phone)
    
    user_id = message.from_user.id
    
    # Сначала фиксируем в БД, что пользователь дошел до шага телефона
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET last_state = 'phone' WHERE user_id = ?", (user_id,))
        await db.commit()
    
    # 🔥 НАСТРОЙКА ТАЙМЕРА АВТОДОГРЕВА
    # Планируем отправку сообщения через 15 минут. 
    # (Для быстрого теста во время разработки можете заменить "minutes=15" на "seconds=30")
    if scheduler.get_job(f"remind_{user_id}"):
        scheduler.remove_job(f"remind_{user_id}")
    
    # scheduler.add_job(
    #     send_reminder,
    #     trigger="date",
    #     run_date=datetime.now(pytz.utc) + timedelta(seconds=30),
    #     args=[bot,user_id],
    #     id=f"remind_{user_id}" # Уникальный ID задачи по ID пользователя
    # )
    scheduler.add_job(
    send_reminder,
    trigger="date",
    # Используем стандартный timezone.utc вместо pytz
    run_date=datetime.now(timezone.utc) + timedelta(seconds=30),
    args=[bot, user_id],
    id=f"remind_{user_id}",
    replace_existing=True # Важно! Перезапишет задачу, если пользователь нажал кнопку снова
)
    scheduler.print_jobs()
    logging.info(f"Запланирован догрев для пользователя {user_id} через 15 минут.")

    phone_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить номер телефона", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("Последний шаг:\nНажмите кнопку ниже для отправки контакта:", reply_markup=phone_kb)

# ШАГ 5: Финал, запись в БД и ОТМЕНА догрева
@dp.message(QuizStates.phone, F.contact)
async def process_phone(message: Message, state: FSMContext):
    user_id = message.from_user.id
    phone_number = message.contact.phone_number
    username = f"@{message.from_user.username}" if message.from_user.username else "Нет юзернейма"
    
    user_data = await state.get_data()
    weight = user_data.get("chosen_weight")
    length = user_data.get("chosen_length")
    lifting_height = user_data.get("chosen_lifting_height")
    
    # 🔥 ОТМЕНА ТАЙМЕРА АВТОДОГРЕВА (так как пользователь вовремя прислал телефон)
    try:
        scheduler.remove_job(job_id=f"remind_{user_id}")
        logging.info(f"Догрев для пользователя {user_id} успешно отменен.")
    except Exception:
        pass # Если задача уже успела выполнилась или её нет — просто игнорируем ошибку

    # Сохраняем финальные данные и ставим статус 'completed'
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE users SET weight = ?, length = ?, lifting_height = ?, phone = ?, last_state = 'completed' WHERE user_id = ?",
            (weight, length,lifting_height, phone_number, user_id)
        )
        async with db.execute("SELECT source FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            source = row[0] if row else "unknown"
        await db.commit()
    
    await state.clear()
    await message.answer(
        "🎯 Расчет принят! Наш менеджер свяжется с вами в ближайшее время.\n\n"
        "Есть вопросы? Позвоните по номеру 8-937-298-35-55\n\n"
        "Не нашли подходящего вам параметра? Советуем посетить наш сайт https://kran-balka.com",
        reply_markup=ReplyKeyboardRemove())
    
    # Текст заявки (общий для ТГ и Email)
    report_text = (
        f"👤 Клиент: {username} (ID: {user_id})\n"
        f"📞 Телефон: {phone_number}\n"
        f"🏗️ Грузоподъемность: {weight}\n"
        f"📏 Длина пролета: {length}\n"
        f"📏 Высота подъёма: {lifting_height}\n"
        f"📈 Источник рекламы: {source}"
    )

    # 2. 🔥 ОТПРАВКА ЗАЯВКИ В ЛИЧКУ АДМИНУ ТЕЛЕГРАМ
    try:
        await bot.send_message(
            chat_id=ADMIN_ID, 
            text=f"🚨 **НОВАЯ ЗАЯВКА НА КОНСОЛЬНЫЙ КРАН!**\n\n{report_text}"
        )
    except Exception as e:
        logging.error(f"Ошибка отправки в Telegram: {e}")

    # 3. 🔥 ОТПРАВКА ЗАЯВКИ НА ЭЛЕКТРОННУЮ ПОЧТУ
    try:
        # Формируем стандартное письмо
        msg = MIMEText(report_text, "plain", "utf-8")
        msg["Subject"] = Header(f"Новая заявка на кран-балку от {phone_number}", "utf-8")
        msg["From"] = SMTP_USER
        msg["To"] = TARGET_EMAIL

        # Подключаемся к SMTP серверу и отправляем асинхронно
        await aiosmtplib.send(
            msg,
            hostname=SMTP_HOST,
            port=SMTP_PORT,
            username=SMTP_USER,
            password=SMTP_PASSWORD,
            use_tls=True
        )
        logging.info(f"Заявка успешно продублирована на почту {TARGET_EMAIL}")
    except Exception as e:
        logging.error(f"Не удалось отправить письмо на почту: {e}")

@dp.message(QuizStates.phone)
async def process_phone_text(message: Message):
    await message.answer("Пожалуйста, используйте кнопку «📱 Отправить номер телефона» ниже.")

# ---------------------------------------------------------------------------
# 5. АДМИН-КОМАНДА ДЛЯ ПОВТОРНОЙ РАССЫЛКИ ПО «БРОШЕННЫМ КВИЗАМ»
# ---------------------------------------------------------------------------
@dp.message(Command("broadcast_unfinished"))
async def cmd_broadcast_unfinished(message: Message):
    # Доступ только для админа
    if message.from_user.id != ADMIN_ID:
        return

    # Извлекаем текст рассылки (всё, что идет после команды /broadcast_unfinished )
    broadcast_text = message.text[22:].strip()
    if not broadcast_text:
        await message.answer("Использование: `/broadcast_unfinished Введите текст сообщения для догрева лидов`", parse_mode="Markdown")
        return

    async with aiosqlite.connect(DB_NAME) as db:
        # Выбираем только тех, кто застрял на шагах weight, length или phone, но НЕ завершил квиз
        async with db.execute(
            "SELECT user_id FROM users WHERE last_state IN ('weight', 'length', 'lifting_height', 'phone')"
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await message.answer("Нет пользователей, которые не завершили квиз.")
        return

    success_count = 0
    for row in rows:
        target_user_id = row[0]
        try:
            await bot.send_message(chat_id=target_user_id, text=broadcast_text)
            success_count += 1
            await asyncio.sleep(0.05) # Защита от флуд-контроля Telegram
        except Exception:
            pass # Игнорируем заблокировавших бота пользователей

    await message.answer(f"📢 Рассылка завершена. Успешно отправлено {success_count} пользователям из {len(rows)} оставшихся.")

async def main():
    await init_db()
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        import asyncio
        asyncio.run(main())
    except Exception as e:
        logging.error(f"Произошла ошибка при запуске бота: {e}")