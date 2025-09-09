import streamlit as st
import csv
import requests
import pandas as pd
from datetime import datetime, date, time
import uuid
import pytz
from io import StringIO, BytesIO
import base64


# =========================
# Helpers for CSV handling
# =========================
def _decode_uploaded_bytes(file_bytes):
    """Try utf-8-sig, then utf-8, then latin-1. Return (text, encoding)."""
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return file_bytes.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return file_bytes.decode("latin-1"), "latin-1"


def _normalize_fields(fields):
    """Strip BOM and whitespace from header names."""
    return [(f or "").strip().lstrip("\ufeff") for f in fields]


def _normalize_row(row):
    """Strip BOM and whitespace from DictReader row keys; ensure values are strings."""
    return {(k or "").strip().lstrip("\ufeff"): (v or "") for k, v in row.items()}


# =========================
# UI: Logo / Header
# =========================
logo_path = "logo.png"
try:
    with open(logo_path, "rb") as f:
        logo_base64 = base64.b64encode(f.read()).decode()
except Exception:
    logo_base64 = ""

st.set_page_config(page_title="Calendar Event Uploader", layout="wide")

st.markdown(f"""
    <style>
    #MainMenu {{visibility: hidden;}}
    header [data-testid="stToolbar"] {{display: none !important;}}
    .custom-header {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        background-color: white;
        border-bottom: 1px solid #ddd;
        padding: 8px 20px;
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        z-index: 1000;
    }}
    .custom-header img {{ height: 28px; }}
    .back-button {{
        background-color: black;
        color: white;
        border: none;
        font-size: 16px;
        padding: 6px 14px;
        border-radius: 6px;
        cursor: pointer;
    }}
    .back-button:hover {{ background-color: #333; }}
    </style>
    <div class="custom-header">
        <div>
            <img src="data:image/png;base64,{logo_base64}" alt="TARGControl Logo">
        </div>
    </div>
    <div style="margin-top: 60px;"></div>
""", unsafe_allow_html=True)

st.title("TargControl: Управление календарными событиями")

# =========================
# Config / API Endpoints
# =========================
DOMAIN = 'dev'

URL_CALENDAR_TYPES = f'https://{DOMAIN}.targcontrol.com/external/api/employee-schedules/calendar/types'
URL_EMPLOYEES = f'https://{DOMAIN}.targcontrol.com/external/api/employees/query'
URL_CREATE_SCHEDULE = f'https://{DOMAIN}.targcontrol.com/external/api/employee-schedules/calendar/create'
URL_LOCATIONS = f'https://{DOMAIN}.targcontrol.com/external/api/locations'
URL_CALENDAR_EVENTS = f'https://{DOMAIN}.targcontrol.com/external/api/employee-schedules/calendar/query'
URL_DELETE_EVENT = f'https://{DOMAIN}.targcontrol.com/external/api/employee-schedules/calendar/delete/{{calendarEventId}}'

# =========================
# Instructions
# =========================
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
    | Фамилия   | Имя       | Отчество       | Тип               | Дата1     | Дата2     |
    |-----------|-----------|----------------|-------------------|-----------|-----------|
    | Иванов    | Александр | Константинович | Отпуск            | 14/08/25  | 30/08/25  |
    | Петрова   | Виктория  |                | Отпуск            | 30/06/25  | 13/07/25  |
    | Сидорова  |           |                | Отпуск            | 01/07/25  | 14/07/25  |
    | Погребович| Екатерина | Александровна  | Отпуск            | 02/06/25  | 16/06/25  |

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


# =========================
# API helpers
# =========================
def get_headers(api_key):
    return {
        'accept': 'application/json',
        'X-API-Key': api_key,
        'Content-Type': 'application/json',
    }


