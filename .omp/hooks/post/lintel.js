const WATCHED_TOOLS = new Set(["edit", "write"]);

function describe(result, event) {
  const findings = Array.isArray(result.findings) ? result.findings : [];
  const commands = Array.isArray(result.commands) ? result.commands : [];
  const lines = findings.map((finding) => {
    const rule = finding.rule ?? finding.id ?? "finding";
    const location = finding.location ?? finding.path ?? "";
    const message = finding.message ?? finding.fix ?? "";
    const fingerprint = finding.fingerprint ? ` [${finding.fingerprint}]` : "";
    return `- ${rule}${fingerprint}${location ? ` at ${location}` : ""}: ${message}`;
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

function semanticReviews(result) {
  return (Array.isArray(result.findings) ? result.findings : []).filter(
    (finding) => finding.rule === "semantic_review"
  );
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

    const cwd = ctx.cwd ?? pi.cwd;
    const result = await runHook("post-edit", cwd);
    const findings = Array.isArray(result.findings) ? result.findings : [];
    ctx.ui?.setStatus?.("lintel", findings.length ? `lintel: ${findings.length} finding(s)` : "lintel: clean");

    if (!result.block && findings.length === 0) return;

    const parts = [describe(result, "post-edit")];
    if (semanticReviews(result).length) {
      parts.push(describe(await runHook("review-request", cwd), "review-request"));
    }
    ctx.ui?.notify?.(`lintel post-edit: ${findings.length} finding(s)`, "warning");
    return { additionalContext: parts.join("\n\n") };
  });

  pi.on("agent_end", async (event, ctx) => {
    if (event.willContinue || event.awaitingAsyncWork) return;

    const cwd = ctx.cwd ?? pi.cwd;
    const result = await runHook("stop", cwd);
    const findings = Array.isArray(result.findings) ? result.findings : [];
    if (!result.block && findings.length === 0) return;

    const parts = [describe(result, "stop")];
    if (semanticReviews(result).length) {
      parts.push(describe(await runHook("review-request", cwd), "review-request"));
    }
    ctx.ui?.notify?.(`lintel stop: ${findings.length} finding(s)`, "warning");
    pi.logger?.warn?.(parts.join("\n\n"));
  });
}
