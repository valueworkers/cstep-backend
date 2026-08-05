from rest_framework.exceptions import ValidationError


def parse_int_param(request, name):
    raw = request.query_params.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        raise ValidationError({name: f"'{raw}' is not a valid integer."})