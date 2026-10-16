import {useEffect,useState} from 'react';
import {api} from '../api/client';
import type {CareReview,StockKind,StockStatus,CountUnit} from '../api/care';
import {useLanguage} from '../language';
import {CareReviewSheet} from './CareReviewSheet';
import {ErrorNotice} from './primitives';

export function InventoryPanel({medicationId}:{medicationId:string}){
 const {t,language,preferences}=useLanguage();const [data,setData]=useState<StockStatus|null>(null),[error,setError]=useState<unknown>(null),[pending,setPending]=useState<CareReview|null>(null);
 const [kind,setKind]=useState<StockKind>('count'),[quantity,setQuantity]=useState(''),[unit,setUnit]=useState<CountUnit>('tablet'),[threshold,setThreshold]=useState('7'),[note,setNote]=useState('');
 const refresh=()=>api.inventory(medicationId).then(value=>{setData(value);if(value.unit)setUnit(value.unit);setThreshold(String(value.transactions.at(-1)?.low_threshold??7));});
 useEffect(()=>{let live=true;setData(null);void api.inventory(medicationId).then(value=>{if(live){setData(value);if(value.unit)setUnit(value.unit);setThreshold(String(value.transactions.at(-1)?.low_threshold??7));}}).catch(caught=>{if(live)setError(caught);});return()=>{live=false;};},[medicationId]);
 const date=(value:string)=>new Date(value).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:preferences.timezone});
 return <section className="inventory-panel" aria-label={t('Stock and refill')}><h3>{t('Stock and refill')}</h3>{error?<ErrorNotice error={error}/>:null}
 {data?<><dl><dt>{t('Last confirmed physical count')}</dt><dd>{data.last_confirmed_stock??t('Unknown')} {t(data.unit??'')}{data.last_confirmed_at?` · ${date(data.last_confirmed_at)}`:''}</dd><dt>{t('Estimated remaining')}</dt><dd>{data.estimated_remaining??t('Unknown')} {t(data.unit??'')}</dd><dt>{t('Estimated days of supply')}</dt><dd>{data.estimated_days===null?t('Not estimable'):data.estimated_days.toFixed(1)}</dd></dl>
 {data.low_stock?<p className="notice" role="status">{t('Low stock: review your supply with your pharmacy.')}</p>:null}
 <p className="notice">{t('Estimate from confirmed counts, stock changes and compatible reported doses. Unreported consumption is unknown. PRN and incomplete plans have no daily estimate.')}</p>
 {data.label_quantities?.length?<details><summary>{t('Label quantity evidence (not current stock)')}</summary>{data.label_quantities.map(row=><p key={row.source_document_id}>{row.printed_line} · {t(row.review_status)}<small>{t('Source document')}: {row.source_document_id}</small></p>)}</details>:null}
 <details><summary>{t('Update stock or record refill')}</summary><label className="field">{t('Stock action')}<select value={kind} onChange={event=>setKind(event.target.value as StockKind)}>{(['count','refill','adjustment','lost','discarded','damaged'] as const).map(value=><option key={value} value={value}>{t(value)}</option>)}</select></label>
 <label className="field">{t('Quantity')}<input type="number" step="any" value={quantity} onChange={event=>setQuantity(event.target.value)}/></label><p className="notice">{t(kind==='count'?'Count the units you physically have now. Label quantity is not your current stock.':kind==='adjustment'?'Enter a signed correction. Use a new count if you are unsure.':'Enter the number of units added or removed, not medicine strength.')}</p>
 <label className="field">{t('Stock unit')}<select value={unit} disabled={!!data.unit} onChange={event=>setUnit(event.target.value as CountUnit)}><option value="tablet">{t('tablet')}</option><option value="capsule">{t('capsule')}</option></select></label>
 <label className="field">{t('Low-stock threshold')}<input type="number" min="0" max="10000" value={threshold} onChange={event=>setThreshold(event.target.value)}/></label><label className="field">{t('Your note')}<textarea maxLength={500} value={note} onChange={event=>setNote(event.target.value)}/></label>
 <button disabled={!quantity.trim()||!Number.isFinite(Number(quantity))||!threshold.trim()||!Number.isFinite(Number(threshold))} onClick={()=>setPending({action:'stock',medication_id:medicationId,stock:{id:crypto.randomUUID(),kind,quantity:Number(quantity),unit,low_threshold:Number(threshold),note,confirmed:false}})}>{t('Review stock change')}</button></details>
 <details><summary>{t('Stock transaction history')} ({data.transactions.length})</summary>{data.transactions.map(row=><p key={row.id}>{date(row.recorded_at)} · {t(row.kind)} {row.quantity} {t(row.unit)}{row.note?` · ${row.note}`:''}</p>)}</details></>:<p role="status">{t('Loading stock records…')}</p>}
 {pending?<CareReviewSheet proposal={pending} onCancel={()=>setPending(null)} onSaved={()=>{setPending(null);setQuantity('');void refresh().catch(setError);}}/>:null}</section>;
}
