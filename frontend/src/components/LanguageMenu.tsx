import {useEffect,useRef,useState} from 'react';
import {useLanguage,type Language} from '../language';
import {Icon} from './Icon';

/**
 * The header language control.
 *
 * It used to navigate to the full Language & speech settings page, which meant
 * two taps and a page load to do the one thing this control is for. It now
 * opens the two available languages and switches on choice. The full set of
 * language and speech preferences still lives in Settings.
 */
const OPTIONS: Array<{code: Language; label: string}> = [
  {code: 'en', label: 'English'},
  {code: 'zh', label: '中文'},
];

export function LanguageMenu() {
  const {language, setLanguage, t} = useLanguage();
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!wrap.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  return <div className="language-menu" ref={wrap}>
    <button
      type="button"
      className="language-shortcut"
      aria-haspopup="menu"
      aria-expanded={open}
      aria-label={t('Language and speech')}
      onClick={() => setOpen(value => !value)}
    >{language === 'zh' ? '中文' : 'EN'}</button>
    {open ? <ul className="language-menu__list" role="menu" aria-label={t('Choose a language')}>
      {OPTIONS.map(option => <li key={option.code} role="none">
        <button
          type="button"
          role="menuitemradio"
          aria-checked={language === option.code}
          className={language === option.code ? 'is-current' : undefined}
          lang={option.code}
          onClick={() => { setLanguage(option.code); setOpen(false); }}
        >
          <span>{option.label}</span>
          {language === option.code ? <Icon name="check"/> : null}
        </button>
      </li>)}
    </ul> : null}
  </div>;
}
