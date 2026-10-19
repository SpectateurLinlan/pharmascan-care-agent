import type {ToolTrace} from '../api/client';
import {useLanguage} from '../language';

export function AnswerSources({traces}:{traces:ToolTrace[]}){
 const {t,language}=useLanguage();const links=new Map<string,{label:string;excerpts:string[]}>();
 for(const trace of traces){
  const knowledge=trace.payload?.general_knowledge;
  if(!knowledge||typeof knowledge!=='object'||!('status' in knowledge)||knowledge.status!=='matched'||!('sources' in knowledge)||!Array.isArray(knowledge.sources))continue;
  for(const source of knowledge.sources){
   if(!source||typeof source!=='object'||!('url' in source)||typeof source.url!=='string')continue;
   try{const url=new URL(source.url);if(url.protocol!=='https:'||url.hostname!=='dailymed.nlm.nih.gov')continue;
    const date='effective_time' in source?String(source.effective_time):'';const version='version' in source?String(source.version):'';
    const name='label_name' in source&&typeof source.label_name==='string'?source.label_name:'';
    const excerpts='sections' in source&&Array.isArray(source.sections)?source.sections.flatMap((section:unknown)=>
     section&&typeof section==='object'&&'field' in section&&section.field==='indications_and_usage'&&'text' in section&&typeof section.text==='string'?[section.text]:[]):[];
    links.set(url.href,{label:`${t('US drug label')}${name?` — ${name}`:''} · ${date} · v${version}`,excerpts});
   }catch{continue;}
  }
 }
 return links.size?<details className="answer-sources"><summary>{t('Knowledge sources')}</summary>
  <p>{language==='zh'?'以下是支持一般用途的美国来源标签；来源商品、剂型和释放形式不代表您持有的具体产品，也不证明新加坡批准用途。':'These US source labels support general uses. Their brands, forms and release types do not identify your product or establish Singapore-approved uses.'}</p>
  <ul>{[...links].map(([url,{label,excerpts}])=><li key={url}><a href={url} target="_blank" rel="noopener noreferrer">{label}</a>
   {excerpts.length>0&&<details><summary>{language==='zh'?'查看用途原文（来源标签适用范围）':'Original use excerpt (source label scope)'}</summary>{excerpts.map((text,index)=><p key={index}>{text}</p>)}</details>}
  </li>)}</ul></details>:null;
}
