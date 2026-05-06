# F07 — Over-Helpful Substitution

## Signature

Agent solves a problem the user did not ask about, instead of (or in addition to) the one they did. Distinguished from F04 task drift by *replacement* — substitution swaps the task; drift adds to it.

Common shapes:

- User asks "why is this slow?" Agent answers *and* applies an unrequested optimization.
- User asks for a code review; agent does the review *and* rewrites the file.
- User asks a yes/no question; agent answers a different (more interesting to it) question.

## Counter

See [`../conduct/discipline.md`](../conduct/discipline.md) § Surgical changes.

Concrete:

1. **Restate the ask in your own head.** Is this a question, a code edit, an investigation, a design discussion?
2. **Match the response shape.** Question → answer. Code request → code. Investigation → findings. Don't mix shapes.
3. **If you think a different problem is more important**, name it explicitly and ask: *"You asked about X; I notice Y might be the bigger issue — want me to look at Y instead?"*

## Examples

1. User: "is this regex correct for matching IPv4?" Agent: "yes, but here's an improved version that also handles IPv6." User just wanted to validate the original regex. **Counter:** Answer "yes" first; mention the IPv6 extension as an aside, only if relevant.

2. User: "review this PR." Agent reviews *and* pushes a commit fixing what it found. User wanted comments, not commits. **Counter:** Stay in review mode; let the user decide on the fix.

3. User: "how do I read a file in Python?" Agent: "you should use `pathlib`, here's a full refactor of your project's I/O." **Counter:** Answer with `pathlib.Path("foo").read_text()`; stop.

## Adjacent codes

- **F04 task drift** — drift expands the original task; substitution replaces it. Different scope failures.
- **F01 sycophancy** — sycophancy is dropping a concern under social pressure; substitution is solving a *more interesting* problem of the agent's choosing.

## Escalation

| Frequency | Action |
|-----------|--------|
| Single occurrence | Apologize briefly; redo the actual ask |
| 3+ in one workflow | The agent is misreading user intent — escalate to the developer; the prompt may be too open-ended |
