/** Check the complete static entry graph, not just the largest emitted chunk. */
import assert from 'node:assert/strict';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';
import { build } from 'vite';

test('optional screens and workflow forms stay outside the initial JavaScript budget', async () => {
  const root = fileURLToPath(new URL('../', import.meta.url));
  let initial;
  await build({
    root,
    logLevel: 'warn',
    build: { write: false },
    plugins: [
      {
        name: 'startup-resource-contract',
        generateBundle(_options, bundle) {
          const included = new Set();
          const visit = (name) => {
            if (included.has(name)) return;
            included.add(name);
            for (const dependency of bundle[name]?.imports ?? []) visit(dependency);
          };
          for (const chunk of Object.values(bundle)) {
            if (chunk.type === 'chunk' && chunk.isEntry) visit(chunk.fileName);
          }
          initial = Object.values(bundle).filter(
            (chunk) => chunk.type === 'chunk' && included.has(chunk.fileName),
          );
        },
      },
    ],
  });
  const modules = initial
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
  const bytes = initial.reduce((sum, chunk) => sum + Buffer.byteLength(chunk.code), 0);
  const gzipBytes = initial.reduce((sum, chunk) => sum + gzipSync(chunk.code).byteLength, 0);
  console.log({ initialJsBytes: bytes, initialGzipBytes: gzipBytes });
  assert.ok(bytes <= 640_000, `Initial JavaScript ${bytes} exceeds 640000 bytes`);
  assert.ok(gzipBytes <= 200_000, `Initial gzip ${gzipBytes} exceeds 200000 bytes`);
});
