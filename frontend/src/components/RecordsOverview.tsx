import {useLanguage} from '../language';
import {Row,RowGroup} from '../ui/primitives';
import {LateDoseFollowUps} from './LateDoseFollowUps';
import {Icon} from './Icon';

export function RecordsOverview({lateReportsEnabled,onOpenSummary,onOpenMedicationRecords,onOpenArea}:{lateReportsEnabled:boolean;onOpenSummary:(period:'week'|'month'|'course')=>void;onOpenMedicationRecords:()=>void;onOpenArea:(area:'health-notes'|'adherence-barriers'|'care-tasks'|'medication-review')=>void}){
 const {t}=useLanguage();
 return <>
  <RowGroup title="Medication and health summary" className="records-summary records-summary--highlight">
   <div className="period-actions records-summary-actions">{(['week','month','course'] as const).map(period=><button key={period} type="button" onClick={()=>onOpenSummary(period)}>{t(period==='week'?'This week':period==='month'?'This month':'By medication plan')}</button>)}</div>
  </RowGroup>
  <details className="records-pending-disclosure">
   <summary>
    <span className="records-pending-disclosure__copy">
     <strong data-guide="medication-records">{t('Medication reports to confirm')}</strong>
     <span>{t('Open to review scheduled doses from the past 7 days; eligibility still applies.')}</span>
    </span>
    <span className="records-pending-disclosure__chevron"><Icon name="chevron-right"/></span>
   </summary>
   <LateDoseFollowUps enabled={lateReportsEnabled} showHeading={false}/>
  </details>
  <section className="card records-medication-history-card">
   <button type="button" className="records-medication-history-link" onClick={onOpenMedicationRecords}>
    <span className="records-history-icon"><Icon name="clipboard"/></span>
    <span className="records-medication-history-link__copy"><strong>{t('My medication records')}</strong><span>{t('View saved dose reports and past scheduled doses by medicine and date.')}</span></span>
    <Icon name="chevron-right"/>
   </button>
  </section>
  <RowGroup title="Health records and ongoing care" hint="Choose an area to review or update." className="records-navigation-group">
   <Row icon="heart" title="My health notes" hint="How you have been feeling" onClick={()=>onOpenArea('health-notes')}/>
   <Row icon="alert" title="Medication difficulties" hint="Challenges managing medicines" onClick={()=>onOpenArea('adherence-barriers')}/>
   <Row icon="calendar" title="Medication follow-ups" hint="Your care follow-ups" onClick={()=>onOpenArea('care-tasks')}/>
   <Row icon="clipboard" title="Medication review preparation" hint="Information for your next review" onClick={()=>onOpenArea('medication-review')}/>
  </RowGroup>
 </>;
}
