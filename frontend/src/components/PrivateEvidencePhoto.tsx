import {useEffect,useState} from 'react';
import {api,type GalleryImage} from '../api/client';
import {useLanguage} from '../language';

/** Authenticated photo acquisition; object URLs exist only while this view is mounted. */
export function PrivateEvidencePhoto({photo,onOpen}:{photo:GalleryImage;onOpen?:()=>void}){
 const {t}=useLanguage();const [url,setUrl]=useState(''),[failed,setFailed]=useState(false),[retry,setRetry]=useState(0);
 // Skip authenticated acquisition when StrictMode/navigation disposes the effect before it starts.
 useEffect(()=>{let live=true,objectUrl='';setFailed(false);setUrl('');void Promise.resolve().then(()=>{if(!live)return;return api.referencePhoto(photo.id).then(blob=>{if(live){objectUrl=URL.createObjectURL(blob);setUrl(objectUrl);}}).catch(()=>{if(live)setFailed(true);});});return()=>{live=false;if(objectUrl)URL.revokeObjectURL(objectUrl);};},[photo.id,retry]);
 const alt=t(photo.image_kind==='loose_pill'?'Pill reference photo':photo.image_kind==='blister'?'Blister reference photo':'Packaging/source photo');
 return url?onOpen?<button type="button" className="private-photo-open" onClick={onOpen} aria-label={`${t('Open photo preview')}: ${alt}`}><img loading="lazy" className="gallery-thumbnail" src={url} alt={alt}/></button>:<img loading="lazy" className="gallery-thumbnail" src={url} alt={alt}/>:failed?<button type="button" onClick={()=>setRetry(value=>value+1)}>{t('Retry loading photo')}</button>:<span role="status">{t('Loading photo…')}</span>;
}
