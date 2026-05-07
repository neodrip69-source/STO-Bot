"""
Интеграция автопарка в основной бот - новая заявка с выбором автомобиля
"""

# ===== В основном main.py добавить: =====

from cars_manager import CarFleetManager
from warehouse_manager_1c import OneC_WarehouseManager

# Инициализация менеджеров
def init_managers():
    sheet = get_sheet()
    return {
        'cars': CarFleetManager(sheet),
        'warehouse': OneC_WarehouseManager(),
    }

managers = init_managers()
car_fleet = managers['cars']
warehouse = managers['warehouse']

# ============================================
# КОМАНДЫ ЛОГИСТА - НОВАЯ ЗАЯВКА
# ============================================

@bot.callback_query_handler(func=lambda call: call.data == "new_request" and get_user(call.message.chat.id)[0] == 'logist')
def new_request_start(call):
    """Начало процесса создания заявки"""
    role, _ = get_user(call.message.chat.id)
    if role != 'logist':
        bot.answer_callback_query(call.id, "❌ Доступ запрещён", show_alert=True)
        return
    
    msg = bot.send_message(
        call.message.chat.id,
        "🚗 *Создание новой заявки на ремонт*\n\n"
        "Введите гос.номер автомобиля (например: АА001БВ77)\n"
        "или выберите из списка ниже:",
        parse_mode='Markdown'
    )
    
    # Показываем список последних 10 машин
    cars = car_fleet.get_all_cars()
    if cars:
        markup = InlineKeyboardMarkup(row_width=1)
        
        # Добавляем кнопки для быстрого выбора (последние 10)
        for car in cars[-10:]:
            markup.add(
                InlineKeyboardButton(
                    f"🚗 {car['license_plate']} ({car['brand']} {car.get('model', '')})",
                    callback_data=f"select_car_{car['license_plate']}"
                )
            )
        
        bot.send_message(
            call.message.chat.id,
            "📋 *Или выберите из списка:*",
            reply_markup=markup,
            parse_mode='Markdown'
        )
    
    # Регистрируем ввод номера вручную
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
        # Машина найдена
        select_car_by_plate(message.chat.id, car)
    else:
        # Машина не найдена - предлагаем добавить вручную
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("✅ Добавить вручную", callback_data=f"add_car_manual_{license_plate}"),
            InlineKeyboardButton("🔍 Поискать ещё раз", callback_data="new_request")
        )
        
        bot.send_message(
            message.chat.id,
            f"❌ Автомобиль `{license_plate}` не найден в базе\n\n"
            f"Вы можете добавить его вручную или попробовать ещё раз.",
            reply_markup=markup,
            parse_mode='Markdown'
        )


@bot.callback_query_handler(func=lambda call: call.data.startswith("select_car_"))
def select_car_callback(call):
    """Выбор автомобиля из списка"""
    license_plate = call.data.replace("select_car_", "")
    car = car_fleet.search_car_by_plate(license_plate)
    
    if car:
        select_car_by_plate(call.message.chat.id, car)
    else:
        bot.answer_callback_query(call.id, "❌ Автомобиль не найден", show_alert=True)
    
    bot.answer_callback_query(call.id)


def select_car_by_plate(chat_id, car: Dict):
    """Обработка выбранного автомобиля"""
    # Подтверждение выбора
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("✅ Это правильно", callback_data=f"confirm_car_{car['license_plate']}"),
        InlineKeyboardButton("❌ Выбрать другой", callback_data="new_request")
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
    """Подтверждение автомобиля и переход к описанию проблемы"""
    license_plate = call.data.replace("confirm_car_", "")
    car = car_fleet.search_car_by_plate(license_plate)
    
    if not car:
        bot.answer_callback_query(call.id, "❌ Автомобиль не найден", show_alert=True)
        return
    
    # Сохраняем выбранный автомобиль в кеше (временно)
    user_cars_cache[call.message.chat.id] = car
    
    msg = bot.send_message(
        call.message.chat.id,
        f"📝 *Описание проблемы*\n\n"
        f"Опишите проблему с автомобилем `{car['license_plate']}`:\n"
        f"(текст, голос или фото)",
        parse_mode='Markdown'
    )
    
    bot.register_next_step_handler(msg, process_defect_description)
    bot.answer_callback_query(call.id)


user_cars_cache = {}  # Временное хранилище выбранных машин


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
    
    # Обработка разных типов сообщений
    if message.content_type == 'text':
        defect_text = message.text
    
    elif message.content_type == 'voice':
        # Сохраняем голос
        voice_file_id = message.voice.file_id
        defect_text = "[Голосовое сообщение]"
    
    elif message.content_type == 'photo':
        # Сохраняем фото
        photo_ids = [message.photo[-1].file_id]
        defect_text = "[Фото проблемы]"
    
    else:
        bot.reply_to(message, "❌ Поддерживаются только текст, голос и фото")
        return
    
    # Создаём заявку
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
        
        # Очищаем кеш
        del user_cars_cache[chat_id]
        
        # Уведомляем логиста
        bot.send_message(
            chat_id,
            f"✅ *ЗАЯВКА СОЗДАНА*\n\n"
            f"Номер заявки: `#{request_id}`\n"
            f"Автомобиль: {car['brand']} {car.get('model', '')} (`{car['license_plate']}`)\n"
            f"Статус: *Новая*\n\n"
            f"Механик назначит диагностику.",
            parse_mode='Markdown'
        )
        
        # Уведомляем механиков
        notify_mechanics(
            f"🆕 *НОВАЯ ЗАЯВКА #{request_id}*\n\n"
            f"🚗 Автомобиль: {car['brand']} {car.get('model', '')} (`{car['license_plate']}`)\n"
            f"📝 Проблема: {defect_text[:100]}...\n"
            f"👤 От логиста: @{get_user_name(chat_id)}\n\n"
            f"Приступите к назначению диагностики.",
            parse_mode='Markdown'
        )
    
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка при создании заявки: {e}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("add_car_manual_"))
def add_car_manual_callback(call):
    """Добавление машины вручную"""
    license_plate = call.data.replace("add_car_manual_", "")
    
    msg = bot.send_message(
        call.message.chat.id,
        f"📝 Введите информацию об автомобиле `{license_plate}`:\n\n"
        f"Формат: *Марка Модель ТипЭнергоноситель*\n"
        f"Пример: Mercedes Axor большегрузный",
        parse_mode='Markdown'
    )
    
    bot.register_next_step_handler(
        msg,
        lambda m: process_manual_car_input(m, license_plate)
    )
    bot.answer_callback_query(call.id)


