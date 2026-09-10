import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve, join } from 'node:path'
import { fileURLToPath } from 'node:url'
const require = createRequire(import.meta.url)
const {buildSync} = require('esbuild')
const app = resolve(fileURLToPath(new URL('..', import.meta.url)))
const output = mkdtempSync(join(tmpdir(), 'mrcall-setup-preview-'))
buildSync({entryPoints:[join(app, 'src/renderer/src/lib/setupReadiness.ts')], bundle:true, platform:'node', format:'cjs', outfile:join(output,'model.cjs')})
const {preparationSummary, needsEngineSplash} = require(join(output,'model.cjs'))
for (const view of ['setup', 'settings', 'logs']) assert.equal(needsEngineSplash(view, false, false), false)
assert.equal(needsEngineSplash('tasks',false,false),true)
assert.equal(preparationSummary({emails_count:10,has_trained:true,agents_trained:['memory_message','task_email','emailer'],emails_analyzed_count:12,emails_pending_analysis:0}).complete,false)
assert.equal(preparationSummary(null).complete,false)
assert.equal(preparationSummary({emails_count:10,has_trained:true}).complete,false)
assert.equal(preparationSummary({emails_count:0,has_trained:true,emails_analyzed_count:0,emails_pending_analysis:0}).complete,false)
assert.equal(preparationSummary({emails_count:10,has_trained:true,emails_analyzed_count:3,emails_pending_analysis:7}).complete,false)
assert.equal(preparationSummary({emails_count:10,has_trained:true,agents_trained:['memory_message','task_email','emailer'],emails_analyzed_count:10,emails_pending_analysis:0}).complete,true)
buildSync({entryPoints:[join(app,'scripts/fixtures-setup-preview.tsx')],bundle:true,platform:'browser',format:'iife',jsx:'automatic',outfile:join(output,'preview.js')})
writeFileSync(join(output,'index.html'), '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="style.css"></head><body style="margin:0;background:#f5f5f5;font-family:Arial,sans-serif"><div id="root"></div><p id="navigation"></p><script src="preview.js"></script></body></html>')
console.log('Setup evidence assertions passed. Actual component preview:',output)