def load_calendar_types(api_key):
    try:
        r = requests.get(URL_CALENDAR_TYPES, headers=get_headers(api_key))
        if r.status_code == 200:
            types = r.json()
            return {item['name']: item['id'] for item in types}
        else:
            st.error(f"Ошибка загрузки типов событий: {r.status_code} — {r.text}")
            return {}
    except Exception as e:
        st.error(f"Не удалось загрузить типы событий: {e}")
        return {}


def get_locations(api_key):
    try:
        r = requests.get(URL_LOCATIONS, headers=get_headers(api_key))
        if r.status_code == 200:
            locations = r.json().get('data', [])
            return {loc['name']: loc['id'] for loc in locations}
        else:
            st.error(f"Ошибка загрузки локаций: {r.status_code} — {r.text}")
            return {}
    except Exception as e:
        st.error(f"Не удалось загрузить локации: {e}")
        return {}


def get_employees_by_location(api_key, location_id):
    try:
        r = requests.get(URL_EMPLOYEES, headers=get_headers(api_key))
        if r.status_code == 200:
            employees = r.json()
            filtered = [emp['id'] for emp in employees if location_id in emp.get('locationIds', [])]
            st.info(f"Найдено {len(filtered)} сотрудников в выбранной локации")
            return filtered
        else:
            st.error(f"Ошибка при получении сотрудников: {r.status_code} — {r.text}")
            return []
    except Exception as e:
        st.error(f"Не удалось получить сотрудников: {e}")
        return []


def get_calendar_events(api_key, employee_ids, start, end):
    if not employee_ids:
        st.info("Нет сотрудников для получения календарных событий")
        return []
    payload = {"range": {"since": start, "upTo": end}, "employeeIds": employee_ids}
    try:
        r = requests.post(URL_CALENDAR_EVENTS, headers=get_headers(api_key), json=payload)
        if r.status_code == 200:
            events = r.json()
            st.info(f"Получено {len(events)} календарных событий")
            return events
        else:
            st.error(f"Ошибка при получении календарных событий: {r.status_code} — {r.text}")
            return []
    except Exception as e:
        st.error(f"Не удалось получить календарные события: {e}")
        return []


def delete_calendar_event(api_key, event_id):
    url = URL_DELETE_EVENT.format(calendarEventId=event_id)
    try:
        r = requests.delete(url, headers=get_headers(api_key))
        if r.status_code in [200, 204]:
            return True, f"Успешно удалено календарное событие {event_id}"
        else:
            return False, f"Ошибка при удалении календарного события {event_id}: {r.status_code} — {r.text}"
    except Exception as e:
        return False, f"Не удалось удалить событие {event_id}: {e}"


def get_employees(api_key):
    try:
        r = requests.get(URL_EMPLOYEES, headers=get_headers(api_key))
        if r.status_code == 200:
            employees = r.json()
            employee_dict = {}
            for emp in employees:
                last_name = (emp['name'].get('lastName') or '').strip()
                first_name = (emp['name'].get('firstName') or '').strip()
                middle_name = (emp['name'].get('middleName') or '').strip()

                if not last_name:
                    st.warning(f"Пропущен сотрудник с ID {emp.get('id', 'неизвестно')}: отсутствует фамилия")
                    continue

                full_name = f"{last_name} {first_name} {middle_name}".strip()
                if not first_name and not middle_name:
                    full_name = last_name
                elif not middle_name:
                    full_name = f"{last_name} {first_name}"

                if middle_name:
                    employee_dict[f"{last_name} {first_name} {middle_name}"] = {'id': emp['id'], 'name': full_name}
                if first_name:
                    employee_dict[f"{last_name} {first_name}"] = {'id': emp['id'], 'name': full_name}
                if not first_name and not middle_name:
                    employee_dict[last_name] = {'id': emp['id'], 'name': full_name}
            return employee_dict
        else:
            st.error(f"Ошибка загрузки сотрудников: {r.status_code} — {r.text}")
            return {}
    except Exception as e:
        st.error(f"Не удалось загрузить сотрудников: {e}")
        return {}


