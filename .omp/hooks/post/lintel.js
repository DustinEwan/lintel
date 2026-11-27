const WATCHED_TOOLS = new Set(["edit", "write"]);

function describe(result, event) {
  const findings = Array.isArray(result.findings) ? result.findings : [];
  const commands = Array.isArray(result.commands) ? result.commands : [];
  const lines = findings.map((finding) => {
    const rule = finding.rule ?? finding.id ?? "finding";
    const location = finding.location ?? finding.path ?? "";
    const message = finding.message ?? finding.fix ?? "";
    return `- ${rule}${location ? ` at ${location}` : ""}: ${message}`;
  });

  return [
    `lintel ${event}: ${findings.length} finding(s).`,
    ...lines,
    result.context ?? "",
    commands.length ? "Commands:" : "",
    ...commands.map((command) => `  ${command}`),
  ]
    .filter(Boolean)
    .join("\n");
}

export default function lintelHooks(pi) {

  async function runHook(name, cwd) {
    const result = await pi.exec("lintel", ["hook", name], { cwd });
    let payload;
    try {
      payload = JSON.parse(result.stdout);
    } catch {
      payload = null;
    }
    const valid = payload && typeof payload === "object" && !Array.isArray(payload);
    if (result.killed || Number(result.code) > 1 || !valid) {
      return { block: true, context: result.stderr || `lintel hook ${name} failed`, findings: [] };
    }
    return payload;
  }

  pi.on("tool_result", async (event, ctx) => {
    if (event.isError || !WATCHED_TOOLS.has(event.toolName)) return;

    const result = await runHook("post-edit", ctx.cwd ?? pi.cwd);
    const findings = Array.isArray(result.findings) ? result.findings : [];
    ctx.ui?.setStatus?.("lintel", findings.length ? `lintel: ${findings.length} finding(s)` : "lintel: clean");

    if (!result.block && findings.length === 0) return;

    const text = describe(result, "post-edit");
    ctx.ui?.notify?.(`lintel post-edit: ${findings.length} finding(s)`, "warning");
    return { additionalContext: text };
  });

  pi.on("agent_end", async (event, ctx) => {
    if (event.willContinue || event.awaitingAsyncWork) return;

    const result = await runHook("stop", ctx.cwd ?? pi.cwd);
    const findings = Array.isArray(result.findings) ? result.findings : [];
    if (!result.block && findings.length === 0) return;

    ctx.ui?.notify?.(`lintel stop: ${findings.length} finding(s)`, "warning");
    pi.logger?.warn?.(describe(result, "stop"));
  });
}
