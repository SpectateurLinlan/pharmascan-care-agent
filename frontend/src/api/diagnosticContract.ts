/** Closed, credential-free development observation contract. No request/query/body data. */
export const diagnosticEvent='medithread:local-auth-response';
export const diagnosticPaths=['/api/me/medications','/api/me/regimens','/api/me/today-attention','/api/reminders/alerts'] as const;
export type DiagnosticPath=typeof diagnosticPaths[number];
export type FailureStage='none'|'missing_bearer'|'identity_rejected'|'identity_service_unavailable'|'legacy_identity_service_failure_401'|'data_api_auth_rejected'|'unknown';
export type AuthObservation={endpoint:DiagnosticPath;status:number;authorization_attached:boolean;failure_stage:FailureStage};
export function diagnosticFailureStage(status:number,message=''):FailureStage{
 if(status>=200&&status<300)return 'none';
 if(message==='A bearer access token is required for this endpoint')return 'missing_bearer';
 if(/^Access token rejected by the identity provider \(HTTP (401|403)\)$/.test(message))return 'identity_rejected';
 if(status===503&&message.startsWith('Identity verification '))return 'identity_service_unavailable';
 if(status===401&&message==='Could not verify the access token with the identity provider')return 'legacy_identity_service_failure_401';
 if(message==='Supabase rejected authenticated data access')return 'data_api_auth_rejected';
 return 'unknown';
}
export const localDiagnosticOrigin=(origin:string)=>['http://localhost:5173','http://127.0.0.1:5173'].includes(origin);
export function observeDiagnosticResponse(path:string,status:number,attached:boolean,message=''){
 if(!import.meta.env.DEV||typeof window==='undefined'||!window.location||typeof window.dispatchEvent!=='function'||!localDiagnosticOrigin(window.location.origin))return;
 const endpoint=path.split('?')[0];
 if(!diagnosticPaths.includes(endpoint as DiagnosticPath))return;
 window.dispatchEvent(new CustomEvent<AuthObservation>(diagnosticEvent,{detail:{endpoint:endpoint as DiagnosticPath,status,authorization_attached:attached,failure_stage:diagnosticFailureStage(status,message)}}));
}
