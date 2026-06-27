from marshmallow import Schema, fields, validate, validates_schema, ValidationError
from datetime import datetime


class PayrollRunSchema(Schema):
    year = fields.Int(required=True, validate=validate.Range(min=2000, max=2100))
    month = fields.Int(required=True, validate=validate.Range(min=1, max=12))
    employee_ids = fields.List(fields.Str(), load_default=None)

    @validates_schema
    def validate_not_future(self, data, **kwargs):
        now = datetime.now()
        year = data.get("year")
        month = data.get("month")
        if year and month:
            if (year, month) > (now.year, now.month):
                raise ValidationError(
                    {"month": ["Cannot run payroll for a future period."]}
                )
