// fetch.js — fetch a source tree into a temp dir. Uses git + bun from PATH.

import fs from 'fs';
import path from 'path';
import { sh, mkdtmp } from './resource.js';

export function fetchGithub(repo, ref) {
  const t = mkdtmp();
  const a = ['clone', '--depth', '1'];
  if (ref) a.push('--branch', ref);
  a.push(`https://github.com/${repo}.git`, t);
  sh('git', a);
  return t;
}
export function fetchGit(url, ref) {
  const t = mkdtmp();
  const a = ['clone', '--depth', '1'];
  if (ref) a.push('--branch', ref);
  a.push(url, t);
  sh('git', a);
  return t;
}
export function fetchNpm(pkg) {
  // Install the package into a throwaway dir via bun, then read it from node_modules.
  const t = mkdtmp();
  fs.writeFileSync(path.join(t, 'package.json'), '{"name":"_cortex_tmp","private":true}\n');
  sh('bun', ['add', pkg, '--no-save'], { cwd: t });
  // bun add of "<name>" or "<scope>/<name>@version" installs under node_modules/<name>.
  const bare = pkg.replace(/@[^/]+$/, '');               // strip trailing @version
  return path.join(t, 'node_modules', bare);
}
