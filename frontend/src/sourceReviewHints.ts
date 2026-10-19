import type {SourcePreview} from './api/client';

/** Quoted candidates only: never fill a plan, infer dates, or confirm instructions. */
export function sourceReviewHints(candidates:SourcePreview['candidates']) {
 const clocks=new Set<string>(),release=new Set<string>(),duration=new Set<string>();
 for(const candidate of candidates){
  const evidence=candidate.regimen_evidence;
  const text=[...(candidate.product.source_lines??[]),evidence.directions?.value,evidence.directions?.line,evidence.instructions?.text,evidence.instructions?.line].filter(Boolean).join('\n');
  for(const match of text.matchAll(/(?:\bat\s+|于\s*|在\s*)([01]?\d|2[0-3]):([0-5]\d)(?!\d)(?:\s*([ap]\.?m\.?))?/gi)){
   const hour=match[1],minute=match[2];if(hour===undefined||minute===undefined)continue;
   let clockHour=Number(hour);const meridiem=match[3]?.toLowerCase();
   if(meridiem){if(clockHour<1||clockHour>12)continue;clockHour=clockHour%12+(meridiem.startsWith('p')?12:0);}
   clocks.add(`${String(clockHour).padStart(2,'0')}:${minute}`);
  }
  for(const match of text.matchAll(/\b(?:ER|XR|SR|DR|extended[- ]release|modified[- ]release|delayed[- ]release)\b|缓释|緩釋|肠溶/gi))release.add(match[0]);
  for(const match of text.matchAll(/\bfor\s+\d{1,3}\s+days?\b|(?:服用|连用|连续)\s*\d{1,3}\s*天/gi))duration.add(match[0]);
 }
 return {clocks:[...clocks],release:[...release],duration:[...duration]};
}
