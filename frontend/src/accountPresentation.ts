import type {Account} from './api/auth';
/** Presentation fallback only; never changes the authenticated patient identity. */
export function accountDisplayName(account:Account|null,preferred:string|null|undefined,guest='Guest'):string {
 if(account?.kind!=='member')return guest;
 const name=preferred?.trim();
 return name&&!['guest','访客','guest demo'].includes(name.toLowerCase())?name:account.email?.split('@')[0]||'Your account';
}
