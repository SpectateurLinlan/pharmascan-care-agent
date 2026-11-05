/** Parse source imports without executing UI, Auth, HTTP or browser code. */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import ts from 'typescript';

const extensions = ['', '.ts', '.tsx', '.js', '.jsx', '.json', '.css', '/index.ts', '/index.tsx'];
const normalize = (value) => value.replaceAll('\\', '/');
const layer = (file) => (file.includes('/') ? file.split('/')[0] : 'app');
const feature = (file) => (file.startsWith('features/') ? file.split('/')[1] : null);

/** Validate browser URLs separately from file-relative module imports. */
export function analyzeBrowserReferences(sources, assets) {
  const issues = [];
  for (const [file, source] of sources) {
    const values = [];
    if (file.endsWith('.html')) {
      for (const match of source.matchAll(/(?:src|href)=["']([^"']+)["']/g)) values.push(match[1]);
    } else {
      const tree = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true);
      function visit(node) {
        if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node))
          values.push(node.text);
        if (ts.isTemplateExpression(node) && /\.(?:html|tsx?)[?#]/.test(node.head.text))
          values.push(node.head.text);
        ts.forEachChild(node, visit);
      }
      visit(tree);
    }
    for (const value of values) {
      if (!value.startsWith('/') && !/^https?:\/\//.test(value)) continue;
      let url;
      try {
        url = new URL(value, 'http://frontend.local');
      } catch {
        continue;
      }
      if (!['frontend.local', 'localhost', '127.0.0.1'].includes(url.hostname)) continue;
      if (!/^\/(src|e2e)\//.test(url.pathname)) continue;
      const target = decodeURIComponent(url.pathname.slice(1));
      if (!assets.has(target)) issues.push({ file, message: `unresolved browser asset: ${value}` });
    }
  }
  return issues;
}

export function checkBrowserReferences(frontend) {
  const sources = new Map(),
    assets = new Set();
  function collect(directory) {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const absolute = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        collect(absolute);
        continue;
      }
      const relative = normalize(path.relative(frontend, absolute));
      assets.add(relative);
      if (relative.startsWith('e2e/') && /\.(tsx?|html)$/.test(relative))
        sources.set(relative, fs.readFileSync(absolute, 'utf8'));
    }
  }
  collect(path.join(frontend, 'src'));
  collect(path.join(frontend, 'e2e'));
  return analyzeBrowserReferences(sources, assets);
}

/** Return all relative module edges, retaining type-only and lazy dependencies. */
function imports(file, source, report) {
  const tree = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true);
  const found = [];
  function visit(node) {
    if (
      (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) &&
      node.moduleSpecifier &&
      ts.isStringLiteral(node.moduleSpecifier)
    )
      found.push(node.moduleSpecifier.text);
    if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) {
      const target = node.arguments[0];
      if (target && (ts.isStringLiteral(target) || ts.isNoSubstitutionTemplateLiteral(target)))
        found.push(target.text);
      else report(file, 'nonliteral dynamic import cannot be checked against module boundaries');
    }
    if (
      ts.isImportTypeNode(node) &&
      ts.isLiteralTypeNode(node.argument) &&
      ts.isStringLiteral(node.argument.literal)
    )
      found.push(node.argument.literal.text);
    ts.forEachChild(node, visit);
  }
  visit(tree);
  return found;
}

/** Check a virtual inventory; diagnostics are deterministic and suitable for CI. */
export function analyzeSources(sources, config) {
  const issues = [];
  const edges = new Map();
  const report = (file, message) => issues.push({ file, message });
  for (const [file, source] of sources) {
    if (!/\.[jt]sx?$/.test(file) || file.endsWith('.d.ts')) continue;
    edges.set(file, []);
    const owner = feature(file);
    if (owner && !Object.hasOwn(config.featureDependencies ?? {}, owner))
      report(file, `undeclared feature: ${owner}`);
    for (const specifier of imports(file, source, report)) {
      if (!specifier.startsWith('.')) {
        if (specifier.startsWith('@supabase/') && file !== 'api/auth.ts')
          report(file, 'Auth SDK is restricted to api/auth.ts');
        continue;
      }
      const base = path.posix.normalize(path.posix.join(path.posix.dirname(file), specifier));
      const target = extensions
        .map((extension) => base + extension)
        .find((candidate) => sources.has(candidate));
      if (!target) {
        report(file, `unresolved import: ${specifier}`);
        continue;
      }
      if (!/\.[jt]sx?$/.test(target)) continue;
      edges.get(file).push(target);
      const fromLayer = layer(file),
        toLayer = layer(target);
      if (!(config.allowed[fromLayer] ?? []).includes(toLayer))
        report(file, `forbidden dependency ${fromLayer} -> ${toLayer}: ${target}`);
      const fromFeature = feature(file),
        toFeature = feature(target);
      if (toFeature && fromFeature !== toFeature) {
        const publicPath = target.slice(`features/${toFeature}/`.length);
        if (!(config.publicModules[toFeature] ?? []).includes(publicPath))
          report(file, `use a declared public module of ${toFeature}: ${target}`);
        if (fromFeature && !(config.featureDependencies?.[fromFeature] ?? []).includes(toFeature))
          report(file, `forbidden feature dependency ${fromFeature} -> ${toFeature}`);
      }
    }
  }
  const visiting = new Set(),
    visited = new Set(),
    stack = [];
  function walk(file) {
    if (visiting.has(file)) {
      report(file, `dependency cycle: ${[...stack.slice(stack.indexOf(file)), file].join(' -> ')}`);
      return;
    }
    if (visited.has(file)) return;
    visiting.add(file);
    stack.push(file);
    for (const target of edges.get(file) ?? []) walk(target);
    stack.pop();
    visiting.delete(file);
    visited.add(file);
  }
  for (const file of edges.keys()) walk(file);
  return issues;
}

/** Include assets and JSON for resolution, but never load generated or test files. */
export function checkArchitecture(root, config) {
  const sources = new Map();
  function collect(directory) {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const absolute = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        if (entry.name !== 'test') collect(absolute);
        continue;
      }
      const relative = normalize(path.relative(root, absolute));
      if (/\.test\.[jt]sx?$/.test(relative) || relative.endsWith('.md')) continue;
      sources.set(relative, fs.readFileSync(absolute, 'utf8'));
    }
  }
  collect(root);
  // App metadata is a source JSON dependency outside src.
  sources.set('../package.json', fs.readFileSync(path.join(root, '../package.json'), 'utf8'));
  return analyzeSources(sources, config);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  const { default: config } = await import(
    pathToFileURL(path.join(frontend, 'architecture.config.mjs')).href
  );
  const issues = [
    ...checkArchitecture(path.join(frontend, 'src'), config),
    ...checkBrowserReferences(frontend),
  ];
  for (const issue of issues) console.error(`${issue.file}: ${issue.message}`);
  if (issues.length) process.exitCode = 1;
  else
    console.log('Frontend architecture: no unresolved imports, cycles or forbidden dependencies.');
}
