"""Verify paired wheel contents and imports; optionally run selected offline operator tests."""
import argparse
import ast
import hashlib
import importlib
import importlib.abc
import importlib.machinery
import importlib.metadata
import email.message
import subprocess
import ipaddress
import json
import os
from pathlib import Path
import runpy
import shlex
import sys
import tempfile
import unittest
import zipfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')


def configure(wheel_root, sites):
    sys.dont_write_bytecode = True
    sys.path[:] = [str(wheel_root)] + [p for p in sys.path if p and 'site-packages' not in p and 'dist-packages' not in p and Path(p).is_relative_to(Path(sys.base_prefix))] + sites
    class SourceFinder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split('.')[0] not in ('cs', 'zylch'):
                return None
            spec = importlib.machinery.PathFinder.find_spec(fullname, [str(wheel_root)] if path is None else path)
            if spec is None:
                return None
            if spec.origin and not Path(spec.origin).resolve().is_relative_to(wheel_root):
                raise ImportError('Foreign candidate module: ' + fullname)
            return spec
    sys.meta_path.insert(0, SourceFinder())
    def offline(event, values):
        if event in ('socket.connect', 'socket.bind', 'socket.getaddrinfo'):
            address = values[:2] if event == 'socket.getaddrinfo' else values[1]
            if isinstance(address, tuple):
                host = address[0]
                if host == 'localhost':
                    return
                try:
                    allowed = ipaddress.ip_address(host).is_loopback
                except ValueError:
                    allowed = False
                if not allowed:
                    raise RuntimeError('Offline verification refused external socket: ' + str(address))
    sys.addaudithook(offline)


def audit(wheel_root):
    modules = {}
    for name, module in sorted(sys.modules.items()):
        if name.split('.')[0] in ('cs', 'zylch'):
            paths = [getattr(module, '__file__', None)] + list(getattr(module, '__path__', []))
            for origin in paths:
                if origin and not Path(origin).resolve().is_relative_to(wheel_root):
                    raise RuntimeError('Foreign module source: ' + name + ' ' + origin)
            modules[name] = paths
    return modules


def launch_child():
    wheel_root = Path(sys.argv[2]).resolve()
    sites = json.loads(sys.argv[3])
    args = sys.argv[4:]
    configure(wheel_root, sites)
    sys.argv = args
    try:
        if args[0] == '-c':
            sys.argv = ['-c', *args[2:]]
            exec(args[1], {'__name__': '__main__'})
        elif args[0] == '-m':
            sys.argv = args[1:]
            runpy.run_module(args[1], run_name='__main__', alter_sys=True)
        else:
            runpy.run_path(args[0], run_name='__main__')
    finally:
        audit(wheel_root)


