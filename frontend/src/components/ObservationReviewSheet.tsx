import type {ReactNode} from 'react';
import type {Measurement} from '../api/client';
import {useLanguage} from '../language';
import {BottomSheet} from './BottomSheet';

/** Shared presentation; caller supplies the original independent patient save. */
export function ObservationReviewSheet({record,deleting=false,busy,onConfirm,onCancel,children,linkedLabel}:{record:Measurement&{description:string;occurred_at?:string;notes?:string|null;severity?:string|null};deleting?:boolean;busy:boolean;onConfirm:()=>void;onCancel:()=>void;children?:ReactNode;linkedLabel?:string|undefined}){
 const {t,language,preferences}=useLanguage();
 return <BottomSheet title={t(deleting?'Delete this health note?':'Save this health note?')} busy={busy} onCancel={onCancel}>
  <p>{record.description}</p>
  {linkedLabel?<p>{t('Linked medication')}: {linkedLabel}</p>:null}{record.severity?<p>{t(record.severity)}</p>:null}
  {record.occurred_at?<p>{new Date(record.occurred_at).toLocaleString(language==='zh'?'zh-CN':'en-SG',{timeZone:preferences.timezone})}</p>:null}
  {record.kind&&record.kind!=='note'?<p>{t(record.kind)}: {record.value}{record.secondary_value!==null&&record.secondary_value!==undefined?` / ${record.secondary_value}`:''} {record.unit}</p>:null}
  {record.notes?<p>{record.notes}</p>:null}
  <p>{t(deleting?'Your medication and dose records will not change.':'This records your experience without diagnosing a cause.')}</p>
  {children}<div className="actions"><button className="primary" disabled={busy} onClick={onConfirm}>{t(deleting?'Delete':'Confirm record')}</button><button disabled={busy} onClick={onCancel}>{t('Cancel')}</button></div>
 </BottomSheet>;
}
