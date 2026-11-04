import {useEffect,useRef,useState} from 'react';
import {api,type CaregiverDetails,type PreferenceUpdate} from '../api/client';
import type {JsonValue,WorkflowEventHandler,WorkflowView} from '../api/assistantWorkflows';
import {useLanguage} from '../language';
import {BottomSheet} from './BottomSheet';
import {CaregiverDetailsFields,type CaregiverEditorDraft} from './CaregiverDetailsFields';
import {ReminderLeadSelect} from './ReminderLeadSelect';

const record=(value:JsonValue|undefined):Record<string,JsonValue>=>value&&typeof value==='object'&&!Array.isArray(value)?value:{};
const contactDetails=(value:Record<string,JsonValue>)=>Object.fromEntries(['name','relationship','contact_type','contact_value','storage_consent'].map(key=>[key,value[key]??null]));
const scopeFields:Record<string,string[]>={'preference.language':['preferred_language'],'preference.text':['text_scale_percent'],'preference.voice':['voice_enabled','tts_autoplay'],'preference.reminder':['reminders_enabled','reminder_lead_minutes'],'preference.privacy':['conversation_history_enabled'],'preference.timezone':['timezone'],'profile.edit':['display_name']};

export function AssistantSettingsActions({view,busy,onEvent,onDirtyChange,onClinicalChanged}:{view:WorkflowView;busy:boolean;onEvent:WorkflowEventHandler;onDirtyChange?:((dirty:boolean)=>void)|undefined;onClinicalChanged?:(()=>void)|undefined}){
 const {language,t,loadPreferences}=useLanguage(),say=(en:string,zh:string)=>language==='zh'?zh:en;
 const capability=view.capability_id,input=view.input_fields??{},current=record(view.visible_fields.current_preferences),contact=record(view.visible_fields.current_contact),isContact=capability.startsWith('caregiver.'),deleting=capability==='caregiver.delete';
 const [values,setValues]=useState<Record<string,JsonValue>>({...current,...input});
 const [draft,setDraft]=useState<CaregiverEditorDraft>({name:String(input.name??contact.name??''),relationship:String(input.relationship??contact.relationship??''),contact_type:(input.contact_type??contact.contact_type)==='phone'?'phone':'email',contact_value:String(input.contact_value??contact.contact_value??''),consent:input.storage_consent===true});
 const [dirty,setDirty]=useState(false),[working,setWorking]=useState(false),[open,setOpen]=useState(false),[editing,setEditing]=useState(false),[uncertain,setUncertain]=useState(false),[error,setError]=useState(false);
 const pending=useRef(false),live=useRef(true);
 useEffect(()=>{live.current=true;return()=>{live.current=false;};},[]);
 useEffect(()=>{onDirtyChange?.(dirty||open||working);return()=>onDirtyChange?.(false);},[dirty,open,working,onDirtyChange]);
 const blocked=busy||working,bound=view.save_mode==='allowed'&&view.state==='awaiting_confirmation'&&view.result_ref?.kind==='settings_review';
 const label=(key:string)=>({display_name:say('Display name','显示名称'),preferred_language:say('Preferred language','首选语言'),speech_locale:say('Speech language','语音语言'),text_scale_percent:say('Text size','字号百分比'),text_size:say('Text size preset','字号预设'),voice_enabled:say('Voice playback','语音播放'),tts_autoplay:say('Automatic reading','自动朗读'),conversation_history_enabled:say('Save chat history','保存聊天记录'),reminders_enabled:say('Medication reminders','药物提醒'),reminder_lead_minutes:say('Reminder lead minutes','提前提醒分钟数'),timezone:say('Time zone','时区')}[key]??key);
 const shown=(value:JsonValue)=>typeof value==='boolean'?value?say('On','开启'):say('Off','关闭'):value===null?say('Not set','未设置'):value==='zh'?'中文':value==='en'?'English':value==='large'?say('Large','大'):value==='standard'?say('Standard','标准'):String(value);
 const preferenceSummary=(fields:Record<string,JsonValue>)=><dl>{Object.entries(fields).map(([key,value])=><div key={key}><dt>{label(key)}</dt><dd>{shown(value)}</dd></div>)}</dl>;
 async function dispatch(fields:Record<string,JsonValue>){if(blocked||pending.current)return;pending.current=true;setWorking(true);setError(false);try{await onEvent({event_id:crypto.randomUUID(),expected_revision:view.revision,kind:'provide_fields',values:fields});if(live.current)setDirty(false);}catch{if(live.current)setError(true);}finally{pending.current=false;if(live.current)setWorking(false);}}
 async function check(){const next=await onEvent({event_id:crypto.randomUUID(),expected_revision:view.revision,kind:'report_business_result',values:{}});if(!next||next.task_id!==view.task_id||next.revision<=view.revision)throw new Error('Check the current settings result.');if(live.current){setOpen(false);setUncertain(false);}if(next.state==='completed')onClinicalChanged?.();}
 const review=record(view.visible_fields.settings_review),payload=record(review.payload),target=typeof review.target_id==='string'?review.target_id:null;
 async function confirm(){if(!bound||blocked||pending.current||uncertain)return;pending.current=true;setWorking(true);setError(false);const binding={task_id:view.task_id,expected_revision:view.revision};try{
   if(capability==='caregiver.add')await api.createCaregiver(payload as unknown as CaregiverDetails&{id:string},binding);
   else if(capability==='caregiver.edit'&&target)await api.updateCaregiver(target,payload as unknown as CaregiverDetails,binding);
   else if(deleting&&target)await api.deleteCaregiver(target,binding);
   else if(!isContact){await api.updatePreferences(payload as PreferenceUpdate,binding);await loadPreferences();}
   else throw new Error('Reopen the selected contact.');await check();
  }catch{if(live.current){setError(true);setUncertain(true);}}finally{pending.current=false;if(live.current)setWorking(false);}}
 if(view.state==='suspended'||view.state==='cancelled')return null;
 const contactSummary=(fields:Record<string,JsonValue>)=><><strong>{String(fields.name??'')}</strong><p>{String(fields.relationship??'')}</p><p>{String(fields.contact_value??'')}</p><p>{say('This contact is not independently verified. No notifications, invitations or record access are enabled.','此联系人尚未独立验证，不会开启通知、邀请或记录访问权限。')}</p></>;
 if(capability==='profile.view')return preferenceSummary(current);
 if(capability==='caregiver.list'){const rows=Array.isArray(view.visible_fields.contacts)?view.visible_fields.contacts.map(record):[];return <div>{rows.length?<ul>{rows.map((row,index)=><li key={index}>{contactSummary(row)}</li>)}</ul>:<p>{say('No care contacts saved yet.','尚未保存关怀联系人。')}</p>}</div>;}
 if(view.state==='completed')return <div><p>{say('The earlier change was saved. Current values are shown below.','此前的变更已保存，以下显示当前资料。')}</p>{isContact?Object.keys(contact).length?contactSummary(contact):<p>{say('This contact is not currently saved.','当前未保存此联系人。')}</p>:preferenceSummary(current)}</div>;
 if(bound&&!editing)return <div>{view.prompt_key==='assistant.settings.check_result'?<button disabled={blocked} onClick={()=>void check().catch(()=>setError(true))}>{say('Check settings result','核查设置结果')}</button>:<><button disabled={blocked} onClick={()=>setOpen(true)}>{say('Review settings change','核对设置变更')}</button><button disabled={blocked||uncertain} onClick={()=>setEditing(true)}>{say('Edit settings details','修改设置资料')}</button></>}
  {open?<BottomSheet title={say('Review settings change','核对设置变更')} onCancel={()=>setOpen(false)} busy={working}>
   {isContact?<>{deleting?<p>{say('Remove only this contact. Medication and account records are retained.','仅移除此联系人，药物及账户记录会保留。')}</p>:null}{contactSummary(deleting?contact:payload)}</>:preferenceSummary(payload)}
   {!uncertain?<button disabled={blocked} onClick={()=>void confirm()}>{say('Confirm settings change','确认设置变更')}</button>:<button disabled={blocked} onClick={()=>void check().catch(()=>setError(true))}>{say('Check settings result','核查设置结果')}</button>}
   <button disabled={working} onClick={()=>setOpen(false)}>{t('Cancel')}</button>{error?<p role="alert">{say('The save or result check did not finish. Your details are retained. Check the result before another change.','保存或结果核查未完成，资料仍保留。请先核查结果，再进行下一次变更。')}</p>:null}
  </BottomSheet>:null}{error&&!open?<p role="alert">{say('The current result could not be confirmed.','暂时无法确认当前结果。')}</p>:null}
 </div>;
 const choices=view.actions.flatMap(action=>action.kind==='choice'&&action.action_id==='settings.contact'?action.options:[]);
 const change=(key:string,value:JsonValue)=>{setValues(old=>({...old,[key]:value}));setDirty(true);};
 return <div>{choices.map(option=><button key={option.value} disabled={blocked} onClick={()=>void dispatch({contact_id:option.value})}>{say('Select','选择')}: {option.label_text}</button>)}
  {isContact&&capability!=='caregiver.add'&&!input.contact_id?<p>{say('Choose the saved contact to continue.','请选择已保存的联系人，再继续办理。')}</p>:<form onSubmit={event=>{event.preventDefault();const fields=isContact?{...(input.contact_id?{contact_id:input.contact_id}:{}),...(capability!=='caregiver.add'?{previous:contactDetails(contact),previous_updated_at:contact.updated_at??null}:{}),...(!deleting?{name:draft.name.trim(),relationship:draft.relationship.trim()||null,contact_type:draft.contact_type,contact_value:draft.contact_value.trim(),storage_consent:draft.consent}:{})}:{...Object.fromEntries((scopeFields[capability]??[]).map(key=>[key,values[key]??null])),previous:current};void dispatch(fields);}}>
   {isContact?deleting?contactSummary(contact):<CaregiverDetailsFields draft={draft} busy={blocked} onChange={next=>{setDraft(next);setDirty(true);}}/>:<>
    {capability==='preference.language'?<label className="field">{label('preferred_language')}<select disabled={blocked} value={String(values.preferred_language??'en')} onChange={event=>change('preferred_language',event.target.value)}><option value="en">English</option><option value="zh">中文</option></select></label>:null}
    {capability==='preference.text'?<label className="field">{t('Text size')}<input type="range" min="100" max="150" step="1" disabled={blocked} value={Number(values.text_scale_percent??100)} onChange={event=>change('text_scale_percent',Number(event.target.value))}/><output>{String(values.text_scale_percent??100)}%</output></label>:null}
    {(scopeFields[capability]??[]).filter(key=>['voice_enabled','tts_autoplay','conversation_history_enabled','reminders_enabled'].includes(key)).map(key=><label key={key}><input type="checkbox" checked={values[key]===true} disabled={blocked} onChange={event=>change(key,event.target.checked)}/>{label(key)}</label>)}
    {capability==='preference.reminder'?<ReminderLeadSelect value={Number(values.reminder_lead_minutes??0)} disabled={blocked} onChange={value=>change('reminder_lead_minutes',value)} id={`settings-lead-${view.task_id}`}/>:null}
    {capability==='preference.timezone'||capability==='profile.edit'?<label className="field">{label(capability==='profile.edit'?'display_name':'timezone')}<input required maxLength={80} disabled={blocked} value={String(values[capability==='profile.edit'?'display_name':'timezone']??'')} onChange={event=>change(capability==='profile.edit'?'display_name':'timezone',event.target.value)}/></label>:null}
    {capability==='preference.privacy'?<p>{say('This changes future chat saving. It does not delete existing chats or clinical records.','这只更改后续聊天保存设置，不会删除已有聊天或临床记录。')}</p>:capability==='preference.timezone'?<p>{say('The app will refresh the schedule display after saving. Historical dose reports are retained.','保存后应用会刷新排程显示，历史服药记录会保留。')}</p>:capability==='preference.voice'?<p>{say('These preferences do not grant microphone or cloud-processing permission.','这些偏好不会授予麦克风或云端处理权限。')}</p>:null}
   </>}
   <button type="submit" disabled={blocked||(isContact&&!deleting&&!draft.consent)}>{say('Apply settings details','使用设置资料')}</button>
   {dirty?<button type="button" disabled={blocked} onClick={()=>{setValues({...current,...input});setDraft({name:String(input.name??contact.name??''),relationship:String(input.relationship??contact.relationship??''),contact_type:(input.contact_type??contact.contact_type)==='phone'?'phone':'email',contact_value:String(input.contact_value??contact.contact_value??''),consent:input.storage_consent===true});setDirty(false);}}>{say('Undo unsent changes','撤回未提交的更改')}</button>:null}
  </form>}
  {error?<p role="alert">{say('The draft could not be updated. Your input is still here.','暂时无法更新草稿，输入仍保留。')}</p>:null}
 </div>;
}
