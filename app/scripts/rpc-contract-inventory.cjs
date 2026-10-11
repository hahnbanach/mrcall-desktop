const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')
const { spawnSync } = require('node:child_process')
const { createHash } = require('node:crypto')
const ts = require('typescript')

const root = path.resolve(__dirname, '../..')
const app = path.join(root, 'app')
const preloadPath = path.join(app, 'src/preload/index.ts')
const rendererPath = path.join(app, 'src/renderer/src/types.ts')
const kernel = path.resolve(process.env.CS_KERNEL_ROOT || path.join(root, '../cs-kernel'))
const python = process.env.ENGINE_PYTHON || path.join(root, 'engine/venv/bin/python')
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'rpc-inventory-'))
const pythonSource = String.raw`
import ast, inspect, json, os, pathlib, re
from zylch.rpc.dispatch import METHODS
from zylch.rpc.param_spec import ACCEPTED_PARAMS, REQUIRED_PARAMS, OPEN_METHODS
methods = {}
for name, handler in sorted(METHODS.items()):
    doc = inspect.getdoc(handler) or ''
    signature = re.match(r'^\s*[A-Za-z0-9_.]+\s*\(.*?\)\s*(?:->\s*([^\n]+))?', doc, re.S)
    methods[name] = {'accepted': sorted(ACCEPTED_PARAMS.get(name, [])), 'required': sorted(REQUIRED_PARAMS.get(name, [])), 'declared_return': signature.group(1) if signature else None, 'open': name in OPEN_METHODS}
kernel = pathlib.Path(os.environ['CS_KERNEL_ROOT'])
if not (kernel / 'cs/rpc.py').is_file():
    raise SystemExit('CS_KERNEL_ROOT must contain cs/rpc.py; missing inventory is not a pass')
calls = []
for source in sorted((kernel / 'cs').rglob('*.py')):
    tree = ast.parse(source.read_text())
    for node in sorted(ast.walk(tree), key=lambda n: getattr(n, 'lineno', 0)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ''
        if name not in {'call_sync', 'call_rpc', 'call'}:
            continue
        offset = 1 if name == 'call_sync' or (name == 'call' and source.name in {'setup.py', 'project_documents.py', 'instructions.py'}) else 0
        if len(node.args) <= offset:
            continue
        method_node = node.args[offset]
        method = method_node.value if isinstance(method_node, ast.Constant) and isinstance(method_node.value, str) else None
        payload = node.args[offset + 1] if len(node.args) > offset + 1 else next((kw.value for kw in node.keywords if kw.arg == 'params'), None)
        keys = sorted(key.value for key in payload.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)) if isinstance(payload, ast.Dict) else []
        dynamic = payload is not None and (not isinstance(payload, ast.Dict) or any(key is None or not isinstance(key, ast.Constant) for key in payload.keys))
        calls.append({'file': source.relative_to(kernel).as_posix(), 'line': node.lineno, 'callee': ast.unparse(func), 'method': method, 'method_expression': ast.unparse(method_node), 'keys': keys, 'dynamic_payload': dynamic, 'return': 'Any at EngineClient.call; no runtime return schema'})
print(json.dumps({'engine': methods, 'kernel_calls': calls}))
`
let data
try {
  const result = spawnSync(python, ['-c', pythonSource], {
    cwd: scratch, encoding: 'utf8', maxBuffer: 8 * 1024 * 1024,
    env: { PATH: process.env.PATH || '', HOME: scratch, PYTHONPATH: path.join(root, 'engine'),
      ZYLCH_HOME: scratch, ZYLCH_PROFILE_DIR: scratch, ZYLCH_DB_PATH: path.join(scratch, 'inventory.db'),
      EMAIL_ADDRESS: 'inventory@example.test', EMAIL_PASSWORD: 'fixture-only', CS_KERNEL_ROOT: kernel }
  })
  if (result.status !== 0) throw new Error(result.stderr || result.stdout)
  data = JSON.parse(result.stdout)
} finally {
  fs.rmSync(scratch, { recursive: true, force: true })
}

