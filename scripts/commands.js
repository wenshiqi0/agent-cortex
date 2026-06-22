// commands.js — cortex CLI commands. Runtime: bun (ESM).
//
//   install  (no args)  -> bootstrap: relink builtin + restore externals from lock
//   install  <kind> <github|git|npm> <source> [name] [--ref r] [--path p]
//   uninstall <name>    -> delete external resource + link(s) + lock entry
//   relink              -> rebuild ALL tool symlinks (builtin + external)
//   verify  [name]      -> recompute hashes vs lock, report drift (exit 1 on drift)
//   list                -> list builtin + external, both kinds

import fs from 'fs';
import path from 'path';
import { ROOT, KIND } from './config.js';
import {
  die, rmrf, readLock, writeLock, hashResource,
  findSkill, findAgent, nameFromFrontmatter,
  copyInto, linkResource, unlinkResource,
} from './resource.js';
import { fetchGithub, fetchGit, fetchNpm } from './fetch.js';

// Install ONE external resource from a source. Returns the resolved name.
function installOne(kindArg, sourceType, source, name, ref, explicitPath) {
  const cfg = KIND[kindArg];
  if (!cfg) die('install <skill|agent> <github|git|npm> <source> [name] [--ref r] [--path p]');
  if (!sourceType || !source) die('install ' + kindArg + ' <github|git|npm> <source> [name]');

  let tmpRoot, srcRoot;
  if (sourceType === 'github') { tmpRoot = fetchGithub(source, ref); srcRoot = tmpRoot; }
  else if (sourceType === 'git') { tmpRoot = fetchGit(source, ref); srcRoot = tmpRoot; }
  else if (sourceType === 'npm') { srcRoot = fetchNpm(source); tmpRoot = path.dirname(srcRoot); }
  else die('unknown source type: ' + sourceType);

  try {
    const isFile = cfg.kind === 'file';
    const found = isFile ? findAgent(srcRoot, name, explicitPath) : findSkill(srcRoot, name, explicitPath);
    if (!found) die(`no ${kindArg} found in source`);
    name = name || nameFromFrontmatter(isFile ? found : path.join(found, 'SKILL.md'),
      isFile ? path.basename(found, '.md') : path.basename(found));

    const dest = path.join(cfg.externalDir, isFile ? name + '.md' : name);
    copyInto(found, dest, isFile);
    const hash = hashResource(dest);

    const lock = readLock(cfg);
    lock.items[name] = {
      source, sourceType,
      ...(ref ? { ref } : {}),
      resourcePath: path.relative(srcRoot, found).replace(/\\/g, '/'),
      computedHash: hash,
    };
    writeLock(cfg, lock);
    linkResource(cfg, name, dest);
    console.log(`installed ${kindArg} ${name} -> ${path.relative(ROOT, dest)}  (${hash.slice(0, 19)}…)`);
    return name;
  } finally { rmrf(tmpRoot); }
}

// `install` with no positional args: bootstrap the checkout.
//   1. relink builtin + whatever external content is already on disk
//   2. restore any external recorded in a lock but missing from disk
function bootstrap() {
  relink();
  for (const k of Object.keys(KIND)) {
    const cfg = KIND[k];
    const isFile = cfg.kind === 'file';
    const lock = readLock(cfg);
    for (const n of Object.keys(lock.items)) {
      const e = lock.items[n];
      const p = path.join(cfg.externalDir, isFile ? n + '.md' : n);
      if (fs.existsSync(p)) continue; // already present, relink handled it
      console.log(`restoring ${k} ${n} from ${e.sourceType}:${e.source}${e.ref ? '@' + e.ref : ''}`);
      installOne(k, e.sourceType, e.source, n, e.ref, e.resourcePath);
    }
  }
}

export function cmdInstall(argv) {
  // no positional args -> bootstrap; otherwise install one external
  if (argv._.length === 0) return bootstrap();
  const [kindArg, sourceType, source, name] = argv._;
  installOne(kindArg, sourceType, source, name || null, argv.ref, argv.path);
}

// Rebuild ALL tool links from scratch: builtin (knowledge/) + external (./).
export function relink() {
  for (const k of Object.keys(KIND)) {
    const cfg = KIND[k];
    const isFile = cfg.kind === 'file';
    // wipe tool dirs (real dirs of symlinks), recreate empty
    for (const td of cfg.toolDirs) { rmrf(td); fs.mkdirSync(td, { recursive: true }); }
    for (const dir of [cfg.builtinDir, cfg.externalDir]) {
      if (!fs.existsSync(dir)) continue;
      for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
        if (e.name.endsWith('-lock.json')) continue;
        if (isFile) {
          if (!e.isFile() || !e.name.endsWith('.md')) continue;
          linkResource(cfg, e.name.slice(0, -3), path.join(dir, e.name));
        } else {
          if (!e.isDirectory()) continue;
          linkResource(cfg, e.name, path.join(dir, e.name));
        }
      }
    }
    console.log(`relinked ${k}: tool dirs ${cfg.toolDirs.map(d => path.relative(ROOT, d)).join(', ')}`);
  }
}
export function cmdRelink() { relink(); }

export function cmdVerify(argv) {
  let drift = 0;
  for (const k of Object.keys(KIND)) {
    const cfg = KIND[k]; const isFile = cfg.kind === 'file';
    const lock = readLock(cfg);
    const names = argv._[0] ? [argv._[0]] : Object.keys(lock.items);
    for (const n of names) {
      const e = lock.items[n]; if (!e) continue;
      const p = path.join(cfg.externalDir, isFile ? n + '.md' : n);
      if (!fs.existsSync(p)) { console.log(`MISSING ${k} ${n}`); drift++; continue; }
      const cur = hashResource(p);
      if (cur === e.computedHash) console.log(`OK    ${k} ${n}`);
      else { console.log(`DRIFT ${k} ${n}`); drift++; }
    }
  }
  if (drift) process.exit(1);
}

export function cmdUninstall(argv) {
  const name = argv._[0]; if (!name) die('uninstall <name>');
  let hit = false;
  for (const k of Object.keys(KIND)) {
    const cfg = KIND[k]; const isFile = cfg.kind === 'file';
    const lock = readLock(cfg);
    if (lock.items[name]) {
      rmrf(path.join(cfg.externalDir, isFile ? name + '.md' : name));
      unlinkResource(cfg, name);
      delete lock.items[name]; writeLock(cfg, lock);
      console.log(`uninstalled ${k} ${name}`); hit = true;
    }
  }
  if (!hit) die('not found in any lock: ' + name);
}

export function cmdList() {
  for (const k of Object.keys(KIND)) {
    const cfg = KIND[k]; const isFile = cfg.kind === 'file';
    console.log(`# ${k}s`);
    if (fs.existsSync(cfg.builtinDir)) for (const e of fs.readdirSync(cfg.builtinDir, { withFileTypes: true }).sort((a, b) => a.name < b.name ? -1 : 1)) {
      const ok = isFile ? (e.isFile() && e.name.endsWith('.md')) : e.isDirectory();
      if (ok) console.log(`  ${isFile ? e.name.slice(0, -3) : e.name}\t[builtin]`);
    }
    const lock = readLock(cfg);
    for (const n of Object.keys(lock.items)) { const e = lock.items[n]; console.log(`  ${n}\t[${e.sourceType}:${e.source}${e.ref ? '@' + e.ref : ''}]`); }
  }
}
