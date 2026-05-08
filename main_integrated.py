"""
STO-Bot - ГЛАВНЫЙ ФАЙЛ
Система управления ремонтом грузовиков через Telegram

Структура:
- Логистика: создание заявок на диагностику
- Диагностика: проведение диагностики, указание требуемых запчастей
- Снабжение: управление складом, проверка наличия
- Ремонт: выполнение ремонта, завершение работ

Зависимости:
    pip install pyTelegramBotAPI
    pip install gspread
    pip install google-auth-oauthlib
    pip install pandas
    pip install python-dotenv

Конфигурация (.env файл):
    BOT_TOKEN=ваш_токен_бота
    GOOGLE_SHEET_ID=ваш_id_таблицы
    GOOGLE_CREDENTIALS_JSON={"type": "service_account", ...}
"""

import os
import json
import logging
import time
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from io import BytesIO

# Telegram Bot
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Google Sheets
import gspread
from google.oauth2.service_account import Credentials

# Data processing
import pandas as pd

# Utilities
from dotenv import load_dotenv

# ============================================
# КОНФИГУРАЦИЯ И ЛОГИРОВАНИЕ
# ============================================

load_dotenv()

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Переменные окружения
BOT_TOKEN = os.environ.get('BOT_TOKEN')
GOOGLE_SHEET_ID = os.environ.get('GOOGLE_SHEET_ID')
GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS_JSON')

if not all([BOT_TOKEN, GOOGLE_SHEET_ID, GOOGLE_CREDENTIALS_JSON]):
    logger.error("❌ Не установлены необходимые переменные окружения")
    exit(1)

# Инициализация бота
bot = telebot.TeleBot(BOT_TOKEN)

# Кеш для временного хранения данных во время сессии
user_cars_cache = {}
user_requests_cache = {}

logger.info("✅ Бот инициализирован")

# ============================================
# GOOGLE SHEETS ИНТЕГРАЦИЯ
# ============================================

class GoogleSheetsManager:
    """Менеджер для работы с Google Sheets"""
    
    _sheet_cache = None
    _cache_time = 0
    _cache_ttl = 300  # 5 минут
    
    @classmethod
    def get_sheet(cls):
        """Получить объект Sheets с кешированием"""
        current_time = time.time()
        
        if cls._sheet_cache and (current_time - cls._cache_time) < cls._cache_ttl:
            return cls._sheet_cache
        
        try:
            creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
            scope = [
                'https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive'
            ]
            creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
            client = gspread.authorize(creds)
            cls._sheet_cache = client.open_by_key(GOOGLE_SHEET_ID)
            cls._cache_time = current_time
            return cls._sheet_cache
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к Google Sheets: {e}")
            return None


def get_sheet():
    """Вспомогательная функция"""
    return GoogleSheetsManager.get_sheet()


# ============================================
# CAR FLEET MANAGER (Менеджер автопарка)
# ============================================