function inventory(preloadText = fs.readFileSync(preloadPath, 'utf8'), rendererText = fs.readFileSync(rendererPath, 'utf8')) {
  const host = ts.createCompilerHost({})
  const originalRead = host.readFile.bind(host)
  host.readFile = file => path.resolve(file) === preloadPath ? preloadText : path.resolve(file) === rendererPath ? rendererText : originalRead(file)
  const program = ts.createProgram([preloadPath, rendererPath], {
    strict: true, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext,
    moduleResolution: ts.ModuleResolutionKind.Bundler, skipLibCheck: true, esModuleInterop: true
  }, host)
  const checker = program.getTypeChecker()
  const preload = program.getSourceFile(preloadPath)
  const renderer = program.getSourceFile(rendererPath)
  const errors = program.getSyntacticDiagnostics().map(d => ts.flattenDiagnosticMessageText(d.messageText, '\n'))
  const calls = []
  const linkage = []
  const typeText = type => checker.typeToString(type, undefined, ts.TypeFormatFlags.NoTruncation)

  function shape(type) {
    if (type.isUnion()) {
      const parts = type.types.filter(t => !(t.flags & ts.TypeFlags.Undefined)).map(shape)
      return { keys: [...new Set(parts.flatMap(p => p.keys))].sort(),
        required: parts.length ? parts[0].required.filter(k => parts.every(p => p.required.includes(k))) : [],
        dynamic: parts.some(p => p.dynamic) }
    }
    const properties = checker.getPropertiesOfType(type)
    return { keys: properties.map(p => p.name).sort(),
      required: properties.filter(p => !(p.flags & ts.SymbolFlags.Optional)).map(p => p.name).sort(),
      dynamic: Boolean(type.flags & (ts.TypeFlags.Any | ts.TypeFlags.Unknown)) || Boolean(checker.getIndexTypeOfType(type, ts.IndexKind.String)) }
  }

  function payloadShape(node) {
    if (!node) return { keys: [], required: [], dynamic: false }
    const result = shape(checker.getTypeAtLocation(node))
    if (result.dynamic && ts.isIdentifier(node)) {
      const symbol = checker.getSymbolAtLocation(node)
      const declaration = symbol?.valueDeclaration
      if (declaration && ts.isVariableDeclaration(declaration) && declaration.initializer && ts.isObjectLiteralExpression(declaration.initializer)) {
        const initial = shape(checker.getTypeAtLocation(declaration.initializer))
        const keys = new Set(initial.keys)
        let computed = false
        let scope = declaration.parent
        while (scope.parent && !ts.isFunctionLike(scope)) scope = scope.parent
        function writes(current) {
          if (ts.isBinaryExpression(current) && current.operatorToken.kind === ts.SyntaxKind.EqualsToken) {
            const lhs = current.left
            if (ts.isPropertyAccessExpression(lhs) && ts.isIdentifier(lhs.expression) && checker.getSymbolAtLocation(lhs.expression) === symbol) keys.add(lhs.name.text)
            if (ts.isElementAccessExpression(lhs) && checker.getSymbolAtLocation(lhs.expression) === symbol) computed = true
          }
          ts.forEachChild(current, writes)
        }
        writes(scope)
        return { keys: [...keys].sort(), required: initial.required, dynamic: computed }
      }
    }
    return result
  }

  function visit(node) {
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === 'call') {
      const methodNode = node.arguments[0]
      const method = methodNode && ts.isStringLiteralLike(methodNode) ? methodNode.text : null
      const payload = payloadShape(node.arguments[1])
      const row = { line: preload.getLineAndCharacterOfPosition(node.getStart()).line + 1, method,
        payload_keys: payload.keys, guaranteed_keys: payload.required, dynamic_payload: payload.dynamic,
        declared_return: typeText(checker.getTypeAtLocation(node)) }
      calls.push(row)
      if (!method || !data.engine[method]) errors.push(`preload line ${row.line}: unknown method ${method}`)
      else {
        const contract = data.engine[method]
        for (const key of payload.keys) if (!contract.accepted.includes(key)) errors.push(`${method}: unknown payload key ${key}`)
        if (!payload.dynamic) for (const key of contract.required) if (!payload.required.includes(key)) errors.push(`${method}: required payload key ${key} is not guaranteed`)
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(preload)
  let apiNode
  function findApi(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText() === 'api') apiNode = node
    ts.forEachChild(node, findApi)
  }
  findApi(preload)
  const rendererNode = renderer.statements.find(n => ts.isInterfaceDeclaration(n) && n.name.text === 'ZylchAPI')
  if (!apiNode || !rendererNode) throw new Error('Both preload api and renderer ZylchAPI are required')

  function compare(source, target, prefix) {
    for (const property of checker.getPropertiesOfType(target)) {
      const location = [...prefix, property.name].join('.')
      const actual = checker.getPropertyOfType(source, property.name)
      if (!actual) { errors.push(`renderer API ${location} is missing in preload`); continue }
      const st = checker.getTypeOfSymbolAtLocation(actual, apiNode)
      const tt = checker.getTypeOfSymbolAtLocation(property, rendererNode)
      const ss = st.getCallSignatures()[0]
      const tsig = tt.getCallSignatures()[0]
      if (ss && tsig) {
        const issues = []
        for (let index = 0; index < tsig.parameters.length; index++) {
          const expected = tsig.parameters[index]
          const accepted = ss.parameters[index]
          if (!accepted) { issues.push(`argument ${index + 1} absent in preload`); continue }
          const et = checker.getTypeOfSymbolAtLocation(expected, rendererNode)
          const at = checker.getTypeOfSymbolAtLocation(accepted, apiNode)
          const declaration = accepted.valueDeclaration || accepted.declarations?.[0]
          const acceptsUndefined = declaration && (declaration.initializer || declaration.questionToken)
          const alternatives = et.isUnion() ? et.types : [et]
          if (!alternatives.every(t => (acceptsUndefined && Boolean(t.flags & ts.TypeFlags.Undefined)) || checker.isTypeAssignableTo(t, at))) issues.push(`argument ${index + 1}: ${typeText(et)} is not accepted as ${typeText(at)}`)
        }
        for (let index = tsig.parameters.length; index < ss.parameters.length; index++) {
          const parameter = ss.parameters[index]
          const declaration = parameter.valueDeclaration || parameter.declarations?.[0]
          if (!declaration?.initializer && !declaration?.questionToken && !declaration?.dotDotDotToken) issues.push(`required preload argument ${index + 1} absent from renderer`)
        }
        for (const issue of issues) errors.push(`${location}: ${issue}`)
        linkage.push({ api: location, renderer: typeText(tt), preload: typeText(st),
          renderer_arguments_accepted: issues.length === 0,
          declared_return_assignable: checker.isTypeAssignableTo(checker.getReturnTypeOfSignature(ss), checker.getReturnTypeOfSignature(tsig)) })
      } else compare(st, tt, [...prefix, property.name])
    }
  }
  compare(checker.getTypeAtLocation(apiNode.name), checker.getTypeAtLocation(rendererNode), [])
  for (const item of linkage) if (!item.declared_return_assignable) errors.push(`${item.api}: preload declared return is not assignable to renderer declaration`)
  return { calls, linkage, errors }
}

const result = inventory()
for (const [method, contract] of Object.entries(data.engine)) if (contract.open) result.errors.push(`${method}: engine parameter declaration is open`)
for (const call of data.kernel_calls) {
  if (!call.method) continue
  const contract = data.engine[call.method]
  if (!contract) result.errors.push(`${call.file}:${call.line}: unknown kernel method ${call.method}`)
  else {
    for (const key of call.keys) if (!contract.accepted.includes(key)) result.errors.push(`${call.file}:${call.line}: unknown ${call.method} key ${key}`)
    if (!call.dynamic_payload) for (const key of contract.required) if (!call.keys.includes(key)) result.errors.push(`${call.file}:${call.line}: missing ${call.method} key ${key}`)
  }
}
if (process.argv.includes('--negative-proof')) {
  const original = fs.readFileSync(preloadPath, 'utf8')
  const altered = original.replace("{ task_id, note: note ?? null }", "{ task_id, invalid_contract_key: note ?? null }")
  if (altered === original || !inventory(altered).errors.some(e => e.includes('unknown payload key invalid_contract_key'))) throw new Error('Malformed payload negative proof did not fail')
  const missing = original.replace("{ task_id, note: note ?? null }", "{ note: note ?? null }")
  if (missing === original || !inventory(missing).errors.some(e => e.includes('tasks.complete: required payload key task_id is not guaranteed'))) throw new Error('Missing required payload negative proof did not fail')
  const wrongReturn = original.replace("call<{ ok: boolean }>('tasks.complete'", "call<{ ok: number }>('tasks.complete'")
  if (wrongReturn === original || !inventory(wrongReturn).errors.some(e => e.startsWith('tasks.complete: preload declared return'))) throw new Error('Declared return negative proof did not fail')
  const renderer = fs.readFileSync(rendererPath, 'utf8')
  const changedRenderer = renderer.replace('complete: (task_id: string, note?', 'complete: (task_id: number, note?')
  if (changedRenderer === renderer || !inventory(original, changedRenderer).errors.some(e => e.startsWith('tasks.complete: argument 1'))) throw new Error('Renderer argument negative proof did not fail')
  console.log('Negative proofs passed: unknown/missing preload keys, incompatible renderer argument and declared return rejected')
}
if (result.errors.length) {
  console.error(result.errors.join('\n'))
  process.exit(1)
}
const sourceHash = file => createHash('sha256').update(fs.readFileSync(file)).digest('hex')
const report = { version: 1, source_sha256: { preload: sourceHash(preloadPath), renderer: sourceHash(rendererPath), finance: sourceHash(path.join(app, 'src/renderer/src/finance.ts')) }, command: 'ENGINE_PYTHON=../engine/venv/bin/python CS_KERNEL_ROOT=../../cs-kernel npm run test:rpc-contracts',
  limits: [
    'Engine accepted/required parameter names are runtime-enforced docstring declarations; parameter value types and returns have no shared runtime schema.',
    'Preload payload keys use the TypeScript checker plus local named-property assignment extraction; dynamic indexed payloads remain explicit.',
    'Renderer argument assignability checks the first callable signature against preload declarations, including defaults. Declared return assignability is checked; any/unknown may hide drift and no declaration proves runtime results.',
    'Kernel candidates are Python AST calls named call_sync, call_rpc or call; aliases with other names and dynamically generated calls are outside this inventory.',
    'Kernel variable payloads and computed method names are reported without dataflow resolution; Any returns are not validated.',
    'WebSocket transport tests use fixture claims; Firebase verification, deployed clones and packaged installers are outside these checks.'
  ], engine: data.engine, preload_calls: result.calls, renderer_linkage: result.linkage, kernel_calls: data.kernel_calls }
if (process.argv.includes('--write')) fs.writeFileSync(path.join(root, 'docs/rpc-contract-inventory.json'), JSON.stringify(report, null, 2) + '\n')
console.log(`RPC parameter checks passed: ${Object.keys(data.engine).length} engine methods, ${result.calls.length} preload calls, ${result.linkage.length} renderer methods, ${data.kernel_calls.length} kernel candidates`)
console.log(`Limitations: ${result.calls.filter(c => c.dynamic_payload).length} dynamic preload payloads, ${result.linkage.filter(c => !c.declared_return_assignable).length} incompatible declared renderer returns, ${data.kernel_calls.filter(c => !c.method || c.dynamic_payload).length} unresolved kernel calls`)
