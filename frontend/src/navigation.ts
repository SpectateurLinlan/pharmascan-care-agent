import {useCallback, useEffect, useRef, useState} from 'react';

export const roots = ['today', 'medicines', 'records', 'me'] as const;
const parents: Record<string,string> = {
  'care-tasks':'today','adherence-barriers':'records','medication-review':'records',
  assistant:'today', check:'today', 'check-result':'check', 'add-method':'medicines', label:'add-method', manual:'add-method',
  'edit-medication':'medicine-detail', unfinished:'medicines', 'past-medicines':'medicines', gallery:'medicines', 'medicine-detail':'medicines',
  'health-notes':'records', 'summary-week':'records', 'summary-month':'records', 'summary-course':'records',
  profile:'me', account:'me', caregivers:'me', settings:'me', 'reminder-settings':'me',
  'language-settings':'me', accessibility:'me', privacy:'me', about:'me', feedback:'me', help:'me',
};
const normalize = (value:string) => value === 'history' ? 'records' : value;
function authCallback(){return /(?:access_token|refresh_token)=/.test(window.location.hash)||new URLSearchParams(window.location.search).has('code');}
function valid(value:string) {return roots.some(root=>root===value)||Object.hasOwn(parents,value);}
function initial():string[] {
  const route=normalize(window.location.hash.slice(1).split('?')[0]||'today');
  const stored:unknown=window.history.state?.careRoute;
  if(Array.isArray(stored)&&stored.length<=12&&stored.every(item=>typeof item==='string'&&valid(item))&&stored.at(-1)===route)return stored as string[];
  return valid(route)?[route]:['today'];
}
/** Root selection replaces only its current entry; child tasks retain their origin. */
export function useCareNavigation(blocked:boolean) {
  const [stack,setStack]=useState(initial);
  const current=useRef(stack);current.current=stack;
  const locked=useRef(blocked);locked.current=blocked;
  useEffect(()=>{
    // Let the identity SDK consume and scrub email/OAuth callbacks first.
    if(!authCallback())window.history.replaceState({...window.history.state,careRoute:current.current},'',`#${current.current.at(-1)}`);
    const pop=()=>{
      if(locked.current){window.history.pushState({careRoute:current.current},'',`#${current.current.at(-1)}`);return;}
      setStack(initial());
    };
    window.addEventListener('popstate',pop);return()=>window.removeEventListener('popstate',pop);
  },[]);
  const navigate=useCallback((value:string) => {
    const next=normalize(value);if(locked.current||authCallback()||!valid(next)||next===current.current.at(-1))return;
    const isRoot=roots.some(root=>root===next);
    const updated=isRoot?[next]:[...current.current,next].slice(-12);
    window.history[isRoot?'replaceState':'pushState']({careRoute:updated},'',`#${next}`);
    setStack(updated);document.documentElement.scrollTop=0;
  },[]);
  function back(){
    if(locked.current)return;
    if(stack.length>1)window.history.back();
    else {const parent=parents[stack[0]??'']??'today';window.history.replaceState({careRoute:[parent]},'',`#${parent}`);setStack([parent]);}
  }
  return {tab:stack.at(-1)??'today',navigate,back,isRoot:roots.some(root=>root===stack.at(-1))};
}
