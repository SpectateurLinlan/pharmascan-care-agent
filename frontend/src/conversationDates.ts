import type {ConversationEntry} from './api/client';

export function localDateKey(stamp:string,timeZone:string):string{
 const date=new Date(stamp);
 if(!Number.isFinite(date.getTime()))return 'unknown';
 const parts=new Intl.DateTimeFormat('en-CA',{timeZone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(date);
 const part=(type:string)=>parts.find(row=>row.type===type)!.value;
 return `${part('year')}-${part('month')}-${part('day')}`;
}

/** Date headings are presentation only, never inferred session boundaries. */
export function conversationDateGroups(entries:ConversationEntry[],timeZone:string,now:Date){
 const today=localDateKey(now.toISOString(),timeZone);
 const [year,month,day]=today.split('-').map(Number);
 const yesterday=new Date(Date.UTC(year!,month!-1,day!-1)).toISOString().slice(0,10);
 const groups=new Map<string,ConversationEntry[]>();
 for(const row of entries){const key=localDateKey(row.created_at,timeZone);groups.set(key,[...(groups.get(key)??[]),row]);}
 return [...groups].sort(([a],[b])=>b.localeCompare(a)).map(([date,rows])=>({date,relative:date===today?'Today':date===yesterday?'Yesterday':null,rows}));
}
