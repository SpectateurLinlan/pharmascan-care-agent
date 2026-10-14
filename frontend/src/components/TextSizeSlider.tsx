import {useEffect, useRef, useState} from 'react';
import {useLanguage} from '../language';

export function TextSizeSlider() {
  const {t, textScale, previewTextScale, updatePreferences} = useLanguage();
  const [saving, setSaving] = useState(false);
  const changed = useRef(false);
  useEffect(()=>()=>previewTextScale(null),[previewTextScale]);
  function commit(value: number) {
    if (!changed.current || saving) return;
    changed.current = false; setSaving(true);
    void updatePreferences({text_scale_percent:value}).then(()=>{previewTextScale(null);setSaving(false);});
  }
  return <div className="field text-size-control">
    <label htmlFor="text-size">{t('Text size')} <output htmlFor="text-size" aria-live="polite">{textScale}%</output></label>
    <input id="text-size" type="range" min="100" max="150" step="1" value={textScale} disabled={saving}
      aria-valuetext={`${textScale}%`} aria-describedby="text-size-help"
      onChange={event=>{changed.current=true;previewTextScale(Number(event.target.value));}}
      onPointerUp={event=>commit(Number(event.currentTarget.value))}
      onKeyUp={event=>{if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key))commit(Number(event.currentTarget.value));}}
      onBlur={event=>commit(Number(event.currentTarget.value))}/>
    <div className="text-size-range"><span>100%</span><span>150%</span></div>
    <p id="text-size-help">{t('Applies to all text, including buttons and navigation. Release the slider to save.')}</p>
    {saving?<p role="status">{t('Saving text size…')}</p>:null}
  </div>;
}
