#!/usr/bin/env bun
// Commit selected paths and create or update a GitHub pull request.

import fs from "fs";
import os from "os";
import path from "path";
import { fileURLToPath } from "url";
import { spawnSync } from "child_process";

export class SubmitPrError extends Error {
  constructor(message) {
    super(message);
    this.name = "SubmitPrError";
  }
}

export function parseArgs(argv = process.argv.slice(2)) {
  const args = {
    title: null,
    bodyFile: null,
    commitMessage: null,
    paths: [],
    base: null,
    draft: false,
    dryRun: false,
    allowSensitive: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--title") args.title = requireValue(argv, ++i, arg);
    else if (arg === "--body-file") args.bodyFile = requireValue(argv, ++i, arg);
    else if (arg === "--commit-message") args.commitMessage = requireValue(argv, ++i, arg);
    else if (arg === "--path") args.paths.push(requireValue(argv, ++i, arg));
    else if (arg === "--base") args.base = requireValue(argv, ++i, arg);
    else if (arg === "--draft") args.draft = true;
    else if (arg === "--dry-run") args.dryRun = true;
    else if (arg === "--allow-sensitive") args.allowSensitive = true;
    else throw new SubmitPrError(`unknown argument: ${arg}`);
  }

  for (const [key, flag] of [
    ["title", "--title"],
    ["bodyFile", "--body-file"],
    ["commitMessage", "--commit-message"],
  ]) {
    if (!args[key]) throw new SubmitPrError(`missing required argument: ${flag}`);
  }
  if (args.paths.length === 0) throw new SubmitPrError("missing required argument: --path");
  return args;
}

function requireValue(argv, index, flag) {
  const value = argv[index];
  if (!value || value.startsWith("--")) {
    throw new SubmitPrError(`missing value for ${flag}`);
  }
  return value;
}

export function isSensitivePath(inputPath) {
  const normalized = inputPath.replaceAll("\\", "/").toLowerCase();
  const parts = normalized.split("/").filter(Boolean);
  const name = parts.at(-1) || normalized;
  const exactNames = new Set([
    ".env",
    ".env.local",
    ".env.production",
    ".npmrc",
    "credentials.json",
    "service-account.json",
    "private.key",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "kubeconfig",
  ]);
  const sensitiveExtensions = [".pem", ".p12", ".pfx", ".key"];
  const sensitiveTerms = new Set(["secret", "secrets", "credential", "credentials", "token"]);

  return (
    exactNames.has(name) ||
    sensitiveExtensions.some((extension) => name.endsWith(extension)) ||
    parts.some((part) => sensitiveTerms.has(part))
  );
}

export function validatePaths(paths, allowSensitive) {
  if (!paths.length) throw new SubmitPrError("at least one --path is required");

  const broadPaths = new Set(["", ".", "./", "/", "*", "**"]);
  for (const rawPath of paths) {
    const trimmed = rawPath.trim();
    if (trimmed !== rawPath || broadPaths.has(trimmed)) {
      throw new SubmitPrError(`refusing broad or ambiguous path: ${JSON.stringify(rawPath)}`);
    }
    if (path.isAbsolute(trimmed)) {
      throw new SubmitPrError(`--path must be relative to the repository root: ${trimmed}`);
    }
    if (isSensitivePath(trimmed) && !allowSensitive) {
      throw new SubmitPrError(`refusing to stage sensitive-looking path without --allow-sensitive: ${trimmed}`);
    }
  }
}

export function appendUpdate(existingBody, updateBody, timestamp = currentTimestamp()) {
  const existing = existingBody.trimEnd();
  const update = updateBody.trimEnd();
  const entry = `### ${timestamp}\n\n${update}\n`;

  if (existing.includes("## Updates")) return `${existing}\n\n${entry}`;
  if (existing) return `${existing}\n\n## Updates\n\n${entry}`;
  return `## Updates\n\n${entry}`;
}

function currentTimestamp() {
  const date = new Date();
  const offsetMinutes = -date.getTimezoneOffset();
  const sign = offsetMinutes >= 0 ? "+" : "-";
  const absolute = Math.abs(offsetMinutes);
  const hours = String(Math.floor(absolute / 60)).padStart(2, "0");
  const minutes = String(absolute % 60).padStart(2, "0");
  return `${date.toISOString().slice(0, 16).replace("T", " ")} ${sign}${hours}${minutes}`;
}

export function buildCommandPlan(args, branch, hasExistingPr) {
  const plan = [
    ["git", "add", "--", ...args.paths],
    ["git", "diff", "--cached", "--quiet", "--exit-code", "--"],
    ["git", "commit", "-m", args.commitMessage],
    ["git", "push", "-u", "origin", "HEAD"],
  ];

  if (hasExistingPr) {
    plan.push(["gh", "pr", "edit", branch, "--title", args.title, "--body-file", "<merged-body-file>"]);
  } else {
    const command = ["gh", "pr", "create", "--title", args.title, "--body-file", args.bodyFile];
    if (args.base) command.push("--base", args.base);
    if (args.draft) command.push("--draft");
    plan.push(command);
  }
  return plan;
}

