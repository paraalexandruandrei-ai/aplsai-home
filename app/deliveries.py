from datetime import datetime, timezone

from flask import jsonify, request, session

from .rbac import has_permission


CHECKS = [
    ("CN-01", "Chiusura del cantiere", "Cantiere chiuso con collaudi approvati e senza difetti residui."),
    ("CN-02", "Completezza documentale", "Almeno il 95% dei documenti previsti è disponibile e identificato."),
    ("CN-03", "Documenti tecnici e impianti", "Verbali, certificazioni e riferimenti tecnici sono registrati."),
    ("CN-04", "Chiavi e accessi", "Tutte le chiavi e gli accessi censiti risultano consegnati."),
    ("CN-05", "Garanzie e assistenza", "Garanzie, referenti e modalità di assistenza sono registrati."),
    ("CN-06", "Consuntivo economico", "Costi, valore finale, margine e scostamenti sono verificabili."),
    ("CN-07", "Comprensione del destinatario", "Comprensione della consegna almeno all’80% e conferma registrata."),
]
DELIVERY_TYPES = {"Consegna al cliente", "Immissione sul mercato"}
DEFECT_SEVERITIES = {"Normale", "Alta", "Critica"}
DEFECT_STATUSES = {"Aperto", "In lavorazione", "Risolto", "Verificato"}


def utcnow():
    return datetime.now(timezone.utc)


