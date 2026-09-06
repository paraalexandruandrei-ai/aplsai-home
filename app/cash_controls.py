import math
from datetime import datetime, timezone

from flask import jsonify, request, session

from .rbac import has_permission


MODES = {"A - Senza anticipazione", "B - Anticipazione fino al 40%", "C - Conto vincolato / SAL"}
MILESTONE_STATUSES = {"Da pianificare", "In corso", "Consegnata", "Accettata", "Con difetti critici"}
PAYMENT_STATUSES = {"Non autorizzato", "Autorizzato", "Pagato"}


def utcnow(): return datetime.now(timezone.utc)


def parse_date(value):
    if value in {None, ""}: return None
    out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return out.replace(tzinfo=timezone.utc) if not out.tzinfo else out.astimezone(timezone.utc)


def init_cash_controls(app, app_module):
    if app.extensions.get("aplsai_cash_controls"): return
    db = app_module.db

    class CashControl(db.Model):
        __tablename__ = "cash_control"
        id = db.Column(db.Integer, primary_key=True)
        plan_id = db.Column(db.Integer, unique=True, nullable=False, index=True)
        mode = db.Column(db.String(80), nullable=False, default="A - Senza anticipazione")
        contingency_percent = db.Column(db.Float, nullable=False, default=10)
        advance_percent = db.Column(db.Float, nullable=False, default=0)
        unpaid_titles_percent = db.Column(db.Float, nullable=False, default=0)
        own_capital_limit = db.Column(db.Float, nullable=False, default=0)
        reserve_months = db.Column(db.Integer, nullable=False, default=6)
        notes = db.Column(db.Text, nullable=False, default="")
        version = db.Column(db.Integer, nullable=False, default=1)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    class CashMilestone(db.Model):
        __tablename__ = "cash_milestone"
        id = db.Column(db.Integer, primary_key=True)
        control_id = db.Column(db.Integer, db.ForeignKey("cash_control.id"), nullable=False, index=True)
        number = db.Column(db.Integer, nullable=False)
        title = db.Column(db.String(220), nullable=False)
        deliverable = db.Column(db.Text, nullable=False)
        planned_amount = db.Column(db.Float, nullable=False)
        due_at = db.Column(db.DateTime(timezone=True))
        status = db.Column(db.String(40), nullable=False, default="Da pianificare")
        evidence_ref = db.Column(db.String(500), nullable=False, default="")
        verification_note = db.Column(db.Text, nullable=False, default="")
        critical_defects = db.Column(db.Text, nullable=False, default="")
        verified_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        verified_at = db.Column(db.DateTime(timezone=True))
        payment_status = db.Column(db.String(40), nullable=False, default="Non autorizzato")
        authorized_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        authorized_at = db.Column(db.DateTime(timezone=True))
        paid_amount = db.Column(db.Float, nullable=False, default=0)
        payment_reference = db.Column(db.String(500), nullable=False, default="")
        paid_at = db.Column(db.DateTime(timezone=True))
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
        __table_args__ = (db.UniqueConstraint("control_id", "number", name="uq_cash_milestone_number"),)

    class CashControlEvent(db.Model):
        __tablename__ = "cash_control_event"
        id = db.Column(db.Integer, primary_key=True)
        control_id = db.Column(db.Integer, db.ForeignKey("cash_control.id"), nullable=False, index=True)
        milestone_id = db.Column(db.Integer, nullable=True)
        actor_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        action = db.Column(db.String(100), nullable=False)
        note = db.Column(db.String(500), nullable=False, default="")
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    with app.app_context(): db.create_all()

    def actor(permission):
        user = db.session.get(app_module.User, session.get("uid")) if session.get("uid") else None
        if not user: return None, (jsonify(error="Non autenticato."), 401)
        if not has_permission(user.role, permission): return None, (jsonify(error="Permesso insufficiente."), 403)
        return user, None

    def event(control, user, action, milestone=None, note=""):
        db.session.add(CashControlEvent(control_id=control.id, milestone_id=milestone.id if milestone else None,
                                       actor_user_id=user.id, action=action, note=app_module.clean_text(note, 500)))

    def milestones(control): return CashMilestone.query.filter_by(control_id=control.id).order_by(CashMilestone.number).all()

    def milestone_dict(row):
        return {"id": row.id, "number": row.number, "title": row.title, "deliverable": row.deliverable,
                "planned_amount": row.planned_amount, "due_at": row.due_at.isoformat() if row.due_at else None,
                "status": row.status, "evidence_ref": row.evidence_ref, "verification_note": row.verification_note,
                "critical_defects": row.critical_defects, "verified_at": row.verified_at.isoformat() if row.verified_at else None,
                "payment_status": row.payment_status, "paid_amount": row.paid_amount,
                "payment_reference": row.payment_reference, "paid_at": row.paid_at.isoformat() if row.paid_at else None}

    def control_dict(row):
        CashPlan = (app.extensions.get("aplsai_cashflow") or {}).get("CashFlowPlan")
        plan = db.session.get(CashPlan, row.plan_id) if CashPlan else None
        analysis = None
        if plan:
            Analysis = (app.extensions.get("aplsai_feasibility") or {}).get("FeasibilityAnalysis")
            analysis = db.session.get(Analysis, plan.analysis_id) if Analysis else None
        rows = milestones(row); total = sum(x.planned_amount for x in rows); paid = sum(x.paid_amount for x in rows)
        base_cost = 0
        if analysis:
            calc = (app.extensions.get("aplsai_feasibility") or {}).get("calculations")
            base_cost = float((calc(analysis, include_investors=False) if calc else {}).get("known_cost_base") or 0)
        reserve = base_cost * row.contingency_percent / 100
        return {"id": row.id, "plan_id": row.plan_id, "mode": row.mode,
                "contingency_percent": row.contingency_percent, "advance_percent": row.advance_percent,
                "unpaid_titles_percent": row.unpaid_titles_percent, "own_capital_limit": row.own_capital_limit,
                "reserve_months": row.reserve_months, "notes": row.notes, "version": row.version,
                "base_cost": round(base_cost, 2), "required_reserve": round(reserve, 2),
                "milestone_count": len(rows), "planned_total": round(total, 2), "paid_total": round(paid, 2),
                "remaining_total": round(total-paid, 2), "milestones": [milestone_dict(x) for x in rows]}

    @app.get("/api/staff/cash-controls/<int:plan_id>")
    def get_control(plan_id):
        user, denied = actor("cash_control_read")
        if denied: return denied
        row = CashControl.query.filter_by(plan_id=plan_id).first()
        return jsonify(control=control_dict(row) if row else None)

    @app.put("/api/staff/cash-controls/<int:plan_id>")
    def save_control(plan_id):
        user, denied = actor("cash_control_manage")
        if denied: return denied
        CashPlan = (app.extensions.get("aplsai_cashflow") or {}).get("CashFlowPlan")
        plan = db.session.get(CashPlan, plan_id) if CashPlan else None
        if not plan or plan.archived_at: return jsonify(error="Piano di cassa non disponibile."), 404
        data = request.get_json(silent=True) or {}; mode = data.get("mode", "A - Senza anticipazione")
        try:
            contingency = float(data.get("contingency_percent", 10)); advance = float(data.get("advance_percent", 0))
            unpaid = float(data.get("unpaid_titles_percent", 0)); own_limit = float(data.get("own_capital_limit", 0)); reserve_months = int(data.get("reserve_months", 6))
        except (TypeError, ValueError): return jsonify(error="Parametri di cassa non validi."), 400
        if mode not in MODES or not all(math.isfinite(x) and x >= 0 for x in (contingency, advance, unpaid, own_limit)) or advance > 40 or unpaid > 30 or not 0 <= reserve_months <= 60:
            return jsonify(error="Limiti non validi: anticipo massimo 40%, titoli non quietanzati massimo 30%."), 400
        if mode == "A - Senza anticipazione" and advance != 0: return jsonify(error="Lo scenario A deve funzionare senza anticipazione."), 400
        row = CashControl.query.filter_by(plan_id=plan_id).first() or CashControl(plan_id=plan_id)
        if not row.id: db.session.add(row); db.session.flush()
        row.mode, row.contingency_percent, row.advance_percent = mode, contingency, advance
        row.unpaid_titles_percent, row.own_capital_limit, row.reserve_months = unpaid, own_limit, reserve_months
        row.notes = app_module.clean_text(data.get("notes"), 4000); row.version += 1; event(row, user, "Controllo cassa aggiornato")
        db.session.commit(); return jsonify(control=control_dict(row))

    @app.post("/api/staff/cash-controls/<int:control_id>/milestones")
    def create_milestone(control_id):
        user, denied = actor("cash_control_manage")
        if denied: return denied
        control = db.session.get(CashControl, control_id)
        if not control: return jsonify(error="Controllo di cassa non trovato."), 404
        if CashMilestone.query.filter_by(control_id=control.id).count() >= 5: return jsonify(error="Sono ammessi al massimo 5 SAL."), 409
        data = request.get_json(silent=True) or {}
        try: amount = float(data.get("planned_amount")); number = int(data.get("number")); due = parse_date(data.get("due_at"))
        except (TypeError, ValueError): return jsonify(error="Dati SAL non validi."), 400
        title, deliverable = app_module.clean_text(data.get("title"), 220), app_module.clean_text(data.get("deliverable"), 5000)
        if not title or not deliverable or amount <= 0 or not math.isfinite(amount) or not 1 <= number <= 5: return jsonify(error="Numero, titolo, risultato e importo del SAL sono obbligatori."), 400
        if control.mode == "C - Conto vincolato / SAL" and amount < control_dict(control)["base_cost"] * .10:
            return jsonify(error="Nel regime agevolato ogni SAL deve valere almeno il 10% dell’investimento ammesso."), 400
        row = CashMilestone(control_id=control.id, number=number, title=title, deliverable=deliverable, planned_amount=amount, due_at=due)
        db.session.add(row); db.session.flush(); event(control, user, "SAL creato", row); db.session.commit()
        return jsonify(control=control_dict(control)), 201

    @app.patch("/api/staff/cash-milestones/<int:milestone_id>")
    def update_milestone(milestone_id):
        user, denied = actor("cash_control_manage")
        if denied: return denied
        row = db.session.get(CashMilestone, milestone_id)
        if not row: return jsonify(error="SAL non trovato."), 404
        data = request.get_json(silent=True) or {}; status = data.get("status", row.status)
        if status not in MILESTONE_STATUSES: return jsonify(error="Stato SAL non valido."), 400
        row.status = status
        for key, limit in (("evidence_ref",500),("verification_note",5000),("critical_defects",5000)):
            if key in data: setattr(row, key, app_module.clean_text(data.get(key), limit))
        control = db.session.get(CashControl, row.control_id); event(control, user, "SAL aggiornato", row, status); db.session.commit()
        return jsonify(control=control_dict(control))

    @app.post("/api/admin/cash-milestones/<int:milestone_id>/authorize")
    def authorize_milestone(milestone_id):
        user, denied = actor("cash_control_approve")
        if denied: return denied
        row = db.session.get(CashMilestone, milestone_id)
        if not row: return jsonify(error="SAL non trovato."), 404
        if row.status != "Accettata" or not row.evidence_ref or row.critical_defects:
            return jsonify(error="Pagamento bloccato: risultato non accettato, evidenza assente o difetti critici aperti."), 409
        row.payment_status, row.authorized_by_user_id, row.authorized_at = "Autorizzato", user.id, utcnow()
        row.verified_by_user_id, row.verified_at = user.id, utcnow()
        control = db.session.get(CashControl, row.control_id); event(control, user, "Pagamento autorizzato", row); db.session.commit()
        return jsonify(control=control_dict(control))

    @app.post("/api/admin/cash-milestones/<int:milestone_id>/paid")
    def register_payment(milestone_id):
        user, denied = actor("cash_control_approve")
        if denied: return denied
        row = db.session.get(CashMilestone, milestone_id); data = request.get_json(silent=True) or {}
        if not row or row.payment_status != "Autorizzato": return jsonify(error="Il pagamento deve essere prima autorizzato."), 409
        try: amount = float(data.get("amount"))
        except (TypeError, ValueError): return jsonify(error="Importo pagato non valido."), 400
        reference = app_module.clean_text(data.get("reference"), 500)
        if amount <= 0 or amount > row.planned_amount or not reference: return jsonify(error="Importo entro il SAL e riferimento di pagamento sono obbligatori."), 400
        row.paid_amount, row.payment_reference, row.paid_at, row.payment_status = amount, reference, utcnow(), "Pagato"
        control = db.session.get(CashControl, row.control_id); event(control, user, "Pagamento registrato", row, reference); db.session.commit()
        return jsonify(control=control_dict(control))

    app.extensions["aplsai_cash_controls"] = {"CashControl": CashControl, "CashMilestone": CashMilestone, "CashControlEvent": CashControlEvent}
