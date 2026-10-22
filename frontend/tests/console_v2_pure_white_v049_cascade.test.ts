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
    // 122-case exact-context source regression pins every former v049 declaration.
    // This test separately protects the final text/eyebrow ownership contract.
    const canonical = read('src/styles/v056-right-workspace-v2.css');
    const laterBody = (sel: string): string => {
      const rx=new RegExp('(?:^|\\n)'+sel.replace(/\./g,'\\.')+'\\s*\\{([^}]*)\\}');
      return canonical.match(rx)?.[1] ?? '';
    };
    for(const [sel,p,v] of [
      ['.nfc-page-title','font-size','clamp(27px, 1.45vw, 31px)'],
      ['.nfc-page-description','font-size','13px'],
      ['.nfc-data-panel-title','font-size','14px'],
      ['.nfc-data-panel-description','font-size','11.5px'],
    ] as const){
      assert.ok(selectorRules(sel).every(rule=>!properties(rule).has(p)),
        'Retired typography returned in v049: '+sel+' '+p);
      assert.equal(properties(laterBody(sel)).get(p),v,'Canonical v056 typography drift: '+sel+' '+p);
    }
    const eyebrow=selectorRules('.nfc-page-eyebrow');
    assert.ok(eyebrow.some(rule=>properties(rule).get('font-weight')==='740'),
      'Independent v049 eyebrow tracking/weight should remain');
    assert.ok(eyebrow.some(rule=>properties(rule).get('font-size')==='8.5px'));
  });

  test('retain independent eyebrow and late v049 typography with exact v056 text owners', () => {
    const original=selectorRules('.nfc-page-eyebrow');
    assert.ok(original.some(rule=>properties(rule).get('font-weight')==='740'));
    assert.ok(original.some(rule=>properties(rule).get('letter-spacing')==='0.14em'));
    const late=read('src/styles/v056-right-workspace-v2.css');
    for(const [selector,prop,val] of [
      ['.nfc-page-title','line-height','1.18'],
      ['.nfc-page-description','max-width','82ch'],
      ['.nfc-data-panel-title','letter-spacing','-0.004em'],
      ['.nfc-data-panel-description','color','var(--nfc-w2-text-subtle)'],
    ] as const){
      const regex=new RegExp('(?:^|\\n)'+selector.replace(/\./g,'\\.')+'\\s*\\{([^}]*)\\}');
      const body=late.match(regex)?.[1];
      assert.ok(body,'Canonical v056 rule missing: '+selector);
      assert.equal(properties(body).get(prop),val,'Final v056 textual contract drifted '+selector+' '+prop);
    }
  });

  test('sole historical owners stay in source order and other native styles remain', () => {
    const eyebrow=css.indexOf('.nfc-page-eyebrow {');
    const panel=css.indexOf('.nfc-data-panel-header {');
    assert.ok(eyebrow>=0 && panel>=0,'Independent historical eyebrow/panel frame disappeared');
    for(const selector of [
      '.nfc-page-title','.nfc-page-description',
      '.nfc-data-panel-title','.nfc-data-panel-description',
    ]) assert.ok(selectorRules(selector).every(rule=>!properties(rule).has('font-size')),
      'Obsolete text sizing in v049: '+selector);
    for(const marker of [
      '.nfc-data-panel-dense {','.nfc-page-header {',
      '.nfc-directory-list-viewport {','.nfc-mobile-pagination {',
    ])assert.ok(css.includes(marker),'Independent native v049 owner missing: '+marker);
    assert.match(read('src/styles/v056-right-workspace-v2.css'),
      /\.nfc-row-actions:focus-within\s*\{[^}]*opacity:\s*1;/,
      'Final keyboard focus owner must remain');
    assert.doesNotMatch(css,/\.(?:ant-[a-z][\w-]*|anticon\b)/);
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
    assert.equal([...css.matchAll(/@media\s*\([^)]*\)/g)].length,8);
    assert.match(css,/@media \(max-width: 767px\)/);
    assert.match(css,/@media \(prefers-reduced-motion: reduce\)/);
    assert.match(css,/@media \(prefers-reduced-transparency: reduce\)/);
    assert.match(css,/@media \(max-width: 767px\)[\s\S]*\.nfc-metric-grid\s*\{[^}]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)/,
      'Independent phone metric columns remain in v049');
    const late=read('src/styles/v056-right-workspace-v2.css');
    for(const [sel,prop,v] of [
      ['.nfc-header.nfc-header','min-height','52px'],
      ['.nfc-page-header','gap','15px'],
      ['.nfc-page-header-copy','max-width','none'],
      ['.nfc-metric-card','min-height','96px'],
      ['.nfc-metric-card','padding','13px'],
    ] as const){
      // Mobile context and early absence are pinned exactly by the 122-case guard.
      const finalMedia=late.slice(late.indexOf('@media (max-width: 767px)'));
      assert.ok(finalMedia.includes(prop+': '+v+';'),
        'Phone authority changed in v056: '+sel+' '+prop);
    }
    assert.match(css,/\.nfc-header\.nfc-header\s*\{[^}]*border:\s*1px solid var\(--nfc-border-soft\) !important/,
      'Early important header border remains protected');
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
