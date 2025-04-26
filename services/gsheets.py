import gspread
import os
import json
from google.oauth2 import service_account

if not os.path.exists('credentials.json'):
    credentials_data = {
        "type": "service_account",
        "project_id": os.getenv("GOOGLE_PROJECT_ID"),
        "private_key_id": os.getenv("GOOGLE_PRIVATE_KEY_ID"),
        "private_key": os.getenv("GOOGLE_PRIVATE_KEY").replace('\\n', '\n'),
        "client_email": os.getenv("GOOGLE_CLIENT_EMAIL"),
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{os.getenv('GOOGLE_CLIENT_EMAIL').replace('@', '%40')}"
    }
    with open('credentials.json', 'w') as f:
        json.dump(credentials_data, f)

def get_gsheet_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    credentials = service_account.Credentials.from_service_account_file('credentials.json', scopes=scopes)
    return gspread.authorize(credentials)


# Поиск клиента по NIF/NIE
def find_rows_by_nif(nif: str):
    gc = get_gsheet_client()
    sheet = gc.open_by_key("1MJpg-462leENvyX3ixLjwjZwiFqZo7U7wYnjjzpHZv4").sheet1
    data = sheet.get_all_records()

    cleaned_nif = nif.strip().replace(" ", "").upper()
    matched_rows = []

    for i, row in enumerate(data, start=2):  # начиная со 2-й строки
        sheet_nif = str(row.get("NIF", "")).strip().replace(" ", "").upper()
        if sheet_nif == cleaned_nif:
            matched_rows.append(i)

    return matched_rows

#сохраняем telegram id в таблице
def update_telegram_ids(row_numbers: list[int], telegram_id: int):
    gc = get_gsheet_client()
    sheet = gc.open_by_key("1MJpg-462leENvyX3ixLjwjZwiFqZo7U7wYnjjzpHZv4").sheet1
    headers = sheet.row_values(1)

    # Найдём индекс колонки "ID Telegram"
    telegram_col_index = None
    for idx, name in enumerate(headers, start=1):
        if name.strip().lower() == "id telegram":
            telegram_col_index = idx
            break

    if telegram_col_index is None:
        raise ValueError("Колонка 'ID Telegram' не найдена")

    # Обновим значение во всех строках
    for row in row_numbers:
        sheet.update_cell(row, telegram_col_index, str(telegram_id))

#запись на консультацию
def add_consultation_to_sheet(chat_id: int, question: str, preferred_time: str, username: str):
    gc = get_gsheet_client()
    sheet = gc.open_by_key("1FXQ3E15_2ntV_BtQNjJTHKICPihkRhUUnjfMjEi-RPk").sheet1
    from datetime import datetime
    sheet.append_row([
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        str(chat_id),
        username,
        question,
        preferred_time
    ])

#уведомления сегуридад социаль добавления в список
from datetime import datetime

def add_subscriber_to_seguridad_social(telegram_id: int, username: str):
    gc = get_gsheet_client()
    sheet = gc.open_by_key("1AmvN1TiC9oIHCpy6rKlwX4b5tIK-CdLsYtZh6dkLoks").sheet1
    data = sheet.get_all_records()

    for row in data:
        cleaned_row = {k.strip(): v for k, v in row.items()}

        try:
            existing_id = int(str(cleaned_row.get("ID Telegram", "")).strip())
            active = str(cleaned_row.get("Activo", "")).strip().lower()
        except:
            continue

        if existing_id == telegram_id and active == "sí":
            #print(f"🔁 Уже есть активная подписка для ID {telegram_id}")
            return

    # Добавляем новую строку только если НЕ найдено активной записи
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sheet.append_row([now, str(telegram_id), username, "sí"])
    #print(f"✅ Добавлен новый подписчик: {telegram_id}")

#уведомления сегуридад социаль
def get_all_active_subscribers(column="Activo"):
    gc = get_gsheet_client()
    sheet = gc.open_by_key("1AmvN1TiC9oIHCpy6rKlwX4b5tIK-CdLsYtZh6dkLoks").sheet1
    data = sheet.get_all_records()
    subscribers = []

    for row in data:
        # Удалим пробелы и \n из заголовков
        cleaned_row = {k.strip(): v for k, v in row.items()}
        #print(f"▶️ Строка: {cleaned_row}")  # отладка

        value = str(cleaned_row.get(column, "")).strip().lower()
        #print(f"🔍 Значение '{column}': {value}")  # отладка

        if value == "sí":
            try:
                subscribers.append(int(cleaned_row["ID Telegram"]))
            except Exception as e:
                #print(f"❌ Ошибка при добавлении ID: {e}")
                continue

    #print(f"📋 Найдено подписчиков по {column}: {len(subscribers)}")
    return subscribers

#Подписка AEAT для неклиентов-аутономо
def add_aeat_subscriber(telegram_id: int, username: str):
    gc = get_gsheet_client()
    sheet = gc.open_by_key("1AmvN1TiC9oIHCpy6rKlwX4b5tIK-CdLsYtZh6dkLoks").sheet1
    data = sheet.get_all_records()

    for i, row in enumerate(data, start=2):
        cleaned_row = {k.strip(): v for k, v in row.items()}
        existing_id = cleaned_row.get("ID Telegram")
        try:
            if int(existing_id) == telegram_id:
                sheet.update_cell(i, 5, "sí")  # колонка 5 = "AEAT"
                #print(f"🔁 Обновлена подписка AEAT для {telegram_id}")
                return
        except:
            continue

    # Если ID не найден, создаём новую строку
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sheet.append_row([now, str(telegram_id), username, "no", "sí"])
    #print(f"✅ Добавлен новый AEAT-подписчик: {telegram_id}")

