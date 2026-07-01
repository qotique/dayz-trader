# TraderX Config Generator

Генератор конфигурационных файлов для мода **TraderX** в DayZ.

## Возможности

- **Google Sheets** — читает таблицу напрямую
- **Локальные файлы** — читает **CSV**, **JSON** или **Excel** (экспорт из Google Sheets)
- **ZIP-упаковка** — готовый архив для установки на сервер
- Никакого программирования — всё через одну команду

## Быстрый старт

### 1. Установка

```bash
pip install -r requirements.txt
```

Или через `pip` напрямую:

```bash
pip install gspread oauth2client pydantic python-dotenv transliterate click openpyxl
```

### 2. Генерация

#### Вариант A: Из Google Sheets

```bash
# ID таблицы берётся из ссылки:
# https://docs.google.com/spreadsheets/d/<ВОТ_ЭТОТ_ID>/edit
python trader.py google --sheet-id "1yC8sdoBM_bpFciLyPNAWtvXBQvO604-3WlUJ_y123Xw"
```

Укажите путь к `credentials.json`, если он не в текущей папке:
```bash
python trader.py google --sheet-id "..." --credentials "путь/к/credentials.json"
```

#### Вариант B: Из локальных файлов (проще всего)

1. В Google Sheets откройте **Файл → Скачать → CSV** (каждый лист отдельно)
2. Положите все CSV-файлы в одну папку, названия не меняйте
3. Запустите:

```bash
python trader.py local /путь/к/папке/с/csv
```

Или скачайте как **Excel** (один файл):

```bash
python trader.py local таблица.xlsx
```

### 3. Результат

Файлы создаются в папке `output/profiles/TraderX/`.

Чтобы сразу получить ZIP-архив для установки на сервер:

```bash
python trader.py local таблица.xlsx --zip traderx_config.zip
```

## Все команды

| Команда | Описание |
|---|---|
| `trader google --sheet-id ID` | Генерация из Google Sheets |
| `trader local ПАПКА_ИЛИ_ФАЙЛ` | Генерация из CSV/JSON/Excel |
| `trader pack ПАПКА АРХИВ.ZIP` | Упаковать готовые файлы в ZIP |
| `trader init-config` | Создать config.toml |

## Config.toml

Можно настроить параметры в файле `config.toml` (создаётся командой `trader init-config`):

```toml
mode = "google"

[google]
spreadsheet_id = "1yC8sdoBM_bpFciLyPNAWtvXBQvO604-3WlUJ_y123Xw"
credentials_file = "credentials.json"

output_dir = "output/profiles/TraderX"
```

## Что внутри

- `models/` — Pydantic-модели для валидации данных
- `trader_concept.py` — основной движок генерации
- `cli.py` — интерфейс командной строки
- `tests/` — 47 тестов

## Требования

- Python 3.10+
- Установленные пакеты (см. requirements.txt)

## Структура выходных файлов

```
output/profiles/TraderX/
  TraderXConfig/
    TraderXGeneralSettings.json   # общие настройки (версия, сервер, лицензии, торговцы)
    TraderXCurrencySettings.json  # настройки валют
    Categories/                   # категории товаров
      cat_<имя>_<торговец>_001.json
    Products/                     # товары
      prod_<класс>_<торговец>_001.json
  TraderXDatabase/
    Stock/                        # остатки на складе
      prod_<класс>_<торговец>_001.json
```
