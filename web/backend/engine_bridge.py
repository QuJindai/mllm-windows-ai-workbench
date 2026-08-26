from __future__ import annotations
import json, os, subprocess
from pathlib import Path
import httpx

class EngineBridge:
    def __init__(self, testing: bool=False):
        self.testing=testing
        self.project_root=Path(os.environ.get('MLLM_PROJECT_ROOT') or Path(__file__).resolve().parents[2])
        self.data_root=Path(os.environ.get('MLLM_DATA_ROOT') or (Path(os.environ.get('LOCALAPPDATA','.') )/'M-LLM'/'Data'))
    def _state_path(self): return self.data_root/'state'/'runtime.json'
    def state(self):
        p=self._state_path()
        if not p.exists(): return {'schema_version':1,'runtime':{'api':{},'web':{}},'models':{}}
        return json.loads(p.read_text(encoding='utf-8-sig'))
    def snapshot(self): return {'state':self.state(),'data_root':str(self.data_root),'project_root':str(self.project_root)}
    def chat(self,messages):
        state=self.state();base=((state.get('runtime') or {}).get('api') or {}).get('base_url')
        if not base: raise RuntimeError('Local model service is not running')
        with httpx.Client(timeout=120) as c:
            r=c.post(base.rstrip('/')+'/chat/completions',json={'model':'local','messages':messages,'temperature':0.2,'max_tokens':512}); r.raise_for_status(); return r.json()
    def _run_ps(self,*args):
        if os.name!='nt': return {'ok':False,'error':'PowerShell control actions require Windows'}
        ps=str(self.project_root/'Start_M_LLM_Workbench.ps1'); cmd=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',ps,*args,'-DataRoot',str(self.data_root)]
        p=subprocess.run(cmd,capture_output=True,text=True,timeout=1800)
        return {'ok':p.returncode==0,'returncode':p.returncode,'stdout':p.stdout[-12000:],'stderr':p.stderr[-12000:]}
    def service_start(self): return self._run_ps('-StartService')
    def service_stop(self): return self._run_ps('-StopService')
    def doctor(self): return self._run_ps('-Doctor')
