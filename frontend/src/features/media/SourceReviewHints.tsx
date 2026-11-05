import type { SourcePreview } from '../../api/client';
import { useLanguage } from '../../i18n/language';
import { sourceReviewHints } from './sourceReviewHintModel';

export function SourceReviewHints({
  candidates,
  previewOnly = false,
}: {
  candidates: SourcePreview['candidates'];
  previewOnly?: boolean;
}) {
  const { language } = useLanguage();
  const zh = language === 'zh';
  const hints = sourceReviewHints(candidates);
  if (!hints.clocks.length && !hints.release.length && !hints.duration.length) return null;
  return (
    <section
      className="notice"
      aria-label={zh ? '原始标签待核对信息' : 'Original label details to check'}
    >
      <p>
        {zh
          ? '请对照原始标签核对，以下文字尚未确认为您的用药计划。'
          : 'Check these words against the original label. They are not yet confirmed plan instructions.'}
      </p>
      <ul>
        {hints.release.length ? (
          <li>
            {zh ? '剂型与释放方式待核对' : 'Dosage form and release need review'}：
            {hints.release.join('、')}
          </li>
        ) : null}
        {hints.clocks.length ? (
          <li>
            {zh
              ? '原始标签提到以下时点，请核对实际服药时间'
              : 'The original label mentions these times; check your actual scheduled times'}
            ：{hints.clocks.join(', ')}。
            {previewOnly ? (
              <span>
                {zh
                  ? '预览中的时间文字尚未确认，本次预览不会保存服药时间。'
                  : 'Previewed clock words are unconfirmed; this preview does not save scheduled times.'}
              </span>
            ) : zh ? (
              '请在下方时间栏核对填写，不会自动改为08:00。'
            ) : (
              'Review and enter them in the time fields below; they are not replaced with 08:00.'
            )}
          </li>
        ) : null}
        {hints.duration.length ? (
          <li>
            {zh ? '疗程尚需核对' : 'Course duration needs review'}：{hints.duration.join('、')}。
            {zh
              ? '起止日期仍须核对，发药日不等于疗程开始日。'
              : 'Confirm the course dates separately; a dispensing date is not a course start date.'}
          </li>
        ) : null}
      </ul>
    </section>
  );
}
