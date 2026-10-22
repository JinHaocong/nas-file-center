import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
const read = file => readFileSync(resolve(process.cwd(),file),'utf8');
const old = read('src/styles/v048-detail.css');
const files = ["v056-right-workspace-v2.css","v054-premium-system.css","v052-final-audit.css","v049-workspace.css","v051-product-polish.css"];
const successor = Object.fromEntries(files.map(file => [file,read('src/styles/'+file)]));
const cases = [
  [
    "",
    ".nfc-header.nfc-header",
    "min-height",
    "v056-right-workspace-v2.css",
    "68px"
  ],
  [
    "",
    ".nfc-header-command-cluster",
    "gap",
    "v054-premium-system.css",
    "4px"
  ],
  [
    "",
    ".nfc-page-header-copy",
    "max-width",
    "v056-right-workspace-v2.css",
    "min(980px, 74vw)"
  ],
  [
    "",
    ".nfc-page-title",
    "text-wrap",
    "v056-right-workspace-v2.css",
    "balance"
  ],
  [
    "",
    ".nfc-page-description",
    "text-wrap",
    "v052-final-audit.css",
    "pretty"
  ],
  [
    "",
    ".nfc-page-actions .nfc-action-bar",
    "justify-content",
    "v052-final-audit.css",
    "flex-end"
  ],
  [
    "",
    ".nfc-responsive-descriptions",
    "overflow",
    "v049-workspace.css",
    "clip"
  ],
  [
    "",
    ".nfc-responsive-descriptions",
    "border",
    "v049-workspace.css",
    "1px solid var(--nfc-v49-line) !important"
  ],
  [
    "",
    ".nfc-responsive-descriptions",
    "border-radius",
    "v049-workspace.css",
    "var(--nfc-v49-radius-lg) !important"
  ],
  [
    "",
    ".nfc-responsive-descriptions",
    "background",
    "v049-workspace.css",
    "var(--nfc-v49-surface) !important"
  ],
  [
    "",
    ".nfc-row-actions",
    "gap",
    "v056-right-workspace-v2.css",
    "2px"
  ],
  [
    "",
    ".nfc-row-actions",
    "opacity",
    "v056-right-workspace-v2.css",
    "0.56"
  ],
  [
    "",
    ".nfc-row-actions",
    "transition",
    "v051-product-polish.css",
    "opacity 140ms ease, transform 140ms ease"
  ],
  [
    "",
    ".nfc-row-actions:focus-within",
    "opacity",
    "v056-right-workspace-v2.css",
    "1"
  ],
  [
    "",
    ".nfc-status-dot",
    "width",
    "v049-workspace.css",
    "5px"
  ],
  [
    "",
    ".nfc-status-dot",
    "height",
    "v049-workspace.css",
    "5px"
  ],
  [
    "",
    ".nfc-centered-state",
    "min-height",
    "v049-workspace.css",
    "240px"
  ],
  [
    "",
    ".nfc-centered-state",
    "color",
    "v049-workspace.css",
    "var(--nfc-v49-muted)"
  ],
  [
    "",
    ".nfc-mobile-pagination",
    "min-height",
    "v049-workspace.css",
    "50px"
  ],
  [
    "",
    ".nfc-mobile-pagination",
    "padding",
    "v049-workspace.css",
    "9px 12px"
  ],
  [
    "",
    ".nfc-mobile-pagination",
    "background",
    "v049-workspace.css",
    "color-mix(in srgb, var(--nfc-nav-surface) 68%, transparent)"
  ],
  [
    "@media (max-width: 1199px)",
    ".nfc-page-header-copy",
    "max-width",
    "v056-right-workspace-v2.css",
    "min(860px, 68vw)"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-header-status",
    "max-width",
    "v056-right-workspace-v2.css",
    "min(54vw, 250px)"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-header-status",
    "overflow-x",
    "v056-right-workspace-v2.css",
    "auto"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-header-status",
    "scrollbar-width",
    "v056-right-workspace-v2.css",
    "none"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-header-status::-webkit-scrollbar",
    "display",
    "v056-right-workspace-v2.css",
    "none"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-page-header-copy",
    "max-width",
    "v056-right-workspace-v2.css",
    "none"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-page-actions .nfc-action-bar",
    "justify-content",
    "v052-final-audit.css",
    "flex-start"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-responsive-descriptions",
    "grid-template-columns",
    "v049-workspace.css",
    "repeat(2, minmax(0, 1fr))"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-description-item",
    "min-height",
    "v049-workspace.css",
    "66px"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-description-item",
    "padding",
    "v049-workspace.css",
    "10px 11px"
  ],
  [
    "@media (max-width: 767px)",
    ".nfc-row-actions",
    "opacity",
    "v051-product-polish.css",
    "1"
  ],
  [
    "@media (max-width: 420px)",
    ".nfc-responsive-descriptions",
    "grid-template-columns",
    "v049-workspace.css",
    "1fr"
  ]
];

