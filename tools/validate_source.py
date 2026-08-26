from __future__ import annotations
import json,re,sys,zipfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
errors=[]
def powershell_balance_error(text: str):
    pairs={')':'(',']':'[','}':'{'}; stack=[]; i=0; n=len(text)
    while i<n:
        if text.startswith('<#',i):
            j=text.find('#>',i+2)
            if j<0:return 'unterminated block comment'
            i=j+2;continue
        ch=text[i]
        if ch=='#':
            j=text.find('\n',i+1);i=n if j<0 else j+1;continue
        if text.startswith("@'",i) or text.startswith('@"',i):
            quote=text[i+1];marker='\n'+quote+'@';j=text.find(marker,i+2)
            if j<0:return 'unterminated here-string'
            i=j+len(marker);continue
        if ch=="'":
            i+=1
            while i<n:
                if text[i]=="'":
                    if i+1<n and text[i+1]=="'":i+=2;continue
                    i+=1;break
                i+=1
            else:return 'unterminated single-quoted string'
            continue
        if ch=='"':
            i+=1
            while i<n:
                if text[i]=='`':i+=2;continue
                if text[i]=='"':i+=1;break
                i+=1
            else:return 'unterminated double-quoted string'
            continue
        if ch=='`':i+=2;continue
        if ch in '([{':stack.append((ch,i))
        elif ch in ')]}':
            if not stack or stack[-1][0]!=pairs[ch]:return f'unbalanced {ch} at offset {i}'
            stack.pop()
        i+=1
    if stack:return f'unclosed {stack[-1][0]} at offset {stack[-1][1]}'
    return None
for p in root.rglob('*.json'):
    if 'dist' in p.parts:continue
    try:json.loads(p.read_text(encoding='utf-8-sig'))
    except Exception as e:errors.append(f'JSON {p}: {e}')
required=['engine/Core.psm1','engine/State.psm1','engine/Detection.psm1','engine/Network.psm1','engine/Runtime.psm1','engine/Evidence.psm1','gui/Workbench.xaml','gui/Workbench.Wpf.ps1','gui/GuiAdapter.psm1','web/backend/app.py','Start_M_LLM_Workbench.cmd','Start_M_LLM_Workbench.ps1']
for rel in required:
    if not (root/rel).exists():errors.append(f'missing {rel}')
ids=[]
for p in sorted((root/'tasks').glob('*.task.ps1')):
    s=p.read_text(errors='replace');m=re.findall(r"Register-MLLMTask\s+@\{Id='([^']+)'",s,re.I)
    if len(m)!=1:errors.append(f'{p.name}: expected 1 task registration, got {len(m)}')
    else:ids+=m
if len(ids)!=len(set(ids)):errors.append('duplicate task ids')
policy=json.loads((root/'config/task-policy.json').read_text())
for name,arr in policy['presets'].items():
    for x in arr:
        if x not in ids:errors.append(f'preset {name} unknown {x}')
if errors:
    print('STATIC_VALIDATION=FAIL');print('\n'.join(' - '+e for e in errors));sys.exit(1)
print(f'STATIC_VALIDATION=PASS tasks={len(ids)}')