def _format_ddmmyy(d: date) -> str:
    """Convert date/datetime to 'DD/MM/YY' string."""
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime("%d/%m/%y")


def parse_date(date_str_or_obj, timezone, is_end_date=False):
    """
    Принимает 'DD/MM/YY', 'DD/MM/YYYY', 'YYYY-MM-DD' (строки) ИЛИ date/datetime.
    Возвращает UTC ISO 'YYYY-MM-DDTHH:MM:SS.sssZ'.
    """
    if date_str_or_obj is None or (isinstance(date_str_or_obj, str) and not date_str_or_obj.strip()):
        return None

    tz = pytz.timezone(timezone)

    # Если пришёл date/datetime — используем напрямую
    if isinstance(date_str_or_obj, (datetime, date)):
        dt = (datetime.combine(date_str_or_obj, time(23, 59, 59)) if isinstance(date_str_or_obj, date) and not isinstance(date_str_or_obj, datetime)
              else date_str_or_obj)
        if is_end_date:
            dt = dt.replace(hour=23, minute=59, second=59) if isinstance(dt, datetime) else dt
        else:
            if isinstance(dt, datetime):
                dt = dt.replace(hour=0, minute=0, second=0)
        dt_local = tz.localize(dt) if getattr(dt, "tzinfo", None) is None else dt.astimezone(tz)
        dt_utc = dt_local.astimezone(pytz.UTC)
        return dt_utc.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    # Иначе — это строка: поддерживаем DD/MM/YY, DD/MM/YYYY, а также YYYY-MM-DD (от редактора)
    s = str(date_str_or_obj).strip()
    formats = ["%d/%m/%y", "%d/%m/%Y", "%Y-%m-%d"]
    for fmt in formats:
        try:
            dt = datetime.strptime(s, fmt)
            if is_end_date:
                dt = dt.replace(hour=23, minute=59, second=59)
            else:
                dt = dt.replace(hour=0, minute=0, second=0)
            dt_local = tz.localize(dt)
            dt_utc = dt_local.astimezone(pytz.UTC)
            return dt_utc.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        except ValueError:
            continue

    st.warning(f"Неверный формат даты: '{date_str_or_obj}' (ожидался ДД/ММ/ГГ, ДД/ММ/ГГГГ или ГГГГ-ММ-ДД)")
    return None



def create_schedule(api_key, employee_id, employee_name, calendar_type_id, start_date, end_date):
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
        r = requests.post(URL_CREATE_SCHEDULE, headers=get_headers(api_key), json=data)
        if r.status_code in [200, 201]:
            return True, f"Событие создано для сотрудника: {employee_name}"
        else:
            if r.status_code == 400 and "Employee" in r.text and "is fired" in r.text:
                return False, f"⚠️ Пропущено: Сотрудник {employee_name} уволен"
            return False, f"Ошибка создания события для {employee_name}: {r.status_code} — {r.text}"
    except Exception as e:
        return False, f"Не удалось создать событие для {employee_name}: {e}"