def own_suite(suite, module_name, exclusions):
    result = unittest.TestSuite()
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            result.addTests(own_suite(item, module_name, exclusions))
        elif type(item).__module__ == module_name or isinstance(item, unittest.loader._FailedTest):
            if item.id() not in exclusions:
                result.addTest(item)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--tests', choices=('none', 'desktop', 'kernel', 'all'), default='none')
    parser.add_argument('--test-module', action='append', default=[], help='Run only these manifest test module stems; repeatable.')
    args = parser.parse_args()
    report = json.loads(args.report.read_bytes())
    args.output.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='wheel-check-', dir=args.output.resolve()))
    for key in list(os.environ):
        if key.startswith(('ZYLCH_','CS_','FIREBASE_','OPENAI_','ANTHROPIC_','MRCALL_TEST_')):
            os.environ.pop(key)
    sandbox_home = work/'home'
    sandbox_home.mkdir()
    os.environ.update({'HOME':str(sandbox_home),'ZYLCH_HOME':str(sandbox_home/'profile')})
    wheel_root = work / 'packages'
    wheel_root.mkdir()
    coverage = []
    manifests = []
    for package in report['packages']:
        wheel = Path(package['wheel'])
        if sha(wheel.read_bytes()) != package['wheel_sha256']:
            raise ValueError('Wheel hash mismatch: ' + str(wheel))
        with zipfile.ZipFile(wheel) as archive:
            for name in archive.namelist():
                if Path(name).is_absolute() or '..' in Path(name).parts:
                    raise ValueError('Unsafe wheel member: ' + name)
            archive.extractall(wheel_root)
        export_root = Path(package['export'])
        manifest_path = export_root / 'docs/operator-source-manifest.json'
        if sha(manifest_path.read_bytes()) != package['manifest_sha256']:
            raise ValueError('Manifest hash mismatch')
        manifest = json.loads(manifest_path.read_bytes())
        manifests.append((package, manifest))
        expected = {**manifest['files'], **manifest.get('supplemental_base_files', {})}
        expected_names = set()
        for path, entry in expected.items():
            relative = path.removeprefix('engine/')
            expected_names.add(relative)
            if sha((wheel_root / relative).read_bytes()) != entry['sha256']:
                raise ValueError('Wheel package mismatch: ' + relative)
        actual = {str(p.relative_to(wheel_root)) for p in (wheel_root / package['package_prefix']).rglob('*') if p.is_file()}
        if actual != expected_names:
            raise ValueError('Wheel package-set mismatch: ' + repr(sorted(actual ^ expected_names)))
        for path, expected_hash in manifest.get('required_present', {}).items():
            if sha((wheel_root / path.removeprefix('engine/')).read_bytes()) != expected_hash:
                raise ValueError('Required guard mismatch: ' + path)
        coverage.append({'package':package['package_prefix'],'expected_paths':len(manifest['files']),'supplemental_paths':len(manifest.get('supplemental_base_files', {})),'exact_paths':len(actual),'wheel_sha256':package['wheel_sha256']})
    if args.test_module:
        available = {
            Path(path).stem
            for package, manifest in manifests
            if args.tests in ('all', 'desktop' if package['package_prefix'] == 'zylch/' else 'kernel')
            for path in manifest['tests']
        }
        unknown = set(args.test_module) - available
        if unknown:
            parser.error('Test modules absent from the selected scope: ' + ', '.join(sorted(unknown)))
    native_command = [sys.executable,'-I','-S','-B',str(Path(__file__).resolve()),'--native-without-sdk',str(wheel_root),json.dumps(report['third_party_sites'])]
    native_check = subprocess.run(native_command,capture_output=True,text=True)
    save(args.output/'native-without-sdk.json',{'command':native_command,'exit_code':native_check.returncode,'stdout':native_check.stdout,'stderr':native_check.stderr})
    if native_check.returncode:
        raise RuntimeError('Ordinary native imports failed without optional MCP SDK; see native-without-sdk.json')
    configure(wheel_root, report['third_party_sites'])
    imports = ('cs.cli', 'cs.desktop_runtime', 'cs.desktop_diagnostic', 'cs.desktop_mcp', 'cs.bootstrap', 'zylch.cli.main', 'zylch.operator_mcp.__main__', 'zylch.operator_mcp.server', 'zylch.operator_mcp.issuer', 'zylch.rpc.dispatch')
    imported = {}
    for name in imports:
        imported[name] = importlib.import_module(name).__file__
    entrypoints = {}
    for dist_name in ('zylch', 'cs-kernel'):
        dist = importlib.metadata.distribution(dist_name)
        entrypoints[dist_name] = {}
        for entry in dist.entry_points:
            if entry.group == 'console_scripts':
                entrypoints[dist_name][entry.name] = {'value':entry.value,'callable':callable(entry.load())}
    versions = {}
    for name in ('setuptools','mcp','uvicorn','jsonschema','jinja2','MarkupSafe'):
        versions[name] = importlib.metadata.version(name)
    wrapper = work / 'isolated-python'
    command = [sys.executable, '-I', '-S', '-B', str(Path(__file__).resolve()), '--child', str(wheel_root), json.dumps(report['third_party_sites'])]
    wrapper.write_text('#!/bin/sh\nexec ' + shlex.join(command) + ' "$@"\n')
    wrapper.chmod(0o755)
    sys.executable = str(wrapper)
    exclusions = {}
    result = {'excluded_cases':exclusions,'coverage':coverage,'imports':imported,'entrypoints':entrypoints,'versions':versions,'python':sys.version,'fresh_dependency_environment':False,'wheel_root':str(wheel_root),'tests':[]}
    class AuditedResult(unittest.TextTestResult):
        def stopTest(self, test):
            audit(wheel_root)
            super().stopTest(test)
    for package, manifest in manifests:
        desktop = package['package_prefix'] == 'zylch/'
        if args.tests not in ('all', 'desktop' if desktop else 'kernel'):
            continue
        root = Path(package['export'])
        sys.path[:0] = [str(root),str(root/'engine'),str(root/'engine/tests')] if desktop else [str(root/'tests'), str(root)]
        selected_tests = {p:e for p,e in manifest['tests'].items() if not args.test_module or Path(p).stem in args.test_module}
        pytest_paths = [p for p in selected_tests if desktop and any(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name.startswith('test_') for n in ast.parse((root/p).read_bytes()).body)]
        module_names = ['engine.tests.' + Path(p).stem if desktop else Path(p).stem for p in selected_tests if p not in pytest_paths]
        suite = unittest.TestSuite()
        for name in module_names:
            suite.addTests(own_suite(unittest.defaultTestLoader.loadTestsFromName(name),name,exclusions))
        run = unittest.TextTestRunner(verbosity=2,resultclass=AuditedResult).run(suite)
        result['tests'].append({'package':package['package_prefix'],'modules':module_names,'tests':run.testsRun,'failures':len(run.failures),'errors':len(run.errors),'skipped':[{'test':test.id(),'reason':reason} for test,reason in run.skipped],'success':run.wasSuccessful()})
        save(args.output/'test-results.json',result['tests'])
        if pytest_paths:
            import pytest
            sys.path.insert(0,str(root/'engine/tests/assignments'))
            class AuditPlugin:
                def pytest_runtest_teardown(self,item,nextitem):
                    audit(wheel_root)
            pytest_code = pytest.main([*[str(root/p) for p in pytest_paths],'-q','--tb=short','--noconftest','-p','no:cacheprovider'],plugins=[AuditPlugin()])
            result['tests'].append({'package':'zylch/','framework':'pytest','paths':pytest_paths,'exit_code':int(pytest_code),'success':pytest_code == 0})
            save(args.output/'test-results.json',result['tests'])
    result['source_audit'] = audit(wheel_root)
    result['success'] = all(t['success'] for t in result['tests'])
    save(args.output/'check-report.json',result)
    print('PACKAGE_COVERAGE',json.dumps(coverage))
    print('SOURCE_AUDIT_MODULES',len(result['source_audit']))
    print('CHECK_REPORT',args.output/'check-report.json')
    raise SystemExit(0 if result['success'] else 1)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--native-without-sdk':
        root = Path(sys.argv[2]).resolve()
        configure(root,json.loads(sys.argv[3]))
        class WithoutSDK(importlib.abc.MetaPathFinder):
            def find_spec(self,name,path=None,target=None):
                if name == 'mcp' or name.startswith('mcp.'):
                    raise ModuleNotFoundError('Optional MCP SDK deliberately unavailable')
        sys.meta_path.insert(0,WithoutSDK())
        for name in ('zylch.assistant.core','zylch.rpc.methods','zylch.rpc.server_ws'):
            importlib.import_module(name)
        print(json.dumps({'ordinary_native_imports':'passed','audited_modules':len(audit(root)),'mcp_loaded':any(n == 'mcp' or n.startswith('mcp.') for n in sys.modules)}))
    elif len(sys.argv) > 1 and sys.argv[1] == '--child':
        launch_child()
    else:
        main()
