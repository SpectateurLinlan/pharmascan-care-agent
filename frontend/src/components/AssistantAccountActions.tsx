import {useEffect,useState} from 'react';
import type {WorkflowView} from '../api/assistantWorkflows';
import {useLanguage} from '../language';
import {MeScreen} from './MeScreen';

function identityChanged(){window.localStorage.removeItem('pharmascan.agent-session');window.location.reload();}

/** Native Auth owns every secret, session and identity transition; no workflow event carries them. */
export function AssistantAccountActions({view,busy,onDirtyChange,onIdentityChanged=identityChanged}:{view:WorkflowView;busy:boolean;onDirtyChange?:((dirty:boolean)=>void)|undefined;onIdentityChanged?:(()=>void)|undefined}){
 const {language}=useLanguage(),say=(en:string,zh:string)=>language==='zh'?zh:en;
 const [open,setOpen]=useState(false);
 useEffect(()=>{onDirtyChange?.(open);return()=>onDirtyChange?.(false);},[open,onDirtyChange]);
 if(['suspended','cancelled','completed'].includes(view.state))return null;
 const action=view.capability_id.split('.')[1] as 'status'|'login'|'link'|'password'|'signout';
 return <div><p>{say('Use the secure account form. Passwords and verification codes are not sent to the Assistant or saved in this task.','请使用安全账户表单。密码和验证码不会发送给 Assistant 或保存到此任务中。')}</p>
  {!open?<button disabled={busy} onClick={()=>setOpen(true)}>{say('Open secure account form','打开安全账户表单')}</button>:<>
   <MeScreen embedded initialAction={action} onIdentityChanged={onIdentityChanged}/>
   <button disabled={busy} onClick={()=>setOpen(false)}>{say('Close account form','关闭账户表单')}</button>
  </>}
 </div>;
}
