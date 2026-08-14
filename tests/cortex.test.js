import { afterEach, describe, expect, test } from "bun:test";
import fs from "fs";
import os from "os";
import path from "path";
import { spawnSync } from "child_process";

import { cmdInstall, cmdRefresh } from "../scripts/commands.js";

const CLI = path.resolve(import.meta.dir, "../scripts/cli.js");

function runGit(cwd, args) {
  // File redirect: bun test under workspace cwd may drop spawnSync pipes
  // (same pattern as tests/cortex-repo.test.js).
  const id = `${process.pid}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const outFile = path.join(os.tmpdir(), `cortex-cli-git-out-${id}.txt`);
  const errFile = path.join(os.tmpdir(), `cortex-cli-git-err-${id}.txt`);
  const quote = (value) => `'${String(value).replaceAll("'", `'\"'\"'`)}'`;
  try {
    const shellCmd = `git ${args.map(quote).join(" ")} >${quote(outFile)} 2>${quote(errFile)}`;
    const result = spawnSync("sh", ["-c", shellCmd], {
      cwd,
      encoding: "utf8",
      env: {
        ...process.env,
        GIT_AUTHOR_NAME: "cortex-cli-test",
        GIT_AUTHOR_EMAIL: "cortex-cli-test@example.com",
        GIT_COMMITTER_NAME: "cortex-cli-test",
        GIT_COMMITTER_EMAIL: "cortex-cli-test@example.com",
      },
    });
    const stdout = fs.existsSync(outFile) ? fs.readFileSync(outFile, "utf8") : "";
    const stderr = fs.existsSync(errFile) ? fs.readFileSync(errFile, "utf8") : "";
    if (result.status !== 0) {
      const detail = (stderr || stdout || `exit ${result.status}`).trim();
      throw new Error(`git ${args.join(" ")} failed: ${detail}`);
    }
    return stdout.trimEnd();
  } finally {
    fs.rmSync(outFile, { force: true });
    fs.rmSync(errFile, { force: true });
  }
}

function runCortexCli(args) {
  const id = `${process.pid}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const outFile = path.join(os.tmpdir(), `cortex-cli-out-${id}.txt`);
  const errFile = path.join(os.tmpdir(), `cortex-cli-err-${id}.txt`);
  const quote = (value) => `'${String(value).replaceAll("'", `'\"'\"'`)}'`;
  try {
    const shellCmd = `bun ${quote(CLI)} ${args.map(quote).join(" ")} >${quote(outFile)} 2>${quote(errFile)}`;
    const result = spawnSync("sh", ["-c", shellCmd], {
      cwd: path.resolve(import.meta.dir, ".."),
      encoding: "utf8",
    });
    const stdout = fs.existsSync(outFile) ? fs.readFileSync(outFile, "utf8") : "";
    const stderr = fs.existsSync(errFile) ? fs.readFileSync(errFile, "utf8") : "";
    return { status: result.status ?? 1, stdout, stderr };
  } finally {
    fs.rmSync(outFile, { force: true });
    fs.rmSync(errFile, { force: true });
  }
}

/** Minimal cortex layout so install/refresh can resolve KIND paths under `root`. */
function makeCortexRoot() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "cortex-cli-root-"));
  for (const dir of [
    "knowledge/skills",
    "knowledge/agents",
    "skills",
    "agents",
    ".claude/skills",
    ".agents/skills",
    ".claude/agents",
    ".cursor/agents",
    ".opencode/agent",
  ]) {
    fs.mkdirSync(path.join(root, dir), { recursive: true });
  }
  return root;
}

/** Local git repo containing one skill folder (no network). */
function makeSkillSourceRepo(skillName, body) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cortex-cli-src-"));
  const skillDir = path.join(dir, "skills", skillName);
  fs.mkdirSync(skillDir, { recursive: true });
  fs.writeFileSync(
    path.join(skillDir, "SKILL.md"),
    `---\nname: ${skillName}\ndescription: fixture skill for cortex refresh tests\n---\n\n${body}\n`,
  );
  runGit(dir, ["init", "-b", "main"]);
  runGit(dir, ["add", "."]);
  runGit(dir, ["commit", "-m", "init skill"]);
  return dir;
}

