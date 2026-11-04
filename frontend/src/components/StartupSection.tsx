import type {ReactNode} from 'react';
import type {LoadState} from '../startupState';
import {useLanguage} from '../language';

export function StartupSection<T>({state,onRetry,children}:{state:LoadState<T>;onRetry:()=>Promise<void>;children?:ReactNode}){
 const {language}=useLanguage();
 if(state.status==='ready')return <>{children}</>;
 return <section className="card" aria-busy={state.status!=='error'}>
  {state.status==='error'?<><p role="alert">{language==='zh'?'这部分资料暂时无法读取，不代表没有记录。':'This information could not be loaded. This does not mean there are no records.'}</p><button onClick={()=>void onRetry()}>{language==='zh'?'重试读取资料':'Retry loading information'}</button></>
   :<p role="status">{language==='zh'?'正在读取这部分资料…':'Loading this information…'}</p>}
 </section>;
}
