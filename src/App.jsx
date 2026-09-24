import { useEffect, useMemo, useState } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Polyline, CircleMarker } from 'react-leaflet';
import L from 'leaflet';
import { io } from 'socket.io-client';

const defaultIcon = L.icon({
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
  iconSize: [25, 41],
  iconAnchor: [12, 41]
});

const restaurantColors = {
  r1: '#ff7a18',
  r2: '#5b8def',
  r3: '#34c759'
};

const formatCurrency = (value) => `${Number(value).toLocaleString('ru-RU')} ₸`;

function App() {
  const [config, setConfig] = useState(null);
  const [restaurants, setRestaurants] = useState([]);
  const [orders, setOrders] = useState([]);
  const [couriers, setCouriers] = useState([]);
  const [selectedTab, setSelectedTab] = useState('home');
  const [selectedOrderType, setSelectedOrderType] = useState('food');
  const [selectedRestaurant, setSelectedRestaurant] = useState('r1');
  const [form, setForm] = useState({
    customer: 'Айгерим',
    startLat: 51.1694,
    startLng: 71.4491,
    endLat: 51.1705,
    endLng: 71.4308,
    total: 3400
  });

  useEffect(() => {
    fetch('/api/config')
      .then(res => res.json())
      .then(setConfig)
      .catch(() => setConfig({ appName: 'YaGo', city: 'Астана' }));

    fetch('/api/restaurants')
      .then(res => res.json())
      .then(setRestaurants)
      .catch(() => setRestaurants([]));

    fetch('/api/orders')
      .then(res => res.json())
      .then(setOrders)
      .catch(() => setOrders([]));

    fetch('/api/couriers')
      .then(res => res.json())
      .then(setCouriers)
      .catch(() => setCouriers([]));

    const socket = io();
    socket.on('orderCreated', (order) => setOrders(prev => [order, ...prev]));
    socket.on('orderStatusUpdated', (order) => setOrders(prev => prev.map(item => item.id === order.id ? order : item)));
    socket.on('driverMoved', (courier) => setCouriers(prev => prev.map(item => item.id === courier.id ? courier : item)));

    return () => socket.disconnect();
  }, []);

  const selectedRestaurantData = useMemo(() =>
    restaurants.find(item => item.id === selectedRestaurant) || restaurants[0],
    [restaurants, selectedRestaurant]
  );

  const handleCreateOrder = async () => {
    const payload = {
      customer: form.customer,
      type: selectedOrderType,
      restaurantId: selectedRestaurant,
      total: Number(form.total),
      start: { lat: Number(form.startLat), lng: Number(form.startLng) },
      end: { lat: Number(form.endLat), lng: Number(form.endLng) }
    };

    const response = await fetch('/api/orders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (response.ok) {
      const order = await response.json();
      setOrders(prev => [order, ...prev]);
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
            <button key={id} className={selectedTab === id ? 'nav-button active' : 'nav-button'} onClick={() => setSelectedTab(id)}>
              {label}
            </button>
          ))}
        </nav>

        <section className="card">
          <h3>Создать заказ</h3>
          <div className="segmented">
            <button className={selectedOrderType === 'food' ? 'chip active' : 'chip'} onClick={() => setSelectedOrderType('food')}>Еда</button>
            <button className={selectedOrderType === 'taxi' ? 'chip active' : 'chip'} onClick={() => setSelectedOrderType('taxi')}>Такси</button>
          </div>

          <label>
            Клиент
            <input value={form.customer} onChange={(e) => setForm({ ...form, customer: e.target.value })} />
          </label>

          <label>
            Ресторан
            <select value={selectedRestaurant} onChange={(e) => setSelectedRestaurant(e.target.value)}>
              {restaurants.map((restaurant) => (
                <option key={restaurant.id} value={restaurant.id}>{restaurant.name}</option>
              ))}
            </select>
          </label>

          <label>
            Цена заказа
            <input type="number" value={form.total} onChange={(e) => setForm({ ...form, total: e.target.value })} />
          </label>

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

          <button className="primary-button" onClick={handleCreateOrder}>Проверить сценарий</button>
        </section>

        <section className="card">
          <h3>Роли в системе</h3>
          <ul className="role-list">
            {['client', 'courier', 'driver', 'restaurant', 'admin'].map(role => (
              <li key={role}>{role}</li>
            ))}
          </ul>
        </section>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div>
            <p className="eyebrow">Город</p>
            <h2>{config?.city || 'Астана'}</h2>
          </div>
          <div className="status-pill success">Live • карта</div>
        </header>

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

            {orders.map((order) => (
              <Polyline
                key={order.id}
                positions={[[order.start.lat, order.start.lng], [order.end.lat, order.end.lng]]}
                pathOptions={{ color: order.type === 'taxi' ? '#8b5cf6' : '#f97316', weight: 4, opacity: 0.75 }}
              />
            ))}
          </MapContainer>
        </div>

        <section className="stats-grid">
          <div className="metric">
            <span>Активные заказы</span>
            <strong>{orders.length}</strong>
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
                      <span>{item.name}</span>
                      <strong>{formatCurrency(item.price)}</strong>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>

          <div className="card">
            <h3>Бизнес-процессы</h3>
            <ol className="process-list">
              <li>Клиент выбирает ресторан рядом</li>
              <li>Формирует корзину и оформляет заказ</li>
              <li>Система назначает курьера или водителя</li>
              <li>В реальном времени отображает маршрут на карте</li>
              <li>Заказ завершается с оценкой и историей</li>
            </ol>
          </div>
        </section>

        <section className="card orders-card">
          <h3>Заказы в работе</h3>
          <div className="orders-list">
            {orders.map((order) => (
              <div key={order.id} className="order-row">
                <div>
                  <strong>{order.customer}</strong>
                  <span>{order.type === 'food' ? 'Доставка еды' : 'Такси'}</span>
                </div>
                <div className="status-tag">{order.status}</div>
                <div className="order-total">{formatCurrency(order.total)}</div>
              </div>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}

export default App;
