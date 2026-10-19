import {ApiError} from '../api/client';
import {useLanguage} from '../language';
import {careCopy} from './followUpCopy';

/** Scoped error feedback stays with the form; never expose provider SQL or private IDs. */
export function FollowUpError({error,kind='write'}:{error:unknown;kind?:'read'|'write'}){
 const {language}=useLanguage(),c=careCopy(language);
 const messages:Record<string,readonly [string,string]>={
  'Advanced follow-up settings are not enabled':['Advanced follow-up settings are not enabled yet. Reload the app before continuing.','扩展跟进设置尚未启用，请刷新应用后继续。'],
  'This report changed. Reload it before confirming a correction':['This report changed. Reopen it before confirming a correction.','这条自述已更新，请重新打开后核对更正。'],
  'Follow-up changed; reload before confirming':['This task changed. Reload it and review the new details.','该事项已更新，请重新读取并核对最新资料。'],
  'Actual administration time must be in the past and within this plan version':['The administration time must be in the past and within the reviewed plan dates.','实际服用时间必须是已核对计划有效日期内的过去时间。'],
  'Choose a future reminder time or no reminder':['Choose a future reminder time or no reminder.','请选择未来的提醒时间，或选择不提醒。'],
  'Choose a future follow-up time':['Choose a future rescheduled time.','改期请选择未来时间。'],
  'Confirm that this is a historical follow-up':['Confirm historical entry before saving this past task.','请先确认历史日期，再保存该事项。'],
  'Review and confirm this exact report again':['This confirmation is no longer valid. Return to edit and review the report again.','本次确认已失效，请返回编辑并重新核对自述。'],
  'This confirmation expired; start a new report':['This confirmation expired. Return to edit and review again.','确认已过期，请返回编辑并重新核对。'],
 };
 const known=error instanceof ApiError?messages[error.message]:undefined;
 const message=known?known[language==='zh'?1:0]:error instanceof ApiError&&error.code==='AUTH_REQUIRED'?c('Sign in again to continue.','请重新登录后继续。'):error instanceof ApiError&&error.code==='NOT_FOUND'?c('This record is unavailable. Reload the current list.','无法读取该记录，请重新读取当前列表。'):kind==='read'?c('Could not load these records. Try loading them again.','暂时无法读取这些记录，请重试。'):c('Could not confirm the result. Check the latest records before retrying; your entries remain here.','暂时无法确认提交结果。请核对最新记录后重试，您填写的内容仍保留在此。');
 return <p className="followup-error" role="alert">{message}</p>;
}
