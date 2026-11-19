// Browser acceptance on a seeded local stand. Each run creates a separate demonstration client.
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { chromium } = require('playwright-core');

const baseURL = process.env.YAGO_URL || 'https://localhost:8443';
const emailDomain = '@demo.yago.test';
const password = process.env.DEMO_PASSWORD || 'YaGo-demo-2026!';
const label = 'Репетиция ' + randomUUID().slice(0, 8);
const button = (page, name) => page.getByRole('button', { name, exact: true });

async function openPage(browser, role) {
  const context = await browser.newContext({
    baseURL, ignoreHTTPSErrors: true, viewport: { width: 1440, height: 950 },
  });
  const page = await context.newPage();
  page.setDefaultTimeout(18000);
  if (!role) await page.addInitScript(() => {
    const NativeWebSocket = window.WebSocket;
    window.WebSocket = class extends NativeWebSocket {
      constructor(...args) { super(...args); window.rehearsalSocket = this; }
    };
  });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  if (!role) return page;
  await page.getByLabel('Электронная почта').fill(role + emailDomain);
  await page.getByLabel('Пароль').fill(password);
  await button(page, 'Войти').click();
  await page.getByRole('button', { name: /Кабинет/ }).click();
  return page;
}

async function pick(page, lat, lng) {
  // Leaflet's initial Web Mercator viewport, zoom 13.
  const project = (lat, lng) => {
    const sin = Math.sin(lat * Math.PI / 180);
    return [2097152 * (lng + 180) / 360, 2097152 * (.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI))];
  };
  const [x, y] = project(lat, lng), [cx, cy] = project(51.129, 71.43);
  const map = page.locator('.map.leaflet-container');
  await map.scrollIntoViewIfNeeded();
  const box = await map.boundingBox();
  await map.click({ position: { x: box.width / 2 + x - cx, y: box.height / 2 + y - cy } });
}

async function confirm(page, action, path, status) {
  const response = page.waitForResponse(r => new URL(r.url()).pathname.endsWith(path) &&
    ['POST', 'PATCH'].includes(r.request().method()));
  await action();
  const result = await response;
  assert.equal(result.status(), status, await result.text());
  return result.json();
}

async function advance(page, order, service, status) {
  const card = page.locator('.office-order').filter({ hasText: label }).filter({ hasText: service });
  const result = await confirm(page, () => card.getByRole('button', { name: 'Следующий статус' }).click(),
    '/orders/' + order.id + '/status', 200);
  assert.equal(result.status, status);
  // Wait for the page to render the transition before clicking the next action.
  await card.getByText(new RegExp({ preparing: 'Готовится', assigned: 'Назначен', accepted: 'Принят',
    arriving: 'Едет к вам', in_progress: 'В пути', picked_up: 'Забран курьером', completed: 'Завершён' }[status])).waitFor();
}

