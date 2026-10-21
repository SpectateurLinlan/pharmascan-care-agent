import {useState} from 'react';
import {useLanguage,type Language} from '../language';

/**
 * One tap switches the interface language. Detailed speech preferences remain
 * available on the Language & speech settings page.
 */
export function LanguageMenu() {
  const {language, savePreferences, t} = useLanguage();
  const [savingLanguage,setSavingLanguage]=useState<Language|null>(null);
  const switching=savingLanguage!==null;
  const nextLanguage: Language = language === 'zh' ? 'en' : 'zh';
  const targetLabel=nextLanguage==='zh'?'中文':'EN';
  const progressLabel=t((savingLanguage??nextLanguage)==='zh'?'Switching to Chinese…':'Switching to English…');
  async function switchLanguage(){
    if(switching)return;
    setSavingLanguage(nextLanguage);
    try{await savePreferences({preferred_language:nextLanguage});}
    finally{setSavingLanguage(null);}
  }
  return <div className="language-menu">
    <button
      type="button"
      className="language-shortcut"
      data-ui-language={language}
      aria-label={switching?progressLabel:t('Switch language')}
      aria-busy={switching}
      disabled={switching}
      title={switching?progressLabel:t('Switch language')}
      onClick={() => void switchLanguage()}
    >{targetLabel}</button>
    <span className="sr-only" role="status" aria-live="polite">{switching?progressLabel:''}</span>
  </div>;
}
