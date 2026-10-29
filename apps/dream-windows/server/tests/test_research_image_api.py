import time

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from errors import DreamApiError
import research_experiment_routes
from test_research_image_service import harness  # real shared service/queue, inference boundary only


@pytest.fixture
def client(harness):
    assert hasattr(research_experiment_routes,'create_research_image_router'), 'Image experiment router missing'
    app=FastAPI()
    @app.exception_handler(DreamApiError)
    async def error(request,exc):
        return JSONResponse(status_code=exc.status_code,content={'code':exc.code,'message':exc.message})
    app.include_router(research_experiment_routes.create_research_image_router(harness[1]),prefix='/api/identity')
    with TestClient(app,base_url='http://127.0.0.1:8866') as client: yield client


PREFIX='/api/identity/research/images'


def test_submit_poll_and_serve_four_bound_images_without_native_parallelism(client):
    assert client.get(PREFIX+'/capability').json()['available'] is True
    response=client.post(PREFIX,json={'prompt':'x','seed':42,'steps':1,'width':256,'height':256,'requestId':'http-request-00001'})
    assert response.status_code==200,response.text
    job=response.json()['id']
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        row=client.get(PREFIX+'/'+job).json()
        if row['state'] not in ('queued','running'): break
        time.sleep(.01)
    assert row['state']=='complete',row
    for variant in row['result']['variants']:
        image=client.get(variant['imageUrl'])
        assert image.status_code==200 and image.content.startswith(b'\x89PNG')
    assert client.get(PREFIX+'/'+job+'/not-a-mode/image').status_code==422
    assert client.get(PREFIX+'/fusion-'+'f'*24).status_code==404


def test_mutation_rejects_cross_origin_oversize_invalid_paths_and_nan(client):
    assert client.post(PREFIX,json={},headers={'origin':'https://evil.example'}).status_code==403
    assert client.post(PREFIX,content=' '*40000,headers={'content-type':'application/json'}).status_code==413
    assert client.post(PREFIX,json={'prompt':'x','requestId':'http-request-00001','outputPaths':{}}).status_code==422
    assert client.post(PREFIX,content='{"prompt":"x","requestId":"http-request-00001","cfg":NaN}',headers={'content-type':'application/json'}).status_code==422


def test_cancel_returns_promptly_and_incomplete_images_stay_unavailable(client,harness):
    _,_,_,_,release,started=harness
    release.clear()
    row=client.post(PREFIX,json={'prompt':'x','requestId':'cancel-request-001'}).json()
    assert started.wait(2)
    response=client.post(PREFIX+'/'+row['id']+'/cancel')
    assert response.status_code==200
    assert response.json()['state'] in ('cancelling','cancelled')
    assert client.get(PREFIX+'/'+row['id']+'/first_only/image').status_code==404


def test_identity_router_mounts_same_service_with_its_own_guard_and_preserves_refinements(harness,monkeypatch):
    import identity_routes
    _,service,runner,*_=harness
    constructed=[]
    def existing(config,job_runner):
        assert config is service.config and job_runner is runner
        constructed.append(service)
        return service
    monkeypatch.setattr(identity_routes,'IdentityService',existing)
    router=identity_routes.create_identity_router(service.config,runner)
    paths={route.path for route in router.routes}
    assert '/api/identity/refinements' in paths
    assert PREFIX in paths and PREFIX+'/capability' in paths
    assert constructed==[service]
    app=FastAPI()
    @app.exception_handler(DreamApiError)
    async def error(request,exc):
        return JSONResponse(status_code=exc.status_code,content={'code':exc.code})
    app.include_router(router)
    with TestClient(app,base_url='http://127.0.0.1:8866') as client:
        assert client.get(PREFIX+'/capability').json()['available'] is True
        assert client.post(PREFIX,json={},headers={'origin':'https://evil.example'}).status_code==403
    assert service._closed


def test_identity_router_injected_service_never_constructs_a_second_owner(harness,monkeypatch):
    import identity_routes
    _,service,runner,*_=harness
    monkeypatch.setattr(identity_routes,'IdentityService',lambda *args:pytest.fail('constructed a duplicate service owner'))
    app=FastAPI()
    @app.exception_handler(DreamApiError)
    async def error(request,exc):
        return JSONResponse(status_code=exc.status_code,content={'code':exc.code})
    app.include_router(identity_routes.create_identity_router(service.config,runner,service=service))
    with TestClient(app,base_url='http://127.0.0.1:8866') as client:
        assert client.get(PREFIX+'/capability').json()['available'] is True
        assert client.post(PREFIX,json={},headers={'origin':'https://evil.example'}).status_code==403
    assert service._closed


@pytest.mark.parametrize('headers',[
    {'origin':'https://evil.example'}, {'host':'evil.example'},
    {'origin':'http://127.0.0.1:8866/'}, {'sec-fetch-site':'cross-site'},
])
def test_shared_origin_helper_rejects_unsafe_mutation_origins(harness,headers):
    from identity_routes import require_local_origin
    from starlette.requests import Request
    merged={'host':'127.0.0.1:8866',**headers}
    request=Request({'type':'http','scheme':'http','server':('127.0.0.1',8866),'path':'/api/identity/x',
                     'query_string':b'','headers':[(k.encode(),v.encode()) for k,v in merged.items()]})
    with pytest.raises(DreamApiError) as error:
        require_local_origin(request,harness[1].config)
    assert error.value.status_code==403
