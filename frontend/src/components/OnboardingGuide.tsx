import {useEffect, useRef, useState, type CSSProperties} from 'react';
import {useLanguage} from '../language';
import {BottomSheet} from './BottomSheet';
import {readTour,saveTour} from '../onboarding';

const steps = [
  {target:'[data-guide="today"]', title:'Your daily companion', body:'Today shows your reviewed schedule. Start by adding your medicine if your list is empty.'},
  {target:'[data-guide="medicines"]', title:'Add and manage medicines', body:'Open Medicines to read a label or enter instructions. Review and activate the plan before it appears in Today.'},
  {target:'.composer-row .photo-button', title:'Use a photo', body:'Attach a medication photo to your message. The app routes it to label reading or visual evidence, then the assistant can help with your question. A photo does not confirm identity or prove that a dose was taken.'},
  {target:'.composer-row', title:'Speak, review, then send', body:'Tap the microphone, allow speech recognition, then review or edit the words. Send is on the right. You can always type instead. Your browser may use an online speech service.'},
  {target:'[data-guide="records"]', title:'Record and review your reports', body:'After choosing I took it, confirm the separate summary to save your report. Cancel saves nothing. Records contains your reports and summaries; a report does not prove ingestion. Reminders are prompts, not changes to your plan.'},
  {target:'[data-guide="me"]', title:'Choose your voice settings', body:'Automatic reading is off by default. Turn on Read replies automatically in Language and speech if you want it. You can also use Play response and Stop audio. Browser voice is the default; cloud voice requires an explicit choice.'},
  {target:'[data-guide="me"]', title:'Your account and settings', body:'Me contains your account and settings categories. Open Medication reminders for reminders and device notifications, or Usage preferences for language, speech and text size. You can reopen this guide from Me → Help / User Guide.'},
] as const;

export function OnboardingGuide({owner,replay=false,onClose}: {owner:string;replay?:boolean;onClose:()=>void}) {
  const {t, preferences} = useLanguage();
  const [index, setIndex] = useState(()=>replay?0:readTour(owner).step);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const bubble = useRef<HTMLDivElement>(null);
  const [top, setTop] = useState(100);
  const step = steps[index]!;
  useEffect(()=>{if(!replay)saveTour(owner,{version:2,status:'in_progress',step:index});},[owner,index,replay]);
  function finish(status:'completed'|'skipped'){if(!replay)saveTour(owner,{version:2,status,step:index});onClose();}
  useEffect(() => {
    const target = document.querySelector<HTMLElement>(step.target);
    function position() {
      const bounds = target?.getBoundingClientRect() ?? null;
      setRect(bounds);
      const height = bubble.current?.closest('section')?.getBoundingClientRect().height ?? 360;
      const viewportHeight = window.visualViewport?.height ?? window.innerHeight;
      const below = bounds ? bounds.bottom + 14 : 90;
      const candidate = below + height < viewportHeight - 16 ? below : (bounds?.top ?? viewportHeight) - height - 14;
      setTop(Math.max(16, Math.min(candidate, viewportHeight - height - 16)));
    }
    position();
    const observer = new ResizeObserver(position);
    if (bubble.current) observer.observe(bubble.current);
    window.addEventListener('resize', position);
    window.addEventListener('scroll', position, true);
    window.visualViewport?.addEventListener('resize', position);
    return () => {
      observer.disconnect(); window.removeEventListener('resize', position);
      window.removeEventListener('scroll', position, true);
      window.visualViewport?.removeEventListener('resize', position);
    };
  }, [step.target]);
  const style = {'--guide-top':`${top}px`} as CSSProperties;
  return <div className="onboarding-tour" style={style}>
    <BottomSheet title={t('Quick start guide')} dismissible={false} onCancel={()=>undefined}>
      <div ref={bubble}>
        <p className="guide-progress" aria-live="polite">{index + 1} / {steps.length}</p>
        <h3>{t(step.title)}</h3><p>{t(step.body)}</p>
        {index === 5 ? <p className="guide-preferences">{t('Current settings')}: {t('Voice')} {t(preferences.voice_enabled ? 'On' : 'Off')} · {t('Read replies automatically')} {t(preferences.tts_autoplay ? 'On' : 'Off')}</p> : null}
        <div className="guide-actions">
          <button onClick={()=>finish('skipped')}>{t('Skip for now')}</button>
          {index > 0 ? <button onClick={()=>setIndex(index - 1)}>{t('Previous')}</button> : null}
          <button className="primary" onClick={()=>index === steps.length - 1 ? finish('completed') : setIndex(index + 1)}>{t(index === steps.length - 1 ? 'Finish' : 'Next')}</button>
        </div>

      </div>
    </BottomSheet>
    {rect ? <div className="guide-highlight" aria-hidden="true" style={{left:rect.left - 4,top:rect.top - 4,width:rect.width + 8,height:rect.height + 8}}/> : null}
  </div>;
}
