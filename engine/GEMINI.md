# Claude Code Configuration - SPARC Development Environment

## 🚨 CRITICAL: NO OUTPUT TRUNCATION IN CODE

**NEVER truncate output in code you write:**
- NO `[:8]`, `[:50]`, `[:100]`, `[:200]` slicing for display
- NO `...` or `[truncated]` in user-facing output or **WORSE** when debugging!!
- ALWAYS show FULL IDs, FULL content, FULL values
- Let the USER decide if output is too long

## 🚨 CRITICAL: MANDATORY DEBUG LOGGING 

**You must always add meaningful logs (debug/warning/info/error), particularly debug**

1. **Input**: Log all parameters
2. **Calls**: Endpoints, body etc
3. **Results**: Print 'em out!

**Pattern**:
```python
logger.debug(f"[/command] function(param={param}) -> result={result}")

## 🚨 CRITICAL: CONCURRENT EXECUTION & FILE MANAGEMENT

**ABSOLUTE RULES**:
1. ALL operations MUST be concurrent/parallel in a single message
2. **NEVER save working files, text/mds and tests to the root folder**
3. ALWAYS organize files in appropriate subdirectories

### ⚡ GOLDEN RULE: "1 MESSAGE = ALL RELATED OPERATIONS"

**MANDATORY PATTERNS:**
- **TodoWrite**: ALWAYS batch ALL todos in ONE call (5-10+ todos minimum)
- **File operations**: ALWAYS batch ALL reads/writes/edits in ONE message
- **Bash commands**: ALWAYS batch ALL terminal operations in ONE message
- **Memory operations**: ALWAYS batch ALL memory store/retrieve in ONE message

### 📁 File Organization Rules

**NEVER save to root folder. Use these directories:**
- `/src` - Source code files
- `/tests` - Test files
- `/docs` - Documentation and markdown files
- `/config` - Configuration files
- `/scripts` - Utility scripts
- `/examples` - Example code

## Project Overview

This project uses SPARC (Specification, Pseudocode, Architecture, Refinement, Completion) methodology with Claude-Flow orchestration for systematic Test-Driven Development.

## Code Style & Best Practices

- **Modular Design**: Files under 500 lines
- **Environment Safety**: Never hardcode secrets
- **Clean Architecture**: Separate concerns
- **Documentation**: Keep updated