def init_deliveries(app, app_module):
    if app.extensions.get("aplsai_deliveries"):
        return
    db = app_module.db

    class OperationDelivery(db.Model):
        __tablename__ = "operation_delivery"
        id = db.Column(db.Integer, primary_key=True)
        worksite_id = db.Column(db.Integer, unique=True, nullable=False, index=True)
        delivery_type = db.Column(db.String(60), nullable=False, default="Consegna al cliente")
        recipient_name = db.Column(db.String(220), nullable=False, default="")
        recipient_contact = db.Column(db.String(220), nullable=False, default="")
        status = db.Column(db.String(40), nullable=False, default="Da preparare")
        required_documents = db.Column(db.Integer, nullable=False, default=0)
        complete_documents = db.Column(db.Integer, nullable=False, default=0)
        technical_documents_ref = db.Column(db.String(500), nullable=False, default="")
        keys_expected = db.Column(db.Integer, nullable=False, default=0)
        keys_delivered = db.Column(db.Integer, nullable=False, default=0)
        warranty_ref = db.Column(db.String(500), nullable=False, default="")
        assistance_contact = db.Column(db.String(220), nullable=False, default="")
        planned_total_cost = db.Column(db.Float, nullable=False, default=0)
        acquisition_cost = db.Column(db.Float, nullable=False, default=0)
        work_cost = db.Column(db.Float, nullable=False, default=0)
        other_cost = db.Column(db.Float, nullable=False, default=0)
        final_value = db.Column(db.Float, nullable=False, default=0)
        variance_explanation = db.Column(db.Text, nullable=False, default="")
        comprehension_percent = db.Column(db.Float, nullable=False, default=0)
        satisfaction_percent = db.Column(db.Float, nullable=False, default=0)
        handover_evidence = db.Column(db.String(500), nullable=False, default="")
        delivery_note = db.Column(db.Text, nullable=False, default="")
        delivered_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        delivered_at = db.Column(db.DateTime(timezone=True))
        closing_note = db.Column(db.Text, nullable=False, default="")
        closed_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        closed_at = db.Column(db.DateTime(timezone=True))
        version = db.Column(db.Integer, nullable=False, default=1)
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    class DeliveryCheck(db.Model):
        __tablename__ = "delivery_check"
        id = db.Column(db.Integer, primary_key=True)
        delivery_id = db.Column(db.Integer, db.ForeignKey("operation_delivery.id"), nullable=False, index=True)
        code = db.Column(db.String(20), nullable=False)
        title = db.Column(db.String(220), nullable=False)
        expected_result = db.Column(db.Text, nullable=False)
        automatic_status = db.Column(db.String(30), nullable=False, default="Da verificare")
        automatic_detail = db.Column(db.Text, nullable=False, default="")
        evidence_ref = db.Column(db.String(500), nullable=False, default="")
        residual_defects = db.Column(db.Text, nullable=False, default="")
        mandatory_actions = db.Column(db.Text, nullable=False, default="")
        action_owner = db.Column(db.String(220), nullable=False, default="")
        verification_status = db.Column(db.String(30), nullable=False, default="Da verificare")
        verification_note = db.Column(db.Text, nullable=False, default="")
        verified_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        verified_at = db.Column(db.DateTime(timezone=True))
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
        __table_args__ = (db.UniqueConstraint("delivery_id", "code", name="uq_delivery_check_code"),)

    class DeliveryDefect(db.Model):
        __tablename__ = "delivery_defect"
        id = db.Column(db.Integer, primary_key=True)
        delivery_id = db.Column(db.Integer, db.ForeignKey("operation_delivery.id"), nullable=False, index=True)
        title = db.Column(db.String(220), nullable=False)
        description = db.Column(db.Text, nullable=False)
        severity = db.Column(db.String(30), nullable=False, default="Normale")
        status = db.Column(db.String(40), nullable=False, default="Aperto")
        responsible_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        due_at = db.Column(db.DateTime(timezone=True))
        evidence_ref = db.Column(db.String(500), nullable=False, default="")
        resolution_note = db.Column(db.Text, nullable=False, default="")
        verified_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        verified_at = db.Column(db.DateTime(timezone=True))
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    class DeliveryEvent(db.Model):
        __tablename__ = "delivery_event"
        id = db.Column(db.Integer, primary_key=True)
        delivery_id = db.Column(db.Integer, db.ForeignKey("operation_delivery.id"), nullable=False, index=True)
        defect_id = db.Column(db.Integer)
        actor_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        action = db.Column(db.String(100), nullable=False)
        detail = db.Column(db.String(500), nullable=False, default="")
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    with app.app_context():
        db.create_all()

    def actor(permission):
        user = db.session.get(app_module.User, session.get("uid")) if session.get("uid") else None
        if not user: return None, (jsonify(error="Non autenticato."), 401)
        if not has_permission(user.role, permission): return None, (jsonify(error="Permesso insufficiente."), 403)
        return user, None

    def event(delivery, user, action, detail="", defect=None):
        db.session.add(DeliveryEvent(delivery_id=delivery.id, defect_id=defect.id if defect else None,
                                     actor_user_id=user.id, action=action,
                                     detail=app_module.clean_text(detail, 500)))

    def ensure_checks(delivery):
        for code, title, expected in CHECKS:
            if not DeliveryCheck.query.filter_by(delivery_id=delivery.id, code=code).first():
                db.session.add(DeliveryCheck(delivery_id=delivery.id, code=code, title=title, expected_result=expected))
        db.session.flush()

    def calculated(delivery):
        Worksite = (app.extensions.get("aplsai_worksites") or {}).get("WorksiteProject")
        Phase = (app.extensions.get("aplsai_worksites") or {}).get("WorksitePhase")
        worksite = db.session.get(Worksite, delivery.worksite_id) if Worksite else None
        phases = Phase.query.filter_by(project_id=worksite.id).all() if Phase and worksite else []
        documents_percent = round(delivery.complete_documents / delivery.required_documents * 100, 1) if delivery.required_documents else 0
        actual_cost = delivery.acquisition_cost + delivery.work_cost + delivery.other_cost
        margin = delivery.final_value - actual_cost
        variance = actual_cost - delivery.planned_total_cost
        economic_ok = delivery.planned_total_cost > 0 and actual_cost > 0 and delivery.final_value > 0 and (abs(variance) < 0.01 or bool(delivery.variance_explanation))
        values = {
            "CN-01": (bool(worksite and worksite.status == "Chiuso" and phases and all(p.admin_decision == "Approvata" and not p.critical_defects and not p.residual_defects for p in phases)), "Cantiere chiuso e fasi conformi" if worksite and worksite.status == "Chiuso" else "Cantiere non ancora chiuso"),
            "CN-02": (documents_percent >= 95, f"Completezza {documents_percent}% ({delivery.complete_documents}/{delivery.required_documents})"),
            "CN-03": (bool(delivery.technical_documents_ref), "Riferimenti tecnici presenti" if delivery.technical_documents_ref else "Riferimenti tecnici mancanti"),
            "CN-04": (delivery.keys_expected > 0 and delivery.keys_delivered == delivery.keys_expected, f"Chiavi consegnate {delivery.keys_delivered}/{delivery.keys_expected}"),
            "CN-05": (bool(delivery.warranty_ref and delivery.assistance_contact), "Garanzie e assistenza registrate" if delivery.warranty_ref and delivery.assistance_contact else "Garanzie o assistenza incomplete"),
            "CN-06": (economic_ok, f"Costo effettivo € {actual_cost:,.2f}; scostamento € {variance:,.2f}; margine € {margin:,.2f}"),
            "CN-07": (delivery.comprehension_percent >= 80, f"Comprensione destinatario {delivery.comprehension_percent}%"),
        }
        return values, worksite, documents_percent, actual_cost, variance, margin

    def refresh(delivery):
        ensure_checks(delivery); values, worksite, documents_percent, actual_cost, variance, margin = calculated(delivery)
        for check in DeliveryCheck.query.filter_by(delivery_id=delivery.id).all():
            ok, detail = values[check.code]; check.automatic_status = "Superato" if ok else "Bloccato"; check.automatic_detail = detail
            if not ok: check.verification_status = "Da verificare"
        return worksite, documents_percent, actual_cost, variance, margin

    def defect_dict(row):
        owner = db.session.get(app_module.User, row.responsible_user_id)
        return {"id": row.id, "title": row.title, "description": row.description, "severity": row.severity,
                "status": row.status, "responsible_user_id": row.responsible_user_id,
                "responsible_name": owner.name if owner else "", "due_at": row.due_at.isoformat() if row.due_at else None,
                "evidence_ref": row.evidence_ref, "resolution_note": row.resolution_note,
                "verified_at": row.verified_at.isoformat() if row.verified_at else None,
                "created_at": row.created_at.isoformat() if row.created_at else None}

    def delivery_dict(row, include_history=False):
        worksite, documents_percent, actual_cost, variance, margin = refresh(row)
        checks = DeliveryCheck.query.filter_by(delivery_id=row.id).order_by(DeliveryCheck.code).all()
        defects = DeliveryDefect.query.filter_by(delivery_id=row.id).order_by(DeliveryDefect.created_at.desc()).all()
        complete = all(x.automatic_status == "Superato" and x.verification_status == "Approvata" and not x.residual_defects for x in checks)
        if row.status not in {"Consegnata", "Chiusa"}: row.status = "Pronta alla consegna" if complete else "Da preparare"
        data = {"id": row.id, "worksite_id": row.worksite_id, "worksite_name": worksite.name if worksite else "",
                "delivery_type": row.delivery_type, "recipient_name": row.recipient_name,
                "recipient_contact": row.recipient_contact, "status": row.status,
                "required_documents": row.required_documents, "complete_documents": row.complete_documents,
                "documents_percent": documents_percent, "technical_documents_ref": row.technical_documents_ref,
                "keys_expected": row.keys_expected, "keys_delivered": row.keys_delivered,
                "warranty_ref": row.warranty_ref, "assistance_contact": row.assistance_contact,
                "planned_total_cost": row.planned_total_cost, "acquisition_cost": row.acquisition_cost,
                "work_cost": row.work_cost, "other_cost": row.other_cost, "actual_total_cost": actual_cost,
                "final_value": row.final_value, "final_margin": margin, "cost_variance": variance,
                "variance_explanation": row.variance_explanation, "comprehension_percent": row.comprehension_percent,
                "satisfaction_percent": row.satisfaction_percent, "handover_evidence": row.handover_evidence,
                "delivery_note": row.delivery_note, "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
                "closing_note": row.closing_note, "closed_at": row.closed_at.isoformat() if row.closed_at else None,
                "version": row.version, "checks": [{"id": x.id, "code": x.code, "title": x.title,
                    "expected_result": x.expected_result, "automatic_status": x.automatic_status,
                    "automatic_detail": x.automatic_detail, "evidence_ref": x.evidence_ref,
                    "residual_defects": x.residual_defects, "mandatory_actions": x.mandatory_actions,
                    "action_owner": x.action_owner, "verification_status": x.verification_status,
                    "verification_note": x.verification_note} for x in checks],
                "defects": [defect_dict(x) for x in defects], "updated_at": row.updated_at.isoformat() if row.updated_at else None}
        if include_history:
            data["events"] = [{"id": x.id, "defect_id": x.defect_id, "action": x.action, "detail": x.detail,
                               "actor_user_id": x.actor_user_id, "created_at": x.created_at.isoformat()}
                              for x in DeliveryEvent.query.filter_by(delivery_id=row.id).order_by(DeliveryEvent.id.desc()).all()]
        return data

    @app.get("/api/staff/deliveries")
    def list_deliveries():
        user, denied = actor("delivery_read")
        if denied: return denied
        rows = OperationDelivery.query.order_by(OperationDelivery.updated_at.desc()).all()
        return jsonify(deliveries=[delivery_dict(x) for x in rows])

    @app.get("/api/staff/deliveries/<int:delivery_id>")
    def get_delivery(delivery_id):
        user, denied = actor("delivery_read")
        if denied: return denied
        row = db.session.get(OperationDelivery, delivery_id)
        if not row: return jsonify(error="Consegna non trovata."), 404
        return jsonify(delivery=delivery_dict(row, include_history=True))

    @app.post("/api/staff/deliveries")
    def create_delivery():
        user, denied = actor("delivery_manage")
        if denied: return denied
        data = request.get_json(silent=True) or {}
        try: worksite_id = int(data.get("worksite_id"))
        except (TypeError, ValueError): return jsonify(error="Cantiere non valido."), 400
        Worksite = (app.extensions.get("aplsai_worksites") or {}).get("WorksiteProject")
        worksite = db.session.get(Worksite, worksite_id) if Worksite else None
        if not worksite or worksite.status != "Chiuso": return jsonify(error="La consegna può essere preparata solo dopo la chiusura del cantiere."), 409
        if OperationDelivery.query.filter_by(worksite_id=worksite_id).first(): return jsonify(error="Consegna già presente per questo cantiere."), 409
        delivery_type = data.get("delivery_type", "Consegna al cliente")
        if delivery_type not in DELIVERY_TYPES: return jsonify(error="Tipo di consegna non valido."), 400
        row = OperationDelivery(worksite_id=worksite_id, delivery_type=delivery_type,
                                recipient_name=app_module.clean_text(data.get("recipient_name"), 220),
                                recipient_contact=app_module.clean_text(data.get("recipient_contact"), 220),
                                planned_total_cost=worksite.initial_budget)
        db.session.add(row); db.session.flush(); ensure_checks(row); event(row, user, "Consegna preparata", delivery_type); db.session.commit()
        return jsonify(delivery=delivery_dict(row, include_history=True)), 201

    @app.patch("/api/staff/deliveries/<int:delivery_id>")
    def update_delivery(delivery_id):
        user, denied = actor("delivery_manage")
        if denied: return denied
        row = db.session.get(OperationDelivery, delivery_id)
        if not row or row.status == "Chiusa": return jsonify(error="Consegna non modificabile."), 404
        data = request.get_json(silent=True) or {}
        try:
            for key in ("required_documents", "complete_documents", "keys_expected", "keys_delivered"):
                if key in data:
                    value = int(data.get(key) or 0)
                    if value < 0: raise ValueError
                    setattr(row, key, value)
            if row.complete_documents > row.required_documents or row.keys_delivered > row.keys_expected: raise ValueError
            for key in ("planned_total_cost", "acquisition_cost", "work_cost", "other_cost", "final_value", "comprehension_percent", "satisfaction_percent"):
                if key in data:
                    value = float(data.get(key) or 0)
                    if value < 0 or (key.endswith("_percent") and value > 100): raise ValueError
                    setattr(row, key, value)
        except (TypeError, ValueError): return jsonify(error="Valori numerici non validi."), 400
        for key, limit in (("recipient_name",220),("recipient_contact",220),("technical_documents_ref",500),
                           ("warranty_ref",500),("assistance_contact",220),("variance_explanation",5000)):
            if key in data: setattr(row, key, app_module.clean_text(data.get(key), limit))
        row.version += 1; event(row, user, "Dati consegna aggiornati", data.get("change_note", "")); out = delivery_dict(row, True); db.session.commit()
        return jsonify(delivery=out)

    @app.patch("/api/staff/delivery-checks/<int:check_id>")
    def update_delivery_check(check_id):
        user, denied = actor("delivery_manage")
        if denied: return denied
        check = db.session.get(DeliveryCheck, check_id)
        if not check: return jsonify(error="Controllo non trovato."), 404
        data = request.get_json(silent=True) or {}
        for key, limit in (("evidence_ref",500),("residual_defects",5000),("mandatory_actions",5000),("action_owner",220)):
            if key in data: setattr(check, key, app_module.clean_text(data.get(key), limit))
        check.verification_status = "Da verificare"; delivery = db.session.get(OperationDelivery, check.delivery_id)
        event(delivery, user, "Controllo consegna aggiornato", check.code); out = delivery_dict(delivery, True); db.session.commit()
        return jsonify(delivery=out)

    @app.post("/api/admin/delivery-checks/<int:check_id>/verify")
    def verify_delivery_check(check_id):
        user, denied = actor("delivery_approve")
        if denied: return denied
        check = db.session.get(DeliveryCheck, check_id)
        if not check: return jsonify(error="Controllo non trovato."), 404
        delivery = db.session.get(OperationDelivery, check.delivery_id); refresh(delivery)
        data = request.get_json(silent=True) or {}; approved = data.get("approved") is True; note = app_module.clean_text(data.get("note"), 5000)
        if approved and (check.automatic_status != "Superato" or not check.evidence_ref or check.residual_defects):
            return jsonify(error="Verifica bloccata: requisito, evidenza o difetti residui non conformi."), 409
        if not approved and not note: return jsonify(error="Indica le correzioni richieste."), 400
        check.verification_status = "Approvata" if approved else "Respinta"; check.verification_note = note
        check.verified_by_user_id = user.id; check.verified_at = utcnow(); event(delivery, user, "Verifica consegna", f"{check.code}: {check.verification_status}")
        out = delivery_dict(delivery, True); db.session.commit(); return jsonify(delivery=out)

    @app.post("/api/admin/deliveries/<int:delivery_id>/deliver")
    def deliver(delivery_id):
        user, denied = actor("delivery_approve")
        if denied: return denied
        row = db.session.get(OperationDelivery, delivery_id)
        if not row: return jsonify(error="Consegna non trovata."), 404
        data = request.get_json(silent=True) or {}; evidence = app_module.clean_text(data.get("evidence_ref"), 500); note = app_module.clean_text(data.get("note"), 5000)
        out = delivery_dict(row, True)
        if out["status"] != "Pronta alla consegna" or not row.recipient_name or not evidence or not note:
            return jsonify(error="Consegna bloccata: completare i controlli, il destinatario, l’evidenza e il verbale."), 409
        row.status = "Consegnata"; row.handover_evidence = evidence; row.delivery_note = note
        row.delivered_by_user_id = user.id; row.delivered_at = utcnow(); row.version += 1
        event(row, user, "Consegna eseguita", note); db.session.commit(); return jsonify(delivery=delivery_dict(row, True))

    @app.post("/api/staff/deliveries/<int:delivery_id>/defects")
    def create_defect(delivery_id):
        user, denied = actor("delivery_manage")
        if denied: return denied
        delivery = db.session.get(OperationDelivery, delivery_id); data = request.get_json(silent=True) or {}
        if not delivery or delivery.status not in {"Consegnata", "Chiusa"}: return jsonify(error="I difetti post-consegna si registrano dopo la consegna."), 409
        title = app_module.clean_text(data.get("title"), 220); description = app_module.clean_text(data.get("description"), 5000); severity = data.get("severity", "Normale")
        if not title or not description or severity not in DEFECT_SEVERITIES: return jsonify(error="Titolo, descrizione e gravità sono obbligatori."), 400
        try: responsible_id = int(data.get("responsible_user_id") or user.id)
        except (TypeError, ValueError): return jsonify(error="Responsabile non valido."), 400
        responsible = db.session.get(app_module.User, responsible_id)
        if not responsible: return jsonify(error="Responsabile non valido."), 400
        due_at = None
        if data.get("due_at"):
            try: due_at = datetime.fromisoformat(str(data["due_at"]).replace("Z", "+00:00"))
            except ValueError: return jsonify(error="Scadenza non valida."), 400
        defect = DeliveryDefect(delivery_id=delivery.id, title=title, description=description, severity=severity,
                                responsible_user_id=responsible_id, due_at=due_at)
        if delivery.status == "Chiusa":
            delivery.status = "Consegnata"; delivery.closed_by_user_id = None; delivery.closed_at = None
            delivery.closing_note = ""
        db.session.add(defect); db.session.flush(); event(delivery, user, "Difetto post-consegna aperto", title, defect); db.session.commit()
        return jsonify(delivery=delivery_dict(delivery, True)), 201

    @app.patch("/api/staff/delivery-defects/<int:defect_id>")
    def update_defect(defect_id):
        user, denied = actor("delivery_manage")
        if denied: return denied
        row = db.session.get(DeliveryDefect, defect_id)
        if not row: return jsonify(error="Difetto non trovato."), 404
        data = request.get_json(silent=True) or {}; status = data.get("status", row.status)
        if status not in DEFECT_STATUSES - {"Verificato"}: return jsonify(error="Stato difetto non valido."), 400
        row.status = status
        for key, limit in (("evidence_ref",500),("resolution_note",5000)):
            if key in data: setattr(row, key, app_module.clean_text(data.get(key), limit))
        if status == "Risolto" and (not row.evidence_ref or not row.resolution_note): return jsonify(error="Per indicare Risolto servono evidenza e nota."), 409
        delivery = db.session.get(OperationDelivery, row.delivery_id); event(delivery, user, "Difetto aggiornato", status, row); db.session.commit()
        return jsonify(delivery=delivery_dict(delivery, True))

    @app.post("/api/admin/delivery-defects/<int:defect_id>/verify")
    def verify_defect(defect_id):
        user, denied = actor("delivery_approve")
        if denied: return denied
        row = db.session.get(DeliveryDefect, defect_id)
        if not row or row.status != "Risolto" or not row.evidence_ref: return jsonify(error="Difetto non verificabile."), 409
        row.status = "Verificato"; row.verified_by_user_id = user.id; row.verified_at = utcnow()
        delivery = db.session.get(OperationDelivery, row.delivery_id); event(delivery, user, "Difetto verificato", row.title, row); db.session.commit()
        return jsonify(delivery=delivery_dict(delivery, True))

    @app.post("/api/admin/deliveries/<int:delivery_id>/close")
    def close_delivery(delivery_id):
        user, denied = actor("delivery_approve")
        if denied: return denied
        row = db.session.get(OperationDelivery, delivery_id); data = request.get_json(silent=True) or {}; note = app_module.clean_text(data.get("note"), 5000)
        if not row or row.status != "Consegnata": return jsonify(error="La consegna deve essere prima eseguita."), 409
        open_defects = DeliveryDefect.query.filter_by(delivery_id=row.id).filter(DeliveryDefect.status != "Verificato").count()
        if open_defects or row.comprehension_percent < 80 or not note: return jsonify(error="Chiusura bloccata: risolvere i difetti, confermare la comprensione e inserire la decisione finale."), 409
        row.status = "Chiusa"; row.closing_note = note; row.closed_by_user_id = user.id; row.closed_at = utcnow(); row.version += 1
        event(row, user, "Operazione chiusa", note); db.session.commit(); return jsonify(delivery=delivery_dict(row, True))

    app.extensions["aplsai_deliveries"] = {"OperationDelivery": OperationDelivery, "DeliveryCheck": DeliveryCheck,
                                            "DeliveryDefect": DeliveryDefect, "DeliveryEvent": DeliveryEvent,
                                            "delivery_dict": delivery_dict}
