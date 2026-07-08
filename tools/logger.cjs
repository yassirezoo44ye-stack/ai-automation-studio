/**
 * Structured logger — writes to logs/{runtime,install,build,errors}.log
 * Each entry is one JSON line: { ts, level, category, message, data? }
 * Safe to import in any Node context; creates log dir on first write.
 */
"use strict";

const fs   = require("fs");
const path = require("path");

const LOG_DIR = path.resolve(__dirname, "..", "logs");

const FILES = {
  runtime : path.join(LOG_DIR, "runtime.log"),
  install : path.join(LOG_DIR, "install.log"),
  build   : path.join(LOG_DIR, "build.log"),
  errors  : path.join(LOG_DIR, "errors.log"),
};

let _dirReady = false;

function ensureDir() {
  if (_dirReady) return;
  try { fs.mkdirSync(LOG_DIR, { recursive: true }); } catch (_) { /* read-only fs */ }
  _dirReady = true;
}

function write(file, level, message, data) {
  ensureDir();
  const entry = JSON.stringify({
    ts      : new Date().toISOString(),
    level,
    message,
    ...(data !== undefined ? { data } : {}),
  });
  try {
    fs.appendFileSync(file, entry + "\n", "utf8");
  } catch (_) { /* log writes must never crash the process */ }
}

function makeCategory(file) {
  return {
    info : (msg, data) => write(file, "INFO",  msg, data),
    warn : (msg, data) => write(file, "WARN",  msg, data),
    error: (msg, data) => {
      write(file, "ERROR", msg, data);
      write(FILES.errors, "ERROR", msg, { source: path.basename(file), ...data });
    },
  };
}

/** Write a full error record: root cause + repair attempted + result + next action */
function errorRecord({ message, rootCause, repairAttempted = null, repairResult = null, nextAction = null }) {
  const data = { rootCause, repairAttempted, repairResult, nextAction };
  write(FILES.errors, "ERROR", message, data);
}

module.exports = {
  runtime : makeCategory(FILES.runtime),
  install : makeCategory(FILES.install),
  build   : makeCategory(FILES.build),
  errors  : makeCategory(FILES.errors),
  errorRecord,
  LOG_DIR,
  FILES,
};
