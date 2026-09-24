import { orders as initialOrders, couriers } from '../data/mockData.js';

export const orders = [...initialOrders];

export function getOrders() {
  return orders;
}

export function createOrder(payload = {}) {
  const order = {
    id: `o-${Date.now()}`,
    customer: payload.customer || 'Клиент',
    type: payload.type || 'food',
    restaurantId: payload.restaurantId || 'r1',
    status: 'pending',
    total: payload.total || 3200,
    start: payload.start || { lat: 51.1694, lng: 71.4491 },
    end: payload.end || { lat: 51.1705, lng: 71.4308 },
    courierId: payload.courierId || 'c1',
    createdAt: new Date().toISOString()
  };
  orders.unshift(order);
  return order;
}

export function updateOrderStatus(orderId, status) {
  const order = orders.find(item => item.id === orderId);
  if (!order) {
    return null;
  }
  order.status = status;
  return order;
}

export function getCourierList() {
  return couriers;
}

export function updateCourierLocation(courierId, lat, lng) {
  const courier = couriers.find(item => item.id === courierId);
  if (!courier) {
    return null;
  }
  courier.lat = lat;
  courier.lng = lng;
  return courier;
}
