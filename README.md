# YaGo

YaGo — учебное суперприложение для Астаны. Рабочий MVP включает каталог ресторанов, корзину с серверным расчётом состава заказа, заказ такси с демонстрационным фиксированным тарифом, карту, назначение свободного исполнителя, обновление статусов и live-события. Клиент — React/Vite/Leaflet; API — FastAPI; основная база данных — PostgreSQL.

## Запуск

Требуются Node.js 20+, Python 3.11+ и Docker Compose.

```bash
npm install
python3 -m venv server/fastapi/.venv
source server/fastapi/.venv/bin/activate
pip install -r server/fastapi/requirements.txt
cp server/.env.example server/.env
docker compose up -d db
npm run dev
```

Frontend: http://localhost:5173  
Backend: http://localhost:8000  
OpenAPI: http://localhost:8000/docs

PostgreSQL хранит рестораны, меню, исполнителей, заказы и снимки строк заказа. При первом запуске таблицы создаются приложением, каталог и исполнители заполняются демонстрационными данными. Цены еды и итог рассчитывает backend; свободный исполнитель резервируется при назначении в одной транзакции с заказом. Данные PostgreSQL сохраняются в Docker volume `yago-postgres`.

Для внешней БД измените `DATABASE_URL` в `server/.env`. Не коммитьте `.env` и реальные секреты. Для остановки локальной БД выполните `docker compose down`; данные останутся в volume.

## API

- `GET /api/health`, `/api/config`, `/api/restaurants`, `/api/orders`, `/api/couriers`
- `GET /api/routes?startLat=...&startLng=...&endLat=...&endLng=...` — автомобильный маршрут OSRM: GeoJSON улиц, названия дорог, длины участков и ETA
- `POST /api/orders` — создать заказ
- `PATCH /api/orders/{id}/status` — допустимый переход статуса заказа
- `POST /api/trace/{performer_id}` — обновить позицию исполнителя
- `WS /ws` — события `orderCreated`, `orderStatusUpdated`, `driverMoved`

Заказы и изменения статуса сохраняются до отправки события. После переподключения клиент загружает актуальное состояние через REST.

## Границы MVP

OSRM строит один автомобильный маршрут по дорожному графу OpenStreetMap и возвращает геометрию, названия улиц, шаги и расчётное время. Публичный demo-router ограничен и не предоставляет данные о live-пробках; для постоянной нагрузки задайте собственный `OSRM_BASE_URL`. Альтернативные маршруты, пеший/велосипедный режим, регистрация/RBAC, оплата, динамический тариф, PostGIS-геозоны, аренда самокатов/велосипедов и versioned-миграции БД пока не реализованы. Такси пока оформляется по фиксированному демонстрационному тарифу 2 800 ₸; заказ сам по себе не является платежом или реальной оценкой с учётом пробок. Эти возможности описаны в [плане проекта](TZ_13weeks_team_plan.md) и [архитектуре](docs/week-02/p2/ru/02-system-architecture.md), но не должны считаться реализованными.

## Проверки

```bash
npm run build
npm run lint
```

Подробные исходные проектные материалы и ограничения прототипа находятся в [`docs/week-02/`](docs/week-02/README.md).
