"""Build paired local wheels from manifest-enumerated source exports without installation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def export(root, destination, mode, ref, desktop, kernel_descriptor=None):
    commit = git(root, 'rev-parse', ref).decode().strip()
    def read(path):
        if Path(path).is_absolute() or '..' in Path(path).parts:
            raise ValueError('Unsafe source path: ' + path)
        return git(root, 'show', commit + ':' + path) if mode == 'git' else (root / path).read_bytes()
    if desktop:
        manifest_data = read('docs/operator-source-manifest.json')
        manifest = json.loads(manifest_data)
    else:
        if mode != 'git' or commit != kernel_descriptor['source_commit']:
            raise ValueError('Kernel export requires the exact embedded reviewed Git commit')
        manifest = {'files':{p:{'sha256':h} for p,h in kernel_descriptor['package_files'].items()},
            'tests':{p:{'sha256':h} for p,h in kernel_descriptor['test_files'].items()},
            'pairing':kernel_descriptor}
        manifest_data = (json.dumps(manifest,indent=2,sort_keys=True)+'\n').encode()
    expected = {**manifest['files'], **manifest.get('supplemental_base_files', {}), **manifest['tests']}
    if not desktop:
        expected.update({p:{'sha256':h} for p,h in kernel_descriptor['metadata'].items()})
    paths = set(expected) | {'docs/operator-source-manifest.json'}
    tracked = git(root, 'ls-tree', '-r', '--name-only', commit).decode().splitlines()
    if not desktop and {p for p in tracked if p.startswith('cs/')} != set(kernel_descriptor['package_files']):
        raise ValueError('Embedded paired kernel package inventory differs from the selected Git tree')
    test_prefix = 'engine/tests/' if desktop else 'tests/'
    paths.update(p for p in tracked if p.startswith(test_prefix) and p.endswith('.py'))
    metadata = 'engine/pyproject.toml' if desktop else 'pyproject.toml'
    paths.add(metadata)
    if desktop:
        paths.add('engine/README.md')
        paths.update(p for p in ('scripts/build_operator_candidate.py', 'scripts/check_operator_source.py') if mode != 'git' or p in tracked)
    paths.update(p for p in tracked if Path(p).name in ('LICENSE', 'LICENSE.txt') and len(Path(p).parts) <= 2)
    hashes = {}
    for path in sorted(paths):
        data = manifest_data if path == 'docs/operator-source-manifest.json' else read(path)
        if path in expected and digest(data) != expected[path]['sha256']:
            raise ValueError('Frozen manifest mismatch: ' + path)
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        hashes[path] = digest(data)
    for path, expected_hash in manifest.get('required_present', {}).items():
        if digest((destination / path).read_bytes()) != expected_hash:
            raise ValueError('Required native guard mismatch: ' + path)
    return {'repository': str(root), 'source_mode': mode, 'source_commit': commit,
            'head': git(root, 'rev-parse', 'HEAD').decode().strip(),
            'working_tree_status': git(root, 'status', '--porcelain', '--untracked-files=all').decode(),
            'manifest_sha256': digest(manifest_data), 'export': str(destination),
            'source_files': hashes, 'source_digest': digest(json.dumps(hashes, sort_keys=True).encode()),
            'metadata': metadata, 'package_prefix': 'zylch/' if desktop else 'cs/'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desktop-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--kernel-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--source-mode', choices=('working-tree', 'git'), default='working-tree')
    parser.add_argument('--desktop-ref', default='HEAD')
    parser.add_argument('--kernel-ref', required=True)
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--dependency-site', action='append', default=[], type=Path)
    parser.add_argument('--source-date-epoch', default='1704067200')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    sites = [str(p.resolve()) for p in args.dependency_site]
    if not sites or not all(Path(p).is_dir() for p in sites):
        parser.error('Provide existing third-party-only --dependency-site directories')
    desktop_root = args.desktop_root.resolve()
    manifest_data = git(desktop_root,'show',args.desktop_ref+':docs/operator-source-manifest.json') if args.source_mode == 'git' else (desktop_root/'docs/operator-source-manifest.json').read_bytes()
    pairing = json.loads(manifest_data)['paired_kernel']
    if args.kernel_ref != pairing['source_commit'] or not pairing['compatibility'].startswith('reviewed-'):
        parser.error('Select the exact reviewed paired kernel commit embedded in the Desktop manifest')
    temporary = Path(tempfile.mkdtemp(prefix='source-export-', dir=output))
    report = {'source_date_epoch': args.source_date_epoch, 'python': str(Path(args.python).absolute()),
              'third_party_sites': sites, 'fresh_dependency_environment': False, 'kernel_pair_scope':pairing['scope'], 'packages': []}
    for name, root, ref, desktop in (('desktop', args.desktop_root, args.desktop_ref, True), ('kernel', args.kernel_root, args.kernel_ref, False)):
        destination = temporary / name
        receipt = export(root.resolve(), destination, args.source_mode if desktop else 'git', ref, desktop, pairing)
        wheel_dir = output / 'wheels' / name
        wheel_dir.mkdir(parents=True, exist_ok=True)
        cwd = destination / ('engine' if desktop else '')
        code = 'import sys;sys.path[:0]=' + repr(sites) + ';from setuptools.build_meta import build_wheel;print(build_wheel(' + repr(str(wheel_dir)) + '))'
        command = [args.python, '-I', '-S', '-B', '-c', code]
        env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME') and not k.startswith(('ZYLCH_', 'CS_', 'FIREBASE_', 'OPENAI_', 'ANTHROPIC_'))}
        env.update(SOURCE_DATE_EPOCH=args.source_date_epoch, PYTHONHASHSEED='0')
        ran = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
        log = output / (name + '-build.log')
        log.write_text(ran.stdout + ran.stderr)
        receipt.update(build_command=command, build_exit_code=ran.returncode, build_log=str(log))
        report['packages'].append(receipt)
        if ran.returncode:
            write_json(output / 'build-report.json', report)
            raise SystemExit('Build failed; see ' + str(log))
        filename = ran.stdout.strip().splitlines()[-1]
        wheel = wheel_dir / filename
        receipt.update(wheel=str(wheel), wheel_sha256=digest(wheel.read_bytes()))
        print(name, filename, receipt['wheel_sha256'])
    write_json(output / 'build-report.json', report)
    print('BUILD_REPORT', output / 'build-report.json')


if __name__ == '__main__':
    main()
