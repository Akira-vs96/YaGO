import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import { createServer } from 'http';
import { Server } from 'socket.io';
import { Pool } from 'pg';
import { v4 as uuidv4 } from 'uuid';

dotenv.config();

const app = express();
const server = createServer(app);
const io = new Server(server, {
  cors: {
    origin: '*',
    methods: ['GET', 'POST']
  }
});

const PORT = process.env.PORT || 4000;
const databaseUrl = process.env.DATABASE_URL || 'postgresql://postgres:[YOUR-PASSWORD]@db.ilefhpfvoidmdlhinbsy.supabase.co:5432/postgres';

const pool = new Pool({
  connectionString: databaseUrl,
  ssl: { rejectUnauthorized: false }
});

app.use(cors());
app.use(express.json());

const astanaCenter = { lat: 51.1694, lng: 71.4491 };

const restaurants = [
  { id: 'r1', name: 'Bukhara', lat: 51.1676, lng: 71.4258, cuisine: 'Центральная Азия', eta: 18 },
  { id: 'r2', name: 'Caffe Luna', lat: 51.1734, lng: 71.4524, cuisine: 'Кофе и бургеры', eta: 22 },
  { id: 'r3', name: 'Sakura Wok', lat: 51.1612, lng: 71.4307, cuisine: 'Японская кухня', eta: 25 }
];

const menu = {
  r1: [
    { id: 'm1', name: 'Плов', price: 2200, category: 'Основное' },
    { id: 'm2', name: 'Самса с курицей', price: 750, category: 'Закуски' },
    { id: 'm3', name: 'Чай тан', price: 500, category: 'Напитки' }
  ],
  r2: [
    { id: 'm4', name: 'Бургер Classic', price: 1900, category: 'Бургеры' },
    { id: 'm5', name: 'Картофель фри', price: 700, category: 'Закуски' },
    { id: 'm6', name: 'Латте', price: 650, category: 'Напитки' }
  ],
  r3: [
    { id: 'm7', name: 'Рис с курицей', price: 2400, category: 'Основное' },
    { id: 'm8', name: 'Гункан', price: 990, category: 'Закуски' },
    { id: 'm9', name: 'Морс', price: 500, category: 'Напитки' }
  ]
};

const couriers = [
  { id: 'c1', name: 'Ержан', role: 'courier', lat: 51.1688, lng: 71.4441, status: 'available' },
  { id: 'c2', name: 'Дина', role: 'courier', lat: 51.175, lng: 71.4385, status: 'busy' },
  { id: 'c3', name: 'Тимур', role: 'driver', lat: 51.1636, lng: 71.4522, status: 'available' }
];

const orders = [
  {
    id: 'o-1001',
    customer: 'Айгерим',
    type: 'food',
    restaurantId: 'r1',
    status: 'assigned',
    total: 3400,
    start: { lat: 51.1689, lng: 71.4411 },
    end: { lat: 51.1708, lng: 71.4305 },
    courierId: 'c1',
    createdAt: new Date().toISOString()
  },
  {
    id: 'o-1002',
    customer: 'Нурсултан',
    type: 'taxi',
    status: 'in_progress',
    total: 2800,
    start: { lat: 51.1743, lng: 71.4296 },
    end: { lat: 51.1769, lng: 71.4498 },
    courierId: 'c3',
    createdAt: new Date().toISOString()
  }
];

app.get('/api/health', async (req, res) => {
  try {
    await pool.query('SELECT 1');
    res.json({ ok: true, service: 'YaGo API', db: 'connected', city: 'Astana' });
  } catch (error) {
    res.json({ ok: true, service: 'YaGo API', db: 'offline-demo', city: 'Astana', error: error.message });
  }
});

app.get('/api/config', (req, res) => {
  res.json({
    appName: 'YaGo',
    city: 'Астана',
    mapCenter: astanaCenter,
    supportedRoles: ['client', 'courier', 'driver', 'restaurant', 'admin'],
    featureFlags: ['food_delivery', 'taxi', 'scooter_tracking', 'admin_dashboard']
  });
});

app.get('/api/restaurants', (req, res) => {
  res.json(restaurants.map(restaurant => ({
    ...restaurant,
    menu: menu[restaurant.id] || []
  })));
});

app.get('/api/orders', (req, res) => {
  res.json(orders);
});

app.get('/api/couriers', (req, res) => {
  res.json(couriers);
});

app.post('/api/orders', (req, res) => {
  const body = req.body || {};
  const newOrder = {
    id: `o-${Date.now()}`,
    customer: body.customer || 'Клиент',
    type: body.type || 'food',
    restaurantId: body.restaurantId || 'r1',
    status: 'pending',
    total: body.total || 3200,
    start: body.start || astanaCenter,
    end: body.end || { lat: 51.1713, lng: 71.4412 },
    courierId: body.courierId || 'c1',
    createdAt: new Date().toISOString()
  };
  orders.unshift(newOrder);
  io.emit('orderCreated', newOrder);
  res.status(201).json(newOrder);
});

app.post('/api/orders/:id/status', (req, res) => {
  const { id } = req.params;
  const { status } = req.body;
  const order = orders.find(item => item.id === id);
  if (!order) {
    return res.status(404).json({ error: 'Order not found' });
  }
  order.status = status;
  io.emit('orderStatusUpdated', order);
  res.json(order);
});

app.post('/api/trace', (req, res) => {
  const { courierId, lat, lng } = req.body;
  const courier = couriers.find(item => item.id === courierId);
  if (!courier) {
    return res.status(404).json({ error: 'Courier not found' });
  }
  courier.lat = lat;
  courier.lng = lng;
  io.emit('driverMoved', courier);
  res.json(courier);
});

io.on('connection', (socket) => {
  socket.emit('welcome', { message: 'Connected to YaGo live tracking' });

  socket.on('joinRoom', (room) => {
    socket.join(room);
  });
});

server.listen(PORT, () => {
  console.log(`YaGo API is running on http://localhost:${PORT}`);
});
