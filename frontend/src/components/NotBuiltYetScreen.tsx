/**
 * Placeholders for screens that are deliberately NOT implemented in this
 * build. They exist so the UI has no dead links and so an unfinished page can
 * never be mistaken for a working one.
 */

import { Card, Tag } from './primitives';

const NOT_BUILT: { title: string; reason: string; blocker: string }[] = [
  {
    title: 'Pill photo check',
    reason:
      'The camera capture flow and the live Stage2 vision provider are not available in this build. No photo is uploaded and no visual comparison is run.',
    blocker: 'B01 — live Stage2 contract unconfirmed',
  },
  {
    title: 'Preferences and accessibility settings',
    reason:
      'Visual mode, language and notification preferences are not implemented. The UI already follows your system light/dark setting.',
    blocker: 'Not in tonight\'s P0 scope',
  },
  {
    title: 'Caregiver contact',
    reason:
      'Sharing a summary with another person requires independent verification of that contact and is not built.',
    blocker: 'Not in tonight\'s P0 scope',
  },
  {
    title: 'Health observations',
    reason:
      'Recording blood pressure or glucose readings is not implemented. This app does not diagnose.',
    blocker: 'Not in tonight\'s P0 scope',
  },
];

export function NotBuiltYetScreen() {
  return (
    <Card
      title="Not built yet"
      hint="These are listed so nothing here looks finished when it is not."
    >
      <ul className="med-list">
        {NOT_BUILT.map((item) => (
          <li className="med" key={item.title}>
            <span className="med__name">{item.title}</span>
            <span className="med__meta">{item.reason}</span>
            <span>
              <Tag>{item.blocker}</Tag>
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
