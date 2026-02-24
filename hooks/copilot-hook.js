#!/usr/bin/env node
/**
 * Copilot Chat Logger — Hook Handler
 *
 * This script is invoked by VS Code Copilot Chat
 * as a shell-command hook. It receives JSON on stdin describing the hook
 * event and POSTs it to the dashboard ingestion API.
 *
 * Exit codes:
 *   0 = allow / continue (never blocks)
 *   Non-zero would block the action — we always exit 0.
 */

const http = require("http");

const DASHBOARD_URL =
  process.env.COPILOT_LOGGER_URL || "http://localhost:8081/api/logs";

function readStdin() {
  return new Promise((resolve) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => (data += chunk));
    process.stdin.on("end", () => resolve(data));
    // If stdin is already closed / empty, resolve after a short timeout
    setTimeout(() => resolve(data), 500);
  });
}

function post(url, body) {
  return new Promise((resolve) => {
    const parsed = new URL(url);
    const options = {
      hostname: parsed.hostname,
      port: parsed.port || 80,
      path: parsed.pathname,
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(body),
      },
      timeout: 3000,
    };

    const req = http.request(options, (res) => {
      res.resume(); // drain
      resolve();
    });

    req.on("error", () => resolve()); // never fail
    req.on("timeout", () => {
      req.destroy();
      resolve();
    });
    req.write(body);
    req.end();
  });
}

/**
 * Map the hook event name + input JSON into the dashboard API format.
 */
function mapEvent(hookName, input) {
  const sessionId = input.sessionId || input.session_id || "unknown";
  const developer = process.env.USER || process.env.USERNAME || "unknown";

  switch (hookName) {
    case "SessionStart":
      return {
        type: "session_start",
        session_id: sessionId,
        payload: {
          developer,
          model: input.model || null,
          cwd: input.cwd || process.cwd(),
          source: input.source || "vscode-hook",
        },
      };

    case "UserPromptSubmit":
      return {
        type: "prompt",
        session_id: sessionId,
        payload: {
          prompt_text: input.prompt || "",
          response_text: null,
          duration_ms: null,
        },
      };

    case "PreToolUse":
      return {
        type: "tool",
        session_id: sessionId,
        payload: {
          phase: "pre",
          tool_name: input.tool_name || "unknown",
          tool_args: input.tool_input || null,
          tool_result: null,
          permission: null,
        },
      };

    case "PostToolUse":
      return {
        type: "tool",
        session_id: sessionId,
        payload: {
          phase: "post",
          tool_name: input.tool_name || "unknown",
          tool_args: input.tool_input || null,
          tool_result:
            typeof input.tool_response === "string"
              ? { output: input.tool_response }
              : input.tool_response || null,
          permission: null,
        },
      };

    case "PostToolUseFailure":
      return {
        type: "error",
        session_id: sessionId,
        payload: {
          error_message: input.error || "Tool execution failed",
          error_context: `tool:${input.tool_name || "unknown"}`,
          recoverable: !input.is_interrupt,
        },
      };

    case "Stop":
      return {
        type: "session_end",
        session_id: sessionId,
        payload: {
          end_reason: input.stop_hook_active ? "stop_hook" : "complete",
          final_message: null,
        },
      };

    case "SessionEnd":
      return {
        type: "session_end",
        session_id: sessionId,
        payload: {
          end_reason: input.reason || "unknown",
          final_message: null,
        },
      };

    case "Notification":
      // Log notifications as prompts (informational)
      return {
        type: "prompt",
        session_id: sessionId,
        payload: {
          prompt_text: `[Notification] ${input.title || ""}: ${input.message || ""}`,
          response_text: null,
          duration_ms: null,
        },
      };

    default:
      return null;
  }
}

async function main() {
  // The hook event name is passed via the COPILOT_HOOK_NAME env variable
  // or can be inferred from the input JSON. In the Copilot Chat hook system,
  // the hook type is determined by how the hook is registered (in settings).
  // We pass it as the first CLI argument from the hook command.
  const hookName = process.argv[2] || process.env.COPILOT_HOOK_NAME;
  if (!hookName) {
    process.exit(0);
  }

  const raw = await readStdin();
  if (!raw.trim()) {
    process.exit(0);
  }

  let input;
  try {
    input = JSON.parse(raw);
  } catch {
    process.exit(0);
  }

  const event = mapEvent(hookName, input);
  if (event) {
    await post(DASHBOARD_URL, JSON.stringify(event));
  }

  // Always allow — never block the agent
  process.exit(0);
}

main().catch(() => process.exit(0));