function runCommand(command, { check = true, capture = true } = {}) {
  const result = spawnSync(command[0], command.slice(1), {
    encoding: "utf8",
    stdio: capture ? ["ignore", "pipe", "pipe"] : "inherit",
  });

  if (check && result.status !== 0) {
    const detail = (result.stderr || result.stdout || `exit code ${result.status}`).trim();
    throw new SubmitPrError(`command failed: ${command.join(" ")}: ${detail}`);
  }
  return result;
}

function commandOutput(command) {
  const result = runCommand(command);
  return (result.stdout || "").trim();
}

function currentBranch() {
  const branch = commandOutput(["git", "rev-parse", "--abbrev-ref", "HEAD"]);
  if (branch === "HEAD") throw new SubmitPrError("refusing to submit from detached HEAD");
  return branch;
}

function defaultBranch() {
  try {
    const ref = commandOutput(["git", "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"]);
    return ref.startsWith("origin/") ? ref.slice("origin/".length) : ref;
  } catch {
    return "main";
  }
}

function ensureNotDefaultBranch(branch) {
  const protectedBranches = new Set([defaultBranch(), "main", "master"]);
  if (protectedBranches.has(branch)) {
    throw new SubmitPrError(`refusing to commit directly on protected branch: ${branch}`);
  }
}

function readBodyFile(bodyFile) {
  if (!fs.existsSync(bodyFile) || !fs.statSync(bodyFile).isFile()) {
    throw new SubmitPrError(`--body-file does not exist: ${bodyFile}`);
  }
  const body = fs.readFileSync(bodyFile, "utf8").trim();
  if (!body) throw new SubmitPrError("--body-file is empty");
  return body;
}

function currentPr() {
  const result = runCommand(["gh", "pr", "view", "--json", "number,url,body,title"], {
    check: false,
  });
  if (result.status !== 0) return null;
  const text = (result.stdout || "").trim();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new SubmitPrError(`failed to parse gh pr view output: ${error.message}`);
  }
}

function ensureStagedChanges() {
  const result = runCommand(["git", "diff", "--cached", "--quiet", "--exit-code", "--"], {
    check: false,
  });
  if (result.status === 0) {
    throw new SubmitPrError("no staged diff after git add; refusing to create an empty commit");
  }
  if (result.status !== 1) {
    throw new SubmitPrError(`failed to inspect staged diff: ${(result.stderr || result.status).toString().trim()}`);
  }
}

export function execute(args) {
  validatePaths(args.paths, args.allowSensitive);
  const body = readBodyFile(args.bodyFile);
  const branch = currentBranch();
  ensureNotDefaultBranch(branch);
  let pr = currentPr();

  if (args.dryRun) {
    return {
      status: "dry-run",
      branch,
      paths: args.paths,
      existing_pr: pr,
      commands: buildCommandPlan(args, branch, pr !== null),
    };
  }

  runCommand(["git", "add", "--", ...args.paths], { capture: false });
  ensureStagedChanges();
  runCommand(["git", "commit", "-m", args.commitMessage], { capture: false });
  runCommand(["git", "push", "-u", "origin", "HEAD"], { capture: false });

  let action;
  if (pr) {
    const mergedBody = appendUpdate(String(pr.body || ""), body);
    const mergedBodyFile = path.join(os.tmpdir(), `submit-pr-${process.pid}-${Date.now()}.md`);
    fs.writeFileSync(mergedBodyFile, mergedBody, "utf8");
    try {
      runCommand(
        ["gh", "pr", "edit", String(pr.number), "--title", args.title, "--body-file", mergedBodyFile],
        { capture: false },
      );
    } finally {
      fs.rmSync(mergedBodyFile, { force: true });
    }
    action = "updated";
  } else {
    const command = ["gh", "pr", "create", "--title", args.title, "--body-file", args.bodyFile];
    if (args.base) command.push("--base", args.base);
    if (args.draft) command.push("--draft");
    runCommand(command, { capture: false });
    action = "created";
    pr = currentPr();
  }

  return {
    status: action,
    branch,
    paths: args.paths,
    pr,
  };
}

export function main(argv = process.argv.slice(2)) {
  try {
    const args = parseArgs(argv);
    const result = execute(args);
    console.log(JSON.stringify(result, null, 2));
    return 0;
  } catch (error) {
    if (error instanceof SubmitPrError) {
      console.error(JSON.stringify({ status: "error", error: error.message }));
      return 1;
    }
    throw error;
  }
}

const isCli = process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1]);
if (isCli) process.exit(main());
