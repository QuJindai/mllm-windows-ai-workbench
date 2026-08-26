from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from engine_bridge import EngineBridge

def create_app(testing: bool=False):
    app=FastAPI(title='M-LLM Workbench',version='1.0.0')
    bridge=EngineBridge(testing=testing)
    @app.get('/api/health')
    def health(): return {'ok':True,'service':'m-llm-web','bind_policy':'localhost-default'}
    @app.get('/api/snapshot')
    def snapshot(): return bridge.snapshot()
    @app.post('/api/service/start')
    def service_start(): return bridge.service_start()
    @app.post('/api/service/stop')
    def service_stop(): return bridge.service_stop()
    @app.post('/api/doctor')
    def doctor(): return bridge.doctor()
    @app.post('/api/chat')
    def chat(payload:dict):
        route=payload.get('route','local-fast')
        if route!='local-fast': raise HTTPException(400,'unsupported route')
        messages=payload.get('messages',[])
        if not isinstance(messages,list) or not messages: raise HTTPException(400,'messages required')
        try:return bridge.chat(messages)
        except Exception as e: raise HTTPException(503,str(e))
    front=Path(__file__).resolve().parents[1]/'frontend'
    if front.exists():
        app.mount('/static',StaticFiles(directory=str(front)),name='static')
        @app.get('/')
        def root(): return FileResponse(front/'index.html')
    return app
app=create_app()
