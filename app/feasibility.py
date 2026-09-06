import json
import math
from datetime import datetime, timezone

from flask import jsonify, request, session

from . import db
from .rbac import has_permission


ENGINE_VERSION = "APL-FEASIBILITY-1.1"
ANALYSIS_STATUSES = {"Bozza", "Da verificare", "Validata", "Approvata", "Respinta"}
FINAL_DECISIONS = {"GO", "NO-GO", "PROCEDERE CON CONDIZIONI"}
CASE_KEYS = ("base", "prudente", "stress", "doppio_stress")
CASE_LABELS = {
    "base": "Base", "prudente": "Prudente",
    "stress": "Stress", "doppio_stress": "Doppio Stress",
}


def init_feasibility(app, app_module):
    if app.extensions.get("aplsai_feasibility"):
        return

    class FeasibilityAnalysis(db.Model):
        __tablename__ = "feasibility_analysis"
        id = db.Column(db.Integer, primary_key=True)
        property_id = db.Column(db.Integer, db.ForeignKey("property.id"), nullable=False, index=True)
        scenario_id = db.Column(db.Integer, db.ForeignKey("property_scenario.id"), nullable=False, index=True)
        name = db.Column(db.String(160), nullable=False)
        status = db.Column(db.String(40), nullable=False, default="Da verificare")
        expected_sale_value = db.Column(db.Float, nullable=False)
        other_income = db.Column(db.Float, nullable=False, default=0)
        ap_capital = db.Column(db.Float, nullable=False, default=0)
        external_financing = db.Column(db.Float, nullable=False, default=0)
        risk_budget = db.Column(db.Float, nullable=False, default=0)
        target_margin_percent = db.Column(db.Float, nullable=False, default=0)
        base_duration_months = db.Column(db.Integer, nullable=False)
        assumptions_json = db.Column(db.Text, nullable=False)
        notes = db.Column(db.Text, nullable=False, default="")
        version = db.Column(db.Integer, nullable=False, default=1)
        archived_at = db.Column(db.DateTime(timezone=True))
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)

    class FeasibilityRevision(db.Model):
        __tablename__ = "feasibility_revision"
        id = db.Column(db.Integer, primary_key=True)
        analysis_id = db.Column(db.Integer, db.ForeignKey("feasibility_analysis.id"), nullable=False, index=True)
        version = db.Column(db.Integer, nullable=False)
        snapshot_json = db.Column(db.Text, nullable=False)
        changed_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        change_note = db.Column(db.String(255), nullable=False)
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)
        __table_args__ = (db.UniqueConstraint("analysis_id", "version", name="uq_feasibility_revision_version"),)

        def to_dict(self):
            return {
                "id": self.id, "analysis_id": self.analysis_id, "version": self.version,
                "snapshot": json.loads(self.snapshot_json), "changed_by_user_id": self.changed_by_user_id,
                "change_note": self.change_note,
                "created_at": self.created_at.isoformat() if self.created_at else None,
            }

    class FeasibilityDecision(db.Model):
        __tablename__ = "feasibility_decision"
        id = db.Column(db.Integer, primary_key=True)
        analysis_id = db.Column(db.Integer, db.ForeignKey("feasibility_analysis.id"), nullable=False, index=True)
        decision = db.Column(db.String(40), nullable=False)
        conditions = db.Column(db.Text, nullable=False, default="")
        evidence_ref = db.Column(db.String(500), nullable=False)
        residual_defects = db.Column(db.Text, nullable=False, default="")
        cost_to_complete = db.Column(db.Float, nullable=False, default=0)
        decided_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        analysis_version = db.Column(db.Integer, nullable=False)
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)

    with app.app_context():
        db.create_all()

    def staff_user(permission="feasibility_manage"):
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
            fn(actor, action, "feasibility", object_id, detail)

    def scenario_data(analysis):
        ext = app.extensions.get("aplsai_scenarios") or {}
        Scenario = ext.get("PropertyScenario")
        serializer = ext.get("scenario_dict")
        scenario = db.session.get(Scenario, analysis.scenario_id) if Scenario else None
        return scenario, serializer(scenario) if scenario and serializer else None

    def calculations(analysis, include_investors=True):
        scenario, data = scenario_data(analysis)
        prop = db.session.get(app_module.Property, analysis.property_id)
        purchase = float(prop.price) if prop else 0
        totals = (data or {}).get("totals") or {}
        item_cost = float(totals.get("items_max") or 0)
        missing = list(totals.get("missing_categories") or [])
        quote_basis = {"linked": False, "applied": False, "verified": 0, "total": 0, "missing_codes": []}
        quote_ext = app.extensions.get("aplsai_quotes") or {}
        pilot_ext = app.extensions.get("aplsai_pilot_cases") or {}
        QuoteRequest, PilotCase = quote_ext.get("QuoteRequest"), pilot_ext.get("PilotCase")
        pilot = PilotCase.query.filter_by(code="CO 01", feasibility_id=analysis.id, property_id=analysis.property_id).first() if QuoteRequest and PilotCase else None
        if pilot:
            quotes = QuoteRequest.query.filter_by(pilot_case_id=pilot.id, property_id=analysis.property_id).all()
            verified = [q for q in quotes if q.verification_status == "Verificata" and q.offered_total is not None]
            required = {f"RP-{number:02d}" for number in range(1, 9)}
            verified_codes = {q.code for q in verified}
            quote_basis = {"linked": True, "applied": required == verified_codes, "verified": len(verified_codes),
                           "total": round(sum(float(q.offered_total or 0) for q in verified), 2),
                           "missing_codes": sorted(required - verified_codes)}
            if quote_basis["applied"]:
                purchase = float(next(q.offered_total for q in verified if q.code == "RP-01"))
                item_cost = sum(float(q.offered_total or 0) for q in verified if q.code != "RP-01")
                missing = []
            else:
                missing.append("Preventivi CO 01 verificati: " + ", ".join(quote_basis["missing_codes"]))
        assumptions = json.loads(analysis.assumptions_json)
        cases = []
        for key in CASE_KEYS:
            case = assumptions[key]
            revenue = analysis.expected_sale_value * (1 - case["revenue_reduction_percent"] / 100) + analysis.other_income
            stressed_items = item_cost * (1 + case["cost_increase_percent"] / 100)
            total_cost = purchase + stressed_items
            profit = revenue - total_cost
            loss = max(0, -profit)
            margin_revenue = (profit / revenue * 100) if revenue else None
            margin_cost = (profit / total_cost * 100) if total_cost else None
            roi_ap = (profit / analysis.ap_capital * 100) if analysis.ap_capital else None
            peak_cash = max(0, total_cost - analysis.external_financing)
            funding_gap = max(0, peak_cash - analysis.ap_capital)
            target_profit = revenue * analysis.target_margin_percent / 100
            max_acquisition = revenue - stressed_items - target_profit
            risk_status = "superato" if loss > analysis.risk_budget else "entro_limite"
            cases.append({
                "key": key, "label": CASE_LABELS[key],
                "revenue_reduction_percent": case["revenue_reduction_percent"],
                "cost_increase_percent": case["cost_increase_percent"],
                "delay_months": case["delay_months"],
                "duration_months": analysis.base_duration_months + case["delay_months"],
                "revenue": round(revenue, 2), "total_cost": round(total_cost, 2),
                "profit": round(profit, 2), "loss": round(loss, 2),
                "margin_on_revenue_percent": round(margin_revenue, 2) if margin_revenue is not None else None,
                "margin_on_cost_percent": round(margin_cost, 2) if margin_cost is not None else None,
                "roi_ap_percent": round(roi_ap, 2) if roi_ap is not None else None,
                "estimated_peak_cash_need": round(peak_cash, 2),
                "ap_exposure": round(min(analysis.ap_capital, peak_cash), 2),
                "funding_gap": round(funding_gap, 2),
                "break_even_buffer": round(profit, 2),
                "maximum_acquisition_price": round(max_acquisition, 2),
                "risk_status": risk_status,
            })
        case_map = {case["key"]: case for case in cases}
        if missing:
            decision = "DATI INCOMPLETI"
        elif case_map["doppio_stress"]["risk_status"] == "superato":
            decision = "NO-GO / RISTRUTTURARE"
        elif case_map["stress"]["profit"] < 0:
            decision = "GO CON RISERVE"
        else:
            decision = "GO"
        result = {
            "engine_version": ENGINE_VERSION, "decision": decision, "economic_decision": decision,
            "known_cost_base": round(purchase + item_cost, 2),
            "purchase_price": purchase, "scenario_item_cost_max": round(item_cost, 2),
            "missing_categories": missing, "risk_budget": analysis.risk_budget, "quote_basis": quote_basis,
            "cases": cases,
            "warnings": (["Il costo totale è parziale: completare le categorie mancanti."] if missing else [])
                + ["Il fabbisogno di cassa è una stima conservativa prima dell’incasso finale."]
                + ["Valori da validare con tecnico, commercialista e finanziatore."],
        }
        if include_investors:
            investor_ext = app.extensions.get("aplsai_investors") or {}
            coverage = investor_ext.get("coverage_for_analysis")
            if coverage:
                result["financial_coverage"] = coverage(analysis)
                if result["economic_decision"] not in {"DATI INCOMPLETI", "NO-GO / RISTRUTTURARE"}:
                    if coverage.get("remaining_to_cover", 0) > 0.01:
                        result["decision"] = "PROCEDERE CON CONDIZIONI – COPERTURA DA COMPLETARE"
                    elif coverage.get("decision") != "ESEGUIBILE":
                        result["decision"] = "PROCEDERE CON CONDIZIONI – APPROVAZIONI MANCANTI"
        return result

    def analysis_dict(analysis, include_history=False):
        scenario, data = scenario_data(analysis)
        prop = db.session.get(app_module.Property, analysis.property_id)
        result = {
            "id": analysis.id, "property_id": analysis.property_id,
            "property_ref": prop.ref if prop else None, "scenario_id": analysis.scenario_id,
            "scenario_name": scenario.name if scenario else None, "name": analysis.name,
            "status": analysis.status, "expected_sale_value": analysis.expected_sale_value,
            "other_income": analysis.other_income, "ap_capital": analysis.ap_capital,
            "external_financing": analysis.external_financing, "risk_budget": analysis.risk_budget,
            "target_margin_percent": analysis.target_margin_percent,
            "base_duration_months": analysis.base_duration_months,
            "assumptions": json.loads(analysis.assumptions_json), "notes": analysis.notes,
            "version": analysis.version,
            "archived_at": analysis.archived_at.isoformat() if analysis.archived_at else None,
            "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
            "updated_at": analysis.updated_at.isoformat() if analysis.updated_at else None,
            "results": calculations(analysis),
        }
        if include_history:
            history = FeasibilityRevision.query.filter_by(analysis_id=analysis.id).order_by(FeasibilityRevision.version.desc()).limit(20).all()
            result["revisions"] = [row.to_dict() for row in history]
            decisions = FeasibilityDecision.query.filter_by(analysis_id=analysis.id).order_by(FeasibilityDecision.id.desc()).limit(20).all()
            result["decisions"] = [{
                "id": row.id, "decision": row.decision, "conditions": row.conditions,
                "evidence_ref": row.evidence_ref, "residual_defects": row.residual_defects,
                "cost_to_complete": row.cost_to_complete, "decided_by_user_id": row.decided_by_user_id,
                "analysis_version": row.analysis_version,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            } for row in decisions]
        return result

    def parse_assumptions(data):
        supplied = data.get("assumptions")
        if not isinstance(supplied, dict):
            raise ValueError("Inserire le ipotesi dei quattro scenari.")
        result = {}
        for key in CASE_KEYS:
            row = supplied.get(key)
            if not isinstance(row, dict):
                raise ValueError(f"Ipotesi scenario {CASE_LABELS[key]} mancanti.")
            try:
                revenue_drop = float(row.get("revenue_reduction_percent"))
                cost_rise = float(row.get("cost_increase_percent"))
                delay = int(row.get("delay_months"))
            except (TypeError, ValueError):
                raise ValueError(f"Ipotesi scenario {CASE_LABELS[key]} non valide.")
            if not all(math.isfinite(value) for value in (revenue_drop, cost_rise, delay)):
                raise ValueError("Le ipotesi devono contenere numeri finiti.")
            if not (0 <= revenue_drop <= 100 and 0 <= cost_rise <= 500 and 0 <= delay <= 120):
                raise ValueError("Ipotesi fuori dai limiti ammessi.")
            result[key] = {
                "revenue_reduction_percent": revenue_drop,
                "cost_increase_percent": cost_rise, "delay_months": delay,
            }
        if result["base"] != {"revenue_reduction_percent": 0.0, "cost_increase_percent": 0.0, "delay_months": 0}:
            raise ValueError("Lo scenario Base deve avere variazioni pari a zero.")
        for field in ("revenue_reduction_percent", "cost_increase_percent", "delay_months"):
            values = [result[key][field] for key in CASE_KEYS]
            if values != sorted(values):
                raise ValueError("Prudente, Stress e Doppio Stress devono essere progressivamente più severi.")
        return result

    def apply_payload(analysis, data, creating=False):
        if "name" in data:
            analysis.name = app_module.clean_text(data.get("name"), 160)
        if "status" in data:
            analysis.status = app_module.clean_text(data.get("status"), 40)
        if "notes" in data:
            analysis.notes = app_module.clean_text(data.get("notes"), 4000)
        numeric = {
            "expected_sale_value": float, "other_income": float, "ap_capital": float,
            "external_financing": float, "risk_budget": float,
            "target_margin_percent": float, "base_duration_months": int,
        }
        for field, cast in numeric.items():
            if field in data:
                try:
                    value = cast(data[field])
                except (TypeError, ValueError):
                    raise ValueError("Dati economici non validi.")
                if not math.isfinite(value) or value < 0:
                    raise ValueError("I valori economici non possono essere negativi.")
                setattr(analysis, field, value)
        if "assumptions" in data:
            analysis.assumptions_json = json.dumps(parse_assumptions(data), ensure_ascii=False)
        if not analysis.name or analysis.status not in ANALYSIS_STATUSES:
            raise ValueError("Nome o stato analisi non valido.")
        if not analysis.expected_sale_value or not analysis.base_duration_months:
            raise ValueError("Valore di vendita e durata Base sono obbligatori.")
        if analysis.target_margin_percent > 100:
            raise ValueError("Il margine obiettivo non può superare il 100%.")
        if creating and not analysis.assumptions_json:
            raise ValueError("Inserire le ipotesi dei quattro scenari.")

    def record_revision(analysis, actor, note):
        db.session.add(FeasibilityRevision(
            analysis_id=analysis.id, version=analysis.version,
            snapshot_json=json.dumps(analysis_dict(analysis), ensure_ascii=False),
            changed_by_user_id=actor.id,
            change_note=app_module.clean_text(note or "Analisi aggiornata", 255),
        ))

    @app.get("/api/staff/feasibility")
    def feasibility_list():
        actor, denied = staff_user()
        if denied:
            return denied
        query = FeasibilityAnalysis.query
        if request.args.get("include_archived") != "1":
            query = query.filter(FeasibilityAnalysis.archived_at.is_(None))
        rows = query.order_by(FeasibilityAnalysis.updated_at.desc()).all()
        return jsonify(analyses=[analysis_dict(row) for row in rows])

    @app.get("/api/staff/feasibility/<int:analysis_id>")
    def feasibility_detail(analysis_id):
        actor, denied = staff_user()
        if denied:
            return denied
        analysis = db.session.get(FeasibilityAnalysis, analysis_id)
        if not analysis:
            return jsonify(error="Analisi non trovata."), 404
        return jsonify(analysis=analysis_dict(analysis, include_history=True))

    @app.post("/api/staff/feasibility")
    def feasibility_create():
        actor, denied = staff_user()
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        ext = app.extensions.get("aplsai_scenarios") or {}
        Scenario = ext.get("PropertyScenario")
        try:
            property_id = int(data.get("property_id"))
            scenario_id = int(data.get("scenario_id"))
        except (TypeError, ValueError):
            return jsonify(error="Immobile o scenario non valido."), 400
        prop = db.session.get(app_module.Property, property_id)
        scenario = db.session.get(Scenario, scenario_id) if Scenario else None
        if not prop or prop.archived_at or not scenario or scenario.archived_at or scenario.property_id != prop.id:
            return jsonify(error="Immobile o scenario non disponibile."), 404
        analysis = FeasibilityAnalysis(
            property_id=prop.id, scenario_id=scenario.id, name="", status="Da verificare",
            expected_sale_value=0, other_income=0, ap_capital=0, external_financing=0,
            risk_budget=0, target_margin_percent=0, base_duration_months=0,
            assumptions_json="", notes="",
        )
        try:
            apply_payload(analysis, data, creating=True)
        except (TypeError, ValueError) as exc:
            return jsonify(error=str(exc)), 400
        db.session.add(analysis)
        db.session.flush()
        record_revision(analysis, actor, "Creazione analisi")
        audit(actor, "feasibility_create", analysis.id, f"scenario={scenario.id}")
        db.session.commit()
        return jsonify(analysis=analysis_dict(analysis)), 201

    @app.patch("/api/staff/feasibility/<int:analysis_id>")
    def feasibility_update(analysis_id):
        actor, denied = staff_user()
        if denied:
            return denied
        analysis = db.session.get(FeasibilityAnalysis, analysis_id)
        if not analysis:
            return jsonify(error="Analisi non trovata."), 404
        data = request.get_json(silent=True) or {}
        try:
            apply_payload(analysis, data)
        except (TypeError, ValueError) as exc:
            return jsonify(error=str(exc)), 400
        analysis.version += 1
        analysis.updated_at = datetime.now(timezone.utc)
        record_revision(analysis, actor, data.get("change_note") or "Analisi aggiornata")
        audit(actor, "feasibility_update", analysis.id)
        db.session.commit()
        return jsonify(analysis=analysis_dict(analysis))

    @app.patch("/api/staff/feasibility/<int:analysis_id>/archive")
    def feasibility_archive(analysis_id):
        actor, denied = staff_user()
        if denied:
            return denied
        analysis = db.session.get(FeasibilityAnalysis, analysis_id)
        if not analysis:
            return jsonify(error="Analisi non trovata."), 404
        data = request.get_json(silent=True) or {}
        if not isinstance(data.get("archived"), bool):
            return jsonify(error="Stato archivio non valido."), 400
        analysis.archived_at = datetime.now(timezone.utc) if data["archived"] else None
        analysis.version += 1
        analysis.updated_at = datetime.now(timezone.utc)
        record_revision(analysis, actor, "Analisi archiviata" if data["archived"] else "Analisi ripristinata")
        audit(actor, "feasibility_archive" if data["archived"] else "feasibility_restore", analysis.id)
        db.session.commit()
        return jsonify(analysis=analysis_dict(analysis))

    @app.post("/api/admin/feasibility/<int:analysis_id>/decision")
    def feasibility_decision(analysis_id):
        actor, denied = staff_user("feasibility_approve")
        if denied:
            return denied
        analysis = db.session.get(FeasibilityAnalysis, analysis_id)
        if not analysis or analysis.archived_at:
            return jsonify(error="Analisi non disponibile."), 404
        data = request.get_json(silent=True) or {}
        decision = app_module.clean_text(data.get("decision"), 40)
        conditions = app_module.clean_text(data.get("conditions"), 5000)
        evidence = app_module.clean_text(data.get("evidence_ref"), 500)
        defects = app_module.clean_text(data.get("residual_defects"), 5000)
        try:
            cost_to_complete = float(data.get("cost_to_complete") or 0)
        except (TypeError, ValueError):
            return jsonify(error="Costo a finire non valido."), 400
        if decision not in FINAL_DECISIONS or not evidence or cost_to_complete < 0 or not math.isfinite(cost_to_complete):
            return jsonify(error="Decisione, evidenza e costo a finire validi sono obbligatori."), 400
        if decision == "PROCEDERE CON CONDIZIONI" and not conditions:
            return jsonify(error="Indicare le condizioni da completare."), 400
        result = calculations(analysis)
        if decision == "GO" and (result.get("decision") != "GO" or analysis.status != "Approvata"):
            return jsonify(error="GO bloccato: completare preventivi, copertura, verifiche e approvazione dell’analisi."), 409
        row = FeasibilityDecision(analysis_id=analysis.id, decision=decision, conditions=conditions,
                                  evidence_ref=evidence, residual_defects=defects,
                                  cost_to_complete=cost_to_complete, decided_by_user_id=actor.id,
                                  analysis_version=analysis.version)
        db.session.add(row); db.session.flush()
        audit(actor, "feasibility_decision", analysis.id, f"decision={decision}; record={row.id}")
        db.session.commit()
        return jsonify(analysis=analysis_dict(analysis, include_history=True)), 201

    app.extensions["aplsai_feasibility"] = {
        "FeasibilityAnalysis": FeasibilityAnalysis,
        "FeasibilityRevision": FeasibilityRevision,
        "FeasibilityDecision": FeasibilityDecision,
        "analysis_dict": analysis_dict,
        "calculations": calculations,
    }
