import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { CircleMarker, GeoJSON, MapContainer, Marker, Polyline, TileLayer, useMapEvents } from 'react-leaflet';
import L from 'leaflet';
import markerIconUrl from 'leaflet/dist/images/marker-icon.png';
import markerShadowUrl from 'leaflet/dist/images/marker-shadow.png';
import 'leaflet/dist/leaflet.css';

const marker = L.icon({ iconUrl: markerIconUrl, shadowUrl: markerShadowUrl, iconSize: [25, 41], iconAnchor: [12, 41] });
const routeMarker = (label, kind) => L.divIcon({ className: `route-pin route-pin-${kind}`, html: `<span>${label}</span>`, iconSize: [32, 32], iconAnchor: [16, 16] });
const startMarker = routeMarker('А', 'start');
const endMarker = routeMarker('Б', 'end');
const money = value => `${Number(value || 0).toLocaleString('ru-RU', { maximumFractionDigits: 2 })} ₸`;
const date = value => new Intl.DateTimeFormat('ru-RU', { timeZone: 'Asia/Almaty', dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
const names = { pending: 'Ожидает', preparing: 'Готовится', assigned: 'Назначен', accepted: 'Принят', arriving: 'Едет к вам', picked_up: 'Забран курьером', in_progress: 'В пути', completed: 'Завершён', cancelled: 'Отменён', active: 'Активна' };
const loginNames = { login: 'Вход', login_failed: 'Неверный пароль или адрес', login_rate_limited: 'Лимит попыток', login_2fa: 'Вход с 2FA', login_2fa_failed: 'Неверный код 2FA', login_2fa_expired: 'Истёкший код 2FA' };
const serviceName = type => ({ taxi: 'Такси', food: 'Доставка еды', scooter: 'Электросамокаты' })[type] || 'Архивная услуга';
const nav = [['taxi', 'Такси', '↗'], ['food', 'Еда', '◧'], ['scooter', 'Самокаты', '⌁'], ['history', 'История', '◷'], ['profile', 'Профиль', '○']];
const blank = () => ({ address: '', lat: '', lng: '' });
const csrf = () => decodeURIComponent(document.cookie.split('; ').find(x => x.startsWith('yago_csrf='))?.split('=')[1] || '');

function validationMessage(detail) {
  if (!Array.isArray(detail)) return null;
  const fields = { full_name: 'Имя', email: 'Почта', password: 'Пароль' };
  return detail.map(issue => {
    const field = issue.loc?.at(-1);
    const label = fields[field];
    if (!label) return 'Проверьте введённые данные';
    if (issue.type === 'string_too_short') return `${label}: минимум ${issue.ctx?.min_length} символов`;
    if (issue.type === 'string_too_long') return `${label}: максимум ${issue.ctx?.max_length} символов`;
    if (issue.type === 'missing') return `${label}: заполните поле`;
    if (field === 'email') return 'Укажите корректную почту';
    return `${label}: проверьте значение`;
  }).join('. ') || 'Проверьте введённые данные';
}

async function api(path, options = {}) {
  const response = await fetch(path, { credentials: 'same-origin', ...options,
    headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.method && options.method !== 'GET' ? { 'X-CSRF-Token': csrf() } : {}), ...options.headers } });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail;
    const error = new Error(typeof detail === 'string' ? detail : validationMessage(detail) || detail?.message || 'Не удалось выполнить действие');
    error.detail = detail;
    error.status = response.status;
    throw error;
  }
  return data;
}

function Button({ children, variant = 'primary', ...props }) {
  return <button className={`button button-${variant}`} type="button" {...props}>{children}</button>;
}
function Field({ label, value, onChange, type = 'text', placeholder, autoComplete }) {
  return <label className="field"><span>{label}</span><input type={type} value={value} onChange={onChange} placeholder={placeholder} autoComplete={autoComplete} /></label>;
}
function Card({ title, children, className = '' }) {
  return <section className={`card ${className}`}><h2>{title}</h2>{children}</section>;
}
function MapClick({ onPick }) { useMapEvents({ click: e => onPick(e.latlng) }); return null; }

function OrderMapLayers({ orders, tab }) {
  return orders.filter(order => order.type === tab).map(order => {
    const coordinates = order.routeGeometry?.coordinates || [
      [order.start.lng, order.start.lat], [order.end.lng, order.end.lat],
    ];
    return <ReactOrderMap key={order.id} order={order} coordinates={coordinates} />;
  });
}

function ReactOrderMap({ order, coordinates }) {
  return <>
    <Polyline positions={coordinates.map(([lng, lat]) => [lat, lng])} pathOptions={{ color: '#47699a', weight: 4, opacity: .8 }} />
    <Marker position={[order.start.lat, order.start.lng]} icon={marker} />
    <Marker position={[order.end.lat, order.end.lng]} icon={marker} />
  </>;
}

