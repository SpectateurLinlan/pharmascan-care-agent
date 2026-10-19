/** Calendar inputs are interpreted in the authenticated patient's IANA zone, never device time. */
export function localFields(value:string,zone:string){
 const parts=new Intl.DateTimeFormat('en-CA',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(value));
 const get=(key:string)=>parts.find(part=>part.type===key)?.value??'';
 return {date:`${get('year')}-${get('month')}-${get('day')}`,time:`${get('hour')}:${get('minute')}`};
}
export function patientInstant(date:string,time:string,zone:string):string|null {
 if(!/^\d{4}-\d{2}-\d{2}$/.test(date)||!/^\d{2}:\d{2}$/.test(time))return null;
 const nominal=Date.parse(`${date}T${time}:00Z`);if(!Number.isFinite(nominal))return null;
 const matches:string[]=[];
 for(let offset=-14*60;offset<=14*60;offset+=15){const value=new Date(nominal-offset*60000).toISOString();const local=localFields(value,zone);if(local.date===date&&local.time===time)matches.push(value);}
 // Ambiguous/nonexistent DST times require the patient to choose a different time.
 return matches.length===1?matches[0]??null:null;
}
