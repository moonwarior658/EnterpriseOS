// K0 fixtures only: no iiko IDs, Supply links, storage or network calls.
export type SaleStatus = 'ON_SALE' | 'OFF_SALE'
export type SaleMode = 'PORTION' | 'WEIGHT' | 'UNKNOWN'
export type DemoProduct = {
  id: string; name: string; sku: string; category: string; status: SaleStatus
  mode: SaleMode; weight: string | null; image: string | null
  description: string | null; composition: string | null; allergens: string | null
  storage: string | null; training: string | null
  prices: { point: string; from: string; to: string; amount: number; unit: string }[]
}
export const demoPoints = ['Демо · Центральная', 'Демо · Парковая']
export const demoDate = '2026-10-08'
const illustration = (color: string) => `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300"><rect width="400" height="300" fill="#f3ede4"/><ellipse cx="200" cy="235" rx="125" ry="24" fill="#ddd4c7"/><path d="M100 130h200v90q-100 40-200 0z" fill="${color}"/><ellipse cx="200" cy="130" rx="100" ry="40" fill="#faf1dc"/><circle cx="180" cy="120" r="20" fill="#b65054"/><circle cx="216" cy="135" r="16" fill="#b65054"/><path d="M200 105q20-35 45-18" stroke="#5b7960" stroke-width="8" fill="none"/></svg>`)}`
const names = ['Чизкейк с ягодами', 'Медовик', 'Наполеон', 'Эклер шоколадный', 'Торт «Прага»', 'Морковный торт', 'Тарт лимонный', 'Макарон малиновый', 'Пирожное «Картошка»', 'Торт «Прага»', 'Тирамису', 'Брауни', 'Печенье овсяное', 'Меренговый рулет']
export const demoProducts: DemoProduct[] = names.map((name, index) => ({
  id: `demo-${index + 1}`, name, sku: `DEMO-${String(index + 1).padStart(3, '0')}`,
  category: index === 4 || index === 9 ? 'Торты' : index > 10 ? 'Выпечка' : 'Десерты',
  status: index === 8 || index === 12 ? 'OFF_SALE' : 'ON_SALE',
  mode: index === 4 || index === 9 ? 'WEIGHT' : index === 6 ? 'UNKNOWN' : 'PORTION',
  weight: index === 6 ? null : index === 4 || index === 9 ? '1 кг · базовая единица' : `${120 + index * 5} г / порция`,
  image: index < 3 ? illustration(['#bc8c64', '#ca9c55', '#d6bb87'][index]) : null,
  description: index === 0 ? 'Нежный десерт на песочной основе с ягодным украшением. Пример описания для проверки карточки.' : null,
  composition: index === 0 ? 'Сливочный сыр, сливки, песочная основа, ягоды. Учебный пример, не утверждённый состав.' : null,
  allergens: index === 0 ? 'Молоко, пшеница, яйца. Демонстрационные сведения; не использовать для консультации покупателя.' : null,
  storage: index === 0 ? 'Условия и срок хранения требуют подтверждения ответственного. Демонстрационный текст.' : null,
  training: index === 0 ? 'Перед продажей проверьте маркировку, срок годности и утверждённый состав. Этот пример предназначен только для review интерфейса.' : null,
  prices: index === 6 ? [] : demoPoints.map((point, pointIndex) => ({ point, from: '2026-09-01', to: '2026-11-01', amount: (index === 4 || index === 9 ? 1800 : 220 + index * 15) + pointIndex * 20, unit: index === 4 || index === 9 ? 'кг' : 'порция' })),
}))
export type CatalogFilters = { query: string; status: string; category: string; mode: string }
export function filterCatalog(products: DemoProduct[], filters: CatalogFilters) {
  const query = filters.query.trim().toLocaleLowerCase('ru')
  return products.filter(p => (!query || `${p.name} ${p.sku}`.toLocaleLowerCase('ru').includes(query)) && (!filters.status || p.status === filters.status) && (!filters.category || p.category === filters.category) && (!filters.mode || p.mode === filters.mode))
}
export function resolveDemoPrice(product: DemoProduct, point: string, date: string) {
  if (!point) return 'Выберите точку'
  const matches = product.prices.filter(p => p.point === point && p.from <= date && date < p.to)
  if (matches.length !== 1) return 'Нет данных'
  return `${matches[0].amount.toLocaleString('ru-RU')} ₽ / ${matches[0].unit}`
}
export const statusLabel = (status: SaleStatus) => status === 'ON_SALE' ? 'В продаже' : 'Выведено из продажи'
export const modeLabel = (mode: SaleMode) => mode === 'PORTION' ? 'Порционный' : mode === 'WEIGHT' ? 'Весовой' : 'Нет данных'
