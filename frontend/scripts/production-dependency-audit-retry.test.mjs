import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, readFileSync, rmSync, chmodSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const script=resolve('scripts/run-production-dependency-audit.mjs');
const mock=`#!/usr/bin/env node
const fs = require('node:fs');
const p=process.env.NFC_AUDIT_TEST_COUNTER;
const n=(fs.existsSync(p)?Number(fs.readFileSync(p,'utf8')):0)+1;
fs.writeFileSync(p,String(n));
const args=process.argv.slice(2);
for(const flag of ['audit','--omit=dev','--audit-level=moderate','--fetch-retries=0','--fetch-timeout=45000']){
 if(!args.includes(flag)){process.stderr.write('missing '+flag+'\\n');process.exit(3)}
}
const mode=process.env.NFC_AUDIT_TEST_MODE;
if(mode==='clean'||mode==='recover'&&n>=2){process.stdout.write('found 0 vulnerabilities\\n');process.exit(0)}
if(mode==='vulnerability'){process.stdout.write('2 moderate vulnerabilities\\n');process.exit(1)}
if(mode==='unknown'){process.stderr.write('npm ERR audit connection dropped\\n');process.exit(1)}
process.stderr.write('npm warn audit 503 Service Unavailable - POST https://registry.npmjs.org/-/npm/v1/security/audits/quick\\n');process.exit(1);
`;
function exercise(mode) {
 const dir=mkdtempSync(join(tmpdir(),'nfc-audit-'));
 try {
  const cmd=join(dir,'npm'), count=join(dir,'attempts');
  writeFileSync(cmd,mock);chmodSync(cmd,0o755);
  const res=spawnSync(process.execPath,[script],{
   cwd:process.cwd(),encoding:'utf8',timeout:12000,
   env:{...process.env,PATH:dir+':'+process.env.PATH,
    NFC_AUDIT_RETRY_DELAY_MS:'0', NFC_AUDIT_TEST_MODE:mode,
    NFC_AUDIT_TEST_COUNTER:count}
  });
  const n=Number(readFileSync(count,'utf8'));
  assert.equal(res.error,undefined,res.error?.message);
  return {res,n,output:(res.stdout||'')+'\n'+(res.stderr||'')};
 } finally {rmSync(dir,{recursive:true,force:true})}
}

test('production npm audit recovers only after a transient 503 then succeeds',()=>{
 const {res,n,output}=exercise('recover');
 assert.equal(res.status,0,output);assert.equal(n,2);
 assert.match(output,/retrying only transient service failure/);
});
test('persistent npm advisory HTTP 503 fails closed after three bounded attempts',()=>{
 const {res,n,output}=exercise('outage');
 assert.equal(res.status,1);assert.equal(n,3);
 assert.match(output,/FAIL CLOSED/);
});
test('moderate/high production vulnerability fails immediately, no retry',()=>{
 const {res,n,output}=exercise('vulnerability');
 assert.equal(res.status,1);assert.equal(n,1);
 assert.match(output,/audit failed; no bypass/);
});
test('unknown network failures fail immediately instead of being hidden',()=>{
 const {res,n}=exercise('unknown');
 assert.equal(res.status,1);assert.equal(n,1);
});
test('clean npm audit completes with exactly one invocation',()=>{
 const {res,n}=exercise('clean');assert.equal(res.status,0);assert.equal(n,1);
});
test('CI installs locked tree and runs fail-closed audit on exact PR/main SHA',()=>{
 const workflow=readFileSync(resolve('../.github/workflows/dependency-audit.yml'),'utf8');
 const runner=readFileSync(resolve('scripts/run-tests.mjs'),'utf8');
 assert.match(workflow,/ref: \$\{\{ github\.event\.pull_request\.head\.sha \|\| github\.sha \}\}/);
 assert.match(workflow,/npm ci --ignore-scripts/);
 assert.match(workflow,/node scripts\/run-production-dependency-audit\.mjs/);
 assert.doesNotMatch(workflow,/continue-on-error:\s*true/);
 assert.match(runner,/node --test scripts\/production-dependency-audit-retry\.test\.mjs/);
 const src=readFileSync(script,'utf8');
 for(const guard of ['--omit=dev','--audit-level=moderate','--fetch-retries=0','--fetch-timeout=45000','MAX_ATTEMPTS = 3','process.exit(1)'])
  assert.ok(src.includes(guard),'Required fail-closed guard removed: '+guard);
});
