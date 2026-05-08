"""
test_modules.py - Модульные unit-тесты для STO-Bot

Запуск:
    python -m unittest test_modules.py -v
    
    или
    
    python test_modules.py
"""

import unittest
from unittest.mock import Mock, patch
from datetime import datetime
from io import BytesIO
import pandas as pd


class TestCarFleetManager(unittest.TestCase):
    """Тесты менеджера автопарка"""
    
    def setUp(self):
        """Подготовка к каждому тесту"""
        from cars_manager import CarFleetManager
        
        # Mock Google Sheets
        self.mock_sheet = Mock()
        self.mock_ws = Mock()
        self.mock_sheet.worksheet.return_value = self.mock_ws
        
        # Тестовые данные
        self.test_cars = [
            {
                'license_plate': 'АА001БВ77',
                'brand': 'Mercedes',
                'model': 'Axor',
                'car_type': 'большегрузный',
                'vin': 'WDB123456'
            },
            {
                'license_plate': 'BB002ГД77',
                'brand': 'DAF',
                'model': 'XF',
                'car_type': 'большегрузный',
                'vin': 'VV7456789'
            },
            {
                'license_plate': 'CC003ЕЖ77',
                'brand': 'Sprinter',
                'model': '311',
                'car_type': 'малотоннажный',
                'vin': 'WDB789012'
            }
        ]
        
        self.mock_ws.get_all_records.return_value = self.test_cars
        self.car_fleet = CarFleetManager(self.mock_sheet)
    
    def test_get_all_cars(self):
        """Тест получения всех машин"""
        cars = self.car_fleet.get_all_cars()
        self.assertEqual(len(cars), 3)
        self.assertEqual(cars[0]['license_plate'], 'АА001БВ77')
    
    def test_search_car_exact_match(self):
        """Тест поиска по точному номеру"""
        car = self.car_fleet.search_car_by_plate('АА001БВ77')
        self.assertIsNotNone(car)
        self.assertEqual(car['brand'], 'Mercedes')
    
    def test_search_car_case_insensitive(self):
        """Тест поиска без учёта регистра"""
        car = self.car_fleet.search_car_by_plate('аа001бв77')
        self.assertIsNotNone(car)
        self.assertEqual(car['license_plate'], 'АА001БВ77')
    
    def test_search_car_with_spaces(self):
        """Тест поиска с пробелами"""
        car = self.car_fleet.search_car_by_plate('аа 001 бв 77')
        self.assertIsNotNone(car)
        self.assertEqual(car['brand'], 'Mercedes')
    
    def test_search_car_not_found(self):
        """Тест поиска несуществующей машины"""
        car = self.car_fleet.search_car_by_plate('ZZ999НН99')
        self.assertIsNone(car)
    
    def test_get_cars_by_type(self):
        """Тест поиска по типу"""
        large_cars = self.car_fleet.get_cars_by_type('большегрузный')
        self.assertEqual(len(large_cars), 2)
        for car in large_cars:
            self.assertEqual(car['car_type'], 'большегрузный')
    
    def test_get_cars_by_brand(self):
        """Тест поиска по марке"""
        mercedes_cars = self.car_fleet.get_cars_by_brand('Mercedes')
        self.assertEqual(len(mercedes_cars), 1)
        self.assertEqual(mercedes_cars[0]['license_plate'], 'АА001БВ77')
    
    def test_format_car_info(self):
        """Тест форматирования информации об авто"""
        car = self.test_cars[0]
        info = self.car_fleet.format_car_info(car)
        self.assertIn('АА001БВ77', info)
        self.assertIn('Mercedes', info)
        self.assertIn('большегрузный', info)
    
    def test_find_car_columns(self):
        """Тест парсинга колонок Excel"""
        columns = ['Гос.номер', 'Марка', 'Модель', 'Тип', 'VIN']
        result = self.car_fleet._find_car_columns(columns)
        
        self.assertIn('license_plate', result)
        self.assertIn('brand', result)
        self.assertIn('model', result)
        self.assertEqual(result['license_plate'], 'Гос.номер')


class TestWarehouseManager(unittest.TestCase):
    """Тесты менеджера склада"""
    
    def setUp(self):
        """Подготовка к каждому тесту"""
        from warehouse_manager_1c import OneC_WarehouseManager
        
        # Mock Google Sheets
        self.mock_sheet = Mock()
        self.mock_ws = Mock()
        self.mock_sheet.worksheet.return_value = self.mock_ws
        
        # Тестовые данные
        self.test_stock = [
            {
                'part_article': '00-0001647',
                'part_name': 'Датчик системы',
                'quantity': '15',
                'unit': 'шт'
            },
            {
                'part_article': '00-0005226',
                'part_name': 'Подшипник',
                'quantity': '3',
                'unit': 'шт'
            },
            {
                'part_article': '00-0005894',
                'part_name': 'Прокладка ГБЦ',
                'quantity': '0',
                'unit': 'шт'
            }
        ]
        
        self.mock_ws.get_all_records.return_value = self.test_stock
        self.warehouse = OneC_WarehouseManager()
        self.warehouse.sheet = self.mock_sheet
    
    def test_all_parts_available(self):
        """Тест: все запчасти в наличии"""
        parts = [
            {'article': '00-0001647', 'qty': 10},
            {'article': '00-0005226', 'qty': 2}
        ]
        result = self.warehouse.check_part_availability(parts)
        
        self.assertEqual(result['overall_status'], 'in_stock')
        self.assertEqual(result['summary']['total_shortage'], 0)
    
    def test_parts_deficiency(self):
        """Тест: дефицит запчастей"""
        parts = [
            {'article': '00-0001647', 'qty': 20},  # нужно 20, есть 15 = дефицит 5
            {'article': '00-0005226', 'qty': 5}    # нужно 5, есть 3 = дефицит 2
        ]
        result = self.warehouse.check_part_availability(parts)
        
        self.assertEqual(result['overall_status'], 'partial')
        self.assertEqual(result['summary']['total_shortage'], 7)
    
    def test_part_unavailable(self):
        """Тест: запчасть отсутствует"""
        parts = [
            {'article': '00-0005894', 'qty': 5}  # есть 0
        ]
        result = self.warehouse.check_part_availability(parts)
        
        self.assertEqual(result['overall_status'], 'unavailable')
        self.assertEqual(result['summary']['total_shortage'], 5)


