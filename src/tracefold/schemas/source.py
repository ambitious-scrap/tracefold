from pydantic import Field, model_validator

from tracefold.schemas.common import HashValue, StrictModel


class SourceInput(StrictModel):
    input_ordinal: int = Field(ge=0)
    kind: str = Field(min_length=1)
    authority: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    text: str | None = None
    bytes_base64: str | None = None
    file_path: str | None = None
    message_id: str | None = None
    role: str | None = None

    @model_validator(mode="after")
    def exactly_one_payload(self) -> "SourceInput":
        if (self.text is None) == (self.bytes_base64 is None):
            raise ValueError("exactly one of text or bytes_base64 is required")
        return self


class SourceManifestEntry(StrictModel):
    source_id: str = Field(min_length=1)
    input_ordinal: int = Field(ge=0)
    kind: str = Field(min_length=1)
    authority: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    raw_byte_hash: HashValue
    byte_length: int = Field(ge=0)
    file_path: str | None = None
    message_id: str | None = None
    role: str | None = None


class SourceManifest(StrictModel):
    entries: list[SourceManifestEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_source_ids(self) -> "SourceManifest":
        ids = [entry.source_id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate source IDs")
        return self
