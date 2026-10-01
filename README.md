# YaGo

### Текущий прототип

YaGo — учебный прототип суперприложения для Астаны: еда, такси, доставка и карта. Самокаты и велосипеды предусмотрены целевой архитектурой.

## Структура

- `server/` — backend API, бизнес-логика, роуты и интеграция с Supabase/PostgreSQL
- `src/` — frontend React + Vite + Leaflet
Node.js demo API: http://localhost:4000
- [`docs/week-02/`](docs/week-02/README.md) — результаты второй недели для всех пяти участников: экономическая глава, архитектура, сущности БД, спецификация самокатов/велосипедов и ER-модель
### FastAPI backend (каркас недели 3)
## Выполнено по второй неделе
FastAPI пока запускается отдельно; `npm run dev` и Vite proxy продолжают использовать Node.js API на порту 4000.
Подготовлен [полный комплект документов](docs/week-02/README.md) по разделу «Организационно-экономическая часть + архитектура». В нём разделены фактическое состояние кода и решения для следующих недель. [Обзор проекта](docs/week-02/common/ru/00-project-review.md) содержит карту исходников, API, ограничения и результаты проверки запуска.

cd server/fastapi
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --env-file .env --port 8000

Документы второй недели зафиксировали целевой backend на FastAPI, REST и native WebSocket. Исходный код приложения пока не мигрирован: текущий демонстрационный backend находится в `server/src/index.js`; его переделка будет отдельной задачей.
FastAPI health check: http://localhost:8000/api/health
OpenAPI docs: http://localhost:8000/docs

`.env.example` содержит только локальные настройки приложения. Настоящие реквизиты БД и секреты не добавляйте в репозиторий.
## Запуск

```bash
npm install
npm run dev
```

Frontend: http://localhost:5173
Backend: http://localhost:8000

## Переменные окружения

Для проверки соединения с PostgreSQL создайте `server/.env` на основе `server/.env.example` и укажите собственные реквизиты подключения:

```env
PORT=8000
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DATABASE
CITY=Астана
```

Бизнес-данные сейчас хранятся в памяти; постоянное хранение и миграции относятся к следующему этапу. FastAPI backend слушает порт 8000, а dev proxy направляет туда `/api` и `/ws`.

## Текущее устройство

- `server/src/index.js` — работающие обработчики API, WebSocket и демонстрационные данные в памяти.
- `server/src/modules/`, `server/src/data/`, `server/src/config.js` — заготовки, которые точка входа пока не использует.
- `src/App.jsx` — интерфейс, Leaflet/OpenStreetMap, создание заказов `food`/`taxi` и обработка событий.
- [`Архитектура`](docs/week-02/p2/ru/02-system-architecture.md) — текущая и целевая схемы с распределением ответственности.

В прототипе доступны каталог, форма заказа, карта и обновления по WebSocket. Корзина, автоматическое назначение, маршрутизация по дорогам, авторизация, аренда, оценки и полноценная админка ещё не реализованы; навигационные кнопки меняют только выделение.

## Проверки и сборка

```bash
npm run build
npm run lint
```

Сборка проходит. Линтер исходного проекта не запускается: для установленного ESLint 9 отсутствует `eslint.config.*`. Backend build — информационный скрипт без компиляции. `npm start` запускает только API, а не собранный frontend; размещение статики и HTTPS предусмотрено неделей 11. Подробные результаты находятся в [обзоре проекта](docs/week-02/common/ru/00-project-review.md).
