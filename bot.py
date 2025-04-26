import os
from dotenv import load_dotenv
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from services.gsheets import find_rows_by_nif, update_telegram_ids
from utils.lang import get_text
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import date
from services.gsheets import get_all_active_subscribers
from utils.date_tools import is_two_days_before_last_working_day
import asyncio
from datetime import datetime, timedelta
from services.reminders import send_client_report_reminders
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler
from services.gsheets import mark_report_as_submitted
from datetime import time

# Загружаем токен из .en
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = 5183772550

waiting_for_nif = {}
waiting_for_consultation = {}  # ждём текст вопроса
consultation_data = {}         # временное хранилище текста и времени
waiting_for_consultation_time = {}
waiting_for_client_request = {}

# Стартовая команда

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Приветственное сообщение из lang.py
    await update.message.reply_text(get_text("intro_text"))

    # Кнопки
    keyboard = [
        [KeyboardButton("👋 Я уже с вами"), KeyboardButton("✨ Пока не с вами")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    # Вопрос: кто ты
    await update.message.reply_text(get_text("start_prompt"), reply_markup=reply_markup)

# Обработка выбора
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    # ⚠️ Проверка, что это сообщение, а не, например, стикер
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    if text.lower() in ["/menu", "📋 меню"] or text.strip() == "📋 Меню":
        user = update.effective_user
        chat_id = user.id

        # Определяем, кем является пользователь
        if waiting_for_nif.get(chat_id, False):
            keyboard = [
                [KeyboardButton("💶 Напоминания о Seguridad Social")],
                [KeyboardButton("🗓 Записаться на консультацию")],
                [KeyboardButton("📋 Меню")]
            ]
        else:
            keyboard = [
                [KeyboardButton("📩 Уведомления о подаче деклараций")],
                [KeyboardButton("💶 Напоминания о Seguridad Social")],
                [KeyboardButton("🗓 Консультация")],
                [KeyboardButton("🤝 Хочу работать с вами")],
                [KeyboardButton("📋 Меню")]
            ]

        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            "Вот что я могу для тебя сделать 👇",
            reply_markup=reply_markup
        )
        return
    #print(f"Текст от пользователя: {repr(text)}")
    if text == "/start":
        waiting_for_nif[chat_id] = False
        waiting_for_consultation[chat_id] = False
        waiting_for_consultation_time[chat_id] = False  # ← ВАЖНО: сбрасываем

        keyboard = [
            [KeyboardButton("👋 Я уже с вами"), KeyboardButton("✨ Пока не с вами")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(get_text("start_prompt"), reply_markup=reply_markup)
        return

    #print(f"Текст от пользователя: {repr(text)}")

    # 🟢 1. Если ждём время консультации — обрабатываем ПЕРВЫМИ
    if waiting_for_consultation_time.get(chat_id):
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

        await update.message.reply_text("Спасибо! Я записал твой запрос на консультацию. Мы с тобой скоро свяжемся 🤝")
        await update.message.reply_text("Хочешь вернуться в меню? Нажми 📋")
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=(
                f"📥 Новая заявка на консультацию!\n"
                f"👤 Пользователь: @{username}\n"
                f"💬 Вопрос: {consultation_data[chat_id]['question']}\n"
                f"🗓 Время: {consultation_data[chat_id]['time']}"
            )
        )
        return
    if waiting_for_client_request.get(chat_id):
        from services.gsheets import add_client_request
        user = update.effective_user
        username = user.username or f"{user.first_name} {user.last_name or ''}".strip()

        add_client_request(chat_id, username, text)

        await update.message.reply_text("Спасибо! Мы всё записали ✍️ И скоро с тобой свяжемся 🤝")
        await update.message.reply_text("Хочешь вернуться в меню? Нажми 📋")

        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=(
                f"🤝 Новая заявка на сотрудничество!\n"
                f"👤 Пользователь: @{username}\n"
                f"💬 Что написал: {text}"
            )
        )

        waiting_for_client_request[chat_id] = False
        return

    if waiting_for_consultation.get(chat_id):
        consultation_data[chat_id]["question"] = text
        waiting_for_consultation[chat_id] = False
        waiting_for_consultation_time[chat_id] = True
        await update.message.reply_text("Спасибо! Теперь напиши, когда тебе удобно — дату и время консультации.")
        return
    if waiting_for_nif.get(chat_id):
        nif = text
        from services.gsheets import find_rows_by_nif, update_telegram_ids
        rows = find_rows_by_nif(nif)

        if rows:
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
            await update.message.reply_text("К сожалению, твой NIF/NIE не найден. Проверь корректность.")

        waiting_for_nif[chat_id] = False
        return

    # Кнопка "Я клиент"
    if text == "👋 Я уже с вами":
        waiting_for_nif[chat_id] = True
        await update.message.reply_text("Пожалуйста, введите ваш NIF или NIE:")
    elif text == "✨ Пока не с вами":
        keyboard = [
            ["📩 Уведомления о подаче деклараций"],
            ["💶 Напоминания о Seguridad Social"],
            ["🗓 Консультация"],
            ["🤝 Хочу работать с вами"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            "Рада приветствовать тебя здесь 🤗\n"
            "Чем могу помочь? Выбери, пожалуйста:", reply_markup=reply_markup
        )
        return
    elif text == "📩 Уведомления о подаче деклараций":
        from services.gsheets import add_aeat_subscriber
        user = update.effective_user
        username = user.username or f"{user.first_name} {user.last_name or ''}".strip()

        add_aeat_subscriber(chat_id, username)

        await update.message.reply_text(
            "Отлично! Я добавлю тебя в список и буду напоминать, когда начнётся подача деклараций 📅")
        await update.message.reply_text("Хочешь вернуться в меню? Нажми 📋")

    elif text == "💶 Напоминания о Seguridad Social":
        from services.gsheets import add_subscriber_to_seguridad_social
        user = update.effective_user
        username = user.username or f"{user.first_name} {user.last_name or ''}".strip()

        add_subscriber_to_seguridad_social(chat_id, username)

        await update.message.reply_text("Я буду напоминать тебе за 2 дня до списания в Seguridad Social 💶")

    elif text == "🗓 Записаться на консультацию":
        waiting_for_consultation[chat_id] = True
        consultation_data[chat_id] = {}
        await update.message.reply_text("Кратко опиши свой вопрос:")
    elif text == "📩 Уведомления о подаче деклараций":
        await update.message.reply_text(
        "Отлично! Я добавлю тебя в список, чтобы присылать уведомления о сроках подачи деклараций 📅"
        )

    elif text == "🤝 Хочу работать с вами":
        waiting_for_client_request[chat_id] = True
        await update.message.reply_text(
            "Спасибо, что доверяешь нам 🤗\n\n"
            "Пожалуйста, напиши: имя, контакты (телефон или e-mail) и кратко, в чём нужна помощь 💼\n\n"
            "Я передам твой запрос хестору, и мы скоро с тобой свяжемся!"
        )
        await update.message.reply_text("Хочешь вернуться в меню? Нажми 📋")
    elif text == "🗓 Консультация":
        waiting_for_consultation[chat_id] = True
        consultation_data[chat_id] = {}
        await update.message.reply_text("Кратко опиши свой вопрос — мы с тобой свяжемся 💬")
    else:
        await update.message.reply_text(
        "Спасибо! Я всё записал 😊\n\n"
        "Если хочешь вернуться в меню — нажми 📋 Меню"
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
    await send_client_report_reminders(app)  # временный вызов
    # 👥 Обработчики команд и сообщений
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))  

    # ⏰ Планировщик задач
    scheduler = AsyncIOScheduler()

    # 📆 Ежедневная задача в 9:30 — рассылает напоминания о Seguridad Social
    scheduler.add_job(
        send_ss_reminders,
        trigger="cron",
        hour=9,
        minute=28,
        args=[app]
    )
    # 🕘 Ежедневная рассылка деклараций AEAT в 9:15
    scheduler.add_job(
        send_aeat_reminders,
        trigger="cron",
        hour=9,
        minute=18,
        args=[app]
    )
    from datetime import datetime, timedelta

    #персональные уведомления клиентам
    scheduler.add_job(send_client_report_reminders, "cron", hour=9, minute=15, args=[app])

    # Тестовая задача — отправка через 1 минуту
    #scheduler.add_job(
    #    send_aeat_reminders,
    #    trigger="date",
    #    run_date=datetime.now() + timedelta(minutes=1),
    #    args=[app]
    #)
    ## 🧪 Временная тестовая задача — срабатывает через 1 минуту после запуска
    #scheduler.add_job(
    #    send_ss_reminders,
    #    trigger="date",
    #    run_date=datetime.now() + timedelta(minutes=1),
    #    args=[app]
    #)
    scheduler.add_job(
        send_client_report_reminders,
        trigger="date",
        run_date=datetime.now() + timedelta(minutes=1),
        args=[app]
    )

    scheduler.add_job(
        send_good_morning,
        trigger='cron',
        hour=9,
        minute=0,
        timezone='Europe/Madrid',  # твой часовой пояс
        args=[app]  # передаём application в context
    )
    
    scheduler.start()



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