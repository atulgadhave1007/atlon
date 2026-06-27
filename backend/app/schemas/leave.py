from marshmallow import Schema, fields, validate, validates_schema, ValidationError
from datetime import date as date_type


class LeaveApplicationSchema(Schema):
    leave_type_id = fields.Str(required=True)
    from_date = fields.Date(required=True, format="%Y-%m-%d")
    to_date = fields.Date(required=True, format="%Y-%m-%d")
    reason = fields.Str(required=True, validate=validate.Length(min=3, max=1000))
    from_half = fields.Str(load_default=None, validate=validate.OneOf(["first", "second"]))
    to_half = fields.Str(load_default=None, validate=validate.OneOf(["first", "second"]))
    contact_during_leave = fields.Str(load_default=None, validate=validate.Length(max=100))

    @validates_schema
    def validate_date_range(self, data, **kwargs):
        from_date = data.get("from_date")
        to_date = data.get("to_date")
        if from_date and to_date and from_date > to_date:
            raise ValidationError({"to_date": ["To date must be on or after from date."]})
        if from_date and from_date < date_type.today():
            raise ValidationError({"from_date": ["Leave cannot be applied for a past date."]})
