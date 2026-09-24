# YaGo жалпы архитектурасы

[Аптаның барлық материалдары](../../README.md) · [Орысша](../ru/02-system-architecture.md)

**Версия:** 1.0, 24.09.2026. **Жауапты:** П2 — Maps & Real-time.

## 1. Қазіргі архитектура

![YaGo ағымдағы архитектурасы](diagrams/architecture-current.png)

Қазіргі демонстрациялық жүйеде React Vite арқылы Express және Socket.IO серверіне қосылады. Бизнес деректері жадтағы массивтерде, карта Leaflet/OpenStreetMap арқылы беріледі. [SVG нұсқасы](diagrams/architecture-current.svg).

```mermaid
flowchart LR
    User["Демо пайдаланушы"] --> UI["React: src/App.jsx"]
    UI -->|"HTTP /api; Socket.IO /socket.io"| Vite["Vite :5173 / dev proxy"]
    Vite --> API["Express + Socket.IO :4000 / server/src/index.js"]
    API --> Memory["Жадтағы массивтер: restaurants, menu, couriers, orders"]
    API -->|"/api/health ішінде тек SELECT 1"| PG["PostgreSQL / Supabase, қолжетімділік бапталса"]
    UI --> Tiles["OpenStreetMap тайлдары"]
    UI --> CDN["Leaflet және Google Fonts CDN"]
    Drafts["config.js, mockData.js, orderService.js"] -.->|"дайындама: entry point импорттамайды"| API
```

## 2. Мақсатты архитектура

![YaGo мақсатты архитектурасы](diagrams/architecture-target.png)

Мақсатты шешім — бір NestJS backend-процесі бар модульдік монолит. Auth, Orders, Maps, Rentals және Admin модульдері ортақ PostgreSQL/PostGIS қоймасымен транзакциялар арқылы жұмыс істейді; Nginx REST пен Socket.IO трафигін қабылдайды. [SVG нұсқасы](diagrams/architecture-target.svg).

```mermaid
flowchart TB
    Client["Клиент / жүргізуші / курьер / мейрамхана"] --> Web["React: клиент экрандары"]
    Staff["Әкімші / техника операторы"] --> AdminUI["React: басқару экрандары"]
    Web -->|"HTTPS REST + Socket.IO"| Edge["Nginx / HTTPS / статикалық файлдар"]
    AdminUI -->|"HTTPS REST + Socket.IO"| Edge
    Web -->|"карта және тайлдар; браузер кілті"| MapGL["2GIS MapGL / Map Tiles"]
    subgraph Backend["NestJS — бір backend"]
        API["Controllers / кіріс деректерін тексеру"]
        Auth["П1: Auth / Sessions / RBAC"]
        Orders["П3: Orders / каталог / тағайындау"]
        Maps["П2: Maps / Routing / Tracking"]
        Rentals["П4: Scooter / Bike / Rentals"]
        Admin["П5: Admin / Analytics / Tariffs / Zones"]
        RT["П2: Socket.IO Gateway"]
        Storage["Репозиторийлер / транзакциялар"]
    end
    Edge --> API
    Edge <-->|"Socket.IO"| RT
    API --> Auth
    RT --> Auth
    API --> Orders
    API --> Maps
    API --> Rentals
    API --> Admin
    Orders -->|"маршрут және геоіздеу"| Maps
    Rentals -->|"ортақ тапсырыс"| Orders
    Orders -->|"тариф және аймақ"| Admin
    Rentals -->|"тариф және аймақ"| Admin
    Maps -->|"серверлік HTTP, тайм-аут"| Routing["2GIS Routing API"]
    Rentals -->|"unlock / lock, command_id"| Emulator["Құлып және телеметрия эмуляторы"]
    Emulator -->|"растау және координаттар"| Rentals
    Auth --> Storage
    Orders --> Storage
    Maps --> Storage
    Rentals --> Storage
    Admin --> Storage
    Storage --> DB[("PostgreSQL + PostGIS")]
    Orders -.->|"бекітілгеннен кейін"| RT
    Rentals -.->|"бекітілгеннен кейін"| RT
    Maps -.->|"жазылушыға қолжетімді координаттар"| RT
```

## 3. Апта 2 шешімдері

Express-тен NestJS-ке, Leaflet/OSM-нан 2GIS MapGL-ға көшу келесі апталарда орындалады. `orders` ортақ тапсырысты, `rentals` аренда деталін сақтайды. REST әрекетті бекітеді, Socket.IO commit-тен кейін өзгерісті хабарлайды. Баға серверде есептеледі, браузер дерекқорға тікелей қосылмайды.

## 4. Аренда ағыны

![Аренданы брондау және бастау](diagrams/rental-sequence.png)

Бронь транзакцияда жасалады, ал құлып эмуляторын күту кезінде дерекқор транзакциясы ашық тұрмайды. [SVG нұсқасы](diagrams/rental-sequence.svg).

```mermaid
sequenceDiagram
    actor C as Клиент
    participant API as Auth + Scooter API
    participant O as Orders + Rentals
    participant DB as PostgreSQL
    participant E as Эмулятор
    participant G as Socket.IO Gateway
    C->>API: vehicle_id + идемпотенттілік кілтімен брондау
    API->>API: Пайдаланушыны, құқықтарды, деректерді тексеру
    API->>O: Бронь жасау
    O->>DB: Транзакция: техника қолжетімділігі, orders + rentals
    DB-->>O: Commit немесе қақтығыс
    O-->>C: Расталған бронь немесе қате
    C->>API: Өз бронінің QR коды + бастау командасы
    API->>O: Иесін, мерзімін және күйін тексеру
    O->>DB: unlocking және command_id сақтау
    O->>E: unlock(command_id, vehicle_id)
    alt unlock сәтті расталды
        E-->>O: Команда орындалды
        O->>DB: Транзакция: active, in_use, басталу уақыты
        DB-->>O: Commit
        O->>G: Тапсырыс пен аренда өзгерді
        G-->>C: Ағымдағы күй
    else Тайм-аут немесе қате
        O->>DB: Тексеру нәтижесін немесе инцидентті сақтау
        O-->>C: Команда күйі, қайта оқу
    end
```

## 5. Тапсыру нәтижесі

Осы құжат T3/2-апта архитектуралық тапсырмасының казахша нұсқасы болып табылады: қазіргі және мақсатты схемалар, модуль иелері, протоколдар, сақтау орны және аренда ағыны көрсетілген. NestJS, PostgreSQL/PostGIS, 2GIS және IoT эмуляторының толық іске асуы келесі апталардың жұмысы.
