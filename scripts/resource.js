// resource.js — low-level helpers: shell, fs, symlink, lockfile, hashing,
// source lookup, copy, link/unlink. Runtime: bun (ESM).

import fs from 'fs';
import path from 'path';
import os from 'os';
import crypto from 'crypto';
import { execFileSync } from 'child_process';
import { LOCK_VERSION } from './config.js';

export function die(m) { console.error('error: ' + m); process.exit(1); }
export function sh(cmd, args, opts = {}) {
  return execFileSync(cmd, args, { stdio: ['ignore', 'pipe', 'inherit'], encoding: 'utf8', ...opts });
}
export function rmrf(p) { fs.rmSync(p, { recursive: true, force: true }); }
export function mkdtmp() { return fs.mkdtempSync(path.join(os.tmpdir(), 'cortex-')); }

export function relSymlink(target, link) {
  fs.mkdirSync(path.dirname(link), { recursive: true });
  const rel = path.relative(path.dirname(link), target);
  if (fs.existsSync(link) || fs.lstatSync(link, { throwIfNoEntry: false })) rmrf(link);
  fs.symlinkSync(rel, link);
}

export function readLock(cfg) {
  if (!fs.existsSync(cfg.lock)) return { version: LOCK_VERSION, items: {} };
  try { return JSON.parse(fs.readFileSync(cfg.lock, 'utf8')); }
  catch (e) { die('corrupt lock ' + cfg.lock + ': ' + e.message); }
}
export function writeLock(cfg, lock) {
  lock.version = LOCK_VERSION;
  fs.mkdirSync(path.dirname(cfg.lock), { recursive: true });
  fs.writeFileSync(cfg.lock, JSON.stringify(lock, null, 2) + '\n');
}

// SHA-256 over a resource. Folder: all files (sorted rel path + bytes). File: its bytes.
export function hashResource(p) {
  const h = crypto.createHash('sha256');
  const st = fs.statSync(p);
  if (st.isFile()) { h.update(fs.readFileSync(p)); return 'sha256:' + h.digest('hex'); }
  const files = [];
  (function walk(d, rel) {
    for (const e of fs.readdirSync(d, { withFileTypes: true }).sort((a, b) => a.name < b.name ? -1 : 1)) {
      if (e.name === '.git' || e.name === 'node_modules') continue;
      const abs = path.join(d, e.name), r = rel ? rel + '/' + e.name : e.name;
      if (e.isDirectory()) walk(abs, r);
      else if (e.isFile()) files.push([r, abs]);
    }
  })(p, '');
  for (const [rel, abs] of files) { h.update(rel, 'utf8'); h.update('\0'); h.update(fs.readFileSync(abs)); h.update('\0'); }
  return 'sha256:' + h.digest('hex');
}

// Find a skill folder (dir with SKILL.md) inside a source tree.
export function findSkill(srcRoot, name, explicit) {
  const cands = [];
  if (explicit) cands.push(path.join(srcRoot, explicit));
  if (name) cands.push(path.join(srcRoot, 'skills', name), path.join(srcRoot, name));
  cands.push(srcRoot);
  for (const c of cands) if (fs.existsSync(path.join(c, 'SKILL.md'))) return c;
  const sd = path.join(srcRoot, 'skills');
  if (fs.existsSync(sd)) for (const e of fs.readdirSync(sd, { withFileTypes: true }))
    if (e.isDirectory() && fs.existsSync(path.join(sd, e.name, 'SKILL.md'))) return path.join(sd, e.name);
  return null;
}
// Find an agent .md inside a source tree.
export function findAgent(srcRoot, name, explicit) {
  const cands = [];
  if (explicit) cands.push(path.join(srcRoot, explicit));
  if (name) cands.push(path.join(srcRoot, 'agents', name + '.md'), path.join(srcRoot, name + '.md'));
  for (const c of cands) if (fs.existsSync(c) && fs.statSync(c).isFile()) return c;
  const ad = path.join(srcRoot, 'agents');
  if (fs.existsSync(ad)) for (const e of fs.readdirSync(ad, { withFileTypes: true }))
    if (e.isFile() && e.name.endsWith('.md')) return path.join(ad, e.name);
  return null;
}
export function nameFromFrontmatter(file, fallback) {
  const md = fs.readFileSync(file, 'utf8');
  const m = md.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  if (m) { const n = m[1].match(/^name:\s*(.+)$/m); if (n) return n[1].trim(); }
  return fallback;
}
export function copyInto(src, dst, isFile) {
  rmrf(dst);
  if (isFile) { fs.mkdirSync(path.dirname(dst), { recursive: true }); fs.copyFileSync(src, dst); }
  else fs.cpSync(src, dst, { recursive: true, filter: (s) => { const b = path.basename(s); return b !== '.git' && b !== 'node_modules'; } });
}

// Link a single resource into every tool dir for its kind.
export function linkResource(cfg, name, contentPath) {
  for (const td of cfg.toolDirs) {
    fs.mkdirSync(td, { recursive: true });
    relSymlink(contentPath, path.join(td, cfg.entryName(name)));
  }
}
export function unlinkResource(cfg, name) {
  for (const td of cfg.toolDirs) rmrf(path.join(td, cfg.entryName(name)));
}
