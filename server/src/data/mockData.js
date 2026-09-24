export const restaurants = [
  { id: 'r1', name: 'Bukhara', lat: 51.1676, lng: 71.4258, cuisine: 'Центральная Азия', eta: 18 },
  { id: 'r2', name: 'Caffe Luna', lat: 51.1734, lng: 71.4524, cuisine: 'Кофе и бургеры', eta: 22 },
  { id: 'r3', name: 'Sakura Wok', lat: 51.1612, lng: 71.4307, cuisine: 'Японская кухня', eta: 25 }
];

export const menu = {
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

export const couriers = [
  { id: 'c1', name: 'Ержан', role: 'courier', lat: 51.1688, lng: 71.4441, status: 'available' },
  { id: 'c2', name: 'Дина', role: 'courier', lat: 51.175, lng: 71.4385, status: 'busy' },
  { id: 'c3', name: 'Тимур', role: 'driver', lat: 51.1636, lng: 71.4522, status: 'available' }
];

export const orders = [
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
