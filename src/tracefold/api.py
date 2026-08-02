from fastapi import FastAPI, HTTPException

from tracefold import SCHEMA_VERSION, __version__
from tracefold.cprgc import CPRGCExecutionError
from tracefold.schemas.common import StrictModel
from tracefold.schemas.phase7r import PublicCompressionRequest, PublicCompressionResponse
from tracefold.service import compress_public
from tracefold.sources import SourceNormalizationError
from tracefold.tokenizers import TokenizerConfigurationError

app = FastAPI(title="TraceFold", version=__version__)


class HealthResponse(StrictModel):
    status: str
    service_version: str


class VersionResponse(StrictModel):
    package_version: str
    schema_version: str


@app.get("/healthz", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service_version=__version__)


@app.get("/version", response_model=VersionResponse)
def version() -> VersionResponse:
    return VersionResponse(package_version=__version__, schema_version=SCHEMA_VERSION)


@app.post("/v1/compress", response_model=PublicCompressionResponse)
def compress(request: PublicCompressionRequest) -> PublicCompressionResponse:
    try:
        return compress_public(request)
    except (TokenizerConfigurationError, SourceNormalizationError, CPRGCExecutionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
