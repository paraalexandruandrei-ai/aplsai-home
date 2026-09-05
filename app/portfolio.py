import json
import math
from datetime import datetime, timezone

from flask import jsonify, request, session

from . import db
from .rbac import has_permission


CASE_KEYS = ("base", "prudente", "stress", "doppio_stress")
ITALIAN_MONTHS = ("", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno", "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre")


def init_portfolio(app, app_module):
    if app.extensions.get("aplsai_portfolio"):
        return

    class PortfolioSettings(db.Model):
        __tablename__ = "portfolio_settings"
        id = db.Column(db.Integer, primary_key=True)
        available_liquidity = db.Column(db.Float, nullable=True)
        minimum_liquidity_reserve = db.Column(db.Float, nullable=True)
        max_ap_exposure = db.Column(db.Float, nullable=True)
        max_concurrent_operations = db.Column(db.Integer, nullable=True)
        notes = db.Column(db.Text, nullable=False, default="")
        version = db.Column(db.Integer, nullable=False, default=1)
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)

    class PortfolioRevision(db.Model):
        __tablename__ = "portfolio_revision"
        id = db.Column(db.Integer, primary_key=True)
        settings_id = db.Column(db.Integer, db.ForeignKey("portfolio_settings.id"), nullable=False, index=True)
        version = db.Column(db.Integer, nullable=False)
        snapshot_json = db.Column(db.Text, nullable=False)
        changed_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        change_note = db.Column(db.String(255), nullable=False)
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)
        __table_args__ = (db.UniqueConstraint("settings_id", "version", name="uq_portfolio_revision_version"),)

        def to_dict(self):
            return {
                "id": self.id, "settings_id": self.settings_id, "version": self.version,
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
            fn(actor, action, "portfolio", object_id, detail)

    def absolute_month(value):
        year, month = (int(part) for part in value.split("-"))
        return year * 12 + month - 1

    def month_label(value):
        year, month_index = divmod(value, 12)
        return f"{ITALIAN_MONTHS[month_index + 1]} {year}"

    def settings_dict(settings):
        if not settings:
            return {
                "id": None, "available_liquidity": None,
                "minimum_liquidity_reserve": None, "max_ap_exposure": None,
                "max_concurrent_operations": None, "notes": "", "version": 0,
                "created_at": None, "updated_at": None,
            }
        return {
            "id": settings.id, "available_liquidity": settings.available_liquidity,
            "minimum_liquidity_reserve": settings.minimum_liquidity_reserve,
            "max_ap_exposure": settings.max_ap_exposure,
            "max_concurrent_operations": settings.max_concurrent_operations,
            "notes": settings.notes, "version": settings.version,
            "created_at": settings.created_at.isoformat() if settings.created_at else None,
            "updated_at": settings.updated_at.isoformat() if settings.updated_at else None,
        }

    def active_plan_data():
        cash_ext = app.extensions.get("aplsai_cashflow") or {}
        feasibility_ext = app.extensions.get("aplsai_feasibility") or {}
        Plan = cash_ext.get("CashFlowPlan")
        Movement = cash_ext.get("CashFlowMovement")
        Analysis = feasibility_ext.get("FeasibilityAnalysis")
        serializer = feasibility_ext.get("analysis_dict")
        if not all((Plan, Movement, Analysis, serializer)):
            return []
        plans = Plan.query.filter(Plan.archived_at.is_(None)).order_by(Plan.start_month.asc(), Plan.id.asc()).all()
        result = []
        for plan in plans:
            analysis = db.session.get(Analysis, plan.analysis_id)
            if not analysis or analysis.archived_at:
                continue
            view = serializer(analysis)
            movements = Movement.query.filter_by(plan_id=plan.id).order_by(Movement.month_index.asc(), Movement.id.asc()).all()
            result.append({"plan": plan, "analysis": analysis, "view": view, "movements": movements})
        return result

    def case_timeline(case_key, rows, settings):
        if not rows:
            return {
                "key": case_key, "label": case_key.replace("_", " ").title(), "months": [],
                "peak_cash_absorption": 0, "peak_ap_exposure": 0,
                "peak_month": None, "max_concurrent_operations": 0,
                "minimum_remaining_liquidity": settings.available_liquidity if settings else None,
                "maximum_uncovered_need": 0, "decision": "NESSUNA OPERAZIONE",
                "breaches": [],
            }

        simulations = []
        for row in rows:
            case = next(item for item in row["view"]["results"]["cases"] if item["key"] == case_key)
            start = absolute_month(row["plan"].start_month)
            schedule = {}
            end = start
            for movement in row["movements"]:
                offset = movement.month_index + (case["delay_months"] if movement.movement_type == "Entrata" else 0)
                when = start + offset
                end = max(end, when)
                if movement.movement_type == "Entrata":
                    amount = movement.amount_min * (1 - case["revenue_reduction_percent"] / 100)
                    signed = amount
                elif movement.movement_type == "Finanziamento ricevuto":
                    amount = movement.amount_min
                    signed = amount
                elif movement.movement_type == "Uscita":
                    multiplier = 1 if movement.category == "Acquisto immobile" else 1 + case["cost_increase_percent"] / 100
                    amount = movement.amount_max * multiplier
                    signed = -amount
                else:
                    amount = movement.amount_max
                    signed = -amount
                schedule[when] = schedule.get(when, 0) + signed
            simulations.append({
                "plan": row["plan"], "view": row["view"], "start": start, "end": end,
                "balance": row["plan"].opening_cash, "schedule": schedule,
            })

        first = min(item["start"] for item in simulations)
        last = max(item["end"] for item in simulations)
        timeline = []
        peak_absorption = peak_ap = maximum_uncovered = 0
        peak_month_value = first
        max_concurrent = 0
        minimum_remaining = settings.available_liquidity if settings and settings.available_liquidity is not None else None

        for current in range(first, last + 1):
            gross_absorption = ap_exposure = credit_used = uncovered = inflows = outflows = 0
            active = []
            for item in simulations:
                if not (item["start"] <= current <= item["end"]):
                    continue
                active.append({"id": item["plan"].id, "name": item["plan"].name, "property_ref": item["view"].get("property_ref")})
                movement = item["schedule"].get(current, 0)
                item["balance"] += movement
                if movement >= 0:
                    inflows += movement
                else:
                    outflows += -movement
                absorption = max(0, item["plan"].opening_cash - item["balance"])
                own_allocated = min(item["plan"].opening_cash, absorption)
                additional_need = max(0, absorption - item["plan"].opening_cash)
                plan_credit = min(item["plan"].additional_credit_limit, additional_need)
                plan_uncovered = max(0, additional_need - item["plan"].additional_credit_limit)
                gross_absorption += absorption
                credit_used += plan_credit
                uncovered += plan_uncovered
                ap_exposure += own_allocated + plan_uncovered

            remaining = None if not settings or settings.available_liquidity is None else settings.available_liquidity - ap_exposure
            if remaining is not None:
                minimum_remaining = remaining if minimum_remaining is None else min(minimum_remaining, remaining)
            if gross_absorption > peak_absorption:
                peak_absorption, peak_month_value = gross_absorption, current
            peak_ap = max(peak_ap, ap_exposure)
            maximum_uncovered = max(maximum_uncovered, uncovered)
            max_concurrent = max(max_concurrent, len(active))
            timeline.append({
                "month": month_label(current), "month_key": f"{current // 12:04d}-{current % 12 + 1:02d}",
                "inflows": round(inflows, 2), "outflows": round(outflows, 2),
                "gross_cash_absorption": round(gross_absorption, 2),
                "ap_exposure": round(ap_exposure, 2), "credit_used": round(credit_used, 2),
                "uncovered_need": round(uncovered, 2),
                "remaining_liquidity": round(remaining, 2) if remaining is not None else None,
                "concurrent_operations": len(active), "active_plans": active,
            })

        missing = []
        if not settings or settings.available_liquidity is None:
            missing.append("Liquidità AP disponibile")
        if not settings or settings.minimum_liquidity_reserve is None:
            missing.append("Riserva minima di liquidità")
        if not settings or settings.max_ap_exposure is None:
            missing.append("Tetto di esposizione AP")
        if not settings or settings.max_concurrent_operations is None:
            missing.append("Numero massimo di operazioni simultanee")

        breaches = []
        if not missing:
            if peak_ap > settings.max_ap_exposure:
                breaches.append("Tetto di esposizione AP superato")
            if minimum_remaining < settings.minimum_liquidity_reserve:
                breaches.append("Riserva minima di liquidità non rispettata")
            if max_concurrent > settings.max_concurrent_operations:
                breaches.append("Numero massimo di operazioni simultanee superato")
        incomplete_plans = [
            row["plan"].name for row in rows
            if (app.extensions["aplsai_cashflow"]["plan_dict"](row["plan"])["results"].get("reconciliation") or {}).get("status") != "riconciliato"
        ]
        if missing:
            decision = "DATI DA CONFIGURARE"
        elif breaches:
            decision = "BLOCCO / RIPIANIFICARE"
        elif incomplete_plans:
            decision = "ATTENZIONE / PIANI INCOMPLETI"
        else:
            decision = "SOSTENIBILE"
        label = next(item for item in rows[0]["view"]["results"]["cases"] if item["key"] == case_key)["label"]
        return {
            "key": case_key, "label": label, "months": timeline,
            "peak_cash_absorption": round(peak_absorption, 2),
            "peak_ap_exposure": round(peak_ap, 2), "peak_month": month_label(peak_month_value),
            "max_concurrent_operations": max_concurrent,
            "minimum_remaining_liquidity": round(minimum_remaining, 2) if minimum_remaining is not None else None,
            "maximum_uncovered_need": round(maximum_uncovered, 2),
            "decision": decision, "breaches": breaches, "missing_settings": missing,
            "incomplete_plans": incomplete_plans,
        }

    def calculations(settings):
        rows = active_plan_data()
        cases = [case_timeline(key, rows, settings) for key in CASE_KEYS]
        double_case = next(case for case in cases if case["key"] == "doppio_stress")
        plans = [{
            "id": row["plan"].id, "name": row["plan"].name,
            "property_ref": row["view"].get("property_ref"), "start_month": row["plan"].start_month,
            "opening_cash": row["plan"].opening_cash,
            "additional_credit_limit": row["plan"].additional_credit_limit,
            "status": row["plan"].status,
        } for row in rows]
        return {
            "decision": double_case["decision"], "active_plan_count": len(plans),
            "plans": plans, "cases": cases,
            "warnings": [
                "I limiti sono decisioni interne AP: il sistema non applica soglie predefinite.",
                "Calendari SAL, linee bancarie e incassi devono essere aggiornati con dati contrattuali reali.",
            ],
        }

    def portfolio_dict(include_history=False):
        settings = PortfolioSettings.query.order_by(PortfolioSettings.id.asc()).first()
        result = {"settings": settings_dict(settings), "results": calculations(settings)}
        if include_history:
            revisions = PortfolioRevision.query.filter_by(settings_id=settings.id).order_by(PortfolioRevision.version.desc()).limit(20).all() if settings else []
            result["revisions"] = [revision.to_dict() for revision in revisions]
        return result

    def numeric_or_none(data, field, integer=False):
        value = data.get(field)
        if value in (None, ""):
            return None
        try:
            parsed = int(value) if integer else float(value)
        except (TypeError, ValueError):
            raise ValueError("Limiti di portafoglio non validi.")
        if not math.isfinite(parsed) or parsed < 0 or (integer and parsed < 1):
            raise ValueError("I limiti devono essere valori positivi o zero, salvo il numero operazioni.")
        return parsed

    @app.get("/api/staff/portfolio")
    def portfolio_get():
        actor, denied = staff_user("portfolio_read")
        if denied:
            return denied
        return jsonify(portfolio=portfolio_dict(include_history=True))

    @app.patch("/api/staff/portfolio/settings")
    def portfolio_settings_update():
        actor, denied = staff_user("portfolio_manage")
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        settings = PortfolioSettings.query.order_by(PortfolioSettings.id.asc()).first()
        creating = settings is None
        if creating:
            settings = PortfolioSettings()
            db.session.add(settings)
        try:
            settings.available_liquidity = numeric_or_none(data, "available_liquidity")
            settings.minimum_liquidity_reserve = numeric_or_none(data, "minimum_liquidity_reserve")
            settings.max_ap_exposure = numeric_or_none(data, "max_ap_exposure")
            settings.max_concurrent_operations = numeric_or_none(data, "max_concurrent_operations", integer=True)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        settings.notes = app_module.clean_text(data.get("notes"), 4000)
        if not creating:
            settings.version += 1
        settings.updated_at = datetime.now(timezone.utc)
        db.session.flush()
        snapshot = settings_dict(settings)
        db.session.add(PortfolioRevision(
            settings_id=settings.id, version=settings.version,
            snapshot_json=json.dumps(snapshot, ensure_ascii=False),
            changed_by_user_id=actor.id,
            change_note=app_module.clean_text(data.get("change_note") or ("Configurazione iniziale" if creating else "Limiti aggiornati"), 255),
        ))
        audit(actor, "portfolio_settings_create" if creating else "portfolio_settings_update", settings.id)
        db.session.commit()
        return jsonify(portfolio=portfolio_dict(include_history=True))

    app.extensions["aplsai_portfolio"] = {
        "PortfolioSettings": PortfolioSettings, "PortfolioRevision": PortfolioRevision,
        "portfolio_dict": portfolio_dict,
    }
