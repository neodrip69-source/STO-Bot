import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import gspread
from google.oauth2.service_account import Credentials
import json
import os
import re
from datetime import datetime
import requests
import speech_recognition as sr
import pandas as pd
from io import BytesIO
from flask import Flask
from threading import Thread


# ---------- КОНФИГУРАЦИЯ ----------
BOT_TOKEN = os.environ.get('BOT_TOKEN')
GOOGLE_SHEET_ID = os.environ.get('GOOGLE_SHEET_ID')
GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS_JSON')


bot = telebot.TeleBot(BOT_TOKEN)
recognizer = sr.Recognizer()


# ---------- ПОДКЛЮЧЕНИЕ К GOOGLE SHEETS ----------
def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    client = gspread.authorize(creds)
    return client.open_by_key(GOOGLE_SHEET_ID)


# ---------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------
def get_user(chat_id):
    """Возвращает (role, post) или (None, None)"""
    try:
        sheet = get_sheet()
        ws = sheet.worksheet("users")
        records = ws.get_all_records()
        for row in records:
            if str(row['telegram_id']) == str(chat_id):
                return row['role'], row.get('post', None)
        return None, None
    except Exception as e:
        print(f"get_user error: {e}")
        return None, None


def add_request(logist_id, car_number, defect_text, voice_text=None, photo_ids=None):
    sheet = get_sheet()
    ws = sheet.worksheet("requests")
    all_ids = ws.col_values(1)[1:]
    next_id = max([int(x) for x in all_ids if x.isdigit()] or [0]) + 1
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    row = [
        next_id, now, logist_id, car_number, defect_text,
        'new', '', '', '', '', '', '', '', photo_ids or '', voice_text or ''
    ]
    ws.append_row(row)
    return next_id


def get_requests_by_user(chat_id, role, post=None):
    sheet = get_sheet()
    ws = sheet.worksheet("requests")
    records = ws.get_all_records()
    result = []
    for r in records:
        if role == 'logist' and str(r['logist_id']) == str(chat_id):
            result.append(r)
        elif role == 'repairman' and post is not None:
            if str(r['diag_post']) == str(post) or str(r['repair_post']) == str(post):
                result.append(r)
        elif role in ['mechanic', 'storekeeper', 'supplier']:
            result.append(r)
    return result


def update_request_field(request_id, field, value):
    sheet = get_sheet()
    ws = sheet.worksheet("requests")
    cell = ws.find(str(request_id), in_column=1)
    if cell:
        headers = ws.row_values(1)
        col_idx = headers.index(field) + 1
        ws.update_cell(cell.row, col_idx, value)
        return True
    return False


def get_stock():
    sheet = get_sheet()
    ws = sheet.worksheet("stock")
    data = ws.get_all_records()
    return pd.DataFrame(data)


def update_stock_from_dataframe(df):
    sheet = get_sheet()
    ws = sheet.worksheet("stock")
    ws.clear()
    ws.append_row(['part_article', 'part_name', 'quantity'])
    for _, row in df.iterrows():
        ws.append_row([row['part_article'], row['part_name'], row['quantity']])


def notify_mechanics(text):
    sheet = get_sheet()
    ws = sheet.worksheet("users")
    records = ws.get_all_records()
    for row in records:
        if row['role'] == 'mechanic':
            try:
                bot.send_message(int(row['telegram_id']), text)
            except:
                pass


def notify_user(chat_id, text):
    try:
        bot.send_message(chat_id, text, parse_mode='Markdown')
    except:
        pass


