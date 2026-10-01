import { useEffect, useMemo, useState } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Polyline, CircleMarker } from 'react-leaflet';
import L from 'leaflet';

const defaultIcon = L.icon({
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
  iconSize: [25, 41],
  iconAnchor: [12, 41]
});

const formatCurrency = (value) => `${Number(value).toLocaleString('ru-RU')} ₸`;
const formatDistance = (meters) => meters < 1000
  ? `${meters} м`
  : `${(meters / 1000).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} км`;

const formatManeuver = ({ maneuver, modifier }) => {
  const actions = {
    depart: 'Старт',
    arrive: 'Прибытие',
    turn: 'Поворот',
    'end of road': 'На конце дороги',
    'new name': 'Продолжайте',
    continue: 'Продолжайте',
    merge: 'Въезд',
    fork: 'Развилка',
    roundabout: 'Круговое движение',
    rotary: 'Круговое движение'
  };
  const directions = {
    left: 'налево',
    right: 'направо',
    straight: 'прямо',
    'slight left': 'плавно налево',
    'slight right': 'плавно направо',
    'sharp left': 'резко налево',
    'sharp right': 'резко направо',
    uturn: 'разворот'
  };
  const action = actions[maneuver] || 'Продолжайте';
  return modifier && directions[modifier] ? `${action} ${directions[modifier]}` : action;
};

