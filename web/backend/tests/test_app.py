from fastapi.testclient import TestClient
from app import create_app

def test_health_is_local_and_explicit():
    c=TestClient(create_app(testing=True)); r=c.get('/api/health'); assert r.status_code == 200; assert r.json()['ok'] is True

def test_chat_rejects_unknown_route():
    c=TestClient(create_app(testing=True)); r=c.post('/api/chat',json={'route':'not-real','messages':[{'role':'user','content':'x'}]}); assert r.status_code == 400
