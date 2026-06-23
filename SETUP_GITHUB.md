# Деплой на GitHub Pages — пошаговая инструкция

## Что получится

- Публичная веб-страница `https://ВАШ_НИК.github.io/auksion_bot/`
- Три вкладки: Недвижимость, Авто, Банкротство
- Вкладка Дашборд с графиками по дням и месяцам
- Автообновление каждый день в 09:00 (Ташкент) через GitHub Actions

---

## Шаг 1 — Создать репозиторий

1. Открыть [github.com/new](https://github.com/new)
2. Имя: `auksion_bot` (можно любое)
3. **Public** — обязательно (иначе GitHub Pages не работает)
4. Нажать **Create repository**

---

## Шаг 2 — Загрузить файлы

В терминале в папке `auksion_bot`:

```bash
git init
git add .
git commit -m "initial"
git branch -M main
git remote add origin https://github.com/ВАШ_НИК/auksion_bot.git
git push -u origin main
```

---

## Шаг 3 — Настроить секреты

В репозитории: **Settings → Secrets and variables → Actions → New repository secret**

| Имя секрета | Значение |
|---|---|
| `TELEGRAM_TOKEN` | Токен бота от @BotFather |
| `TELEGRAM_CHAT_ID` | ID чата или канала |
| `GOOGLE_CREDS_JSON` | Содержимое файла `google_creds.json` (опционально) |

> **Без Google Sheets** бот всё равно работает — данные сохраняются в `data/lots.json`  
> и веб-страница генерируется. Google Sheets — дополнительно.

Как получить содержимое google_creds.json для секрета:
```bash
cat google_creds.json
```
Скопировать весь вывод и вставить в значение секрета.

---

## Шаг 4 — Включить GitHub Pages

1. **Settings → Pages**
2. Source: **Deploy from a branch**
3. Branch: `main`, папка: `/docs`
4. Нажать **Save**

Через 1–2 минуты страница будет доступна по адресу:  
`https://ВАШ_НИК.github.io/auksion_bot/`

---

## Шаг 5 — Первый запуск

1. Перейти во вкладку **Actions** репозитория
2. Слева выбрать **Обновить лоты e-auksion.uz**
3. Нажать **Run workflow → Run workflow**

После завершения (3–5 минут) страница обновится с данными.

---

## Расписание автообновления

Бот запускается автоматически каждый день в **04:00 UTC = 09:00 Ташкент**.

Если хотите изменить время — отредактируйте `.github/workflows/update.yml`:
```yaml
- cron: '0 4 * * *'   # HH MM (UTC)
```
Конвертер: Ташкент UTC+5, значит 9:00 TZT = 04:00 UTC.

---

## Структура файлов после деплоя

```
auksion_bot/
├── bot.py                  # основной бот
├── generate_html.py        # генератор HTML
├── requirements.txt        # зависимости
├── google_creds.json       # НЕ КОММИТИТЬ! (уже в .gitignore)
├── seen_lots.json          # уже обработанные лоты
├── data/
│   ├── lots.json           # все данные лотов
│   └── history.json        # история по дням
├── docs/
│   └── index.html          # ← веб-страница (GitHub Pages)
└── .github/
    └── workflows/
        └── update.yml      # GitHub Actions
```

---

## Добавить .gitignore

Создать файл `.gitignore`:
```
google_creds.json
__pycache__/
*.pyc
.env
```

---

## Локальный запуск (для теста)

```bash
# Установить зависимости
pip install -r requirements.txt

# Запустить бота один раз
python bot.py --no-schedule

# Сгенерировать HTML
python generate_html.py

# Открыть страницу
open docs/index.html
```
