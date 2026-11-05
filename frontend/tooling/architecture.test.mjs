import assert from 'node:assert/strict';
import { test } from 'node:test';
import { analyzeSources, analyzeBrowserReferences } from './architecture.mjs';

const config = {
  allowed: {
    app: ['features', 'components', 'api', 'shared', 'platform', 'i18n', 'app'],
    features: ['features', 'components', 'api', 'shared', 'platform', 'i18n'],
    components: ['components', 'shared', 'platform', 'i18n'],
    api: ['api', 'shared'],
    shared: ['shared'],
    platform: ['platform', 'shared'],
    i18n: ['i18n', 'shared'],
  },
  publicModules: { care: ['form.tsx'] },
  featureDependencies: { assistant: ['care'], care: [] },
};
const analyze = (entries) => analyzeSources(new Map(entries), config);

test('rejects a shared module importing a feature', () => {
  const issues = analyze([
    ['shared/model.ts', "import {x} from '../features/care/form';"],
    ['features/care/form.tsx', 'export const x=1;'],
  ]);
  assert.ok(issues.some((issue) => issue.message.includes('shared -> features')));
});
test('rejects component access to the HTTP client', () => {
  const issues = analyze([
    ['components/notice.tsx', "import {api} from '../api/client';"],
    ['api/client.ts', 'export const api={};'],
  ]);
  assert.ok(issues.some((issue) => issue.message.includes('components -> api')));
});
test('detects cycles through type-only imports', () => {
  const issues = analyze([
    ['shared/a.ts', "import type {B} from './b'; export type A=B;"],
    ['shared/b.ts', "import type {A} from './a';export type B=A;"],
  ]);
  assert.ok(issues.some((issue) => issue.message.includes('cycle')));
});
test('detects cycles through lazy imports', () => {
  const issues = analyze([
    ['app/a.ts', "export const a=()=>import('./b');"],
    ['app/b.ts', "export const b=()=>import('./a');"],
  ]);
  assert.ok(issues.some((issue) => issue.message.includes('cycle')));
});
test('reports a missing source target including incorrect letter case', () => {
  const issues = analyze([
    ['app/main.ts', "import '../components/Button';"],
    ['components/button.tsx', 'export {};'],
  ]);
  assert.ok(issues.some((issue) => issue.message.includes('unresolved')));
});
test('rejects undeclared access to a feature implementation', () => {
  const issues = analyze([
    ['features/assistant/run.ts', "import {x} from '../care/internal';"],
    ['features/care/internal.ts', 'export const x=1;'],
  ]);
  assert.ok(issues.some((issue) => issue.message.includes('public')));
});
test('accepts an explicitly declared public feature module and external libraries', () => {
  assert.deepEqual(
    analyze([
      [
        'features/assistant/run.ts',
        "import {x} from '../care/form';import {useState} from 'react';",
      ],
      ['features/care/form.tsx', 'export const x=1;'],
    ]),
    [],
  );
});
test('accepts CSS dependencies resolved in the same inventory', () => {
  assert.deepEqual(
    analyze([
      ['app/main.ts', "import '../styles/index.css';"],
      ['styles/index.css', 'body{}'],
    ]),
    [],
  );
});

test('checks constant template-literal dynamic imports against the same layer rules', () => {
  const issues = analyze([
    ['shared/model.ts', 'export const get=()=>import(`../features/care/form`);'],
    ['features/care/form.tsx', 'export const x=1;'],
  ]);
  assert.ok(issues.some((issue) => issue.message.includes('shared -> features')));
});
test('rejects undeclared features rather than granting every public feature', () => {
  const issues = analyze([
    ['features/new-feature/run.ts', "export {x} from '../care/form';"],
    ['features/care/form.tsx', 'export const x=1;'],
  ]);
  assert.ok(issues.some((issue) => issue.message.includes('undeclared feature')));
});
test('rejects nonliteral dynamic imports that cannot be statically bounded', () => {
  const issues = analyze([['shared/model.ts', 'export const get=(name:string)=>import(name);']]);
  assert.ok(issues.some((issue) => issue.message.includes('nonliteral dynamic import')));
});
test('detects cycles through inline import type expressions', () => {
  const issues = analyze([
    ['shared/a.ts', "export type A=import('./b').B;"],
    ['shared/b.ts', "export type B=import('./a').A;"],
  ]);
  assert.ok(issues.some((issue) => issue.message.includes('cycle')));
});

test('rejects missing browser module URLs and query-bearing fixture URLs', () => {
  const issues = analyzeBrowserReferences(
    new Map([['e2e/qa.ts', "const module='/src/moved.ts';const page='/e2e/old.html?shell=1';"]]),
    new Set(['src/current.ts', 'e2e/support/page.html']),
  );
  assert.equal(issues.length, 2);
});
test('accepts existing local browser assets with query/hash and ignores remote sources', () => {
  assert.deepEqual(
    analyzeBrowserReferences(
      new Map([
        [
          'e2e/qa.ts',
          "const page='http://127.0.0.1:5174/e2e/support/page.html?shell=1#me';const remote='https://example.org/src/remote.ts';",
        ],
      ]),
      new Set(['e2e/support/page.html']),
    ),
    [],
  );
});
test('checks template URL asset paths before interpolated query/hash values', () => {
  const issues = analyzeBrowserReferences(
    new Map([['e2e/qa.ts', 'const page=`/e2e/moved.html?shell=1#${route}`;']]),
    new Set(),
  );
  assert.equal(issues.length, 1);
});
