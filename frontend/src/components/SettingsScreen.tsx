import {useEffect,useState} from 'react';
import {useLanguage} from '../language';
import {ReminderSettings} from './ReminderSettings';
import {api} from '../api/client';
import {TextSizeSlider} from './TextSizeSlider';
import {Screen} from '../ui/primitives';

/**
 * One settings screen per concern.
 *
 * Each is a titled screen with named groups rather than one long card with
 * hidden blocks, so a patient arriving from Me sees where they are and what
 * belongs together.
 */
export function SettingsScreen({section='all'}:{section?:'all'|'language'|'accessibility'|'reminders'}){
 const {language,setLanguage,t,preferences,updatePreferences,ttsProvider,setTtsProvider,speechRate,setSpeechRate}=useLanguage();
 const [cloudAllowed,setCloudAllowed]=useState(false);
 useEffect(()=>{let live=true;if(api.speechCapabilities)void api.speechCapabilities().then(cap=>{if(live)setCloudAllowed(cap.cloud_tts_allowed);}).catch(()=>{if(live)setCloudAllowed(false);});return()=>{live=false;};},[]);

 const titles:Record<'all'|'language'|'accessibility'|'reminders',string>={
  all:'Settings',language:'Language and speech',accessibility:'Accessibility',reminders:'Medication reminders',
 };
 const leads:Record<'all'|'language'|'accessibility'|'reminders',string>={
  all:'Everything you can change about how the app works for you.',
  language:'Which language the app uses, and how it speaks to you.',
  accessibility:'Make the app easier to read and to tap.',
  reminders:'When the app prompts you about a dose, and how that reaches you.',
 };
 const showLanguage=section==='all'||section==='language';
 const showAccessibility=section==='all'||section==='accessibility';
 const showReminders=section==='all'||section==='reminders';

 return <Screen title={titles[section]} lead={leads[section]}>
  {showLanguage?<>
   <section className="card">
    <h2 className="card__title">{t('Preferred language')}</h2>
    <div className="field"><label htmlFor="settings-language">{t('Preferred language')}</label>
     <select id="settings-language" aria-label="Settings language" value={language} onChange={event=>setLanguage(event.target.value==='zh'?'zh':'en')}><option value="en">English</option><option value="zh">中文</option></select>
    </div>
   </section>

   <section className="card">
    <h2 className="card__title">{t('Voice and speech')}</h2>
    <label className="consent"><input type="checkbox" checked={preferences.voice_enabled} onChange={event=>updatePreferences({voice_enabled:event.target.checked})}/>{t('Enable voice')}</label>
    <label className="consent"><input type="checkbox" checked={preferences.tts_autoplay} onChange={event=>updatePreferences({tts_autoplay:event.target.checked})}/>{t('Read replies automatically')}</label>
    <label className="field">{t('Speech playback')}<select aria-label={t('Speech playback')} value={ttsProvider} onChange={event=>setTtsProvider(event.target.value==='tencent'&&cloudAllowed?'tencent':'browser')}><option value="browser">{t('Browser voice (default)')}</option><option value="tencent" disabled={!cloudAllowed}>{t('Cloud voice (usage charges may apply)')}</option></select></label>
    <label className="field">{t('Speech speed')}<input aria-label={t('Speech speed')} type="range" min="0.7" max="1.2" step="0.05" value={speechRate} onChange={event=>setSpeechRate(Number(event.target.value))}/>{speechRate.toFixed(2)}x</label>
    <p className="notice">{t('Browser voices depend on your device and may use an online service. Cloud voice requires explicit selection and server permission. Selection resets to browser on reload.')}</p>
    <p className="notice">{t('Voice input uses your browser’s speech service, which may be online. Your browser asks for microphone permission the first time; audio is not saved. Review the transcript before sending.')}</p>
   </section>
  </>:null}

  {showAccessibility?<section className="card">
   <h2 className="card__title">{t('Text size')}</h2>
   <TextSizeSlider/>
  </section>:null}

  {showReminders?<section className="card">
   <h2 className="card__title">{t('Reminders')}</h2>
   <ReminderSettings/>
  </section>:null}
 </Screen>;
}
