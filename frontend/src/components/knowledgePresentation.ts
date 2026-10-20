export const knowledgeLabels = {purpose:'Назначение',composition:'Состав',allergens:'Аллергены',characteristics:'Характеристики',receiving_requirements:'Требования к приёмке',storage:'Условия хранения',shelf_life:'Срок годности',manufacturer:'Производитель основного товара',weight_evidence:'Основание веса условной единицы'}
/** Display only: source decimals and stored precision are never changed. */
export function knowledgeNumber(value:string|number|null|undefined):string {
  if(value===null||value===undefined||value==='')return 'Нет данных'
  let raw=String(value)
  const exponential=/^(-?)(\d+)(?:\.(\d*))?[eE]([+-]?\d+)$/.exec(raw)
  if(exponential){
    const exponent=Number(exponential[4])
    if(!Number.isSafeInteger(exponent)||Math.abs(exponent)>1000)return 'Нет данных'
    const digits=exponential[2]+(exponential[3]||''),point=exponential[2].length+exponent
    raw=exponential[1]+(point<=0?'0.'+'0'.repeat(-point)+digits:point>=digits.length?digits+'0'.repeat(point-digits.length):digits.slice(0,point)+'.'+digits.slice(point))
  }
  const match=/^(-?)(\d+)(?:\.(\d*))?$/.exec(raw)
  if(!match)return 'Нет данных'
  const fraction=(match[3]||'').padEnd(3,'0')
  const cents=BigInt(match[2])*100n+BigInt(fraction.slice(0,2))+(Number(fraction[2])>=5?1n:0n)
  const integer=(cents/100n).toString().replace(/\B(?=(\d{3})+(?!\d))/g,' ')
  return `${match[1]&&cents!==0n?'-':''}${integer},${(cents%100n).toString().padStart(2,'0')}`
}
export function knowledgePeriod(from?:string,to?:string):string {
  if(!from||!to)return 'Период не подтверждён'
  const end=new Date(`${to.slice(0,10)}T00:00:00Z`);end.setUTCDate(end.getUTCDate()-1)
  const label=(v:string)=>v.slice(0,10).split('-').reverse().join('.')
  return `${label(from)} — ${label(end.toISOString())}`
}
