from starlette.exceptions import HTTPException

class AppError(HTTPException):
    def __init__(self, status_code: int, message: str, code: str = "app_error", errors: list | None = None):
        self.code = code
        self.errors = errors or []
        super().__init__(status_code=status_code, detail=message)


class ProductImportError(AppError):
    def __init__(self, message: str, code: str, errors: list[dict] | None = None):
        super().__init__(status_code=400, message=message, code=code, errors=errors)


def build_error_payload(error: Exception) -> dict:
    detail = getattr(error, "detail", None)
    message = detail if isinstance(detail, str) else "Request failed"
    return {
        "message": message,
        "code": getattr(error, "code", "request_error"),
        "errors": getattr(error, "errors", []),
    }
