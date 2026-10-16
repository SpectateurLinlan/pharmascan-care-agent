export type TourState={version:2;status:'in_progress'|'completed'|'skipped';step:number};
const key=(owner:string)=>`pharmascan.quick-start.v2:${owner}`;
export function readTour(owner:string):TourState {
  try {const value:unknown=JSON.parse(localStorage.getItem(key(owner))??'null');
    if(value&&typeof value==='object'&&'version' in value&&value.version===2&&'status' in value&&['in_progress','completed','skipped'].includes(String(value.status))&&'step' in value&&Number.isInteger(value.step)&&Number(value.step)>=0&&Number(value.step)<7)return value as TourState;
  }catch{/* Unavailable/corrupt browser storage must not mark a tour complete. */}
  return {version:2,status:'in_progress',step:0};
}
export function saveTour(owner:string,state:TourState):boolean {
  try{localStorage.setItem(key(owner),JSON.stringify(state));return true;}catch{return false;}
}
