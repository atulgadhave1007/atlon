import pytest
from datetime import date


class TestAttendance:
    def test_checkin(self, client, auth_headers):
        r = client.post('/api/attendance/checkin', headers=auth_headers, json={'source': 'web'})
        assert r.status_code in (200, 409)

    def test_checkout(self, client, auth_headers):
        r = client.post('/api/attendance/checkout', headers=auth_headers, json={'source': 'web'})
        assert r.status_code in (200, 400)

    def test_today_attendance(self, client, auth_headers):
        r = client.get('/api/attendance/today', headers=auth_headers)
        assert r.status_code in (200, 404)

    def test_monthly_attendance(self, client, auth_headers):
        today = date.today()
        r = client.get('/api/attendance/monthly', query_string={
            'year': today.year, 'month': today.month
        }, headers=auth_headers)
        assert r.status_code == 200
        data = r.get_json()
        assert 'records' in data
        assert 'summary' in data

    def test_regularization(self, client, auth_headers):
        r = client.post('/api/attendance/regularize', headers=auth_headers, json={
            'date': str(date.today()),
            'check_in': f'{date.today()}T09:00:00',
            'check_out': f'{date.today()}T18:00:00',
            'reason': 'Forgot to check in via portal'
        })
        assert r.status_code in (201, 400)

    def test_shifts_list(self, client, auth_headers):
        r = client.get('/api/attendance/shifts', headers=auth_headers)
        assert r.status_code == 200

    def test_holidays_list(self, client, auth_headers):
        r = client.get('/api/attendance/holidays', headers=auth_headers)
        assert r.status_code == 200
        data = r.get_json()
        assert 'holidays' in data


class TestLeave:
    def test_leave_types(self, client, auth_headers):
        r = client.get('/api/leave/types', headers=auth_headers)
        assert r.status_code == 200

    def test_leave_balance(self, client, auth_headers):
        r = client.get('/api/leave/balance', headers=auth_headers)
        assert r.status_code == 200
        data = r.get_json()
        assert 'balances' in data

    def test_apply_leave(self, client, auth_headers):
        r = client.get('/api/leave/types', headers=auth_headers)
        types = r.get_json().get('leave_types', [])
        if not types:
            pytest.skip('No leave types configured')

        r2 = client.post('/api/leave/apply', headers=auth_headers, json={
            'leave_type_id': types[0]['id'],
            'from_date': '2025-12-20',
            'to_date': '2025-12-21',
            'reason': 'Personal work'
        })
        assert r2.status_code in (201, 400)

    def test_leave_applications(self, client, auth_headers):
        r = client.get('/api/leave/applications', headers=auth_headers)
        assert r.status_code == 200
        data = r.get_json()
        assert 'applications' in data
