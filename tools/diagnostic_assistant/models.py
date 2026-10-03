"""Evidence-only data structures. No OAS imports or runtime state."""
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Reference:
    path: str
    start: int
    end: int  # exclusive byte offset
    first_line: int | None = None
    last_line: int | None = None

    def label(self):
        if self.first_line is not None:
            return f"{self.path}:L{self.first_line}-L{self.last_line} (bytes {self.start}-{self.end}, end exclusive)"
        return f"{self.path}:bytes {self.start}-{self.end} (end exclusive)"


@dataclass
class Line:
    text: str
    ref: Reference


@dataclass
class Event:
    kind: str
    ts: datetime | None
    ref: Reference
    fields: dict = field(default_factory=dict)
    status: str = "confirmed"
    source: str | None = None
    source_line: int | None = None
    level: str | None = None


@dataclass
class Issue:
    code: str
    detail: str
    ref: Reference | None = None


@dataclass
class EvidenceFile:
    path: str
    instance_candidate: str | None
    package: str | None
    size: int
    read_bytes: int
    read_start: int
    lines: list[Line] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    image_refs: list[str] = field(default_factory=list)


@dataclass
class Answer:
    status: str
    text: str
    refs: list[Reference] = field(default_factory=list)
