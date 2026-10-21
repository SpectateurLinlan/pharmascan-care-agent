import {useEffect,useRef,useState,type CSSProperties} from 'react';
import {createPortal} from 'react-dom';
import {useLanguage} from '../language';
import {BrowserTts} from '../browserTts';
import {Icon} from './Icon';
import {BottomSheet} from './BottomSheet';
import {ONBOARDING_STEP_COUNT,readTour,saveTour} from '../onboarding';

type GuideStep={route:string;target:string;title:string;sections:readonly {heading:string;body:string;guestBody?:string}[];note?:string;guestNote?:boolean};
const steps:readonly GuideStep[]=[
  {route:'today',target:'#today-medication',title:"Check Today's Schedule",sections:[
    {heading:"Today's Medications",body:"Review today's scheduled doses and record what actually happened."},
    {heading:'Care Tasks',body:'See follow-up tasks that are pending or overdue.'},
  ],note:'Not recorded does not mean not taken.'},
  {route:'medicines',target:'[data-guide="medication-add"]',title:'Add and Manage Medications',sections:[
    {heading:'Add a Medication',body:'Open Medications to add a medication using the available entry methods.'},
    {heading:'Review the Schedule',body:'Check the medication name, dose, and schedule before relying on the information for daily management.'},
  ],note:"A photo alone cannot confirm a medication's identity."},
  {route:'records',target:'.records-summary--highlight',title:'Review Medication and Health Records',sections:[
    {heading:'Review History',body:'Use Records to review saved dose reports, health observations, and follow-up information.'},
    {heading:'Medication & Health Summary',body:'Open or export a summary when reviewing your information or preparing for a healthcare visit.'},
  ]},
  {route:'assistant',target:'[data-guide="assistant-conversation"]',title:'Ask the AI Assistant',sections:[
    {heading:'Questions and Preparation',body:'Ask about medications, review existing records, or prepare questions for a healthcare visit.'},
    {heading:'Conversation History',body:'If chat saving is enabled, you can revisit previous conversations in the full chat view.'},
  ],note:'The AI assistant does not independently change your medication schedule or replace a doctor or pharmacist.'},
  {route:'assistant',target:'[data-guide="assistant-composer"]',title:'Use Text, Photos, or Voice',sections:[
    {heading:'Text Input',body:'Type your question and review it before sending.'},
    {heading:'Photos and Voice',body:'You can attach photos or use voice input when available. Recognition and transcription may be inaccurate, so check the results.'},
  ],note:'Adding photos or using the microphone may require browser permissions.'},
  {route:'me',target:'[data-guide="me-settings"]',title:'Manage Your Account and Settings',sections:[
    {heading:'Account and Care',body:'Use Me to manage your profile, sign-in options, and care contacts.',guestBody:'Use Me to manage account access and care contacts.'},
    {heading:'Reminders and Preferences',body:'Adjust reminders, language, voice, text size, and privacy settings.'},
  ],guestNote:true},
];

function targetBounds(target:HTMLElement):DOMRect|null {
  const visible=[target,...Array.from(target.querySelectorAll<HTMLElement>(':scope > *'))]
    .filter(element=>!element.closest('[hidden]')&&getComputedStyle(element).display!=='none'&&getComputedStyle(element).visibility!=='hidden')
    .map(element=>element.getBoundingClientRect())
    .filter(rect=>rect.width>0&&rect.height>0);
  if(!visible.length)return null;
  const left=Math.min(...visible.map(rect=>rect.left)),top=Math.min(...visible.map(rect=>rect.top));
  const right=Math.max(...visible.map(rect=>rect.right)),bottom=Math.max(...visible.map(rect=>rect.bottom));
  return {left,top,right,bottom,width:right-left,height:bottom-top,x:left,y:top,toJSON:()=>({left,top,right,bottom,width:right-left,height:bottom-top,x:left,y:top})} as DOMRect;
}

