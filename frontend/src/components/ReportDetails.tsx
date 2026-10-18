import {useEffect,useRef,type ReactNode} from 'react';
import {useLanguage} from '../language';

/** Disclosure is visual only: print includes every fetched detail, even when closed. */
export function ReportDetails({children}:{children:ReactNode}){
 const {t}=useLanguage();const ref=useRef<HTMLDetailsElement>(null);
 useEffect(()=>{
  let previous=false;
  const before=()=>{if(ref.current){previous=ref.current.open;ref.current.open=true;}};
  const after=()=>{if(ref.current)ref.current.open=previous;};
  window.addEventListener('beforeprint',before);window.addEventListener('afterprint',after);
  return()=>{window.removeEventListener('beforeprint',before);window.removeEventListener('afterprint',after);};
 },[]);
 return <details className="report-details" ref={ref}><summary>{t('Detailed records and sources')}</summary><div className="report-details__content report-reader" role="region" aria-label={t('Detailed records and sources')} tabIndex={0}>{children}</div></details>;
}