# =========================
# Main App
# =========================
def main():
    st.write("Введите API-токен, выберите таймзону и выполните действия по созданию или удалению календарных событий.")

    api_key = st.text_input("Введите API-токен", type="password")
    if not api_key:
        st.warning("Пожалуйста, введите API-токен.")
        return

    timezone = st.selectbox(
        "Выберите таймзону",
        options=pytz.all_timezones,
        index=pytz.all_timezones.index("Europe/Moscow")
    )

    if st.button("Очистить кэш и обновить данные"):
        st.cache_data.clear()
        st.success("Кэш очищен. Попробуйте загрузить данные снова.")

    tab1, tab2 = st.tabs(["Создать события", "Удалить события"])

    # -------------------------
    # TAB 1: Create events
    # -------------------------
    with tab1:
        st.subheader("Создание календарных событий")

        # Справочники для обоих режимов
        calendar_types = load_calendar_types(api_key)
        if not calendar_types:
            st.error("Не удалось загрузить типы событий. Проверьте API-токен и подключение.")
            return

        employees = get_employees(api_key)
        if not employees:
            st.error("Не удалось загрузить сотрудников. Проверьте API-токен и подключение.")
            return

        source = st.radio("Источник данных", ["CSV-файл", "Форма (таблица)"], horizontal=True)

        # ===== Режим 1: CSV-файл (как было) =====
        if source == "CSV-файл":
            uploaded_file = st.file_uploader("Выберите CSV-файл", type="csv", key="create_uploader")

            if st.button("Загрузить и создать события"):
                if uploaded_file is None:
                    st.error("Пожалуйста, загрузите CSV-файл.")
                else:
                    try:
                        # Предпросмотр через pandas с попыткой определить кодировку/разделитель
                        required_columns = ['Фамилия', 'Тип', 'Дата1', 'Дата2']
                        file_bytes = uploaded_file.getvalue()

                        preview_df = None
                        for enc in ("utf-8-sig", "utf-8"):
                            for delim in (";", ","):
                                try:
                                    uploaded_like = BytesIO(file_bytes)
                                    df_try = pd.read_csv(uploaded_like, delimiter=delim, encoding=enc)
                                    df_try.columns = _normalize_fields(df_try.columns.tolist())
                                    if all(col in df_try.columns for col in required_columns):
                                        preview_df = df_try
                                        break
                                except Exception:
                                    pass
                            if preview_df is not None:
                                break

                        if preview_df is None:
                            st.error(
                                "Ошибка: CSV-файл не содержит всех обязательных столбцов: 'Фамилия', 'Тип', 'Дата1', 'Дата2'.")
                            return

                        st.write("Предпросмотр загруженного CSV:")
                        st.dataframe(preview_df)

                    except Exception as e:
                        st.error(
                            f"Ошибка чтения CSV-файла. Убедитесь, что файл использует ';' или ',' и содержит корректные данные. Детали: {e}")
                        return

                    # Основная обработка через csv.DictReader (как у тебя)
                    results = []
                    csv_str, used_enc = _decode_uploaded_bytes(file_bytes)
                    csv_text = StringIO(csv_str)

                    reader = csv.DictReader(csv_text, delimiter=';')
                    fieldnames_norm = _normalize_fields(reader.fieldnames or [])
                    if not all(col in fieldnames_norm for col in required_columns):
                        csv_text.seek(0)
                        reader = csv.DictReader(csv_text, delimiter=',')
                        fieldnames_norm = _normalize_fields(reader.fieldnames or [])
                    if not all(col in fieldnames_norm for col in required_columns):
                        st.error(
                            "Ошибка: CSV-файл не содержит всех обязательных столбцов: 'Фамилия', 'Тип', 'Дата1', 'Дата2'.")
                        return

                    for row in reader:
                        rown = _normalize_row(row)

                        surname = rown.get('Фамилия', '').strip()
                        name = rown.get('Имя', '').strip()
                        middle_name = rown.get('Отчество', '').strip()
                        event_type_name = rown.get('Тип', '').strip()

                        if not event_type_name:
                            results.append(f"⚠️ Пропущено: Нет типа события для {surname} {name} {middle_name}".strip())
                            continue

                        start_date = parse_date(rown.get('Дата1', ''), timezone, is_end_date=False)
                        end_date = parse_date(rown.get('Дата2', ''), timezone, is_end_date=True)
                        if not start_date or not end_date:
                            results.append(
                                f"⚠️ Пропущено: Неверные или отсутствующие даты для {surname} {name} {middle_name}".strip())
                            continue

                        if middle_name:
                            full_name = f"{surname} {name} {middle_name}".strip()
                        elif name:
                            full_name = f"{surname} {name}".strip()
                        else:
                            full_name = surname

                        employee_data = employees.get(full_name)
                        if not employee_data:
                            results.append(f"⚠️ Пропущено: Сотрудник не найден: {full_name}")
                            continue

                        employee_id = employee_data['id']
                        employee_name = employee_data['name']

                        event_type_id = calendar_types.get(event_type_name)
                        if not event_type_id:
                            results.append(f"⚠️ Пропущено: Тип события '{event_type_name}' не найден")
                            continue

                        success, message = create_schedule(api_key, employee_id, employee_name, event_type_id,
                                                           start_date, end_date)
                        results.append(message)

                    st.subheader("Результаты обработки")
                    for result in results:
                        if "Ошибка" in result or "⚠️" in result:
                            st.error(result)
                        else:
                            st.success(result)

                    total = len(preview_df)
                    created = sum(1 for r in results if "Событие создано" in r)
                    skipped = sum(1 for r in results if "⚠️" in r or "Ошибка" in r)
                    st.info(
                        f"✅ Обработка завершена: всего строк в файле — {total}, успешно создано — {created}, пропущено/с ошибкой — {skipped}.")

        # ===== Режим 2: Форма (таблица) =====
        else:
            st.markdown("Введите строки вручную. Минимально нужны: **Фамилия**, **Тип**, **Дата1**, **Дата2**.")
            # Пустой шаблон на 5 строк
            default_rows = 5
            df_init = pd.DataFrame({
                "Фамилия": ["" for _ in range(default_rows)],
                "Имя": ["" for _ in range(default_rows)],
                "Отчество": ["" for _ in range(default_rows)],
                "Тип": ["" for _ in range(default_rows)],
                "Дата1": [None for _ in range(default_rows)],
                "Дата2": [None for _ in range(default_rows)],
            })

            # Конфиг столбцов: Тип — выпадающий список из API; Даты — datepicker
            type_options = list(calendar_types.keys())

            edited_df = st.data_editor(
                df_init,
                num_rows="dynamic",
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Тип": st.column_config.SelectboxColumn(
                        "Тип",
                        help="Выберите тип события из справочника TargControl",
                        options=type_options,
                        required=False
                    ),
                    "Дата1": st.column_config.DateColumn(
                        "Дата1",
                        help="Дата начала (локальная)",
                        format="DD/MM/YY"
                    ),
                    "Дата2": st.column_config.DateColumn(
                        "Дата2",
                        help="Дата окончания (локальная)",
                        format="DD/MM/YY"
                    ),
                }
            )

            if st.button("Создать события из таблицы"):
                # Очистка пустых строк (где нет 'Фамилия' и нет 'Тип' и пустые даты)
                df = edited_df.copy()

                # Приводим названия столбцов (на всякий случай)
                df.columns = _normalize_fields(df.columns.tolist())

                required_columns = ['Фамилия', 'Тип', 'Дата1', 'Дата2']
                if not all(col in df.columns for col in required_columns):
                    st.error("В таблице должны быть столбцы: 'Фамилия', 'Тип', 'Дата1', 'Дата2'.")
                    return

                # Удаляем полностью пустые строки
                df = df[~(
                        df['Фамилия'].astype(str).str.strip().eq("") &
                        df['Тип'].astype(str).str.strip().eq("") &
                        df['Дата1'].isna() &
                        df['Дата2'].isna()
                )].reset_index(drop=True)

                if df.empty:
                    st.warning("Нет данных для создания событий.")
                    return

                results = []
                total = len(df)

                for idx, row in df.iterrows():
                    surname = str(row.get('Фамилия') or "").strip()
                    name = str(row.get('Имя') or "").strip()
                    middle_name = str(row.get('Отчество') or "").strip()
                    event_type_name = str(row.get('Тип') or "").strip()
                    d1 = row.get('Дата1')
                    d2 = row.get('Дата2')

                    # Валидация обязательных
                    if not surname:
                        results.append(f"⚠️ Пропущено: Не указана фамилия (строка {idx + 1})")
                        continue
                    if not event_type_name:
                        results.append(f"⚠️ Пропущено: Нет типа события для {surname} {name} {middle_name}".strip())
                        continue
                    if pd.isna(d1) or pd.isna(d2):
                        results.append(
                            f"⚠️ Пропущено: Неверные или отсутствующие даты для {surname} {name} {middle_name}".strip())
                        continue

                    # Преобразуем даты (приходят как date/datetime из редактора)
                    start_date = parse_date(d1, timezone, is_end_date=False)
                    end_date = parse_date(d2, timezone, is_end_date=True)
                    if not start_date or not end_date:
                        results.append(f"⚠️ Пропущено: Ошибка парсинга дат для {surname} {name} {middle_name}".strip())
                        continue

                    # Поиск сотрудника
                    if middle_name:
                        full_name = f"{surname} {name} {middle_name}".strip()
                    elif name:
                        full_name = f"{surname} {name}".strip()
                    else:
                        full_name = surname

                    employee_data = employees.get(full_name)
                    if not employee_data:
                        results.append(f"⚠️ Пропущено: Сотрудник не найден: {full_name}")
                        continue

                    employee_id = employee_data['id']
                    employee_name = employee_data['name']

                    # Тип события
                    event_type_id = calendar_types.get(event_type_name)
                    if not event_type_id:
                        results.append(f"⚠️ Пропущено: Тип события '{event_type_name}' не найден")
                        continue

                    success, message = create_schedule(api_key, employee_id, employee_name, event_type_id, start_date,
                                                       end_date)
                    results.append(message)

                # Вывод результатов
                st.subheader("Результаты обработки")
                for result in results:
                    if "Ошибка" in result or "⚠️" in result:
                        st.error(result)
                    else:
                        st.success(result)

                created = sum(1 for r in results if "Событие создано" in r)
                skipped = sum(1 for r in results if "⚠️" in r or "Ошибка" in r)
                st.info(
                    f"✅ Обработка завершена: всего строк — {total}, успешно создано — {created}, пропущено/с ошибкой — {skipped}.")

    # -------------------------
    # TAB 2: Delete events
    # -------------------------
    with tab2:
        st.subheader("Удаление календарных событий")

        locations = get_locations(api_key)
        if not locations:
            st.error("Не удалось загрузить локации. Проверьте API-токен и подключение.")
            return

        location_name = st.selectbox("Выберите локацию", options=list(locations.keys()))
        location_id = locations.get(location_name)

        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Дата начала", value=datetime(2025, 7, 1), key="start_date")
        with col2:
            end_date = st.date_input("Дата окончания", value=datetime(2025, 12, 31), key="end_date")

        if st.button("Удалить события"):
            if not location_id:
                st.error("Пожалуйста, выберите локацию.")
                return

            tz = pytz.timezone(timezone)
            start_datetime = datetime.combine(start_date, time(0, 0, 0))
            end_datetime = datetime.combine(end_date, time(23, 59, 59, 999999))
            start_date_utc = tz.localize(start_datetime).astimezone(pytz.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            end_date_utc = tz.localize(end_datetime).astimezone(pytz.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

            employee_ids = get_employees_by_location(api_key, location_id)
            if not employee_ids:
                st.error("Не удалось получить сотрудников для указанной локации.")
                return

            calendar_events = get_calendar_events(api_key, employee_ids, start_date_utc, end_date_utc)
            event_ids = [event['id'] for event in calendar_events]

            results = []
            st.info(f"Найдено {len(event_ids)} событий для удаления")
            for event_id in event_ids:
                success, message = delete_calendar_event(api_key, event_id)
                results.append(message)

            st.subheader("Результаты удаления")
            for result in results:
                if "Ошибка" in result or "⚠️" in result:
                    st.error(result)
                else:
                    st.success(result)


if __name__ == "__main__":
    main()
