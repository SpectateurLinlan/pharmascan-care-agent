import {useId,useRef} from 'react';
import {useLanguage} from '../language';
import {Icon} from './Icon';

/** Editable native text segments plus a full-width picker target beside them. */
export function MedicationDate({label,value,onChange,type='date',min,id:providedId}:{id?:string;label:string;value:string;onChange:(value:string)=>void;type?:'date'|'time';min?:string}){
 const {t}=useLanguage();const input=useRef<HTMLInputElement>(null);const generatedId=useId();const id=providedId??generatedId;
 return <div className="field"><label htmlFor={id}>{t(label)}</label><div className="picker-control"><input ref={input} id={id} type={type} min={min} value={value} onChange={event=>onChange(event.target.value)}/><button type="button" className="picker-open" aria-label={t(type==='date'?'Choose date':'Choose time')} onClick={()=>{try{if(input.current?.showPicker)input.current.showPicker();else input.current?.focus();}catch{input.current?.focus();}}}><Icon name={type==='date'?'calendar':'clock'}/></button></div></div>;
}
export function MedicationTimes({value,onChange}:{value:string;onChange:(value:string)=>void}){
 const {t}=useLanguage();const rows=value.split(',').map(item=>item.trim());
 return <fieldset className="medication-times"><legend>{t('Scheduled times')}</legend>{rows.map((time,index)=><div className="time-input-row" key={index}>
 <MedicationDate type="time" label={`${t('Dose time')} ${index+1}`} value={time} onChange={value=>onChange(rows.map((item,at)=>at===index?value:item).join(', '))}/>
 <button type="button" className="icon-button" aria-label={t('Add another time')} onClick={()=>onChange([...rows,''].join(', '))}><Icon name="plus"/></button>
 {rows.length>1?<button type="button" onClick={()=>onChange(rows.filter((_,at)=>at!==index).join(', '))}>{t('Remove')}</button>:null}
 </div>)}</fieldset>;
}
