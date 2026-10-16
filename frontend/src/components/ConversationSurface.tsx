import {useEffect,useRef,type ReactNode} from 'react';
import {createPortal} from 'react-dom';
import {useLanguage} from '../language';

/**
 * The Assistant owns its state; this surface only controls focus and placement.
 *
 * One size, one dismissal set. The previous Compact/Full toggle changed the
 * sheet's height but nothing else, so it asked the patient to make a decision
 * that had no consequence; the sheet now simply fits the visual viewport.
 */
export function ConversationSurface({open,onClose,locked,children}:{open:boolean;onClose?:(()=>void)|undefined;locked:boolean;children:ReactNode}){
 const {t}=useLanguage();const panel=useRef<HTMLElement>(null);
 useEffect(()=>{if(!open)return;const previous=document.activeElement;const background=document.querySelector<HTMLElement>('[data-app-content]');const overflow=document.body.style.overflow;const priorInert=background?.inert;
  if(background)background.inert=true;document.body.style.overflow='hidden';
  const viewport=window.visualViewport;const size=()=>{panel.current?.style.setProperty('--conversation-height',`${viewport?.height??innerHeight}px`);panel.current?.style.setProperty('--keyboard-offset',`${Math.max(0,innerHeight-(viewport?.height??innerHeight)-(viewport?.offsetTop??0))}px`);};size();viewport?.addEventListener('resize',size);viewport?.addEventListener('scroll',size);
  panel.current?.querySelector<HTMLInputElement>('.composer-row input')?.focus();
  return()=>{if(background)background.inert=priorInert??false;document.body.style.overflow=overflow;viewport?.removeEventListener('resize',size);viewport?.removeEventListener('scroll',size);if(previous instanceof HTMLElement&&previous.isConnected)previous.focus();};
 },[open]);
 if(!open)return children;
 return createPortal(<div className="conversation-backdrop" onClick={event=>{if(event.target===event.currentTarget&&!locked)onClose?.();}}><section ref={panel} className="conversation-panel" role="dialog" aria-modal="true" aria-label={t('Medication assistant')} onKeyDown={event=>{
  if((event.target as HTMLElement).closest('.bottom-sheet'))return;
  if(event.key==='Escape'&&!locked){event.preventDefault();onClose?.();}
  if(event.key==='Tab'){const controls=panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),textarea,select,summary,[tabindex="0"]');const first=controls?.[0],last=controls?.[controls.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}}
 }}><div className="conversation-toolbar"><strong>{t('Medication assistant')}</strong><button disabled={locked} onClick={onClose}>{t('Close conversation')}</button></div>{children}</section></div>,document.body);
}