// Parse leaf declarations by complete selector and ancestor @media context.
// Never treat a matching property under another media scope as a replacement.
function leaf(css){
 const out=[],stack=[];let start=0,comment=false,quote=null,escaped=false;
 for(let i=0;i<css.length;i++){
  const c=css[i],n=css[i+1];
  if(comment){if(c==='*'&&n==='/'){comment=false;i++}continue}
  if(quote){if(escaped){escaped=false;continue}if(c==='\\'){escaped=true;continue}if(c===quote)quote=null;continue}
  if(c==='/'&&n==='*'){comment=true;i++;continue}
  if(c==='"'||c==="'"){quote=c;continue}
  if(c==='{'){
   const sel=css.slice(start,i).replace(/\/\*[\s\S]*?\*\//g,'').trim().replace(/\s+/g,' ');
   stack.push({sel,ctx:stack.filter(s=>s.sel.startsWith('@')).map(s=>s.sel).join(' > '),start:i+1});start=i+1;
  }else if(c==='}'){
   const rule=stack.pop();assert.ok(rule,'balanced CSS');
   const body=css.slice(rule.start,i),decls=new Map();
   if(!rule.sel.startsWith('@')&&!body.includes('{')){
    for(const field of body.replace(/\/\*[\s\S]*?\*\//g,'').split(';')){
     const at=field.indexOf(':');if(at>0)decls.set(field.slice(0,at).trim(),field.slice(at+1).trim());
    }
    out.push({sel:rule.sel,ctx:rule.ctx,decls});
   }start=i+1;
  }else if(c===';'&&!stack.length)start=i+1;
 }
 assert.equal(stack.length,0,'CSS braces must close');return out;
}
const before=leaf(old);
const after=Object.fromEntries(files.map(file=>[file,leaf(successor[file])]));
const matching=(rules,ctx,sel)=>rules.filter(r=>r.ctx===ctx&&r.sel===sel);

test('33 exact v048 detail declarations stay retired with fixed late owner values',()=>{
 assert.equal(cases.length,33);
 assert.equal(new Set(cases.map(c=>c.slice(0,3).join('|'))).size,33);
 for(const [ctx,sel,prop,file,value] of cases){
  const label=[ctx,sel,prop].join(' | ');
  assert.ok(matching(before,ctx,sel).every(r=>!r.decls.has(prop)),'old declaration returned: '+label);
  const owners=matching(after[file],ctx,sel).filter(r=>r.decls.has(prop));
  assert.ok(owners.length,'owner missing: '+file+' '+label);
  assert.equal(owners.at(-1).decls.get(prop),value,'owner value changed: '+file+' '+label);
 }
});
test('independent badges, borders, accessibility and narrow viewport rules remain',()=>{
 for(const [ctx,sel,prop,val] of [
  ['', '.nfc-header-status-badge.is-safe','color','var(--nfc-success) !important'],
  ['', '.nfc-header-workspace-kicker','text-overflow','ellipsis'],
  ['', '.nfc-responsive-descriptions','border-top','1px solid var(--nfc-premium-line) !important'],
  ['', '.nfc-status-dot','box-shadow','none'],
  ['', '.nfc-mobile-pagination','border-top','1px solid var(--nfc-premium-line)'],
  ['@media (max-width: 767px)','.nfc-header-status','padding','2px'],
  ['@media (max-width: 767px)','.nfc-description-item:nth-child(2n)','border-right','0'],
  ['@media (max-width: 420px)','.nfc-description-item:last-child','border-bottom','0'],
  ['@media (prefers-reduced-motion: reduce)','.nfc-row-actions','transition','none'],
 ]){
  assert.ok(matching(before,ctx,sel).some(r=>r.decls.get(prop)===val),
   'Independent early property lost: '+ctx+' '+sel+' '+prop);
 }
 assert.match(old,/@keyframes nfc-detail-live-pulse/);
 assert.match(old,/--nfc-detail-row: 46px/);
});
test('import precedence and read-only Chromium validation preserved',()=>{
 const entry=read('src/main.tsx');
 const names=['v048-detail.css','v049-workspace.css','v051-product-polish.css','v052-final-audit.css','v054-premium-system.css','v056-right-workspace-v2.css','console-v2.css'];
 let prior=-1;for(const f of names){const pos=entry.indexOf("import './styles/"+f+"';");assert.ok(pos>prior,'import order changed '+f);prior=pos}
 const workflow=read('../.github/workflows/ui-v044-validation.yml');
 for(const script of ['browser-full-route-visual.mjs','browser-workspace-cascade.mjs','browser-overlay-smoke.mjs'])
  assert.ok(workflow.includes(script),'browser check missing '+script);
});
