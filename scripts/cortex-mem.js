#!/usr/bin/env bun
// Local Qdrant-backed memory CLI for agent-cortex. Runtime: bun (ESM).

import crypto from "crypto";
import fs from "fs";
import path from "path";
import { spawn } from "child_process";
import { fileURLToPath } from "url";

import { ROOT } from "./config.js";

export const DEFAULT_QDRANT_URL = "http://127.0.0.1:6333";
export const DEFAULT_COLLECTION = "cortex_mem";
export const VECTOR_SIZE = 384;
export const CORTEX_MEM_DIR = path.join(ROOT, ".cortex-mem");
export const QDRANT_DIR = path.join(CORTEX_MEM_DIR, "qdrant");

const KEYWORD_INDEXES = [
  "scope.repo",
  "scope.project",
  "scope.runtime",
  "kind",
  "tags",
  "files",
];

export class CortexMemError extends Error {
  constructor(message) {
    super(message);
    this.name = "CortexMemError";
  }
}

export function parseArgs(argv = process.argv.slice(2)) {
  const [command, ...rest] = argv;
  const args = {
    command,
    url: process.env.CORTEX_MEM_QDRANT_URL || DEFAULT_QDRANT_URL,
    collection: process.env.CORTEX_MEM_COLLECTION || DEFAULT_COLLECTION,
    grpcPort: process.env.CORTEX_MEM_QDRANT_GRPC_PORT || null,
    limit: 8,
    tags: [],
    files: [],
  };

  if (command === "--help" || command === "-h") {
    args.command = null;
    args.help = true;
    return args;
  }

  for (let i = 0; i < rest.length; i += 1) {
    const arg = rest[i];
    if (arg === "--url") args.url = requireValue(rest, ++i, arg);
    else if (arg === "--collection") args.collection = requireValue(rest, ++i, arg);
    else if (arg === "--grpc-port") args.grpcPort = parsePositiveInt(requireValue(rest, ++i, arg), arg);
    else if (arg === "--query") args.query = requireValue(rest, ++i, arg);
    else if (arg === "--repo") args.repo = requireValue(rest, ++i, arg);
    else if (arg === "--project") args.project = requireValue(rest, ++i, arg);
    else if (arg === "--kind") args.kind = requireValue(rest, ++i, arg);
    else if (arg === "--tag") args.tags.push(requireValue(rest, ++i, arg));
    else if (arg === "--file") args.files.push(requireValue(rest, ++i, arg));
    else if (arg === "--limit") args.limit = parsePositiveInt(requireValue(rest, ++i, arg), arg);
    else if (arg === "--json") args.json = requireValue(rest, ++i, arg);
    else if (arg === "--help" || arg === "-h") args.help = true;
    else throw new CortexMemError(`unknown argument: ${arg}`);
  }

  if (!command || args.help) return args;
  if (!["status", "qdrant-start", "qdrant-stop", "init", "search", "remember"].includes(command)) {
    throw new CortexMemError("commands: status | qdrant-start | qdrant-stop | init | search | remember");
  }
  if (command === "search" && !args.query) throw new CortexMemError("missing required argument: --query");
  if (command === "remember" && !args.json) throw new CortexMemError("missing required argument: --json");
  return args;
}

function requireValue(argv, index, flag) {
  const value = argv[index];
  if (!value || value.startsWith("--")) throw new CortexMemError(`missing value for ${flag}`);
  return value;
}

function parsePositiveInt(value, flag) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isInteger(parsed) || parsed < 1) throw new CortexMemError(`${flag} must be a positive integer`);
  return parsed;
}

export function usage() {
  return `commands:
  scripts/cortex-mem status [--url URL] [--collection NAME]
  scripts/cortex-mem qdrant-start [--url URL] [--grpc-port N]
  scripts/cortex-mem qdrant-stop
  scripts/cortex-mem init [--url URL] [--collection NAME]
  scripts/cortex-mem search --query TEXT [--repo NAME] [--project NAME] [--kind KIND] [--tag TAG] [--file PATH] [--limit N]
  scripts/cortex-mem remember --json FILE [--url URL] [--collection NAME]`;
}

