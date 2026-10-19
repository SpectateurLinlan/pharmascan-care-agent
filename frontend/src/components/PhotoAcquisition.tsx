import {useEffect,useRef,useState} from 'react';
import {useLanguage} from '../language';
import {Icon} from './Icon';

const MAX_IMAGE_BYTES=8_000_000;

/** Shared camera/file acquisition only. It never saves or assigns a medication. */
export function PhotoAcquisition({file,onFile,disabled=false}:{file:File|null;onFile:(file:File|null)=>void;disabled?:boolean}){
 const {t}=useLanguage();
 const filePicker=useRef<HTMLInputElement>(null),video=useRef<HTMLVideoElement>(null),streamRef=useRef<MediaStream|null>(null);
 const [stream,setStream]=useState<MediaStream|null>(null),[cameraBusy,setCameraBusy]=useState(false),[error,setError]=useState(''),[preview,setPreview]=useState('');
 useEffect(()=>{if(!video.current||!stream)return;video.current.srcObject=stream;void video.current.play().catch(()=>setError(t('Camera preview could not start. Try again or choose an existing photo.')));},[stream,t]);
 useEffect(()=>{if(!file){setPreview('');return;}const url=URL.createObjectURL(file);setPreview(url);return()=>URL.revokeObjectURL(url);},[file]);
 useEffect(()=>()=>{streamRef.current?.getTracks().forEach(track=>track.stop());streamRef.current=null;},[]);
 function stop(){streamRef.current?.getTracks().forEach(track=>track.stop());streamRef.current=null;setStream(null);setCameraBusy(false);}
 function accept(candidate:File|null){
  if(!candidate)return;
  if(!['image/png','image/jpeg'].includes(candidate.type)||candidate.size>MAX_IMAGE_BYTES){setError(t('Choose a PNG or JPEG image no larger than 8 MB.'));return;}
  setError('');onFile(candidate);
 }
 async function takePhoto(){
  setError('');
  if(!window.isSecureContext){setError(t('Camera access requires a secure connection (HTTPS or localhost). Choose an existing photo instead.'));return;}
  if(!navigator.mediaDevices?.getUserMedia){setError(t('Camera capture is not supported in this browser. Choose an existing photo instead.'));return;}
  setCameraBusy(true);
  try{
   // Call getUserMedia directly in the button's user gesture so Chromium can
   // display its permission prompt when the origin has not already been denied.
   const next=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'}},audio:false});
   streamRef.current=next;setStream(next);
  }catch(caught){
   const name=caught instanceof DOMException?caught.name:(caught as {name?:string}|null)?.name;
   const message=name==='NotAllowedError'||name==='PermissionDeniedError'?'Allow camera access in your browser settings, then try again. If access was previously denied, a new prompt may not appear.':
    name==='NotFoundError'||name==='DevicesNotFoundError'?'No camera was found on this device. Choose an existing photo instead.':
    name==='NotReadableError'||name==='TrackStartError'||name==='AbortError'?'The camera is in use or could not be read. Close other camera apps and try again, or choose a photo.':
    name==='OverconstrainedError'?'No camera is available for this capture. Choose an existing photo instead.':'Camera could not be started. Choose an existing photo instead.';
   setError(t(message));setCameraBusy(false);
  }
 }
 function capture(){
  const element=video.current;if(!element?.videoWidth||!element.videoHeight){setError(t('Camera preview is not ready yet. Try again or choose an existing photo.'));return;}
  const canvas=document.createElement('canvas');canvas.width=element.videoWidth;canvas.height=element.videoHeight;
  const context=canvas.getContext('2d');if(!context){setError(t('Could not capture this photo. Try again or choose an existing photo.'));return;}context.drawImage(element,0,0);
  canvas.toBlob(blob=>{if(blob){accept(new File([blob],'medication-photo.jpg',{type:'image/jpeg',lastModified:Date.now()}));stop();}else setError(t('Could not capture this photo. Try again or choose an existing photo.'));},'image/jpeg',0.92);
 }
 return <div className="photo-acquisition">
  <div className="gallery-capture-actions">
   <button type="button" onClick={()=>void takePhoto()} disabled={disabled||cameraBusy}><Icon name="camera"/>{t('Take photo')}</button>
   <button type="button" onClick={()=>filePicker.current?.click()} disabled={disabled}><Icon name="image"/>{t('Choose existing photo')}</button>
  </div>
  <input ref={filePicker} className="visually-hidden" type="file" accept="image/png,image/jpeg" aria-hidden="true" tabIndex={-1} aria-label={t('Choose a photo from device')} onChange={event=>{accept(event.target.files?.[0]??null);event.currentTarget.value='';}}/>
  {error?<p role="alert">{error}</p>:null}
  {stream?<div className="gallery-camera"><video ref={video} autoPlay playsInline muted aria-label={t('Camera preview')}/><div className="gallery-capture-actions"><button type="button" className="primary" onClick={capture}>{t('Capture photo')}</button><button type="button" onClick={stop}>{t('Cancel camera')}</button></div></div>:null}
  {file?<div className="gallery-selected-photo"><img className="photo-preview" src={preview} alt={t('Selected image preview')}/><div><p>{file.name}</p><small>{(file.size/1024/1024).toFixed(1)} MB · {t('PNG or JPEG, up to 8 MB')}</small></div><button type="button" disabled={disabled} onClick={()=>onFile(null)}>{t('Replace photo')}</button></div>:null}
 </div>;
}
