#!/usr/bin/env bun
// cli.js — cortex CLI entrypoint. Runtime: bun (ESM).
//
//   cortex install                                   bootstrap: relink + restore externals
//   cortex install <skill|agent> <github|git|npm> <source> [name] [--ref r] [--path p]
//   cortex uninstall <name>                          remove an external resource
//   cortex relink                                    rebuild all tool symlinks
//   cortex verify [name]                             check on-disk hashes vs lock
//   cortex list                                      list builtin + external

import { die } from './resource.js';
import { cmdInstall, cmdUninstall, cmdRelink, cmdVerify, cmdList } from './commands.js';

function parse(args) {
  const o = { _: [] };
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a === '--ref') o.ref = args[++i];
    else if (a === '--path') o.path = args[++i];
    else o._.push(a);
  }
  return o;
}

function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  const argv = parse(rest);
  switch (cmd) {
    case 'install': return cmdInstall(argv);
    case 'uninstall': return cmdUninstall(argv);
    case 'relink': return cmdRelink();
    case 'verify': return cmdVerify(argv);
    case 'list': return cmdList();
    default: die('commands: install | uninstall | relink | verify | list');
  }
}
main();