export function tokenize(text) {
  const normalized = String(text || "").toLowerCase();
  const latin = normalized.match(/[a-z0-9][a-z0-9._/-]*/g) || [];
  const cjk = [];
  const chars = Array.from(normalized).filter((char) => /\p{Script=Han}/u.test(char));
  for (let i = 0; i < chars.length; i += 1) {
    cjk.push(chars[i]);
    if (i + 1 < chars.length) cjk.push(chars[i] + chars[i + 1]);
  }
  return [...latin, ...cjk].filter((token) => token.length > 0);
}

export function embedText(text, dimensions = VECTOR_SIZE) {
  const vector = new Array(dimensions).fill(0);
  for (const token of tokenize(text)) {
    const hash = crypto.createHash("sha256").update(token).digest();
    const index = hash.readUInt32BE(0) % dimensions;
    const sign = hash[4] % 2 === 0 ? 1 : -1;
    vector[index] += sign;
  }
  const norm = Math.sqrt(vector.reduce((sum, value) => sum + value * value, 0));
  if (norm === 0) return vector;
  return vector.map((value) => value / norm);
}

export function extractMemory(input) {
  const memory = input?.should_remember === false ? null : input?.memory || input;
  if (!memory) {
    throw new CortexMemError(input?.rejection_reason || "memory candidate rejected");
  }
  if (!memory.summary || typeof memory.summary !== "string") {
    throw new CortexMemError("memory JSON must include string field: summary");
  }
  if (!memory.scope || typeof memory.scope !== "object") {
    throw new CortexMemError("memory JSON must include object field: scope");
  }
  if (!memory.kind || typeof memory.kind !== "string") {
    throw new CortexMemError("memory JSON must include string field: kind");
  }
  if (!Array.isArray(memory.evidence)) {
    throw new CortexMemError("memory JSON must include array field: evidence");
  }
  if (!Array.isArray(memory.tags)) {
    throw new CortexMemError("memory JSON must include array field: tags");
  }
  if (typeof memory.confidence !== "number" || memory.confidence < 0 || memory.confidence > 1) {
    throw new CortexMemError("memory JSON must include confidence between 0 and 1");
  }
  if (containsSensitiveData(memory)) {
    throw new CortexMemError("refusing to persist memory containing sensitive-looking data");
  }
  return memory;
}

export function containsSensitiveData(value) {
  const sensitiveKeys = /(^|[_-])(api[_-]?key|token|secret|secrets|password|passwd|credential|credentials|cookie|private[_-]?key|client[_-]?secret)($|[_-])/i;
  const sensitiveValues = /(-----BEGIN [A-Z ]*PRIVATE KEY-----|xox[baprs]-|gh[pousr]_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]{20,})/;
  const stack = [value];
  while (stack.length) {
    const item = stack.pop();
    if (item == null) continue;
    if (typeof item === "string") {
      if (sensitiveValues.test(item)) return true;
      continue;
    }
    if (Array.isArray(item)) {
      stack.push(...item);
      continue;
    }
    if (typeof item === "object") {
      for (const [key, nested] of Object.entries(item)) {
        if (sensitiveKeys.test(key)) return true;
        stack.push(nested);
      }
    }
  }
  return false;
}

export function memoryText(memory) {
  const evidence = memory.evidence
    .map((item) => `${item.type || ""} ${item.ref || ""} ${item.note || ""}`)
    .join("\n");
  return [
    memory.summary,
    memory.kind,
    ...(memory.tags || []),
    ...(memory.files || []),
    evidence,
  ].join("\n");
}

