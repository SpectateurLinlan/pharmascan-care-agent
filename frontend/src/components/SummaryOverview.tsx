import type {ReviewSummary} from '../api/client';
import {useLanguage} from '../language';

/** Factual overview of a fetched report; no inferred adherence or clinical findings. */
export function SummaryOverview({data,questions=data.questions}:{data:ReviewSummary;questions?:string[]}){
 const {language,t}=useLanguage(),zh=language==='zh';
 const medicines=new Set(data.medications.map(row=>row.medication_id)).size;
 const reports=data.reported_taken+data.reported_not_taken+data.unsure;
 const unrecorded=data.medications.reduce((sum,row)=>sum+row.without_report,0);
 return <section className="summary-overview">
  <h3>{zh?'简明概览':'Overview'}</h3>
  <p>{zh?`${medicines} 项药物 · ${reports} 条服药自述 · ${data.observations.length} 条健康观察`:`${medicines} medicines · ${reports} dose reports · ${data.observations.length} health observations`}</p>
  <h3>{zh?'记录要点':'Record highlights'}</h3>
  <p>{t('Patient reported taken')}: {data.reported_taken} · {t('Patient reported not taken')}: {data.reported_not_taken} · {t('Patient is unsure')}: {data.unsure}</p>
  <p>{zh?`${unrecorded} 个已生成的过去计划剂次尚未记录；不表示未服用。`:`${unrecorded} stored past scheduled doses have no report; this does not mean they were missed.`}</p>
  <h3>{zh?'待确认事项及下一步':'Items to confirm and next steps'}</h3>
  {questions.length?<ul>{questions.map(question=><li key={question}>{t(question)}</li>)}</ul>:<p>{zh?'本次记录没有生成额外问题；您可以补充希望向医护人员了解的事项。':'No additional questions were generated from these records. Add anything you want to discuss with your healthcare professional.'}</p>}
 </section>;
}
