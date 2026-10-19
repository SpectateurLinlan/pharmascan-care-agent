import type {CareTask} from './api/care';

export type CareTaskViewStatus='pending'|'overdue'|'completed';
export type CareTaskStatusFilter='all'|CareTaskViewStatus;

export function taskView(task:CareTask,now=Date.now()):CareTaskViewStatus{
 if(['completed','cancelled'].includes(task.status))return 'completed';
 const due=Date.parse(task.due_at);
 return Number.isFinite(due)&&due<now?'overdue':'pending';
}

export function careTaskLocalDate(value:string,timezone:string):string|null{
 const instant=new Date(value);
 if(!Number.isFinite(instant.getTime()))return null;
 try{
  const parts=new Intl.DateTimeFormat('en-CA',{timeZone:timezone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(instant);
  const part=(type:Intl.DateTimeFormatPartTypes)=>parts.find(value=>value.type===type)?.value??'';
  const result=`${part('year')}-${part('month')}-${part('day')}`;
  return /^\d{4}-\d{2}-\d{2}$/.test(result)?result:null;
 }catch{return null;}
}

export function careTaskMonthDays(month:string):Array<string|null>{
 const match=/^(\d{4})-(\d{2})$/.exec(month);
 if(!match)return [];
 const year=Number(match[1]),monthNumber=Number(match[2]);
 if(monthNumber<1||monthNumber>12)return [];
 const firstDay=new Date(Date.UTC(year,monthNumber-1,1)).getUTCDay();
 const offset=(firstDay+6)%7;
 const count=new Date(Date.UTC(year,monthNumber,0)).getUTCDate();
 return Array.from({length:offset+count},(_,index)=>{
  if(index<offset)return null;
  return `${match[1]}-${match[2]}-${String(index-offset+1).padStart(2,'0')}`;
 });
}

export function shiftCareTaskMonth(month:string,delta:number):string{
 const match=/^(\d{4})-(\d{2})$/.exec(month);
 if(!match||!Number.isInteger(delta))return month;
 const shifted=new Date(Date.UTC(Number(match[1]),Number(match[2])-1+delta,1));
 return `${shifted.getUTCFullYear()}-${String(shifted.getUTCMonth()+1).padStart(2,'0')}`;
}

export function sortCareTasks(rows:CareTask[],now=Date.now()):CareTask[]{
 const rank:Record<CareTaskViewStatus,number>={overdue:0,pending:1,completed:2};
 return [...rows].sort((left,right)=>{
  const leftStatus=taskView(left,now),rightStatus=taskView(right,now);
  if(leftStatus!==rightStatus)return rank[leftStatus]-rank[rightStatus];
  const leftDue=Date.parse(left.due_at),rightDue=Date.parse(right.due_at);
  if(!Number.isFinite(leftDue))return Number.isFinite(rightDue)?1:0;
  if(!Number.isFinite(rightDue))return -1;
  return leftStatus==='overdue'?rightDue-leftDue:leftDue-rightDue;
 });
}
