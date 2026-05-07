"""
Менеджер автопарка - управление базой автомобилей из Excel
"""

import pandas as pd
from io import BytesIO
from datetime import datetime
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class CarFleetManager:
    """
    Управление автопарком из Excel
    Структура: Гос.номер, Марка, Модель, Тип, VIN
    """
    
    CAR_TYPES = [
        'малотоннажный',
        'среднетоннажный', 
        'большегрузный',
        'неизвестный'
    ]
    
    BRANDS = ['Mercedes', 'DAF', 'Renault', 'Volvo', 'Man', 'Iveco', 'Scania', 'Astros', 'Axor']
    
    def __init__(self, sheet=None):
        self.sheet = sheet
    
    def set_sheet(self, sheet):
        """Установить sheet"""
        self.sheet = sheet
    
    def get_all_cars(self) -> List[Dict]:
        """Получить все автомобили"""
        try:
            ws = self.sheet.worksheet("cars")
            return ws.get_all_records()
        except Exception as e:
            logger.error(f"Error getting cars: {e}")
            return []
    
    def search_car_by_plate(self, license_plate: str) -> Optional[Dict]:
        """
        Найти машину по гос.номеру (быстрый поиск)
        Нормализует номер перед поиском
        """
        normalized = self._normalize_plate(license_plate)
        cars = self.get_all_cars()
        
        for car in cars:
            if self._normalize_plate(car.get('license_plate', '')) == normalized:
                return car
        
        return None
    
    def _normalize_plate(self, plate: str) -> str:
        """Нормализует гос.номер для поиска"""
        return plate.strip().upper().replace(' ', '')
    
    def get_cars_by_type(self, car_type: str) -> List[Dict]:
        """Получить машины по типу"""
        cars = self.get_all_cars()
        return [c for c in cars if c.get('car_type', '').lower() == car_type.lower()]
    
    def get_cars_by_brand(self, brand: str) -> List[Dict]:
        """Получить машины по марке"""
        cars = self.get_all_cars()
        return [c for c in cars if c.get('brand', '').lower() == brand.lower()]
    
    def sync_cars_from_excel(self, file_bytes: bytes) -> Dict:
        """
        Синхронизировать автопарк из Excel
        
        Ожидает колонки: Гос.номер, Марка, Модель, Тип (опционально), VIN (опционально)
        """
        errors = []
        
        try:
            df = pd.read_excel(BytesIO(file_bytes))
            
            if df.empty:
                return {'ok': False, 'error': '❌ Excel файл пуст'}
            
            df.columns = [str(col).strip() for col in df.columns]
            
            # Ищем нужные колонки
            col_mapping = self._find_car_columns(df.columns.tolist())
            
            if 'license_plate' not in col_mapping or 'brand' not in col_mapping or 'model' not in col_mapping:
                return {
                    'ok': False,
                    'error': '❌ Не найдены обязательные колонки: Гос.номер, Марка, Модель',
                    'found_columns': col_mapping,
                    'available_columns': df.columns.tolist()
                }
            
            rows_to_insert = []
            rows_errors = 0
            
            for idx, (_, row) in enumerate(df.iterrows(), 1):
                try:
                    license_plate = str(row[col_mapping['license_plate']]).strip().upper()
                    brand = str(row[col_mapping['brand']]).strip()
                    model = str(row[col_mapping['model']]).strip()
                    
                    car_type = 'неизвестный'
                    if 'car_type' in col_mapping:
                        car_type = str(row[col_mapping['car_type']]).strip()
                    
                    vin = ''
                    if 'vin' in col_mapping:
                        vin = str(row[col_mapping['vin']]).strip()
                    
                    # Валидация
                    if not license_plate or license_plate == 'NAN':
                        errors.append(f"⚠️ Row {idx}: пустой гос.номер")
                        rows_errors += 1
                        continue
                    
                    if not brand or brand.lower() == 'nan':
                        errors.append(f"⚠️ Row {idx}: пустая марка")
                        rows_errors += 1
                        continue
                    
                    if not model or model.lower() == 'nan':
                        errors.append(f"⚠️ Row {idx}: пустая модель")
                        rows_errors += 1
                        continue
                    
                    rows_to_insert.append({
                        'license_plate': license_plate,
                        'brand': brand,
                        'model': model,
                        'car_type': car_type,
                        'vin': vin,
                        'added_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    })
                
                except Exception as e:
                    errors.append(f"⚠️ Row {idx}: {str(e)}")
                    rows_errors += 1
            
            if not rows_to_insert:
                return {
                    'ok': False,
                    'error': '❌ Не удалось распарсить ни одной машины',
                    'rows_errors': rows_errors,
                    'errors': errors[:10]
                }
            
            # Обновляем Google Sheets
            try:
                ws = self.sheet.worksheet("cars")
            except:
                # Создаём лист если его нет
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
            
            # Логируем синхронизацию
            self._log_sync(len(rows_to_insert), len(file_bytes))
            
            return {
                'ok': True,
                'cars_loaded': len(rows_to_insert),
                'cars_failed': rows_errors,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'columns_found': col_mapping,
                'errors': errors if errors else None,
                'sample_data': [
                    f"• {row['license_plate']} — {row['brand']} {row['model']} ({row['car_type']})"
                    for row in rows_to_insert[:5]
                ]
            }
        
        except Exception as e:
            logger.exception(f"Excel sync error: {e}")
            return {
                'ok': False,
                'error': f'❌ Критическая ошибка: {str(e)}'
            }
    
    def _find_car_columns(self, df_columns: List[str]) -> Dict[str, str]:
        """Находит колонки для данных об автомобилях"""
        col_mapping = {}
        df_cols_lower = [c.lower() for c in df_columns]
        
        # Ищем гос.номер
        for alias in ['гос.номер', 'гос номер', 'номер', 'license_plate', 'plate', 'registration']:
            for i, col in enumerate(df_cols_lower):
                if alias in col:
                    col_mapping['license_plate'] = df_columns[i]
                    break
            if 'license_plate' in col_mapping:
                break
        
        # Ищем марку
        for alias in ['марка', 'brand', 'manufacturer', 'make']:
            for i, col in enumerate(df_cols_lower):
                if alias in col:
                    col_mapping['brand'] = df_columns[i]
                    break
            if 'brand' in col_mapping:
                break
        
        # Ищем модель
        for alias in ['модель', 'model', 'name']:
            for i, col in enumerate(df_cols_lower):
                if alias in col:
                    col_mapping['model'] = df_columns[i]
                    break
            if 'model' in col_mapping:
                break
        
        # Ищем тип
        for alias in ['тип', 'type', 'car_type', 'tonnage']:
            for i, col in enumerate(df_cols_lower):
                if alias in col:
                    col_mapping['car_type'] = df_columns[i]
                    break
            if 'car_type' in col_mapping:
                break
        
        # Ищем VIN
        for alias in ['vin', 'вин', 'chassis']:
            for i, col in enumerate(df_cols_lower):
                if alias in col:
                    col_mapping['vin'] = df_columns[i]
                    break
            if 'vin' in col_mapping:
                break
        
        return col_mapping
    
    def _log_sync(self, cars_count: int, file_size: int):
        """Логирует синхронизацию"""
        try:
            ws = self.sheet.worksheet("cars_sync_log")
        except:
            ws = self.sheet.add_worksheet("cars_sync_log", rows=1000, cols=5)
            ws.append_row(['Дата', 'Время', 'Машин загружено', 'Файл KB', 'Статус'])
        
        now = datetime.now()
        ws.append_row([
            now.strftime('%Y-%m-%d'),
            now.strftime('%H:%M:%S'),
            cars_count,
            f"{file_size / 1024:.1f}",
            '✅'
        ])
    
    def format_car_info(self, car: Dict) -> str:
        """Форматирует информацию об автомобиле"""
        return (
            f"🚗 *ИНФОРМАЦИЯ О ТРАНСПОРТНОМ СРЕДСТВЕ*\n\n"
            f"📋 Гос.номер: `{car['license_plate']}`\n"
            f"🏢 Марка: *{car['brand']}*\n"
            f"📍 Модель: *{car.get('model', 'неизвестна')}*\n"
            f"📊 Тип: *{car.get('car_type', 'неизвестный')}*\n"
        )
    
    def format_fleet_stats(self) -> str:
        """Статистика по автопарку"""
        cars = self.get_all_cars()
        
        if not cars:
            return "📦 Автопарк пуст"
        
        by_type = {}
        by_brand = {}
        
        for car in cars:
            car_type = car.get('car_type', 'неизвестный')
            brand = car.get('brand', 'неизвестная')
            
            by_type[car_type] = by_type.get(car_type, 0) + 1
            by_brand[brand] = by_brand.get(brand, 0) + 1
        
        text = f"📊 *СТАТИСТИКА АВТОПАРКА*\n\n"
        text += f"🚗 Всего машин: *{len(cars)}*\n\n"
        
        text += "*По типам:*\n"
        for car_type in self.CAR_TYPES:
            if car_type in by_type:
                text += f"  • {car_type}: {by_type[car_type]} шт\n"
        
        text += "\n*По маркам:*\n"
        for brand in sorted(by_brand.keys()):
            text += f"  • {brand}: {by_brand[brand]} шт\n"
        
        return text


def get_car_fleet_manager(sheet):
    """Фабрика для создания менеджера"""
    manager = CarFleetManager(sheet)
    return manager