export function memoryToPoint(memory, now = new Date()) {
  const id = memory.id || crypto.randomUUID();
  const files = Array.isArray(memory.files)
    ? memory.files
    : memory.evidence
      .filter((item) => item.type === "file" && item.ref)
      .map((item) => item.ref);
  const payload = {
    id,
    summary: memory.summary,
    scope: memory.scope,
    kind: memory.kind,
    evidence: memory.evidence,
    tags: memory.tags,
    files,
    confidence: memory.confidence,
    expires_at: memory.expires_at || null,
    created_at: memory.created_at || now.toISOString(),
  };
  return {
    id,
    vector: embedText(memoryText({ ...memory, files })),
    payload,
  };
}

export function buildFilter(args) {
  const must = [];
  if (args.repo) must.push({ key: "scope.repo", match: { value: args.repo } });
  if (args.project) must.push({ key: "scope.project", match: { value: args.project } });
  if (args.kind) must.push({ key: "kind", match: { value: args.kind } });
  for (const tag of args.tags || []) must.push({ key: "tags", match: { value: tag } });
  for (const file of args.files || []) must.push({ key: "files", match: { value: file } });
  return must.length ? { must } : undefined;
}

function qdrantUrl(baseUrl, suffix) {
  return `${String(baseUrl).replace(/\/+$/, "")}${suffix}`;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      "content-type": "application/json",
      ...(options.headers || {}),
    },
  });
  const text = await response.text();
  let body = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  if (!response.ok) {
    throw new CortexMemError(`Qdrant request failed ${response.status}: ${typeof body === "string" ? body : JSON.stringify(body)}`);
  }
  return body;
}

async function collectionExists(args) {
  const response = await fetch(qdrantUrl(args.url, `/collections/${encodeURIComponent(args.collection)}`));
  if (response.status === 404) return false;
  if (!response.ok) throw new CortexMemError(`Qdrant collection check failed ${response.status}`);
  return true;
}

async function createPayloadIndex(args, fieldName) {
  try {
    await requestJson(qdrantUrl(args.url, `/collections/${encodeURIComponent(args.collection)}/index?wait=true`), {
      method: "PUT",
      body: JSON.stringify({ field_name: fieldName, field_schema: "keyword" }),
    });
  } catch (error) {
    // Qdrant returns an error when an index already exists; init should be idempotent.
    if (!String(error.message).toLowerCase().includes("already exists")) throw error;
  }
}

export function qdrantPaths() {
  return {
    runtime_dir: QDRANT_DIR,
    storage_dir: path.join(QDRANT_DIR, "storage"),
    logs_dir: path.join(QDRANT_DIR, "logs"),
    log_file: path.join(QDRANT_DIR, "logs", "qdrant.log"),
    pid_file: path.join(QDRANT_DIR, "qdrant.pid"),
  };
}

function qdrantHttpPort(url) {
  const parsed = new URL(url);
  if (parsed.port) return Number.parseInt(parsed.port, 10);
  return parsed.protocol === "https:" ? 443 : 80;
}

function qdrantGrpcPort(args) {
  return args.grpcPort || qdrantHttpPort(args.url) + 1;
}

function isLocalQdrantUrl(url) {
  const parsed = new URL(url);
  return ["127.0.0.1", "localhost", "::1"].includes(parsed.hostname);
}

function readPid(pidFile) {
  try {
    const raw = fs.readFileSync(pidFile, "utf8").trim();
    const pid = Number.parseInt(raw, 10);
    return Number.isInteger(pid) ? pid : null;
  } catch {
    return null;
  }
}