class TestIntegration(unittest.TestCase):
    """Интеграционные тесты"""
    
    def test_full_workflow(self):
        """Тест полного рабочего процесса"""
        from cars_manager import CarFleetManager
        from warehouse_manager_1c import OneC_WarehouseManager
        
        # Подготавливаем mock для cars_manager
        mock_sheet_cars = Mock()
        mock_ws_cars = Mock()
        mock_sheet_cars.worksheet.return_value = mock_ws_cars
        
        test_cars = [
            {
                'license_plate': 'АА001БВ77',
                'brand': 'Mercedes',
                'model': 'Axor',
                'car_type': 'большегрузный'
            }
        ]
        mock_ws_cars.get_all_records.return_value = test_cars
        
        car_fleet = CarFleetManager(mock_sheet_cars)
        
        # Подготавливаем mock для warehouse_manager
        mock_sheet_warehouse = Mock()
        mock_ws_warehouse = Mock()
        mock_sheet_warehouse.worksheet.return_value = mock_ws_warehouse
        
        test_stock = [
            {
                'part_article': '00-0001647',
                'part_name': 'Датчик',
                'quantity': '15',
                'unit': 'шт'
            }
        ]
        mock_ws_warehouse.get_all_records.return_value = test_stock
        
        warehouse = OneC_WarehouseManager()
        warehouse.sheet = mock_sheet_warehouse
        
        # Тестируем workflow
        # 1. Логист выбирает машину
        car = car_fleet.search_car_by_plate('АА001БВ77')
        self.assertIsNotNone(car)
        self.assertEqual(car['brand'], 'Mercedes')
        
        # 2. Диагност указывает требуемые запчасти
        parts = [{'article': '00-0001647', 'qty': 2}]
        
        # 3. Система проверяет наличие
        result = warehouse.check_part_availability(parts)
        self.assertEqual(result['overall_status'], 'in_stock')


class TestErrorHandling(unittest.TestCase):
    """Тесты обработки ошибок"""
    
    def test_empty_car_database(self):
        """Тест: пустая база машин"""
        from cars_manager import CarFleetManager
        
        mock_sheet = Mock()
        mock_ws = Mock()
        mock_sheet.worksheet.return_value = mock_ws
        mock_ws.get_all_records.return_value = []
        
        car_fleet = CarFleetManager(mock_sheet)
        car = car_fleet.search_car_by_plate('АА001БВ77')
        
        self.assertIsNone(car)
    
    def test_empty_warehouse_database(self):
        """Тест: пустой склад"""
        from warehouse_manager_1c import OneC_WarehouseManager
        
        mock_sheet = Mock()
        mock_ws = Mock()
        mock_sheet.worksheet.return_value = mock_ws
        mock_ws.get_all_records.return_value = []
        
        warehouse = OneC_WarehouseManager()
        warehouse.sheet = mock_sheet
        
        result = warehouse.check_part_availability([{'article': '00-001', 'qty': 1}])
        
        # Все запчасти должны быть недоступны
        self.assertIn('00-001', result['parts'])
        self.assertEqual(result['parts']['00-001']['status'], 'unavailable')


class TestDataParsing(unittest.TestCase):
    """Тесты парсинга данных"""
    
    def test_parse_excel_with_different_columns(self):
        """Тест парсинга Excel с разными названиями колонок"""
        from cars_manager import CarFleetManager
        
        mock_sheet = Mock()
        car_fleet = CarFleetManager(mock_sheet)
        
        # Тест 1: Русские названия
        columns_ru = ['Гос.номер', 'Марка', 'Модель', 'Тип', 'VIN']
        result = car_fleet._find_car_columns(columns_ru)
        self.assertIn('license_plate', result)
        self.assertIn('brand', result)
        
        # Тест 2: Английские названия
        columns_en = ['license_plate', 'brand', 'model', 'type', 'vin']
        result = car_fleet._find_car_columns(columns_en)
        self.assertIn('license_plate', result)
        self.assertIn('brand', result)
        
        # Тест 3: Смешанные названия
        columns_mixed = ['Номер', 'Manufacturer', 'Model', 'car_type']
        result = car_fleet._find_car_columns(columns_mixed)
        self.assertIn('license_plate', result)
        self.assertIn('brand', result)


# ============================================
# ЗАПУСК ТЕСТОВ
# ============================================

def run_tests():
    """Функция для запуска всех тестов"""
    # Создаём набор тестов
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Добавляем все тесты
    suite.addTests(loader.loadTestsFromTestCase(TestCarFleetManager))
    suite.addTests(loader.loadTestsFromTestCase(TestWarehouseManager))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestErrorHandling))
    suite.addTests(loader.loadTestsFromTestCase(TestDataParsing))
    
    # Запускаем с подробным выводом
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Выводим итоги
    print("\n" + "=" * 70)
    print(f"Тестов запущено: {result.testsRun}")
    print(f"Успешно: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Ошибок: {len(result.failures)}")
    print(f"Критических ошибок: {len(result.errors)}")
    print("=" * 70 + "\n")
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    exit(0 if success else 1)