function App() {
  const [config, setConfig] = useState(null);
  const [restaurants, setRestaurants] = useState([]);
  const [orders, setOrders] = useState([]);
  const [couriers, setCouriers] = useState([]);
  const [routes, setRoutes] = useState({});
  const [routesLoading, setRoutesLoading] = useState(false);
  const [apiError, setApiError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState('connecting');
  const [selectedTab, setSelectedTab] = useState('home');
  const [selectedOrderType, setSelectedOrderType] = useState('food');
  const [selectedRestaurant, setSelectedRestaurant] = useState('r1');
  const [cart, setCart] = useState({});
  const [form, setForm] = useState({
    customer: 'Айгерим',
    startLat: 51.1694,
    startLng: 71.4491,
    endLat: 51.1705,
    endLng: 71.4308
  });

  useEffect(() => {
    let retryTimer;
    let connectTimer;
    let disposed = false;
    let socket;

    const loadDashboard = async () => {
      try {
        const [configResponse, restaurantsResponse, ordersResponse, couriersResponse] = await Promise.all([
          fetch('/api/config'),
          fetch('/api/restaurants'),
          fetch('/api/orders'),
          fetch('/api/couriers')
        ]);
        const responses = [configResponse, restaurantsResponse, ordersResponse, couriersResponse];
        if (responses.some(response => !response.ok)) throw new Error('Не удалось загрузить данные сервера');
        const [nextConfig, nextRestaurants, nextOrders, nextCouriers] = await Promise.all(responses.map(response => response.json()));
        if (disposed) return;
        setConfig(nextConfig);
        setRestaurants(nextRestaurants);
        setOrders(nextOrders);
        setCouriers(nextCouriers);
        setApiError('');
      } catch (error) {
        if (!disposed) setApiError(error.message || 'Сервер YaGo недоступен');
      }
    };

    const connect = () => {
      if (disposed) return;
      const socketUrl = new URL('/ws', window.location.href);
      socketUrl.protocol = socketUrl.protocol === 'https:' ? 'wss:' : 'ws:';
      socket = new WebSocket(socketUrl);
      socket.onopen = () => setConnectionStatus('connected');
      socket.onmessage = (message) => {
        try {
          const { event, data } = JSON.parse(message.data);
          if (event === 'orderCreated') setOrders(previous => [data, ...previous.filter(item => item.id !== data.id)]);
          if (event === 'orderStatusUpdated') setOrders(previous => previous.map(item => item.id === data.id ? data : item));
          if (event === 'driverMoved') setCouriers(previous => previous.map(item => item.id === data.id ? data : item));
        } catch {
          setApiError('Получено некорректное обновление сервера');
        }
      };
      socket.onclose = () => {
        setConnectionStatus('disconnected');
        if (!disposed) retryTimer = window.setTimeout(connect, 2000);
      };
      socket.onerror = () => socket.close();
    };

    loadDashboard();
    connectTimer = window.setTimeout(connect, 0);
    return () => {
      disposed = true;
      window.clearTimeout(connectTimer);
      window.clearTimeout(retryTimer);
      socket?.close();
    };
  }, []);

  const selectedRestaurantData = useMemo(() =>
    restaurants.find(item => item.id === selectedRestaurant) || restaurants[0],
    [restaurants, selectedRestaurant]
  );
  const visibleOrders = useMemo(() => {
    if (selectedTab === 'food' || selectedTab === 'taxi') {
      return orders.filter(order => order.type === selectedTab);
    }
    if (selectedTab === 'admin') return orders;
    return orders.filter(order => !['completed', 'cancelled'].includes(order.status));
  }, [orders, selectedTab]);
  useEffect(() => {
    const missingRoutes = visibleOrders.filter(order => !Object.hasOwn(routes, order.id));
    if (missingRoutes.length === 0) {
      setRoutesLoading(false);
      return;
    }

    let disposed = false;
    setRoutesLoading(true);
    Promise.all(missingRoutes.map(async order => {
      const query = new URLSearchParams({
        startLat: String(order.start.lat),
        startLng: String(order.start.lng),
        endLat: String(order.end.lat),
        endLng: String(order.end.lng)
      });
      try {
        const response = await fetch(`/api/routes?${query}`);
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || 'Маршрут не найден');
        return [order.id, result];
      } catch (error) {
        return [order.id, { error: error.message || 'Маршрут не найден' }];
      }
    })).then(results => {
      if (disposed) return;
      setRoutes(previous => ({ ...previous, ...Object.fromEntries(results) }));
      setRoutesLoading(false);
    });
    return () => {
      disposed = true;
    };
  }, [visibleOrders, routes]);
  const cartLines = useMemo(() => restaurants.flatMap(restaurant =>
    restaurant.menu
      .filter(item => restaurant.id === selectedRestaurant && cart[item.id])
      .map(item => ({ ...item, quantity: cart[item.id] }))
  ), [restaurants, selectedRestaurant, cart]);
  const cartTotal = cartLines.reduce((total, item) => total + item.price * item.quantity, 0);
  const routeFailureCount = visibleOrders.filter(order => routes[order.id]?.error).length;
  const routedOrderCount = visibleOrders.filter(order => routes[order.id]?.geometry).length;

  const retryFailedRoutes = () => {
    setRoutes(previous => {
      const next = { ...previous };
      visibleOrders.filter(order => next[order.id]?.error).forEach(order => delete next[order.id]);
      return next;
    });
  };

  const handleCreateOrder = async (event) => {
    event.preventDefault();
    setIsSubmitting(true);
    setApiError('');
    const payload = {
      customer: form.customer.trim(),
      type: selectedOrderType,
      restaurantId: selectedOrderType === 'food' ? selectedRestaurant : null,
      items: selectedOrderType === 'food'
        ? cartLines.map(item => ({ menuItemId: item.id, quantity: item.quantity }))
        : [],
      start: { lat: Number(form.startLat), lng: Number(form.startLng) },
      end: { lat: Number(form.endLat), lng: Number(form.endLng) }
    };

    try {
      const response = await fetch('/api/orders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Не удалось создать заказ');
      setOrders(previous => [result, ...previous.filter(item => item.id !== result.id)]);
      setCart({});
    } catch (error) {
      setApiError(error.message || 'Не удалось создать заказ');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleOrderStatus = async (order) => {
    const nextStatus = { pending: 'assigned', assigned: 'in_progress', in_progress: 'completed' }[order.status];
    if (!nextStatus) return;
    try {
      const response = await fetch(`/api/orders/${order.id}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: nextStatus })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Не удалось обновить заказ');
      setOrders(previous => previous.map(item => item.id === result.id ? result : item));
      setApiError('');
    } catch (error) {
      setApiError(error.message || 'Не удалось обновить заказ');
    }
  };

  const mapCenter = [51.1694, 71.4491];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-block">
          <div className="brand-logo">Y</div>
          <div>
            <p className="eyebrow">Суперприложение</p>
            <h1>YaGo</h1>
          </div>
        </div>

        <nav className="nav-tabs">
          {[
            ['home', 'Главная'],
            ['food', 'Еда'],
            ['taxi', 'Такси'],
            ['admin', 'Админка']
          ].map(([id, label]) => (
            <button
              key={id}
              className={selectedTab === id ? 'nav-button active' : 'nav-button'}
              onClick={() => {
                setSelectedTab(id);
                if (id === 'food' || id === 'taxi') setSelectedOrderType(id);
              }}
            >
              {label}
            </button>
          ))}
        </nav>

        <section className="card">
          <h3>Создать заказ</h3>
          <form id="order-form" onSubmit={handleCreateOrder}>
          <div className="segmented">
            <button type="button" className={selectedOrderType === 'food' ? 'chip active' : 'chip'} onClick={() => setSelectedOrderType('food')}>Еда</button>
            <button type="button" className={selectedOrderType === 'taxi' ? 'chip active' : 'chip'} onClick={() => setSelectedOrderType('taxi')}>Такси</button>
          </div>

          <label>
            Клиент
            <input value={form.customer} onChange={(e) => setForm({ ...form, customer: e.target.value })} />
          </label>

          {selectedOrderType === 'food' ? (
            <label>
              Ресторан
              <select value={selectedRestaurant} onChange={(event) => {
                setSelectedRestaurant(event.target.value);
                setCart({});
              }}>
                {restaurants.map((restaurant) => (
                  <option key={restaurant.id} value={restaurant.id}>{restaurant.name}</option>
                ))}
              </select>
            </label>
          ) : null}

          {selectedOrderType === 'food' ? (
            <div className="cart-summary">
              <h4>Корзина</h4>
              {cartLines.length ? cartLines.map(item => (
                <div className="cart-line" key={item.id}>
                  <span>{item.name}</span>
                  <div className="quantity-control">
                    <button type="button" aria-label={`Уменьшить ${item.name}`} onClick={() => setCart(previous => {
                      const next = { ...previous };
                      if (next[item.id] <= 1) delete next[item.id];
                      else next[item.id] -= 1;
                      return next;
                    })}>−</button>
                    <span>{item.quantity}</span>
                    <button type="button" aria-label={`Добавить ${item.name}`} onClick={() => setCart(previous => ({ ...previous, [item.id]: previous[item.id] + 1 }))}>+</button>
                  </div>
                  <strong>{formatCurrency(item.price * item.quantity)}</strong>
                </div>
              )) : <p className="empty-cart">Выберите блюда в меню</p>}
              <div className="cart-total"><span>Итого</span><strong>{formatCurrency(cartTotal)}</strong></div>
            </div>
          ) : <p className="tariff-note">Демо-тариф такси · 2 800 ₸</p>}

          <div className="two-column">
            <label>
              Lat A
              <input type="number" step="0.0001" value={form.startLat} onChange={(e) => setForm({ ...form, startLat: e.target.value })} />
            </label>
            <label>
              Lng A
              <input type="number" step="0.0001" value={form.startLng} onChange={(e) => setForm({ ...form, startLng: e.target.value })} />
            </label>
          </div>

          <div className="two-column">
            <label>
              Lat B
              <input type="number" step="0.0001" value={form.endLat} onChange={(e) => setForm({ ...form, endLat: e.target.value })} />
            </label>
            <label>
              Lng B
              <input type="number" step="0.0001" value={form.endLng} onChange={(e) => setForm({ ...form, endLng: e.target.value })} />
            </label>
          </div>

          <button className="primary-button" type="submit" form="order-form" disabled={isSubmitting || (selectedOrderType === 'food' && cartLines.length === 0)}>
            {isSubmitting ? 'Сохраняем…' : 'Создать заказ'}
          </button>
          </form>
        </section>

      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div>
            <p className="eyebrow">Город</p>
            <h2>{config?.city || 'Астана'}</h2>
          </div>
          <div className={`status-pill ${connectionStatus === 'connected' ? 'success' : 'warning'}`}>
            <span className="connection-dot" />
            {connectionStatus === 'connected' ? 'Синхронизация включена' : 'Нет соединения'}
          </div>
        </header>

        {apiError ? <div className="api-alert" role="alert">{apiError}</div> : null}

        <div className={`route-status ${routeFailureCount ? 'failed' : ''}`} role="status">
          <span>
            {routeFailureCount
              ? `Не построено дорожных маршрутов: ${routeFailureCount}`
              : routesLoading
                ? 'Рассчитываем путь по улицам…'
                : `Построено дорожных маршрутов: ${routedOrderCount}`}
          </span>
          <small>OSRM · автомобильные дороги</small>
          {routeFailureCount ? <button type="button" onClick={retryFailedRoutes}>Повторить</button> : null}
        </div>

        <div className="map-card">
          <MapContainer center={mapCenter} zoom={13} scrollWheelZoom className="map-root">
            <TileLayer
              attribution='&copy; OpenStreetMap contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />

            {restaurants.map((restaurant) => (
              <Marker key={restaurant.id} position={[restaurant.lat, restaurant.lng]} icon={defaultIcon}>
                <Popup>
                  <strong>{restaurant.name}</strong><br />
                  {restaurant.cuisine}<br />
                  {restaurant.eta} мин до доставки
                </Popup>
              </Marker>
            ))}

            {couriers.map((courier) => (
              <CircleMarker key={courier.id} center={[courier.lat, courier.lng]} radius={12} pathOptions={{ color: courier.role === 'driver' ? '#7c3aed' : '#0ea5e9', fillColor: courier.role === 'driver' ? '#7c3aed' : '#0ea5e9', fillOpacity: 0.85 }}>
                <Popup>
                  {courier.name} · {courier.role === 'driver' ? 'водитель такси' : 'курьер'}
                </Popup>
              </CircleMarker>
            ))}

            {visibleOrders.map((order) => {
              const route = routes[order.id];
              if (!route?.geometry?.coordinates) return null;
              return (
                <Polyline
                  key={order.id}
                  positions={route.geometry.coordinates.map(([lng, lat]) => [lat, lng])}
                  pathOptions={{ color: order.type === 'taxi' ? '#8b5cf6' : '#f97316', weight: 5, opacity: 0.85 }}
                >
                  <Popup>
                    <strong>{order.customer}</strong><br />
                    {route.distanceKm} км · около {route.durationMinutes} мин
                    <ol className="route-steps">
                      {(route.steps || []).map((step, index) => (
                        <li key={`${step.name}-${index}`}>
                          <span>{formatManeuver(step)}</span>
                          <strong>{step.name}</strong>
                          <small>{formatDistance(step.distanceMeters)}</small>
                        </li>
                      ))}
                    </ol>
                  </Popup>
                </Polyline>
              );
            })}
          </MapContainer>
        </div>

        <section className="stats-grid">
          <div className="metric">
            <span>Активные заказы</span>
            <strong>{visibleOrders.filter(order => !['completed', 'cancelled'].includes(order.status)).length}</strong>
          </div>
          <div className="metric">
            <span>Курьеры онлайн</span>
            <strong>{couriers.filter(c => c.status === 'available').length}</strong>
          </div>
          <div className="metric">
            <span>Средняя доставка</span>
            <strong>18-25 мин</strong>
          </div>
          <div className="metric">
            <span>Город</span>
            <strong>Астана</strong>
          </div>
        </section>

        <section className="content-grid">
          <div className="card">
            <h3>Рестораны</h3>
            {selectedRestaurantData ? (
              <div className="restaurant-card">
                <div className="restaurant-header">
                  <div>
                    <h4>{selectedRestaurantData.name}</h4>
                    <p>{selectedRestaurantData.cuisine}</p>
                  </div>
                  <span className="badge">{selectedRestaurantData.eta} мин</span>
                </div>
                <ul>
                  {(selectedRestaurantData.menu || []).map((item) => (
                    <li key={item.id}>
                      <span>
                        {item.name}
                        <small>{item.category}</small>
                      </span>
                      <div className="menu-price-control">
                        <strong>{formatCurrency(item.price)}</strong>
                        <button type="button" aria-label={`Добавить ${item.name} в корзину`} onClick={() => setCart(previous => ({ ...previous, [item.id]: (previous[item.id] || 0) + 1 }))}>+</button>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>

          <div className="card">
            <h3>Исполнители</h3>
            <ul className="performer-list">
              {couriers.map(courier => (
                <li key={courier.id}>
                  <span>
                    <strong>{courier.name}</strong>
                    <small>{courier.role === 'driver' ? 'Водитель' : 'Курьер'}</small>
                  </span>
                  <span className={`performer-status ${courier.status}`}>
                    {courier.status === 'available' ? 'Свободен' : 'Занят'}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="card orders-card">
          <h3>{{ home: 'Активные заказы', food: 'Заказы еды', taxi: 'Заказы такси', admin: 'Все заказы' }[selectedTab]}</h3>
          <div className="orders-list">
            {visibleOrders.length === 0 ? <p className="orders-empty">Заказов пока нет</p> : null}
            {visibleOrders.map((order) => (
              <div key={order.id} className="order-row">
                <div>
                  <strong>{order.customer}</strong>
                  <span>
                    {order.type === 'food' ? 'Доставка еды' : 'Такси'}
                    {order.items?.length ? ` · ${order.items.map(item => `${item.name} × ${item.quantity}`).join(', ')}` : ''}
                  </span>
                  {routes[order.id]?.geometry ? (
                    <small className="route-summary">{routes[order.id].distanceKm} км · {routes[order.id].durationMinutes} мин по дорогам</small>
                  ) : null}
                  {routes[order.id]?.steps?.length ? (
                    <details className="route-details">
                      <summary>Улицы маршрута · {routes[order.id].steps.length}</summary>
                      <ol>
                        {routes[order.id].steps.map((step, index) => (
                          <li key={`${step.name}-${index}`}>
                            <span>{formatManeuver(step)}</span>
                            <strong>{step.name}</strong>
                            <small>{formatDistance(step.distanceMeters)}</small>
                          </li>
                        ))}
                      </ol>
                    </details>
                  ) : null}
                </div>
                <div className={`status-tag status-${order.status}`}>
                  {{ pending: 'Новый', assigned: 'Назначен', in_progress: 'В пути', completed: 'Завершён', cancelled: 'Отменён' }[order.status] || order.status}
                </div>
                <div className="order-total">{formatCurrency(order.total)}</div>
                {!['completed', 'cancelled'].includes(order.status) ? (
                  <button className="order-action" onClick={() => handleOrderStatus(order)}>
                    {{ pending: 'Назначить', assigned: 'Начать поездку', in_progress: 'Завершить' }[order.status]}
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}

export default App;
