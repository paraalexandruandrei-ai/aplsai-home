"""APLSAI role/permission model.

Pure permission logic only: no database access and no session mutation.
This keeps authorization rules testable and fail-closed.
"""

ROLE_ALIASES = {
    "staff": "admin",  # compatibility during migration
    "admin": "admin",
    "operator": "operator",
    "partner": "partner",
    "client": "client",
}

PERMISSIONS = {
    "admin": {
        "dashboard_full",
        "client_read_all",
        "client_update_operation",
        "property_create",
        "property_update",
        "scenario_manage",
        "feasibility_manage",
        "cashflow_manage",
        "portfolio_read",
        "portfolio_manage",
        "capacity_read",
        "capacity_manage",
        "opportunity_read",
        "opportunity_manage",
        "outreach_read",
        "outreach_manage",
        "outreach_approve",
        "matching_run",
        "proposal_create",
        "document_share",
        "audit_read",
        "staff_manage",
        "assigned_case_read",
        "assigned_document_read",
    },
    "operator": {
        "dashboard_full",
        "client_read_all",
        "client_update_operation",
        "property_create",
        "property_update",
        "scenario_manage",
        "feasibility_manage",
        "cashflow_manage",
        "portfolio_read",
        "capacity_read",
        "capacity_manage",
        "opportunity_read",
        "opportunity_manage",
        "outreach_read",
        "outreach_manage",
        "matching_run",
        "proposal_create",
        "document_share",
    },
    "partner": {
        "assigned_case_read",
        "assigned_document_read",
    },
    "client": {
        "own_profile_read",
    },
}


def effective_role(role):
    """Return canonical role or None for unknown roles."""
    if not isinstance(role, str):
        return None
    return ROLE_ALIASES.get(role.strip().lower())


def has_permission(role, permission):
    """Fail closed for unknown role or permission."""
    canonical = effective_role(role)
    if not canonical or not isinstance(permission, str):
        return False
    return permission in PERMISSIONS.get(canonical, set())


def require_assignment(role, permission):
    """Whether a permission also needs case/document assignment verification."""
    canonical = effective_role(role)
    return canonical == "partner" and permission in {
        "assigned_case_read",
        "assigned_document_read",
    }
