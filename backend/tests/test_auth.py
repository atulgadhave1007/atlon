import pytest


class TestAuth:
    def test_health(self, client):
        r = client.get('/api/health')
        assert r.status_code == 200
        data = r.get_json()
        assert data['status'] == 'ok'

    def test_login_invalid_email(self, client):
        r = client.post('/api/auth/login', json={
            'email': 'nobody@nowhere.com',
            'password': 'wrong',
            'slug': 'testco'
        })
        assert r.status_code in (401, 404)

    def test_login_success(self, client, seeded):
        r = client.post('/api/auth/login', json={
            'email': 'hradmin@test.co',
            'password': 'Test@1234',
            'slug': 'testco'
        })
        assert r.status_code == 200
        data = r.get_json()
        assert 'access_token' in data
        assert 'refresh_token' in data
        assert data['user']['role'] == 'hr_admin'

    def test_login_wrong_password(self, client, seeded):
        r = client.post('/api/auth/login', json={
            'email': 'hradmin@test.co',
            'password': 'wrongpassword',
            'slug': 'testco'
        })
        assert r.status_code == 401

    def test_me_without_token(self, client):
        r = client.get('/api/auth/me')
        assert r.status_code == 401

    def test_me_with_token(self, client, auth_headers):
        r = client.get('/api/auth/me', headers=auth_headers)
        assert r.status_code == 200
        data = r.get_json()
        assert data['email'] == 'hradmin@test.co'

    def test_super_admin_login(self, client, seeded):
        r = client.post('/api/auth/login', json={
            'email': 'superadmin@atlon.in',
            'password': 'Admin@123'
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data['user']['role'] == 'super_admin'

    def test_logout(self, client, seeded):
        r = client.post('/api/auth/login', json={
            'email': 'hradmin@test.co',
            'password': 'Test@1234',
            'slug': 'testco'
        })
        data = r.get_json()
        headers = {'Authorization': f'Bearer {data["access_token"]}', 'X-Tenant-Slug': 'testco'}
        r2 = client.post('/api/auth/logout', json={'refresh_token': data['refresh_token']}, headers=headers)
        assert r2.status_code == 200

    def test_change_password(self, client, seeded):
        r = client.post('/api/auth/login', json={
            'email': 'hradmin@test.co',
            'password': 'Test@1234',
            'slug': 'testco'
        })
        data = r.get_json()
        headers = {'Authorization': f'Bearer {data["access_token"]}', 'X-Tenant-Slug': 'testco'}
        r2 = client.post('/api/auth/change-password', json={
            'current_password': 'Test@1234',
            'new_password': 'NewTest@5678'
        }, headers=headers)
        assert r2.status_code == 200

        # Log in again with old password to restore
        client.post('/api/auth/login', json={
            'email': 'hradmin@test.co',
            'password': 'NewTest@5678',
            'slug': 'testco'
        })
