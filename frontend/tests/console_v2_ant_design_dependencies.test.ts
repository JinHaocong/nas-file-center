import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(),path),'utf8');
const pkg = JSON.parse(read('package.json')) as {
  dependencies: Record<string,string>; devDependencies: Record<string,string>
};
const lock = JSON.parse(read('package-lock.json')) as {
  lockfileVersion: number;
  packages: Record<string, {
    dependencies?: Record<string,string>;
    devDependencies?: Record<string,string>;
    optionalDependencies?: Record<string,string>;
    peerDependencies?: Record<string,string>;
    peerDependenciesMeta?: Record<string,{optional?:boolean}>;
  }>
};

describe('Console v2 Ant Design npm dependency retirement', () => {
  test('npm ci root manifest and lock root are identical', () => {
    assert.equal(lock.lockfileVersion,3);
    assert.deepEqual(lock.packages[''].dependencies,pkg.dependencies);
    assert.deepEqual(lock.packages[''].devDependencies,pkg.devDependencies);
    assert.ok(Object.keys(pkg.dependencies).length > 0);
    for (const name of ['@radix-ui/react-dialog','lucide-react',
      '@tanstack/react-query','react','react-dom','react-router-dom']) {
      assert.ok(name in pkg.dependencies,name);
    }
    for (const name of ['typescript','vite','@vitejs/plugin-react']) {
      assert.ok(name in pkg.devDependencies,name);
    }
  });
  test('no direct AntD deps, transitive AntD tree or stale rc-component packages', () => {
    for (const pkgName of ['antd','@ant-design/icons']) {
      assert.equal(pkg.dependencies[pkgName],undefined);
      assert.equal(pkg.devDependencies[pkgName],undefined);
      assert.equal(lock.packages[''].dependencies?.[pkgName],undefined);
    }
    const paths=Object.keys(lock.packages);
    const unexpected=paths.filter(path=>path.startsWith('node_modules/antd') ||
      path.startsWith('node_modules/@ant-design/') ||
      path.startsWith('node_modules/@rc-component/') ||
      /^node_modules\/rc-(?:cascader|field-form|table|tabs|select|picker|dialog|util)(?:\/|$)/.test(path));
    assert.deepEqual(unexpected,[]);
  });
  test('all retained lock nodes are reachable and have resolvable mandatory deps/peers', () => {
    const files=lock.packages;
    const rootNames={...pkg.dependencies,...pkg.devDependencies};
    const lookup=(from:string,name:string):string=>{
      let parent=from;
      while(parent){
        const local=parent+'/node_modules/'+name;
        if(files[local])return local;
        const index=parent.lastIndexOf('/node_modules/');
        if(index<0)break;
        parent=parent.slice(0,index);
      }
      return 'node_modules/'+name;
    };
    const queue=Object.keys(rootNames).map(x=>'node_modules/'+x);
    const visited=new Set<string>();
    for(let i=0;i<queue.length;i++){
      const path=queue[i];
      if(visited.has(path))continue;
      visited.add(path);
      const entry=files[path];
      assert.ok(entry,'Missing npm lock node: '+path);
      for(const type of ['dependencies','optionalDependencies','peerDependencies'] as const){
        for(const name of Object.keys(entry[type]||{})){
          if(type==='peerDependencies'&&entry.peerDependenciesMeta?.[name]?.optional)continue;
          queue.push(lookup(path,name));
        }
      }
    }
    assert.equal(visited.size,Object.keys(files).length-1,
      'npm lock contains orphaned or unreachable dependency nodes');
  });
  test('runtime import gate and Docker both use the newly locked tree',()=>{
    const guard=read('scripts/check-ant-design-tail.mjs');
    assert.ok(guard.includes('const allowed = new Set(['));
    assert.ok(!guard.includes("'src/contexts/ThemeContext.tsx'"));
    assert.ok(guard.includes('const unexpected = matches.filter(item => !item.approved)'));
    const docker=read('../Dockerfile');
    assert.ok(docker.includes('COPY frontend/package.json frontend/package-lock.json ./'));
    assert.ok(docker.includes('RUN npm ci'));
  });
});
