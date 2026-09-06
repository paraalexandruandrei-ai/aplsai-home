from datetime import datetime, timezone

from flask import jsonify, request, session

from .rbac import has_permission


CHECKS = [
    ("AV-01", "Fattibilità approvata", "Analisi approvata e ultimo verbale decisionale GO."),
    ("AV-02", "Preventivi verificati", "Le otto richieste CO 01 sono complete e applicate ai costi."),
    ("AV-03", "Copertura finanziaria", "Capitale e finanziamenti documentati rendono l’operazione eseguibile."),
    ("AV-04", "Cassa e SAL", "Piano approvato, riconciliato e controllo SAL configurato."),
    ("AV-05", "Portafoglio sostenibile", "Liquidità, riserva, esposizione e operazioni simultanee rispettano i limiti."),
    ("AV-06", "Capacità operativa", "Squadre, carico e dipendenze operative sono confermati."),
    ("AV-07", "Documenti e autorizzazioni", "Documenti, autorizzazioni e verifiche professionali necessari sono disponibili."),
]


def utcnow(): return datetime.now(timezone.utc)


def init_launch_control(app, app_module):
    if app.extensions.get("aplsai_launch_control"): return
    db = app_module.db

    class OperationLaunch(db.Model):
        __tablename__ = "operation_launch"
        id = db.Column(db.Integer, primary_key=True)
        analysis_id = db.Column(db.Integer, unique=True, nullable=False, index=True)
        assigned_to_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        status = db.Column(db.String(50), nullable=False, default="Da preparare")
        final_decision = db.Column(db.String(50), nullable=False, default="NON AUTORIZZATO")
        final_note = db.Column(db.Text, nullable=False, default="")
        authorized_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        authorized_at = db.Column(db.DateTime(timezone=True))
        version = db.Column(db.Integer, nullable=False, default=1)
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    class LaunchCheck(db.Model):
        __tablename__ = "launch_check"
        id = db.Column(db.Integer, primary_key=True)
        launch_id = db.Column(db.Integer, db.ForeignKey("operation_launch.id"), nullable=False, index=True)
        code = db.Column(db.String(20), nullable=False)
        title = db.Column(db.String(220), nullable=False)
        expected_result = db.Column(db.Text, nullable=False)
        automatic_status = db.Column(db.String(30), nullable=False, default="Da verificare")
        automatic_detail = db.Column(db.Text, nullable=False, default="")
        evidence_ref = db.Column(db.String(500), nullable=False, default="")
        residual_defects = db.Column(db.Text, nullable=False, default="")
        corrective_action = db.Column(db.Text, nullable=False, default="")
        due_at = db.Column(db.DateTime(timezone=True))
        verification_status = db.Column(db.String(30), nullable=False, default="Da verificare")
        verification_note = db.Column(db.Text, nullable=False, default="")
        verified_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        verified_at = db.Column(db.DateTime(timezone=True))
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
        __table_args__ = (db.UniqueConstraint("launch_id", "code", name="uq_launch_check_code"),)

    class LaunchEvent(db.Model):
        __tablename__ = "launch_event"
        id = db.Column(db.Integer, primary_key=True)
        launch_id = db.Column(db.Integer, db.ForeignKey("operation_launch.id"), nullable=False, index=True)
        actor_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        action = db.Column(db.String(100), nullable=False)
        detail = db.Column(db.String(500), nullable=False, default="")
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    with app.app_context(): db.create_all()

    def actor(permission):
        user = db.session.get(app_module.User, session.get("uid")) if session.get("uid") else None
        if not user: return None, (jsonify(error="Non autenticato."), 401)
        if not has_permission(user.role, permission): return None, (jsonify(error="Permesso insufficiente."), 403)
        return user, None

    def event(row, user, action, detail=""):
        db.session.add(LaunchEvent(launch_id=row.id, actor_user_id=user.id, action=action, detail=app_module.clean_text(detail, 500)))

    def ensure_checks(row):
        for code, title, expected in CHECKS:
            if not LaunchCheck.query.filter_by(launch_id=row.id, code=code).first():
                db.session.add(LaunchCheck(launch_id=row.id, code=code, title=title, expected_result=expected))
        db.session.flush()

    def derived(row):
        Analysis = (app.extensions.get("aplsai_feasibility") or {}).get("FeasibilityAnalysis")
        serializer = (app.extensions.get("aplsai_feasibility") or {}).get("analysis_dict")
        analysis = db.session.get(Analysis, row.analysis_id) if Analysis else None
        if not analysis or not serializer: return {}, None
        data = serializer(analysis, include_history=True); results = data.get("results") or {}
        last_decision = (data.get("decisions") or [{}])[0]
        financial = results.get("financial_coverage") or {}
        CashPlan = (app.extensions.get("aplsai_cashflow") or {}).get("CashFlowPlan")
        plan_serializer = (app.extensions.get("aplsai_cashflow") or {}).get("plan_dict")
        plans = CashPlan.query.filter_by(analysis_id=analysis.id).filter(CashPlan.archived_at.is_(None)).all() if CashPlan else []
        approved_plans = [p for p in plans if p.status == "Approvato"]
        cash_ok = any((plan_serializer(p).get("results") or {}).get("decision") == "COPERTURA ADEGUATA" for p in approved_plans) if plan_serializer else False
        CashControl = (app.extensions.get("aplsai_cash_controls") or {}).get("CashControl")
        CashMilestone = (app.extensions.get("aplsai_cash_controls") or {}).get("CashMilestone")
        control_ok = any(CashControl.query.filter_by(plan_id=p.id).first() and 0 < CashMilestone.query.filter_by(control_id=CashControl.query.filter_by(plan_id=p.id).first().id).count() <= 5 for p in approved_plans) if CashControl and CashMilestone else False
        portfolio_fn = (app.extensions.get("aplsai_portfolio") or {}).get("portfolio_dict")
        portfolio = portfolio_fn().get("results", {}) if portfolio_fn else {}
        capacity_fn = (app.extensions.get("aplsai_capacity") or {}).get("capacity_dict")
        capacity = capacity_fn().get("results", {}) if capacity_fn else {}
        Allocation = (app.extensions.get("aplsai_capacity") or {}).get("CapacityAllocation")
        allocated = any(Allocation.query.filter_by(plan_id=p.id).count() for p in approved_plans) if Allocation else False
        checks = {
            "AV-01": (analysis.status == "Approvata" and last_decision.get("decision") == "GO", f"Analisi {analysis.status}; verbale {last_decision.get('decision','mancante')}"),
            "AV-02": (bool((results.get("quote_basis") or {}).get("applied")), f"Preventivi verificati {(results.get('quote_basis') or {}).get('verified',0)}/8"),
            "AV-03": (financial.get("decision") == "ESEGUIBILE", financial.get("decision", "Piano di copertura non disponibile")),
            "AV-04": (cash_ok and control_ok, f"Piano approvato e coperto: {'sì' if cash_ok else 'no'}; SAL: {'sì' if control_ok else 'no'}"),
            "AV-05": (portfolio.get("decision") == "SOSTENIBILE", portfolio.get("decision", "Portafoglio non configurato")),
            "AV-06": (capacity.get("decision") == "CAPACITÀ DISPONIBILE" and allocated, f"{capacity.get('decision','Capacità non configurata')}; assegnazione: {'sì' if allocated else 'no'}"),
            "AV-07": (True, "Requisito manuale: allegare i riferimenti prima dell’approvazione Admin"),
        }
        return checks, analysis

    def refresh(row):
        ensure_checks(row); values, analysis = derived(row)
        for check in LaunchCheck.query.filter_by(launch_id=row.id).all():
            ok, detail = values.get(check.code, (False, "Non disponibile"))
            check.automatic_status = "Superato" if ok else "Bloccato"
            check.automatic_detail = detail
            if not ok and check.code != "AV-07": check.verification_status = "Da verificare"
        return analysis

    def as_dict(row):
        analysis = refresh(row); checks = LaunchCheck.query.filter_by(launch_id=row.id).order_by(LaunchCheck.code).all()
        complete = all(c.automatic_status == "Superato" and c.verification_status == "Approvata" and not c.residual_defects for c in checks)
        row.status = "Autorizzato" if row.final_decision == "AVVIO AUTORIZZATO" else ("Pronto all’autorizzazione" if complete else "Bloccato")
        return {"id": row.id, "analysis_id": row.analysis_id, "analysis_name": analysis.name if analysis else "",
                "status": row.status, "final_decision": row.final_decision, "final_note": row.final_note,
                "assigned_to_user_id": row.assigned_to_user_id, "version": row.version,
                "authorized_at": row.authorized_at.isoformat() if row.authorized_at else None,
                "checks": [{"id": c.id, "code": c.code, "title": c.title, "expected_result": c.expected_result,
                            "automatic_status": c.automatic_status, "automatic_detail": c.automatic_detail,
                            "evidence_ref": c.evidence_ref, "residual_defects": c.residual_defects,
                            "corrective_action": c.corrective_action, "verification_status": c.verification_status,
                            "verification_note": c.verification_note} for c in checks]}

    @app.get("/api/staff/launch-controls")
    def list_launches():
        user, denied = actor("launch_read")
        if denied: return denied
        rows = OperationLaunch.query.order_by(OperationLaunch.updated_at.desc()).all(); data=[as_dict(x) for x in rows]; db.session.commit()
        return jsonify(launches=data)

    @app.post("/api/staff/launch-controls")
    def create_launch():
        user, denied = actor("launch_manage")
        if denied: return denied
        data=request.get_json(silent=True) or {}
        try: analysis_id=int(data.get("analysis_id"))
        except (TypeError,ValueError): return jsonify(error="Analisi non valida."),400
        Analysis=(app.extensions.get("aplsai_feasibility") or {}).get("FeasibilityAnalysis")
        analysis=db.session.get(Analysis,analysis_id) if Analysis else None
        if not analysis or analysis.archived_at: return jsonify(error="Analisi non disponibile."),404
        if OperationLaunch.query.filter_by(analysis_id=analysis_id).first(): return jsonify(error="Controllo di avvio già presente."),409
        row=OperationLaunch(analysis_id=analysis_id,assigned_to_user_id=user.id);db.session.add(row);db.session.flush();ensure_checks(row);event(row,user,"Controllo avvio creato");out=as_dict(row);db.session.commit();return jsonify(launch=out),201

    @app.patch("/api/staff/launch-checks/<int:check_id>")
    def update_check(check_id):
        user, denied = actor("launch_manage")
        if denied:return denied
        check=db.session.get(LaunchCheck,check_id)
        if not check:return jsonify(error="Controllo non trovato."),404
        data=request.get_json(silent=True) or {}
        for key,limit in (("evidence_ref",500),("residual_defects",5000),("corrective_action",5000)):
            if key in data:setattr(check,key,app_module.clean_text(data.get(key),limit))
        row=db.session.get(OperationLaunch,check.launch_id);event(row,user,"Evidenza aggiornata",check.code);out=as_dict(row);db.session.commit();return jsonify(launch=out)

    @app.post("/api/admin/launch-checks/<int:check_id>/verify")
    def verify_check(check_id):
        user, denied=actor("launch_approve")
        if denied:return denied
        check=db.session.get(LaunchCheck,check_id)
        if not check:return jsonify(error="Controllo non trovato."),404
        row=db.session.get(OperationLaunch,check.launch_id);refresh(row);data=request.get_json(silent=True) or {}; approved=data.get("approved") is True
        if approved and (check.automatic_status!="Superato" or not check.evidence_ref or check.residual_defects): return jsonify(error="Verifica bloccata: requisito automatico, evidenza o difetti residui non conformi."),409
        check.verification_status="Approvata" if approved else "Respinta";check.verification_note=app_module.clean_text(data.get("note"),5000);check.verified_by_user_id=user.id;check.verified_at=utcnow();event(row,user,"Verifica Admin",check.code+" "+check.verification_status);out=as_dict(row);db.session.commit();return jsonify(launch=out)

    @app.post("/api/admin/launch-controls/<int:launch_id>/authorize")
    def authorize_launch(launch_id):
        user, denied=actor("launch_approve")
        if denied:return denied
        row=db.session.get(OperationLaunch,launch_id)
        if not row:return jsonify(error="Controllo di avvio non trovato."),404
        out=as_dict(row);data=request.get_json(silent=True) or {};note=app_module.clean_text(data.get("note"),5000)
        if out["status"]!="Pronto all’autorizzazione" or not note:return jsonify(error="Avvio bloccato: completare tutti i controlli e inserire il verbale finale."),409
        row.final_decision="AVVIO AUTORIZZATO";row.final_note=note;row.authorized_by_user_id=user.id;row.authorized_at=utcnow();row.status="Autorizzato";row.version+=1;event(row,user,"Avvio autorizzato",note);db.session.commit();return jsonify(launch=as_dict(row))

    app.extensions["aplsai_launch_control"]={"OperationLaunch":OperationLaunch,"LaunchCheck":LaunchCheck,"LaunchEvent":LaunchEvent}
