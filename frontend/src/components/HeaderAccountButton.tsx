import {useEffect, useState} from 'react';
import {accountAuth, type Account, type AccountPort} from '../api/auth';
import {useLanguage} from '../language';

export function HeaderAccountButton({ready, onOpen, auth = accountAuth}: {ready:boolean; onOpen:()=>void; auth?:AccountPort}) {
  const {t} = useLanguage();
  const [kind, setKind] = useState<Account['kind'] | null>(null);
  useEffect(() => {
    if (!ready) return;
    let live = true;
    void auth.account().then(account=>{if (live) setKind(account.kind);}).catch(()=>{if (live) setKind(null);});
    return () => {live = false;};
  }, [auth, ready]);
  const label = kind === 'member' ? 'Your account' : kind === 'guest' ? 'Guest demo' : kind === 'local' ? 'Local demo' : kind === 'signed_out' ? 'Sign in' : 'Account and login';
  const short = kind === 'member' ? 'Account' : kind === 'guest' ? 'Guest' : kind === 'local' ? 'Demo' : kind === 'signed_out' ? 'Sign in' : 'Me';
  return <button className="header-account" data-guide="account" title={t(label)} aria-label={`${t('Me')}: ${t(label)}`} onClick={onOpen}>
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="12" cy="7" r="4"/><path d="M4 22v-3a8 8 0 0 1 16 0v3"/></svg>
    <span>{t(short)}</span>
  </button>;
}
