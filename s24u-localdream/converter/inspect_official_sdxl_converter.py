#!/usr/bin/env python3
"""Fingerprint and inspect Local Dream's official convertsdxl.zip."""
from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path

TEXT_SUFFIXES={'.py','.sh','.txt','.json','.yaml','.yml','.toml'}
EXPECTED={'prepare_data_sdxl.py','gen_quant_data_sdxl.py','export_onnx_sdxl.py','convert_all_sdxl.sh'}
KEYWORD_RE=re.compile(r'encoder_hidden_states|text_embeds|input_list|quant|onnx|unet|clip|sdxl',re.I)
L77=re.compile(r'(?<!\d)77(?!\d)')
L2048=re.compile(r'(?<!\d)2048(?!\d)')

def sha256(p:Path)->str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda:f.read(1024*1024),b''): h.update(c)
    return h.hexdigest()

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('root',type=Path); ap.add_argument('--output',type=Path,required=True); a=ap.parse_args()
    root=a.root.resolve(); found={n:[] for n in EXPECTED}; inventory=[]; hits=[]
    for p in sorted(x for x in root.rglob('*') if x.is_file()):
        rel=p.relative_to(root).as_posix(); inventory.append({'path':rel,'size':p.stat().st_size,'sha256':sha256(p)})
        if p.name in found: found[p.name].append(rel)
        if p.suffix.lower() not in TEXT_SUFFIXES: continue
        try: lines=p.read_text(encoding='utf-8').splitlines()
        except UnicodeDecodeError: continue
        for i,line in enumerate(lines,1):
            context='\n'.join(lines[max(0,i-3):min(len(lines),i+2)])
            direct='encoder_hidden_states' in line
            if direct or (L77.search(line) and KEYWORD_RE.search(context)) or (L2048.search(line) and KEYWORD_RE.search(context)):
                hits.append({'path':rel,'line':i,'text':line.rstrip(),'has_77':bool(L77.search(line)),'has_2048':bool(L2048.search(line)),'mentions_encoder_hidden_states':direct})
    missing=[n for n,v in found.items() if not v]; dup={n:v for n,v in found.items() if len(v)>1}
    report={'schema':1,'expected_files':found,'missing_expected_files':missing,'duplicate_expected_files':dup,'candidate_shape_sites':hits,'inventory':inventory}
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(f'files={len(inventory)} candidates={len(hits)} report={a.output}')
    for h in hits: print(f"{h['path']}:{h['line']}: {h['text']}")
    if missing or dup: print(f'CONVERTER_LAYOUT=FAIL missing={missing} duplicates={dup}'); return 2
    if not any(h['mentions_encoder_hidden_states'] for h in hits): print('CONVERTER_LAYOUT=FAIL encoder_hidden_states not found'); return 3
    print('CONVERTER_LAYOUT=PASS'); return 0
if __name__=='__main__': raise SystemExit(main())