function AddressField({ label, point, onChange }) {
  const [results, setResults] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function search() {
    if (point.address.trim().length < 3) { setError('Введите минимум три символа'); return; }
    setBusy(true); setError('');
    try { setResults(await api(`/api/geocode?q=${encodeURIComponent(point.address)}`)); }
    catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return <div className="address-field"><div className="address-input"><Field label={label} value={point.address} placeholder="Улица и дом в Астане" onChange={e => onChange({ address: e.target.value, lat: '', lng: '' })} /><Button variant="quiet" onClick={search} disabled={busy}>{busy ? 'Ищем…' : 'Найти'}</Button></div>
    {error && <small className="field-error" role="alert">{error}</small>}
    {results.length > 0 && <div className="address-results">{results.map((result, i) => <button key={i} type="button" onClick={() => { onChange(result); setResults([]); }}>{result.address}</button>)}</div>}
    {point.lat !== '' && <small className="hint">Точка выбрана · {Number(point.lat).toFixed(4)}, {Number(point.lng).toFixed(4)}</small>}
  </div>;
}

const emptyZone = () => ({ name: '', south: '51.12', west: '71.42', north: '51.14', east: '71.45', active: true });
function ZoneManager({ zones, act, busy }) {
  const [selected, setSelected] = useState('');
  const [form, setForm] = useState(emptyZone);
  function choose(zone) {
    const ring = zone.geometry.coordinates[0];
    const lng = ring.map(point => point[0]);
    const lat = ring.map(point => point[1]);
    setSelected(zone.id);
    setForm({ name: zone.name, south: String(Math.min(...lat)), west: String(Math.min(...lng)),
      north: String(Math.max(...lat)), east: String(Math.max(...lng)), active: zone.active });
  }
  async function save() {
    const body = { ...form, south: Number(form.south), west: Number(form.west),
      north: Number(form.north), east: Number(form.east) };
    const result = await act(() => api(selected ? `/api/operator/zones/${selected}` : '/api/operator/zones',
      { method: selected ? 'PATCH' : 'POST', body: JSON.stringify(body) }), 'Зона сохранена');
    if (result) { setSelected(''); setForm(emptyZone()); }
  }
  return <Card title="Геозоны парковки">
    {zones.map(zone => <div className="session-row" key={zone.id}><span>{zone.name} · {zone.active ? 'активна' : 'архив'}</span>
      <div className="office-actions"><Button variant="quiet" onClick={() => choose(zone)}>Изменить</Button>
        <Button variant="quiet" onClick={() => act(() => api(`/api/operator/zones/${zone.id}/status`,
          { method: 'PATCH', body: JSON.stringify({ active: !zone.active }) }), 'Зона обновлена')}>{zone.active ? 'Архивировать' : 'Включить'}</Button>
        {!zone.active && <Button variant="quiet" onClick={() => { if (window.confirm(`Удалить зону «${zone.name}»?`)) act(() => api(`/api/operator/zones/${zone.id}`, { method: 'DELETE' }), 'Зона удалена'); }}>Удалить</Button>}</div>
    </div>)}
    <h3>{selected ? 'Изменить зону' : 'Новая зона'}</h3>
    {['name', 'south', 'west', 'north', 'east'].map(field => <Field key={field}
      label={{ name: 'Название', south: 'Южная граница', west: 'Западная граница', north: 'Северная граница', east: 'Восточная граница' }[field]}
      value={form[field]} onChange={event => setForm({ ...form, [field]: event.target.value })} />)}
    {selected && <label className="field"><span>Состояние</span><select value={String(form.active)}
      onChange={event => setForm({ ...form, active: event.target.value === 'true' })}>
      <option value="true">Активна</option><option value="false">Архив</option></select></label>}
    <p className="hint">Координаты WGS84; граница зоны разрешена для парковки.</p>
    <Button disabled={busy} onClick={save}>{selected ? 'Сохранить зону' : 'Создать зону'}</Button>
    {selected && <Button variant="quiet" onClick={() => { setSelected(''); setForm(emptyZone()); }}>Отмена</Button>}
  </Card>;
}

const emptyTariff = () => ({ service: 'taxi', name: '', baseFare: '', pricePerKm: '0', pricePerMinute: '0' });
function TariffManager({ tariffs, act, busy }) {
  const [selected, setSelected] = useState('');
  const [form, setForm] = useState(emptyTariff);
  async function save() {
    const result = await act(() => api(selected ? `/api/operator/tariffs/${selected}` : '/api/operator/tariffs',
      { method: selected ? 'PATCH' : 'POST', body: JSON.stringify(form) }), 'Версия тарифа сохранена');
    if (result) { setSelected(''); setForm(emptyTariff()); }
  }
  return <Card title="Версии тарифов">
    {tariffs.map(tariff => <div className="session-row" key={tariff.id}><span>{tariff.name}
      <small>{serviceName(tariff.service)} · {date(tariff.validFrom)} · {tariff.used ? 'использована' : 'не использована'}</small></span>
      {!tariff.used && <div className="office-actions"><Button variant="quiet" onClick={() => {
        setSelected(tariff.id); setForm({ service: tariff.service, name: tariff.name,
          baseFare: tariff.baseFare, pricePerKm: tariff.pricePerKm, pricePerMinute: tariff.pricePerMinute });
      }}>Изменить</Button><Button variant="quiet" onClick={() => {
        if (window.confirm(`Удалить версию «${tariff.name}»?`)) act(() => api(`/api/operator/tariffs/${tariff.id}`, { method: 'DELETE' }), 'Версия тарифа удалена');
      }}>Удалить</Button></div>}
    </div>)}
    <h3>{selected ? 'Изменить неиспользованную версию' : 'Новая версия тарифа'}</h3>
    <label className="field"><span>Услуга</span><select value={form.service}
      onChange={event => setForm({ ...form, service: event.target.value })}>
      <option value="taxi">Такси</option><option value="food">Еда</option><option value="scooter">Самокаты</option></select></label>
    {['name', 'baseFare', 'pricePerKm', 'pricePerMinute'].map(field => <Field key={field}
      label={{ name: 'Название', baseFare: 'Посадка / разблокировка', pricePerKm: 'За километр', pricePerMinute: 'За минуту' }[field]}
      value={form[field]} onChange={event => setForm({ ...form, [field]: event.target.value })} />)}
    <Button disabled={busy} onClick={save}>{selected ? 'Сохранить версию' : 'Создать версию'}</Button>
    {selected && <Button variant="quiet" onClick={() => { setSelected(''); setForm(emptyTariff()); }}>Отмена</Button>}
  </Card>;
}

function Auth({ onSuccess }) {
  const [mode, setMode] = useState('login');
  const [form, setForm] = useState({ email: '', password: '', full_name: '' });
  const [secondCode, setSecondCode] = useState('');
  const [challenge, setChallenge] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      if (challenge) { onSuccess(await api('/api/auth/verify-2fa', { method: 'POST', body: JSON.stringify({ code: secondCode }) })); }
      else {
        const result = await api(`/api/auth/${mode}`, { method: 'POST', body: JSON.stringify(mode === 'login' ? { email: form.email, password: form.password } : form) });
        if (result.requires2fa) setChallenge(true); else onSuccess(result);
      }
    }
    catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return <main className="auth-page"><div className="auth-brand"><span className="brand-mark">Я</span><h1>YaGo</h1><p>Ваш город в одном движении.</p></div>
    <form className="auth-card" onSubmit={submit}><p className="eyebrow">Астана · городской сервис</p><h1>{challenge ? 'Код подтверждения' : mode === 'login' ? 'С возвращением' : 'Поехали вместе'}</h1>
      <p className="muted">Такси, доставка еды и электросамокаты рядом с вами.</p>
      {challenge ? <Field label="Шестизначный код приложения" value={secondCode} onChange={e => setSecondCode(e.target.value)} autoComplete="one-time-code" /> : <>
      {mode === 'register' && <Field label="Ваше имя" value={form.full_name} onChange={e => setForm({ ...form, full_name: e.target.value })} autoComplete="name" />}
      <Field label="Электронная почта" type="email" value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} autoComplete="email" />
      <Field label="Пароль" type="password" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} />
      {mode === 'register' && <small className="hint">Минимум 10 символов. Роль клиента назначается автоматически.</small>}</>}
      {error && <p className="notice error" role="alert">{error}</p>}
      <button className="button button-primary full" disabled={busy} type="submit">{busy ? 'Подождите…' : challenge ? 'Подтвердить' : mode === 'login' ? 'Войти' : 'Зарегистрироваться'}</button>
      <button className="text-button" type="button" onClick={() => { if (challenge) setChallenge(false); else setMode(mode === 'login' ? 'register' : 'login'); setError(''); }}>{challenge ? 'Вернуться к входу' : mode === 'login' ? 'Нет аккаунта? Зарегистрироваться' : 'Уже есть аккаунт? Войти'}</button>
    </form></main>;
}

