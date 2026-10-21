export const ONBOARDING_STEP_COUNT=6;
export type TourState={version:5;status:'in_progress'|'completed'|'skipped';step:number};
const key=(owner:string)=>`pharmascan.quick-start.v5:${owner}`;
const previousKey=(owner:string)=>`pharmascan.quick-start.v4:${owner}`;
function isTourState(value:unknown,version:number):value is {version:number;status:TourState['status'];step:number} {
  return Boolean(value&&typeof value==='object'&&'version' in value&&value.version===version&&'status' in value&&['in_progress','completed','skipped'].includes(String(value.status))&&'step' in value&&Number.isInteger(value.step)&&Number(value.step)>=0);
}
export function readTour(owner:string):TourState {
  try {
    const current:unknown=JSON.parse(localStorage.getItem(key(owner))??'null');
    if(isTourState(current,5)&&current.step<ONBOARDING_STEP_COUNT)return current as TourState;
    const previous:unknown=JSON.parse(localStorage.getItem(previousKey(owner))??'null');
    if(isTourState(previous,4)){
      const migrated:TourState={version:5,status:previous.status,step:0};
      try{localStorage.setItem(key(owner),JSON.stringify(migrated));}catch{/* Preserve the in-memory legacy decision if storage is read-only. */}
      return migrated;
    }
  }catch{/* Unavailable/corrupt browser storage must not mark a tour complete. */}
  return {version:5,status:'in_progress',step:0};
}
export function saveTour(owner:string,state:TourState):boolean {
  try{localStorage.setItem(key(owner),JSON.stringify(state));return true;}catch{return false;}
}
