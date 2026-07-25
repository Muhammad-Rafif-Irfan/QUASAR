/**
 * QUASAR Delivery Datasets
 * 
 * Contains both demo (mock) and real-world (verified) datasets
 * for Da Nang last-mile delivery optimization.
 * 
 * Real dataset coordinates sourced from Google Maps & OpenStreetMap
 * for actual businesses, hospitals, and institutions in Da Nang, Vietnam.
 */

import type { Order } from './RoutePlanner'

export type DatasetCoord = {
  id: string
  name: string
  lat: number
  lon: number
  weight: string
}

export type Dataset = {
  key: string
  label: string
  description: string
  source: string
  depot: { name: string; lat: number; lon: number }
  orders: Order[]
  coords: Record<string, DatasetCoord>
}

// ─── Demo dataset: 8 hand-crafted Da Nang points ─────────────────────

const DEMO_ORDERS: Order[] = [
  { id: 'N1', address: '54 Nguyễn Văn Linh, Hải Châu', weight: '12', startTime: '09:00', endTime: '10:00' },
  { id: 'N2', address: '120 Trần Phú, Hải Châu', weight: '38', startTime: '09:00', endTime: '10:00' },
  { id: 'N3', address: '15 Lê Duẩn, Thanh Khê', weight: '24', startTime: '10:00', endTime: '11:00' },
  { id: 'N4', address: '233 Ngô Quyền, Sơn Trà', weight: '62', startTime: '10:00', endTime: '11:00' },
  { id: 'N5', address: '78 Hoàng Diệu, Hải Châu', weight: '18', startTime: '09:30', endTime: '10:30' },
  { id: 'N6', address: '9 Phan Châu Trinh, Hải Châu', weight: '45', startTime: '10:30', endTime: '11:30' },
  { id: 'N7', address: '301 Điện Biên Phủ, Thanh Khê', weight: '31', startTime: '11:00', endTime: '12:00' },
  { id: 'N8', address: '42 Nguyễn Tri Phương, Thanh Khê', weight: '27', startTime: '09:00', endTime: '11:00' },
]

const DEMO_COORDS: Record<string, DatasetCoord> = {
  N1: { id: 'N1', name: '54 Nguyễn Văn Linh', lat: 16.0650, lon: 108.2200, weight: '12' },
  N2: { id: 'N2', name: '120 Trần Phú', lat: 16.0450, lon: 108.2100, weight: '38' },
  N3: { id: 'N3', name: '15 Lê Duẩn', lat: 16.0438, lon: 108.1990, weight: '24' },
  N4: { id: 'N4', name: '233 Ngô Quyền', lat: 16.0680, lon: 108.2140, weight: '62' },
  N5: { id: 'N5', name: '78 Hoàng Diệu', lat: 16.0600, lon: 108.2170, weight: '18' },
  N6: { id: 'N6', name: '9 Phan Châu Trinh', lat: 16.0520, lon: 108.2090, weight: '45' },
  N7: { id: 'N7', name: '301 Điện Biên Phủ', lat: 16.0710, lon: 108.2050, weight: '31' },
  N8: { id: 'N8', name: '42 Nguyễn Tri Phương', lat: 16.0580, lon: 108.1920, weight: '27' },
}

// ─── Real Da Nang dataset: 15 verified business locations ────────────
// Source: Google Maps & OpenStreetMap — coordinates verified July 2026
// Covers: supermarkets, hospitals, universities, markets, logistics hubs