def get_today_aeat_reports():
    gc = get_gsheet_client()
    sheet = gc.open_by_key("1EhIIQba03rkyeRI87a_WiC9dT45W9b28Nd65MlWf1E0").sheet1
    data = sheet.get_all_records()

    today = datetime.today().date().strftime("%d/%m/%Y")
    reports = []

    for row in data:
        if str(row.get("autonomo", "")).strip().lower() == "да":
            inicio = str(row.get("Inicio Recepción", "")).strip()
            if inicio == today:
                nombre = str(row.get("Nombre Informe", "")).strip()
                deadline = str(row.get("Fecha Límite AEAT", "")).strip()
                reports.append((nombre, deadline))

    return reports

#рассылка информации по декларациям для неклиентов - аутономо
def get_today_aeat_reports():
    gc = get_gsheet_client()
    sheet = gc.open_by_key("1EhIIQba03rkyeRI87a_WiC9dT45W9b28Nd65MlWf1E0").sheet1
    data = sheet.get_all_records()

    today = datetime.today().strftime("%d/%m/%Y")
    reports = []

    for row in data:
        inicio = str(row.get("Inicio Recepción", "")).strip()
        if inicio == today:
            nombre = str(row.get("Nombre Informe", "")).strip()
            fecha_limite = str(row.get("Fecha Límite AEAT", "")).strip()
            url = str(row.get("URL", "")).strip() if row.get("URL") else ""
            reports.append((nombre, fecha_limite, url))

    return reports

#заявка стать клиентом
def add_client_request(chat_id: int, username: str, message: str):
    gc = get_gsheet_client()
    sheet = gc.open_by_key("1FXQ3E15_2ntV_BtQNjJTHKICPihkRhUUnjfMjEi-RPk").sheet1
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Добавляем в таблицу новую строку с пометкой "хочу стать клиентом"
    sheet.append_row([now, str(chat_id), username, message, "", "хочу стать клиентом"])

#напоминания клиентам
from datetime import datetime, timedelta

def get_client_report_reminders():
    gc = get_gsheet_client()
    reportes_sheet = gc.open_by_key("1EhIIQba03rkyeRI87a_WiC9dT45W9b28Nd65MlWf1E0").sheet1
    tareas_sheet = gc.open_by_key("1MJpg-462leENvyX3ixLjwjZwiFqZo7U7wYnjjzpHZv4").sheet1

    reportes_data = reportes_sheet.get_all_records()
    tareas_data = tareas_sheet.get_all_records()

    today = datetime.now().date()
    reminders = []
    
    #print(f"📅 Сегодняшняя дата: {today.strftime('%d/%m/%Y')}")

    for tarea in tareas_data:
        tarea = {k.strip(): v for k, v in tarea.items()}
        id_informe = tarea.get("ID Informe")
        chat_id = tarea.get("ID Telegram")
        if not id_informe or not chat_id:
            continue

        matching_reports = [r for r in reportes_data if r.get("ID Informe") == id_informe]
        for report in matching_reports:
            report = {k.strip(): v for k, v in report.items()}
            nombre = report.get("Nombre Informe", "").strip()
            fecha_limite = report.get("Fecha Límite AEAT", "").strip()
            inicio = report.get("Inicio Recepción", "").strip()
            fin = report.get("Fin Recepción", "").strip()
            docs = report.get("Documentos Requeridos", "").strip()
            url = report.get("URL", "").strip()

            try:
                inicio_date = datetime.strptime(inicio, "%d/%m/%Y").date()
                fin_date = datetime.strptime(fin, "%d/%m/%Y").date()
                limite_date = datetime.strptime(fecha_limite, "%d/%m/%Y").date()
            except:
                continue
            #print(f"🔍 Проверяем: {nombre}")
            #print(f"📅 Начало приёма: {inicio_date}, Конец приёма: {fin_date}, Крайний срок: {limite_date}")
            #print(f"📆 Сегодня: {today}")
            if inicio_date - timedelta(days=3) == today:
                reminders.append({
                    "chat_id": chat_id,
                    "tipo": "inicio",
                    "nombre": nombre,
                    "fin": fin_date.strftime("%d/%m/%Y"),
                    "docs": docs,
                    "id_informe": id_informe,
                    "url": url
                })

            if fin_date - timedelta(days=1) == today:
                reminders.append({
                    "chat_id": chat_id,
                    "tipo": "fin",
                    "nombre": nombre,
                    "limite": fecha_limite,
                    "docs": docs,
                    "id_informe": id_informe,
                    "url": url 
                })

    return reminders

#отмечаем загрузку отчета по кнопке
def mark_report_as_submitted(chat_id, id_informe):
    gc = get_gsheet_client()
    sheet = gc.open_by_key("1MJpg-462leENvyX3ixLjwjZwiFqZo7U7wYnjjzpHZv4").sheet1
    data = sheet.get_all_records()

    for i, row in enumerate(data, start=2):  # начинаем с 2, т.к. первая строка — заголовки
        cleaned_row = {k.strip(): v for k, v in row.items()}
        if (
            str(cleaned_row.get("ID Telegram", "")).strip() == str(chat_id)
            and str(cleaned_row.get("ID Informe", "")).strip() == str(id_informe)
        ):
            sheet.update_cell(i, 4, "Enviado")  # Столбец Estado (4) ← обновляем статус
            #print(f"✅ Статус обновлён для ID {chat_id} / Informe {id_informe}")
            return True

    #print(f"⚠️ Не найдена строка для обновления: {chat_id}, {id_informe}")
    return False