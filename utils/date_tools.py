import calendar
from datetime import date, timedelta

def is_two_days_before_last_working_day(today: date) -> bool:
    year = today.year
    month = today.month

    #временно для проверки
    #return True  # всегда возвращает истину — для проверки

    
    # Найдём последний день месяца
    last_day = calendar.monthrange(year, month)[1]
    last_date = date(year, month, last_day)

    # Назад — пока не рабочий день (будни: 0-4)
    while last_date.weekday() >= 5:
        last_date -= timedelta(days=1)

    return today == last_date - timedelta(days=2)