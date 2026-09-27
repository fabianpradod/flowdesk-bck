from starlette.exceptions import HTTPException

class AppError(HTTPException):
    def __init__(self, status_code: int, message: str, code: str = "app_error", errors: list | None = None,):
        self.message = message
        self.code = code
        self.errors = errors or []

        super().__init__(status_code=status_code, detail=message,)

class ProductImportError(AppError):
    def __init__(self, message: str, code: str, errors: list[dict] | None = None,):
        super().__init__(status_code=400, message=message, code=code, errors=errors,)

def build_error_payload(error: Exception) -> dict:
    detail = getattr(error, "detail", None)

    if isinstance(detail, str):
        message = detail
    else:
        message = getattr(error, "message", "Request failed")

    return {
        "message": message,
        "code": getattr(error, "code", "request_error"),
        "errors": getattr(error, "errors", []),
    }

def sanitize_validation_errors(errors) -> list[dict]:
    """Keep where and why each field failed, drop what was sent.

    Pydantic also returns `input`, the raw value (passwords included), and `ctx`,
    which can hold a Decimal limit or the ValueError itself. Neither belongs in a
    response, and since neither is JSON serializable they turned a 422 into a 500.
    """
    return [
        {
            "loc": list(error.get("loc", ())),
            "msg": error.get("msg", ""),
            "type": error.get("type", ""),
        }
        for error in errors
    ]
