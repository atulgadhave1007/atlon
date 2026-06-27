from marshmallow import ValidationError
from flask import jsonify


def validate_request(schema, data: dict):
    """
    Validate data against a marshmallow schema.
    Returns (validated_dict, None) on success, or (None, error_response) on failure.

    Usage in a route:
        validated, err = validate_request(EmployeeCreateSchema(), data)
        if err:
            return err
    """
    try:
        validated = schema.load(data)
        return validated, None
    except ValidationError as exc:
        return None, (jsonify({"errors": exc.messages}), 422)
