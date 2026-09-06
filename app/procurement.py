from datetime import datetime, timezone

from flask import jsonify, request, session

from .rbac import has_permission


CASE_TYPES = {"Software e tecnologia", "Lavori e forniture"}
CASE_STATUSES = {"Bozza", "Raccolta offerte", "In valutazione", "Decisa", "Annullata"}
CAPACITY_STATUSES = {"Da verificare", "Disponibile", "Parzialmente disponibile", "Piena capacità", "Non disponibile"}
REVIEW_STATUSES = {"Da valutare", "In verifica", "Verificata", "Respinta"}
SOFTWARE_WEIGHTS = {
    "functional_score": 20, "technical_score": 15, "ai_data_score": 10, "cybersecurity_score": 10,
    "ip_score": 15, "team_score": 10, "capacity_score": 10, "tco_score": 10,
}


def utcnow(): return datetime.now(timezone.utc)


def init_procurement(app, app_module):
    if app.extensions.get("aplsai_procurement"): return
    db = app_module.db

    class ProcurementCase(db.Model):
        __tablename__ = "procurement_case"
        id = db.Column(db.Integer, primary_key=True)
        title = db.Column(db.String(220), nullable=False)
        case_type = db.Column(db.String(80), nullable=False)
        requirement_ref = db.Column(db.String(500), nullable=False)
        common_specification = db.Column(db.Text, nullable=False)
        quantity_scope = db.Column(db.Text, nullable=False, default="")
        technical_requirements = db.Column(db.Text, nullable=False, default="")
        budget_reference = db.Column(db.Float, nullable=False, default=0)
        budget_source = db.Column(db.String(500), nullable=False, default="")
        status = db.Column(db.String(40), nullable=False, default="Bozza")
        selected_offer_id = db.Column(db.Integer)
        decision_note = db.Column(db.Text, nullable=False, default="")
        decision_evidence = db.Column(db.String(500), nullable=False, default="")
        decided_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        decided_at = db.Column(db.DateTime(timezone=True))
        version = db.Column(db.Integer, nullable=False, default=1)
        created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    class ProcurementOffer(db.Model):
        __tablename__ = "procurement_offer"
        id = db.Column(db.Integer, primary_key=True)
        case_id = db.Column(db.Integer, db.ForeignKey("procurement_case.id"), nullable=False, index=True)
        partner_id = db.Column(db.Integer, db.ForeignKey("partner_registry.id"), nullable=False, index=True)
        offer_ref = db.Column(db.String(500), nullable=False, default="")
        modules_detail = db.Column(db.Text, nullable=False, default="")
        deliverables = db.Column(db.Text, nullable=False, default="")
        duration_days = db.Column(db.Integer, nullable=False, default=0)
        person_days = db.Column(db.Float, nullable=False, default=0)
        profiles_rates = db.Column(db.Text, nullable=False, default="")
        technologies = db.Column(db.Text, nullable=False, default="")
        dependencies = db.Column(db.Text, nullable=False, default="")
        exclusions = db.Column(db.Text, nullable=False, default="")
        assumptions = db.Column(db.Text, nullable=False, default="")
        vat_note = db.Column(db.String(300), nullable=False, default="")
        payment_milestones = db.Column(db.Text, nullable=False, default="")
        one_time_cost = db.Column(db.Float, nullable=False, default=0)
        recurring_monthly_cost = db.Column(db.Float, nullable=False, default=0)
        maintenance_24m = db.Column(db.Float, nullable=False, default=0)
        cloud_24m = db.Column(db.Float, nullable=False, default=0)
        ai_24m = db.Column(db.Float, nullable=False, default=0)
        licenses_24m = db.Column(db.Float, nullable=False, default=0)
        third_party_24m = db.Column(db.Float, nullable=False, default=0)
        subcontractors_24m = db.Column(db.Float, nullable=False, default=0)
        estimated_excluded_costs = db.Column(db.Float, nullable=False, default=0)
        capacity_status = db.Column(db.String(60), nullable=False, default="Da verificare")
        capacity_evidence = db.Column(db.String(500), nullable=False, default="")
        repository_aplsai = db.Column(db.Boolean, nullable=False, default=False)
        accounts_aplsai = db.Column(db.Boolean, nullable=False, default=False)
        documentation_transferable = db.Column(db.Boolean, nullable=False, default=False)
        third_party_separable = db.Column(db.Boolean, nullable=False, default=False)
        ai_replaceable = db.Column(db.Boolean, nullable=False, default=False)
        exit_clause = db.Column(db.Boolean, nullable=False, default=False)
        functional_score = db.Column(db.Float)
        technical_score = db.Column(db.Float)
        ai_data_score = db.Column(db.Float)
        cybersecurity_score = db.Column(db.Float)
        ip_score = db.Column(db.Float)
        team_score = db.Column(db.Float)
        capacity_score = db.Column(db.Float)
        tco_score = db.Column(db.Float)
        score_evidence = db.Column(db.String(500), nullable=False, default="")
        review_status = db.Column(db.String(40), nullable=False, default="Da valutare")
        review_note = db.Column(db.Text, nullable=False, default="")
        reviewed_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        reviewed_at = db.Column(db.DateTime(timezone=True))
        created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    class ProcurementEvent(db.Model):
        __tablename__ = "procurement_event"
        id = db.Column(db.Integer, primary_key=True)
        case_id = db.Column(db.Integer, db.ForeignKey("procurement_case.id"), nullable=False, index=True)
        offer_id = db.Column(db.Integer)
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

    def event(case, user, action, detail="", offer=None):
        db.session.add(ProcurementEvent(case_id=case.id, offer_id=offer.id if offer else None,
                                        actor_user_id=user.id, action=action, detail=app_module.clean_text(detail, 500)))

    def active_concentration(partner_id):
        ext = app.extensions.get("aplsai_partners") or {}; Assignment = ext.get("PartnerAssignment")
        if not Assignment: return {"active_assignments": 0, "share_percent": 0, "notice": "Dati incarichi non disponibili."}
        active = Assignment.query.filter(Assignment.status.in_(["Confermato", "In corso", "Consegnato"])).all()
        own = sum(1 for row in active if row.partner_id == partner_id)
        share = round(own * 100 / len(active), 1) if active else 0
        notice = "Partner presente su più incarichi attivi: verificare concentrazione e capacità." if own > 1 else "Nessuna concentrazione multipla rilevata nei dati registrati."
        return {"active_assignments": own, "total_active_assignments": len(active), "share_percent": share, "notice": notice}

    def offer_missing(row):
        required = ((row.offer_ref, "documento offerta"), (row.modules_detail, "moduli/attività"),
                    (row.deliverables, "risultati"), (row.duration_days, "tempi"), (row.person_days, "giornate-uomo"),
                    (row.profiles_rates, "profili e tariffe"), (row.technologies, "tecnologie"),
                    (row.dependencies, "dipendenze"), (row.exclusions, "esclusioni"),
                    (row.assumptions, "assunzioni"), (row.vat_note, "trattamento IVA"),
                    (row.payment_milestones, "milestone e pagamenti"), (row.capacity_evidence, "evidenza capacità"))
        return [label for value, label in required if value in {None, "", 0}]

    def offer_dict(row, case_type=None):
        case_type = case_type or db.session.get(ProcurementCase, row.case_id).case_type
        tco = (row.one_time_cost + row.recurring_monthly_cost * 24 + row.maintenance_24m + row.cloud_24m +
               row.ai_24m + row.licenses_24m + row.third_party_24m + row.subcontractors_24m + row.estimated_excluded_costs)
        missing = offer_missing(row)
        lock_missing = [label for ok, label in ((row.repository_aplsai, "repository/codice sotto controllo APLSAI"),
                       (row.accounts_aplsai, "account sotto controllo APLSAI"),
                       (row.documentation_transferable, "documentazione trasferibile"),
                       (row.third_party_separable, "terze parti separabili"),
                       (row.ai_replaceable, "fornitore IA sostituibile"), (row.exit_clause, "clausola di uscita/subentro")) if not ok]
        scores = {key: getattr(row, key) for key in SOFTWARE_WEIGHTS}
        weighted = None
        if case_type == "Software e tecnologia" and all(value is not None for value in scores.values()):
            weighted = round(sum(scores[key] * weight for key, weight in SOFTWARE_WEIGHTS.items()) / 100, 2)
        partner_ext = app.extensions.get("aplsai_partners") or {}; Partner = partner_ext.get("Partner")
        partner = db.session.get(Partner, row.partner_id) if Partner else None
        return {"id": row.id, "case_id": row.case_id, "partner_id": row.partner_id,
                "partner_name": partner.name if partner else f"Partner {row.partner_id}", "offer_ref": row.offer_ref,
                "modules_detail": row.modules_detail, "deliverables": row.deliverables, "duration_days": row.duration_days,
                "person_days": row.person_days, "profiles_rates": row.profiles_rates, "technologies": row.technologies,
                "dependencies": row.dependencies, "exclusions": row.exclusions, "assumptions": row.assumptions,
                "vat_note": row.vat_note, "payment_milestones": row.payment_milestones,
                "one_time_cost": row.one_time_cost, "recurring_monthly_cost": row.recurring_monthly_cost,
                "maintenance_24m": row.maintenance_24m, "cloud_24m": row.cloud_24m, "ai_24m": row.ai_24m,
                "licenses_24m": row.licenses_24m, "third_party_24m": row.third_party_24m,
                "subcontractors_24m": row.subcontractors_24m, "estimated_excluded_costs": row.estimated_excluded_costs,
                "tco_24m": tco, "capacity_status": row.capacity_status, "capacity_evidence": row.capacity_evidence,
                "repository_aplsai": row.repository_aplsai, "accounts_aplsai": row.accounts_aplsai,
                "documentation_transferable": row.documentation_transferable, "third_party_separable": row.third_party_separable,
                "ai_replaceable": row.ai_replaceable, "exit_clause": row.exit_clause, "lock_in_missing": lock_missing,
                "scores": scores, "weighted_score": weighted, "score_evidence": row.score_evidence,
                "review_status": row.review_status, "review_note": row.review_note, "missing": missing,
                "completeness": "Completa" if not missing else "Incompleta", "concentration": active_concentration(row.partner_id),
                "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None}

    def case_dict(row, history=False):
        offers = ProcurementOffer.query.filter_by(case_id=row.id).order_by(ProcurementOffer.id).all()
        data = {"id": row.id, "title": row.title, "case_type": row.case_type, "requirement_ref": row.requirement_ref,
                "common_specification": row.common_specification, "quantity_scope": row.quantity_scope,
                "technical_requirements": row.technical_requirements, "budget_reference": row.budget_reference,
                "budget_source": row.budget_source, "status": row.status, "selected_offer_id": row.selected_offer_id,
                "decision_note": row.decision_note, "decision_evidence": row.decision_evidence,
                "decided_at": row.decided_at.isoformat() if row.decided_at else None, "version": row.version,
                "offers": [offer_dict(x, row.case_type) for x in offers]}
        if history: data["events"] = [{"id": x.id, "offer_id": x.offer_id, "actor_user_id": x.actor_user_id,
                                       "action": x.action, "detail": x.detail, "created_at": x.created_at.isoformat()}
                                      for x in ProcurementEvent.query.filter_by(case_id=row.id).order_by(ProcurementEvent.id.desc()).all()]
        return data

    @app.get("/api/staff/procurements")
    def list_cases():
        user, denied = actor("procurement_read")
        if denied: return denied
        return jsonify(cases=[case_dict(x) for x in ProcurementCase.query.order_by(ProcurementCase.id.desc()).all()],
                       software_weights=SOFTWARE_WEIGHTS)

    @app.get("/api/staff/procurements/<int:case_id>")
    def get_case(case_id):
        user, denied = actor("procurement_read")
        if denied: return denied
        row = db.session.get(ProcurementCase, case_id)
        return jsonify(case=case_dict(row, True), software_weights=SOFTWARE_WEIGHTS) if row else (jsonify(error="Confronto non trovato."), 404)

    @app.post("/api/staff/procurements")
    def create_case():
        user, denied = actor("procurement_manage")
        if denied: return denied
        data = request.get_json(silent=True) or {}; title = app_module.clean_text(data.get("title"), 220); kind = data.get("case_type")
        requirement = app_module.clean_text(data.get("requirement_ref"), 500); specification = app_module.clean_text(data.get("common_specification"), 10000)
        if not title or kind not in CASE_TYPES or not requirement or not specification:
            return jsonify(error="Titolo, tipo, riferimento requisiti e capitolato comune sono obbligatori."), 400
        try: budget_reference = max(0, float(data.get("budget_reference") or 0))
        except (TypeError, ValueError): return jsonify(error="Budget di riferimento non valido."), 400
        row = ProcurementCase(title=title, case_type=kind, requirement_ref=requirement, common_specification=specification,
                              quantity_scope=app_module.clean_text(data.get("quantity_scope"), 5000),
                              technical_requirements=app_module.clean_text(data.get("technical_requirements"), 10000),
                              budget_reference=budget_reference,
                              budget_source=app_module.clean_text(data.get("budget_source"), 500), created_by_user_id=user.id)
        db.session.add(row); db.session.flush(); event(row, user, "Confronto creato", requirement); db.session.commit()
        return jsonify(case=case_dict(row, True)), 201

    @app.post("/api/staff/procurements/<int:case_id>/offers")
    def create_offer(case_id):
        user, denied = actor("procurement_manage")
        if denied: return denied
        case = db.session.get(ProcurementCase, case_id); data = request.get_json(silent=True) or {}
        partner_ext = app.extensions.get("aplsai_partners") or {}; Partner = partner_ext.get("Partner")
        try: partner_id = int(data.get("partner_id"))
        except (TypeError, ValueError): partner_id = 0
        partner = db.session.get(Partner, partner_id) if Partner and partner_id else None
        if not case or not partner: return jsonify(error="Confronto o partner non valido."), 400
        if ProcurementOffer.query.filter_by(case_id=case.id, partner_id=partner.id).first(): return jsonify(error="Esiste già un’offerta di questo partner nel confronto."), 409
        row = ProcurementOffer(case_id=case.id, partner_id=partner.id, created_by_user_id=user.id)
        db.session.add(row); db.session.flush(); event(case, user, "Offerta aggiunta", partner.name, row); db.session.commit()
        return jsonify(case=case_dict(case, True)), 201

    @app.patch("/api/staff/procurement-offers/<int:offer_id>")
    def update_offer(offer_id):
        user, denied = actor("procurement_manage")
        if denied: return denied
        row = db.session.get(ProcurementOffer, offer_id); data = request.get_json(silent=True) or {}
        if not row: return jsonify(error="Offerta non trovata."), 404
        case = db.session.get(ProcurementCase, row.case_id)
        for key, limit in (("offer_ref",500),("modules_detail",10000),("deliverables",10000),("profiles_rates",10000),
                          ("technologies",10000),("dependencies",10000),("exclusions",10000),("assumptions",10000),
                          ("vat_note",300),("payment_milestones",10000),("capacity_evidence",500),("score_evidence",500)):
            if key in data: setattr(row, key, app_module.clean_text(data.get(key), limit))
        try:
            for key in ("one_time_cost","recurring_monthly_cost","maintenance_24m","cloud_24m","ai_24m","licenses_24m","third_party_24m","subcontractors_24m","estimated_excluded_costs","person_days"):
                if key in data:
                    value = float(data.get(key) or 0)
                    if value < 0: raise ValueError
                    setattr(row, key, value)
            if "duration_days" in data:
                row.duration_days = int(data.get("duration_days") or 0)
                if row.duration_days < 0: raise ValueError
            for key in SOFTWARE_WEIGHTS:
                if key in data:
                    value = None if data.get(key) in {None, ""} else float(data.get(key))
                    if value is not None and not 0 <= value <= 100: raise ValueError
                    setattr(row, key, value)
        except (TypeError, ValueError): return jsonify(error="Valori economici, tempi o punteggi non validi."), 400
        if "capacity_status" in data:
            if data["capacity_status"] not in CAPACITY_STATUSES: return jsonify(error="Capacità non valida."), 400
            row.capacity_status = data["capacity_status"]
        for key in ("repository_aplsai","accounts_aplsai","documentation_transferable","third_party_separable","ai_replaceable","exit_clause"):
            if key in data: setattr(row, key, bool(data[key]))
        row.review_status = "Da valutare"; row.reviewed_at = None; row.reviewed_by_user_id = None
        event(case, user, "Offerta aggiornata", data.get("change_note", ""), row); db.session.commit()
        return jsonify(case=case_dict(case, True))

    @app.post("/api/admin/procurement-offers/<int:offer_id>/review")
    def review_offer(offer_id):
        user, denied = actor("procurement_approve")
        if denied: return denied
        row = db.session.get(ProcurementOffer, offer_id); data = request.get_json(silent=True) or {}; status = data.get("status")
        note = app_module.clean_text(data.get("note"), 5000); evidence = app_module.clean_text(data.get("evidence_ref"), 500)
        if not row: return jsonify(error="Offerta non trovata."), 404
        case = db.session.get(ProcurementCase, row.case_id); details = offer_dict(row, case.case_type)
        if status not in REVIEW_STATUSES - {"Da valutare"} or not note or not evidence: return jsonify(error="Esito, nota ed evidenza sono obbligatori."), 400
        if status == "Verificata" and details["missing"]: return jsonify(error="Verifica bloccata: mancano " + ", ".join(details["missing"]) + "."), 409
        if status == "Verificata" and case.case_type == "Software e tecnologia" and (details["weighted_score"] is None or not row.score_evidence):
            return jsonify(error="Verifica bloccata: completare criteri e fonte dei punteggi."), 409
        row.review_status = status; row.review_note = note; row.score_evidence = evidence; row.reviewed_by_user_id = user.id; row.reviewed_at = utcnow()
        case.status = "In valutazione"; case.version += 1; event(case, user, "Offerta verificata", status, row); db.session.commit()
        return jsonify(case=case_dict(case, True))

    @app.post("/api/admin/procurements/<int:case_id>/decision")
    def decide_case(case_id):
        user, denied = actor("procurement_approve")
        if denied: return denied
        case = db.session.get(ProcurementCase, case_id); data = request.get_json(silent=True) or {}
        try: offer_id = int(data.get("offer_id"))
        except (TypeError, ValueError): offer_id = 0
        offer = db.session.get(ProcurementOffer, offer_id) if offer_id else None
        note = app_module.clean_text(data.get("note"), 5000); evidence = app_module.clean_text(data.get("evidence_ref"), 500)
        if not case or not offer or offer.case_id != case.id: return jsonify(error="Confronto o offerta non validi."), 400
        if offer.review_status != "Verificata" or not note or not evidence: return jsonify(error="La scelta richiede offerta verificata, motivazione ed evidenza."), 409
        case.selected_offer_id = offer.id; case.status = "Decisa"; case.decision_note = note; case.decision_evidence = evidence
        case.decided_by_user_id = user.id; case.decided_at = utcnow(); case.version += 1
        event(case, user, "Decisione finale", f"Offerta {offer.id}: {note}", offer); db.session.commit()
        return jsonify(case=case_dict(case, True))

    app.extensions["aplsai_procurement"] = {"ProcurementCase": ProcurementCase, "ProcurementOffer": ProcurementOffer,
        "ProcurementEvent": ProcurementEvent, "case_dict": case_dict, "offer_dict": offer_dict, "software_weights": SOFTWARE_WEIGHTS}
