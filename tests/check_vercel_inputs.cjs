// Vercel build-utils uses the same gitignore parser. Check both path bases:
// a Git checkout (frontend/...) and a CLI upload from the frontend directory.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createRequire} = require('node:module');
const root = path.resolve(__dirname, '..');
const frontendRequire = createRequire(path.join(root, 'frontend/package.json'));
const ignore = frontendRequire('ignore');
const shared = ignore().add(fs.readFileSync(path.join(root, '.vercelignore'), 'utf8'));
const project = ignore().add(fs.readFileSync(path.join(root, 'frontend/.vercelignore'), 'utf8'));
const inputs = [
  'package.json', 'package-lock.json', 'index.html', 'tsconfig.json',
  'vite.config.ts', 'vercel.json', 'src/App.tsx', 'public/sw.js',
];
for (const file of inputs) {
  assert.equal(shared.ignores(`frontend/${file}`), false, `Shared filter removed ${file}`);
  for (const prefix of ['', 'frontend/']) {
    assert.equal(project.ignores(prefix + file), false, `Project filter removed ${prefix + file}`);
  }
}
for (const file of ['.env', '.env.local', '.auth/session.json', 'private.key', 'node_modules/vite/package.json', 'dist/index.html', 'unlisted-note.md']) {
  for (const prefix of ['', 'frontend/']) {
    assert.equal(project.ignores(prefix + file), true, `Project filter allowed ${prefix + file}`);
  }
}
for (const file of ['unlisted-note.md', 'unlisted-directory/note.md', '.env']) {
  assert.equal(shared.ignores(file), true, `Shared filter allowed ${file}`);
  assert.equal(project.ignores(file), true, `Project filter allowed ${file}`);
}
const lock = JSON.parse(fs.readFileSync(path.join(root, 'frontend/package-lock.json'), 'utf8'));
assert.ok(lock.lockfileVersion >= 1);
assert.ok(lock.packages[''].devDependencies.vite);
console.log('PASS: 24 build-input, 14 private/generated and 6 root-exclusion checks; valid lockfile');
