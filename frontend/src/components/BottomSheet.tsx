import {useEffect,useRef,type ReactNode} from 'react';
/** Presentation only: callers obtain and submit a real server challenge. */
export function BottomSheet({title,onCancel,busy=false,children}:{title:string;onCancel:()=>void;busy?:boolean;children:ReactNode}){
 const dialog=useRef<HTMLElement>(null);
 useEffect(()=>{const previous=document.activeElement;const overflow=document.body.style.overflow;document.body.style.overflow='hidden';dialog.current?.focus();return()=>{document.body.style.overflow=overflow;if(previous instanceof HTMLElement)previous.focus();};},[]);
 return <div className="modal-backdrop sheet-backdrop" onClick={event=>{if(event.target===event.currentTarget&&!busy)onCancel();}}><section ref={dialog} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title} className="bottom-sheet" onKeyDown={event=>{
  if(event.key==='Escape'&&!busy)onCancel();
  if(event.key==='Tab'){const controls=dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input,textarea,select,[tabindex="0"]');const first=controls?.[0],last=controls?.[controls.length-1];if(event.shiftKey&&(document.activeElement===first||document.activeElement===dialog.current)){event.preventDefault();last?.focus();}else if(!event.shiftKey&&(document.activeElement===last||document.activeElement===dialog.current)){event.preventDefault();first?.focus();}}
 }}><div className="sheet-handle" aria-hidden="true"/><h2>{title}</h2>{children}</section></div>;
}