class CarFleetManager:
    """Управление автопарком из Excel"""
    
    CAR_TYPES = [
        'малотоннажный',
        'среднетоннажный',
        'большегрузный',
        'неизвестный'
    ]
    
    def __init__(self, sheet=None):
        self.sheet = sheet
    
    def get_all_cars(self) -> List[Dict]:
        """Получить все автомобили"""
        try:
            ws = self.sheet.worksheet("cars")
            return ws.get_all_records()
        except Exception as e:
            logger.error(f"❌ Ошибка получения машин: {e}")
            return []
    
    def search_car_by_plate(self, license_plate: str) -> Optional[Dict]:
        """Найти машину по гос.номеру"""
        normalized = license_plate.strip().upper().replace(' ', '')
        cars = self.get_all_cars()
        
        for car in cars:
            if car.get('license_plate', '').strip().upper().replace(' ', '') == normalized:
                return car
        return None
    
    def get_cars_by_type(self, car_type: str) -> List[Dict]:
        """Получить машин�� по типу"""
        cars = self.get_all_cars()
        return [c for c in cars if c.get('car_type', '').lower() == car_type.lower()]
    
    def sync_cars_from_excel(self, file_bytes: bytes) -> Dict:
        """Синхронизировать автопарк из Excel"""
        try:
            df = pd.read_excel(BytesIO(file_bytes))
            
            if df.empty:
                return {'ok': False, 'error': '❌ Excel файл пуст'}
            
            df.columns = [str(col).strip() for col in df.columns]
            col_mapping = self._find_car_columns(df.columns.tolist())
            
            if 'license_plate' not in col_mapping or 'brand' not in col_mapping or 'model' not in col_mapping:
                return {
                    'ok': False,
                    'error': '❌ Не найдены обязательные колонки: Гос.номер, Марка, Модель',
                    'available_columns': df.columns.tolist()
                }
            
            rows_to_insert = []
            errors = []
            
            for idx, (_, row) in enumerate(df.iterrows(), 1):
                try:
                    license_plate = str(row[col_mapping['license_plate']]).strip().upper()
                    brand = str(row[col_mapping['brand']]).strip()
                    model = str(row[col_mapping['model']]).strip()
                    
                    if not license_plate or not brand or not model:
                        errors.append(f"Row {idx}: пустые данные")
                        continue
                    
                    car_type = 'неизвестный'
                    if 'car_type' in col_mapping:
                        car_type = str(row[col_mapping['car_type']]).strip()
                    
                    vin = ''
                    if 'vin' in col_mapping:
                        vin = str(row[col_mapping['vin']]).strip()
                    
                    rows_to_insert.append({
                        'license_plate': license_plate,
                        'brand': brand,
                        'model': model,
                        'car_type': car_type,
                        'vin': vin,
                        'added_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    })
                
                except Exception as e:
                    errors.append(f"Row {idx}: {str(e)}")
            
            if not rows_to_insert:
                return {'ok': False, 'error': '❌ Не удалось распарсить ни одной машины'}
            
            # Обновляем Google Sheets
            try:
                ws = self.sheet.worksheet("cars")
            except:
                ws = self.sheet.add_worksheet("cars", rows=1000, cols=6)
            
            ws.clear()
            ws.append_row(['license_plate', 'brand', 'model', 'car_type', 'vin', 'added_date'])
            
            for row in rows_to_insert:
                ws.append_row([
                    row['license_plate'],
                    row['brand'],
                    row['model'],
                    row['car_type'],
                    row['vin'],
                    row['added_date']
                ])
            
            return {
                'ok': True,
                'cars_loaded': len(rows_to_insert),
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'sample_data': [f"• {r['license_plate']} — {r['brand']} {r['model']}" for r in rows_to_insert[:3]]
            }
        
        except Exception as e:
            logger.error(f"❌ Ошибка синхронизации автопарка: {e}")
            return {'ok': False, 'error': f'❌ Ошибка: {str(e)}'}
    
    def _find_car_columns(self, df_columns: List[str]) -> Dict[str, str]:
        """Находит колонки для данных об автомобилях"""
        col_mapping = {}
        df_cols_lower = [c.lower() for c in df_columns]
        
        for alias in ['гос.номер', 'гос номер', 'номер', 'license_plate', 'plate']:
            for i, col in enumerate(df_cols_lower):
                if alias in col:
                    col_mapping['license_plate'] = df_columns[i]
                    break
            if 'license_plate' in col_mapping:
                break
        
        for alias in ['марка', 'brand', 'manufacturer']:
            for i, col in enumerate(df_cols_lower):
                if alias in col:
                    col_mapping['brand'] = df_columns[i]
                    break
            if 'brand' in col_mapping:
                break
        
        for alias in ['модель', 'model', 'name']:
            for i, col in enumerate(df_cols_lower):
                if alias in col:
                    col_mapping['model'] = df_columns[i]
                    break
            if 'model' in col_mapping:
                break
        
        for alias in ['тип', 'type', 'car_type']:
            for i, col in enumerate(df_cols_lower):
                if alias in col:
                    col_mapping['car_type'] = df_columns[i]
                    break
            if 'car_type' in col_mapping:
                break
        
        for alias in ['vin', 'вин']:
            for i, col in enumerate(df_cols_lower):
                if alias in col:
                    col_mapping['vin'] = df_columns[i]
                    break
            if 'vin' in col_mapping:
                break
        
        return col_mapping
    
    def format_car_info(self, car: Dict) -> str:
        """Форматирует информацию об автомобиле"""
        return (
            f"🚗 *ИНФОРМАЦИЯ О ТС*\n\n"
            f"📋 Гос.номер: `{car['license_plate']}`\n"
            f"🏢 Марка: *{car['brand']}*\n"
            f"📍 Модель: *{car.get('model', 'неизвестна')}*\n"
            f"📊 Тип: *{car.get('car_type', 'неизвестный')}*\n"
        )


# ============================================
# WAREHOUSE MANAGER (Менеджер склада)
# ============================================

class OneC_WarehouseManager:
    """Управление складом из Excel 1С"""
    
    def __init__(self, sheet=None):
        self.sheet = sheet
    
    def sync_from_excel(self, file_bytes: bytes) -> Dict:
        """Синхронизировать остатки из Excel"""
        try:
            df = pd.read_excel(BytesIO(file_bytes))
            
            if df.empty:
                return {'ok': False, 'error': '❌ Excel файл пуст'}
            
            df.columns = [str(col).strip() for col in df.columns]
            col_mapping = self._find_stock_columns(df.columns.tolist())
            
            if 'article' not in col_mapping or 'name' not in col_mapping or 'quantity' not in col_mapping:
                return {
                    'ok': False,
                    'error': '❌ Не найдены обязательные колонки: Артикул, Наименование, Кол-во',
                    'available_columns': df.columns.tolist()
                }
            
            rows_to_insert = []
            errors = []
            
            for idx, (_, row) in enumerate(df.iterrows(), 1):
                try:
                    article = str(row[col_mapping['article']]).strip().upper()
                    name = str(row[col_mapping['name']]).strip()
                    qty = int(float(str(row[col_mapping['quantity']]).replace(',', '.') or 0))
                    
                    if not article or not name:
                        errors.append(f"Row {idx}: пустые данные")
                        continue
                    
                    unit = 'шт'
                    if 'unit' in col_mapping:
                        unit = str(row[col_mapping['unit']]).strip()
                    
                    rows_to_insert.append({
                        'part_article': article,
                        'part_name': name,
                        'quantity': max(0, qty),
                        'unit': unit,
                        'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    })
                
                except Exception as e:
                    errors.append(f"Row {idx}: {str(e)}")
            
            if not rows_to_insert:
                return {'ok': False, 'error': '❌ Не удалось распарсить ни одной позиции'}
            
            # Обновляем Google Sheets
            try:
                ws = self.sheet.worksheet("stock")
            except:
                ws = self.sheet.add_worksheet("stock", rows=1000, cols=5)
            
            ws.clear()
            ws.append_row(['part_article', 'part_name', 'quantity', 'unit', 'last_updated'])
            
            for row in rows_to_insert:
                ws.append_row([
                    row['part_article'],
                    row['part_name'],
                    row['quantity'],
                    row['unit'],
                    row['last_updated']
                ])
            
            return {
                'ok': True,
                'rows_loaded': len(rows_to_insert),
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'sample_data': [f"• {r['part_article']}: {r['part_name']} ({r['quantity']} {r['unit']})" for r in rows_to_insert[:3]]
            }
        
        except Exception as e:
            logger.error(f"❌ Ошибка синхронизации склада: {e}")
            return {'ok': False, 'error': f'❌ Ошибка: {str(e)}'}
    
    def _find_stock_columns(self, df_columns: List[str]) -> Dict[str, str]:
        """Находит колонки для данных склада"""
        col_mapping = {}
        df_cols_lower = [c.lower() for c in df_columns]
        
        for alias in ['артикул', 'article', 'code']:
            for i, col in enumerate(df_cols_lower):
                if alias in col:
                    col_mapping['article'] = df_columns[i]
                    break
            if 'article' in col_mapping:
                break
        
        for alias in ['наименование', 'название', 'name', 'description']:
            for i, col in enumerate(df_cols_lower):
                if alias in col:
                    col_mapping['name'] = df_columns[i]
                    break
            if 'name' in col_mapping:
                break
        
        for alias in ['кол-во', 'количество', 'quantity', 'qty']:
            for i, col in enumerate(df_cols_lower):
                if alias in col:
                    col_mapping['quantity'] = df_columns[i]
                    break
            if 'quantity' in col_mapping:
                break
        
        for alias in ['ед.изм', 'ед.изм.', 'unit', 'uom']:
            for i, col in enumerate(df_cols_lower):
                if alias in col:
                    col_mapping['unit'] = df_columns[i]
                    break
            if 'unit' in col_mapping:
                break
        
        return col_mapping
    
    def check_part_availability(self, parts_needed: List[Dict]) -> Dict:
        """Проверить наличие запчастей"""
        try:
            ws = self.sheet.worksheet("stock")
            records = ws.get_all_records()
            stock = {r['part_article'].upper(): int(r.get('quantity', 0)) for r in records}
            
            result = {
                'parts': {},
                'overall_status': 'in_stock',
                'summary': {
                    'total_needed': 0,
                    'total_available': 0,
                    'total_shortage': 0
                }
            }
            
            for part in parts_needed:
                article = part['article'].upper()
                needed = part['qty']
                available = stock.get(article, 0)
                
                status = 'available' if available >= needed else 'partial' if available > 0 else 'unavailable'
                shortage = max(0, needed - available)
                
                result['parts'][article] = {
                    'needed': needed,
                    'available': available,
                    'shortage': shortage,
                    'status': status
                }
                
                result['summary']['total_needed'] += needed
                result['summary']['total_available'] += available
                result['summary']['total_shortage'] += shortage
                
                if status == 'unavailable' and result['overall_status'] != 'unavailable':
                    result['overall_status'] = 'unavailable'
                elif status == 'partial' and result['overall_status'] == 'in_stock':
                    result['overall_status'] = 'partial'
            
            return result
        
        except Exception as e:
            logger.error(f"❌ Ошибка проверки запчастей: {e}")
            return {'overall_status': 'error', 'error': str(e)}
    
    def format_availability_message(self, check_result: Dict) -> str:
        """Форматирует отчёт по наличию для Telegram"""
        if 'error' in check_result:
            return f"❌ Ошибка: {check_result['error']}"
        
        lines = []
        
        status_icon = {
            'in_stock': '✅',
            'partial': '⚠️',
            'unavailable': '❌'
        }
        
        overall = check_result['overall_status']
        lines.append(f"\n{status_icon[overall]} *СТАТУС ЗАПЧАСТЕЙ*\n")
        
        for article, info in check_result['parts'].items():
            icon_map = {'available': '✅', 'partial': '⚠️', 'unavailable': '❌'}
            icon = icon_map[info['status']]
            
            lines.append(
                f"{icon} `{article}`\n"
                f"   Нужно: {info['needed']} шт, Есть: {info['available']} шт"
            )
            
            if info['shortage'] > 0:
                lines.append(f"   ❌ Дефицит: {info['shortage']} шт")
            
            lines.append("")
        
        summary = check_result['summary']
        lines.append(f"📊 *ИТОГО:*")
        lines.append(f"   Требуется: {summary['total_needed']} шт")
        lines.append(f"   В наличии: {summary['total_available']} шт")
        
        if summary['total_shortage'] > 0:
            lines.append(f"   ❌ Дефицит: {summary['total_shortage']} шт")
        
        return "\n".join(lines)


# ============================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================

def get_user(chat_id: int) -> Tuple[Optional[str], Optional[str]]:
    """Получить роль и пост пользователя"""
    try:
        sheet = get_sheet()
        ws = sheet.worksheet("users")
        records = ws.get_all_records()
        
        for row in records:
            if str(row.get('telegram_id', '')) == str(chat_id):
                return row.get('role'), row.get('post')
        
        return None, None
    except Exception as e:
        logger.error(f"❌ Ошибка получения пользователя: {e}")
        return None, None


def add_request(logist_id, car_plate, car_brand, car_model, car_type,
                defect_text, voice_file_id=None, photo_ids=None) -> int:
    """Создаёт новую заявку"""
    sheet = get_sheet()
    ws = sheet.worksheet("requests")
    
    all_ids = ws.col_values(1)[1:]
    next_id = max([int(x) for x in all_ids if x.isdigit()] or [0]) + 1
    
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    row = [
        next_id,
        now,
        logist_id,
        car_plate,
        car_brand,
        car_model,
        car_type,
        defect_text,
        'new',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        photo_ids or '',
        voice_file_id or ''
    ]
    
    ws.append_row(row)
    return next_id


def notify_user(chat_id, text):
    """Отправляет сообщение пользователю"""
    try:
        bot.send_message(chat_id, text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"❌ Ошибка отправки сообщения: {e}")


def notify_mechanics(text):
    """Уведомляет всех механиков"""
    try:
        sheet = get_sheet()
        ws = sheet.worksheet("users")
        records = ws.get_all_records()
        
        for row in records:
            if row.get('role') == 'mechanic':
                try:
                    bot.send_message(int(row['telegram_id']), text, parse_mode='Markdown')
                except:
                    pass
    except Exception as e:
        logger.error(f"❌ Ошибка отправки механикам: {e}")


# ============================================
# ИНИЦИАЛИЗАЦИЯ МЕНЕДЖЕРОВ
# ============================================

sheet = get_sheet()
car_fleet = CarFleetManager(sheet)
warehouse = OneC_WarehouseManager(sheet)

logger.info("✅ Менеджеры инициализированы")

# ============================================
# КОМАНДЫ И ОБРАБОТЧИКИ
# ============================================

@bot.message_handler(commands=['start'])
def start(message):
    """Команда /start"""
    role, post = get_user(message.chat.id)
    
    if not role:
        bot.reply_to(
            message,
            "❌ Вы не зарегистрированы. Администратор должен внести ваш ID в таблицу `users`."
        )
        return
    
    markup = InlineKeyboardMarkup(row_width=2)
    
    if role == 'logist':
        markup.add(
            InlineKeyboardButton("📝 Новая заявка", callback_data="new_request"),
            InlineKeyboardButton("📋 Мои заявки", callback_data="my_requests")
        )
    elif role == 'service_manager':
        markup.add(
            InlineKeyboardButton("📋 Все заявки", callback_data="all_requests"),
            InlineKeyboardButton("⚙️ Назначить диагностику", callback_data="assign_diag_menu"),
            InlineKeyboardButton("🔧 Назначить ремонт", callback_data="assign_repair_menu")
        )
    elif role == 'supply_manager':
        markup.add(
            InlineKeyboardButton("📦 Остатки", callback_data="show_stock"),
            InlineKeyboardButton("📤 Обновить склад", callback_data="update_stock_file")
        )
    
    bot.send_message(
        message.chat.id,
        f"🏠 *Главное меню* ({role})",
        reply_markup=markup,
        parse_mode='Markdown'
    )


@bot.message_handler(commands=['update_cars'])
def update_cars_command(message):
    """Обновление базы автомобилей"""
    role, _ = get_user(message.chat.id)
    if role not in ['admin', 'logist']:
        bot.reply_to(message, "❌ Только администратор или логист")
        return
    
    msg = bot.send_message(
        message.chat.id,
        "📎 *Загрузка автопарка из Excel*\n\n"
        "Отправьте файл с автомобилями из 1С.",
        parse_mode='Markdown'
    )
    
    bot.register_next_step_handler(msg, process_cars_excel)


def process_cars_excel(message):
    """Обработка Excel с автомобилями"""
    if not message.document or not message.document.file_name.lower().endswith('.xlsx'):
        bot.reply_to(message, "❌ Отправьте файл .xlsx")
        return
    
    try:
        status_msg = bot.send_message(message.chat.id, "⏳ Обработка файла...")
        
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        
        result = car_fleet.sync_cars_from_excel(downloaded)
        
        bot.delete_message(message.chat.id, status_msg.message_id)
        
        if result['ok']:
            text = (
                f"✅ *АВТОПАРК ОБНОВЛЁН!*\n\n"
                f"🚗 Загружено машин: `{result['cars_loaded']}`\n"
                f"🕐 Время: `{result['timestamp']}`\n\n"
            )
            
            if result.get('sample_data'):
                text += "📌 Примеры:\n"
                for item in result['sample_data']:
                    text += f"  {item}\n"
            
            bot.send_message(message.chat.id, text, parse_mode='Markdown')
        else:
            bot.reply_to(message, f"❌ {result['error']}", parse_mode='Markdown')
    
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")


@bot.message_handler(commands=['update_warehouse', 'update_stock'])
def update_warehouse_command(message):
    """Обновление склада"""
    role, _ = get_user(message.chat.id)
    if role not in ['supply_manager', 'admin']:
        bot.reply_to(message, "❌ Только снабженец или администратор")
        return
    
    msg = bot.send_message(
        message.chat.id,
        "📎 *Загрузка из 1С*\n\n"
        "Отправьте Excel с остатками из 1С.",
        parse_mode='Markdown'
    )
    
    bot.register_next_step_handler(msg, process_stock_excel)


def process_stock_excel(message):
    """Обработка Excel со складом"""
    if not message.document or not message.document.file_name.lower().endswith('.xlsx'):
        bot.reply_to(message, "❌ Отправьте файл .xlsx")
        return
    
    try:
        status_msg = bot.send_message(message.chat.id, "⏳ Обработка файла...")
        
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        
        result = warehouse.sync_from_excel(downloaded)
        
        bot.delete_message(message.chat.id, status_msg.message_id)
        
        if result['ok']:
            text = (
                f"✅ *СКЛАД ОБНОВЛЁН!*\n\n"
                f"📊 Загружено позиций: `{result['rows_loaded']}`\n"
                f"🕐 Время: `{result['timestamp']}`\n\n"
            )
            
            if result.get('sample_data'):
                text += "📌 Примеры:\n"
                for item in result['sample_data']:
                    text += f"  {item}\n"
            
            bot.send_message(message.chat.id, text, parse_mode='Markdown')
        else:
            bot.reply_to(message, f"❌ {result['error']}", parse_mode='Markdown')
    
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")


@bot.message_handler(commands=['cars', 'автопарк'])
def show_cars_command(message):
    """Показать весь автопарк"""
    cars = car_fleet.get_all_cars()
    
    if not cars:
        bot.reply_to(message, "📦 Автопарк пуст. Обновите через /update_cars")
        return
    
    by_type = {}
    for car in cars:
        car_type = car.get('car_type', 'неизвестный')
        if car_type not in by_type:
            by_type[car_type] = []
        by_type[car_type].append(car)
    
    text = "🚗 *АВТОПАРК*\n\n"
    
    for car_type in ['большегрузный', 'среднетоннажный', 'малотоннажный', 'неизвестный']:
        if car_type in by_type:
            text += f"*{car_type.upper()}*: {len(by_type[car_type])} шт\n"
            for car in by_type[car_type][:5]:
                text += f"  • `{car['license_plate']}` — {car['brand']} {car.get('model', '')}\n"
            if len(by_type[car_type]) > 5:
                text += f"  ... и ещё {len(by_type[car_type]) - 5}\n"
            text += "\n"
    
    text += f"\n📊 ИТОГО: {len(cars)} автомобилей"
    
    bot.send_message(message.chat.id, text, parse_mode='Markdown')


@bot.callback_query_handler(func=lambda call: call.data == "new_request")
def new_request_start(call):
    """Начало создания заявки"""
    role, _ = get_user(call.message.chat.id)
    if role != 'logist':
        bot.answer_callback_query(call.id, "❌ Доступ запрещён", show_alert=True)
        return
    
    msg = bot.send_message(
        call.message.chat.id,
        "🚗 *Введите гос.номер автомобиля* (например: АА001БВ77)",
        parse_mode='Markdown'
    )
    
    bot.register_next_step_handler(msg, process_car_plate_input)
    bot.answer_callback_query(call.id)


def process_car_plate_input(message):
    """Обработка ввода гос.номера"""
    if not message.text:
        bot.reply_to(message, "❌ Введите корректный номер")
        return
    
    license_plate = message.text.strip().upper()
    car = car_fleet.search_car_by_plate(license_plate)
    
    if car:
        select_car_by_plate(message.chat.id, car)
    else:
        bot.send_message(
            message.chat.id,
            f"❌ Автомобиль `{license_plate}` не найден в базе",
            parse_mode='Markdown'
        )


def select_car_by_plate(chat_id, car: Dict):
    """Обработка выбранного автомобиля"""
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("✅ Правильно", callback_data=f"confirm_car_{car['license_plate']}"),
        InlineKeyboardButton("❌ Другой", callback_data="new_request")
    )
    
    info = car_fleet.format_car_info(car)
    
    bot.send_message(
        chat_id,
        f"{info}\n*Это правильный автомобиль?*",
        reply_markup=markup,
        parse_mode='Markdown'
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_car_"))
def confirm_car_callback(call):
    """Подтверждение автомобиля"""
    license_plate = call.data.replace("confirm_car_", "")
    car = car_fleet.search_car_by_plate(license_plate)
    
    if not car:
        bot.answer_callback_query(call.id, "❌ Автомобиль не найден", show_alert=True)
        return
    
    user_cars_cache[call.message.chat.id] = car
    
    msg = bot.send_message(
        call.message.chat.id,
        f"📝 *Описание проблемы*\n\n"
        f"Опишите проблему с автомобилем `{car['license_plate']}`\n"
        f"(текст, голос или фото)",
        parse_mode='Markdown'
    )
    
    bot.register_next_step_handler(msg, process_defect_description)
    bot.answer_callback_query(call.id)


def process_defect_description(message):
    """Обработка описания проблемы"""
    chat_id = message.chat.id
    
    if chat_id not in user_cars_cache:
        bot.reply_to(message, "❌ Ошибка: автомобиль не выбран")
        return
    
    car = user_cars_cache[chat_id]
    defect_text = ""
    photo_ids = []
    voice_file_id = None
    
    if message.content_type == 'text':
        defect_text = message.text
    elif message.content_type == 'voice':
        voice_file_id = message.voice.file_id
        defect_text = "[Голосовое сообщение]"
    elif message.content_type == 'photo':
        photo_ids = [message.photo[-1].file_id]
        defect_text = "[Фото проблемы]"
    else:
        bot.reply_to(message, "��� Поддерживаются только текст, голос и фото")
        return
    
    try:
        request_id = add_request(
            logist_id=chat_id,
            car_plate=car['license_plate'],
            car_brand=car['brand'],
            car_model=car.get('model', ''),
            car_type=car.get('car_type', ''),
            defect_text=defect_text,
            voice_file_id=voice_file_id,
            photo_ids=photo_ids
        )
        
        del user_cars_cache[chat_id]
        
        bot.send_message(
            chat_id,
            f"✅ *ЗАЯВКА СОЗДАНА*\n\n"
            f"Номер заявки: `#{request_id}`\n"
            f"Автомобиль: {car['brand']} {car.get('model', '')} (`{car['license_plate']}`)\n"
            f"Статус: *Новая*\n\n"
            f"Механик назначит диагностику.",
            parse_mode='Markdown'
        )
        
        notify_mechanics(
            f"🆕 *НОВАЯ ЗАЯВКА #{request_id}*\n\n"
            f"🚗 Автомобиль: {car['brand']} {car.get('model', '')} (`{car['license_plate']}`)\n"
            f"📝 Проблема: {defect_text[:100]}\n\n"
            f"Приступите к назначению диагностики.",
            parse_mode='Markdown'
        )
    
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка при создании заявки: {e}")


@bot.callback_query_handler(func=lambda call: call.data == "show_stock")
def show_stock_callback(call):
    """Показать остатки склада"""
    try:
        ws = get_sheet().worksheet("stock")
        records = ws.get_all_records()
        
        if not records:
            bot.send_message(call.message.chat.id, "📦 Склад пуст. Загрузите Excel через /update_warehouse")
            return
        
        text = "📦 *ОСТАТКИ НА СКЛАДЕ (первые 20):*\n\n"
        for i, row in enumerate(records[:20], 1):
            qty = int(row.get('quantity', 0))
            emoji = "✅" if qty > 5 else "⚠️" if qty > 0 else "❌"
            text += f"{i}. {emoji} *{row['part_name']}*\n   `{row['part_article']}`: *{qty} {row.get('unit', 'шт')}*\n\n"
        
        if len(records) > 20:
            text += f"... и ещё {len(records) - 20} позиций"
        
        bot.send_message(call.message.chat.id, text, parse_mode='Markdown')
    
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Ошибка: {e}")
    
    bot.answer_callback_query(call.id)


# ============================================
# ЗАПУСК БОТА
# ============================================

if __name__ == '__main__':
    logger.info("🚀 Бот запускается...")
    logger.info("Ожидание сообщений...")
    
    try:
        bot.infinity_polling()
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        exit(1)
