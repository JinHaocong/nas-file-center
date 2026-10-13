import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const css = read('src/styles/v049-workspace.css');

const selectorRules = (selector: string): string[] => {
  const escaped = selector.replace(/\./g, '\\.');
  return [...css.matchAll(new RegExp('(?:^|\\n)\\s*' + escaped + '\\s*\\{([^{}]*)\\}', 'g'))]
    .map(match => match[1]);
};

const properties = (body: string): Map<string, string> => {
  const result = new Map<string, string>();
  for (const raw of body.split(';')) {
    const colon = raw.indexOf(':');
    if (colon < 0) continue;
    result.set(raw.slice(0, colon).trim(), raw.slice(colon + 1).trim());
  }
  return result;
};

describe('Pure White historical CSS cleanup: safe v049 same-selector cascade', () => {
  test('later v049 typography winners are unchanged and earlier shadows are removed', () => {
    const winners = [
      ['.nfc-page-eyebrow', {
        'margin-bottom': '6px', 'font-size': '8.5px', 'letter-spacing': '0.14em',
      }],
      ['.nfc-page-title', {
        'font-size': 'clamp(25px, 1.85vw, 32px)', 'font-weight': '660',
      }],
      ['.nfc-page-description', {
        'margin-top': '7px', 'font-size': '11.5px', 'line-height': '1.62',
      }],
      ['.nfc-data-panel-title', {
        'font-size': '13px', 'font-weight': '670',
      }],
      ['.nfc-data-panel-description', {
        'margin-top': '4px', 'font-size': '10.5px', 'line-height': '1.52',
      }],
    ] as const;

    let retired = 0;
    for (const [selector, expected] of winners) {
      const rules = selectorRules(selector);
      assert.equal(rules.length, 2, selector + ' still has an early and late source block');
      const earlier = properties(rules[0]);
      const later = properties(rules[1]);
      for (const [property, finalValue] of Object.entries(expected)) {
        assert.equal(earlier.has(property), false, selector + ' earlier ' + property + ' was shadowed');
        assert.equal(later.get(property), finalValue, selector + ' later ' + property + ' is unchanged');
        retired += 1;
      }
    }
    assert.equal(retired, 13);
  });

  test('each early selector retains independent typography instead of deleting its rule', () => {
    const expected = [
      ['.nfc-page-eyebrow', 'font-weight', '740'],
      ['.nfc-page-title', 'line-height', '1.08'],
      ['.nfc-page-description', 'max-width', '76ch'],
      ['.nfc-data-panel-title', 'letter-spacing', '-0.012em'],
      ['.nfc-data-panel-description', 'color', 'var(--nfc-v49-subtle)'],
    ] as const;
    for (const [selector, property, value] of expected) {
      const rules = selectorRules(selector);
      assert.equal(properties(rules[0]).get(property), value);
    }
  });

  test('authoritative second group stays after first group and other native styles remain', () => {
    const earlyTitle = css.indexOf('.nfc-page-title {');
    const finalTitle = css.lastIndexOf('.nfc-page-title {');
    const earlyPanel = css.indexOf('.nfc-data-panel-title {');
    const finalPanel = css.lastIndexOf('.nfc-data-panel-title {');
    assert.ok(earlyTitle >= 0 && earlyTitle < finalTitle);
    assert.ok(earlyPanel >= 0 && earlyPanel < finalPanel);
    for (const marker of [
      '.nfc-data-panel-dense {', '.nfc-page-header {',
      '.nfc-directory-list-viewport {', '.nfc-system-controls-page .nfc-settings-grid {',
      '.nfc-row-actions:focus-within', '.nfc-mobile-pagination {',
    ]) assert.ok(css.includes(marker), marker);
    assert.doesNotMatch(css, /\.(?:ant-[a-z][\w-]*|anticon\b)/);
  });

  test('all eight historical media conditions remain and no imports are reordered', () => {
    assert.equal([...css.matchAll(/@media\s*\([^)]*\)/g)].length, 8);
    for (const query of [
      '@media (max-width: 1199px)', '@media (max-width: 767px)',
      '@media (max-width: 420px)', '@media (hover: none)',
      '@media (prefers-reduced-motion: reduce)',
      '@media (prefers-reduced-transparency: reduce)',
    ]) assert.ok(css.includes(query), query);
    const entry = read('src/main.tsx');
    const prev = entry.indexOf("import './styles/v048-detail.css';");
    const current = entry.indexOf("import './styles/v049-workspace.css';");
    const next = entry.indexOf("import './styles/v050-layout.css';");
    const native = entry.indexOf("import './styles/console-v2.css';");
    assert.ok(prev >= 0 && prev < current && current < next && next < native);
    assert.doesNotMatch(entry, /v057|pure-white\.css/);
  });

  test('CSS audit ownership stays complete and existing business safety routes remain unmodified', () => {
    const guard = read('scripts/check-console-css-ownership.mjs');
    assert.ok(guard.includes("'legacy-reviewed:v049-workspace.css'"));
    assert.ok(guard.includes('Incomplete CSS inventory coverage'));
    for (const [path, marker] of [
      ['src/pages/Quarantine/PurgeConfirmModal.tsx', "quarantineApi.purge(entry.id, { confirmation: 'DELETE' })"],
      ['src/pages/Plans/PlanDetail.tsx', 'plansApi.validatePlan(planId)'],
      ['src/pages/Organizer/ProfilePreview.tsx', 'expected_preview_digest: params.expectedPreviewDigest'],
    ] as const) assert.ok(read(path).includes(marker), marker);
  });
});
