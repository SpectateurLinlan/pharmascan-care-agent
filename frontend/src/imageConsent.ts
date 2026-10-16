import {useEffect,useState} from 'react';

/** Device-local processing permission, versioned and scoped to the authenticated owner. */
export function useImageConsent(owner:string){
 const key=owner?`pharmascan.image-processing.v1.${owner}`:null;
 const read=()=>({key,allowed:!!key&&localStorage.getItem(key)==='allowed'});
 const [state,setState]=useState(read);
 useEffect(()=>{const sync=()=>setState(read());sync();window.addEventListener('pharmascan:image-consent',sync);window.addEventListener('storage',sync);return()=>{window.removeEventListener('pharmascan:image-consent',sync);window.removeEventListener('storage',sync);};},[key]);
 const allowed=state.key===key&&state.allowed;
 function change(value:boolean){if(key){if(value)localStorage.setItem(key,'allowed');else localStorage.removeItem(key);}setState({key,allowed:value});if(key)window.dispatchEvent(new Event('pharmascan:image-consent'));}
 return [allowed,change] as const;
}
