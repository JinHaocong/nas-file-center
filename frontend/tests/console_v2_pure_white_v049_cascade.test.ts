import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const css = read('src/styles/v049-workspace.css');

// Only top-level rules share this cascade context. A plain regex would also
// count same-named rules inside responsive @media blocks.
const selectorRules = (selector: string): string[] => {
  const plain = css.replace(/\/\*[\s\S]*?\*\//g, comment => comment.replace(/[^\n]/g, ' '));
  const bodies: string[] = [];
  let depth = 0;
  let segmentStart = 0;
  let selectedOpen = -1;
  for (let i = 0; i < plain.length; i += 1) {
    if (plain[i] === '{') {
      if (depth === 0 && plain.slice(segmentStart, i).trim() === selector) {
        selectedOpen = i;
      }
      depth += 1;
      segmentStart = i + 1;
    } else if (plain[i] === '}') {
      depth -= 1;
      assert.ok(depth >= 0, 'CSS braces remain balanced');
      if (depth === 0 && selectedOpen >= 0) {
        bodies.push(plain.slice(selectedOpen + 1, i));
        selectedOpen = -1;
      }
      segmentStart = i + 1;
    }
  }
  assert.equal(depth, 0, 'CSS braces remain balanced');
  return bodies;
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
      // Only eyebrow has independent declarations in both historical
      // blocks. Four other early text blocks were completely shadowed
      // by v056 and must never reappear in unconditional v049.
      const eyebrow = selector === '.nfc-page-eyebrow';
      assert.equal(rules.length, eyebrow ? 2 : 1,
        selector + ' unconditional v049 ownership drifted');
      const earlier = eyebrow ? properties(rules[0]) : undefined;
      const later = properties(rules.at(-1)!);
      for (const [property, finalValue] of Object.entries(expected)) {
        if (earlier) assert.equal(earlier.has(property), false,
          selector + ' earlier property must remain shadow-free: ' + property);
        assert.equal(later.get(property), finalValue,
          selector + ' later independently meaningful property must survive: ' + property);
        retired += 1;
      }
    }
    assert.equal(retired, 13);
    for (const [selector, obsolete] of [
      ['.nfc-page-title', ['color', 'line-height', 'letter-spacing']],
      ['.nfc-page-description', ['max-width', 'color']],
      ['.nfc-data-panel-title', ['color', 'letter-spacing']],
      ['.nfc-data-panel-description', ['color']],
    ] as const) {
      const only = properties(selectorRules(selector)[0]);
      for (const name of obsolete) assert.equal(only.has(name), false,
        selector + ' obsolete early v049 property reintroduced: ' + name);
    }
  });

  test('retain independent eyebrow and late v049 typography with exact v056 text owners', () => {
    const expected = [
      ['.nfc-page-eyebrow', 'font-weight', '740', 0],
      ['.nfc-page-title', 'font-weight', '660', 0],
      ['.nfc-page-description', 'line-height', '1.62', 0],
      ['.nfc-data-panel-title', 'font-size', '13px', 0],
      ['.nfc-data-panel-description', 'font-size', '10.5px', 0],
    ] as const;
    for (const [selector, name, value, index] of expected) {
      const rules = selectorRules(selector);
      assert.equal(properties(rules[index]).get(name), value,
        selector + ' independent historical typography changed');
    }
    // The final same-selector values are pinned independently from v049
    // so deleting old blocks must never change the canonical text styling.
    const v056 = read('src/styles/v056-right-workspace-v2.css');
    for (const [selector, name, value] of [
      ['.nfc-page-title', 'line-height', '1.18'],
      ['.nfc-page-description', 'max-width', '82ch'],
      ['.nfc-data-panel-title', 'letter-spacing', '-0.004em'],
      ['.nfc-data-panel-description', 'color', 'var(--nfc-w2-text-subtle)'],
    ] as const) {
      const body = v056.match(new RegExp('(?:^|\\n)' +
        selector.replace(/\./g, '\\.') + '\\s*\\{([^}]*)\\}'))?.[1];
      assert.ok(body, 'Missing canonical v056 text rule: ' + selector);
      assert.equal(properties(body).get(name), value, selector + ' winner changed');
    }
  });

  test('sole historical owners stay in source order and other native styles remain', () => {
    // Search ONLY column-zero top-level blocks: a substring indexOf()
    // incorrectly matches indented phone rules and qualified selectors
    // such as "... > .nfc-data-panel-header {" before the actual owner.
    const topLevelPosition = (selector: string): number => {
      const escaped = selector.replace(/\./g, '\\.');
      return css.search(new RegExp('^' + escaped + '\\s*\\{', 'm'));
    };
    const eyebrow = topLevelPosition('.nfc-page-eyebrow');
    const title = topLevelPosition('.nfc-page-title');
    const description = topLevelPosition('.nfc-page-description');
    const panel = topLevelPosition('.nfc-data-panel-header');
    const panelTitle = topLevelPosition('.nfc-data-panel-title');
    const panelDescription = topLevelPosition('.nfc-data-panel-description');
    assert.ok(eyebrow >= 0 && eyebrow < title && title < description);
    assert.ok(description < panel && panel < panelTitle && panelTitle < panelDescription);
    for (const selector of [
      '.nfc-page-title', '.nfc-page-description',
      '.nfc-data-panel-title', '.nfc-data-panel-description',
    ]) assert.equal(selectorRules(selector).length, 1,
      'A retired early selector block was reintroduced: ' + selector);
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

  test('retire six first-mobile same-context shadows, keeping the late v049 winners', () => {
    const firstMobile = css.indexOf('@media (max-width: 767px) {');
    const secondMobile = css.lastIndexOf('@media (max-width: 767px) {');
    assert.ok(firstMobile >= 0 && secondMobile > firstMobile);
    const mediaBody = (at: number): string => {
      const open = css.indexOf('{', at);
      let depth = 0;
      for (let index = open; index < css.length; index += 1) {
        if (css[index] === '{') depth += 1;
        else if (css[index] === '}') {
          depth -= 1;
          if (depth === 0) return css.slice(open + 1, index);
        }
      }
      throw new Error('Unclosed historical mobile @media block');
    };
    const early = mediaBody(firstMobile);
    const later = mediaBody(secondMobile);
    const cases = [
      ['.nfc-header.nfc-header', 'min-height', '54px'],
      ['.nfc-page-header', 'align-items', 'stretch'],
      ['.nfc-page-header', 'gap', '12px'],
      ['.nfc-page-header-copy', 'max-width', '100%'],
      ['.nfc-metric-grid', 'grid-template-columns', 'repeat(2, minmax(0, 1fr))'],
      ['.nfc-metric-card', 'min-height', '94px'],
    ] as const;
    const body = (source: string, selector: string): string => {
      const start = source.indexOf(selector + ' {');
      if (start < 0) return '';
      const open = source.indexOf('{', start);
      return source.slice(open + 1, source.indexOf('}', open));
    };
    for (const [selector, prop, value] of cases) {
      const earlyBody = body(early, selector);
      const lateBody = body(later, selector);
      const property = new RegExp('(?:^|;)\\s*' + prop + '\\s*:\\s*([^;]+)');
      assert.doesNotMatch(earlyBody, property, selector + ' old ' + prop);
      assert.equal(lateBody.match(property)?.[1]?.trim(), value, selector + ' late ' + prop);
    }
    assert.match(body(early, '.nfc-header.nfc-header'), /margin-inline:\s*10px/);
    assert.match(body(early, '.nfc-page-header'), /min-height:\s*auto/);
    assert.doesNotMatch(body(early, '.nfc-metric-card'), /padding:\s*12px/,
      'Earlier metric padding is shadowed by the late same-context winner');
    assert.match(body(later, '.nfc-metric-card'), /padding:\s*12px 13px/,
      'Later metric-card spacing remains the winning value');
    assert.equal([...css.matchAll(/@media\s*\([^)]*\)/g)].length, 8);
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
