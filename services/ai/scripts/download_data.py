"""Download the pinned public educational dataset; never execute archive code."""
from pathlib import Path
import hashlib
import json
import shutil
import urllib.request
import zipfile
from http.client import IncompleteRead
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[3]
URL = 'https://zenodo.org/records/21700869/files/pkp_intercity_delays_dataset.zip?download=1'
MD5 = '7628d3022ec6f257864492ef9d1b3262'
SIZE = 64492235


def download():
    dest = ROOT / 'data' / 'pkp'
    dest.mkdir(parents=True, exist_ok=True)
    archive = dest / 'pkp_intercity_delays_dataset.zip'
    if not archive.exists() or hashlib.md5(archive.read_bytes()).hexdigest() != MD5:
        temporary = archive.with_suffix('.part')
        chunks = dest / 'chunks'
        chunks.mkdir(exist_ok=True)
        chunk_size = 1024 * 1024
        def fetch(start):
            end = min(start + chunk_size, SIZE) - 1
            chunk = chunks / str(start)
            if chunk.exists() and chunk.stat().st_size == end - start + 1:
                return chunk
            for attempt in range(3):
                try:
                    request = urllib.request.Request(URL, headers={'Range': f'bytes={start}-{end}'})
                    with urllib.request.urlopen(request, timeout=90) as r:
                        if r.status != 206 or r.headers.get('Content-Range') != f'bytes {start}-{end}/{SIZE}':
                            raise ValueError('Invalid range response')
                        payload = r.read()
                    if len(payload) != end - start + 1:
                        raise ValueError('Incomplete chunk')
                    chunk.write_bytes(payload)
                    return chunk
                except (OSError, ValueError, IncompleteRead):
                    if attempt == 2: raise
        with ThreadPoolExecutor(max_workers=4) as pool:
            parts = list(pool.map(fetch, range(0, SIZE, chunk_size)))
        with temporary.open('wb') as out:
            for part in parts:
                out.write(part.read_bytes())
        if hashlib.md5(temporary.read_bytes()).hexdigest() != MD5:
            raise ValueError('Checksum mismatch on assembled archive')
        temporary.replace(archive)
    digest = hashlib.md5(archive.read_bytes()).hexdigest()
    if digest != MD5:
        raise ValueError(f'Checksum mismatch: {digest}. Remove the damaged archive and retry.')
    with zipfile.ZipFile(archive) as z:
        for member in z.infolist():
            target = (dest / member.filename).resolve()
            if not target.is_relative_to(dest.resolve()):
                raise ValueError('Unsafe archive member')
        z.extractall(dest)
    print(json.dumps({'path': str(dest), 'bytes': archive.stat().st_size, 'md5': digest}))


if __name__ == '__main__':
    download()
