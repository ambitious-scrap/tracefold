from fastapi import FastAPI, status
from fastapi.responses import JSONResponse

from tracefold import SCHEMA_VERSION, __version__
from tracefold.schemas.api import CompressionRequest
from tracefold.schemas.common import StrictModel

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


@app.post("/v1/compress")
def compress(_: CompressionRequest) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content={
            "code": "PHASE_1_NOT_IMPLEMENTED",
            "message": "compression is not implemented in Phase 1",
            "run_id": None,
        },
    )
