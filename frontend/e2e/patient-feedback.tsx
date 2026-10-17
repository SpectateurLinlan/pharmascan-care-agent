// Local test entry: real components, explicitly simulated identity and HTTP.
import {useEffect,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {App} from '../src/App';
import {LanguageProvider,useLanguage} from '../src/language';
import {PatientHub,ProfileScreen,InformationScreen} from '../src/components/PatientHub';
import {MeScreen} from '../src/components/MeScreen';
import {EvidenceEnrollmentScreen} from '../src/components/EvidenceEnrollmentScreen';
import {AssistantScreen} from '../src/components/AssistantScreen';
import '../src/styles.css';
function Fixture(){
 const [page,setPage]=useState('me'),[chat,setChat]=useState(false);
 const {loadPreferences,setLanguage,updatePreferences}=useLanguage();
 useEffect(()=>{void loadPreferences();},[loadPreferences]);
 return <main className="app" style={{paddingTop:'1rem'}}><p>LOCAL / MOCK — synthetic interaction fixture</p><nav className="actions"><button onClick={()=>setPage('me')}>Fixture Me</button><button onClick={()=>setPage('read')}>Fixture Read</button><button onClick={()=>setPage('login')}>Fixture Login</button><button onClick={()=>setChat(true)}>Fixture Assistant</button><button onClick={()=>setLanguage('zh')}>中文</button><button onClick={()=>updatePreferences({text_scale_percent:150})}>150%</button></nav>
 {page==='me'?<PatientHub onOpen={setPage} onGuide={()=>setPage('guide')}/>:null}
 {page==='profile'?<><ProfileScreen/><MeScreen onIdentityChanged={()=>undefined}/></>:null}
 {page==='login'?<MeScreen onIdentityChanged={()=>undefined}/>:null}
 {page==='privacy'?<InformationScreen ownerId="DEMO-fixture" kind="privacy" onHistory={()=>undefined}/>:null}
 {page==='read'?<EvidenceEnrollmentScreen sessionId="DEMO-session" ownerId="DEMO-fixture" onChanged={()=>undefined}/>:null}
 <div hidden={!chat}><AssistantScreen ownerId="DEMO-fixture" compact={!chat} workspace={chat} onExpand={()=>setChat(true)} active={chat} sessionId="DEMO-session" onSession={()=>undefined} onClose={()=>setChat(false)}/></div>
 </main>;
}
createRoot(document.getElementById('root')!).render(new URLSearchParams(location.search).has('shell')?<App/>:<LanguageProvider><Fixture/></LanguageProvider>);
