from datetime import datetime, timezone

from flask import jsonify, request, session

from .rbac import has_permission


PROJECT_STATUSES = {"Aperto", "In corso", "Sospeso", "Completato", "Chiuso"}
PHASE_STATUSES = {"Da pianificare", "In corso", "Da collaudare", "In verifica", "Approvata", "Respinta"}
TEST_RESULTS = {"Da eseguire", "Superata", "Non superata", "Bloccata"}
TECHNICAL_RESULTS = {"Da verificare", "Conforme", "Non conforme"}
VARIATION_STATUSES = {"Proposta", "In verifica", "Approvata", "Respinta"}


def utcnow():
    return datetime.now(timezone.utc)


def parse_date(value):
    if value in {None, ""}:
        return None
    out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return out.replace(tzinfo=timezone.utc) if not out.tzinfo else out.astimezone(timezone.utc)


def init_worksites(app, app_module):
    if app.extensions.get("aplsai_worksites"):
        return
    db = app_module.db

    class WorksiteProject(db.Model):
        __tablename__ = "worksite_project"
        id = db.Column(db.Integer, primary_key=True)
        launch_id = db.Column(db.Integer, unique=True, nullable=False, index=True)
        analysis_id = db.Column(db.Integer, nullable=False, index=True)
        name = db.Column(db.String(220), nullable=False)
        status = db.Column(db.String(40), nullable=False, default="Aperto")
        responsible_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        technical_validator = db.Column(db.String(220), nullable=False, default="")
        initial_budget = db.Column(db.Float, nullable=False, default=0)
        planned_start_at = db.Column(db.DateTime(timezone=True))
        planned_end_at = db.Column(db.DateTime(timezone=True))
        actual_start_at = db.Column(db.DateTime(timezone=True))
        actual_end_at = db.Column(db.DateTime(timezone=True))
        closing_evidence = db.Column(db.String(500), nullable=False, default="")
        closing_note = db.Column(db.Text, nullable=False, default="")
        closed_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        version = db.Column(db.Integer, nullable=False, default=1)
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    class WorksitePhase(db.Model):
        __tablename__ = "worksite_phase"
        id = db.Column(db.Integer, primary_key=True)
        project_id = db.Column(db.Integer, db.ForeignKey("worksite_project.id"), nullable=False, index=True)
        milestone_id = db.Column(db.Integer, nullable=True, index=True)
        code = db.Column(db.String(30), nullable=False)
        title = db.Column(db.String(220), nullable=False)
        description = db.Column(db.Text, nullable=False, default="")
        responsible_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        supplier_name = db.Column(db.String(220), nullable=False, default="")
        supplier_contact = db.Column(db.String(220), nullable=False, default="")
        planned_start_at = db.Column(db.DateTime(timezone=True))
        planned_end_at = db.Column(db.DateTime(timezone=True))
        actual_start_at = db.Column(db.DateTime(timezone=True))
        actual_end_at = db.Column(db.DateTime(timezone=True))
        planned_cost = db.Column(db.Float, nullable=False, default=0)
        committed_cost = db.Column(db.Float, nullable=False, default=0)
        spent_cost = db.Column(db.Float, nullable=False, default=0)
        cost_to_complete = db.Column(db.Float, nullable=False, default=0)
        progress_percent = db.Column(db.Float, nullable=False, default=0)
        status = db.Column(db.String(40), nullable=False, default="Da pianificare")
        acceptance_threshold = db.Column(db.Text, nullable=False, default="")
        test_result = db.Column(db.String(40), nullable=False, default="Da eseguire")
        observed_result = db.Column(db.Text, nullable=False, default="")
        evidence_ref = db.Column(db.String(500), nullable=False, default="")
        nonconformities = db.Column(db.Text, nullable=False, default="")
        critical_defects = db.Column(db.Text, nullable=False, default="")
        residual_defects = db.Column(db.Text, nullable=False, default="")
        mandatory_actions = db.Column(db.Text, nullable=False, default="")
        action_owner = db.Column(db.String(220), nullable=False, default="")
        action_due_at = db.Column(db.DateTime(timezone=True))
        transition_conditions = db.Column(db.Text, nullable=False, default="")
        technical_validation = db.Column(db.String(40), nullable=False, default="Da verificare")
        admin_decision = db.Column(db.String(40), nullable=False, default="Da verificare")
        admin_note = db.Column(db.Text, nullable=False, default="")
        verified_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        verified_at = db.Column(db.DateTime(timezone=True))
        next_review_at = db.Column(db.DateTime(timezone=True))
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
        __table_args__ = (db.UniqueConstraint("project_id", "code", name="uq_worksite_phase_code"),)

    class WorksiteVariation(db.Model):
        __tablename__ = "worksite_variation"
        id = db.Column(db.Integer, primary_key=True)
        project_id = db.Column(db.Integer, db.ForeignKey("worksite_project.id"), nullable=False, index=True)
        phase_id = db.Column(db.Integer, db.ForeignKey("worksite_phase.id"), nullable=True, index=True)
        code = db.Column(db.String(30), nullable=False)
        description = db.Column(db.Text, nullable=False)
        reason = db.Column(db.Text, nullable=False)
        cost_impact = db.Column(db.Float, nullable=False, default=0)
        delay_days = db.Column(db.Integer, nullable=False, default=0)
        margin_impact = db.Column(db.Float, nullable=False, default=0)
        evidence_ref = db.Column(db.String(500), nullable=False, default="")
        status = db.Column(db.String(40), nullable=False, default="Proposta")
        requested_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        decided_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        decision_note = db.Column(db.Text, nullable=False, default="")
        decided_at = db.Column(db.DateTime(timezone=True))
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
        __table_args__ = (db.UniqueConstraint("project_id", "code", name="uq_worksite_variation_code"),)

    class WorksiteEvent(db.Model):
        __tablename__ = "worksite_event"
        id = db.Column(db.Integer, primary_key=True)
        project_id = db.Column(db.Integer, db.ForeignKey("worksite_project.id"), nullable=False, index=True)
        phase_id = db.Column(db.Integer)
        variation_id = db.Column(db.Integer)
        actor_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        action = db.Column(db.String(100), nullable=False)
        detail = db.Column(db.String(500), nullable=False, default="")
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    with app.app_context():
        db.create_all()

    def actor(permission):
        user = db.session.get(app_module.User, session.get("uid")) if session.get("uid") else None
        if not user:
            return None, (jsonify(error="Non autenticato."), 401)
        if not has_permission(user.role, permission):
            return None, (jsonify(error="Permesso insufficiente."), 403)
        return user, None

    def can_access(user, project):
        return user.role in {"admin", "staff"} or project.responsible_user_id == user.id or WorksitePhase.query.filter_by(project_id=project.id, responsible_user_id=user.id).first() is not None

    def event(project, user, action, detail="", phase=None, variation=None):
        db.session.add(WorksiteEvent(project_id=project.id, phase_id=phase.id if phase else None,
                                     variation_id=variation.id if variation else None, actor_user_id=user.id,
                                     action=action, detail=app_module.clean_text(detail, 500)))

    def phase_dict(row):
        owner = db.session.get(app_module.User, row.responsible_user_id)
        return {"id": row.id, "project_id": row.project_id, "milestone_id": row.milestone_id,
                "code": row.code, "title": row.title, "description": row.description,
                "responsible_user_id": row.responsible_user_id, "responsible_name": owner.name if owner else "",
                "supplier_name": row.supplier_name, "supplier_contact": row.supplier_contact,
                "planned_start_at": row.planned_start_at.isoformat() if row.planned_start_at else None,
                "planned_end_at": row.planned_end_at.isoformat() if row.planned_end_at else None,
                "actual_start_at": row.actual_start_at.isoformat() if row.actual_start_at else None,
                "actual_end_at": row.actual_end_at.isoformat() if row.actual_end_at else None,
                "planned_cost": row.planned_cost, "committed_cost": row.committed_cost,
                "spent_cost": row.spent_cost, "cost_to_complete": row.cost_to_complete,
                "progress_percent": row.progress_percent, "status": row.status,
                "acceptance_threshold": row.acceptance_threshold, "test_result": row.test_result,
                "observed_result": row.observed_result, "evidence_ref": row.evidence_ref,
                "nonconformities": row.nonconformities, "critical_defects": row.critical_defects,
                "residual_defects": row.residual_defects, "mandatory_actions": row.mandatory_actions,
                "action_owner": row.action_owner,
                "action_due_at": row.action_due_at.isoformat() if row.action_due_at else None,
                "transition_conditions": row.transition_conditions, "technical_validation": row.technical_validation,
                "admin_decision": row.admin_decision, "admin_note": row.admin_note,
                "verified_at": row.verified_at.isoformat() if row.verified_at else None,
                "next_review_at": row.next_review_at.isoformat() if row.next_review_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None}

    def variation_dict(row):
        return {"id": row.id, "project_id": row.project_id, "phase_id": row.phase_id, "code": row.code,
                "description": row.description, "reason": row.reason, "cost_impact": row.cost_impact,
                "delay_days": row.delay_days, "margin_impact": row.margin_impact,
                "evidence_ref": row.evidence_ref, "status": row.status,
                "decision_note": row.decision_note,
                "decided_at": row.decided_at.isoformat() if row.decided_at else None,
                "created_at": row.created_at.isoformat() if row.created_at else None}

    def project_dict(row, include_history=False):
        phases = WorksitePhase.query.filter_by(project_id=row.id).order_by(WorksitePhase.code).all()
        variations = WorksiteVariation.query.filter_by(project_id=row.id).order_by(WorksiteVariation.created_at.desc()).all()
        owner = db.session.get(app_module.User, row.responsible_user_id)
        launch = db.session.get((app.extensions.get("aplsai_launch_control") or {}).get("OperationLaunch"), row.launch_id)
        analysis = None
        if launch:
            Analysis = (app.extensions.get("aplsai_feasibility") or {}).get("FeasibilityAnalysis")
            analysis = db.session.get(Analysis, launch.analysis_id) if Analysis else None
        committed = sum(x.committed_cost for x in phases)
        spent = sum(x.spent_cost for x in phases)
        remaining = sum(x.cost_to_complete for x in phases)
        approved_variations = sum(x.cost_impact for x in variations if x.status == "Approvata")
        planned = sum(x.planned_cost for x in phases)
        forecast = max(spent + remaining, planned + approved_variations)
        progress = round(sum(x.progress_percent * max(x.planned_cost, 1) for x in phases) /
                         sum(max(x.planned_cost, 1) for x in phases), 1) if phases else 0
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        alerts = []
        if forecast > row.initial_budget:
            alerts.append(f"Previsione finale superiore al budget di € {forecast-row.initial_budget:,.2f}")
        if committed > row.initial_budget:
            alerts.append("Costi impegnati superiori al budget iniziale")
        if spent > committed:
            alerts.append("Spese effettive superiori ai costi impegnati")
        if any(x.planned_end_at and x.planned_end_at.replace(tzinfo=None) < now and x.status not in {"Approvata"} for x in phases):
            alerts.append("Una o più fasi sono in ritardo")
        if any(x.critical_defects for x in phases):
            alerts.append("Sono presenti difetti critici")
        if any(x.status in {"Proposta", "In verifica"} for x in variations):
            alerts.append("Sono presenti varianti da decidere")
        if any(not x.evidence_ref and x.status in {"Da collaudare", "In verifica"} for x in phases):
            alerts.append("Mancano evidenze per una o più fasi")
        if progress and spent > row.initial_budget * progress / 100 * 1.15:
            alerts.append("Costo sostenuto oltre il 15% rispetto all’avanzamento")
        prop = db.session.get(app_module.Property, analysis.property_id) if analysis else None
        data = {"id": row.id, "launch_id": row.launch_id, "analysis_id": row.analysis_id,
                "analysis_name": analysis.name if analysis else "", "property_ref": prop.ref if prop else "",
                "name": row.name, "status": row.status, "responsible_user_id": row.responsible_user_id,
                "responsible_name": owner.name if owner else "", "technical_validator": row.technical_validator,
                "initial_budget": row.initial_budget, "planned_start_at": row.planned_start_at.isoformat() if row.planned_start_at else None,
                "planned_end_at": row.planned_end_at.isoformat() if row.planned_end_at else None,
                "actual_start_at": row.actual_start_at.isoformat() if row.actual_start_at else None,
                "actual_end_at": row.actual_end_at.isoformat() if row.actual_end_at else None,
                "closing_evidence": row.closing_evidence, "closing_note": row.closing_note,
                "version": row.version, "progress_percent": progress, "committed_cost": committed,
                "spent_cost": spent, "cost_to_complete": remaining, "approved_variations": approved_variations,
                "forecast_final_cost": forecast, "budget_remaining": row.initial_budget-forecast,
                "alerts": alerts, "phases": [phase_dict(x) for x in phases],
                "variations": [variation_dict(x) for x in variations],
                "updated_at": row.updated_at.isoformat() if row.updated_at else None}
        if include_history:
            data["events"] = [{"id": x.id, "action": x.action, "detail": x.detail,
                               "actor_user_id": x.actor_user_id, "created_at": x.created_at.isoformat()}
                              for x in WorksiteEvent.query.filter_by(project_id=row.id).order_by(WorksiteEvent.id.desc()).all()]
        return data

    def apply_phase_data(row, data):
        text_fields = (("title", 220), ("description", 5000), ("supplier_name", 220),
                       ("supplier_contact", 220), ("acceptance_threshold", 5000),
                       ("observed_result", 5000), ("evidence_ref", 500), ("nonconformities", 5000),
                       ("critical_defects", 5000), ("residual_defects", 5000),
                       ("mandatory_actions", 5000), ("action_owner", 220),
                       ("transition_conditions", 5000))
        for key, limit in text_fields:
            if key in data:
                setattr(row, key, app_module.clean_text(data.get(key), limit))
        for key in ("planned_cost", "committed_cost", "spent_cost", "cost_to_complete", "progress_percent"):
            if key in data:
                value = float(data.get(key) or 0)
                if value < 0 or (key == "progress_percent" and value > 100):
                    raise ValueError("Valore economico o avanzamento non valido.")
                setattr(row, key, value)
        for key in ("planned_start_at", "planned_end_at", "actual_start_at", "actual_end_at", "action_due_at", "next_review_at"):
            if key in data:
                setattr(row, key, parse_date(data.get(key)))
        if "status" in data:
            if data["status"] not in PHASE_STATUSES - {"Approvata"}:
                raise ValueError("Stato fase non valido.")
            row.status = data["status"]
        if "test_result" in data:
            if data["test_result"] not in TEST_RESULTS:
                raise ValueError("Esito prova non valido.")
            row.test_result = data["test_result"]
        if "technical_validation" in data:
            if data["technical_validation"] not in TECHNICAL_RESULTS:
                raise ValueError("Validazione tecnica non valida.")
            row.technical_validation = data["technical_validation"]
        if "responsible_user_id" in data:
            uid = int(data["responsible_user_id"])
            user = db.session.get(app_module.User, uid)
            if not user or user.role not in {"admin", "staff", "operator"} or getattr(user, "active", True) is False:
                raise ValueError("Responsabile non valido.")
            row.responsible_user_id = uid
        if "milestone_id" in data:
            milestone_id = int(data["milestone_id"]) if data.get("milestone_id") else None
            Milestone = (app.extensions.get("aplsai_cash_controls") or {}).get("CashMilestone")
            if milestone_id and (not Milestone or not db.session.get(Milestone, milestone_id)):
                raise ValueError("SAL collegato non valido.")
            row.milestone_id = milestone_id

    @app.get("/api/staff/worksites")
    def list_worksites():
        user, denied = actor("worksite_read")
        if denied:
            return denied
        rows = WorksiteProject.query.order_by(WorksiteProject.updated_at.desc()).all()
        rows = [x for x in rows if can_access(user, x)]
        return jsonify(worksites=[project_dict(x) for x in rows])

    @app.get("/api/staff/worksites/<int:project_id>")
    def get_worksite(project_id):
        user, denied = actor("worksite_read")
        if denied:
            return denied
        row = db.session.get(WorksiteProject, project_id)
        if not row or not can_access(user, row):
            return jsonify(error="Cantiere non trovato."), 404
        return jsonify(worksite=project_dict(row, include_history=True))

    @app.post("/api/staff/worksites")
    def create_worksite():
        user, denied = actor("worksite_manage")
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        try:
            launch_id = int(data.get("launch_id")); initial_budget = float(data.get("initial_budget") or 0)
        except (TypeError, ValueError):
            return jsonify(error="Avvio o budget non valido."), 400
        Launch = (app.extensions.get("aplsai_launch_control") or {}).get("OperationLaunch")
        launch = db.session.get(Launch, launch_id) if Launch else None
        if not launch or launch.final_decision != "AVVIO AUTORIZZATO":
            return jsonify(error="Il cantiere può essere aperto solo dopo l’autorizzazione finale dell’avvio."), 409
        if WorksiteProject.query.filter_by(launch_id=launch_id).first():
            return jsonify(error="Cantiere già aperto per questa operazione."), 409
        if initial_budget <= 0:
            return jsonify(error="Il budget iniziale deve essere maggiore di zero."), 400
        try:
            responsible_id = int(data.get("responsible_user_id") or user.id)
            responsible = db.session.get(app_module.User, responsible_id)
            if not responsible or responsible.role not in {"admin", "staff", "operator"}:
                raise ValueError
            name = app_module.clean_text(data.get("name"), 220) or f"Cantiere operazione {launch.analysis_id}"
            row = WorksiteProject(launch_id=launch.id, analysis_id=launch.analysis_id, name=name,
                                  responsible_user_id=responsible_id, initial_budget=initial_budget,
                                  technical_validator=app_module.clean_text(data.get("technical_validator"), 220),
                                  planned_start_at=parse_date(data.get("planned_start_at")),
                                  planned_end_at=parse_date(data.get("planned_end_at")))
        except (TypeError, ValueError):
            return jsonify(error="Dati del cantiere non validi."), 400
        db.session.add(row); db.session.flush(); event(row, user, "Cantiere aperto", name); db.session.commit()
        return jsonify(worksite=project_dict(row, include_history=True)), 201

    @app.patch("/api/staff/worksites/<int:project_id>")
    def update_worksite(project_id):
        user, denied = actor("worksite_manage")
        if denied:
            return denied
        row = db.session.get(WorksiteProject, project_id)
        if not row or not can_access(user, row):
            return jsonify(error="Cantiere non trovato."), 404
        data = request.get_json(silent=True) or {}
        try:
            if "status" in data:
                if data["status"] not in PROJECT_STATUSES - {"Chiuso"}:
                    raise ValueError
                row.status = data["status"]
            if "initial_budget" in data:
                budget = float(data["initial_budget"])
                if budget <= 0: raise ValueError
                row.initial_budget = budget
            for key, limit in (("name", 220), ("technical_validator", 220)):
                if key in data: setattr(row, key, app_module.clean_text(data.get(key), limit))
            for key in ("planned_start_at", "planned_end_at", "actual_start_at", "actual_end_at"):
                if key in data: setattr(row, key, parse_date(data.get(key)))
        except (TypeError, ValueError):
            return jsonify(error="Aggiornamento cantiere non valido."), 400
        row.version += 1; event(row, user, "Cantiere aggiornato", data.get("change_note", "")); db.session.commit()
        return jsonify(worksite=project_dict(row, include_history=True))

    @app.post("/api/staff/worksites/<int:project_id>/phases")
    def create_phase(project_id):
        user, denied = actor("worksite_manage")
        if denied: return denied
        project = db.session.get(WorksiteProject, project_id)
        if not project or not can_access(user, project): return jsonify(error="Cantiere non trovato."), 404
        data = request.get_json(silent=True) or {}; code = app_module.clean_text(data.get("code"), 30).upper()
        title = app_module.clean_text(data.get("title"), 220)
        if not code or not title: return jsonify(error="Codice e titolo della fase sono obbligatori."), 400
        if WorksitePhase.query.filter_by(project_id=project.id, code=code).first(): return jsonify(error="Codice fase già presente."), 409
        row = WorksitePhase(project_id=project.id, code=code, title=title, responsible_user_id=user.id)
        try: apply_phase_data(row, data)
        except (TypeError, ValueError) as exc: return jsonify(error=str(exc) or "Dati fase non validi."), 400
        db.session.add(row); db.session.flush(); event(project, user, "Fase creata", code, phase=row); db.session.commit()
        return jsonify(worksite=project_dict(project, include_history=True)), 201

    @app.patch("/api/staff/worksite-phases/<int:phase_id>")
    def update_phase(phase_id):
        user, denied = actor("worksite_manage")
        if denied: return denied
        row = db.session.get(WorksitePhase, phase_id); project = db.session.get(WorksiteProject, row.project_id) if row else None
        if not row or not project or not can_access(user, project): return jsonify(error="Fase non trovata."), 404
        if user.role not in {"admin", "staff"} and row.responsible_user_id != user.id: return jsonify(error="Puoi aggiornare solo le fasi assegnate a te."), 403
        data = request.get_json(silent=True) or {}
        try: apply_phase_data(row, data)
        except (TypeError, ValueError) as exc: return jsonify(error=str(exc) or "Dati fase non validi."), 400
        row.admin_decision = "Da verificare"; row.verified_by_user_id = None; row.verified_at = None
        event(project, user, "Fase aggiornata", row.code, phase=row); db.session.commit()
        return jsonify(worksite=project_dict(project, include_history=True))

    @app.post("/api/admin/worksite-phases/<int:phase_id>/decision")
    def decide_phase(phase_id):
        user, denied = actor("worksite_approve")
        if denied: return denied
        row = db.session.get(WorksitePhase, phase_id); project = db.session.get(WorksiteProject, row.project_id) if row else None
        if not row or not project: return jsonify(error="Fase non trovata."), 404
        data = request.get_json(silent=True) or {}; approved = data.get("approved") is True
        note = app_module.clean_text(data.get("note"), 5000)
        if approved:
            errors = []
            if row.progress_percent != 100: errors.append("avanzamento non al 100%")
            if not row.acceptance_threshold or not row.evidence_ref or not row.observed_result: errors.append("prove o evidenze incomplete")
            if row.test_result != "Superata" or row.technical_validation != "Conforme": errors.append("collaudo o validazione tecnica non conforme")
            if row.critical_defects: errors.append("difetti critici aperti")
            if row.residual_defects and (not row.mandatory_actions or not row.action_owner or not row.action_due_at): errors.append("difetti residui senza piano correttivo")
            if errors: return jsonify(error="Approvazione bloccata: " + "; ".join(errors) + "."), 409
        elif not note:
            return jsonify(error="Indica le correzioni richieste."), 400
        row.admin_decision = "Approvata" if approved else "Respinta"; row.status = row.admin_decision
        row.admin_note = note; row.verified_by_user_id = user.id; row.verified_at = utcnow()
        if approved and not row.actual_end_at: row.actual_end_at = utcnow()
        event(project, user, "Decisione fase", f"{row.code}: {row.admin_decision}", phase=row); db.session.commit()
        return jsonify(worksite=project_dict(project, include_history=True))

    @app.post("/api/staff/worksites/<int:project_id>/variations")
    def create_variation(project_id):
        user, denied = actor("worksite_manage")
        if denied: return denied
        project = db.session.get(WorksiteProject, project_id)
        if not project or not can_access(user, project): return jsonify(error="Cantiere non trovato."), 404
        data = request.get_json(silent=True) or {}; code = app_module.clean_text(data.get("code"), 30).upper()
        description = app_module.clean_text(data.get("description"), 5000); reason = app_module.clean_text(data.get("reason"), 5000)
        if not code or not description or not reason: return jsonify(error="Codice, descrizione e motivo della variante sono obbligatori."), 400
        if WorksiteVariation.query.filter_by(project_id=project.id, code=code).first(): return jsonify(error="Codice variante già presente."), 409
        try:
            cost = float(data.get("cost_impact") or 0); days = int(data.get("delay_days") or 0); margin = float(data.get("margin_impact") or 0)
            phase_id = int(data["phase_id"]) if data.get("phase_id") else None
        except (TypeError, ValueError): return jsonify(error="Impatto della variante non valido."), 400
        if phase_id and not WorksitePhase.query.filter_by(id=phase_id, project_id=project.id).first(): return jsonify(error="Fase collegata non valida."), 400
        row = WorksiteVariation(project_id=project.id, phase_id=phase_id, code=code, description=description,
                                reason=reason, cost_impact=cost, delay_days=days, margin_impact=margin,
                                evidence_ref=app_module.clean_text(data.get("evidence_ref"), 500), requested_by_user_id=user.id)
        db.session.add(row); db.session.flush(); event(project, user, "Variante proposta", code, variation=row); db.session.commit()
        return jsonify(worksite=project_dict(project, include_history=True)), 201

    @app.post("/api/admin/worksite-variations/<int:variation_id>/decision")
    def decide_variation(variation_id):
        user, denied = actor("worksite_approve")
        if denied: return denied
        row = db.session.get(WorksiteVariation, variation_id); project = db.session.get(WorksiteProject, row.project_id) if row else None
        if not row or not project: return jsonify(error="Variante non trovata."), 404
        data = request.get_json(silent=True) or {}; approved = data.get("approved") is True; note = app_module.clean_text(data.get("note"), 5000)
        if approved and (not row.evidence_ref or not note): return jsonify(error="Evidenza e motivazione della decisione sono obbligatorie."), 409
        if not approved and not note: return jsonify(error="Indica il motivo del rifiuto."), 400
        row.status = "Approvata" if approved else "Respinta"; row.decision_note = note
        row.decided_by_user_id = user.id; row.decided_at = utcnow()
        event(project, user, "Decisione variante", f"{row.code}: {row.status}", variation=row); db.session.commit()
        return jsonify(worksite=project_dict(project, include_history=True))

    @app.post("/api/admin/worksites/<int:project_id>/close")
    def close_worksite(project_id):
        user, denied = actor("worksite_approve")
        if denied: return denied
        row = db.session.get(WorksiteProject, project_id)
        if not row: return jsonify(error="Cantiere non trovato."), 404
        data = request.get_json(silent=True) or {}; evidence = app_module.clean_text(data.get("evidence_ref"), 500); note = app_module.clean_text(data.get("note"), 5000)
        phases = WorksitePhase.query.filter_by(project_id=row.id).all(); pending = WorksiteVariation.query.filter_by(project_id=row.id).filter(WorksiteVariation.status.in_(["Proposta", "In verifica"])).count()
        if not phases or any(x.admin_decision != "Approvata" or x.critical_defects or x.residual_defects for x in phases) or pending or not evidence or not note:
            return jsonify(error="Chiusura bloccata: approvare tutte le fasi, eliminare i difetti, decidere le varianti e allegare verbale ed evidenza."), 409
        row.status = "Chiuso"; row.actual_end_at = utcnow(); row.closing_evidence = evidence; row.closing_note = note
        row.closed_by_user_id = user.id; row.version += 1; event(row, user, "Cantiere chiuso", note); db.session.commit()
        return jsonify(worksite=project_dict(row, include_history=True))

    app.extensions["aplsai_worksites"] = {"WorksiteProject": WorksiteProject, "WorksitePhase": WorksitePhase,
                                           "WorksiteVariation": WorksiteVariation, "WorksiteEvent": WorksiteEvent,
                                           "project_dict": project_dict}
