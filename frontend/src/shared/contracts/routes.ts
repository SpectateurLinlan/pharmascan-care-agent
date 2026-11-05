/** Stable route contract shared by navigation and Assistant intent validation. */
export const roots = ['today', 'medicines', 'records', 'me'] as const;
export const parents: Record<string, string> = {
  'care-tasks': 'today',
  'adherence-barriers': 'records',
  'medication-review': 'records',
  assistant: 'today',
  check: 'today',
  'check-result': 'check',
  label: 'medicines',
  manual: 'medicines',
  'edit-medication': 'medicine-detail',
  'medicine-history': 'medicine-detail',
  'medication-inventory': 'medicine-detail',
  unfinished: 'medicines',
  'past-medicines': 'medicines',
  gallery: 'medicines',
  'medicine-detail': 'medicines',
  'health-notes': 'records',
  'medication-records': 'records',
  'summary-week': 'records',
  'summary-month': 'records',
  'summary-course': 'records',
  profile: 'me',
  account: 'me',
  caregivers: 'me',
  settings: 'me',
  'reminder-settings': 'me',
  'language-settings': 'me',
  accessibility: 'me',
  privacy: 'me',
  conversations: 'me',
  about: 'me',
  feedback: 'me',
  help: 'me',
};
export const normalize = (value: string) => (value === 'history' ? 'records' : value);
export function valid(value: string) {
  return roots.some((root) => root === value) || Object.hasOwn(parents, value);
}
export const isCareRoute = (value: string): boolean => valid(value);
