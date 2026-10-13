/**
 * Console v2 owned CSS boundary.
 * Historical index.css and reviewed v04x-v05x layers are audited after native migration.
 * Native console styles, Settings, index.css, v046/v047 foundations and reviewed v048-v056 CSS must have
 * zero legacy Ant Design class selectors.
 *
 * Usage (from frontend): node scripts/check-console-css-ownership.mjs
 */
import { readdirSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(process.cwd(), 'src/styles');
const owned = readdirSync(root)
  .filter(name => /^console-v2(?:-[a-z0-9-]+)?\.css$/.test(name))
  .map(name => 'console-v2:' + name);
owned.push('settings:pages/settings.css');
owned.push('legacy-reviewed:v048-detail.css');
owned.push('legacy-reviewed:v048.css');
owned.push('legacy-reviewed:v049-workspace.css');
owned.push('legacy-reviewed:v050-layout.css');
owned.push('legacy-reviewed:v051-product-polish.css');
owned.push('legacy-reviewed:v052-final-audit.css');
owned.push('legacy-reviewed:v054-premium-system.css');
owned.push('legacy-reviewed:v056-right-workspace-v2.css');
owned.push('legacy-reviewed:v055-workspace-breathing.css');
owned.push('legacy-index:index.css');
owned.push('legacy-reviewed:shell.css');
owned.push('legacy-reviewed:primitives.css');
owned.push('legacy-reviewed:overlays.css');
owned.push('legacy-reviewed:responsive.css');
owned.push('legacy-reviewed:components.css');
owned.push('legacy-reviewed:foundation.css');
owned.push('legacy-reviewed:pages/dashboard.css');
owned.push('legacy-reviewed:pages/details.css');
owned.push('legacy-reviewed:pages/operations.css');
owned.push('legacy-reviewed:pages/scheduler.css');
owned.push('legacy-reviewed:tokens.css');
owned.push('legacy-reviewed:v046.css');
owned.push('legacy-reviewed:v047.css');
owned.push('legacy-reviewed:pages/login.css');
owned.push('legacy-reviewed:pages/organizer.css');
owned.push('legacy-reviewed:pages/tools.css');
owned.push('legacy-reviewed:pages/workflows.css');
owned.push('legacy-reviewed:v048-pages.css');
// The reviewed list must be exhaustive, not just clean for today's files.
function cssFiles(dir, prefix = '') {
  const files = [];
  for (const entry of readdirSync(resolve(dir, prefix), { withFileTypes: true })) {
    const path = prefix + entry.name;
    if (entry.isDirectory()) files.push(...cssFiles(dir, path + '/'));
    else if (entry.isFile() && entry.name.endsWith('.css')) files.push(path);
  }
  return files;
}

const errors = [];
for (const name of owned) {
  const path = name.substring(name.indexOf(':') + 1);
  const source = readFileSync(resolve(root, name.startsWith('legacy-index:') ? '..' : '.', path), 'utf8');
  // Class selectors only: do not accidentally forbid comments mentioning AntD.
  const hits = [...source.matchAll(/\.(?:ant-[a-z][a-z0-9-]*|anticon(?:-[a-z0-9-]+)?\b)/g)];
  if (hits.length) {
    errors.push(path + ': ' + hits.map(hit => hit[0]).join(', '));
  }
}
const allCss = [...cssFiles(root), '../index.css'];
const reviewed = owned.map(name => name.startsWith('legacy-index:') ?
  '../index.css' : name.substring(name.indexOf(':') + 1));
const reviewedSet = new Set(reviewed);
for (const path of allCss) {
  if (!reviewedSet.has(path)) errors.push('Unreviewed CSS file: ' + path);
}
if (reviewedSet.size !== reviewed.length) errors.push('Duplicate CSS ownership entry');
if (reviewedSet.size !== allCss.length) errors.push('Incomplete CSS inventory coverage');
for (const issue of errors) console.error('[CSS OWNER VIOLATION] ' + issue);
console.log('[CSS AUDIT] ' + owned.length + ' owned/reviewed CSS files checked; ' +
  errors.length + ' violation(s).');
if (errors.length) process.exitCode = 1;
