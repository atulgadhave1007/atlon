from marshmallow import Schema, fields, validate, validates, ValidationError
from app.utils.security import is_valid_email


class EmployeeCreateSchema(Schema):
    first_name = fields.Str(required=True, validate=validate.Length(min=1, max=100))
    last_name = fields.Str(required=True, validate=validate.Length(min=1, max=100))
    work_email = fields.Str(required=True)
    date_of_joining = fields.Date(required=True, format="%Y-%m-%d")

    # Optional identity
    middle_name = fields.Str(load_default=None, validate=validate.Length(max=100))
    display_name = fields.Str(load_default=None, validate=validate.Length(max=200))
    employee_number = fields.Str(load_default=None, validate=validate.Length(max=30))
    gender = fields.Str(load_default=None, validate=validate.OneOf(
        ["male", "female", "other", "prefer_not_to_say"]
    ))
    date_of_birth = fields.Date(load_default=None, format="%Y-%m-%d")
    nationality = fields.Str(load_default=None, validate=validate.Length(max=100))

    # Contact
    personal_email = fields.Str(load_default=None)
    personal_phone = fields.Str(load_default=None, validate=validate.Length(max=20))
    work_phone = fields.Str(load_default=None, validate=validate.Length(max=20))

    # Employment
    employment_type = fields.Str(load_default="full_time", validate=validate.OneOf(
        ["full_time", "part_time", "contract", "intern", "consultant"]
    ))
    role = fields.Str(load_default="employee", validate=validate.OneOf(
        ["employee", "manager", "hr_admin", "payroll_admin"]
    ))
    department_id = fields.Str(load_default=None)
    designation_id = fields.Str(load_default=None)
    branch_id = fields.Str(load_default=None)
    reporting_manager_id = fields.Str(load_default=None)

    # Statutory
    pan = fields.Str(load_default=None, validate=validate.Length(max=20))
    uan = fields.Str(load_default=None, validate=validate.Length(max=20))

    @validates("work_email")
    def validate_work_email(self, value):
        if not is_valid_email(value):
            raise ValidationError("Invalid email address.")

    @validates("personal_email")
    def validate_personal_email(self, value):
        if value and not is_valid_email(value):
            raise ValidationError("Invalid personal email address.")


class EmployeeUpdateSchema(Schema):
    """Subset of fields allowed on PATCH /employees/<id>."""
    first_name = fields.Str(validate=validate.Length(min=1, max=100))
    last_name = fields.Str(validate=validate.Length(min=1, max=100))
    middle_name = fields.Str(load_default=None, validate=validate.Length(max=100))
    display_name = fields.Str(load_default=None, validate=validate.Length(max=200))
    gender = fields.Str(load_default=None, validate=validate.OneOf(
        ["male", "female", "other", "prefer_not_to_say"]
    ))
    date_of_birth = fields.Date(load_default=None, format="%Y-%m-%d")
    personal_phone = fields.Str(load_default=None, validate=validate.Length(max=20))
    personal_email = fields.Str(load_default=None)
    nationality = fields.Str(load_default=None, validate=validate.Length(max=100))
    pan = fields.Str(load_default=None, validate=validate.Length(max=20))
    uan = fields.Str(load_default=None, validate=validate.Length(max=20))
    department_id = fields.Str(load_default=None)
    designation_id = fields.Str(load_default=None)
    branch_id = fields.Str(load_default=None)
    reporting_manager_id = fields.Str(load_default=None)
    employment_type = fields.Str(load_default=None, validate=validate.OneOf(
        ["full_time", "part_time", "contract", "intern", "consultant"]
    ))
