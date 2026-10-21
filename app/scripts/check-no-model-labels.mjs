#!/usr/bin/env node
// Fails when app/src names a model outside a comment (milestone 10a, AC 5).
// The engine resolves models from its role table and `llm.models` returns
// their labels; a model name or id written into the renderer goes stale with
// the next table. Comments are stripped (a comment cannot choose a model);
// strings and code are scanned. Run: npm run check:models
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const SRC = join(ROOT, 'src')
// Family names as a label spells them, and ids as the engine spells them.
const NAMES = /\b(?:Haiku|Sonnet|Opus|Fable|GLM|Kimi|Qwen|MiMo|DeepSeek)\b|\bclaude-[a-z0-9]|(?<![\w./-])(?:anthropic|z-ai|moonshotai|qwen|xiaomi|openai|google|deepseek|x-ai)\/[a-z0-9]/i

// Replace comments with spaces (newlines kept so line numbers hold),
// skipping over string and template literals.
export function stripComments(text) {
  let out = ''
  let i = 0
  while (i < text.length) {
    const c = text[i]
    const next = text[i + 1]
    if (c === '/' && next === '/') {
      while (i < text.length && text[i] !== '\n') { out += ' '; i++ }
    } else if (c === '/' && next === '*') {
      const end = text.indexOf('*/', i + 2)
      const stop = end === -1 ? text.length : end + 2
      out += text.slice(i, stop).replace(/[^\n]/g, ' ')
      i = stop
    } else if (c === '"' || c === "'" || c === '`') {
      let j = i + 1
      while (j < text.length && text[j] !== c && !(c !== '`' && text[j] === '\n')) {
        j += text[j] === '\\' ? 2 : 1
      }
      out += text.slice(i, j + 1)
      i = j + 1
    } else {
      out += c
      i++
    }
  }
  return out
}

function* files(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) yield* files(path)
    else if (/\.(tsx?|jsx?|mjs)$/.test(name)) yield path
  }
}

export function findings(root = SRC) {
  const found = []
  for (const path of files(root)) {
    stripComments(readFileSync(path, 'utf8')).split('\n').forEach((line, index) => {
      const match = line.match(NAMES)
      if (match) found.push(`${relative(ROOT, path)}:${index + 1}: ${match[0]} — ${line.trim().slice(0, 120)}`)
    })
  }
  return found
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const found = findings(process.argv[2] || SRC)
  if (found.length) {
    console.error('Model names in app/src outside comments; show what llm.models or the engine returns instead:')
    for (const line of found) console.error('  ' + line)
    process.exit(1)
  }
  console.log('check:models — no model name in app/src outside comments')
}