export function OnboardingGuide({owner,replay=false,guest=false,activeRoute,originRoute,onNavigate,onRestore,onClose}:{
  owner:string;replay?:boolean;guest?:boolean;activeRoute:string;originRoute:string;
  onNavigate:(route:string)=>void;onRestore:()=>void;onClose:(restoreOrigin:boolean)=>void;
}) {
  const {t,language,speechRate}=useLanguage();
  const [index,setIndex]=useState(()=>replay?0:readTour(owner).step);
  const [complete,setComplete]=useState(false);
  const [rect,setRect]=useState<DOMRect|null>(null);
  const content=useRef<HTMLDivElement>(null);
  const completionAction=useRef<HTMLButtonElement>(null);
  const tts=useRef<BrowserTts|null>(null);
  const observer=useRef<ResizeObserver|null>(null);
  const routeReady=useRef(false),previousRoute=useRef(activeRoute);
  const [narrationEnabled,setNarrationEnabled]=useState(false),[speechError,setSpeechError]=useState(false);
  if(!tts.current){
    const synthesis=typeof window!=='undefined'?window.speechSynthesis:undefined;
    tts.current=new BrowserTts(synthesis,typeof SpeechSynthesisUtterance==='undefined'?undefined:text=>new SpeechSynthesisUtterance(text));
  }
  const step=steps[index]??steps[0]!;
  const canSpeak=typeof window!=='undefined'&&typeof window.speechSynthesis!=='undefined'&&typeof SpeechSynthesisUtterance!=='undefined';
  const guestNote=Boolean(guest&&step.guestNote);
  const spokenText=[t(step.title),...step.sections.flatMap(section=>[t(section.heading),t(guest&&section.guestBody?section.guestBody:section.body)]),...(step.note?[t(step.note)]:[]),...(guestNote?[t('In Guest Mode, you can link an email to keep access to current records or sign in to an existing account. Accounts are not merged.')]:[])].join('. ');

  useEffect(()=>{if(!replay&&!complete)saveTour(owner,{version:5,status:'in_progress',step:index});},[owner,index,replay,complete]);
  useEffect(()=>{
    if(!routeReady.current){routeReady.current=true;if(activeRoute!==steps[index]?.route)onNavigate(steps[index]!.route);previousRoute.current=activeRoute;return;}
    if(previousRoute.current===activeRoute)return;
    previousRoute.current=activeRoute;
    if(complete||activeRoute===steps[index]?.route)return;
    if(activeRoute===originRoute){onClose(false);return;}
    const matches=steps.map((item,stepIndex)=>item.route===activeRoute?stepIndex:-1).filter(stepIndex=>stepIndex>=0);
    if(matches.length){
      const nearest=matches.reduce((best,current)=>Math.abs(current-index)<Math.abs(best-index)?current:best,matches[0]!);
      setIndex(nearest);return;
    }
    onClose(false);
  },[activeRoute,complete,originRoute,index,onClose,onNavigate]);

  // The toggle is a guide-session preference, independent of utterance completion.
  useEffect(()=>{
    setSpeechError(false);
    if(!narrationEnabled||complete)return;
    tts.current?.play(spokenText,language,speechRate,()=>undefined,()=>setSpeechError(true));
    return()=>tts.current?.stop();
  },[narrationEnabled,spokenText,language,speechRate,complete]);
  useEffect(()=>()=>{tts.current?.stop();observer.current?.disconnect();},[]);
  useEffect(()=>{
    if(complete){setRect(null);completionAction.current?.focus();return;}
    if(typeof content.current?.scrollTo==='function')content.current.scrollTo({top:0,behavior:'instant'});
    setRect(null);observer.current?.disconnect();
    let live=true,scrolled=false;
    const refresh=()=>{
      if(!live)return;
      const element=document.querySelector<HTMLElement>(step.target);
      if(!element){setRect(null);return;}
      const bounds=targetBounds(element);
      if(!bounds){setRect(null);return;}
      if(!scrolled){
        scrolled=true;
        const scrollTarget=element.getBoundingClientRect().width>0?element:element.querySelector<HTMLElement>(':scope > *');
        const bounds=scrollTarget?targetBounds(scrollTarget):null;
        const headerBottom=document.querySelector<HTMLElement>('.companion-header')?.getBoundingClientRect().bottom??0;
        const dialogTop=document.querySelector<HTMLElement>('.onboarding-tour .bottom-sheet')?.getBoundingClientRect().top??window.innerHeight;
        const topSlotStart=headerBottom+8,topSlotEnd=dialogTop-8;
        if(bounds&&bounds.height<=topSlotEnd-topSlotStart){
          scrollTarget?.scrollIntoView?.({block:'start',inline:'nearest',behavior:'instant'});
          const moved=scrollTarget?.getBoundingClientRect();if(moved)window.scrollBy({top:moved.top-topSlotStart,behavior:'instant'});
        }else scrollTarget?.scrollIntoView?.({block:'nearest',inline:'nearest',behavior:'instant'});
      }
      setRect(targetBounds(element));
      observer.current?.disconnect();
      if(typeof ResizeObserver!=='undefined'){
        observer.current=new ResizeObserver(()=>setRect(targetBounds(element)));
        observer.current.observe(element);
      }
    };
    const mutations=new MutationObserver(refresh);
    mutations.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['hidden','class','style']});
    const deadline=window.setTimeout(()=>{mutations.disconnect();refresh();},1800);
    const reposition=()=>refresh();
    window.addEventListener('resize',reposition);window.addEventListener('scroll',reposition,true);
    window.visualViewport?.addEventListener('resize',reposition);
    refresh();
    return()=>{live=false;window.clearTimeout(deadline);mutations.disconnect();observer.current?.disconnect();window.removeEventListener('resize',reposition);window.removeEventListener('scroll',reposition,true);window.visualViewport?.removeEventListener('resize',reposition);};
  },[step.target,complete]);

  function stopSpeech(){tts.current?.stop();setNarrationEnabled(false);}
  function exit(restoreOrigin=true){stopSpeech();if(!replay)saveTour(owner,{version:5,status:'skipped',step:index});onClose(restoreOrigin);}
  function completeGuide(){
    stopSpeech();if(!replay)saveTour(owner,{version:5,status:'completed',step:index});
    onRestore();setComplete(true);
  }
  function goToStep(next:number){
    const bounded=Math.max(0,Math.min(ONBOARDING_STEP_COUNT-1,next));
    setIndex(bounded);const destination=steps[bounded]!.route;if(destination!==activeRoute)onNavigate(destination);
  }
  function toggleSpeech(){
    if(narrationEnabled){stopSpeech();return;}
    if(!canSpeak){setSpeechError(true);return;}
    setSpeechError(false);setNarrationEnabled(true);
  }

  const progressStyle={'--guide-progress':`${((index+1)/ONBOARDING_STEP_COUNT)*100}%`} as CSSProperties;
  if(typeof document==='undefined')return null;
  return createPortal(<div className="onboarding-tour" data-has-target={Boolean(rect)} data-complete={complete||undefined}>
    <BottomSheet title={t(complete?"You're All Set!":'Getting Started')} dismissible={false} escapeDismissible onCancel={()=>exit(true)} className={`onboarding-dialog${complete?' onboarding-dialog--complete':''}`}>
      {!complete?<div className="guide-shell">
        <div className="guide-head-actions">
          <button type="button" className="guide-read-button" aria-label={t(narrationEnabled?'Stop Reading':'Read Aloud')} aria-pressed={narrationEnabled} disabled={!canSpeak} onClick={toggleSpeech}><Icon name={narrationEnabled?'close':'speaker'}/><span>{t(narrationEnabled?'Stop Reading':'Read Aloud')}</span></button>
          <button type="button" className="guide-close-button" aria-label={t('Close Guide')} title={t('Close Guide')} onClick={()=>exit(true)}><Icon name="close"/></button>
        </div>
        <div className="guide-progress-block">
          <p className="guide-progress" aria-live="polite">{index+1} / {ONBOARDING_STEP_COUNT} · {t(step.title)}</p>
          <div className="guide-progress-track" role="progressbar" aria-valuemin={1} aria-valuemax={ONBOARDING_STEP_COUNT} aria-valuenow={index+1} aria-label={t('Guide progress')} style={progressStyle}><span/></div>
        </div>
        <div className="guide-scroll" ref={content} key={index}>
          <h3>{t(step.title)}</h3>
          <div className="guide-sections">{step.sections.map(section=><section className="guide-section" key={section.heading}><h4>{t(section.heading)}</h4><p>{t(guest&&section.guestBody?section.guestBody:section.body)}</p></section>)}</div>
          {step.note?<p className="guide-note">{t(step.note)}</p>:null}
          {guestNote?<p className="guide-note">{t('In Guest Mode, you can link an email to keep access to current records or sign in to an existing account. Accounts are not merged.')}</p>:null}
          {!canSpeak?<p className="guide-audio-note" role="status">{t('Read-aloud is not supported by this browser.')}</p>:null}
          {speechError&&canSpeak?<p className="guide-audio-note" role="status">{t('Read-aloud is not supported by this browser.')}</p>:null}
        </div>
        <footer className="guide-footer">
          <button type="button" className="guide-skip" onClick={()=>exit(true)}>{t('Skip Guide')}</button>
          <div className="guide-step-actions">
            <button type="button" className="guide-back" disabled={index===0} onClick={()=>goToStep(index-1)}>{t('Guide Back')}</button>
            {index<ONBOARDING_STEP_COUNT-1?<button type="button" className="guide-next primary" onClick={()=>goToStep(index+1)}>{t('Guide Next')} <span aria-hidden="true">→</span></button>:<button type="button" className="guide-next primary" onClick={completeGuide}>{t('Guide Finish')}</button>}
          </div>
        </footer>
      </div>:<div className="guide-completion">
        <button type="button" className="guide-close-button guide-completion-close" aria-label={t('Close Guide')} title={t('Close Guide')} onClick={()=>exit(false)}><Icon name="close"/></button>
        <span className="guide-completion-icon" aria-hidden="true"><Icon name="check"/></span>
        <h3>{t("You're All Set!")}</h3>
        <p className="guide-completion-primary">{t("You've explored MediThread's main features.")}</p>
        <p>{t('We hope this guide helps you get started.')}</p>
        <p className="guide-completion-revisit">{t('You can reopen this guide anytime from Help & User Guide.')}</p>
        <button ref={completionAction} type="button" className="guide-completion-start primary" onClick={()=>exit(false)}>{t('Start Using MediThread')}</button>
      </div>}
    </BottomSheet>
    {rect?<div className="guide-highlight" aria-hidden="true" style={{left:rect.left-6,top:rect.top-6,width:rect.width+12,height:rect.height+12}}/>:null}
  </div>,document.body);
}
