import streamlit as st
import csv
import requests
import pandas as pd
from datetime import datetime
import uuid
import pytz
from io import StringIO

# Конфигурация
DOMAIN = 'cloud'

# URL-адреса API
URL_CALENDAR_TYPES = f'https://{DOMAIN}.targcontrol.com/external/api/employee-schedules/calendar/types'
URL_EMPLOYEES = f'https://{DOMAIN}.targcontrol.com/external/api/employees/query'
URL_CREATE_SCHEDULE = f'https://{DOMAIN}.targcontrol.com/external/api/employee-schedules/calendar/create'

# Streamlit app configuration
st.set_page_config(page_title="Calendar Event Uploader", layout="wide")
st.title("TargControl: Создание календарных событий")

# Instruction for CSV file
with st.expander("Инструкция по созданию CSV-файла", expanded=False):
    st.markdown("""
    ### Пример структуры CSV-файла
    Для корректной обработки файл должен быть в формате CSV с разделителем `;` и содержать следующие столбцы:
    - **Фамилия**: Фамилия сотрудника (обязательно, должно совпадать с данными в TargControl).
    - **Имя**: Имя сотрудника (необязательно, если отсутствует, используется только фамилия).
    - **Отчество**: Отчество сотрудника (необязательно, используется только при полном совпадении ФИО).
    - **Тип**: Тип календарного события (например, "Отпуск"). Должен точно совпадать с типом события в TargControl.
    - **Дата1**: Дата начала события в формате `DD/MM/YY` (например, `14/08/25`), интерпретируется как начало дня (00:00:00).
    - **Дата2**: Дата окончания события в формате `DD/MM/YY` (например, `30/08/25`).

    **Пример таблицы**:

    | Фамилия     | Имя         | Отчество         | Тип     | Дата1    | Дата2    |
    |-------------|-------------|------------------|---------|----------|----------|
    | Иванов      | Александр   | Константинович   | Отпуск  | 14/08/25 | 30/08/25 |
    | Петрова     | Виктория    |                  | Отпуск  | 30/06/25 | 13/07/25 |
    | Сидорова    |             |                  | Отпуск  | 01/07/25 | 14/07/25 |
    | Погребович  | Екатерина   | Александровна    | Отпуск  | 02/06/25 | 16/06/25 |

    **Убедитесь, что**:
    - Столбцы `Фамилия`, `Тип`, `Дата1`, `Дата2` присутствуют и заполнены.
    - Значения в столбце `Тип` точно совпадают с типами событий из TargControl.
    - Даты указаны в формате `DD/MM/YY`.
    - **Поиск сотрудников**:
      - Если указаны `Фамилия`, `Имя`, `Отчество`, ищется точное совпадение полного ФИО.
      - Если указаны `Фамилия` и `Имя`, ищется совпадение по фамилии и имени (без отчества).
      - Если указана только `Фамилия`, ищется сотрудник с этой фамилией без имени и отчества.
    - Данные сотрудников (ФИО) должны точно совпадать с данными в TargControl.
    """)

def get_headers(api_key):
    """Возвращает заголовки с указанным API-ключом"""
    return {
        'accept': 'application/json',
        'X-API-Key': api_key,
        'Content-Type': 'application/json',
    }

def load_calendar_types(api_key):
    """Загружает типы календарных событий"""
    try:
        response = requests.get(URL_CALENDAR_TYPES, headers=get_headers(api_key))
        if response.status_code == 200:
            types = response.json()
            return {item['name']: item['id'] for item in types}
        else:
            st.error(f"Ошибка загрузки типов событий: {response.status_code} — {response.text}")
            return {}
    except Exception as e:
        st.error(f"Не удалось загрузить типы событий: {e}")
        return {}

def get_employees(api_key):
    """Загружает список сотрудников"""
    try:
        response = requests.get(URL_EMPLOYEES, headers=get_headers(api_key))
        if response.status_code == 200:
            employees = response.json()
            employee_dict = {}
            for emp in employees:
                # Безопасно получаем lastName, firstName, middleName, заменяя None на пустую строку
                last_name = (emp['name'].get('lastName') or '').strip()
                first_name = (emp['name'].get('firstName') or '').strip()
                middle_name = (emp['name'].get('middleName') or '').strip()

                # Пропускаем сотрудников, у которых lastName пустое
                if not last_name:
                    st.warning(f"Пропущен сотрудник с ID {emp.get('id', 'неизвестно')}: отсутствует фамилия")
                    continue

                # Формируем ключи для поиска
                if middle_name:
                    # Полное ФИО: lastName firstName middleName
                    employee_dict[f"{last_name} {first_name} {middle_name}"] = emp['id']
                if first_name:
                    # Фамилия + Имя
                    employee_dict[f"{last_name} {first_name}"] = emp['id']
                if not first_name and not middle_name:
                    # Только фамилия
                    employee_dict[last_name] = emp['id']

            return employee_dict
        else:
            st.error(f"Ошибка загрузки сотрудников: {response.status_code} — {response.text}")
            return {}
    except Exception as e:
        st.error(f"Не удалось загрузить сотрудников: {e}")
        return {}

