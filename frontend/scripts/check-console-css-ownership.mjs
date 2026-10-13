/**
 * Console v2 owned CSS boundary.
 * Historical index.css and other v04x-v05x layers remain pending review.
 * Native console styles, Settings and reviewed v048-detail.css must have
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
const errors = [];
for (const name of owned) {
  const path = name.substring(name.indexOf(':') + 1);
  const source = readFileSync(resolve(root, path), 'utf8');
  // Class selectors only: do not accidentally forbid comments mentioning AntD.
  const hits = [...source.matchAll(/\.(?:ant-[a-z][a-z0-9-]*|anticon(?:-[a-z0-9-]+)?\b)/g)];
  if (hits.length) {
    errors.push(path + ': ' + hits.map(hit => hit[0]).join(', '));
  }
}
if (owned.length < 40) errors.push('Native CSS inventory unexpectedly shrank');
for (const issue of errors) console.error('[CSS OWNER VIOLATION] ' + issue);
console.log('[CSS AUDIT] ' + owned.length + ' owned/reviewed CSS files checked; ' +
  errors.length + ' violation(s). Historical styles remain separately tracked.');
if (errors.length) process.exitCode = 1;
