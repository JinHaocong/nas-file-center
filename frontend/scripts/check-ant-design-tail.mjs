/**
 * Console v2 Ant Design tail gate.
 * Enumerates every runtime source module, never relying on GitHub code search.
 * Only the explicitly reviewed, not-yet-migrated legacy modules may import AntD.
 *
 * Run directly: node scripts/check-ant-design-tail.mjs
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { relative, resolve, sep } from 'node:path';

const frontend = resolve(process.cwd());
const root = resolve(frontend, 'src');
const allowed = new Set([
  'src/components/workflows/OrganizerProfileFields.tsx',
  'src/contexts/ThemeContext.tsx',
  'src/pages/Plans/PlanDetail.tsx',
]);

const sourceExt = /\.(?:[cm]?js|[cm]?ts|jsx|tsx|css)$/i;
const modulePattern = /\b(?:from\s*|import\s*(?:\(\s*)?|require\s*\(\s*|@import\s*(?:url\(\s*)?)['"](?:antd(?:\/[^'"]*)?|@ant-design\/icons(?:\/[^'"]*)?)['"]/g;
const matches = [];
const scan = dir => {
  for (const name of readdirSync(dir)) {
    const full = resolve(dir, name);
    if (statSync(full).isDirectory()) { scan(full); continue; }
    if (!sourceExt.test(name)) continue;
    const path = relative(frontend, full).split(sep).join('/');
    const source = readFileSync(full, 'utf8');
    const hits = [...source.matchAll(modulePattern)];
    if (hits.length) {
      matches.push({ path, count: hits.length, approved: allowed.has(path) });
    }
  }
};
scan(root);
matches.sort((a, b) => a.path.localeCompare(b.path));

const missing = [...allowed].filter(path => !matches.some(item => item.path === path));
const unexpected = matches.filter(item => !item.approved);
for (const item of matches) {
  console.log((item.approved ? '[TAIL]' : '[UNEXPECTED]') + ' ' + item.path +
    ' (' + item.count + ' direct AntD imports)');
}
console.log('[AUDIT] ' + matches.length + ' runtime source files import Ant Design.');
if (missing.length) console.error('[STALE ALLOWLIST] Remove migrated paths: ' + missing.join(', '));
if (unexpected.length) console.error('[BLOCKED] Newly introduced Ant Design imports require migration.');
if (missing.length || unexpected.length) process.exitCode = 1;
