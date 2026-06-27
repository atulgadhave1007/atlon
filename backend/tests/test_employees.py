import pytest


class TestEmployees:
    def test_list_employees(self, client, auth_headers):
        r = client.get('/api/employees', headers=auth_headers)
        assert r.status_code == 200
        data = r.get_json()
        assert 'employees' in data
        assert 'total' in data

    def test_create_employee(self, client, auth_headers, seeded):
        from datetime import date
        r = client.post('/api/employees', headers=auth_headers, json={
            'first_name': 'Jane',
            'last_name': 'Doe',
            'work_email': 'jane.doe@test.co',
            'date_of_joining': str(date.today()),
            'role': 'employee',
            'employment_type': 'full_time'
        })
        assert r.status_code == 201
        data = r.get_json()
        assert 'employee' in data
        assert data['employee']['work_email'] == 'jane.doe@test.co'
        assert 'temp_password' in data

    def test_get_employee(self, client, auth_headers, seeded):
        emp_id = str(seeded['employee'].id)
        r = client.get(f'/api/employees/{emp_id}', headers=auth_headers)
        assert r.status_code == 200
        data = r.get_json()
        assert data['id'] == emp_id

    def test_employee_not_found(self, client, auth_headers):
        r = client.get('/api/employees/00000000-0000-0000-0000-000000000000', headers=auth_headers)
        assert r.status_code == 404

    def test_update_employee(self, client, auth_headers, seeded):
        emp_id = str(seeded['employee'].id)
        r = client.put(f'/api/employees/{emp_id}', headers=auth_headers, json={
            'personal_phone': '+919876543210',
            'blood_group': 'O+'
        })
        assert r.status_code == 200

    def test_duplicate_email(self, client, auth_headers):
        from datetime import date
        client.post('/api/employees', headers=auth_headers, json={
            'first_name': 'Dup',
            'last_name': 'User',
            'work_email': 'dup@test.co',
            'date_of_joining': str(date.today()),
        })
        r = client.post('/api/employees', headers=auth_headers, json={
            'first_name': 'Dup',
            'last_name': 'User2',
            'work_email': 'dup@test.co',
            'date_of_joining': str(date.today()),
        })
        assert r.status_code == 409

    def test_org_chart(self, client, auth_headers):
        r = client.get('/api/employees/org-chart', headers=auth_headers)
        assert r.status_code == 200
        data = r.get_json()
        assert 'nodes' in data
