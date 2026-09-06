import math
from datetime import datetime, timezone

from flask import jsonify, request, session

from . import db
from .rbac import has_permission


INVESTOR_STATUSES = {"Potenziale", "In verifica", "Approvato", "Sospeso"}
VERIFICATION_LEVELS = {"Da verificare", "Identità verificata", "Documenti verificati", "Verificato"}
COMMITMENT_STATUSES = {"Manifestazione di interesse", "Da verificare", "Confermato", "Versato", "Revocato"}
COUNTED_COMMITMENT_STATUSES = {"Confermato", "Versato"}
PLAN_STATUSES = {"Bozza", "Da verificare", "Approvato"}


def init_investors(app, app_module):
    if app.extensions.get("aplsai_investors"):
        return

    class InvestorProfile(db.Model):
        __tablename__ = "investor_profile"
        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(160), nullable=False)
        email = db.Column(db.String(255), nullable=False, unique=True, index=True)
        phone = db.Column(db.String(80), nullable=False, default="")
        investor_type = db.Column(db.String(100), nullable=False, default="Privato")
        available_capital = db.Column(db.Float, nullable=False, default=0)
        status = db.Column(db.String(40), nullable=False, default="Potenziale")
        verification = db.Column(db.String(60), nullable=False, default="Da verificare")
        nda_signed = db.Column(db.Boolean, nullable=False, default=False)
        notes = db.Column(db.Text, nullable=False, default="")
        archived_at = db.Column(db.DateTime(timezone=True))
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)

    class InvestorFundingPlan(db.Model):
        __tablename__ = "investor_funding_plan"
        id = db.Column(db.Integer, primary_key=True)
        analysis_id = db.Column(db.Integer, db.ForeignKey("feasibility_analysis.id"), nullable=False, unique=True, index=True)
        contingency_percent = db.Column(db.Float, nullable=False, default=10)
        status = db.Column(db.String(40), nullable=False, default="Da verificare")
        notes = db.Column(db.Text, nullable=False, default="")
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)

    class InvestorCommitment(db.Model):
        __tablename__ = "investor_commitment"
        id = db.Column(db.Integer, primary_key=True)
        investor_id = db.Column(db.Integer, db.ForeignKey("investor_profile.id"), nullable=False, index=True)
        analysis_id = db.Column(db.Integer, db.ForeignKey("feasibility_analysis.id"), nullable=False, index=True)
        amount = db.Column(db.Float, nullable=False)
        status = db.Column(db.String(50), nullable=False, default="Manifestazione di interesse")
        source = db.Column(db.String(160), nullable=False, default="Da verificare")
        document_reference = db.Column(db.String(500), nullable=False, default="")
        notes = db.Column(db.Text, nullable=False, default="")
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)

    with app.app_context():
        db.create_all()

    def staff_user(permission="investor_read"):
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
            fn(actor, action, "investor", object_id, detail)

    def finite_nonnegative(value, label):
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{label} non valido.")
        if not math.isfinite(number) or number < 0:
            raise ValueError(f"{label} non può essere negativo.")
        return number

    def investor_dict(row):
        commitments = InvestorCommitment.query.filter_by(investor_id=row.id).all()
        confirmed = sum(x.amount for x in commitments if x.status in COUNTED_COMMITMENT_STATUSES)
        interested = sum(x.amount for x in commitments if x.status == "Manifestazione di interesse")
        return {
            "id": row.id, "name": row.name, "email": row.email, "phone": row.phone,
            "investor_type": row.investor_type, "available_capital": row.available_capital,
            "status": row.status, "verification": row.verification,
            "nda_signed": row.nda_signed, "notes": row.notes,
            "confirmed_capital": round(confirmed, 2), "interest_capital": round(interested, 2),
            "archived_at": row.archived_at.isoformat() if row.archived_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def commitment_dict(row):
        investor = db.session.get(InvestorProfile, row.investor_id)
        return {
            "id": row.id, "investor_id": row.investor_id,
            "investor_name": investor.name if investor else None,
            "analysis_id": row.analysis_id, "amount": row.amount, "status": row.status,
            "counted_as_coverage": row.status in COUNTED_COMMITMENT_STATUSES,
            "source": row.source, "document_reference": row.document_reference,
            "notes": row.notes,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def coverage_for_analysis(analysis):
        if not analysis:
            return None
        result = (app.extensions.get("aplsai_feasibility") or {}).get("calculations")
        base_results = result(analysis, include_investors=False) if result else {"cases": []}
        base_case = next((x for x in base_results.get("cases", []) if x.get("key") == "base"), {})
        plan = InvestorFundingPlan.query.filter_by(analysis_id=analysis.id).first()
        buffer_percent = plan.contingency_percent if plan else 10.0
        total_cost = float(base_case.get("total_cost") or 0)
        gross_required = total_cost * (1 + buffer_percent / 100)
        own_and_external = float(analysis.ap_capital or 0) + float(analysis.external_financing or 0)
        investor_required = max(0, gross_required - own_and_external)
        rows = InvestorCommitment.query.filter_by(analysis_id=analysis.id).all()
        confirmed = sum(x.amount for x in rows if x.status in COUNTED_COMMITMENT_STATUSES)
        expressed = sum(x.amount for x in rows if x.status == "Manifestazione di interesse")
        remaining = max(0, investor_required - confirmed)
        coverage_percent = 100 if investor_required == 0 else min(100, confirmed / investor_required * 100)
        if investor_required == 0 or remaining <= 0.01:
            if analysis.status == "Approvata" and plan and plan.status == "Approvato":
                decision = "ESEGUIBILE"
            else:
                decision = "PRONTA PER APPROVAZIONE"
        elif confirmed > 0:
            decision = "COPERTURA PARZIALE"
        else:
            decision = "FATTIBILE MA DA FINANZIARE"
        return {
            "analysis_id": analysis.id,
            "contingency_percent": buffer_percent,
            "funding_plan_status": plan.status if plan else "Da verificare",
            "total_cost_base": round(total_cost, 2),
            "gross_capital_required": round(gross_required, 2),
            "ap_capital": round(float(analysis.ap_capital or 0), 2),
            "external_financing": round(float(analysis.external_financing or 0), 2),
            "investor_capital_required": round(investor_required, 2),
            "confirmed_investor_capital": round(confirmed, 2),
            "interest_not_counted": round(expressed, 2),
            "remaining_to_cover": round(remaining, 2),
            "coverage_percent": round(coverage_percent, 2),
            "decision": decision,
            "commitments": [commitment_dict(x) for x in rows],
            "warning": "Le manifestazioni d'interesse non sono capitale confermato. Avvio subordinato a contratti, verifiche e approvazione umana.",
        }

    def full_payload():
        Feasibility = (app.extensions.get("aplsai_feasibility") or {}).get("FeasibilityAnalysis")
        analyses = Feasibility.query.filter(Feasibility.archived_at.is_(None)).order_by(Feasibility.updated_at.desc()).all() if Feasibility else []
        return {
            "investors": [investor_dict(x) for x in InvestorProfile.query.order_by(InvestorProfile.updated_at.desc()).all()],
            "analyses": [{"id": x.id, "name": x.name, "property_ref": db.session.get(app_module.Property, x.property_id).ref if db.session.get(app_module.Property, x.property_id) else None, "coverage": coverage_for_analysis(x)} for x in analyses],
        }

    @app.get("/api/staff/investors")
    def investors_list():
        actor, denied = staff_user()
        if denied:
            return denied
        return jsonify(**full_payload())

    @app.post("/api/staff/investors")
    def investor_create():
        actor, denied = staff_user("investor_manage")
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        name = app_module.clean_text(data.get("name"), 160)
        email = app_module.clean_email(data.get("email"))
        if not name or not app_module.valid_email(email):
            return jsonify(error="Nome ed email valida sono obbligatori."), 400
        if InvestorProfile.query.filter_by(email=email).first():
            return jsonify(error="Investitore già registrato con questa email."), 409
        try:
            capital = finite_nonnegative(data.get("available_capital") or 0, "Capitale disponibile")
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        status = app_module.clean_text(data.get("status") or "Potenziale", 40)
        verification = app_module.clean_text(data.get("verification") or "Da verificare", 60)
        if status not in INVESTOR_STATUSES or verification not in VERIFICATION_LEVELS:
            return jsonify(error="Stato investitore non valido."), 400
        row = InvestorProfile(name=name, email=email, phone=app_module.clean_text(data.get("phone"), 80), investor_type=app_module.clean_text(data.get("investor_type") or "Privato", 100), available_capital=capital, status=status, verification=verification, nda_signed=bool(data.get("nda_signed")), notes=app_module.clean_text(data.get("notes"), 4000))
        db.session.add(row); db.session.flush()
        audit(actor, "investor_create", row.id, f"status={row.status}")
        db.session.commit()
        return jsonify(investor=investor_dict(row)), 201

    @app.patch("/api/staff/investors/<int:investor_id>")
    def investor_update(investor_id):
        actor, denied = staff_user("investor_manage")
        if denied:
            return denied
        row = db.session.get(InvestorProfile, investor_id)
        if not row:
            return jsonify(error="Investitore non trovato."), 404
        data = request.get_json(silent=True) or {}
        try:
            if "available_capital" in data: row.available_capital = finite_nonnegative(data.get("available_capital"), "Capitale disponibile")
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        for field, limit in (("name",160),("phone",80),("investor_type",100),("notes",4000)):
            if field in data: setattr(row, field, app_module.clean_text(data.get(field), limit))
        if "email" in data:
            email = app_module.clean_email(data.get("email"))
            if not app_module.valid_email(email): return jsonify(error="Email non valida."), 400
            duplicate = InvestorProfile.query.filter(InvestorProfile.email == email, InvestorProfile.id != row.id).first()
            if duplicate: return jsonify(error="Email già utilizzata."), 409
            row.email = email
        if "status" in data:
            if data["status"] not in INVESTOR_STATUSES: return jsonify(error="Stato non valido."), 400
            row.status = data["status"]
        if "verification" in data:
            if data["verification"] not in VERIFICATION_LEVELS: return jsonify(error="Verifica non valida."), 400
            row.verification = data["verification"]
        if "nda_signed" in data: row.nda_signed = bool(data["nda_signed"])
        if "archived" in data: row.archived_at = datetime.now(timezone.utc) if data["archived"] else None
        row.updated_at = app_module.utcnow()
        audit(actor, "investor_update", row.id, f"status={row.status}; verification={row.verification}")
        db.session.commit()
        return jsonify(investor=investor_dict(row))

    @app.post("/api/staff/investor-commitments")
    def commitment_create():
        actor, denied = staff_user("investor_manage")
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        try:
            investor_id = int(data.get("investor_id")); analysis_id = int(data.get("analysis_id"))
            amount = finite_nonnegative(data.get("amount"), "Importo")
        except (TypeError, ValueError) as exc:
            return jsonify(error=str(exc) or "Dati impegno non validi."), 400
        investor = db.session.get(InvestorProfile, investor_id)
        Analysis = (app.extensions.get("aplsai_feasibility") or {}).get("FeasibilityAnalysis")
        analysis = db.session.get(Analysis, analysis_id) if Analysis else None
        if not investor or investor.archived_at or not analysis or analysis.archived_at:
            return jsonify(error="Investitore o analisi non disponibile."), 404
        status = app_module.clean_text(data.get("status") or "Manifestazione di interesse", 50)
        if status not in COMMITMENT_STATUSES:
            return jsonify(error="Stato impegno non valido."), 400
        if status in COUNTED_COMMITMENT_STATUSES and (investor.status != "Approvato" or investor.verification != "Verificato" or not investor.nda_signed):
            return jsonify(error="Per confermare il capitale servono investitore approvato, verifica completata e NDA firmato."), 409
        row = InvestorCommitment(investor_id=investor_id, analysis_id=analysis_id, amount=amount, status=status, source=app_module.clean_text(data.get("source") or "Da verificare",160), document_reference=app_module.clean_text(data.get("document_reference"),500), notes=app_module.clean_text(data.get("notes"),4000))
        db.session.add(row); db.session.flush()
        audit(actor, "investor_commitment_create", row.id, f"analysis={analysis_id}; amount={amount}; status={status}")
        db.session.commit()
        return jsonify(commitment=commitment_dict(row), coverage=coverage_for_analysis(analysis)), 201

    @app.patch("/api/staff/investor-funding/<int:analysis_id>")
    def funding_plan_update(analysis_id):
        actor, denied = staff_user("investor_manage")
        if denied:
            return denied
        Analysis = (app.extensions.get("aplsai_feasibility") or {}).get("FeasibilityAnalysis")
        analysis = db.session.get(Analysis, analysis_id) if Analysis else None
        if not analysis:
            return jsonify(error="Analisi non trovata."), 404
        data = request.get_json(silent=True) or {}
        plan = InvestorFundingPlan.query.filter_by(analysis_id=analysis_id).first()
        if not plan:
            plan = InvestorFundingPlan(analysis_id=analysis_id); db.session.add(plan)
        try:
            buffer_percent = finite_nonnegative(data.get("contingency_percent", plan.contingency_percent), "Margine imprevisti")
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        if buffer_percent > 100:
            return jsonify(error="Il margine imprevisti non può superare il 100%."), 400
        status = app_module.clean_text(data.get("status") or plan.status, 40)
        if status not in PLAN_STATUSES:
            return jsonify(error="Stato piano finanziario non valido."), 400
        plan.contingency_percent = buffer_percent; plan.status = status
        plan.notes = app_module.clean_text(data.get("notes", plan.notes), 4000); plan.updated_at = app_module.utcnow()
        audit(actor, "investor_funding_update", analysis_id, f"buffer={buffer_percent}; status={status}")
        db.session.commit()
        return jsonify(coverage=coverage_for_analysis(analysis))

    app.extensions["aplsai_investors"] = {
        "InvestorProfile": InvestorProfile,
        "InvestorFundingPlan": InvestorFundingPlan,
        "InvestorCommitment": InvestorCommitment,
        "investor_dict": investor_dict,
        "commitment_dict": commitment_dict,
        "coverage_for_analysis": coverage_for_analysis,
    }
