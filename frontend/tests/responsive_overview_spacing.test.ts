import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('deployed responsive spacing regression', () => {
  test('phone page headers reset the tablet flex basis that created vertical dead space', () => {
    const css = read('src/styles/v056-right-workspace-v2.css');

    assert.match(
      css,
      /@media \(max-width: 767px\)[\s\S]*\.nfc-app-main \.nfc-page-header-copy\s*\{[\s\S]*flex:\s*0 1 auto/
    );
    assert.match(
      css,
      /@media \(max-width: 767px\)[\s\S]*\.nfc-app-main \.nfc-page-header\s*\{[\s\S]*justify-content:\s*flex-start/
    );
    assert.match(
      css,
      /\.nfc-app-main \.nfc-page-layout-ledger > \.nfc-page-header\s*\{[\s\S]*margin-bottom:\s*0 !important[\s\S]*padding-bottom:\s*12px/
    );
  });

  test('index actions stay directly attached to the mobile header instead of being pushed down-screen', () => {
    const css = read('src/styles/v056-right-workspace-v2.css');
    const indexes = read('src/pages/Indexes/index.tsx');

    assert.match(indexes, /nfc-indexes-page nfc-page-layout-ledger/);
    assert.match(
      css,
      /\.nfc-app-main \.nfc-indexes-page \.nfc-page-actions \.nfc-action-bar\s*\{[\s\S]*flex-wrap:\s*wrap[\s\S]*gap:\s*8px/
    );
  });

  test('dashboard has one compact spacing rhythm on desktop and removes forced panel height', () => {
    const css = read('src/styles/v056-right-workspace-v2.css');
    const dashboard = read('src/pages/Dashboard/index.tsx');

    assert.match(dashboard, /nfc-dashboard-page nfc-operations-page nfc-page-layout-dashboard/);
    assert.match(
      css,
      /\.nfc-app-main \.nfc-dashboard-page \.nfc-dashboard-command-deck\s*\{[\s\S]*margin:\s*0;[\s\S]*gap:\s*10px/
    );
    assert.match(
      css,
      /\.nfc-app-main \.nfc-dashboard-page \.nfc-dashboard-layout\s*\{[\s\S]*margin-top:\s*0;[\s\S]*gap:\s*18px/
    );
    assert.match(
      css,
      /\.nfc-app-main \.nfc-dashboard-page \.nfc-dashboard-main-column > \.nfc-data-panel\s*\{[\s\S]*min-height:\s*0/
    );
  });

  test('dashboard mobile keeps 2x2 metrics and prioritizes quick actions before activity history', () => {
    const css = read('src/styles/v056-right-workspace-v2.css');

    assert.match(
      css,
      /@media \(max-width: 767px\)[\s\S]*\.nfc-app-main \.nfc-dashboard-page \.nfc-dashboard-command-deck \.nfc-metric-grid\s*\{[\s\S]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)/
    );
    assert.match(
      css,
      /@media \(max-width: 767px\)[\s\S]*\.nfc-app-main \.nfc-dashboard-page \.nfc-dashboard-rail\s*\{[\s\S]*order:\s*-1[\s\S]*grid-template-columns:\s*1fr/
    );
    assert.match(
      css,
      /@media \(max-width: 420px\)[\s\S]*\.nfc-dashboard-command-deck \.nfc-metric-grid\s*\{[\s\S]*repeat\(2, minmax\(0, 1fr\)\)/
    );
  });
});
