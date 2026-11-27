# Lintel harness setup

Lintel exposes one harness-neutral command:

```sh
lintel hook <session-start|post-edit|stop|review-request>
```

`--root` defaults to the current directory; set it only when running outside
the governed project.

It prints JSON with `block`, `context`, `findings`, and `commands`. Treat
`block: true` as a failed in-loop check and surface the findings to the user.

Claude Code: add a `PostToolUse` hook with matcher `Edit|Write` whose command is
`lintel hook post-edit`. Add a `Stop` hook with `lintel hook stop`.

OpenCode: reference `AGENTS.md` as a project instruction file and call the same
hook command from an extension event handler.

Pi: call `lintel hook session-start` on `session_start` and
`lintel hook stop` on `session_shutdown`.

OMP: this repo ships [`.omp/hooks/post/lintel.js`](.omp/hooks/post/lintel.js). Native discovery loads it from `.omp/hooks/post/*.js` after restarting `omp`. It runs `lintel hook post-edit` after `edit`/`write` and `lintel hook stop` when an agent turn settles, surfacing findings in tool context and the status line.

Generic harnesses: run the hook command after edits and before completion; treat
a nonzero exit or `block: true` as a failed check.
