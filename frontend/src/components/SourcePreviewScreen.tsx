import { useState } from 'react';
import { api, type SourcePreview } from '../api/client';
import { Card, ErrorNotice } from './primitives';
import {useLanguage} from '../language';

export function SourcePreviewScreen({ onUse }: { onUse?: (preview: SourcePreview, name: string) => void }) {
  const {t}=useLanguage();
  const [image, setImage] = useState<File | null>(null);
  const [kind, setKind] = useState<'package' | 'pharmacy_label'>('pharmacy_label');
  const [consent, setConsent] = useState(false);
  const [result, setResult] = useState<SourcePreview | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function preview() {
    if (!image || !consent) return;
    setBusy(true); setError(null); setResult(null);
    try { setResult(await api.sourcePreview(image, kind)); } catch (caught) { setError(caught); }
    finally { setBusy(false); }
  }
  return <Card title="Read medication label" hint="Preview only. No medication or dose is saved from an image.">
    <label className="field">{t('Source type')}<select value={kind} onChange={event => setKind(event.target.value as typeof kind)}>
      <option value="pharmacy_label">{t('Pharmacy label')}</option><option value="package">{t('Medicine package')}</option>
    </select></label>
    <label className="field">{t('Synthetic demo image')}<input type="file" accept="image/png,image/jpeg"
      onChange={event => setImage(event.target.files?.[0] ?? null)} /></label>
    <label className="consent"><input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} />
      {t('This is a synthetic image and I agree to send it to PharmaScan for a label preview.')}</label>
    <button onClick={() => void preview()} disabled={!image || !consent || busy}>{t(busy ? 'Reading label…' : 'Preview label')}</button>
    {error ? <ErrorNotice error={error} /> : null}
    {result ? <div><p>{t('Extraction needs your review. Use the manual form below to record the instructions you can verify.')}</p>
      {result.candidates.map((candidate, i) => <article key={i}><h3>{candidate.product.name}</h3>
        <p>{candidate.product.strength}</p><button onClick={() => onUse?.(result, candidate.product.name)}>{t('Use as source for a reviewed draft')}</button><p>{t('Printed directions')}: {candidate.regimen_evidence.directions?.value ?? t('No personal directions were returned.')}</p>
        <dl className="source-instructions">{['Dose amount','doses per day','Number of days','Food instructions'].map(label=><div key={label}><dt>{t(label)}</dt><dd>{t('Not returned as structured instructions. Please review and enter manually.')}</dd></div>)}</dl>
        <p className="notice">{t('Dose amount, schedule and duration have not been inferred.')}</p>
        <details><summary>{t('Printed evidence')}</summary><ul>{candidate.product.source_lines.map((line, index) => <li key={index}>{line}</li>)}</ul>
          <p>{t('Preview evidence is temporary; it is not a reviewed or saved prescription.')}</p></details>
      </article>)}</div> : null}
  </Card>;
}
