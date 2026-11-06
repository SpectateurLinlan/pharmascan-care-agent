/** Check the complete static entry graph, not just the largest emitted chunk. */
import assert from 'node:assert/strict';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';
import { build } from 'vite';
import { readFileSync } from 'node:fs';

test('optional screens and workflow forms stay outside the initial JavaScript budget', async () => {
  const root = fileURLToPath(new URL('../', import.meta.url));
  let initial;
  let runtime;
  const closure = (chunks, roots) => {
    const included = new Set();
    const visit = (name) => {
      if (included.has(name)) return;
      included.add(name);
      for (const dependency of chunks.find((chunk) => chunk.fileName === name)?.imports ?? [])
        visit(dependency);
    };
    for (const chunk of roots) visit(chunk.fileName);
    return chunks.filter((chunk) => included.has(chunk.fileName));
  };
  const result = await build({
    root,
    logLevel: 'warn',
    build: { write: false },
    plugins: [
      {
        name: 'startup-resource-contract',
        generateBundle(_options, bundle) {
          const chunks = Object.values(bundle).filter((item) => item.type === 'chunk');
          initial = closure(
            chunks,
            chunks.filter((chunk) => chunk.isEntry),
          );
          const app = chunks.find((chunk) =>
            Object.keys(chunk.modules).some((id) =>
              id.replaceAll('\\', '/').endsWith('/app/mountApplication.tsx'),
            ),
          );
          assert.ok(app, 'Deferred application composition must be emitted');
          runtime = closure(chunks, [app]);
        },
      },
    ],
  });
  const modules = runtime
    .flatMap((chunk) => Object.keys(chunk.modules))
    .map((id) => id.replaceAll('\\', '/'));
  for (const screen of [
    'AssistantWorkflow',
    'MedicinesHub',
    'CareTasksScreen',
    'RegimenHistoryScreen',
    'InventoryPanel',
    'PendingEvidenceTasks',
    'ConversationHistoryBrowser',
    'AssistantWorkflowOriginals',
  ]) {
    assert.equal(
      modules.some((id) => id.endsWith(`/${screen}.tsx`)),
      false,
      `${screen} must load on demand`,
    );
  }
  const entryModules = initial
    .flatMap((chunk) => Object.keys(chunk.modules))
    .map((id) => id.replaceAll('\\', '/'));
  for (const forbidden of ['/react-dom/', '/@supabase/', '/app/App.tsx', '/messages/catalog.ts']) {
    assert.equal(
      entryModules.some((id) => id.includes(forbidden)),
      false,
      `${forbidden} must not block the local composer`,
    );
  }
  const size = (chunks) => ({
    bytes: chunks.reduce((sum, chunk) => sum + Buffer.byteLength(chunk.code), 0),
    gzip: chunks.reduce((sum, chunk) => sum + gzipSync(chunk.code).byteLength, 0),
  });
  const entrySize = size(initial),
    appSize = size(runtime);
  console.log({ bootstrap: entrySize, applicationStaticClosure: appSize });
  assert.ok(
    entrySize.bytes <= 12_000,
    `Bootstrap JavaScript ${entrySize.bytes} exceeds 12000 bytes`,
  );
  assert.ok(entrySize.gzip <= 6_000, `Bootstrap gzip ${entrySize.gzip} exceeds 6000 bytes`);
  assert.ok(appSize.bytes <= 650_000, `Application closure ${appSize.bytes} exceeds 650000 bytes`);
  assert.ok(appSize.gzip <= 205_000, `Application gzip ${appSize.gzip} exceeds 205000 bytes`);
  const outputs = (Array.isArray(result) ? result : [result]).flatMap((item) => item.output);
  const html = String(outputs.find((item) => item.fileName === 'index.html')?.source);
  assert.ok(html.includes('id="startup-shell"'), 'Nonclinical shell must be in the document');
  assert.ok(html.includes('id="startup-critical-styles"'), 'Critical styles must be inline');
  assert.ok(
    !html.includes('mountApplication-'),
    'Deferred application must not be eagerly preloaded',
  );
});

test('only generated static assets receive immutable browser caching', () => {
  const config = JSON.parse(readFileSync(new URL('../vercel.json', import.meta.url), 'utf8'));
  const value = (source) =>
    config.headers
      .find((rule) => rule.source === source)
      ?.headers.find((header) => header.key.toLowerCase() === 'cache-control')?.value;
  assert.equal(value('/assets/:path*'), 'public, max-age=31536000, immutable');
  assert.equal(value('/api/:path*'), 'private, no-store');
  assert.equal(value('/sw.js'), 'no-cache');
  assert.ok(
    !config.headers.some(
      (rule) =>
        ['/(.*)', '/:path*', '/index.html'].includes(rule.source) &&
        rule.headers.some((header) => header.value.includes('immutable')),
    ),
  );
});
