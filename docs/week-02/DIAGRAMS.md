# Рисунки недели 2

Откройте [галерею схем](index.html) в браузере или отдельный PNG/SVG в IDE. Интернет и запущенное приложение для просмотра не нужны.

| Рисунок | SVG — масштабирование и печать | PNG — вставка в документ | Исходный раздел |
|---|---|---|---|
| ER-модель | [SVG](p5/ru/diagrams/er-model.svg) | [PNG](p5/ru/diagrams/er-model.png) | [П5](p5/ru/05-er-model.md) |
| Текущая архитектура | [SVG](p2/ru/diagrams/architecture-current.svg) | [PNG](p2/ru/diagrams/architecture-current.png) | [П2](p2/ru/02-system-architecture.md) |
| Целевая архитектура | [SVG](p2/ru/diagrams/architecture-target.svg) | [PNG](p2/ru/diagrams/architecture-target.png) | [П2](p2/ru/02-system-architecture.md) |
| Начало аренды: взаимодействие компонентов | [SVG](p2/ru/diagrams/rental-sequence.svg) | [PNG](p2/ru/diagrams/rental-sequence.png) | [П2](p2/ru/02-system-architecture.md) |
| Состояния техники | [SVG](p4/ru/diagrams/vehicle-states.svg) | [PNG](p4/ru/diagrams/vehicle-states.png) | [П4](p4/ru/04-scooter-specification.md) |
| Жизненный цикл аренды | [SVG](p4/ru/diagrams/rental-states.svg) | [PNG](p4/ru/diagrams/rental-states.png) | [П4](p4/ru/04-scooter-specification.md) |

## Обновление рисунков

Канонический исходник каждой схемы — Mermaid-блок в соответствующем Markdown-документе. В просмотре он свёрнут под рисунком. После изменения исходников из корня проекта выполните:

```bash
npm install
npm run docs:diagrams
```

Генератор строит все шесть схем в SVG и PNG с белым фоном; PNG имеет двойную плотность пикселей. Он также сохраняет копии `.mmd` для переноса в редактор Mermaid. PNG, SVG и `.mmd` генерируются заново: правки следует вносить в Markdown, иначе при следующем запуске они будут потеряны. Оформление задаётся в [mermaid.config.json](../../scripts/mermaid.config.json), список исходников — в [render-diagrams.mjs](../../scripts/render-diagrams.mjs).

Для генерации нужны Node.js 20.19+ и Chrome, который Puppeteer загружает при установке зависимостей. Готовые рисунки уже включены в проект: установка инструментов нужна только для обновления. Если загрузка браузера при установке была пропущена, выполните `npx puppeteer browsers install chrome`. При собственном установленном Chrome можно задать `PUPPETEER_EXECUTABLE_PATH`.

При необходимости передайте путь к локальному JSON с параметрами запуска браузера через `MERMAID_PUPPETEER_CONFIG`. Например, файл с `{"executablePath":"/path/to/chrome"}` указывает конкретный Chrome. Настройки рабочей машины не следует добавлять в общую конфигурацию проекта.