function processRunning(pid) {
  if (!pid) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

export function qdrantRuntimeState() {
  const paths = qdrantPaths();
  const pid = readPid(paths.pid_file);
  return {
    ...paths,
    pid,
    process_running: processRunning(pid),
  };
}

async function qdrantHealthy(args) {
  try {
    const response = await fetch(qdrantUrl(args.url, "/healthz"));
    return response.ok;
  } catch {
    return false;
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForQdrant(args, timeoutMs = 10000) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    if (await qdrantHealthy(args)) return true;
    await sleep(250);
  }
  return false;
}

export async function ensureQdrant(args) {
  if (await qdrantHealthy(args)) return;
  if (!isLocalQdrantUrl(args.url)) {
    throw new CortexMemError(`Qdrant is unreachable and cannot be auto-started for non-local URL: ${args.url}`);
  }

  await qdrantStart(args);
  if (!(await waitForQdrant(args))) {
    const { log_file } = qdrantPaths();
    throw new CortexMemError(`Qdrant did not become healthy at ${args.url}; see ${log_file}`);
  }
}

async function ensureCollection(args) {
  if (!(await collectionExists(args))) {
    await init(args, { ensure: false });
  }
}

export async function status(args) {
  await ensureQdrant(args);
  await ensureCollection(args);

  const binary = Bun.which("qdrant") || null;
  const runtime = qdrantRuntimeState();
  const health = await qdrantHealthy(args);
  const collection = health ? await collectionExists(args) : false;
  return {
    status: health && collection ? "ok" : "not-ready",
    qdrant_binary: binary,
    qdrant_url: args.url,
    collection: args.collection,
    runtime_dir: runtime.runtime_dir,
    storage_dir: runtime.storage_dir,
    log_file: runtime.log_file,
    pid: runtime.pid,
    process_running: runtime.process_running,
    health,
    collection_exists: collection,
  };
}

export async function qdrantStart(args) {
  const binary = Bun.which("qdrant");
  if (!binary) throw new CortexMemError("qdrant binary not found on PATH");

  const paths = qdrantPaths();
  if (await qdrantHealthy(args)) {
    return {
      status: "running",
      pid: readPid(paths.pid_file),
      qdrant_url: args.url,
      runtime_dir: paths.runtime_dir,
      storage_dir: paths.storage_dir,
      log_file: paths.log_file,
    };
  }

  const existingPid = readPid(paths.pid_file);
  if (processRunning(existingPid)) {
    if (!(await waitForQdrant(args))) {
      throw new CortexMemError(`Qdrant process ${existingPid} is running but not healthy at ${args.url}; see ${paths.log_file}`);
    }
    return {
      status: "running",
      pid: existingPid,
      qdrant_url: args.url,
      runtime_dir: paths.runtime_dir,
      storage_dir: paths.storage_dir,
      log_file: paths.log_file,
    };
  }

  fs.mkdirSync(paths.storage_dir, { recursive: true });
  fs.mkdirSync(paths.logs_dir, { recursive: true });

  const logFd = fs.openSync(paths.log_file, "a");
  const httpPort = qdrantHttpPort(args.url);
  const grpcPort = qdrantGrpcPort(args);
  const child = spawn(binary, ["--disable-telemetry"], {
    cwd: paths.runtime_dir,
    detached: true,
    stdio: ["ignore", logFd, logFd],
    env: {
      ...process.env,
      QDRANT__SERVICE__HTTP_PORT: String(httpPort),
      QDRANT__SERVICE__GRPC_PORT: String(grpcPort),
      QDRANT__STORAGE__STORAGE_PATH: paths.storage_dir,
    },
  });
  child.unref();
  fs.closeSync(logFd);
  fs.writeFileSync(paths.pid_file, `${child.pid}\n`, "utf8");

  if (!(await waitForQdrant(args))) {
    throw new CortexMemError(`Qdrant did not become healthy at ${args.url}; see ${paths.log_file}`);
  }

  return {
    status: "started",
    pid: child.pid,
    qdrant_url: args.url,
    grpc_port: grpcPort,
    runtime_dir: paths.runtime_dir,
    storage_dir: paths.storage_dir,
    log_file: paths.log_file,
  };
}

export async function qdrantStop() {
  const paths = qdrantPaths();
  const pid = readPid(paths.pid_file);
  if (!processRunning(pid)) {
    fs.rmSync(paths.pid_file, { force: true });
    return {
      status: "not-running",
      pid,
      runtime_dir: paths.runtime_dir,
    };
  }

  process.kill(pid, "SIGTERM");
  fs.rmSync(paths.pid_file, { force: true });
  return {
    status: "stopping",
    pid,
    runtime_dir: paths.runtime_dir,
  };
}

export async function init(args, options = {}) {
  if (options.ensure !== false) await ensureQdrant(args);

  let created = false;
  if (!(await collectionExists(args))) {
    await requestJson(qdrantUrl(args.url, `/collections/${encodeURIComponent(args.collection)}?wait=true`), {
      method: "PUT",
      body: JSON.stringify({
        vectors: {
          size: VECTOR_SIZE,
          distance: "Cosine",
        },
      }),
    });
    created = true;
  }
  for (const fieldName of KEYWORD_INDEXES) {
    await createPayloadIndex(args, fieldName);
  }
  return {
    status: "ok",
    qdrant_url: args.url,
    collection: args.collection,
    vector_size: VECTOR_SIZE,
    created,
    indexes: KEYWORD_INDEXES,
  };
}

export async function search(args) {
  await ensureQdrant(args);
  await ensureCollection(args);

  const body = {
    vector: embedText(args.query),
    limit: args.limit,
    with_payload: true,
    with_vector: false,
  };
  const filter = buildFilter(args);
  if (filter) body.filter = filter;
  const result = await requestJson(qdrantUrl(args.url, `/collections/${encodeURIComponent(args.collection)}/points/search`), {
    method: "POST",
    body: JSON.stringify(body),
  });
  return {
    status: "ok",
    query: args.query,
    collection: args.collection,
    matches: (result?.result || []).map((point) => ({
      id: point.id,
      score: point.score,
      ...point.payload,
    })),
  };
}

export async function remember(args) {
  await ensureQdrant(args);
  await ensureCollection(args);

  const input = JSON.parse(fs.readFileSync(args.json, "utf8"));
  const memory = extractMemory(input);
  const point = memoryToPoint(memory);
  await requestJson(qdrantUrl(args.url, `/collections/${encodeURIComponent(args.collection)}/points?wait=true`), {
    method: "PUT",
    body: JSON.stringify({ points: [point] }),
  });
  appendAuditRecord(point.payload, memory, args);
  return {
    status: "ok",
    id: point.id,
    collection: args.collection,
    qdrant_url: args.url,
  };
}

function appendAuditRecord(payload, memory, args) {
  fs.mkdirSync(CORTEX_MEM_DIR, { recursive: true });
  const record = {
    payload,
    memory,
    qdrant_url: args.url,
    collection: args.collection,
  };
  fs.appendFileSync(path.join(CORTEX_MEM_DIR, "memories.jsonl"), `${JSON.stringify(record)}\n`, "utf8");
}

export async function execute(args) {
  if (!args.command || args.help) return usage();
  if (args.command === "status") return status(args);
  if (args.command === "qdrant-start") return qdrantStart(args);
  if (args.command === "qdrant-stop") return qdrantStop();
  if (args.command === "init") return init(args);
  if (args.command === "search") return search(args);
  if (args.command === "remember") return remember(args);
  throw new CortexMemError("commands: status | qdrant-start | qdrant-stop | init | search | remember");
}

export async function main(argv = process.argv.slice(2)) {
  try {
    const args = parseArgs(argv);
    const result = await execute(args);
    if (typeof result === "string") console.log(result);
    else console.log(JSON.stringify(result, null, 2));
    return 0;
  } catch (error) {
    if (error instanceof CortexMemError || error instanceof SyntaxError) {
      console.error(JSON.stringify({ status: "error", error: error.message }));
      return 1;
    }
    throw error;
  }
}

const isCli = process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1]);
if (isCli) process.exit(await main());