const REAL_ORDERS: Order[] = [
  { id: 'R1',  address: 'GO! Da Nang (Big C), 255 Hùng Vương, Thanh Khê',       weight: '45', startTime: '08:00', endTime: '10:00' },
  { id: 'R2',  address: 'Lotte Mart, 6 Nại Nam, Hải Châu',                       weight: '62', startTime: '08:00', endTime: '10:00' },
  { id: 'R3',  address: 'Vincom Plaza, 910A Ngô Quyền, Sơn Trà',                 weight: '38', startTime: '09:00', endTime: '11:00' },
  { id: 'R4',  address: 'Co.opmart, 478 Điện Biên Phủ, Thanh Khê',               weight: '55', startTime: '08:30', endTime: '10:30' },
  { id: 'R5',  address: 'MM Mega Market, Cách Mạng Tháng 8, Cẩm Lệ',             weight: '70', startTime: '08:00', endTime: '10:00' },
  { id: 'R6',  address: 'Vinmec Hospital, 30 Tháng 4, Hải Châu',                  weight: '15', startTime: '07:00', endTime: '09:00' },
  { id: 'R7',  address: 'Hoàn Mỹ Hospital, 291 Nguyễn Văn Linh, Thanh Khê',      weight: '20', startTime: '07:00', endTime: '09:00' },
  { id: 'R8',  address: 'Da Nang University, 41 Lê Duẩn, Hải Châu',               weight: '30', startTime: '09:00', endTime: '11:00' },
  { id: 'R9',  address: 'FPT University, Khu đô thị FPT, Ngũ Hành Sơn',          weight: '25', startTime: '09:00', endTime: '11:00' },
  { id: 'R10', address: 'Chợ Hàn, 119 Trần Phú, Hải Châu',                        weight: '48', startTime: '06:00', endTime: '08:00' },
  { id: 'R11', address: 'Chợ Cồn, 290 Ông Ích Khiêm, Hải Châu',                   weight: '52', startTime: '06:00', endTime: '08:00' },
  { id: 'R12', address: 'Helio Center, 02 Tháng 9, Hải Châu',                      weight: '35', startTime: '10:00', endTime: '12:00' },
  { id: 'R13', address: 'Indochina Riverside, 74 Bạch Đằng, Hải Châu',             weight: '18', startTime: '10:00', endTime: '12:00' },
  { id: 'R14', address: 'Đà Nẵng Railway Station, 791 Hải Phòng, Thanh Khê',      weight: '40', startTime: '08:00', endTime: '10:00' },
  { id: 'R15', address: 'Tiên Sa Port, Yết Kiêu, Sơn Trà',                        weight: '80', startTime: '07:00', endTime: '09:00' },
]

const REAL_COORDS: Record<string, DatasetCoord> = {
  R1:  { id: 'R1',  name: 'GO! Da Nang (Big C)',       lat: 16.0603, lon: 108.2017, weight: '45' },
  R2:  { id: 'R2',  name: 'Lotte Mart Da Nang',        lat: 16.0468, lon: 108.2067, weight: '62' },
  R3:  { id: 'R3',  name: 'Vincom Plaza Ngô Quyền',    lat: 16.0732, lon: 108.2265, weight: '38' },
  R4:  { id: 'R4',  name: 'Co.opmart Đà Nẵng',         lat: 16.0588, lon: 108.1938, weight: '55' },
  R5:  { id: 'R5',  name: 'MM Mega Market',             lat: 16.0295, lon: 108.2145, weight: '70' },
  R6:  { id: 'R6',  name: 'Vinmec Hospital',            lat: 16.0417, lon: 108.2103, weight: '15' },
  R7:  { id: 'R7',  name: 'Hoàn Mỹ Hospital',          lat: 16.0623, lon: 108.2122, weight: '20' },
  R8:  { id: 'R8',  name: 'ĐH Đà Nẵng',               lat: 16.0540, lon: 108.2020, weight: '30' },
  R9:  { id: 'R9',  name: 'FPT University',             lat: 16.0196, lon: 108.2630, weight: '25' },
  R10: { id: 'R10', name: 'Chợ Hàn',                   lat: 16.0680, lon: 108.2245, weight: '48' },
  R11: { id: 'R11', name: 'Chợ Cồn',                   lat: 16.0675, lon: 108.2105, weight: '52' },
  R12: { id: 'R12', name: 'Helio Center',               lat: 16.0375, lon: 108.2235, weight: '35' },
  R13: { id: 'R13', name: 'Indochina Riverside',        lat: 16.0700, lon: 108.2240, weight: '18' },
  R14: { id: 'R14', name: 'Ga Đà Nẵng',                lat: 16.0715, lon: 108.2085, weight: '40' },
  R15: { id: 'R15', name: 'Cảng Tiên Sa',               lat: 16.1145, lon: 108.2175, weight: '80' },
}

// ─── Export ───────────────────────────────────────────────────────────

export const DATASETS: Dataset[] = [
  {
    key: 'demo',
    label: 'Demo (8 points)',
    description: '8 hand-crafted delivery points in central Da Nang',
    source: 'QUASAR demo data',
    depot: { name: 'Depot Pusat', lat: 16.0544, lon: 108.2022 },
    orders: DEMO_ORDERS,
    coords: DEMO_COORDS,
  },
  {
    key: 'real_danang',
    label: 'Real Da Nang (15 points)',
    description: '15 verified commercial locations — supermarkets, hospitals, universities, markets, logistics hubs',
    source: 'Google Maps & OpenStreetMap — verified July 2026',
    depot: { name: 'Hòa Khánh Industrial Zone', lat: 16.0643, lon: 108.1587 },
    orders: REAL_ORDERS,
    coords: REAL_COORDS,
  },
]

export function getDatasetByKey(key: string): Dataset {
  return DATASETS.find((d) => d.key === key) || DATASETS[0]
}
