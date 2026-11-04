/** Bound waiting even when authentication or a response body ignores abort. */
export async function abortable<T>(operation:()=>Promise<T>,signal:AbortSignal):Promise<T>{
 if(signal.aborted)throw new DOMException('Request aborted','AbortError');
 let abort!:()=>void;
 const stopped=new Promise<never>((_resolve,reject)=>{
  abort=()=>reject(new DOMException('Request aborted','AbortError'));
  signal.addEventListener('abort',abort,{once:true});
 });
 try{return await Promise.race([operation(),stopped]);}
 finally{signal.removeEventListener('abort',abort);}
}
