import json
import math
from datetime import date, datetime, timezone

from flask import jsonify, request, session

from . import db
from .rbac import has_permission


RELIABILITY_LEVELS = {"Da verificare", "Dichiarato", "Documentato", "Verificato"}
ALLOCATION_STATUSES = {"Pianificato", "Confermato", "In corso", "Completato", "Sospeso"}


def init_capacity(app, app_module):
    if app.extensions.get("aplsai_capacity"):
        return

    class OperationalTeam(db.Model):
        __tablename__ = "operational_team"
        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(160), nullable=False)
        company = db.Column(db.String(160), nullable=False)
        specialty = db.Column(db.String(255), nullable=False, default="")
        responsible = db.Column(db.String(160), nullable=False, default="")
        monthly_capacity_days = db.Column(db.Float, nullable=True)
        source = db.Column(db.String(160), nullable=False, default="Da verificare")
        reliability = db.Column(db.String(40), nullable=False, default="Da verificare")
        notes = db.Column(db.Text, nullable=False, default="")
        version = db.Column(db.Integer, nullable=False, default=1)
        archived_at = db.Column(db.DateTime(timezone=True))
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)

    class CapacityAllocation(db.Model):
        __tablename__ = "capacity_allocation"
        id = db.Column(db.Integer, primary_key=True)
        team_id = db.Column(db.Integer, db.ForeignKey("operational_team.id"), nullable=False, index=True)
        plan_id = db.Column(db.Integer, db.ForeignKey("cash_flow_plan.id"), nullable=False, index=True)
        month = db.Column(db.String(7), nullable=False, index=True)
        phase = db.Column(db.String(160), nullable=False)
        required_worker_days = db.Column(db.Float, nullable=False)
        status = db.Column(db.String(40), nullable=False, default="Pianificato")
        external_dependency = db.Column(db.String(500), nullable=False, default="")
        source = db.Column(db.String(160), nullable=False, default="Da verificare")
        reliability = db.Column(db.String(40), nullable=False, default="Da verificare")
        notes = db.Column(db.Text, nullable=False, default="")
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)

    class TeamRevision(db.Model):
        __tablename__ = "operational_team_revision"
        id = db.Column(db.Integer, primary_key=True)
        team_id = db.Column(db.Integer, db.ForeignKey("operational_team.id"), nullable=False, index=True)
        version = db.Column(db.Integer, nullable=False)
        snapshot_json = db.Column(db.Text, nullable=False)
        changed_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        change_note = db.Column(db.String(255), nullable=False)
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)
        __table_args__ = (db.UniqueConstraint("team_id", "version", name="uq_operational_team_revision_version"),)

        def to_dict(self):
            return {
                "id": self.id, "team_id": self.team_id, "version": self.version,
                "snapshot": json.loads(self.snapshot_json), "changed_by_user_id": self.changed_by_user_id,
                "change_note": self.change_note,
                "created_at": self.created_at.isoformat() if self.created_at else None,
            }

    with app.app_context():
        db.create_all()

    def staff_user(permission):
        uid = session.get("uid")
        actor = db.session.get(app_module.User, uid) if uid else None
        if not actor:
            return None, (jsonify(error="Non autenticato."), 401)
        if getattr(actor, "active", True) is False:
            session.clear()
            return None, (jsonify(error="Account disattivato."), 401)
        if not has_permission(actor.role, permission):
            return None, (jsonify(error="Permesso insufficiente."), 403)
        return actor, None

    def audit(actor, action, object_id, detail=""):
        fn = (app.extensions.get("aplsai_operations") or {}).get("audit")
        if fn:
            fn(actor, action, "capacity", object_id, detail)

    def validate_month(value):
        value = app_module.clean_text(value, 7)
        try:
            date.fromisoformat(value + "-01")
        except ValueError:
            raise ValueError("Mese di pianificazione non valido.")
        return value

    def team_dict(team, include_history=False):
        result = {
            "id": team.id, "name": team.name, "company": team.company,
            "specialty": team.specialty, "responsible": team.responsible,
            "monthly_capacity_days": team.monthly_capacity_days,
            "source": team.source, "reliability": team.reliability, "notes": team.notes,
            "version": team.version,
            "archived_at": team.archived_at.isoformat() if team.archived_at else None,
            "created_at": team.created_at.isoformat() if team.created_at else None,
            "updated_at": team.updated_at.isoformat() if team.updated_at else None,
        }
        if include_history:
            rows = TeamRevision.query.filter_by(team_id=team.id).order_by(TeamRevision.version.desc()).limit(20).all()
            result["revisions"] = [row.to_dict() for row in rows]
        return result

    def allocation_dict(allocation):
        cash_ext = app.extensions.get("aplsai_cashflow") or {}
        Plan = cash_ext.get("CashFlowPlan")
        serializer = cash_ext.get("plan_dict")
        plan = db.session.get(Plan, allocation.plan_id) if Plan else None
        plan_data = serializer(plan) if plan and serializer else {}
        team = db.session.get(OperationalTeam, allocation.team_id)
        return {
            "id": allocation.id, "team_id": allocation.team_id,
            "team_name": team.name if team else None, "plan_id": allocation.plan_id,
            "plan_name": plan.name if plan else None, "property_ref": plan_data.get("property_ref"),
            "month": allocation.month, "phase": allocation.phase,
            "required_worker_days": allocation.required_worker_days, "status": allocation.status,
            "external_dependency": allocation.external_dependency, "source": allocation.source,
            "reliability": allocation.reliability, "notes": allocation.notes,
            "created_at": allocation.created_at.isoformat() if allocation.created_at else None,
            "updated_at": allocation.updated_at.isoformat() if allocation.updated_at else None,
        }

    def capacity_results():
        teams = OperationalTeam.query.filter(OperationalTeam.archived_at.is_(None)).order_by(OperationalTeam.name.asc()).all()
        allocations = CapacityAllocation.query.join(OperationalTeam, CapacityAllocation.team_id == OperationalTeam.id).filter(
            OperationalTeam.archived_at.is_(None), CapacityAllocation.status != "Sospeso"
        ).order_by(CapacityAllocation.month.asc(), CapacityAllocation.team_id.asc()).all()
        grouped = {}
        for allocation in allocations:
            grouped.setdefault((allocation.team_id, allocation.month), []).append(allocation)
        months = []
        overloaded = 0
        unconfigured = 0
        for (team_id, month), rows in sorted(grouped.items(), key=lambda item: (item[0][1], item[0][0])):
            team = db.session.get(OperationalTeam, team_id)
            used = sum(row.required_worker_days for row in rows)
            capacity = team.monthly_capacity_days
            if capacity is None or capacity <= 0:
                status, utilization, remaining = "DA CONFIGURARE", None, None
                unconfigured += 1
            else:
                utilization = used / capacity * 100
                remaining = capacity - used
                if used > capacity:
                    status = "SOVRACCARICO"
                    overloaded += 1
                elif abs(used - capacity) < 0.01:
                    status = "SATURO"
                else:
                    status = "DISPONIBILE"
            months.append({
                "team_id": team.id, "team_name": team.name, "company": team.company,
                "month": month, "capacity_days": capacity, "used_days": round(used, 2),
                "remaining_days": round(remaining, 2) if remaining is not None else None,
                "utilization_percent": round(utilization, 2) if utilization is not None else None,
                "status": status, "allocations": [allocation_dict(row) for row in rows],
            })

        cash_ext = app.extensions.get("aplsai_cashflow") or {}
        Plan = cash_ext.get("CashFlowPlan")
        active_plans = Plan.query.filter(Plan.archived_at.is_(None)).order_by(Plan.id.asc()).all() if Plan else []
        assigned_ids = {allocation.plan_id for allocation in allocations}
        missing_plans = [{"id": plan.id, "name": plan.name} for plan in active_plans if plan.id not in assigned_ids]
        if not teams:
            decision = "SQUADRE DA CONFIGURARE"
        elif overloaded:
            decision = "SOVRACCARICO / RIPIANIFICARE"
        elif unconfigured:
            decision = "CAPACITÀ DA COMPLETARE"
        elif missing_plans:
            decision = "PIANIFICAZIONE INCOMPLETA"
        else:
            decision = "CAPACITÀ DISPONIBILE"
        return {
            "decision": decision, "active_team_count": len(teams),
            "active_allocation_count": len(allocations), "overloaded_month_count": overloaded,
            "unconfigured_month_count": unconfigured, "unassigned_plans": missing_plans,
            "months": months,
            "warnings": [
                "La capacità mensile deve derivare dall’organico realmente disponibile e dagli accordi con i partner.",
                "Dipendenze esterne, sicurezza, autorizzazioni e tempi tecnici devono essere confermati prima dell’avvio.",
            ],
        }

    def capacity_dict():
        teams = OperationalTeam.query.order_by(OperationalTeam.name.asc()).all()
        allocations = CapacityAllocation.query.order_by(CapacityAllocation.month.asc(), CapacityAllocation.id.asc()).all()
        return {
            "teams": [team_dict(team) for team in teams],
            "allocations": [allocation_dict(row) for row in allocations],
            "results": capacity_results(),
        }

    def apply_team(team, data):
        if "name" in data:
            team.name = app_module.clean_text(data.get("name"), 160)
        if "company" in data:
            team.company = app_module.clean_text(data.get("company"), 160)
        if "specialty" in data:
            team.specialty = app_module.clean_text(data.get("specialty"), 255)
        if "responsible" in data:
            team.responsible = app_module.clean_text(data.get("responsible"), 160)
        if "source" in data:
            team.source = app_module.clean_text(data.get("source"), 160)
        if "reliability" in data:
            team.reliability = app_module.clean_text(data.get("reliability"), 40)
        if "notes" in data:
            team.notes = app_module.clean_text(data.get("notes"), 4000)
        if "monthly_capacity_days" in data:
            value = data.get("monthly_capacity_days")
            if value in (None, ""):
                team.monthly_capacity_days = None
            else:
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    raise ValueError("Capacità mensile non valida.")
                if not math.isfinite(value) or value <= 0:
                    raise ValueError("La capacità mensile deve essere maggiore di zero.")
                team.monthly_capacity_days = value
        if not team.name or not team.company or team.reliability not in RELIABILITY_LEVELS:
            raise ValueError("Nome, società o affidabilità della squadra non validi.")

    def record_team_revision(team, actor, note):
        db.session.add(TeamRevision(
            team_id=team.id, version=team.version,
            snapshot_json=json.dumps(team_dict(team), ensure_ascii=False),
            changed_by_user_id=actor.id,
            change_note=app_module.clean_text(note or "Squadra aggiornata", 255),
        ))

    @app.get("/api/staff/capacity")
    def capacity_get():
        actor, denied = staff_user("capacity_read")
        if denied:
            return denied
        return jsonify(capacity=capacity_dict())

    @app.get("/api/staff/capacity/teams/<int:team_id>")
    def team_get(team_id):
        actor, denied = staff_user("capacity_read")
        if denied:
            return denied
        team = db.session.get(OperationalTeam, team_id)
        if not team:
            return jsonify(error="Squadra non trovata."), 404
        return jsonify(team=team_dict(team, include_history=True))

    @app.post("/api/staff/capacity/teams")
    def team_create():
        actor, denied = staff_user("capacity_manage")
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        team = OperationalTeam(name="", company="", specialty="", responsible="", source="Da verificare", reliability="Da verificare", notes="")
        try:
            apply_team(team, data)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        db.session.add(team)
        db.session.flush()
        record_team_revision(team, actor, "Creazione squadra")
        audit(actor, "capacity_team_create", team.id)
        db.session.commit()
        return jsonify(team=team_dict(team, include_history=True), capacity=capacity_dict()), 201

    @app.patch("/api/staff/capacity/teams/<int:team_id>")
    def team_update(team_id):
        actor, denied = staff_user("capacity_manage")
        if denied:
            return denied
        team = db.session.get(OperationalTeam, team_id)
        if not team:
            return jsonify(error="Squadra non trovata."), 404
        data = request.get_json(silent=True) or {}
        try:
            apply_team(team, data)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        team.version += 1
        team.updated_at = datetime.now(timezone.utc)
        record_team_revision(team, actor, data.get("change_note") or "Squadra aggiornata")
        audit(actor, "capacity_team_update", team.id)
        db.session.commit()
        return jsonify(team=team_dict(team, include_history=True), capacity=capacity_dict())

    @app.patch("/api/staff/capacity/teams/<int:team_id>/archive")
    def team_archive(team_id):
        actor, denied = staff_user("capacity_manage")
        if denied:
            return denied
        team = db.session.get(OperationalTeam, team_id)
        if not team:
            return jsonify(error="Squadra non trovata."), 404
        data = request.get_json(silent=True) or {}
        if not isinstance(data.get("archived"), bool):
            return jsonify(error="Stato archivio non valido."), 400
        team.archived_at = datetime.now(timezone.utc) if data["archived"] else None
        team.version += 1
        team.updated_at = datetime.now(timezone.utc)
        record_team_revision(team, actor, "Squadra archiviata" if data["archived"] else "Squadra ripristinata")
        audit(actor, "capacity_team_archive" if data["archived"] else "capacity_team_restore", team.id)
        db.session.commit()
        return jsonify(team=team_dict(team, include_history=True), capacity=capacity_dict())

    def allocation_payload(data):
        cash_ext = app.extensions.get("aplsai_cashflow") or {}
        Plan = cash_ext.get("CashFlowPlan")
        try:
            team_id = int(data.get("team_id"))
            plan_id = int(data.get("plan_id"))
            required = float(data.get("required_worker_days"))
        except (TypeError, ValueError):
            raise ValueError("Squadra, operazione o giornate-uomo non valide.")
        team = db.session.get(OperationalTeam, team_id)
        plan = db.session.get(Plan, plan_id) if Plan else None
        if not team or team.archived_at or not plan or plan.archived_at:
            raise LookupError("Squadra o piano di cassa non disponibile.")
        if not math.isfinite(required) or required <= 0:
            raise ValueError("Le giornate-uomo devono essere maggiori di zero.")
        phase = app_module.clean_text(data.get("phase"), 160)
        status = app_module.clean_text(data.get("status") or "Pianificato", 40)
        reliability = app_module.clean_text(data.get("reliability") or "Da verificare", 40)
        if not phase or status not in ALLOCATION_STATUSES or reliability not in RELIABILITY_LEVELS:
            raise ValueError("Fase, stato o affidabilità non validi.")
        return {
            "team_id": team_id, "plan_id": plan_id, "month": validate_month(data.get("month")),
            "phase": phase, "required_worker_days": required, "status": status,
            "external_dependency": app_module.clean_text(data.get("external_dependency"), 500),
            "source": app_module.clean_text(data.get("source") or "Da verificare", 160),
            "reliability": reliability, "notes": app_module.clean_text(data.get("notes"), 4000),
        }

    @app.post("/api/staff/capacity/allocations")
    def allocation_create():
        actor, denied = staff_user("capacity_manage")
        if denied:
            return denied
        try:
            values = allocation_payload(request.get_json(silent=True) or {})
        except LookupError as exc:
            return jsonify(error=str(exc)), 404
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        allocation = CapacityAllocation(**values)
        db.session.add(allocation)
        db.session.flush()
        audit(actor, "capacity_allocation_create", allocation.id, f"team={allocation.team_id};plan={allocation.plan_id}")
        db.session.commit()
        return jsonify(allocation=allocation_dict(allocation), capacity=capacity_dict()), 201

    @app.patch("/api/staff/capacity/allocations/<int:allocation_id>")
    def allocation_update(allocation_id):
        actor, denied = staff_user("capacity_manage")
        if denied:
            return denied
        allocation = db.session.get(CapacityAllocation, allocation_id)
        if not allocation:
            return jsonify(error="Assegnazione non trovata."), 404
        data = request.get_json(silent=True) or {}
        merged = allocation_dict(allocation)
        merged.update(data)
        try:
            values = allocation_payload(merged)
        except LookupError as exc:
            return jsonify(error=str(exc)), 404
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        for field, value in values.items():
            setattr(allocation, field, value)
        allocation.updated_at = datetime.now(timezone.utc)
        audit(actor, "capacity_allocation_update", allocation.id)
        db.session.commit()
        return jsonify(allocation=allocation_dict(allocation), capacity=capacity_dict())

    @app.delete("/api/staff/capacity/allocations/<int:allocation_id>")
    def allocation_delete(allocation_id):
        actor, denied = staff_user("capacity_manage")
        if denied:
            return denied
        allocation = db.session.get(CapacityAllocation, allocation_id)
        if not allocation:
            return jsonify(error="Assegnazione non trovata."), 404
        db.session.delete(allocation)
        audit(actor, "capacity_allocation_delete", allocation_id)
        db.session.commit()
        return jsonify(capacity=capacity_dict())

    app.extensions["aplsai_capacity"] = {
        "OperationalTeam": OperationalTeam, "CapacityAllocation": CapacityAllocation,
        "TeamRevision": TeamRevision, "team_dict": team_dict,
        "allocation_dict": allocation_dict, "capacity_dict": capacity_dict,
    }
