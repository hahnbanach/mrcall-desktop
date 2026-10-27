"""Private workflow records stored only in the profile SQLite database."""

from sqlalchemy import Column, Float, Integer, JSON, LargeBinary, String, Text

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Schema metadata owned exclusively by the workflow migration."""

    pass


class WorkflowDocument(Base):
    __tablename__ = "workflow_documents"

    id = Column(String, primary_key=True)
    uid = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    size = Column(Integer, nullable=False)
    sha256 = Column(String, nullable=False)
    state = Column(String, nullable=False)
    original = Column(LargeBinary, nullable=False)
    text = Column(Text, nullable=False, default="")
    limitations = Column(JSON, nullable=False, default=list)
    provenance = Column(JSON, nullable=False)
    duplicate_of = Column(String, nullable=True)
    created_at = Column(Float, nullable=False)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id = Column(String, primary_key=True)
    uid = Column(String, nullable=False, index=True)
    profile_dir = Column(String, nullable=False)
    workflow_id = Column(String, nullable=False)
    version = Column(String, nullable=False)
    status = Column(String, nullable=False)
    inputs = Column(JSON, nullable=False, default=dict)
    canonical_history = Column(JSON, nullable=False, default=list)
    references = Column(JSON, nullable=False, default=list)
    artifact_ids = Column(JSON, nullable=False, default=list)
    output = Column(JSON, nullable=True)
    bank_binding = Column(JSON, nullable=True)
    history_handle = Column(String, nullable=True)
    history_revision = Column(Integer, nullable=True)
    origin = Column(String, nullable=False)
    progress = Column(JSON, nullable=False, default=dict)
    error = Column(String, nullable=True)
    created_at = Column(Float, nullable=False)
    changed_at = Column(Float, nullable=False)
    expires_at = Column(Float, nullable=False)


class WorkflowArtifact(Base):
    __tablename__ = "workflow_artifacts"

    id = Column(String, primary_key=True)
    uid = Column(String, nullable=False, index=True)
    run_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    original = Column(LargeBinary, nullable=False)
    size = Column(Integer, nullable=False)
    sha256 = Column(String, nullable=False)
    provenance = Column(JSON, nullable=False)
    bank_binding = Column(JSON, nullable=True)
    created_at = Column(Float, nullable=False)


TABLES = tuple(model.__table__ for model in (WorkflowDocument, WorkflowRun, WorkflowArtifact))
