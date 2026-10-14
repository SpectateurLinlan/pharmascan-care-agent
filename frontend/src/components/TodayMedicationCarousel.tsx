import {useEffect, useRef, useState, type ReactNode} from 'react';
import type {MedicationSummary} from '../api/client';
import {useLanguage} from '../language';

/** Presentation only: each slide retains the existing authenticated Today flow. */
export function TodayMedicationCarousel({medications, focusRegimenId, children}: {
  medications:MedicationSummary[]; focusRegimenId:string|null; children:(medication:MedicationSummary)=>ReactNode;
}) {
  const {t} = useLanguage();
  const track = useRef<HTMLDivElement>(null);
  const [selected, setSelected] = useState(0);
  const active = Math.min(selected, Math.max(0, medications.length - 1));
  function choose(index:number) {
    const next = Math.max(0, Math.min(index, medications.length - 1));
    setSelected(next);
    track.current?.scrollTo({left:next * track.current.clientWidth,behavior:'auto'});
  }
  useEffect(()=>{
    if (!focusRegimenId) return;
    const index = medications.findIndex(row=>row.regimen_id===focusRegimenId);
    if (index >= 0) {setSelected(index);track.current?.scrollTo({left:index * track.current.clientWidth,behavior:'auto'});}
  },[focusRegimenId,medications]);
  useEffect(()=>{
    const element=track.current;
    if(!element || typeof ResizeObserver==='undefined')return;
    const observer=new ResizeObserver(()=>element.scrollTo({left:active * element.clientWidth,behavior:'auto'}));
    observer.observe(element);return()=>observer.disconnect();
  },[active]);
  return <section className="card today-overview" aria-label={t("Today's medication")}>
    <div className="today-overview-heading"><h2>{t("Today's medication")}</h2><span>{medications.length} {t('medicines')}</span></div>
    {medications.length>1?<><div className="medicine-overview" data-count={medications.length} role="group" aria-label={t('All current medicines')}>
      {medications.map((row,index)=><button key={row.regimen_id} className="medicine-chip" aria-pressed={index===active} onClick={()=>choose(index)}>
        <strong>{row.display_name}</strong>{' '}<span>{row.dose_amount??t('Not specified')} {t(row.dose_unit??'')} · {row.is_prn?t('As needed'):row.frequency_rule?.local_times.join(', ')??t('Not specified')}</span>
      </button>)}
    </div>
    <div className="medicine-pager"><button aria-label={t('Previous medicine')} disabled={active===0} onClick={()=>choose(active-1)}>‹</button>
      <p aria-live="polite">{active+1} / {medications.length} · {t('Swipe or tap a medicine to view')}</p>
      <button aria-label={t('Next medicine')} disabled={active===medications.length-1} onClick={()=>choose(active+1)}>›</button>
    </div></>:null}
    <div className="medicine-track" ref={track} onScroll={event=>{
      const element=event.currentTarget;
      if(element.clientWidth>0)setSelected(Math.min(medications.length-1,Math.max(0,Math.round(element.scrollLeft/element.clientWidth))));
    }}>
      {medications.map((row,index)=><div key={row.regimen_id} className="medicine-slide" aria-hidden={index!==active} ref={element=>{if(element)element.inert=index!==active;}}>
        {children(row)}
      </div>)}
    </div>
  </section>;
}
