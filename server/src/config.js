import dotenv from 'dotenv';

dotenv.config();

export const config = {
  port: Number(process.env.PORT || 4000),
  city: process.env.CITY || 'Астана',
  databaseUrl: process.env.DATABASE_URL || 'postgresql://postgres:[YOUR-PASSWORD]@db.ilefhpfvoidmdlhinbsy.supabase.co:5432/postgres',
  mapCenter: { lat: 51.1694, lng: 71.4491 },
  roles: ['client', 'courier', 'driver', 'restaurant', 'admin']
};
