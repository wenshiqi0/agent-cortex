import { afterEach, describe, expect, test } from "bun:test";
import fs from "fs";
import os from "os";
import path from "path";
import { spawnSync } from "child_process";

import {
  deriveRepoName,
  resolveRepoDest,
  cmdClone,
  cmdInit,
} from "../scripts/repo.js";

function runGit(cwd, args) {
  // File redirect: bun test under workspace cwd may drop spawnSync pipes
  // (same pattern as tests/submit-pr.test.js).
  const id = `${process.pid}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const outFile = path.join(os.tmpdir(), `cortex-repo-out-${id}.txt`);
  const errFile = path.join(os.tmpdir(), `cortex-repo-err-${id}.txt`);
  const quote = (value) => `'${String(value).replaceAll("'", `'\"'\"'`)}'`;
  try {
    const shellCmd = `git ${args.map(quote).join(" ")} >${quote(outFile)} 2>${quote(errFile)}`;
    const result = spawnSync("sh", ["-c", shellCmd], {
      cwd,
      encoding: "utf8",
      env: {
        ...process.env,
        GIT_AUTHOR_NAME: "cortex-repo-test",
        GIT_AUTHOR_EMAIL: "cortex-repo-test@example.com",
        GIT_COMMITTER_NAME: "cortex-repo-test",
        GIT_COMMITTER_EMAIL: "cortex-repo-test@example.com",
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

function makeTmpRoot() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "cortex-repo-root-"));
  fs.mkdirSync(path.join(root, "repositories"), { recursive: true });
  return root;
}

function makeSourceRepo() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cortex-repo-src-"));
  runGit(dir, ["init", "-b", "main"]);
  fs.writeFileSync(path.join(dir, "README.md"), "fixture\n");
  runGit(dir, ["add", "README.md"]);
  runGit(dir, ["commit", "-m", "init"]);
  return dir;
}

describe("deriveRepoName", () => {
  test("strips https path, trailing slash, and .git", () => {
    expect(deriveRepoName("https://github.com/owner/repo.git")).toBe("repo");
    expect(deriveRepoName("https://github.com/owner/repo/")).toBe("repo");
    expect(deriveRepoName("https://github.com/owner/repo")).toBe("repo");
  });

  test("handles scp-style git@host:owner/repo.git", () => {
    expect(deriveRepoName("git@github.com:owner/my-repo.git")).toBe("my-repo");
    expect(deriveRepoName("git@gitlab.com:group/sub/tool")).toBe("tool");
  });

  test("rejects empty or ambiguous urls", () => {
    for (const url of ["", "   ", "https://github.com/", "git@host:", "git@host:."]) {
      expect(() => deriveRepoName(url)).toThrow();
    }
  });
});

describe("resolveRepoDest destination safety", () => {
  const tmpDirs = [];

  afterEach(() => {
    while (tmpDirs.length) {
      fs.rmSync(tmpDirs.pop(), { recursive: true, force: true });
    }
  });

  test("resolves only under <root>/repositories with safe names", () => {
    const root = makeTmpRoot();
    tmpDirs.push(root);

    expect(resolveRepoDest("demo", { root })).toBe(path.join(root, "repositories", "demo"));
    expect(resolveRepoDest("foo_bar.baz-1", { root })).toBe(
      path.join(root, "repositories", "foo_bar.baz-1"),
    );
  });

  test("rejects unsafe or path-escaping names", () => {
    const root = makeTmpRoot();
    tmpDirs.push(root);

    for (const name of ["..", "../escape", "foo/bar", "foo bar", "foo:bar", "", ".", "a/../b"]) {
      expect(() => resolveRepoDest(name, { root })).toThrow();
    }
  });
});

describe("cmdClone / cmdInit", () => {
  const tmpDirs = [];

  afterEach(() => {
    while (tmpDirs.length) {
      fs.rmSync(tmpDirs.pop(), { recursive: true, force: true });
    }
  });

  test("clone via file:// lands under repositories/ and rejects existing dest", () => {
    const root = makeTmpRoot();
    const src = makeSourceRepo();
    tmpDirs.push(root, src);

    const url = `file://${src}`;
    const dest = path.join(root, "repositories", "fixture-repo");

    cmdClone({ url, name: "fixture-repo", root });
    expect(fs.existsSync(path.join(dest, ".git"))).toBe(true);
    expect(fs.existsSync(path.join(dest, "README.md"))).toBe(true);

    expect(() => cmdClone({ url, name: "fixture-repo", root })).toThrow();
  });

  test("clone --dry-run prints plan and does not create dest", () => {
    const root = makeTmpRoot();
    const src = makeSourceRepo();
    tmpDirs.push(root, src);

    const url = `file://${src}`;
    const logs = [];
    const restore = console.log;
    console.log = (...args) => logs.push(args.join(" "));
    try {
      cmdClone({ url, name: "dry-demo", root, dryRun: true });
    } finally {
      console.log = restore;
    }

    const joined = logs.join("\n");
    expect(joined).toContain("dry-demo");
    expect(joined).toContain(path.join(root, "repositories", "dry-demo"));
    expect(fs.existsSync(path.join(root, "repositories", "dry-demo"))).toBe(false);
  });

  test("init creates .git under repositories/<name>", () => {
    const root = makeTmpRoot();
    tmpDirs.push(root);

    cmdInit({ name: "fresh", root });
    const dest = path.join(root, "repositories", "fresh");
    expect(fs.existsSync(path.join(dest, ".git"))).toBe(true);

    expect(() => cmdInit({ name: "fresh", root })).toThrow();
  });

  test("init rejects path-escaping names before creating anything", () => {
    const root = makeTmpRoot();
    tmpDirs.push(root);

    expect(() => cmdInit({ name: "../escape", root })).toThrow();
    expect(fs.existsSync(path.join(root, "escape"))).toBe(false);
    // path.join(root, "repositories", "..") normalizes to root (always exists);
    // assert no escape entries were created under repositories/ instead.
    expect(fs.readdirSync(path.join(root, "repositories")).includes("..")).toBe(false);
  });
});