async function rehearse(browser) {
  const page = await openPage(browser);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.getByRole('button', { name: /Нет аккаунта/ }).click();
  await page.getByLabel('Ваше имя').fill(label);
  await page.getByLabel('Электронная почта').fill('rehearsal-' + randomUUID() + '@test.yago.local');
  await page.getByLabel('Пароль').fill(password);
  await button(page, 'Зарегистрироваться').click();
  await page.locator('.connection.on').waitFor();
  const session = (await page.context().cookies()).find(cookie => cookie.name === 'yago_session');
  assert(session?.httpOnly);
  if (baseURL.startsWith('https://')) assert(session.secure);
  const [operator, driver, courier, admin] = await Promise.all(
    ['operator', 'driver', 'courier', 'admin'].map(role => openPage(browser, role)));
  await admin.evaluate(async () => {
    window.receivedOrders = [];
    await Promise.all(Array.from({ length: 24 }, () => new Promise((resolve, reject) => {
      const url = new URL('/ws', location.href);
      url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(url);
      const timer = setTimeout(() => reject(new Error('WebSocket handshake exceeded 15s')), 15000);
      ws.onopen = () => { clearTimeout(timer); resolve(); };
      ws.onerror = reject;
      ws.onmessage = ({ data }) => {
        const event = JSON.parse(data);
        if (event.event === 'orderCreated') {
          window.receivedOrders.push(event.data.id);
          ws.close();
        }
      };
    })));
  });
  console.log('24 authenticated WSS subscribers connected');
  await page.setViewportSize({ width: 390, height: 844 });
  assert(await page.locator('.map').isVisible());
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await button(page, 'Профиль').click();
  await page.getByLabel('Учебный код').fill('YAGO-STUDENT');
  await button(page, 'Подтвердить').click();
  await page.getByText(/Статус подтверждён/).first().waitFor();
  await button(page, 'Такси').click();
  await button(page, 'Откуда').click();
  await pick(page, 51.129, 71.430);
  await button(page, 'Куда').click();
  await pick(page, 51.135, 71.410);
  await button(page, 'Рассчитать поездку').click();
  await page.getByText(/Коэффициент спроса/).waitFor();
  const taxi = await confirm(page, () => button(page, 'Подтвердить заказ').click(), '/api/orders', 201);
  await admin.waitForFunction(id => window.receivedOrders.filter(item => item === id).length === 24, taxi.id);
  await page.locator('.history-item').filter({ hasText: 'Такси' }).waitFor();
  assert.equal(await page.locator('.history-item').filter({ hasText: 'Такси' }).count(), 1);
  await advance(operator, taxi, 'Такси', 'assigned');
  await button(page, 'Такси').click();
  await page.locator('.compact-order').getByText('Назначен').waitFor();
  const marker = page.locator('.leaflet-marker-icon').last();
  const beforeMove = await marker.getAttribute('style');
  await driver.getByRole('button', { name: 'Передать дальнюю позицию' }).click();
  await page.waitForFunction(before => [...document.querySelectorAll('.leaflet-marker-icon')].at(-1)?.getAttribute('style') !== before, beforeMove);
  await confirm(driver, () => button(driver, 'Передать позицию в центре').click(), '/performers/me/position', 200);
  await page.context().setOffline(true);
  await page.evaluate(() => window.rehearsalSocket.close());
  await page.locator('.offline-banner').waitFor();
  await advance(driver, taxi, 'Такси', 'accepted');
  await page.context().setOffline(false);
  await page.locator('.compact-order').getByText('Принят').waitFor();
  for (const status of ['arriving', 'in_progress', 'completed']) await advance(driver, taxi, 'Такси', status);
  await button(page, 'История').click();
  const ride = page.locator('.history-item').filter({ hasText: 'Такси' });
  await button(ride, 'Оставить отзыв').click();
  await ride.getByLabel('Оценка').selectOption('4');
  await ride.getByLabel('Комментарий').fill('Машина приехала вовремя');
  await confirm(page, () => button(ride, 'Отправить отзыв').click(), '/review', 201);
  await ride.getByText('Ваша оценка · 4/5').waitFor();
  await ride.getByText('Машина приехала вовремя').waitFor();
  console.log('Mobile taxi, student discount, assignment, WSS reconnect and completed ride OK');

  await page.setViewportSize({ width: 1440, height: 950 });
  await button(page, 'Еда').click();
  await page.getByRole('button', { name: /Зелёный двор/ }).click();
  await button(page, 'Добавить Бешбармак').click();
  await pick(page, 51.135, 71.410);
  await button(page, 'Рассчитать доставку').click();
  const food = await confirm(page, () => button(page, 'Подтвердить заказ').click(), '/api/orders', 201);
  for (const status of ['preparing', 'assigned']) await advance(operator, food, 'Доставка еды', status);
  for (const status of ['accepted', 'picked_up', 'completed']) await advance(courier, food, 'Доставка еды', status);
  console.log('Food order, kitchen, assignment, courier and delivery OK');

  await button(page, 'Самокаты').click();
  const vehicle = 'YG-101';
  await page.getByRole('button', { name: new RegExp(vehicle + '.*Заряд') }).click();
  await button(page, 'Забронировать ' + vehicle).click();
  await button(page, 'Показать демо-код').click();
  await button(page, 'Начать аренду').click();
  await page.getByRole('heading', { name: 'Аренда · ' + vehicle }).waitFor();
  await pick(page, 51.135, 71.445);
  const denied = await confirm(page, () => button(page, 'Завершить аренду').click(), '/finish', 409);
  assert.match(denied.detail, /запрещена/);
  await pick(page, 51.128, 71.421);
  const rental = await confirm(page, () => button(page, 'Завершить аренду').click(), '/finish', 200);
  assert.equal(rental.status, 'completed');
  await button(page, 'История').click();
  await page.locator('.history-item').filter({ hasText: vehicle }).waitFor();
  const select = operator.getByLabel('Состояние ' + vehicle);
  for (const state of ['maintenance', 'blocked', 'available']) {
    await confirm(operator, () => select.selectOption(state), '/operator/scooters/' + rental.scooterId, 200);
  }
  await admin.reload({ waitUntil: 'domcontentloaded' });
  await admin.getByRole('button', { name: /Кабинет/ }).click();
  await admin.getByRole('heading', { name: 'Показатели' }).waitFor();
  await admin.locator('.heatmap .leaflet-overlay-pane path').first().waitFor();
  assert.equal(await admin.locator('.metrics strong').count(), 4);
  assert.deepEqual(errors, []);
  console.log('Scooter QR, both parking decisions, fleet, history and admin metrics OK');
}

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try { await rehearse(browser); } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