def parse_date(date_str, timezone, is_end_date=False):
    """Конвертирует строку даты в ISO-формат в UTC"""
    if not date_str.strip():
        return None
    try:
        dt = datetime.strptime(date_str, "%d/%m/%y")
        tz = pytz.timezone(timezone)
        if is_end_date:
            # Для конечной даты устанавливаем 23:59:59
            dt = dt.replace(hour=23, minute=59, second=59)
        dt_local = tz.localize(dt)
        dt_utc = dt_local.astimezone(pytz.UTC)
        return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError as e:
        st.warning(f"Неверный формат даты для '{date_str}': {e}")
        return None

def create_schedule(api_key, employee_id, calendar_type_id, start_date, end_date):
    """Создает календарное событие"""
    event_id = str(uuid.uuid4())
    data = {
        "id": event_id,
        "employeeId": employee_id,
        "typeId": calendar_type_id,
        "start": start_date,
        "end": end_date,
        "allDay": True,
        "confirmed": True,
        "comment": "Запланировано автоматически через Streamlit"
    }

    try:
        response = requests.post(URL_CREATE_SCHEDULE, headers=get_headers(api_key), json=data)
        if response.status_code in [200, 201]:
            return True, f"Событие создано для сотрудника ID: {employee_id}"
        else:
            return False, f"Ошибка создания события для {employee_id}: {response.status_code} — {response.text}"
    except Exception as e:
        return False, f"Не удалось создать событие для {employee_id}: {e}"

def main():
    st.write("Введите API-токен, выберите таймзону и загрузите CSV-файл для создания событий.")

    # Ввод API-токена
    api_key = st.text_input("Введите API-токен", type="password")
    if not api_key:
        st.warning("Пожалуйста, введите API-токен.")
        return

    # Выбор таймзоны
    timezone = st.selectbox(
        "Выберите таймзону",
        options=pytz.all_timezones,
        index=pytz.all_timezones.index("Europe/Moscow")  # По умолчанию Москва
    )

    # Кнопка для очистки кэша (для отладки)
    if st.button("Очистить кэш и обновить данные"):
        st.cache_data.clear()
        st.success("Кэш очищен. Попробуйте загрузить данные снова.")

    # Загрузка файла
    uploaded_file = st.file_uploader("Выберите CSV-файл", type="csv")

    # Кнопка для запуска обработки
    if st.button("Загрузить и создать события"):
        if uploaded_file is None:
            st.error("Пожалуйста, загрузите CSV-файл.")
            return

        # Показ предварительного просмотра CSV
        try:
            df = pd.read_csv(uploaded_file, delimiter=';', encoding='utf-8')
            st.write("Предпросмотр загруженного CSV:")
            st.dataframe(df)
        except Exception as e:
            st.error(f"Ошибка чтения CSV: {e}")
            return

        # Загрузка типов событий и сотрудников
        calendar_types = load_calendar_types(api_key)
        if not calendar_types:
            st.error("Не удалось загрузить типы событий. Проверьте API-токен и подключение.")
            return

        employees = get_employees(api_key)
        if not employees:
            st.error("Не удалось загрузить сотрудников. Проверьте API-токен и подключение.")
            return

        # Чтение CSV и создание событий
        results = []
        uploaded_file.seek(0)  # Сбросить указатель файла
        csv_text = StringIO(uploaded_file.getvalue().decode('utf-8'))
        reader = csv.DictReader(csv_text, delimiter=';')

        for row in reader:
            surname = row['Фамилия'].strip()
            name = row.get('Имя', '').strip()
            middle_name = row.get('Отчество', '').strip()
            event_type_name = row['Тип'].strip()

            # Пропуск строк без типа события
            if not event_type_name:
                results.append(f"⚠️ Пропущено: Нет типа события для {surname} {name} {middle_name}".strip())
                continue

            # Парсинг дат
            start_date = parse_date(row['Дата1'], timezone, is_end_date=False)
            end_date = parse_date(row['Дата2'], timezone, is_end_date=True)
            if not start_date or not end_date:
                results.append(f"⚠️ Пропущено: Неверные или отсутствующие даты для {surname} {name} {middle_name}".strip())
                continue

            # Формируем ключ для поиска сотрудника
            if middle_name:
                full_name = f"{surname} {name} {middle_name}"
            elif name:
                full_name = f"{surname} {name}"
            else:
                full_name = surname

            # Поиск ID сотрудника
            employee_id = employees.get(full_name)
            if not employee_id:
                results.append(f"⚠️ Пропущено: Сотрудник не найден: {full_name}")
                continue

            # Поиск ID типа события
            event_type_id = calendar_types.get(event_type_name)
            if not event_type_id:
                results.append(f"⚠️ Пропущено: Тип события '{event_type_name}' не найден")
                continue

            # Создание события
            success, message = create_schedule(api_key, employee_id, event_type_id, start_date, end_date)
            results.append(message)

        # Вывод результатов
        st.subheader("Результаты обработки")
        for result in results:
            if "Ошибка" in result or "⚠️" in result:
                st.error(result)
            else:
                st.success(result)

if __name__ == "__main__":
    main()