# Tutorial CLI Recorder - Development Plan

## Overview
A Python tool that reads a tutorial script produced by Claude Code, types commands into a terminal with typewriter effect, speaks narration via ElevenLabs TTS, and waits for output before proceeding.

## Core Components

### 1. Script Parser
- Load JSON tutorial scripts (produced by Claude Code)
- Validate structure against schema

### 2. Terminal Controller
- Use Python `pty` module to spawn and control a shell
- Typewriter effect: inject characters with configurable delay (e.g., 50ms between keystrokes)
- Capture output in real-time

### 3. TTS Narrator (ElevenLabs)
- Integrate ElevenLabs API for high-quality voice synthesis
- Cache audio files to avoid redundant API calls
- Play audio via `pygame`, `playsound`, or similar
- Blocking playback (wait for speech to finish before proceeding)

### 4. Orchestrator
- Read script steps sequentially
- For each step:
  1. Speak narration via ElevenLabs (wait for completion)
  2. Type command character-by-character (typewriter effect)
  3. Press enter and capture output
  4. Wait for output pattern match or timeout
  5. Optional pause after step
  6. Proceed to next step

---

## Tutorial Script Schema (for Claude Code to produce)

Claude Code generates a JSON file following this schema:

```json
{
  "title": "Tutorial Title",
  "description": "Brief description of what this tutorial covers",
  "config": {
    "voice_id": "EXAVITQu4vr4xnSDxMaL",
    "typing_delay_ms": 50,
    "default_wait_timeout_sec": 10,
    "default_post_delay_sec": 1.5
  },
  "steps": [
    {
      "narration": "Text to speak before the command. Should explain what we're about to do and why.",
      "command": "echo 'Hello, World!'",
      "wait_for": "Hello",
      "wait_timeout_sec": 5,
      "post_delay_sec": 2
    },
    {
      "narration": "Now let's create a new directory for our project.",
      "command": "mkdir my-project && cd my-project",
      "wait_for": null,
      "wait_timeout_sec": 3,
      "post_delay_sec": 1
    },
    {
      "narration": "Let's initialize a new Node.js project with default settings.",
      "command": "npm init -y",
      "wait_for": "package.json",
      "wait_timeout_sec": 10,
      "post_delay_sec": 2
    }
  ]
}
```

### Schema Field Definitions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | string | yes | Tutorial name |
| `description` | string | yes | What the tutorial covers |
| `config.voice_id` | string | yes | ElevenLabs voice ID |
| `config.typing_delay_ms` | integer | yes | Milliseconds between keystrokes |
| `config.default_wait_timeout_sec` | number | yes | Default timeout waiting for output |
| `config.default_post_delay_sec` | number | yes | Default pause after each step |
| `steps` | array | yes | List of tutorial steps |
| `steps[].narration` | string | yes | Text to speak (TTS) |
| `steps[].command` | string | yes | Command to type and execute |
| `steps[].wait_for` | string \| null | no | Regex/substring to wait for in output |
| `steps[].wait_timeout_sec` | number | no | Override default timeout |
| `steps[].post_delay_sec` | number | no | Override default post-step delay |

---

## File Structure
```
tools/tutorial-recorder/
├── recorder.py          # Main orchestrator / CLI entry point
├── terminal.py          # PTY controller + typewriter effect
├── narrator.py          # ElevenLabs TTS wrapper
├── schema.py            # Pydantic models for script validation
├── config.py            # Environment variables, API keys
├── requirements.txt     # Dependencies
└── examples/
    └── demo.json        # Example tutorial script
```

## Dependencies
- Python 3.10+
- `pty` (stdlib)
- `elevenlabs` - ElevenLabs Python SDK
- `pydantic` - Script validation
- `pygame` or `playsound` - Audio playback

## Environment Variables
```
ELEVENLABS_API_KEY=your_api_key_here
```

## Usage
```bash
python recorder.py examples/demo.json
```
