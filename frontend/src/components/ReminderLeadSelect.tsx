import {useLanguage} from '../language';

/** Presentation only; native settings and Assistant choose their own save boundary. */
export function ReminderLeadSelect({value,disabled=false,onChange,id='reminder-lead-time'}:{value:number;disabled?:boolean;onChange:(value:number)=>void;id?:string}){
 const {t}=useLanguage(),supported=[0,15,30,60].includes(value);
 return <label className="reminder-lead-control" htmlFor={id}><span>{t('Reminder Lead Time')}</span>
  <select id={id} disabled={disabled} value={value} onChange={event=>{const next=Number(event.target.value);if(Number.isInteger(next)&&next>=0&&next<=120)onChange(next);}}>
   {!supported?<option value={value}>{t('Current setting: {minutes} minutes').replace('{minutes}',String(value))}</option>:null}
   <option value={0}>{t('At scheduled time')}</option><option value={15}>{t('15 minutes before')}</option><option value={30}>{t('30 minutes before')}</option><option value={60}>{t('1 hour before')}</option>
  </select>
 </label>;
}
