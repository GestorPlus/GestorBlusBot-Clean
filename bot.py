import os
from dotenv import load_dotenv
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, filters
from services.gsheets import find_rows_by_nif, update_telegram_ids, get_all_active_subscribers, mark_report_as_submitted, add_or_update_user_visit
from utils.lang import get_text
from utils.date_tools import is_two_days_before_last_working_day
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio
from datetime import date, datetime, time, timedelta
from services.reminders import send_client_report_reminders



# Загружаем токен из .env
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = 5183772550
GROUP_CHAT_ID=-1002423634049

waiting_for_nif = {}
MAX_NIF_ATTEMPTS = 3  # Максимум 3 попытки ввода NIF
waiting_for_consultation = {}  # ждём текст вопроса
consultation_data = {}         # временное хранилище текста и времени
waiting_for_consultation_time = {}
waiting_for_client_request = {}
nif_attempts = {}  # счётчик попыток ввода NIF/NIE
is_known_client = {}  # статус: chat_id → True, если пользователь ввёл корректный NIF/NIE
visited_users = {}      # chat_id → дата первого визита (datetime.date)
visit_counts = {}       # chat_id → число визитов

# 📋 Клавиатура с кнопкой "Меню"
def get_menu_keyboard():
    keyboard = [
        [KeyboardButton("📋 Меню")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
# Стартовая команда

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Получаем chat_id
    chat_id = update.effective_chat.id

    # — Блок учёта визитов —
    first_visit = visited_users.get(chat_id)
    if not first_visit:
        visited_users[chat_id] = date.today()
        visit_counts[chat_id] = 1
    else:
        visit_counts[chat_id] += 1
    # — Конец блока —

    # Здесь вызываем запись в Google Sheet
    user = update.effective_user
    username = user.username or f"{user.first_name} {user.last_name or ''}".strip()
    add_or_update_user_visit(
        chat_id,
        username,
        visited_users[chat_id],   # дата первого визита
        visit_counts[chat_id]     # текущее число визитов
    )
    waiting_for_nif[update.effective_chat.id] = False
    waiting_for_consultation[update.effective_chat.id] = False
    waiting_for_consultation_time[update.effective_chat.id] = False

    keyboard = [
        [KeyboardButton("👋 Я уже с вами"), KeyboardButton("✨ Пока не с вами")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    text = f"{get_text('intro_text')}\n\n{get_text('start_prompt')}"
    await update.message.reply_text(text, reply_markup=reply_markup)

# После всех импортов и глобальных переменных:

async def send_menu(chat_id, context: ContextTypes.DEFAULT_TYPE):
    is_client = chat_id in consultation_data or not waiting_for_nif.get(chat_id, False)

    if is_client:
        # 🔐 Меню клиента
        keyboard = [
            [KeyboardButton("💶 Напоминания о Seguridad Social")],
            [KeyboardButton("🗓 Консультация")],
            [KeyboardButton("🤝 Хочу работать с вами")], 
        ]
    else:
        # 🌱 Меню для новых пользователей
        keyboard = [
            [KeyboardButton("📩 Уведомления о подаче деклараций")],
            [KeyboardButton("💶 Напоминания о Seguridad Social")],
            [KeyboardButton("🗓 Консультация")],
            [KeyboardButton("🤝 Хочу работать с вами")], 
        ]

    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await context.bot.send_message(
        chat_id=chat_id,
        text="Вот что я могу для тебя сделать 👇",
        reply_markup=reply_markup
    )

# Обработка выбора
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    # Проверка, что сообщение есть и оно не пустое
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    # Обработка команды "📋 Меню"
    if text.lower() in ["/menu", "📋 меню"] or text.strip() == "📋 Меню":
        await send_menu(chat_id, context)
        return

    # Стартовая команда
    if text == "/start":
        waiting_for_nif[chat_id] = False
        waiting_for_consultation[chat_id] = False
        waiting_for_consultation_time[chat_id] = False

        keyboard = [
            [KeyboardButton("👋 Я уже с вами"), KeyboardButton("✨ Пока не с вами")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(get_text("start_prompt"), reply_markup=reply_markup)
        return

    # Проверка на ожидание времени для консультации
    if waiting_for_consultation_time.get(chat_id):
        await handle_consultation_time(chat_id, text, update, context)
        return

    # Проверка на запрос клиента
    if waiting_for_client_request.get(chat_id):
        await handle_client_request(chat_id, text, update, context)
        return

    # Проверка на ожидание описания консультации
    if waiting_for_consultation.get(chat_id):
        await handle_consultation(chat_id, text, update, context)
        return

    # Проверка на ввод NIF
    if waiting_for_nif.get(chat_id):
        await handle_nif(chat_id, text, update)
        return

    # Если никаких специальных условий нет, обрабатываем стандартное меню
    await handle_standard_menu(chat_id, text, update, context)


async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_menu(update.effective_chat.id, context)
# 🟢 Обрабатываем время консультации
async def handle_consultation_time(chat_id, text, update, context):
    consultation_data[chat_id]["time"] = text
    waiting_for_consultation_time[chat_id] = False

    from services.gsheets import add_consultation_to_sheet
    user = update.effective_user
    username = user.username or f"{user.first_name} {user.last_name or ''}".strip()

    add_consultation_to_sheet(
        chat_id=chat_id,
        question=consultation_data[chat_id]["question"],
        preferred_time=consultation_data[chat_id]["time"],
        username=username
    )

    keyboard = [
        [KeyboardButton("📋 Меню")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "Спасибо! Я записал твой запрос на консультацию. Мы с тобой скоро свяжемся 🤝\n\n"
        "Хочешь вернуться в меню? Нажми 📋",
        reply_markup=reply_markup
    )

    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"📥 Новая заявка на консультацию!\n"
             f"👤 Пользователь: @{username}\n"
             f"💬 Вопрос: {consultation_data[chat_id]['question']}\n"
             f"🗓 Время: {consultation_data[chat_id]['time']}"
    )

    # дублируем в групповой чат
    await context.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text=f"📥 Новая заявка на консультацию!\n"
            f"👤 @{username}\n"
            f"💬 {consultation_data[chat_id]['question']}\n"
            f"🗓 {consultation_data[chat_id]['time']}"
    )

# 🟢 Обрабатываем заявку на клиента
async def handle_client_request(chat_id, text, update, context):
    from services.gsheets import add_client_request
    user = update.effective_user
    username = user.username or f"{user.first_name} {user.last_name or ''}".strip()

    add_client_request(chat_id, username, text)

    keyboard = [
        [KeyboardButton("📋 Меню")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "Спасибо! Мы всё записали ✍️ И скоро с тобой свяжемся 🤝\n\n"
        "Хочешь вернуться в меню? Нажми 📋",
        reply_markup=reply_markup
    )

    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"🤝 Новая заявка на сотрудничество!\n"
             f"👤 Пользователь: @{username}\n"
             f"💬 Что написал: {text}"
    )
    await context.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text=f"🤝 Новая заявка на сотрудничество!\n"
             f"👤 Пользователь: @{username}\n"
             f"💬 Что написал: {text}"
    )

    waiting_for_client_request[chat_id] = False

# 🟢 Обрабатываем заявку на консультацию (описание вопроса)
async def handle_consultation(chat_id, text, update, context):
    consultation_data[chat_id] = {"question": text}
    waiting_for_consultation[chat_id] = False
    waiting_for_consultation_time[chat_id] = True
    await update.message.reply_text("Спасибо! Теперь напиши дату и время, когда тебе удобно для консультации 📅")

# 🟢 Обрабатываем ввод NIF/NIE
async def handle_nif(chat_id, text, update):
    # считаем попытку
    nif_attempts[chat_id] = nif_attempts.get(chat_id, 0) + 1

    from services.gsheets import find_rows_by_nif, update_telegram_ids
    rows = find_rows_by_nif(text)

    if rows:
        # успех — сбрасываем счётчик и флаг ожидания
        nif_attempts.pop(chat_id, None)
        waiting_for_nif[chat_id] = False
        is_known_client[chat_id] = True

        update_telegram_ids(rows, chat_id)
        await update.message.reply_text(
            "Спасибо! Я нашёл тебя в системе и настроил персональные напоминания 🧾\n"
            "Чем еще я могу помочь 👇"
        )

        keyboard = [
            ["💶 Напоминания о Seguridad Social"],
            ["🗓 Записаться на консультацию"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Что тебе нужно? Выбери, пожалуйста:", reply_markup=reply_markup)

    else:
        # не нашли — проверяем, сколько осталось попыток
        attempts = nif_attempts[chat_id]
        if attempts < MAX_NIF_ATTEMPTS:
            left = MAX_NIF_ATTEMPTS - attempts
            waiting_for_nif[chat_id] = True
            await update.message.reply_text(
                f"К сожалению, твой NIF/NIE не найден. Осталось попыток: {left}. Проверь корректность и попробуй ещё раз."
            )
        else:
            # исчерпали — возврат к выбору клиента или новичка
            nif_attempts.pop(chat_id, None)
            waiting_for_nif[chat_id] = False
            await update.message.reply_text("К сожалению, вы исчерпали 3 попытки. Вернёмся к началу.")

            # выводим исходный выбор (👋 Я уже с вами / ✨ Пока не с вами)
            keyboard = [
                [KeyboardButton("👋 Я уже с вами"), KeyboardButton("✨ Пока не с вами")]
            ]
            markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(get_text("start_prompt"), reply_markup=markup)

# 🟢 Обрабатываем обычные нажатия кнопок
async def handle_standard_menu(chat_id, text, update, context):
    user = update.effective_user
    username = user.username or f"{user.first_name} {user.last_name or ''}".strip()

    # Меню клиентов
    client_menu = ReplyKeyboardMarkup(
        [
            [KeyboardButton("💶 Напоминания о Seguridad Social")],
            [KeyboardButton("🗓 Консультация")]
        ],
        resize_keyboard=True
    )

    # Меню новичков
    new_user_menu = ReplyKeyboardMarkup(
        [
            [KeyboardButton("📩 Уведомления о подаче деклараций")],
            [KeyboardButton("💶 Напоминания о Seguridad Social")],
            [KeyboardButton("🗓 Консультация")],
            [KeyboardButton("🤝 Хочу работать с вами")]
        ],
        resize_keyboard=True
    )

    # Если уже клиент — запрашиваем NIF
    if text == "👋 Я уже с вами":
        waiting_for_nif[chat_id] = True
        await update.message.reply_text("Пожалуйста, введите ваш NIF или NIE:")
        return

    # Новичок впервые
    if text == "✨ Пока не с вами":
        await update.message.reply_text(
            "Рада приветствовать тебя здесь 🤗\n\nЧем могу помочь? Выбери, пожалуйста:",
            reply_markup=new_user_menu
        )
        return

    # Подписки и действия
    if text == "📩 Уведомления о подаче деклараций":
        from services.gsheets import add_aeat_subscriber
        add_aeat_subscriber(chat_id, username)
        markup = client_menu if is_known_client.get(chat_id) else new_user_menu
        await update.message.reply_text(
            "Отлично! Я буду напоминать тебе о сроках подачи деклараций 📅",
            reply_markup=markup
        )
        return

    if text == "💶 Напоминания о Seguridad Social":
        from services.gsheets import add_subscriber_to_seguridad_social
        add_subscriber_to_seguridad_social(chat_id, username)
        markup = client_menu if is_known_client.get(chat_id) else new_user_menu
        await update.message.reply_text(
            "Я буду напоминать тебе за 2 дня до списания в Seguridad Social 💶",
            reply_markup=markup
        )
        return

    if text == "🗓 Консультация":
        waiting_for_consultation[chat_id] = True
        consultation_data[chat_id] = {}
        markup = client_menu if is_known_client.get(chat_id) else ReplyKeyboardMarkup([[KeyboardButton("📋 Меню")]], resize_keyboard=True)
        await update.message.reply_text(
            "✍️ Кратко опиши свой вопрос.\n\nЯ постараюсь помочь как можно быстрее!",
            reply_markup=markup
        )
        return

    if text == "🤝 Хочу работать с вами":
        waiting_for_client_request[chat_id] = True
        markup = client_menu if is_known_client.get(chat_id) else new_user_menu
        await update.message.reply_text(
            "Спасибо за доверие 🤗\n\nПожалуйста, напиши: имя, контакты (телефон или e-mail) и кратко в чём нужна помощь 💼",
            reply_markup=markup
        )
        return

    # По умолчанию — кнопка "Меню"
    await update.message.reply_text(
        "Спасибо! Я всё записал 😊\n\nЕсли хочешь вернуться в меню — нажми 📋 Меню",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("📋 Меню")]], resize_keyboard=True)
    )

    # Уведомление о списании в Seguridad Social
async def send_ss_reminders(app):
    from services.gsheets import get_all_active_subscribers
    from utils.date_tools import is_two_days_before_last_working_day
    from datetime import date

    #print("▶️ Запуск send_ss_reminders...")  # лог старта
    if is_two_days_before_last_working_day(date.today()):
        subscribers = get_all_active_subscribers()
        #print(f"📋 Найдено подписчиков: {len(subscribers)}")  # лог количества

        for chat_id in subscribers:
            try:
                await app.bot.send_message(
                    chat_id=chat_id,
                    text="💶 Напоминаем: через 2 дня будет списание в Seguridad Social. Пожалуйста, проверь, чтобы на счёте были средства."
                )
            
                #print(f"✅ Отправлено: {chat_id}")
            except Exception as e:
                #print(f"❌ Ошибка для {chat_id}: {e}")
                pass
    else:
        #print("⏸ Сегодня не день для напоминания (is_two_days_before_last_working_day = False)")
        pass

#рассылка по декларациям неклиентам
async def send_aeat_reminders(app):
    from services.gsheets import get_today_aeat_reports, get_all_active_subscribers

    reports = get_today_aeat_reports()
    if not reports:
        #print("📭 Сегодня нет новых деклараций AEAT")
        return

    subscribers = get_all_active_subscribers(column="AEAT")
    #print(f"📋 Подписчиков на AEAT: {len(subscribers)}")

    for report in reports:
        nombre, fecha_limite, url = report
        for chat_id in subscribers:
            try:
                message = (
                    f"📄 Сегодня начинается период подачи декларации *{nombre}*.\n"
                    f"📅 Крайний срок подачи: {fecha_limite}\n"
                )
                if url:
                    message += f"[ℹ️ Подробнее о декларации]({url})"

                await app.bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")
                #print(f"✅ Отправлено: {chat_id}")
            except Exception as e:
                #print(f"❌ Ошибка при отправке для {chat_id}: {e}")
                pass
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("submitted:"):
        id_informe = data.split(":")[1]
        chat_id = query.from_user.id
        

        success = mark_report_as_submitted(chat_id, id_informe)

        if success:
            # Только если клавиатура есть — убираем
            if query.message.reply_markup:
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except Exception as e:
                    #print(f"⚠️ Не удалось убрать клавиатуру: {e}")
                    pass

            await query.message.reply_text("📥 Спасибо! Пометили, что документы отправлены. Мы всё подготовим 🙌")
        else:
            await query.message.reply_text("⚠️ Не удалось обновить статус. Напиши, пожалуйста, вручную.")

#я работаю каждое утро
async def send_good_morning(context: ContextTypes.DEFAULT_TYPE):
    chat_id = 5183772550  # твой Telegram ID
    await context.bot.send_message(chat_id=chat_id, text="☀️ Доброе утро! Бот работает стабильно 😊")

# Запуск бота
async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    # 👥 Обработчики команд и сообщений
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(CommandHandler("menu", handle_menu))  

    # ⏰ Планировщик задач
    scheduler = AsyncIOScheduler()

    # 📆 Ежедневная задача в 9:28 — напоминание о Seguridad Social
    scheduler.add_job(
        send_ss_reminders,
        trigger="cron",
        hour=9,
        minute=28,
        timezone='Europe/Madrid',
        args=[app]
    )

    # 🕘 Ежедневная рассылка деклараций AEAT в 9:18
    scheduler.add_job(
        send_aeat_reminders,
        trigger="cron",
        hour=9,
        minute=18,
        timezone='Europe/Madrid',
        args=[app]
    )

    # 🌟 Персональные уведомления клиентам в 9:15
    scheduler.add_job(
        send_client_report_reminders,
        trigger="cron",
        hour=9,
        minute=15,
        timezone='Europe/Madrid',
        args=[app]
    )

    # ☀️ Доброе утро в 9:00
    scheduler.add_job(
        send_good_morning,
        trigger='cron',
        hour=9,
        minute=0,
        timezone='Europe/Madrid',
        args=[app]
    )

    scheduler.start()
    await app.run_polling()




    # 🚀 Запуск бота
    await app.run_polling()
# Для ручного теста
# asyncio.get_event_loop().run_until_complete(send_client_report_reminders(app))
if __name__ == "__main__":
    import asyncio
    import nest_asyncio
    
    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())