import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Gate6-D media metadata + integrity UI', () => {
  test('media route is wired into the main workspace and header context', () => {
    const router = read('src/router/index.tsx');
    const sidebar = read('src/components/Sidebar.tsx');
    const header = read('src/components/Header.tsx');

    assert.match(router, /path="media"[\s\S]*<MediaPage/);
    assert.match(sidebar, /key: '\/media'[\s\S]*媒体完整性/);
    assert.match(header, /'\/media': \{ kicker: 'DATA & SCAN', name: '媒体完整性' \}/);
  });

  test('media page preserves unknown versus corrupt and exposes direct-delete only through preview', () => {
    const page = read('src/pages/Media/index.tsx');

    assert.match(page, /integrity_status === 'corrupt'/);
    assert.match(page, /integrity_status === 'healthy'/);
    assert.match(page, /永久删除会绕过文件隔离区/);
    assert.match(page, /previewCorruptDelete/);
    assert.match(page, /createCorruptDeletePlan/);
    assert.match(page, /DELETE_CORRUPT_FILES|createCorruptDeletePlan/);
    assert.match(page, /validated\.status !== 'ready'/);
    assert.match(page, /plansApi\.executePlan/);
    assert.match(page, /disabled: !record\.can_direct_delete \|\| !isAdmin/);
  });

  test('media API binds deletion to the dedicated corrupt evidence endpoints', () => {
    const api = read('src/api/domain.ts');

    assert.match(api, /\/api\/media\/corrupt-delete\/preview/);
    assert.match(api, /\/api\/media\/corrupt-delete\/plan/);
    assert.match(api, /confirmation: 'DELETE_CORRUPT_FILES'/);
  });

  test('TASK-036-11 exposes immutable-baseline SHA256 verification through the media workspace', () => {
    const page = read('src/pages/Media/index.tsx');
    const api = read('src/api/domain.ts');
    const types = read('src/types/media.ts');

    assert.match(api, /\/api\/media\/integrity\/verify/);
    assert.match(api, /verification_status/);
    assert.match(page, /SHA256 完整性校验/);
    assert.match(page, /基线已建立/);
    assert.match(page, /内容变化/);
    assert.match(page, /verification_changed/);
    assert.match(types, /verification_status: 'unverified' \| 'baseline' \| 'verified' \| 'changed' \| 'unknown'/);
  });

  test('v0.4.9 workspace density covers the new media page without touching sidebar selectors', () => {
    const css = read('src/styles/v049-workspace.css');

    assert.match(css, /\.nfc-media-page > \.nfc-data-panel-dense/);
    assert.match(css, /\.nfc-media-page \.nfc-filter-bar/);
    assert.doesNotMatch(css, /\.nfc-sidebar(?:\b|\.)/);
    assert.doesNotMatch(css, /\.nfc-sidebar-menu(?:\b|\.)/);
    assert.doesNotMatch(css, /\.nfc-brand(?:\b|\.)/);
  });
});
