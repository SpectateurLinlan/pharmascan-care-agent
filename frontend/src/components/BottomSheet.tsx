import {createPortal} from 'react-dom';
import {useEffect,useRef,type ReactNode} from 'react';
/** Presentation only: callers obtain and submit a real server challenge. */
export function BottomSheet({title,onCancel,busy=false,dismissible=true,children}:{title:string;onCancel:()=>void;busy?:boolean;dismissible?:boolean;children:ReactNode}){
 const dialog=useRef<HTMLElement>(null);
 useEffect(()=>{const contain=()=>{if(!dismissible&&!dialog.current?.contains(document.activeElement))dialog.current?.focus();};const keys=(event:KeyboardEvent)=>{if(!dismissible&&event.key==='Tab'&&!dialog.current?.contains(document.activeElement)){event.preventDefault();dialog.current?.focus();}};document.addEventListener('focusin',contain);window.addEventListener('focus',contain);document.addEventListener('keydown',keys,true);return()=>{document.removeEventListener('focusin',contain);window.removeEventListener('focus',contain);document.removeEventListener('keydown',keys,true);};},[dismissible]);
 useEffect(()=>{const previous=document.activeElement;const overflow=document.body.style.overflow;document.body.style.overflow='hidden';dialog.current?.focus();return()=>{document.body.style.overflow=overflow;if(previous instanceof HTMLElement)previous.focus();};},[]);
 const content=<div className="modal-backdrop sheet-backdrop" onPointerDown={event=>{if(!dismissible&&event.target===event.currentTarget){event.preventDefault();dialog.current?.focus();}}} onClick={event=>{if(event.target===event.currentTarget&&!busy&&dismissible)onCancel();}}><section ref={dialog} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title} className="bottom-sheet" onKeyDown={event=>{
  if(event.key==='Escape'){event.preventDefault();event.stopPropagation();if(!busy&&dismissible)onCancel();}
  if(event.key==='Tab'){const controls=dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input,textarea,select,[tabindex="0"]');const first=controls?.[0],last=controls?.[controls.length-1];if(event.shiftKey&&(document.activeElement===first||document.activeElement===dialog.current)){event.preventDefault();last?.focus();}else if(!event.shiftKey&&(document.activeElement===last||document.activeElement===dialog.current)){event.preventDefault();first?.focus();}}
 }}><div className="sheet-handle" aria-hidden="true"/><h2>{title}</h2>{children}</section></div>;
 return dismissible?createPortal(content,document.body):content;
}
