import {useLanguage} from '../language';
import {BottomSheet} from './BottomSheet';
import {ErrorNotice} from './primitives';

/** Shared patient review for stopping recorded tracking; callers use the original API. */
export function StopPlanReview({busy,error,onConfirm,onCancel}:{busy:boolean;error:unknown;onConfirm:()=>void;onCancel:()=>void}){
 const {t}=useLanguage();
 return <BottomSheet title={t('Stop this recorded plan?')} busy={busy} onCancel={onCancel}>
  <p>{t("This stops reminders in MediThread and keeps past records. It does not advise changing your medication. Follow your clinician's instructions.")}</p>
  <p>{t('Previously imported calendar events must be updated or removed in your calendar app.')}</p>
  <button className="primary" disabled={busy} onClick={onConfirm}>{t('Confirm stop')}</button>
  {error?<ErrorNotice error={error}/>:null}
  <button disabled={busy} onClick={onCancel}>{t('Cancel')}</button>
 </BottomSheet>;
}
