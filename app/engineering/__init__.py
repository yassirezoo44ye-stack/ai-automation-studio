"""
Engineering Control Plane — core module.

Flow = secure AI Engineering Control Plane.
Claude = reasoning/decision engine.
Flow = identity + permissions + tools + execution + evidence + approvals + verification.

Entry points:
  app.engineering.missions   — MissionService (create, run, recover)
  app.engineering.tools.gateway — EngineeringToolGateway (typed, allowlisted calls)
  app.engineering.evidence   — EvidenceStore (every external action produces Evidence)
  app.engineering.approvals  — ApprovalService (persistent approval gates)
  app.engineering.verify     — ProductionVerifier (SHA + health + smoke)
  app.engineering.schema     — init_engineering_schema() (DB tables + RLS)
"""
from app.engineering.schema import init_engineering_schema

__all__ = ["init_engineering_schema"]
