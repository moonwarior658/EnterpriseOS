const readinessReasons: Record<string, string> = {
  SUPPLIER_MAPPING_MISSING: 'Сопоставьте поставщика с iiko.',
  SUPPLIER_MAPPING_STALE: 'Обновите сопоставление поставщика: он недоступен в справочнике iiko.',
  STORE_MAPPING_MISSING: 'Проверьте сопоставление склада приёмки с iiko.',
  PRODUCT_MAPPING_MISSING: 'Сопоставьте товары с iiko.',
  UNIT_MAPPING_MISSING: 'Сопоставьте единицы измерения с iiko.',
  PRODUCT_MAIN_UNIT_MISSING: 'В справочнике iiko не определена основная единица товара.',
  UNIT_NOT_MAIN: 'Единица товара не совпадает с основной единицей в iiko.',
  PACKAGE_CONVERSION_REQUIRED: 'Для товара требуется подтверждённый пересчёт упаковок.',
  HISTORICAL_PRICE_MISSING: 'В накладной отсутствует цена или сумма строки.',
  FIXED_AMOUNT_NOT_PHYSICAL: 'Нет подходящей товарной строки накладной для прихода.',
  SUM_ALLOCATION_AMBIGUOUS: 'Невозможно однозначно определить сумму прихода по накладной.',
  PRIOR_ACCOUNTING_FACTS_REQUIRED: 'Не хватает данных о ранее учтённом количестве и сумме.',
  EXCESS_PRICE_SOURCE_MISSING: 'Для принятого излишка отсутствует документальное основание цены.',
  VAT_MISSING: 'Не определены данные НДС для прихода.',
  UNRESOLVED_EXCESS: 'Сначала зафиксируйте решение по принятому излишку.',
  NO_RECEIPT_ELIGIBLE_QUANTITY: 'Нет количества, доступного для прихода.',
}

export function incomingReceiptReadinessMessage(reasons: unknown): string {
  const messages = Array.isArray(reasons)
    ? [...new Set(reasons.map((reason: unknown) => typeof reason === 'string' && Object.hasOwn(readinessReasons, reason) ? readinessReasons[reason] : undefined).filter((message): message is string => Boolean(message)))]
    : []
  return `Приход не подготовлен. ${messages.length ? messages.join(' ') : 'Проверьте наличие связанных строк накладной, их цен и сопоставлений с iiko.'}`
}
