from fastapi.testclient import TestClient
from app import main, database, privacy


def test_consent_encryption_masking_and_login(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'privacy.db')
    main._requests.clear()
    with TestClient(main.app) as client:
        payload = {'username': 'private-user', 'password': 'private-password-long', 'age': 38, 'address': '123 Private Street', 'consent': False, 'consent_version': privacy.CONSENT_VERSION}
        assert client.post('/api/auth/register', json=payload).status_code == 422
        payload['consent'] = True
        payload['age'] = 'bad-private-age'
        invalid = client.post('/api/auth/register', json=payload)
        assert invalid.status_code == 422 and 'bad-private-age' not in invalid.text
        payload['age'] = 38
        assert client.post('/api/auth/register', json=payload).status_code == 201
        with database.db() as conn:
            user = conn.execute('SELECT * FROM users').fetchone()
            profile = conn.execute('SELECT * FROM registration_profiles').fetchone()
        assert user['username'] == privacy.username_key('private-user')
        assert all(value not in profile['encrypted_profile'] for value in ['Private Street', 'private-user'])
        assert profile['consent_version'] == privacy.CONSENT_VERSION and profile['consent_at']
        assert privacy.cipher().decrypt(profile['encrypted_profile'].encode())
        assert client.post('/api/auth/login', json={'username': 'private-user', 'password': 'wrong'}).status_code == 401
        login = client.post('/api/auth/login', json=payload)
        assert login.status_code == 200
        result = client.get('/api/auth/profile')
        assert result.json() == {'username': 'p***', 'age': '***', 'address': '[hidden]'}
        assert result.headers['cache-control'] == 'no-store'


def test_privacy_key_required_and_secure_transport(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'privacy.db')
    main._requests.clear()
    payload = {'username': 'private-user', 'password': 'private-password-long', 'age': 38, 'address': '123 Private Street', 'consent': True, 'consent_version': privacy.CONSENT_VERSION}
    with TestClient(main.app, base_url='http://public.example') as client:
        assert client.post('/api/auth/register', json=payload).status_code == 400
    monkeypatch.delenv('GUARDIAN_PII_ENCRYPTION_KEY')
    with TestClient(main.app) as client:
        assert client.post('/api/auth/register', json=payload).status_code == 503
