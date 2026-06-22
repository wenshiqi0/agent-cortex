// fetch.js — fetch a source tree into a temp dir. Uses git / npm / tar from PATH.

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
  const t = mkdtmp();
  const tgz = sh('npm', ['pack', pkg, '--silent', '--pack-destination', t]).trim().split('\n').pop();
  sh('tar', ['-xzf', path.join(t, tgz), '-C', t]);
  return path.join(t, 'package');
}
