from services.gsheets import get_client_report_reminders
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

async def send_client_report_reminders(app):
    #print("▶️ Запуск индивидуальных напоминаний клиентам...")

    reminders = get_client_report_reminders()
    #print(f"📋 Найдено напоминаний для клиентов: {len(reminders)}")
    for reminder in reminders:
        chat_id = reminder["chat_id"]
        tipo = reminder["tipo"]
        nombre = reminder["nombre"]
        docs = reminder["docs"]
        docs_text = "\n— " + "\n— ".join(d.strip() for d in docs.split(",") if d.strip())

        try:
            if tipo == "inicio":
                fin = reminder["fin"]
                msg = (
                    f"📄 Через 3 дня начинается подача декларации: *{nombre}*\n\n"
                    f"📎 Пожалуйста, отправь хестору до {fin}:{docs_text}\n\n"
                    f"📬 Так мы всё точно успеем 💪"
                )
                url = reminder.get("url", "").strip()
                if url:
                    msg += f"\n\n[ℹ️ Подробнее о декларации]({url})"
            elif tipo == "fin":
                limite = reminder["limite"]
                msg = (
                    f"⏰ Fecha Límite AEAT — крайний срок подачи декларации: *{nombre}*\n\n"
                    f"📎 Пожалуйста, срочно передай хестору:{docs_text}\n\n"
                    f"🙏 Чтобы он успел всё вовремя подготовить и сдать отчётность."
                )
                url = reminder.get("url", "").strip()
                if url:
                    msg += f"\n\n[ℹ️ Подробнее о декларации]({url})"
            # ВНЕ блока msg создаём клавиатуру
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 Документы отправлены", callback_data=f"submitted:{reminder['id_informe']}")]
            ])
            

            await app.bot.send_message(
                chat_id=chat_id,
                text=msg,
                parse_mode="Markdown",
                reply_markup=keyboard  # 👈 вот этого не хватало
            )
            #print(f"✅ Отправлено клиенту {chat_id} по декларации {nombre}")

        except Exception as e:
            #print(f"❌ Ошибка при отправке клиенту {chat_id}: {e}")
            pass

