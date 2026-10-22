import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
const read = file => readFileSync(resolve(process.cwd(),'src/styles',file),'utf8');
const oldFiles = ['v050-layout.css','v054-premium-system.css','v055-workspace-breathing.css'];
const lateFiles = ["v056-right-workspace-v2.css","v052-final-audit.css","v055-workspace-breathing.css"];
const cases = [
  [
    "v050-layout.css",
    "@media (max-width: 1199px)",
    ".nfc-dashboard-page .nfc-dashboard-layout",
    "grid-template-columns",
    "v056-right-workspace-v2.css",
    "1fr"
  ],
  [
    "v050-layout.css",
    "@media (max-width: 1199px)",
    ".nfc-dashboard-page .nfc-dashboard-rail",
    "position",
    "v056-right-workspace-v2.css",
    "static"
  ],
  [
    "v050-layout.css",
    "@media (max-width: 1199px)",
    ".nfc-dashboard-page .nfc-dashboard-rail",
    "grid-template-columns",
    "v056-right-workspace-v2.css",
    "repeat(2, minmax(0, 1fr))"
  ],
  [
    "v050-layout.css",
    "@media (max-width: 767px)",
    ".nfc-dashboard-page .nfc-dashboard-rail",
    "grid-template-columns",
    "v056-right-workspace-v2.css",
    "1fr"
  ],
  [
    "v050-layout.css",
    "",
    ".nfc-system-controls-page .nfc-settings-subpanel",
    "border-radius",
    "v052-final-audit.css",
    "12px !important"
  ],
  [
    "v050-layout.css",
    "",
    ".nfc-tasks-page .nfc-filter-bar",
    "justify-content",
    "v052-final-audit.css",
    "start"
  ],
  [
    "v050-layout.css",
    "",
    ".nfc-tasks-page .nfc-filter-bar",
    "gap",
    "v052-final-audit.css",
    "10px 12px"
  ],
  [
    "v050-layout.css",
    "",
    ".nfc-tasks-page .nfc-filter-control",
    "min-width",
    "v052-final-audit.css",
    "0"
  ],
  [
    "v050-layout.css",
    "",
    ".nfc-tasks-page .nfc-filter-control",
    "grid-template-columns",
    "v052-final-audit.css",
    "64px minmax(0, 1fr)"
  ],
  [
    "v050-layout.css",
    "",
    ".nfc-system-controls-page .nfc-settings-grid",
    "align-items",
    "v052-final-audit.css",
    "start"
  ],
  [
    "v050-layout.css",
    "@media (max-width: 767px)",
    ".nfc-tasks-page .nfc-filter-control",
    "grid-template-columns",
    "v052-final-audit.css",
    "72px minmax(0, 1fr)"
  ],
  [
    "v054-premium-system.css",
    "",
    ".nfc-app-main .nfc-page-header::after",
    "left",
    "v055-workspace-breathing.css",
    "var(--nfc-v55-hero-x)"
  ],
  [
    "v054-premium-system.css",
    "",
    ".nfc-app-main .nfc-page-header::after",
    "bottom",
    "v055-workspace-breathing.css",
    "-1px"
  ],
  [
    "v054-premium-system.css",
    "",
    ".nfc-app-main .nfc-page-header::after",
    "width",
    "v055-workspace-breathing.css",
    "88px"
  ],
  [
    "v054-premium-system.css",
    "",
    ".nfc-app-main .nfc-page-header::after",
    "height",
    "v055-workspace-breathing.css",
    "2px"
  ],
  [
    "v054-premium-system.css",
    "",
    ".nfc-app-main .nfc-page-header::after",
    "background",
    "v055-workspace-breathing.css",
    "linear-gradient(\n    90deg,\n    color-mix(in srgb, var(--nfc-accent) 62%, transparent),\n    color-mix(in srgb, var(--nfc-accent) 6%, transparent)\n  )"
  ],
  [
    "v054-premium-system.css",
    "@media (max-width: 767px)",
    ".nfc-app-main .nfc-page-header::after",
    "left",
    "v055-workspace-breathing.css",
    "var(--nfc-v55-hero-x)"
  ],
  [
    "v054-premium-system.css",
    "@media (max-width: 767px)",
    ".nfc-app-main .nfc-page-header::after",
    "width",
    "v055-workspace-breathing.css",
    "58px"
  ],
  [
    "v055-workspace-breathing.css",
    "@media (max-width: 767px)",
    ".nfc-app-main .nfc-page-content",
    "padding",
    "v056-right-workspace-v2.css",
    "16px 14px max(48px, calc(var(--nfc-mobile-dock-height, 78px) + 28px + env(safe-area-inset-bottom)))"
  ],
  [
    "v055-workspace-breathing.css",
    "@media (max-width: 767px)",
    ".nfc-app-main .nfc-page-header",
    "min-height",
    "v056-right-workspace-v2.css",
    "0"
  ],
  [
    "v055-workspace-breathing.css",
    "@media (max-width: 767px)",
    ".nfc-app-main .nfc-page-header",
    "margin-bottom",
    "v056-right-workspace-v2.css",
    "22px"
  ],
  [
    "v055-workspace-breathing.css",
    "@media (max-width: 767px)",
    ".nfc-app-main .nfc-page-header",
    "padding",
    "v056-right-workspace-v2.css",
    "0 0 18px"
  ],
  [
    "v055-workspace-breathing.css",
    "@media (max-width: 767px)",
    ".nfc-app-main .nfc-page-header",
    "border-radius",
    "v056-right-workspace-v2.css",
    "0"
  ],
  [
    "v055-workspace-breathing.css",
    "@media (max-width: 767px)",
    ".nfc-app-main .nfc-page-header",
    "gap",
    "v056-right-workspace-v2.css",
    "15px"
  ],
  [
    "v055-workspace-breathing.css",
    "@media (max-width: 767px)",
    ".nfc-app-main .nfc-dashboard-page .nfc-dashboard-command-deck",
    "gap",
    "v056-right-workspace-v2.css",
    "8px"
  ],
  [
    "v055-workspace-breathing.css",
    "@media (max-width: 767px)",
    ".nfc-app-main .nfc-dashboard-page .nfc-dashboard-command-deck .nfc-metric-card",
    "min-height",
    "v056-right-workspace-v2.css",
    "86px"
  ],
  [
    "v055-workspace-breathing.css",
    "@media (max-width: 767px)",
    ".nfc-app-main .nfc-dashboard-page .nfc-dashboard-command-deck .nfc-metric-card",
    "padding",
    "v056-right-workspace-v2.css",
    "11px 12px"
  ],
  [
    "v055-workspace-breathing.css",
    "@media (max-width: 767px)",
    ".nfc-app-main .nfc-dashboard-page .nfc-dashboard-command-deck .nfc-snapshot-note",
    "padding",
    "v056-right-workspace-v2.css",
    "9px 11px"
  ]
];

