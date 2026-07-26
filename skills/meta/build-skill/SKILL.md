---
name: build-skill
description: Author or adapt a pasted AgentSkills folder for cursor-agent — frontmatter, reserved names, size cap, and verify with skills list.
---

# Build skill

## When to use

Use when the operator is writing a new AgentSkill or adapting a third-party `SKILL.md` so cursor-agent can discover and invoke it (BYO paste; no marketplace install).

## Procedure

1. Choose a slug: lowercase letters, digits, hyphens (`^[a-z0-9][a-z0-9-]*$`). Prefer matching the folder name.
2. Author `SKILL.md` with YAML frontmatter:
   ```yaml
   ---
   name: my-skill
   description: One line, non-empty, roughly ≤ 160 characters.
   ---
   ```
   Frontmatter `name` is what `/my-skill` and discovery use; the folder name should match but discovery keys off `name`.
3. **Avoid reserved slash-command names** — do not use: `help`, `quit`, `new`, `reset`, `resume`, `stop`, `model`, `retry`, `usage`, `compress`, `skills`, `memory`, `personality`, `title`.
4. Keep the body ≤ **32 KB**. Prefer sections: When to use → Procedure → Tools to prefer → Pitfalls → Verification.
5. Paste under project `.cursor/skills/<name>/SKILL.md` or user `~/.cursor/skills/<name>/SKILL.md` (project wins on name clash).
6. Verify: `cursor-agent skills list` shows the skill. Invoke with `/<name>` in the REPL when listed.
7. **Trust warning:** treat third-party skills as untrusted instructions — read the body before pasting; never paste secrets into a skill file.

## Tools to prefer

- Tool profile: any local (`coding` or `full`); SDK workspace writes/reads are enough.
- No GitHub/search MCP required for authoring.

## Pitfalls

- `name` colliding with a reserved slash command (skill will not route).
- Folder name ≠ frontmatter `name` causing operator confusion.
- Body over 32 KB — discovery **truncates** oversized content at the 32 KB cap; it does not reject the file. Prefer keeping skills well under the limit so nothing important is cut.
- Pasting unreviewed third-party content that exfiltrates data or weakens security posture.

## Verification

- `cursor-agent skills list` includes the new `name` and description.
- `name` is not a reserved slash-command name.
- File is under project or user `.cursor/skills/<name>/` and ≤ 32 KB.
- Operator was warned if the skill came from a third party.
