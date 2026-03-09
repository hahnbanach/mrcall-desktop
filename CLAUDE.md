# Claude Code Configuration - Zylch

## CRITICAL: NO OUTPUT TRUNCATION IN CODE

**NEVER truncate output in code you write:**
- NO `[:8]`, `[:50]`, `[:100]`, `[:200]` slicing for display
- NO `...` or `[truncated]` in user-facing output or **WORSE** when debugging!!
- ALWAYS show FULL IDs, FULL content, FULL values
- Let the USER decide if output is too long

## CRITICAL: DEBUG LOGGING OBBLIGATORIO

**Ogni comando/feature DEVE avere debug logging** per poter diagnosticare problemi:

1. **Input**: Loggare args/parametri ricevuti
2. **Chiamate**: Loggare ogni funzione chiamata con input E output
3. **Risultati**: Loggare valori intermedi e finali

**Pattern**:
```python
logger.debug(f"[/comando] funzione(param={param}) -> result={result}")
```

**MAI** loggare token/secrets. Solo "present"/"absent".

Senza logging, diagnosticare problemi è **IMPOSSIBILE**.

## CRITICAL: CONCURRENT EXECUTION & FILE MANAGEMENT

**ABSOLUTE RULES**:
1. ALL operations MUST be concurrent/parallel in a single message
2. **NEVER save working files, text/mds and tests to the root folder**
3. ALWAYS organize files in appropriate subdirectories

### GOLDEN RULE: "1 MESSAGE = ALL RELATED OPERATIONS"

**MANDATORY PATTERNS:**
- **File operations**: ALWAYS batch ALL reads/writes/edits in ONE message
- **Bash commands**: ALWAYS batch ALL terminal operations in ONE message
- **Agent tool**: ALWAYS spawn ALL agents in ONE message when independent

### File Organization Rules

**NEVER save to root folder. Use these directories:**
- `/zylch` - Source code
- `/tests` - Test files
- `/docs` - Documentation and markdown files
- `/scripts` - Utility scripts

## Code Style & Best Practices

- **Modular Design**: Files under 500 lines
- **Environment Safety**: Never hardcode secrets
- **Test-First**: Write tests before implementation
- **Clean Architecture**: Separate concerns
- **Documentation**: Keep updated

# important-instruction-reminders
Do what has been asked; nothing more, nothing less.
NEVER create files unless they're absolutely necessary for achieving your goal.
ALWAYS prefer editing an existing file to creating a new one.
NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.
Never save working files, text/mds and tests to the root folder.