function leaf(css){
 const result=[],stack=[];let start=0,comment=false,quote=null,escaped=false;
 for(let i=0;i<css.length;i++){
  const c=css[i],n=css[i+1];
  if(comment){if(c==='*'&&n==='/'){comment=false;i++}continue}
  if(quote){if(escaped){escaped=false;continue}if(c==='\\'){escaped=true;continue}if(c===quote)quote=null;continue}
  if(c==='/'&&n==='*'){comment=true;i++;continue}
  if(c==='"'||c==="'"){quote=c;continue}
  if(c==='{'){
   const sel=css.slice(start,i).replace(/\/\*[\s\S]*?\*\//g,'').trim().replace(/\s+/g,' ');
   stack.push({sel,ctx:stack.filter(x=>x.sel.startsWith('@')).map(x=>x.sel).join(' > '),from:i+1});start=i+1;
  }else if(c==='}'){
   const e=stack.pop();assert.ok(e,'Unexpected CSS }');const body=css.slice(e.from,i),props=new Map();
   if(!e.sel.startsWith('@')&&!body.includes('{')){
    for(const part of body.replace(/\/\*[\s\S]*?\*\//g,'').split(';')){const j=part.indexOf(':');if(j>0)props.set(part.slice(0,j).trim(),part.slice(j+1).trim())}
    result.push({sel:e.sel,ctx:e.ctx,props});
   }start=i+1;
  }else if(c===';'&&!stack.length)start=i+1;
 }
 assert.equal(stack.length,0,'Unclosed CSS context');return result;
}
const early=Object.fromEntries(oldFiles.map(f=>[f,leaf(read(f))]));
const later=Object.fromEntries(lateFiles.map(f=>[f,leaf(read(f))]));
const matches=(rs,ctx,sel)=>rs.filter(r=>r.ctx===ctx&&r.sel===sel);

test('28 earlier full-selector, full-at-rule properties remain absent and late values fixed',()=>{
 assert.equal(cases.length,28);
 assert.equal(new Set(cases.map(c=>c.slice(0,4).join('|'))).size,28);
 for(const [file,ctx,selector,prop,owner,val] of cases){
  const name=[file,ctx,selector,prop].join(' | ');
  assert.ok(matches(early[file],ctx,selector).every(r=>!r.props.has(prop)),'Earlier property returned: '+name);
  const finals=matches(later[owner],ctx,selector).filter(r=>r.props.has(prop));
  assert.ok(finals.length,'Owner disappeared: '+owner+' '+name);
  assert.equal(finals.at(-1).props.get(prop),val,'Owner value changed: '+owner+' '+name);
 }
});
test('independent layout, ornaments, responsive and accessibility rules remain',()=>{
 for(const [file,ctx,selector,prop,val] of [
  ['v050-layout.css','','.nfc-tasks-page .nfc-filter-bar','min-height','60px'],
  ['v050-layout.css','','.nfc-tasks-page .nfc-filter-control','display','grid'],
  ['v050-layout.css','@media (max-width: 767px)','.nfc-dashboard-page .nfc-dashboard-rail','display','grid'],
  ['v054-premium-system.css','','.nfc-app-main .nfc-page-header::after','position','absolute'],
  ['v054-premium-system.css','','.nfc-app-main .nfc-page-header::after','border-radius','var(--nfc-radius-pill)'],
  ['v055-workspace-breathing.css','@media (max-width: 767px)','.nfc-app-main .nfc-page-header::after','left','var(--nfc-v55-hero-x)'],
  ['v055-workspace-breathing.css','@media (max-width: 767px)','.nfc-app-main .nfc-page-header::after','width','58px'],
  ['v055-workspace-breathing.css','@media (max-width: 767px)','.nfc-app-main .nfc-dashboard-page .nfc-dashboard-command-deck','margin-bottom','18px'],
 ])assert.ok(matches(early[file],ctx,selector).some(r=>r.props.get(prop)===val),'Independent CSS lost: '+file+' '+ctx+' '+selector+' '+prop);
 for(const file of oldFiles)assert.match(read(file),/@media \(max-width: 767px\)/);
 assert.match(read('v054-premium-system.css'),/@media \(prefers-reduced-motion: reduce\)/);
 assert.match(read('v054-premium-system.css'),/@media \(prefers-reduced-transparency: reduce\)/);
});
test('original import order and actual read-only Chromium gate remain',()=>{
 const entry=readFileSync(resolve(process.cwd(),'src/main.tsx'),'utf8');
 const files=['v050-layout.css','v052-final-audit.css','v054-premium-system.css','v055-workspace-breathing.css','v056-right-workspace-v2.css','console-v2.css'];
 let prev=-1;for(const file of files){const i=entry.indexOf("import './styles/"+file+"';");assert.ok(i>prev,'Import order '+file);prev=i}
 const workflow=readFileSync(resolve(process.cwd(),'../.github/workflows/ui-v044-validation.yml'),'utf8');
 for(const name of ['browser-full-route-visual.mjs','browser-workspace-cascade.mjs','browser-overlay-smoke.mjs'])assert.ok(workflow.includes(name),'Missing Chromium gate '+name);
});
