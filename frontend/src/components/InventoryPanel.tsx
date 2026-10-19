import {useEffect,useState} from 'react';
import {api} from '../api/client';
import type {CareReview,StockKind,StockStatus,CountUnit} from '../api/care';
import {useLanguage} from '../language';
import {CareReviewSheet} from './CareReviewSheet';
import {ErrorNotice} from './primitives';

export function InventoryPanel({medicationId,mode='summary',onManage}:{medicationId:string;mode?:'summary'|'manage';onManage?:()=>void}){
 const {t,language,preferences}=useLanguage();const [data,setData]=useState<StockStatus|null>(null),[error,setError]=useState<unknown>(null),[pending,setPending]=useState<CareReview|null>(null);
 const [kind,setKind]=useState<StockKind>('refill'),[quantity,setQuantity]=useState(''),[unit,setUnit]=useState<CountUnit>('tablet'),[threshold,setThreshold]=useState('7'),[note,setNote]=useState('');
 const refresh=()=>api.inventory(medicationId).then(value=>{setData(value);if(value.unit)setUnit(value.unit);setThreshold(String(value.transactions.at(-1)?.low_threshold??7));});
 useEffect(()=>{let live=true;setData(null);void api.inventory(medicationId).then(value=>{if(live){setData(value);if(value.unit)setUnit(value.unit);setThreshold(String(value.transactions.at(-1)?.low_threshold??7));}}).catch(caught=>{if(live)setError(caught);});return()=>{live=false;};},[medicationId]);
 const date=(value:string)=>new Date(value).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:preferences.timezone});
 const isManagement=mode==='manage';
 return <section className={`card inventory-panel${isManagement?' inventory-panel--management':''}`} aria-labelledby="medication-inventory-title"><header className="medication-detail-section__header"><h2 id="medication-inventory-title">{isManagement?t('Stock overview'):t('Medication inventory')}</h2>{data?<span className="tag">{data.last_confirmed_stock===null?t('Inventory not established'):t('Inventory recorded')}</span>:null}</header>{error?<ErrorNotice error={error}/>:null}
 {data?<><dl className="medication-detail-grid"><div><dt>{t('Current remaining quantity')}</dt><dd>{data.estimated_remaining??t('Unknown')} {t(data.unit??'')}</dd></div><div><dt>{t('Estimated days remaining')}</dt><dd>{data.estimated_days===null?t('Not estimable'):data.estimated_days.toFixed(1)}</dd></div><div><dt>{t('Latest refill')}</dt><dd>{(()=>{const refill=[...data.transactions].reverse().find(item=>item.kind==='refill');return refill?date(refill.recorded_at):t('No record');})()}</dd></div></dl>
 <p>{data.last_confirmed_stock===null?t('No usable physical stock count is recorded.'): `${t('Last confirmed physical count')}: ${data.last_confirmed_stock} ${t(data.unit??'')}${data.last_confirmed_at?` · ${date(data.last_confirmed_at)}`:''}`}</p>
 {data.low_stock?<p className="notice" role="status">{t('Low stock: review your supply with your pharmacy.')}</p>:null}
 <p className="notice">{t('Estimate from confirmed counts, stock changes and compatible reported doses. Unreported consumption is unknown. PRN and incomplete plans have no daily estimate.')}</p>
 {data.label_quantities?.length?<details><summary>{t('Label quantity evidence (not current stock)')}</summary>{data.label_quantities.map(row=><p key={row.source_document_id}>{row.printed_line} · {t(row.review_status)}<small>{t('Source document')}: {row.source_document_id}</small></p>)}</details>:null}
 {!isManagement?<button type="button" onClick={onManage}>{t('Manage inventory and refills')}</button>:<>
  <div className="inventory-actions" aria-label={t('Inventory actions')}>
   <button type="button" className={kind==='refill'?'is-selected':''} aria-pressed={kind==='refill'} onClick={()=>setKind('refill')}>{t('Record refill')}</button>
   <button type="button" className={kind==='adjustment'?'is-selected':''} aria-pressed={kind==='adjustment'} onClick={()=>setKind('adjustment')}>{t('Adjust stock')}</button>
   <label className="field inventory-other-action">{t('Other stock change')}<select value={['count','lost','discarded','damaged'].includes(kind)?kind:''} onChange={event=>{if(event.target.value)setKind(event.target.value as StockKind);}}><option value="">{t('Choose an action')}</option>{(['count','lost','discarded','damaged'] as const).map(value=><option key={value} value={value}>{t(value)}</option>)}</select></label>
  </div>
  <div className="inventory-entry-form">
   <h3>{t(kind==='refill'?'Record refill':kind==='adjustment'?'Adjust stock':kind==='count'?'Record current stock':'Other stock change')}</h3>
   <label className="field">{t('Quantity')}<input type="number" step="any" value={quantity} onChange={event=>setQuantity(event.target.value)}/></label>
   <p className="notice">{t(kind==='adjustment'?'Enter a signed correction. Use a new count if you are unsure.':kind==='count'?'Count the units you physically have now. Label quantity is not your current stock.':'Enter the number of units added or removed, not medicine strength.')}</p>
   <label className="field">{t('Stock unit')}<select value={unit} disabled={!!data.unit} onChange={event=>setUnit(event.target.value as CountUnit)}><option value="tablet">{t('tablet')}</option><option value="capsule">{t('capsule')}</option></select></label>
   <label className="field">{t('Low-stock threshold')}<input type="number" min="0" max="10000" value={threshold} onChange={event=>setThreshold(event.target.value)}/></label><label className="field">{t('Your note')}<textarea maxLength={500} value={note} onChange={event=>setNote(event.target.value)}/></label>
   <button disabled={!quantity.trim()||!Number.isFinite(Number(quantity))||!threshold.trim()||!Number.isFinite(Number(threshold))} onClick={()=>setPending({action:'stock',medication_id:medicationId,stock:{id:crypto.randomUUID(),kind,quantity:Number(quantity),unit,low_threshold:Number(threshold),note,confirmed:false}})}>{t('Review stock change')}</button>
  </div>
  <section className="inventory-history" aria-labelledby="inventory-history-title"><header><h3 id="inventory-history-title">{t('Inventory history')}</h3><span>{data.transactions.length} {t('transactions')}</span></header>{data.transactions.length?data.transactions.slice(-8).reverse().map(row=><p key={row.id}><time dateTime={row.recorded_at}>{date(row.recorded_at)}</time><strong>{t(row.kind)}: {row.quantity} {t(row.unit)}</strong>{row.note?<small>{row.note}</small>:null}</p>):<p>{t('No inventory transactions yet.')}</p>}{data.transactions.length>8?<details><summary>{t('View all transactions')}</summary>{data.transactions.slice(0,-8).reverse().map(row=><p key={row.id}><time dateTime={row.recorded_at}>{date(row.recorded_at)}</time><strong>{t(row.kind)}: {row.quantity} {t(row.unit)}</strong>{row.note?<small>{row.note}</small>:null}</p>)}</details>:null}</section>
 </>}</>:<p role="status">{t('Loading stock records…')}</p>}
 {pending?<CareReviewSheet proposal={pending} onCancel={()=>setPending(null)} onSaved={()=>{setPending(null);setQuantity('');void refresh().catch(setError);}}/>:null}</section>;
}
