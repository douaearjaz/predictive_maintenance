"""Evidence-bearing contracts. Unknown fields are explicitly null."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from typing_extensions import Annotated

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Quote = Annotated[str, StringConstraints(min_length=1)]
FIELDS = ("component", "function", "failure_mode", "cause", "effect", "symptom",
          "detection_method", "maintenance_action")
RELATION_TYPES = Literal["CAUSES", "RESULTS_IN", "DETECTED_BY"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Chunk(StrictModel):
    document_id: Text
    document_name: Text
    page: int = Field(ge=1)
    chunk_id: Text
    text: Quote
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def offsets(self):
        if self.end - self.start != len(self.text):
            raise ValueError("Chunk offsets must match text length")
        return self


class Evidence(StrictModel):
    document_id: Text
    document_name: Text
    page: int = Field(ge=1)
    chunk_id: Text
    quote: Quote


class SupportedField(StrictModel):
    value: Text
    evidence: list[Evidence] = Field(min_length=1)


class RelationClaim(StrictModel):
    source: Text
    relation_type: RELATION_TYPES
    target: Text
    evidence: list[Evidence] = Field(min_length=1)
    operating_conditions: SupportedField | None


class TechnicalRecord(StrictModel):
    component: SupportedField | None
    function: SupportedField | None
    failure_mode: SupportedField | None
    cause: SupportedField | None
    effect: SupportedField | None
    symptom: SupportedField | None
    detection_method: SupportedField | None
    maintenance_action: SupportedField | None
    relations: list[RelationClaim]

    @model_validator(mode="after")
    def not_empty(self):
        if not any(getattr(self, name) for name in FIELDS):
            raise ValueError("Empty technical record")
        return self


class Extraction(StrictModel):
    records: list[TechnicalRecord]


class ReviewDecision(StrictModel):
    candidate_id: Text
    decision: Literal["approved", "rejected", "uncertain"]
    reviewer: Text
    note: Text
