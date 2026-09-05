import json
import math
from datetime import date, datetime, timezone

from flask import jsonify, request, session

from . import db
from .rbac import has_permission


PLAN_STATUSES = {"Bozza", "Da verificare", "Validato", "Approvato"}
MOVEMENT_TYPES = {"Entrata", "Uscita", "Finanziamento ricevuto", "Rimborso finanziamento"}
MOVEMENT_CATEGORIES = {
    "Acquisto immobile", "Lavori", "Tecnici e pratiche", "Imposte, notaio e agenzia",
    "Costi finanziari", "Costi di mantenimento", "Vendita immobile", "Altri ricavi",
    "Fondo imprevisti", "Altro",
}
RELIABILITY_LEVELS = {"Da verificare", "Dichiarato", "Documentato", "Verificato"}
ITALIAN_MONTHS = ("", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno", "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre")


def init_cashflow(app, app_module):
    if app.extensions.get("aplsai_cashflow"):
        return

    class CashFlowPlan(db.Model):
        __tablename__ = "cash_flow_plan"
        id = db.Column(db.Integer, primary_key=True)
        analysis_id = db.Column(db.Integer, db.ForeignKey("feasibility_analysis.id"), nullable=False, index=True)
        name = db.Column(db.String(160), nullable=False)
        start_month = db.Column(db.String(7), nullable=False)
        opening_cash = db.Column(db.Float, nullable=False, default=0)
        additional_credit_limit = db.Column(db.Float, nullable=False, default=0)
        status = db.Column(db.String(40), nullable=False, default="Da verificare")
        notes = db.Column(db.Text, nullable=False, default="")
        version = db.Column(db.Integer, nullable=False, default=1)
        archived_at = db.Column(db.DateTime(timezone=True))
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)

    class CashFlowMovement(db.Model):
        __tablename__ = "cash_flow_movement"
        id = db.Column(db.Integer, primary_key=True)
        plan_id = db.Column(db.Integer, db.ForeignKey("cash_flow_plan.id"), nullable=False, index=True)
        month_index = db.Column(db.Integer, nullable=False)
        movement_type = db.Column(db.String(40), nullable=False)
        category = db.Column(db.String(100), nullable=False)
        description = db.Column(db.String(500), nullable=False)
        amount_min = db.Column(db.Float, nullable=False)
        amount_max = db.Column(db.Float, nullable=False)
        source = db.Column(db.String(160), nullable=False, default="Da verificare")
        reliability = db.Column(db.String(40), nullable=False, default="Da verificare")
        system_generated = db.Column(db.Boolean, nullable=False, default=False)
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)

        def to_dict(self):
            return {
                "id": self.id, "plan_id": self.plan_id, "month_index": self.month_index,
                "movement_type": self.movement_type, "category": self.category,
                "description": self.description, "amount_min": self.amount_min,
                "amount_max": self.amount_max, "source": self.source,
                "reliability": self.reliability, "system_generated": self.system_generated,
                "created_at": self.created_at.isoformat() if self.created_at else None,
            }

    class CashFlowRevision(db.Model):
        __tablename__ = "cash_flow_revision"
        id = db.Column(db.Integer, primary_key=True)
        plan_id = db.Column(db.Integer, db.ForeignKey("cash_flow_plan.id"), nullable=False, index=True)
        version = db.Column(db.Integer, nullable=False)
        snapshot_json = db.Column(db.Text, nullable=False)
        changed_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        change_note = db.Column(db.String(255), nullable=False)
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)
        __table_args__ = (db.UniqueConstraint("plan_id", "version", name="uq_cash_flow_revision_version"),)

        def to_dict(self):
            return {
                "id": self.id, "plan_id": self.plan_id, "version": self.version,
                "snapshot": json.loads(self.snapshot_json), "changed_by_user_id": self.changed_by_user_id,
                "change_note": self.change_note,
                "created_at": self.created_at.isoformat() if self.created_at else None,
            }

    with app.app_context():
        db.create_all()

    def staff_user():
        uid = session.get("uid")
        actor = db.session.get(app_module.User, uid) if uid else None
        if not actor:
            return None, (jsonify(error="Non autenticato."), 401)
        if getattr(actor, "active", True) is False:
            session.clear()
            return None, (jsonify(error="Account disattivato."), 401)
        if not has_permission(actor.role, "cashflow_manage"):
            return None, (jsonify(error="Permesso insufficiente."), 403)
        return actor, None

    def audit(actor, action, object_id, detail=""):
        fn = (app.extensions.get("aplsai_operations") or {}).get("audit")
        if fn:
            fn(actor, action, "cashflow", object_id, detail)

    def analysis_data(plan):
        ext = app.extensions.get("aplsai_feasibility") or {}
        Analysis = ext.get("FeasibilityAnalysis")
        serializer = ext.get("analysis_dict")
        analysis = db.session.get(Analysis, plan.analysis_id) if Analysis else None
        return analysis, serializer(analysis) if analysis and serializer else None

    def movements_for(plan_id):
        return CashFlowMovement.query.filter_by(plan_id=plan_id).order_by(
            CashFlowMovement.month_index.asc(), CashFlowMovement.id.asc()
        ).all()

    def month_label(start_month, offset):
        year, month = (int(value) for value in start_month.split("-"))
        absolute = year * 12 + month - 1 + offset
        target_year, target_month = divmod(absolute, 12)
        return f"{ITALIAN_MONTHS[target_month + 1]} {target_year}"

    def calculations(plan, movements=None):
        movements = movements if movements is not None else movements_for(plan.id)
        analysis, data = analysis_data(plan)
        if not analysis or not data:
            return {"decision": "DATI INCOMPLETI", "months": [], "stress_cases": [], "warnings": ["Analisi di fattibilità non disponibile."]}
        cases = data["results"]["cases"]
        horizon = max([analysis.base_duration_months] + [m.month_index for m in movements] + [case["duration_months"] for case in cases])

        balance_min = balance_max = plan.opening_cash
        monthly = []
        for index in range(horizon + 1):
            rows = [m for m in movements if m.month_index == index]
            inflow_min = sum(m.amount_min for m in rows if m.movement_type in {"Entrata", "Finanziamento ricevuto"})
            inflow_max = sum(m.amount_max for m in rows if m.movement_type in {"Entrata", "Finanziamento ricevuto"})
            outflow_min = sum(m.amount_min for m in rows if m.movement_type in {"Uscita", "Rimborso finanziamento"})
            outflow_max = sum(m.amount_max for m in rows if m.movement_type in {"Uscita", "Rimborso finanziamento"})
            balance_min += inflow_min - outflow_max
            balance_max += inflow_max - outflow_min
            monthly.append({
                "month_index": index, "month": month_label(plan.start_month, index),
                "inflow_min": round(inflow_min, 2), "inflow_max": round(inflow_max, 2),
                "outflow_min": round(outflow_min, 2), "outflow_max": round(outflow_max, 2),
                "balance_min": round(balance_min, 2), "balance_max": round(balance_max, 2),
            })

        stress_cases = []
        for case in cases:
            balance = plan.opening_cash
            minimum = balance
            minimum_month = 0
            last_month = max(horizon, analysis.base_duration_months + case["delay_months"])
            for index in range(last_month + 1):
                for movement in movements:
                    effective_month = movement.month_index
                    if movement.movement_type == "Entrata":
                        effective_month += case["delay_months"]
                    if effective_month != index:
                        continue
                    if movement.movement_type == "Entrata":
                        balance += movement.amount_min * (1 - case["revenue_reduction_percent"] / 100)
                    elif movement.movement_type == "Finanziamento ricevuto":
                        balance += movement.amount_min
                    elif movement.movement_type == "Uscita":
                        multiplier = 1 if movement.category == "Acquisto immobile" else 1 + case["cost_increase_percent"] / 100
                        balance -= movement.amount_max * multiplier
                    else:
                        balance -= movement.amount_max
                if balance < minimum:
                    minimum, minimum_month = balance, index
            need = max(0, -minimum)
            stress_cases.append({
                "key": case["key"], "label": case["label"],
                "minimum_balance": round(minimum, 2), "peak_month_index": minimum_month,
                "peak_month": month_label(plan.start_month, minimum_month),
                "additional_funding_need": round(need, 2),
                "credit_limit": plan.additional_credit_limit,
                "coverage_status": "coperto" if need <= plan.additional_credit_limit else "scoperto",
                "closing_balance": round(balance, 2),
            })

        expected_items = float(data["results"].get("scenario_item_cost_max") or 0)
        planned_items = sum(
            movement.amount_max for movement in movements
            if movement.movement_type == "Uscita" and movement.category != "Acquisto immobile"
        )
        remaining = round(expected_items - planned_items, 2)
        reconciliation = {
            "scenario_cost_max": round(expected_items, 2),
            "planned_cost_max": round(planned_items, 2),
            "remaining_to_schedule": max(0, remaining),
            "over_scheduled": max(0, -remaining),
            "status": "riconciliato" if abs(remaining) < 0.01 else "da_completare",
        }
        double_case = next(case for case in stress_cases if case["key"] == "doppio_stress")
        if reconciliation["status"] != "riconciliato":
            decision = "PIANO DA COMPLETARE"
        elif double_case["coverage_status"] == "scoperto":
            decision = "COPERTURA INSUFFICIENTE"
        else:
            decision = "COPERTURA ADEGUATA"
        return {
            "decision": decision, "months": monthly, "stress_cases": stress_cases,
            "reconciliation": reconciliation,
            "warnings": [
                "Le uscite dei lavori devono essere distribuite secondo SAL e scadenze contrattuali reali.",
                "Il piano non rappresenta una promessa di erogazione bancaria.",
            ],
        }

    def plan_dict(plan, include_history=False):
        analysis, data = analysis_data(plan)
        movements = movements_for(plan.id)
        result = {
            "id": plan.id, "analysis_id": plan.analysis_id,
            "analysis_name": analysis.name if analysis else None,
            "property_ref": data.get("property_ref") if data else None,
            "name": plan.name, "start_month": plan.start_month,
            "opening_cash": plan.opening_cash,
            "additional_credit_limit": plan.additional_credit_limit,
            "status": plan.status, "notes": plan.notes, "version": plan.version,
            "archived_at": plan.archived_at.isoformat() if plan.archived_at else None,
            "created_at": plan.created_at.isoformat() if plan.created_at else None,
            "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
            "movements": [movement.to_dict() for movement in movements],
            "results": calculations(plan, movements),
        }
        if include_history:
            history = CashFlowRevision.query.filter_by(plan_id=plan.id).order_by(CashFlowRevision.version.desc()).limit(20).all()
            result["revisions"] = [row.to_dict() for row in history]
        return result

    def record_revision(plan, actor, note):
        db.session.add(CashFlowRevision(
            plan_id=plan.id, version=plan.version,
            snapshot_json=json.dumps(plan_dict(plan), ensure_ascii=False),
            changed_by_user_id=actor.id,
            change_note=app_module.clean_text(note or "Piano di cassa aggiornato", 255),
        ))

    def apply_plan_payload(plan, data):
        if "name" in data:
            plan.name = app_module.clean_text(data.get("name"), 160)
        if "start_month" in data:
            value = app_module.clean_text(data.get("start_month"), 7)
            try:
                date.fromisoformat(value + "-01")
            except ValueError:
                raise ValueError("Mese iniziale non valido.")
            plan.start_month = value
        if "status" in data:
            plan.status = app_module.clean_text(data.get("status"), 40)
        if "notes" in data:
            plan.notes = app_module.clean_text(data.get("notes"), 4000)
        for field in ("opening_cash", "additional_credit_limit"):
            if field in data:
                try:
                    value = float(data[field])
                except (TypeError, ValueError):
                    raise ValueError("Valori di cassa non validi.")
                if not math.isfinite(value) or value < 0:
                    raise ValueError("I valori di cassa non possono essere negativi.")
                setattr(plan, field, value)
        if not plan.name or plan.status not in PLAN_STATUSES:
            raise ValueError("Nome o stato del piano non valido.")

    def create_anchor(plan, month_index, movement_type, category, description, amount):
        if amount <= 0:
            return
        db.session.add(CashFlowMovement(
            plan_id=plan.id, month_index=month_index, movement_type=movement_type,
            category=category, description=description, amount_min=amount, amount_max=amount,
            source="Analisi di fattibilità", reliability="Documentato", system_generated=True,
        ))

    @app.get("/api/staff/cashflow")
    def cashflow_list():
        actor, denied = staff_user()
        if denied:
            return denied
        query = CashFlowPlan.query
        if request.args.get("include_archived") != "1":
            query = query.filter(CashFlowPlan.archived_at.is_(None))
        rows = query.order_by(CashFlowPlan.updated_at.desc()).all()
        return jsonify(plans=[plan_dict(row) for row in rows])

    @app.get("/api/staff/cashflow/<int:plan_id>")
    def cashflow_detail(plan_id):
        actor, denied = staff_user()
        if denied:
            return denied
        plan = db.session.get(CashFlowPlan, plan_id)
        if not plan:
            return jsonify(error="Piano di cassa non trovato."), 404
        return jsonify(plan=plan_dict(plan, include_history=True))

    @app.post("/api/staff/cashflow")
    def cashflow_create():
        actor, denied = staff_user()
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        ext = app.extensions.get("aplsai_feasibility") or {}
        Analysis = ext.get("FeasibilityAnalysis")
        serializer = ext.get("analysis_dict")
        try:
            analysis_id = int(data.get("analysis_id"))
        except (TypeError, ValueError):
            return jsonify(error="Analisi non valida."), 400
        analysis = db.session.get(Analysis, analysis_id) if Analysis else None
        if not analysis or analysis.archived_at or not serializer:
            return jsonify(error="Analisi non disponibile."), 404
        plan = CashFlowPlan(
            analysis_id=analysis.id, name="", start_month="", opening_cash=analysis.ap_capital,
            additional_credit_limit=0, status="Da verificare", notes="",
        )
        try:
            apply_plan_payload(plan, data)
        except (TypeError, ValueError) as exc:
            return jsonify(error=str(exc)), 400
        db.session.add(plan)
        db.session.flush()
        analysis_view = serializer(analysis)
        create_anchor(plan, 0, "Uscita", "Acquisto immobile", "Acquisto immobile", analysis_view["results"]["purchase_price"])
        create_anchor(plan, 0, "Finanziamento ricevuto", "Altro", "Finanziamento esterno", analysis.external_financing)
        create_anchor(plan, analysis.base_duration_months, "Entrata", "Vendita immobile", "Vendita prevista", analysis.expected_sale_value)
        create_anchor(plan, analysis.base_duration_months, "Entrata", "Altri ricavi", "Altri ricavi previsti", analysis.other_income)
        db.session.flush()
        record_revision(plan, actor, "Creazione piano e movimenti principali")
        audit(actor, "cashflow_create", plan.id, f"analysis={analysis.id}")
        db.session.commit()
        return jsonify(plan=plan_dict(plan)), 201

    @app.patch("/api/staff/cashflow/<int:plan_id>")
    def cashflow_update(plan_id):
        actor, denied = staff_user()
        if denied:
            return denied
        plan = db.session.get(CashFlowPlan, plan_id)
        if not plan:
            return jsonify(error="Piano di cassa non trovato."), 404
        data = request.get_json(silent=True) or {}
        try:
            apply_plan_payload(plan, data)
        except (TypeError, ValueError) as exc:
            return jsonify(error=str(exc)), 400
        plan.version += 1
        plan.updated_at = datetime.now(timezone.utc)
        record_revision(plan, actor, data.get("change_note") or "Piano di cassa aggiornato")
        audit(actor, "cashflow_update", plan.id)
        db.session.commit()
        return jsonify(plan=plan_dict(plan))

    @app.post("/api/staff/cashflow/<int:plan_id>/movements")
    def movement_create(plan_id):
        actor, denied = staff_user()
        if denied:
            return denied
        plan = db.session.get(CashFlowPlan, plan_id)
        if not plan or plan.archived_at:
            return jsonify(error="Piano di cassa non disponibile."), 404
        data = request.get_json(silent=True) or {}
        try:
            month_index = int(data.get("month_index"))
            movement_type = app_module.clean_text(data.get("movement_type"), 40)
            category = app_module.clean_text(data.get("category"), 100)
            description = app_module.clean_text(data.get("description"), 500)
            amount_min = float(data.get("amount_min"))
            amount_max = float(data.get("amount_max"))
            reliability = app_module.clean_text(data.get("reliability") or "Da verificare", 40)
            if movement_type not in MOVEMENT_TYPES or category not in MOVEMENT_CATEGORIES:
                raise ValueError("Tipo o categoria movimento non validi.")
            if reliability not in RELIABILITY_LEVELS:
                raise ValueError("Affidabilità del movimento non valida.")
            if not description or not (0 <= month_index <= 120) or not all(math.isfinite(v) for v in (amount_min, amount_max)) or amount_min < 0 or amount_max < amount_min:
                raise ValueError("Movimento incompleto o non valido.")
        except (TypeError, ValueError) as exc:
            return jsonify(error=str(exc) or "Movimento non valido."), 400
        movement = CashFlowMovement(
            plan_id=plan.id, month_index=month_index, movement_type=movement_type,
            category=category, description=description, amount_min=amount_min, amount_max=amount_max,
            source=app_module.clean_text(data.get("source") or "Da verificare", 160),
            reliability=reliability,
            system_generated=False,
        )
        db.session.add(movement)
        db.session.flush()
        plan.version += 1
        plan.updated_at = datetime.now(timezone.utc)
        record_revision(plan, actor, f"Aggiunto movimento: {description}")
        audit(actor, "cashflow_movement_add", plan.id, f"movement={movement.id}")
        db.session.commit()
        return jsonify(plan=plan_dict(plan)), 201

    @app.delete("/api/staff/cashflow/<int:plan_id>/movements/<int:movement_id>")
    def movement_delete(plan_id, movement_id):
        actor, denied = staff_user()
        if denied:
            return denied
        plan = db.session.get(CashFlowPlan, plan_id)
        movement = db.session.get(CashFlowMovement, movement_id)
        if not plan or not movement or movement.plan_id != plan.id:
            return jsonify(error="Movimento non trovato."), 404
        if movement.system_generated:
            return jsonify(error="I movimenti principali automatici non possono essere eliminati."), 409
        description = movement.description
        db.session.delete(movement)
        db.session.flush()
        plan.version += 1
        plan.updated_at = datetime.now(timezone.utc)
        record_revision(plan, actor, f"Rimosso movimento: {description}")
        audit(actor, "cashflow_movement_delete", plan.id, f"movement={movement_id}")
        db.session.commit()
        return jsonify(plan=plan_dict(plan))

    @app.patch("/api/staff/cashflow/<int:plan_id>/archive")
    def cashflow_archive(plan_id):
        actor, denied = staff_user()
        if denied:
            return denied
        plan = db.session.get(CashFlowPlan, plan_id)
        if not plan:
            return jsonify(error="Piano di cassa non trovato."), 404
        data = request.get_json(silent=True) or {}
        if not isinstance(data.get("archived"), bool):
            return jsonify(error="Stato archivio non valido."), 400
        plan.archived_at = datetime.now(timezone.utc) if data["archived"] else None
        plan.version += 1
        plan.updated_at = datetime.now(timezone.utc)
        record_revision(plan, actor, "Piano archiviato" if data["archived"] else "Piano ripristinato")
        audit(actor, "cashflow_archive" if data["archived"] else "cashflow_restore", plan.id)
        db.session.commit()
        return jsonify(plan=plan_dict(plan))

    app.extensions["aplsai_cashflow"] = {
        "CashFlowPlan": CashFlowPlan, "CashFlowMovement": CashFlowMovement,
        "CashFlowRevision": CashFlowRevision, "plan_dict": plan_dict,
    }