# ---------- КОМАНДЫ И CALLBACK'И ----------
@bot.message_handler(commands=['start'])
def start(message):
    role, post = get_user(message.chat.id)
    if not role:
        bot.reply_to(message, "❌ Вы не зарегистрированы. Администратор должен внести ваш ID в таблицу `users`.")
        return
    markup = InlineKeyboardMarkup(row_width=2)
    if role == 'logist':
        markup.add(
            InlineKeyboardButton("📝 Новая заявка", callback_data="new_request"),
            InlineKeyboardButton("📋 Мои заявки", callback_data="my_requests")
        )
    elif role == 'repairman':
        markup.add(InlineKeyboardButton("🔧 Мои задания", callback_data="my_tasks"))
    elif role == 'mechanic':
        markup.add(
            InlineKeyboardButton("📋 Все заявки", callback_data="all_requests"),
            InlineKeyboardButton("📦 Остатки", callback_data="show_stock"),
            InlineKeyboardButton("⚙️ Назначить диагностику", callback_data="assign_diag_menu")
        )
    elif role in ['storekeeper', 'supplier']:
        markup.add(
            InlineKeyboardButton("📦 Остатки", callback_data="show_stock"),
            InlineKeyboardButton("📤 Обновить склад (Excel)", callback_data="update_stock_file")
        )
    bot.send_message(message.chat.id, f"🏠 Главное меню ({role})", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    role, post = get_user(call.message.chat.id)
    if not role:
        bot.answer_callback_query(call.id, "Ошибка авторизации")
        return


    if call.data == "new_request" and role == 'logist':
        msg = bot.send_message(call.message.chat.id, "Введите номер автомобиля (например, A123BB777):")
        bot.register_next_step_handler(msg, process_car_number)
    elif call.data == "my_requests" and role == 'logist':
        requests = get_requests_by_user(call.message.chat.id, role)
        if not requests:
            bot.send_message(call.message.chat.id, "У вас нет заявок.")
            return
        text = "📋 *Ваши заявки:*\n"
        for r in requests[-10:]:
            status = r['status']
            if status in ('repair_assigned', 'repair_done'):
                text += f"🔹 Заявка #{r['id']}: {r['car_number']} — {status}\n   Ремонт: {r['repair_date']} {r['repair_time']} пост {r['repair_post']}\n"
            else:
                text += f"🔸 Заявка #{r['id']}: {r['car_number']} — {status}\n"
        bot.send_message(call.message.chat.id, text, parse_mode='Markdown')
    elif call.data == "my_tasks" and role == 'repairman':
        requests = get_requests_by_user(call.message.chat.id, role, post)
        if not requests:
            bot.send_message(call.message.chat.id, "Нет заданий на вашем посту.")
            return
        text = f"🔧 *Задания для поста {post}:*\n"
        for r in requests:
            status = r['status']
            if status == 'diag_assigned':
                text += f"📌 Диагностика заявки #{r['id']} (авто {r['car_number']})\n"
            elif status == 'repair_assigned':
                text += f"🔧 Ремонт заявки #{r['id']} (авто {r['car_number']})\n"
        text += "\nДля отправки результата диагностики используйте /diag <id>"
        bot.send_message(call.message.chat.id, text, parse_mode='Markdown')
    elif call.data == "all_requests" and role == 'mechanic':
        requests = get_requests_by_user(call.message.chat.id, role)
        if not requests:
            bot.send_message(call.message.chat.id, "Нет заявок.")
            return
        text = "📋 *Все заявки:*\n"
        for r in requests[-20:]:
            text += f"#{r['id']} {r['car_number']} — {r['status']} (диагностика пост {r['diag_post'] or 'не назн.'})\n"
        bot.send_message(call.message.chat.id, text, parse_mode='Markdown')
    elif call.data == "show_stock":
        stock = get_stock()
        if stock.empty:
            bot.send_message(call.message.chat.id, "Склад пуст. Обновите через кладовщика.")
            return
        text = "📦 *Остатки (первые 10):*\n"
        for _, row in stock.head(10).iterrows():
            text += f"{row['part_name']}: {row['quantity']} шт.\n"
        bot.send_message(call.message.chat.id, text, parse_mode='Markdown')
    elif call.data == "assign_diag_menu":
        bot.send_message(call.message.chat.id, "Используйте команду /assign_diag <id_заявки> <пост> <дата время>")
    elif call.data == "update_stock_file" and role in ['storekeeper', 'supplier']:
        bot.send_message(call.message.chat.id, "📎 Отправьте Excel-файл (.xlsx) с колонками: part_article, part_name, quantity")
        bot.register_next_step_handler_by_chat_id(call.message.chat.id, process_stock_file)
    bot.answer_callback_query(call.id)


def process_car_number(message):
    car_number = message.text.strip().upper()
    msg = bot.send_message(message.chat.id, "Опишите проблему (текст или голосовое):")
    bot.register_next_step_handler(msg, lambda m: process_defect(m, car_number))


def process_defect(message, car_number):
    defect_text = message.text or ""
    request_id = add_request(message.chat.id, car_number, defect_text)
    bot.send_message(message.chat.id, f"✅ Заявка #{request_id} создана. Механик назначит диагностику.")
    notify_mechanics(f"🆕 Новая заявка #{request_id} от логиста. Авто {car_number}")


def process_stock_file(message):
    if not message.document:
        bot.reply_to(message, "❌ Отправьте файл .xlsx")
        return
    file_info = bot.get_file(message.document.file_id)
    downloaded = bot.download_file(file_info.file_path)
    try:
        df = pd.read_excel(BytesIO(downloaded))
        required_cols = ['part_article', 'part_name', 'quantity']
        if not all(col in df.columns for col in required_cols):
            bot.reply_to(message, "❌ Файл должен содержать колонки: part_article, part_name, quantity")
            return
        update_stock_from_dataframe(df)
        bot.reply_to(message, f"✅ Склад обновлён. Загружено {len(df)} позиций.")
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")


@bot.message_handler(commands=['assign_diag'])
def assign_diag(message):
    role, _ = get_user(message.chat.id)
    if role != 'mechanic':
        return
    parts = message.text.split()
    if len(parts) < 4:
        bot.reply_to(message, "Использование: /assign_diag <id> <пост> <дата время>")
        return
    request_id = int(parts[1])
    post = parts[2]
    datetime_str = ' '.join(parts[3:])
    update_request_field(request_id, 'diag_post', post)
    update_request_field(request_id, 'diag_date', datetime_str)
    update_request_field(request_id, 'status', 'diag_assigned')
    sheet = get_sheet()
    ws = sheet.worksheet("users")
    records = ws.get_all_records()
    repairman_id = None
    for row in records:
        if row['role'] == 'repairman' and str(row['post']) == str(post):
            repairman_id = row['telegram_id']
            break
    if repairman_id:
        notify_user(repairman_id, f"🔧 Вам назначена диагностика по заявке #{request_id}\nДата: {datetime_str}")
    bot.reply_to(message, f"✅ Диагностика назначена на пост {post}")


@bot.message_handler(commands=['diag'])
def send_diag(message):
    role, post = get_user(message.chat.id)
    if role != 'repairman':
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        bot.reply_to(message, "Формат: /diag 123 описание поломки и запчасти")
        return
    request_id = int(args[1])
    diag_text = args[2]
    update_request_field(request_id, 'diag_result', diag_text)
    update_request_field(request_id, 'status', 'diag_done')
    notify_mechanics(f"📄 Заявка #{request_id}: получен диагноз.\n{diag_text}")
    bot.reply_to(message, f"✅ Диагноз по заявке #{request_id} отправлен механику")


@bot.message_handler(commands=['assign_repair'])
def assign_repair(message):
    role, _ = get_user(message.chat.id)
    if role != 'mechanic':
        return
    parts = message.text.split(maxsplit=4)
    if len(parts) < 4:
        bot.reply_to(message, "Использование: /assign_repair <id> <пост> <дата> <время>")
        return
    request_id = int(parts[1])
    post = parts[2]
    date = parts[3]
    time = parts[4] if len(parts) > 4 else ""
    update_request_field(request_id, 'repair_post', post)
    update_request_field(request_id, 'repair_date', date)
    update_request_field(request_id, 'repair_time', time)
    update_request_field(request_id, 'status', 'repair_assigned')
    sheet = get_sheet()
    ws = sheet.worksheet("requests")
    rec = ws.find(str(request_id), in_column=1)
    if rec:
        row = ws.row_values(rec.row)
        headers = ws.row_values(1)
        logist_id = int(row[headers.index('logist_id')])
        car_number = row[headers.index('car_number')]
        notify_user(logist_id, f"🚗 Заявка #{request_id} (авто {car_number}) назначена на ремонт\n📅 {date} {time}\n📍 Пост {post}")
    sheet_users = get_sheet().worksheet("users")
    users = sheet_users.get_all_records()
    for u in users:
        if u['role'] == 'repairman' and str(u['post']) == str(post):
            notify_user(int(u['telegram_id']), f"🔧 Вам назначен ремонт по заявке #{request_id}\nДата: {date} {time}")
            break
    bot.reply_to(message, f"✅ Ремонт назначен")


@bot.message_handler(commands=['complete_repair'])
def complete_repair(message):
    role, post = get_user(message.chat.id)
    if role not in ['repairman', 'mechanic']:
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Использование: /complete_repair <id_заявки>")
        return
    request_id = int(parts[1])
    update_request_field(request_id, 'status', 'repair_done')
    sheet = get_sheet()
    ws = sheet.worksheet("requests")
    rec = ws.find(str(request_id), in_column=1)
    if rec:
        row = ws.row_values(rec.row)
        headers = ws.row_values(1)
        logist_id = int(row[headers.index('logist_id')])
        car_number = row[headers.index('car_number')]
        notify_user(logist_id, f"✅ Заявка #{request_id} (авто {car_number}) выполнена. Ремонт завершён.")
    bot.reply_to(message, f"✅ Заявка #{request_id} завершена")


@bot.message_handler(commands=['stock'])
def show_stock_command(message):
    stock = get_stock()
    if stock.empty:
        bot.reply_to(message, "Склад пуст")
        return
    text = "📦 Остатки:\n"
    for _, row in stock.head(20).iterrows():
        text += f"{row['part_name']}: {row['quantity']}\n"
    bot.reply_to(message, text)


# ---------- FLASK ДЛЯ ПРОБУЖДЕНИЯ (KEEP-ALIVE) ----------
health_app = Flask(__name__)


@health_app.route('/')
def health_check():
    return "OK", 200


def run_health_server():
    health_app.run(host='0.0.0.0', port=10000)


# ---------- ЗАПУСК ----------
if __name__ == '__main__':
    thread = Thread(target=run_health_server)
    thread.start()
    print("Бот запущен...")
    bot.infinity_polling()
