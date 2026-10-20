import type { CSSProperties, ReactNode } from 'react'

export function KnowledgeHeader({title,description}:{title:string;description:string}) {
 return <div className="page-title-row"><div><p className="eyebrow">БАЗА ЗНАНИЙ</p><h1>{title}</h1><p className="muted-text">{description}</p></div></div>
}
export function KnowledgeActions({children}:{children:ReactNode}) {return <div className="material-card-actions product-actions">{children}</div>}
export function KnowledgeInfo({title,items}:{title:string;items:{label:string;value:ReactNode}[]}) {
 return <section className="product-knowledge-section knowledge-info"><h2>{title}</h2><dl className="material-info-grid">{items.map(item=><div key={item.label}><dt>{item.label}</dt><dd>{item.value}</dd></div>)}</dl></section>
}
export function KnowledgeStatus({children,tone='empty'}:{children:ReactNode;tone?:'ready'|'empty'|'blocked'}) {return <span className={`material-status material-status-${tone}`}>{children}</span>}
export function KnowledgeFilterToggle({children,active,onClick}:{children:ReactNode;active:boolean;onClick:()=>void}) {return <button type="button" className="secondary-action" aria-pressed={active} onClick={onClick}>{children}</button>}
export function KnowledgeSortHeader({label,field,selected,direction,onSort,enabled=true}:{label:string;field:string;selected:string;direction:string;onSort:(field:string)=>void;enabled?:boolean}) {
 const sortable=Boolean(field)&&enabled,active=selected===field
 return <th scope="col" aria-sort={sortable?(active?(direction==='desc'?'descending':'ascending'):'none'):undefined}>{sortable?<button className="material-sort" onClick={()=>onSort(field)}>{label}<span aria-hidden="true">{active?(direction==='desc'?' ↓':' ↑'):' ↕'}</span></button>:label}</th>
}
export function KnowledgePhoto({name,url,large=false,loading=false,failed=false,fit='cover',onError}:{name:string;url?:string;large?:boolean;loading?:boolean;failed?:boolean;fit?:CSSProperties['objectFit'];onError?:()=>void}) {
 return <div className={`knowledge-photo${large?' knowledge-photo-large':''}`} aria-label={!url?'Фото отсутствует':undefined}>{url&&!failed?<img src={url} alt={name} style={{objectFit:fit}} onError={onError}/>:failed?'Фото недоступно':loading?<span role="status">Загрузка…</span>:'Нет фото'}</div>
}
export function KnowledgePhotoPicker({file,disabled=false,onChange}:{file:File|null;disabled?:boolean;onChange:(file:File|null)=>void}) {
 return <><label className="material-file-picker">Выбрать фотографию<input type="file" accept="image/jpeg,image/png,image/webp" disabled={disabled} onChange={e=>onChange(e.target.files?.[0]||null)}/></label><p>{file?file.name:'Файл не выбран'}</p></>
}
