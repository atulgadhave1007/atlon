from app.extensions import db
from app.models.base import BaseModel, TenantMixin, GUID


class Visitor(BaseModel, TenantMixin):
    __tablename__ = 'visitors'

    visitor_number = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    company = db.Column(db.String(200))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(200))
    purpose = db.Column(db.Text)
    host_employee_id = db.Column(GUID(), db.ForeignKey('employees.id'))
    badge_number = db.Column(db.String(20))
    check_in_time = db.Column(db.DateTime)
    check_out_time = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='expected')  # expected, checked_in, checked_out, cancelled
    id_type = db.Column(db.String(20))
    id_number = db.Column(db.String(50))
    photo_path = db.Column(db.String(500))
    items_carried = db.Column(db.Text)
    vehicle_number = db.Column(db.String(20))


class Timesheet(BaseModel, TenantMixin):
    __tablename__ = 'timesheets'

    employee_id = db.Column(GUID(), db.ForeignKey('employees.id'), nullable=False)
    week_start = db.Column(db.Date, nullable=False)
    week_end = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='draft')  # draft, submitted, approved, rejected
    total_hours = db.Column(db.Numeric(6, 2), default=0)
    billable_hours = db.Column(db.Numeric(6, 2), default=0)
    submitted_at = db.Column(db.DateTime)
    approved_by_id = db.Column(GUID(), db.ForeignKey('employees.id'))
    approved_at = db.Column(db.DateTime)
    remarks = db.Column(db.Text)

    entries = db.relationship('TimesheetEntry', backref='timesheet', cascade='all,delete-orphan')


class TimesheetEntry(BaseModel):
    __tablename__ = 'timesheet_entries'

    timesheet_id = db.Column(GUID(), db.ForeignKey('timesheets.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    project = db.Column(db.String(200))
    task = db.Column(db.String(500))
    hours = db.Column(db.Numeric(5, 2), nullable=False)
    billable = db.Column(db.Boolean, default=True)
    description = db.Column(db.Text)
    tenant_id = db.Column(GUID(), db.ForeignKey('tenants.id'), nullable=False)
