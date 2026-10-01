"""Reproduce the small browser fixture from its canonical synthetic package."""
import json
from ..settings import SERVICE

def main():
    source=SERVICE/'demo'/'eco-package.json'
    package=json.loads(source.read_text(encoding='utf-8'))
    target=SERVICE/'web'/'jibekjoly'/'synthetic-data.js'
    target.write_text('// Generated: python -m services.ai.scripts.export_eco_package\nexport const syntheticData = '+json.dumps(package,ensure_ascii=False,indent=2)+';\n',encoding='utf-8')

if __name__=='__main__':
    main()
