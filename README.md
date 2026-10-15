# YaGo

YaGo — приложение для заказов еды и поездок. Клиент — React/Vite/Leaflet; API — FastAPI; основная база данных — PostgreSQL.

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

PostgreSQL хранит рестораны, меню, исполнителей, заказы и снимки строк заказа. При первом запуске приложение только создаёт таблицы: тестовые пользователи, рестораны, меню, исполнители и заказы не добавляются. Цены еды и итог рассчитывает backend; свободный исполнитель резервируется при назначении в одной транзакции с заказом. Данные PostgreSQL сохраняются в Docker volume `yago-postgres`.

Для внешней БД измените `DATABASE_URL` в `server/.env`. Не коммитьте `.env` и реальные секреты. Для остановки локальной БД выполните `docker compose down`; данные останутся в volume.

## API

- `GET /api/health`, `/api/config`, `/api/restaurants`, `/api/orders`, `/api/couriers`
- `GET /api/geocode?q=...` — поиск адреса и его координат через OpenStreetMap Nominatim
- `GET /api/reverse-geocode?lat=...&lng=...` — получение адреса для точки карты через Nominatim
- `GET /api/routes?startLat=...&startLng=...&endLat=...&endLng=...` — автомобильный маршрут OSRM: GeoJSON улиц, названия дорог, длины участков и ETA
- `POST /api/orders` — создать заказ
- `PATCH /api/orders/{id}/status` — допустимый переход статуса заказа
- `POST /api/trace/{performer_id}` — обновить позицию исполнителя
- `WS /ws` — события `orderCreated`, `orderStatusUpdated`, `driverMoved`

Заказы и изменения статуса сохраняются до отправки события. После переподключения клиент загружает актуальное состояние через REST.

## Настройка перед запуском

Заполните `server/.env`: подключение к PostgreSQL, `NOMINATIM_USER_AGENT`, а также `TAXI_BASE_FARE` и `TAXI_PRICE_PER_KM`. Без тарифа такси и без заведений/исполнителей, добавленных оператором в базу, соответствующие функции специально недоступны — приложение не показывает фиктивные данные.

## Ограничения интеграций

OSRM строит один автомобильный маршрут по дорожному графу OpenStreetMap и возвращает геометрию, названия улиц, шаги и расчётное время. Публичные OSRM и Nominatim ограничены; для production задайте собственные сервисы или коммерческие API. Регистрация/RBAC, оплата, PostGIS-геозоны, аренда самокатов/велосипедов и versioned-миграции БД требуют отдельной настройки инфраструктуры.

## Проверки

```bash
npm run build
npm run lint
```

Подробные исходные проектные материалы и ограничения прототипа находятся в [`docs/week-02/`](docs/week-02/README.md).

## ER-модель базы данных

Логическая модель PostgreSQL в третьей нормальной форме подготовлена в формате diagrams.net:

- [Открыть ER-модель 3НФ](docs/week-03/p3/yago-er-3nf.drawio)

В модели справочники (`roles`, `service_types`, `order_statuses`, `menu_categories`) отделены от операций, адреса вынесены в отдельную таблицу, а связи many-to-many и история статусов реализованы отдельными таблицами. Производные суммы не хранятся в `orders`: итог заказа рассчитывается из строк заказа и тарифа.
