from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4
from pydantic import ValidationError
from sqlalchemy.orm import Session
from app.core.config import ZAI_API_KEY, ZAI_BASE_URL, ZAI_MODEL, ZAI_TIMEOUT_SECONDS
from app.integrations.zai import ZAIAnalysisProvider
from app.models.users import User
from app.schemas.intelligence import IntelligentAnalysisContent, IntelligentAnalysisRequest
from app.services.analysis_context import build_business_context
from app.tenancy.runtime import get_user_schema_name
from app.utils.exceptions import AppError

class AnalysisProvider(Protocol):
    name: str

    def generate(
        self,
        *,
        request: IntelligentAnalysisRequest,
        context: dict[str, Any],
    ) -> IntelligentAnalysisContent | dict[str, Any]: ...

def get_analysis_provider() -> AnalysisProvider:
    api_key = (ZAI_API_KEY or "").strip()
    if not api_key:
        raise AppError(
            status_code=503,
            message="Intelligent analysis provider is not configured",
            code="ai_provider_unavailable",
        )
    if not ZAI_BASE_URL.startswith("https://"):
        raise AppError(
            status_code=503,
            message="Intelligent analysis provider URL must use HTTPS",
            code="ai_provider_misconfigured",
        )
    return ZAIAnalysisProvider(
        api_key=api_key,
        model=ZAI_MODEL,
        base_url=ZAI_BASE_URL,
        timeout_seconds=ZAI_TIMEOUT_SECONDS,
    )

def create_intelligent_analysis(
    request: IntelligentAnalysisRequest,
    current_user: User,
    db: Session,
    provider: AnalysisProvider,
) -> dict[str, Any]:
    get_user_schema_name(current_user)
    context = build_business_context(request, current_user, db)

    try:
        raw_content = provider.generate(request=request, context=context)
        content = IntelligentAnalysisContent.model_validate(raw_content)
    except AppError:
        raise
    except ValidationError as exc:
        raise AppError(
            status_code=502,
            message="The analysis provider returned an invalid response",
            code="invalid_ai_response",
        ) from exc
    except Exception as exc:
        raise AppError(
            status_code=502,
            message="The analysis provider could not generate a response",
            code="ai_provider_error",
        ) from exc

    return {
        "analysis_id": uuid4(),
        "generated_at": datetime.now(timezone.utc),
        "provider": provider.name,
        "scope": request.scope,
        "period": request.period,
        "start_date": context["filters"]["start_date"],
        "end_date": context["filters"]["end_date"],
        "product_id": request.product_id,
        "analysis": content,
    }