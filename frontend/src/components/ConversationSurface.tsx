import {useEffect,useRef,type ReactNode} from 'react';
import {createPortal} from 'react-dom';
import {useLanguage} from '../language';
import {Icon} from './Icon';

/**
 * The Assistant owns its state; this surface only controls focus and placement.
 *
 * One size, one dismissal set. The previous Compact/Full toggle changed the
 * sheet's height but nothing else, so it asked the patient to make a decision
 * that had no consequence; the sheet now simply fits the visual viewport.
 */
export function ConversationSurface({open,workspace=false,onClose,locked,children,actions,navigation}:{open:boolean;workspace?:boolean;onClose?:(()=>void)|undefined;locked:boolean;children:ReactNode;actions?:ReactNode;navigation?:ReactNode}){
 const {t}=useLanguage();const panel=useRef<HTMLElement>(null);
 useEffect(()=>{if(!open)return;const previous=document.activeElement;const background=document.querySelector<HTMLElement>('[data-app-content]');const overflow=document.body.style.overflow;const priorInert=background?.inert;
  if(background)background.inert=true;document.body.style.overflow='hidden';
  const viewport=window.visualViewport;const size=()=>{panel.current?.style.setProperty('--conversation-height',`${viewport?.height??innerHeight}px`);panel.current?.style.setProperty('--keyboard-offset',`${Math.max(0,innerHeight-(viewport?.height??innerHeight)-(viewport?.offsetTop??0))}px`);};size();viewport?.addEventListener('resize',size);viewport?.addEventListener('scroll',size);
  panel.current?.querySelector<HTMLInputElement>('.composer-row input:not([type="file"])')?.focus();
  return()=>{if(background)background.inert=priorInert??false;document.body.style.overflow=overflow;viewport?.removeEventListener('resize',size);viewport?.removeEventListener('scroll',size);if(previous instanceof HTMLElement&&previous.isConnected&&previous!==document.body)previous.focus();else requestAnimationFrame(()=>document.querySelector<HTMLElement>('.today-assistant .composer-row input:not([type="file"]),.assistant-launcher')?.focus());};
 },[open]);
 if(workspace)return <section className="conversation-workspace" aria-label={t('Medication assistant')}><div className="conversation-toolbar"><strong>MediThread Assistant</strong><div className="conversation-actions">{actions}{onClose?<button className="icon-button" aria-label={t('Back')} title={t('Back')} disabled={locked} onClick={onClose}><Icon name="chevron-left"/></button>:null}</div></div><div className={`conversation-workspace__body${navigation?' conversation-workspace__body--with-history':''}${navigation?' conversation-workspace__body--history-open':''}`}>{navigation}{children}</div></section>;
 if(!open)return children;
 return createPortal(<div className="conversation-backdrop" onClick={event=>{if(event.target===event.currentTarget&&!locked)onClose?.();}}><section ref={panel} className="conversation-panel" role="dialog" aria-modal="true" aria-label={t('Medication assistant')} onKeyDown={event=>{
  if((event.target as HTMLElement).closest('.bottom-sheet'))return;
  if(event.key==='Escape'&&!locked){event.preventDefault();onClose?.();}
  if(event.key==='Tab'){const controls=[...(panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled):not([type="file"]),textarea,select,summary,[tabindex="0"]')??[])].filter(el=>el.getClientRects().length>0&&!el.closest('[hidden]'));const first=controls[0],last=controls[controls.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}}
 }}><div className="conversation-toolbar"><strong>MediThread Assistant</strong><div className="conversation-actions">{actions}<button className="icon-button" aria-label={t('Close conversation')} title={t('Close conversation')} disabled={locked} onClick={onClose}><Icon name="close"/></button></div></div>{children}</section></div>,document.body);
}