function readSkillLock(root) {
  const lockPath = path.join(root, "skills", "skills-lock.json");
  if (!fs.existsSync(lockPath)) return { version: 1, items: {} };
  return JSON.parse(fs.readFileSync(lockPath, "utf8"));
}

function captureLogs(fn) {
  const logs = [];
  const restore = console.log;
  console.log = (...args) => logs.push(args.join(" "));
  try {
    fn();
  } finally {
    console.log = restore;
  }
  return logs;
}

describe("cortex refresh", () => {
  const tmpDirs = [];

  afterEach(() => {
    while (tmpDirs.length) {
      fs.rmSync(tmpDirs.pop(), { recursive: true, force: true });
    }
  });

  test("refresh re-fetches git skill, updates lock hash, and overwrites external copy", () => {
    const root = makeCortexRoot();
    const src = makeSkillSourceRepo("refresh-demo", "version-one");
    tmpDirs.push(root, src);

    const source = `file://${src}`;
    cmdInstall({ _: ["skill", "git", source, "refresh-demo"], root });

    const lockBefore = readSkillLock(root);
    const hashBefore = lockBefore.items["refresh-demo"]?.computedHash;
    expect(hashBefore).toBeTruthy();
    expect(fs.readFileSync(path.join(root, "skills", "refresh-demo", "SKILL.md"), "utf8")).toContain(
      "version-one",
    );

    fs.writeFileSync(
      path.join(src, "skills", "refresh-demo", "SKILL.md"),
      `---\nname: refresh-demo\ndescription: fixture skill for cortex refresh tests\n---\n\nversion-two\n`,
    );
    runGit(src, ["add", "."]);
    runGit(src, ["commit", "-m", "bump skill body"]);

    cmdRefresh({ _: ["refresh-demo"], root });

    const lockAfter = readSkillLock(root);
    const hashAfter = lockAfter.items["refresh-demo"]?.computedHash;
    expect(hashAfter).toBeTruthy();
    expect(hashAfter).not.toBe(hashBefore);
    expect(fs.readFileSync(path.join(root, "skills", "refresh-demo", "SKILL.md"), "utf8")).toContain(
      "version-two",
    );
    expect(lockAfter.items["refresh-demo"].sourceType).toBe("git");
    expect(lockAfter.items["refresh-demo"].source).toBe(source);
  });

  test("refresh of a name absent from both locks exits 1", () => {
    const result = runCortexCli(["refresh", "no-such-external-zzzz"]);
    const combined = `${result.stdout}\n${result.stderr}`;
    expect(result.status).toBe(1);
    // Must be the refresh missing-entry path, not the unknown-command usage dump.
    expect(combined).not.toMatch(/commands:\s*install/i);
    expect(combined).toMatch(/not found|no .*lock|absent|missing/i);
  });

  test("refresh --dry-run prints fetch plan and changes nothing on disk", () => {
    const root = makeCortexRoot();
    const src = makeSkillSourceRepo("dry-demo", "dry-body");
    tmpDirs.push(root, src);

    const source = `file://${src}`;
    cmdInstall({ _: ["skill", "git", source, "dry-demo"], root });

    const lockBefore = readSkillLock(root);
    const hashBefore = lockBefore.items["dry-demo"].computedHash;
    const skillPath = path.join(root, "skills", "dry-demo", "SKILL.md");
    const bodyBefore = fs.readFileSync(skillPath, "utf8");
    const entry = lockBefore.items["dry-demo"];
    const dest = path.join(root, "skills", "dry-demo");

    const logs = captureLogs(() => {
      cmdRefresh({ _: ["dry-demo"], dryRun: true, root });
    });
    const joined = logs.join("\n");

    expect(joined).toMatch(/skill/i);
    expect(joined).toContain(source);
    expect(joined).toContain(entry.resourcePath);
    // dest may be absolute or root-relative; require the external skill path segment
    expect(joined.includes(dest) || joined.includes(path.join("skills", "dry-demo"))).toBe(true);
    if (entry.ref) expect(joined).toContain(entry.ref);

    expect(readSkillLock(root).items["dry-demo"].computedHash).toBe(hashBefore);
    expect(fs.readFileSync(skillPath, "utf8")).toBe(bodyBefore);
  });
});