function App() {
  const [user, setUser] = useState(null);
  const [booting, setBooting] = useState(true);
  const [tab, setTab] = useState('taxi');
  const [config, setConfig] = useState(null);
  const [restaurants, setRestaurants] = useState([]);
  const [scooters, setScooters] = useState([]);
  const [zones, setZones] = useState([]);
  const [operatorZones, setOperatorZones] = useState([]);
  const [operatorTariffs, setOperatorTariffs] = useState([]);
  const [orders, setOrders] = useState([]);
  const [rentals, setRentals] = useState([]);
  const [reservations, setReservations] = useState([]);
  const [tariffs, setTariffs] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [users, setUsers] = useState([]);
  const [audit, setAudit] = useState([]);
  const [loginEvents, setLoginEvents] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [heatmap, setHeatmap] = useState([]);
  const [period, setPeriod] = useState({ from: '', to: '' });
  const periodQuery = useRef('');
  const [adminSessionUser, setAdminSessionUser] = useState('');
  const [adminSessions, setAdminSessions] = useState([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState(false);
  const [tracking, setTracking] = useState(false);
  const refreshToken = useRef(0);
  const [clock, setClock] = useState(Date.now());
  const [start, setStart] = useState(blank);
  const [end, setEnd] = useState(blank);
  const [parkingPoint, setParkingPoint] = useState(blank);
  const [mapTarget, setMapTarget] = useState('start');
  const mapPickVersion = useRef({ start: 0, end: 0 });
  const [restaurantId, setRestaurantId] = useState('');
  const [foodSearch, setFoodSearch] = useState('');
  const [foodCategory, setFoodCategory] = useState('');
  const [editingMenuId, setEditingMenuId] = useState('');
  const [cart, setCart] = useState({});
  const [quote, setQuote] = useState(null);
  const [selectedScooter, setSelectedScooter] = useState('');
  const [qrCode, setQrCode] = useState('');
  const [profile, setProfile] = useState({ fullName: '', phone: '' });
  const [twoFactorSecret, setTwoFactorSecret] = useState('');
  const [twoFactorCode, setTwoFactorCode] = useState('');
  const [studentCode, setStudentCode] = useState('');
  const [menuForm, setMenuForm] = useState({ name: '', description: '', category: 'Основное', price: '' });
  const [menuEditForm, setMenuEditForm] = useState({ name: '', description: '', category: '', price: '', available: true });
  const [restaurantForm, setRestaurantForm] = useState({ name: '', cuisine: '', address: blank() });
  const [scooterForm, setScooterForm] = useState({ code: '', qrCode: '', lat: '51.129', lng: '71.43', battery: '100' });
  const orderKey = useRef(crypto.randomUUID());
  const staff = user?.roles.some(role => ['operator', 'admin'].includes(role));
  const performer = user?.roles.some(role => ['driver', 'courier', 'performer'].includes(role));
  const admin = user?.roles.includes('admin');
  const restaurant = restaurants.find(item => item.id === restaurantId);
  const visibleRestaurants = restaurants.filter(item => `${item.name} ${item.cuisine}`.toLocaleLowerCase('ru-RU').includes(foodSearch.toLocaleLowerCase('ru-RU')));
  const categories = [...new Set(restaurant?.menu.map(item => item.category) || [])];
  const visibleMenu = restaurant?.menu.filter(item => !foodCategory || item.category === foodCategory) || [];
  const vehicle = scooters.find(item => item.id === selectedScooter);
  const lines = useMemo(() => restaurant?.menu.filter(item => cart[item.id]).map(item => ({ menuItemId: item.id, quantity: cart[item.id] })) || [], [restaurant, cart]);
  const activeReservation = reservations[0];
  const activeRental = rentals.find(item => item.status === 'active');
  const activeOrders = orders.filter(item => !['completed', 'cancelled'].includes(item.status));
  const trackedPerformers = !staff && performer ? [...new Set(activeOrders.map(order => order.performerId).filter(Boolean))] : [];
  const trackingTargets = trackedPerformers.join(',');

  const refresh = useCallback(async identity => {
    if (!identity) return;
    const token = ++refreshToken.current;
    setLoading(true);
    try {
      const elevated = identity.roles.some(role => ['operator', 'admin'].includes(role));
      const jobs = [api('/api/restaurants'), api('/api/scooters'), api('/api/zones'), api('/api/orders'), api('/api/rentals'), api('/api/reservations'), api('/api/tariffs'), api('/api/auth/sessions')];
      if (elevated) jobs.push(api('/api/operator/scooters'), api('/api/operator/zones'), api('/api/operator/tariffs'));
      if (identity.roles.includes('admin')) jobs.push(api('/api/admin/users'), api('/api/admin/audit'), api(`/api/admin/analytics${periodQuery.current}`), api('/api/admin/heatmap'), api('/api/admin/login-events'));
      const data = await Promise.all(jobs);
      if (token !== refreshToken.current) return;
      setRestaurants(data[0]); setScooters(elevated ? data[8] : data[1]); setZones(data[2]); setOrders(data[3]); setRentals(data[4]); setReservations(data[5]); setTariffs(data[6]); setSessions(data[7]);
      if (elevated) { setOperatorZones(data[9]); setOperatorTariffs(data[10]); }
      if (identity.roles.includes('admin')) { setUsers(data[11]); setAudit(data[12]); setAnalytics(data[13]); setHeatmap(data[14]); setLoginEvents(data[15]); }
      setError('');
    } catch (err) { if (token === refreshToken.current) { if (err.status === 401) setUser(null); else setError(err.message); } }
    finally { if (token === refreshToken.current) setLoading(false); }
  }, []);
  useEffect(() => {
    let alive = true;
    Promise.all([api('/api/config'), api('/api/auth/me').catch(() => null)]).then(([settings, identity]) => {
      if (!alive) return;
      setConfig(settings); setUser(identity);
      if (identity) { setProfile({ fullName: identity.full_name, phone: identity.phone || '' }); refresh(identity); }
    }).catch(err => { if (alive) setError(err.message); }).finally(() => { if (alive) setBooting(false); });
    return () => { alive = false; };
  }, [refresh]);
  useEffect(() => {
    if (!user) return undefined;
    let socket; let timer; let stopped = false; let delay = 1000;
    function connect() {
      const url = new URL('/ws', location.href); url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
      socket = new WebSocket(url);
      socket.onopen = () => { setConnected(true); delay = 1000; refresh(user); };
      socket.onmessage = event => {
        let message;
        try { message = JSON.parse(event.data); } catch { refresh(user); return; }
        if (message.event === 'driverMoved') {
          const { id, lat, lng } = message.data;
          setOrders(previous => previous.map(order => order.performerId === id
            ? { ...order, performerPosition: { lat, lng } } : order));
        } else refresh(user);
      };
      socket.onclose = event => {
        setConnected(false);
        if (event.code === 4401) { setUser(null); return; }
        if (!stopped) { timer = setTimeout(connect, delay); delay = Math.min(delay * 2, 15000); }
      };
      socket.onerror = () => socket.close();
    }
    connect();
    return () => { stopped = true; clearTimeout(timer); socket?.close(); };
  }, [user, refresh]);
  useEffect(() => {
    if (!tracking || !trackingTargets) return undefined;
    if (!navigator.geolocation) { setError('Геолокация недоступна в этом браузере'); setTracking(false); return undefined; }
    const ids = trackingTargets.split(',');
    let lastSent = 0;
    const watch = navigator.geolocation.watchPosition(position => {
      if (Date.now() - lastSent < 5000) return;
      lastSent = Date.now();
      const point = { lat: position.coords.latitude, lng: position.coords.longitude };
      Promise.all(ids.map(id => api(`/api/trace/${id}`, { method: 'POST', body: JSON.stringify(point) })))
        .catch(err => setError(err.message));
    }, error => {
      if (error.code === 1) { setTracking(false); setError('Разрешите доступ к геопозиции для отслеживания'); }
      else setError('Не удалось получить геопозицию. Отслеживание продолжится при восстановлении сигнала');
    },
    { enableHighAccuracy: true, maximumAge: 5000, timeout: 15000 });
    return () => navigator.geolocation.clearWatch(watch);
  }, [tracking, trackingTargets]);
  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 15000);
    return () => window.clearInterval(timer);
  }, []);
  async function act(fn, success) {
    setBusy(true); setError(''); setNotice('');
    try { const result = await fn(); if (success) setNotice(success); await refresh(user); return result; }
    catch (err) { setError(err.message); if (err.detail?.total) { setQuote({ total: err.detail.total, tariffId: err.detail.tariffId }); orderKey.current = crypto.randomUUID(); } return null; }
    finally { setBusy(false); }
  }
  const quoteBody = () => tab === 'taxi' ? { type: 'taxi', start, end } : { type: 'food', end, restaurantId, items: lines };
  async function getQuote() {
    if (end.lat === '' || (tab === 'taxi' && start.lat === '')) { setError('Выберите точки из результатов поиска или на карте'); return; }
    await act(async () => { setQuote(await api('/api/quotes', { method: 'POST', body: JSON.stringify(quoteBody()) })); orderKey.current = crypto.randomUUID(); }, 'Стоимость рассчитана');
  }
  async function createOrder() {
    const result = await act(() => api('/api/orders', { method: 'POST', headers: { 'Idempotency-Key': orderKey.current }, body: JSON.stringify({ ...quoteBody(), quotedTotal: quote.total, tariffId: quote.tariffId }) }), 'Заказ оформлен');
    if (result) { setQuote(null); setCart({}); orderKey.current = crypto.randomUUID(); setTab('history'); }
  }
  async function pickMap(latlng) {
    const target = tab === 'taxi' ? mapTarget : 'end';
    const point = { address: `Точка на карте (${latlng.lat.toFixed(5)}, ${latlng.lng.toFixed(5)})`, lat: latlng.lat, lng: latlng.lng };
    if (tab === 'scooter') { setParkingPoint(point); return; }
    const version = ++mapPickVersion.current[target];
    if (target === 'start') setStart(point); else setEnd(point);
    if (tab === 'taxi' && target === 'start' && end.lat === '') setMapTarget('end');
    setQuote(null);
    try {
      const named = await api(`/api/reverse-geocode?lat=${latlng.lat}&lng=${latlng.lng}`);
      if (mapPickVersion.current[target] === version) {
        if (target === 'start') setStart(named); else setEnd(named);
      }
    } catch { /* Coordinates remain usable. */ }
  }
  function adjustCart(id, delta) { setQuote(null); setCart(previous => ({ ...previous, [id]: Math.max(0, (previous[id] || 0) + delta) })); }
  function selectRestaurant(id) {
    if (restaurantId !== id && Object.values(cart).some(Boolean) && !window.confirm('Заменить корзину блюдами другого заведения?')) return;
    setRestaurantId(id); setFoodCategory(''); setCart({}); setQuote(null);
  }
  async function status(order, next) { await act(() => api(`/api/orders/${order.id}/status`, { method: 'PATCH', body: JSON.stringify({ status: next }) }), 'Статус обновлён'); }
  async function sendPosition(performerId) {
    await act(async () => {
      if (!navigator.geolocation) throw new Error('Геолокация недоступна в этом браузере');
      const position = await new Promise((resolve, reject) => navigator.geolocation.getCurrentPosition(resolve,
        () => reject(new Error('Разрешите доступ к геопозиции и повторите действие')),
        { enableHighAccuracy: true, timeout: 10000 }));
      return api(`/api/trace/${performerId}`, { method: 'POST', body: JSON.stringify({ lat: position.coords.latitude, lng: position.coords.longitude }) });
    }, 'Положение передано клиенту');
  }
  if (booting) return <div className="splash">YaGo · загружаем город…</div>;
  if (!user) return <Auth onSuccess={identity => { setUser(identity); setProfile({ fullName: identity.full_name, phone: identity.phone || '' }); refresh(identity); }} />;
  return <div className="shell">
    <header className="header"><div className="brand"><span className="brand-mark">Я</span><span>YaGo</span><small>Астана</small></div><nav className="nav" aria-label="Основная навигация">{nav.map(([id, label, glyph]) => <button key={id} type="button" className={tab === id ? 'nav-item active' : 'nav-item'} onClick={() => { setTab(id); setError(''); setQuote(null); }}><span aria-hidden="true">{glyph}</span>{label}</button>)}{(staff || performer) && <button type="button" className={tab === 'office' ? 'nav-item active' : 'nav-item'} onClick={() => setTab('office')}>◫ Кабинет</button>}</nav><div className="header-user"><span>{user.full_name}</span><i className={connected ? 'connection on' : 'connection'} title={connected ? 'Связь установлена' : 'Переподключение'} /></div></header>
    {error && <div className="notice error global-notice" role="alert">{error}<button type="button" onClick={() => setError('')} aria-label="Закрыть">×</button></div>}
    {notice && <div className="notice success global-notice" role="status">{notice}<button type="button" onClick={() => setNotice('')} aria-label="Закрыть">×</button></div>}
    {!connected && <div className="offline-banner">Связь с обновлениями потеряна. <button type="button" onClick={() => refresh(user)}>Обновить данные</button></div>}
    {['taxi', 'food', 'scooter'].includes(tab) && <main className="workspace"><aside className="service-panel"><p className="eyebrow">Ваш маршрут по городу</p><h1>{tab === 'taxi' ? 'Такси' : tab === 'food' ? 'Доставка еды' : 'Электросамокаты'}</h1><p className="muted intro">{tab === 'taxi' ? 'Укажите точки поездки — покажем маршрут и стоимость.' : tab === 'food' ? 'Выберите заведение, блюда и адрес доставки.' : 'Выберите самокат на карте и забронируйте на 10 минут.'}</p>
      {tab === 'taxi' && <Card title="Маршрут"><p className="hint">Выберите точки на карте или найдите адреса ниже.</p><AddressField label="Откуда" point={start} onChange={value => { mapPickVersion.current.start++; setStart(value); setQuote(null); }} /><AddressField label="Куда" point={end} onChange={value => { mapPickVersion.current.end++; setEnd(value); setQuote(null); }} /><Button onClick={getQuote} disabled={busy}>Рассчитать поездку</Button></Card>}
      {tab === 'food' && <><Card title="Заведения"><Field label="Поиск заведения или кухни" value={foodSearch} onChange={e => setFoodSearch(e.target.value)} placeholder="Название или кухня" />{visibleRestaurants.length ? visibleRestaurants.map(place => <button className={restaurantId === place.id ? 'restaurant-option selected' : 'restaurant-option'} key={place.id} type="button" onClick={() => selectRestaurant(place.id)}><strong>{place.name}</strong><span>{place.cuisine} · {place.address}</span></button>) : <p className="empty">По вашему запросу заведений нет.</p>}</Card>
        {restaurant && <Card title={`Меню · ${restaurant.name}`}><label className="field"><span>Категория блюд</span><select value={foodCategory} onChange={e => setFoodCategory(e.target.value)}><option value="">Все категории</option>{categories.map(category => <option value={category} key={category}>{category}</option>)}</select></label><div className="menu-list">{visibleMenu.length ? visibleMenu.map(item => <div className="menu-row" key={item.id}><div><strong>{item.name}</strong><small>{item.category}{!item.is_available && ' · сейчас нет в наличии'}</small><span>{money(item.price)}</span></div><div className="quantity"><button type="button" onClick={() => adjustCart(item.id, -1)} aria-label={`Убрать ${item.name}`} disabled={!cart[item.id]}>−</button><b>{cart[item.id] || 0}</b><button type="button" onClick={() => adjustCart(item.id, 1)} aria-label={`Добавить ${item.name}`} disabled={!item.is_available}>+</button></div></div>) : <p className="empty">В этой категории блюд пока нет.</p>}</div></Card>}
        {lines.length > 0 && <Card title="Корзина"><p>{lines.reduce((count, line) => count + line.quantity, 0)} позиции · один ресторан</p><AddressField label="Адрес доставки" point={end} onChange={value => { mapPickVersion.current.end++; setEnd(value); setQuote(null); }} /><Button onClick={getQuote} disabled={busy}>Рассчитать доставку</Button></Card>}</>}
      {quote && ['taxi', 'food'].includes(tab) && <Card title="Ваш заказ" className="quote-card"><div className="quote-total"><span>К оплате</span><strong>{money(quote.total)}</strong></div>{quote.discount > 0 && <p className="muted">Студенческая скидка: −{money(quote.discount)}</p>}{quote.distanceMeters != null && <p className="muted">{(quote.distanceMeters / 1000).toFixed(1)} км · около {Math.ceil(quote.durationSeconds / 60)} мин</p>}{quote.delivery != null && <p className="muted">Блюда {money(quote.subtotal)} · доставка {money(quote.delivery)}</p>}<p className="hint">Оплата учебная; итог проверяет сервер.</p><Button onClick={createOrder} disabled={busy}>{busy ? 'Оформляем…' : 'Подтвердить заказ'}</Button></Card>}
      {tab === 'scooter' && <><Card title="Доступные рядом"><p className="muted">Выберите метку на карте или самокат из списка.</p>{scooters.filter(x => x.status === 'available').map(x => <button type="button" className={selectedScooter === x.id ? 'vehicle selected' : 'vehicle'} key={x.id} onClick={() => setSelectedScooter(x.id)}><strong>{x.code}</strong><span>Заряд {x.battery}%</span></button>)}{!scooters.some(x => x.status === 'available') && <p className="empty">Свободных самокатов нет.</p>}{vehicle?.status === 'available' && <Button disabled={busy} onClick={async () => { const result = await act(() => api('/api/scooters/reserve', { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: JSON.stringify({ scooterId: vehicle.id }) }), 'Самокат забронирован'); if (result) setSelectedScooter(''); }}>Забронировать {vehicle.code}</Button>}</Card>
        {activeReservation && <Card title={`Бронь · ${activeReservation.code}`}><p>До {date(activeReservation.expiresAt)}</p><p className="hint">QR-разблокировка в учебном режиме эмулируется.</p>{config?.demoMode && <Button variant="quiet" onClick={() => act(async () => { const result = await api(`/api/reservations/${activeReservation.id}/demo-qr`); setQrCode(result.qrCode); }, 'Демо-код получен')}>Показать демо-код</Button>}<Field label="Код с самоката" value={qrCode} onChange={e => setQrCode(e.target.value)} /><Button disabled={busy || !qrCode} onClick={() => act(() => api(`/api/reservations/${activeReservation.id}/start`, { method: 'POST', body: JSON.stringify({ qrCode }) }), 'Аренда началась')}>Начать аренду</Button></Card>}
        {activeRental && <Card title={`Аренда · ${activeRental.scooterCode}`}><p>Началась {date(activeRental.startedAt)}</p><p>Прошло {Math.max(1, Math.ceil((clock - new Date(activeRental.startedAt).getTime()) / 60000))} мин</p><p className="muted">Оценка: {money(Number(activeRental.tariff?.baseFare || 0) + Math.max(1, Math.ceil((clock - new Date(activeRental.startedAt).getTime()) / 60000)) * Number(activeRental.tariff?.pricePerMinute || 0))}</p><p className="hint">Для завершения выберите точку в зелёной зоне на карте. Итоговую стоимость определит сервер.</p>{parkingPoint.lat !== '' && <p className="hint">Парковка: {parkingPoint.address}</p>}<Button disabled={busy || parkingPoint.lat === ''} onClick={() => act(() => api(`/api/rentals/${activeRental.id}/finish`, { method: 'POST', body: JSON.stringify({ lat: parkingPoint.lat, lng: parkingPoint.lng }) }), 'Аренда завершена, учебная оплата проведена')}>Завершить аренду</Button></Card>}
        <Card title="Тариф"><p>{tariffs.find(x => x.service === 'scooter')?.name || 'Нет действующего тарифа'}</p><p className="muted">От {money(tariffs.find(x => x.service === 'scooter')?.baseFare)} + {money(tariffs.find(x => x.service === 'scooter')?.pricePerMinute)} / мин</p></Card></>}
      {activeOrders.length > 0 && <Card title="Активный заказ">{activeOrders.map(order => <div className="compact-order" key={order.id}><strong>{serviceName(order.type)}</strong><span>{names[order.status]}</span><small>{order.end.address}</small><b>{money(order.total)}</b></div>)}</Card>}
    </aside><section className="map-stage" aria-label="Карта Астаны"><div className="map-heading"><div><p className="eyebrow">Астана</p><h2>Город на ладони</h2></div>
      <div className="map-controls">
        {tab === 'taxi' && <div className="map-target" role="group" aria-label="Выбор точки на карте">
          <button type="button" aria-pressed={mapTarget === 'start'} onClick={() => setMapTarget('start')}>А · Откуда{start.lat !== '' && ' ✓'}</button>
          <button type="button" aria-pressed={mapTarget === 'end'} onClick={() => setMapTarget('end')}>Б · Куда{end.lat !== '' && ' ✓'}</button>
        </div>}
        <p className="map-hint" aria-live="polite">{tab === 'taxi' ? `Нажмите на карту, чтобы выбрать ${mapTarget === 'start' ? 'точку отправления' : 'точку назначения'}` : tab === 'food' ? 'Нажмите на карту, чтобы выбрать адрес доставки' : 'Нажмите на карту, чтобы выбрать место парковки'}</p>
      </div></div><MapContainer center={[51.129, 71.43]} zoom={13} scrollWheelZoom className="map"><TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url={import.meta.env.VITE_MAP_TILES_URL || 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'} /><MapClick onPick={pickMap} /><OrderMapLayers orders={activeOrders} tab={tab} />{quote?.geometry?.coordinates && <Polyline positions={quote.geometry.coordinates.map(([lng, lat]) => [lat, lng])} pathOptions={{ color: '#287443', weight: 5, opacity: .85 }} />}{tab === 'scooter' && zones.map(zone => <GeoJSON key={zone.id} data={zone.geometry} style={{ color: '#397a35', fillColor: '#aee06f', fillOpacity: .18, weight: 2 }} />)}{tab === 'scooter' && scooters.filter(x => x.status === 'available').map(x => <Marker key={x.id} position={[x.lat, x.lng]} icon={marker} eventHandlers={{ click: () => setSelectedScooter(x.id) }} />)}{start.lat !== '' && tab === 'taxi' && <Marker position={[start.lat, start.lng]} icon={startMarker} />}{tab !== 'scooter' && end.lat !== '' && <Marker position={[end.lat, end.lng]} icon={endMarker} />}{tab === 'scooter' && parkingPoint.lat !== '' && <Marker position={[parkingPoint.lat, parkingPoint.lng]} icon={marker} />}{tab === 'food' && restaurants.map(x => <Marker key={x.id} position={[x.lat, x.lng]} icon={marker} eventHandlers={{ click: () => selectRestaurant(x.id) }} />)}{activeOrders.filter(x => x.type === tab && x.performerPosition).map(x => <Marker key={x.id} position={[x.performerPosition.lat, x.performerPosition.lng]} icon={marker} />)}</MapContainer><div className="map-footer">Адреса: Nominatim · автомобильный маршрут: OSRM · карта: OpenStreetMap</div></section></main>}
    {tab === 'history' && <main className="page"><div className="page-title"><div><p className="eyebrow">Ваши операции</p><h1>История</h1></div><Button variant="quiet" onClick={() => refresh(user)}>{loading ? 'Обновляем…' : 'Обновить'}</Button></div><div className="history-grid"><Card title="Заказы">{orders.length ? orders.map(order => <div className="history-item" key={order.id}><div><strong>{serviceName(order.type)}</strong><small>{date(order.createdAt)}</small><p>{order.start.address} → {order.end.address}</p>{order.items.map((item, i) => <small key={i}>{item.name} × {item.quantity} · {money(item.unitPrice)}</small>)}</div><div><span className="badge">{names[order.status]}</span><b>{money(order.total)}</b>{order.discount > 0 && <small>Скидка {money(order.discount)}</small>}{order.status === 'pending' && ['taxi', 'food'].includes(order.type) && <Button variant="quiet" onClick={() => status(order, 'cancelled')}>Отменить</Button>}{order.status === 'completed' && ['taxi', 'food'].includes(order.type) && <Button variant="quiet" onClick={() => { const rating = Number(window.prompt('Оценка от 1 до 5')); if (rating >= 1 && rating <= 5) act(() => api(`/api/orders/${order.id}/review`, { method: 'POST', body: JSON.stringify({ rating }) }), 'Спасибо за отзыв'); }}>Оставить отзыв</Button>}</div></div>) : <p className="empty">Заказов пока нет. Выберите услугу, чтобы начать.</p>}</Card><Card title="Аренды самокатов">{rentals.length ? rentals.map(rental => <div className="history-item" key={rental.id}><div><strong>{rental.scooterCode}</strong><small>{date(rental.startedAt)}</small></div><div><span className="badge">{names[rental.status]}</span><b>{rental.total ? money(rental.total) : 'В пути'}</b></div></div>) : <p className="empty">Аренд пока нет.</p>}</Card></div></main>}
    {tab === 'profile' && <main className="page narrow"><p className="eyebrow">Личный кабинет</p><h1>Профиль</h1><Card title="Ваши данные"><Field label="Имя" value={profile.fullName} onChange={e => setProfile({ ...profile, fullName: e.target.value })} /><Field label="Телефон" value={profile.phone} onChange={e => setProfile({ ...profile, phone: e.target.value })} /><p className="muted">{user.email}</p><Button disabled={busy} onClick={async () => { const result = await act(() => api('/api/profile', { method: 'PATCH', body: JSON.stringify(profile) }), 'Профиль сохранён'); if (result) setUser({ ...user, full_name: profile.fullName, phone: profile.phone }); }}>Сохранить</Button></Card>
      <Card title="Двухфакторная защита"><p className="muted">{user.two_factor_enabled ? 'Включена. При входе нужен код приложения.' : 'Можно подключить приложение с одноразовыми кодами.'}</p>{!user.two_factor_enabled && !twoFactorSecret && <Button variant="quiet" onClick={() => act(async () => { const result = await api('/api/auth/2fa/setup', { method: 'POST' }); setTwoFactorSecret(result.secret); })}>Настроить</Button>}{twoFactorSecret && <p className="hint">Добавьте в приложение-аутентификатор секрет: <strong>{twoFactorSecret}</strong></p>}{(twoFactorSecret || user.two_factor_enabled) && <><Field label="Код приложения" value={twoFactorCode} onChange={e => setTwoFactorCode(e.target.value)} /><Button onClick={async () => { const result = await act(() => api(user.two_factor_enabled ? '/api/auth/2fa/disable' : '/api/auth/2fa/enable', { method: 'POST', body: JSON.stringify({ code: twoFactorCode }) }), 'Настройка защиты сохранена'); if (result) { setUser({ ...user, two_factor_enabled: !user.two_factor_enabled }); setTwoFactorSecret(''); setTwoFactorCode(''); } }}>{user.two_factor_enabled ? 'Отключить' : 'Включить'}</Button></>}</Card>
      <Card title="Студенческий статус"><p className="muted">{user.student_verified ? 'Подтверждён · скидка 10% на такси и доставку' : 'Статус не подтверждён'}</p>{config?.demoMode && !user.student_verified && <><p className="hint">Учебная проверка без внешнего провайдера. Демо-код: YAGO-STUDENT</p><Field label="Учебный код" value={studentCode} onChange={e => setStudentCode(e.target.value)} /><Button onClick={async () => { const result = await act(() => api('/api/auth/student/verify', { method: 'POST', body: JSON.stringify({ code: studentCode }) }), 'Статус подтверждён'); if (result) setUser({ ...user, student_verified: true }); }}>Подтвердить</Button></>}</Card>
      <Card title="Активные сессии">{sessions.map(session => <div className="session-row" key={session.id}><span>{date(session.created_at)} {session.current && '· текущая'}</span><Button variant="quiet" onClick={async () => { await act(() => api(`/api/auth/sessions/${session.id}`, { method: 'DELETE' }), 'Сессия завершена'); if (session.current) setUser(null); }}>Завершить</Button></div>)}</Card><Button variant="secondary" onClick={async () => { await act(() => api('/api/auth/logout', { method: 'POST' })); setUser(null); }}>Выйти</Button></main>}
    {tab === 'office' && (staff || performer) && <main className="page"><p className="eyebrow">Рабочее пространство</p><h1>{admin ? 'Администрирование' : staff ? 'Кабинет оператора' : 'Мои назначения'}</h1><div className="office-grid">{performer && !staff && trackedPerformers.length > 0 && <Button variant={tracking ? "secondary" : "primary"} onClick={() => setTracking(!tracking)}>{tracking ? "Остановить геотрекинг" : "Включить геотрекинг"}</Button>}<Card title={performer && !staff ? 'Назначенные заказы' : 'Заказы и назначения'}>{orders.length ? orders.map(order => { const next = !['taxi', 'food'].includes(order.type) ? undefined : staff ? (order.type === 'taxi' ? { pending: 'assigned' } : { pending: 'preparing', preparing: 'assigned' })[order.status] : (order.type === 'taxi' ? { assigned: 'accepted', accepted: 'arriving', arriving: 'in_progress', in_progress: 'completed' } : { assigned: 'accepted', accepted: 'picked_up', picked_up: 'completed' })[order.status]; return <div className="office-order" key={order.id}><div><strong>{serviceName(order.type)}</strong><small>{order.customer} · {names[order.status]}</small><p>{order.start.address} → {order.end.address}</p></div><div className="office-actions">{next && <Button disabled={busy} onClick={() => status(order, next)}>Следующий статус</Button>}{performer && !staff && order.performerId && !['completed', 'cancelled'].includes(order.status) && <Button variant="quiet" onClick={() => sendPosition(order.performerId)}>Передать мою позицию</Button>}</div></div>; }) : <p className="empty">Назначений пока нет.</p>}</Card>
      {staff && <>
        <Card title="Новое заведение"><Field label="Название" value={restaurantForm.name} onChange={e => setRestaurantForm({ ...restaurantForm, name: e.target.value })} /><Field label="Кухня" value={restaurantForm.cuisine} onChange={e => setRestaurantForm({ ...restaurantForm, cuisine: e.target.value })} /><AddressField label="Адрес заведения" point={restaurantForm.address} onChange={value => setRestaurantForm({ ...restaurantForm, address: value })} /><Button disabled={busy || restaurantForm.address.lat === ''} onClick={() => act(() => api('/api/operator/restaurants', { method: 'POST', body: JSON.stringify(restaurantForm) }), 'Заведение добавлено')}>Добавить заведение</Button>{restaurants.map(x => <div className="session-row" key={x.id}><span>{x.name}</span><Button variant="quiet" onClick={() => act(() => api(`/api/operator/restaurants/${x.id}/status`, { method: 'PATCH', body: JSON.stringify({ active: false }) }), 'Заведение архивировано')}>В архив</Button></div>)}</Card>
        <Card title="Парк самокатов">{scooters.map(x => <div className="session-row" key={x.id}><span>{x.code} · {x.battery}% · {x.status}</span>{!['reserved', 'in_use'].includes(x.status) && <select aria-label={`Состояние ${x.code}`} value={x.status} onChange={e => act(() => api(`/api/operator/scooters/${x.id}`, { method: 'PATCH', body: JSON.stringify({ status: e.target.value, battery: x.battery }) }), 'Состояние обновлено')}><option value="available">Доступен</option><option value="maintenance">Обслуживание</option><option value="blocked">Заблокирован</option></select>}</div>)}{['code', 'qrCode', 'lat', 'lng', 'battery'].map(field => <Field key={field} label={{ code: 'Номер', qrCode: 'QR-код', lat: 'Широта', lng: 'Долгота', battery: 'Заряд, %' }[field]} value={scooterForm[field]} onChange={e => setScooterForm({ ...scooterForm, [field]: e.target.value })} />)}<Button disabled={busy} onClick={() => act(() => api('/api/operator/scooters', { method: 'POST', body: JSON.stringify(scooterForm) }), 'Самокат добавлен')}>Добавить самокат</Button></Card>
        <ZoneManager zones={operatorZones} act={act} busy={busy} />
        <Card title="Добавить блюдо"><select aria-label="Заведение" value={restaurantId} onChange={e => setRestaurantId(e.target.value)}><option value="">Выберите заведение</option>{restaurants.map(x => <option value={x.id} key={x.id}>{x.name}</option>)}</select>{['name', 'category', 'price', 'description'].map(field => <Field key={field} label={{ name: 'Название', category: 'Категория', price: 'Цена, ₸', description: 'Описание' }[field]} value={menuForm[field]} onChange={e => setMenuForm({ ...menuForm, [field]: e.target.value })} />)}<Button disabled={!restaurantId || busy} onClick={() => act(() => api(`/api/operator/restaurants/${restaurantId}/menu`, { method: 'POST', body: JSON.stringify(menuForm) }), 'Блюдо добавлено')}>Добавить</Button></Card>
        <Card title="Редактировать меню"><p className="muted">Выберите заведение в карточке добавления блюда.</p>{restaurant?.menu.map(item => <div className="session-row" key={item.id}><span>{item.name}<small>{item.category} · {money(item.price)} · {item.is_available ? 'в наличии' : 'нет в наличии'}</small></span><Button variant="quiet" onClick={() => { setEditingMenuId(item.id); setMenuEditForm({ name: item.name, description: item.description || '', category: item.category, price: item.price, available: item.is_available }); }}>Изменить</Button></div>)}{!restaurant && <p className="empty">Заведение не выбрано.</p>}{editingMenuId && <><h3>Параметры блюда</h3>{['name', 'category', 'price', 'description'].map(field => <Field key={field} label={{ name: 'Название', category: 'Категория', price: 'Цена, ₸', description: 'Описание' }[field]} value={menuEditForm[field]} onChange={e => setMenuEditForm({ ...menuEditForm, [field]: e.target.value })} />)}<label className="field"><span>Наличие</span><select value={String(menuEditForm.available)} onChange={e => setMenuEditForm({ ...menuEditForm, available: e.target.value === 'true' })}><option value="true">В наличии</option><option value="false">Нет в наличии</option></select></label><Button disabled={busy} onClick={async () => { const result = await act(() => api(`/api/operator/menu/${editingMenuId}`, { method: 'PATCH', body: JSON.stringify(menuEditForm) }), 'Блюдо обновлено'); if (result) setEditingMenuId(''); }}>Сохранить блюдо</Button></>}</Card>
        <TariffManager tariffs={operatorTariffs} act={act} busy={busy} />
      </>}
      {admin && <>
        <Card title="Показатели"><div className="period"><Field label="С" type="date" value={period.from} onChange={e => setPeriod({ ...period, from: e.target.value })} /><Field label="По" type="date" value={period.to} onChange={e => setPeriod({ ...period, to: e.target.value })} /><Button variant="quiet" onClick={async () => { try { const params = new URLSearchParams(); if (period.from) params.set('from_at', new Date(`${period.from}T00:00:00+05:00`).toISOString()); if (period.to) params.set('to_at', new Date(new Date(`${period.to}T00:00:00+05:00`).getTime() + 86400000).toISOString()); periodQuery.current = params.size ? `?${params}` : ''; setAnalytics(await api(`/api/admin/analytics${periodQuery.current}`)); setError(''); } catch (err) { setError(err.message); } }}>Применить</Button></div><div className="metrics"><div><span>Заказы</span><strong>{analytics?.orders ?? '—'}</strong></div><div><span>Отмены</span><strong>{analytics?.cancellations ?? '—'}</strong></div><div><span>Учебная выручка</span><strong>{money(analytics?.revenue)}</strong></div><div><span>Среднее ожидание</span><strong>{analytics?.average_wait_minutes ?? '—'} мин</strong></div></div><p className="hint">Ожидание: от создания до принятия. Выручка: сумма успешных учебных оплат.</p></Card>
        <Card title="География заказов">{heatmap.length ? <MapContainer center={[51.129, 71.43]} zoom={12} className="heatmap"><TileLayer attribution='&copy; OpenStreetMap contributors' url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />{heatmap.map((point, i) => <CircleMarker key={i} center={[point.lat, point.lng]} radius={Math.min(25, 5 + point.count * 3)} pathOptions={{ color: '#40752f', fillColor: '#a6da6a', fillOpacity: .55 }} />)}</MapContainer> : <p className="empty">Заказов с координатами пока нет.</p>}</Card>
        <Card title="Пользователи и роли">{users.map(person => <div className="session-row" key={person.id}><span>{person.name}<small>{person.email} · {person.roles.join(', ')}</small></span><div className="role-actions"><select aria-label={`Изменить роль ${person.name}`} defaultValue="" onChange={e => { const [role, enabled] = e.target.value.split(':'); if (role) act(() => api(`/api/admin/users/${person.id}/role`, { method: 'PATCH', body: JSON.stringify({ role, enabled: enabled === 'add' }) }), 'Роль обновлена'); e.target.value = ''; }}><option value="">Роль…</option><option value="performer:add">Добавить исполнителя</option><option value="operator:add">Добавить оператора</option><option value="admin:add">Добавить администратора</option><option value="performer:remove">Убрать исполнителя</option><option value="operator:remove">Убрать оператора</option><option value="admin:remove">Убрать администратора</option></select><Button variant="quiet" onClick={async () => { setAdminSessionUser(person.id); await act(async () => setAdminSessions(await api(`/api/admin/users/${person.id}/sessions`))); }}>Сессии</Button></div></div>)}{adminSessionUser && <div><h2>Активные сессии</h2>{adminSessions.length ? adminSessions.map(session => <div className="session-row" key={session.id}><span>{date(session.createdAt)}</span><Button variant="quiet" onClick={async () => { const result = await act(() => api(`/api/admin/sessions/${session.id}`, { method: 'DELETE' }), 'Сессия завершена'); if (result) setAdminSessions(adminSessions.filter(x => x.id !== session.id)); }}>Завершить</Button></div>) : <p className="empty">Активных сессий нет.</p>}</div>}</Card>
        <Card title="Журнал входов">{loginEvents.map((event, i) => <div className="session-row" key={i}><span>{loginNames[event.action] || event.action}<small>{event.actor_email || (event.email_hash ? "Хеш адреса: " + event.email_hash.slice(0, 12) : "Адрес не указан")}</small></span><small>{date(event.created_at)}</small></div>)}</Card><Card title="Аудит">{audit.map((event, i) => <div className="session-row" key={i}><span>{event.action}{event.actor_email && <small>{event.actor_email}</small>}</span><small>{date(event.created_at)}</small></div>)}</Card>
      </>}
    </div></main>}
  </div>;
}
export default App;