def process_manual_car_input(message, license_plate: str):
    """Обработка ручного ввода информации об авто"""
    parts = message.text.split()
    
    if len(parts) < 2:
        bot.reply_to(message, "❌ Введите минимум марку и модель")
        return
    
    brand = parts[0]
    model = parts[1]
    car_type = parts[2] if len(parts) > 2 else "неизвестный"
    
    # Добавляем в Google Sheets
    try:
        ws = get_sheet().worksheet("cars")
        ws.append_row([
            license_plate,
            brand,
            model,
            car_type,
            "",  # VIN
            datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ])
        
        car = {
            'license_plate': license_plate,
            'brand': brand,
            'model': model,
            'car_type': car_type
        }
        
        # Продолжаем с выбранной машиной
        select_car_by_plate(message.chat.id, car)
    
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")


# ============================================
# ОБНОВЛЕНИЕ БАЗЫ АВТОМОБИЛЕЙ
# ============================================

@bot.message_handler(commands=['update_cars'])
def update_cars_command(message):
    """Обновление базы автомобилей из Excel"""
    role, _ = get_user(message.chat.id)
    if role not in ['admin', 'logist']:
        bot.reply_to(message, "❌ Только администратор или логист")
        return
    
    msg = bot.send_message(
        message.chat.id,
        "📎 *Загрузка автопарка из Excel*\n\n"
        "Отправьте файл с автомобилями.\n\n"
        "📋 *Структура:*\n"
        "• Гос.номер (АА001БВ77)\n"
        "• Марка (Mercedes)\n"
        "• Модель (Axor)\n"
        "• Тип (большегрузный)\n"
        "• VIN (опционально)\n\n"
        "💡 *В 1С:*\n"
        "1. Справки → Автопарк или ТС\n"
        "2. Выгрузить Excel\n"
        "3. Отправить сюда",
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
                f"⚠️ Ошибок: `{result['cars_failed']}`\n"
                f"🕐 Время: `{result['timestamp']}`\n\n"
            )
            
            if result.get('sample_data'):
                text += "📌 Примеры:\n"
                for item in result['sample_data']:
                    text += f"  {item}\n"
            
            bot.send_message(message.chat.id, text, parse_mode='Markdown')
        
        else:
            bot.reply_to(
                message,
                f"❌ {result['error']}\n\n"
                f"Найдены колонки: {', '.join(result.get('available_columns', [])[:10])}",
                parse_mode='Markdown'
            )
    
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка: {e}")


# ============================================
# СПРАВОЧНИК АВТОПАРКА
# ============================================

@bot.message_handler(commands=['cars', 'автопарк'])
def show_cars_command(message):
    """Показать весь автопарк"""
    cars = car_fleet.get_all_cars()
    
    if not cars:
        bot.reply_to(message, "📦 Автопарк пуст. Обновите через /update_cars")
        return
    
    # Группируем по типам
    by_type = {}
    for car in cars:
        car_type = car.get('car_type', 'неизвестный')
        if car_type not in by_type:
            by_type[car_type] = []
        by_type[car_type].append(car)
    
    text = "🚗 *АВТОПАРК*\n\n"
    
    for car_type in CarFleetManager.CAR_TYPES:
        if car_type in by_type:
            text += f"*{car_type.upper()}*: {len(by_type[car_type])} шт\n"
            for car in by_type[car_type][:5]:
                text += f"  • `{car['license_plate']}` — {car['brand']} {car.get('model', '')}\n"
            if len(by_type[car_type]) > 5:
                text += f"  ... и ещё {len(by_type[car_type]) - 5}\n"
            text += "\n"
    
    text += f"\n📊 ИТОГО: {len(cars)} автомобилей"
    
    bot.send_message(message.chat.id, text, parse_mode='Markdown')


# ============================================
# ОБНОВЛЁННАЯ ФУНКЦИЯ add_request
# ============================================

def add_request(logist_id, car_plate, car_brand, car_model, car_type, 
                defect_text, voice_file_id=None, photo_ids=None):
    """Создаёт новую заявку с полной информацией об авто"""
    sheet = get_sheet()
    ws = sheet.worksheet("requests")
    
    # Получаем следующий ID
    all_ids = ws.col_values(1)[1:]
    next_id = max([int(x) for x in all_ids if x.isdigit()] or [0]) + 1
    
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    row = [
        next_id,
        now,
        logist_id,
        car_plate,      # гос.номер
        car_brand,      # марка
        car_model,      # модель
        car_type,       # тип (малотоннажный, большегрузный и т.д.)
        defect_text,
        'new',          # статус
        '',             # diag_post
        '',             # diag_date
        '',             # diag_repairman_id
        '',             # diag_result
        '',             # repair_post
        '',             # repair_date
        '',             # repair_time
        photo_ids or '',
        voice_file_id or ''
    ]
    
    ws.append_row(row)
    return next_id
