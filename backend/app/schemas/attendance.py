from marshmallow import Schema, fields, validate


_VALID_SOURCES = ["web", "mobile", "biometric", "kiosk", "api"]


class AttendanceCheckinSchema(Schema):
    lat = fields.Float(load_default=None, validate=validate.Range(min=-90.0, max=90.0))
    lng = fields.Float(load_default=None, validate=validate.Range(min=-180.0, max=180.0))
    source = fields.Str(load_default="web", validate=validate.OneOf(_VALID_SOURCES))
    photo_url = fields.Str(load_default=None, validate=validate.Length(max=500))
    notes = fields.Str(load_default=None, validate=validate.Length(max=500))


class AttendanceCheckoutSchema(Schema):
    lat = fields.Float(load_default=None, validate=validate.Range(min=-90.0, max=90.0))
    lng = fields.Float(load_default=None, validate=validate.Range(min=-180.0, max=180.0))
    source = fields.Str(load_default="web", validate=validate.OneOf(_VALID_SOURCES))
    photo_url = fields.Str(load_default=None, validate=validate.Length(max=500))
    notes = fields.Str(load_default=None, validate=validate.Length(max=500))


class AttendanceRegularizationSchema(Schema):
    date = fields.Date(required=True, format="%Y-%m-%d")
    check_in = fields.Str(load_default=None)
    check_out = fields.Str(load_default=None)
    reason = fields.Str(required=True, validate=validate.Length(min=5, max=500))
