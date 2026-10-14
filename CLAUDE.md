# CLAUDE.md

Claude Code carga este archivo automáticamente. El contexto vive en archivos agnósticos de herramienta para que cualquier agente lo comparta:

@AGENTS.md
@MEMORY.md

## Específico de Claude Code

- Comandos personalizados (`/nombre`): `.claude/commands/<nombre>.md`
- Skills: `.claude/skills/<nombre>/SKILL.md`
- Subagentes: `.claude/agents/<nombre>.md`
- Preferencias personales no compartidas: `CLAUDE.local.md` (ignorado por git).
- Cuando el equipo corrija una conducta o tome una decisión que deba persistir, propone agregarla a `MEMORY.md` con fecha y porqué.
