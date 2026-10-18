import type {ToolTrace} from '../api/client';
import {useLanguage} from '../language';

export function AnswerSources({traces}:{traces:ToolTrace[]}){
 const {t}=useLanguage();const links=new Map<string,string>();
 for(const trace of traces){
  const knowledge=trace.payload?.general_knowledge;
  if(!knowledge||typeof knowledge!=='object'||!('status' in knowledge)||knowledge.status!=='matched'||!('sources' in knowledge)||!Array.isArray(knowledge.sources))continue;
  for(const source of knowledge.sources){
   if(!source||typeof source!=='object'||!('url' in source)||typeof source.url!=='string')continue;
   try{const url=new URL(source.url);if(url.protocol!=='https:'||url.hostname!=='dailymed.nlm.nih.gov')continue;
    const date='effective_time' in source?String(source.effective_time):'';const version='version' in source?String(source.version):'';
    links.set(url.href,`${t('US drug label')} · ${date} · v${version}`);
   }catch{continue;}
  }
 }
 return links.size?<details className="answer-sources"><summary>{t('Knowledge sources')}</summary><ul>{[...links].map(([url,label])=><li key={url}><a href={url} target="_blank" rel="noopener noreferrer">{label}</a></li>)}</ul></details>:null;
}
