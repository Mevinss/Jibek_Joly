"""Pin a GitHub revision and verify dataset bytes without cloning large benchmark blobs."""
import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import quote
import httpx
from ..settings import ROOT

REPOSITORY = 'Mevinss/TurkiSib'
PKP_PREFIX = 'data/external/pkp/pkp_intercity_delays_dataset/'


def blob_sha(content):
    return hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()


def checked_path(root, relative):
    path = PurePosixPath(relative)
    if path.is_absolute() or PureWindowsPath(relative).drive or '..' in path.parts or '\\' in relative:
        raise ValueError('Unsafe source path')
    target = root.joinpath(*path.parts).resolve()
    if not target.is_relative_to(root.resolve()): raise ValueError('Path leaves snapshot')
    return target


def sync(ref, destination):
    with httpx.Client(timeout=60, follow_redirects=True, headers={'User-Agent': 'TurkiSib-data-sync'}) as client:
        def get_json(url):
            response = client.get(url); response.raise_for_status(); return response.json()
        api = f'https://api.github.com/repos/{REPOSITORY}'
        if re.fullmatch(r'[0-9a-f]{40}', ref):
            commit = ref
        else:
            commit = get_json(api + '/git/ref/heads/' + quote(ref, safe=''))['object']['sha']
        commit_data = get_json(api + '/git/commits/' + commit)
        tree_sha = commit_data['tree']['sha']
        tree = get_json(api + '/git/trees/' + tree_sha + '?recursive=1')
        if tree.get('truncated'): raise ValueError('Incomplete Git tree')
        destination.mkdir(parents=True, exist_ok=True)
        files, inventory = [], []
        for entry in tree['tree']:
            path = entry['path']
            if entry['type'] != 'blob': continue
            if path.startswith('data/'): inventory.append({k: entry[k] for k in ('path', 'sha', 'size')})
            wanted = (path.endswith('.md') or path.startswith(PKP_PREFIX)
                      or path.startswith('data/kz_demo/') or path == 'data/source_manifest.json')
            if not wanted: continue
            target = checked_path(destination, path)
            candidates = [target]
            if path.startswith(PKP_PREFIX):
                candidates.append(ROOT / 'data/pkp/pkp_intercity_delays_dataset' / path[len(PKP_PREFIX):])
            content, method = None, 'download'
            for candidate in candidates:
                if not candidate.is_file(): continue
                data = candidate.read_bytes()
                if blob_sha(data) == entry['sha']:
                    content, method = data, 'verified_local_bytes'; break
                normalized = data.replace(b'\r\n', b'\n')
                if blob_sha(normalized) == entry['sha']:
                    content, method = normalized, 'verified_local_line_endings'; break
            if content is None:
                response = client.get(f'https://raw.githubusercontent.com/{REPOSITORY}/{commit}/{quote(path, safe="/")}')
                response.raise_for_status(); content = response.content
            if blob_sha(content) != entry['sha']: raise ValueError(f'Blob integrity mismatch: {path}')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            files.append({'path': path, 'git_blob_sha': entry['sha'], 'bytes': len(content),
                          'sha256': hashlib.sha256(content).hexdigest(), 'method': method})
        manifest = {'repository': REPOSITORY, 'ref': ref, 'commit': commit, 'tree_sha': tree_sha,
                    'files': files, 'data_inventory': inventory}
        for name, data in [('tree.json', tree), ('snapshot.json', manifest)]:
            (destination / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'commit': commit, 'verified_files': len(files), 'snapshot': str(destination)}, ensure_ascii=False))
        return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--ref', default='main')
    parser.add_argument('--destination', type=Path, default=ROOT / 'data/main-source')
    args = parser.parse_args()
    sync(args.ref, args.destination)
