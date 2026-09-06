from datetime import datetime, timezone

from flask import jsonify, request, session

from .rbac import has_permission


INTEREST_STATUSES = {"Da presentare", "Presentata", "Confermata", "Rifiutata"}
DEPOSIT_STATUSES = {"Da richiedere", "Promessa", "Ricevuta", "Da verificare"}
PRELIMINARY_STATUSES = {"Da preparare", "In verifica", "Pronto alla firma", "Firmato", "Trascritto"}
ASSIGNMENT_STATUSES = {"Non prevista", "Da verificare", "Autorizzata", "Completata"}
WORK_STATUSES = {"Non avviati", "Da pianificare", "In corso", "Completati"}
CLOSING_STATUSES = {"Non avviata", "Da preparare", "Pronta", "Completata"}
VALIDATION_STATUSES = {"Da verificare", "In verifica", "Verificata", "Con rilievi"}


def utcnow():
    return datetime.now(timezone.utc)


def _aware(value):
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _parse_date(value):
    if value in {None, ""}:
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("Data non valida.")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def init_transactions(app, app_module):
    if app.extensions.get("aplsai_transactions"):
        return

    db = app_module.db

    class TransactionCase(db.Model):
        __tablename__ = "transaction_case"
        id = db.Column(db.Integer, primary_key=True)
        deal_id = db.Column(db.Integer, db.ForeignKey("deal.id"), unique=True, nullable=False, index=True)
        interest_status = db.Column(db.String(40), nullable=False, default="Da presentare")
        interest_at = db.Column(db.DateTime(timezone=True))
        deposit_amount = db.Column(db.Float, nullable=False, default=0)
        deposit_status = db.Column(db.String(40), nullable=False, default="Da richiedere")
        deposit_reference = db.Column(db.String(500), nullable=False, default="")
        preliminary_status = db.Column(db.String(50), nullable=False, default="Da preparare")
        preliminary_reference = db.Column(db.String(500), nullable=False, default="")
        transcribed_at = db.Column(db.DateTime(timezone=True))
        assignment_status = db.Column(db.String(40), nullable=False, default="Non prevista")
        assignment_reference = db.Column(db.String(500), nullable=False, default="")
        works_status = db.Column(db.String(40), nullable=False, default="Non avviati")
        technical_validation = db.Column(db.String(40), nullable=False, default="Da verificare")
        legal_validation = db.Column(db.String(40), nullable=False, default="Da verificare")
        closing_status = db.Column(db.String(40), nullable=False, default="Non avviata")
        closing_reference = db.Column(db.String(500), nullable=False, default="")
        closing_at = db.Column(db.DateTime(timezone=True))
        next_action = db.Column(db.String(255), nullable=False, default="Presentare la proposta preliminare")
        next_action_due_at = db.Column(db.DateTime(timezone=True))
        assigned_to_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
        notes = db.Column(db.Text, nullable=False, default="")
        version = db.Column(db.Integer, nullable=False, default=1)
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    class TransactionRevision(db.Model):
        __tablename__ = "transaction_revision"
        id = db.Column(db.Integer, primary_key=True)
        transaction_id = db.Column(db.Integer, db.ForeignKey("transaction_case.id"), nullable=False, index=True)
        version = db.Column(db.Integer, nullable=False)
        changed_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        change_note = db.Column(db.String(500), nullable=False, default="")
        snapshot_json = db.Column(db.Text, nullable=False)
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    with app.app_context():
        db.create_all()

    def actor_for(permission):
        uid = session.get("uid")
        actor = db.session.get(app_module.User, uid) if uid else None
        if not actor or actor.role not in {"staff", "operator"}:
            return None, (jsonify(error="Non autenticato."), 401)
        if getattr(actor, "active", True) is False:
            session.clear()
            return None, (jsonify(error="Account disattivato."), 401)
        if not has_permission(actor.role, permission):
            return None, (jsonify(error="Permesso insufficiente."), 403)
        return actor, None

    def user_name(user_id):
        user = db.session.get(app_module.User, user_id) if user_id else None
        return user.name if user else ""

    def ensure_case(deal):
        row = TransactionCase.query.filter_by(deal_id=deal.id).first()
        if not row:
            row = TransactionCase(deal_id=deal.id)
            db.session.add(row)
            db.session.flush()
        return row

    def stage_and_missing(row):
        missing = []
        stage = "Presentazione preliminare"
        if row.interest_status != "Confermata" or not row.interest_at:
            missing.append("Manifestazione di interesse del cliente con data")
            return stage, missing
        stage = "Interesse manifestato"
        if row.deposit_status != "Ricevuta" or row.deposit_amount < 5000 or not row.deposit_reference:
            missing.append("Caparra ricevuta di almeno €5.000 con riferimento documentale")
            return stage, missing
        stage = "Impegno economico"
        if row.legal_validation != "Verificata":
            missing.append("Verifica legale del preliminare")
        if row.preliminary_status not in {"Firmato", "Trascritto"} or not row.preliminary_reference:
            missing.append("Preliminare firmato e riferimento documentale")
        if missing:
            return stage, missing
        stage = "Preliminare"
        if row.preliminary_status != "Trascritto" or not row.transcribed_at:
            missing.append("Trascrizione notarile del preliminare")
            return stage, missing
        stage = "Preliminare trascritto"
        if row.assignment_status == "Da verificare":
            missing.append("Verificare se la cessione del preliminare è ammessa")
            return stage, missing
        if row.assignment_status in {"Autorizzata", "Completata"} and not row.assignment_reference:
            missing.append("Riferimento della cessione autorizzata")
            return stage, missing
        if row.technical_validation != "Verificata":
            missing.append("Validazione tecnica prima dell’avvio lavori")
        if row.works_status not in {"In corso", "Completati"}:
            missing.append("Avvio lavori")
        if missing:
            return stage, missing
        stage = "Lavori" if row.works_status == "In corso" else "Pronto al rogito"
        if row.works_status == "In corso":
            return stage, []
        if row.closing_status != "Completata" or not row.closing_reference or not row.closing_at:
            missing.append("Rogito o chiusura con riferimento documentale")
            return stage, missing
        return "Chiuso", []

    def to_dict(row, include_revisions=False):
        deal = db.session.get(app_module.Deal, row.deal_id)
        client = db.session.get(app_module.User, deal.client_id) if deal else None
        prop = db.session.get(app_module.Property, deal.property_id) if deal else None
        stage, missing = stage_and_missing(row)
        if deal and deal.stage != stage:
            deal.stage = stage
            deal.updated_at = utcnow()
        result = {
            "id": row.id, "deal_id": row.deal_id, "stage": stage,
            "client_id": deal.client_id if deal else None,
            "client_name": client.name if client else "",
            "property_id": deal.property_id if deal else None,
            "property_ref": prop.ref if prop else (deal.ref if deal else ""),
            "interest_status": row.interest_status,
            "interest_at": _aware(row.interest_at).isoformat() if row.interest_at else None,
            "deposit_amount": row.deposit_amount, "deposit_status": row.deposit_status,
            "deposit_reference": row.deposit_reference,
            "preliminary_status": row.preliminary_status,
            "preliminary_reference": row.preliminary_reference,
            "transcribed_at": _aware(row.transcribed_at).isoformat() if row.transcribed_at else None,
            "assignment_status": row.assignment_status,
            "assignment_reference": row.assignment_reference,
            "works_status": row.works_status,
            "technical_validation": row.technical_validation,
            "legal_validation": row.legal_validation,
            "closing_status": row.closing_status,
            "closing_reference": row.closing_reference,
            "closing_at": _aware(row.closing_at).isoformat() if row.closing_at else None,
            "next_action": row.next_action,
            "next_action_due_at": _aware(row.next_action_due_at).isoformat() if row.next_action_due_at else None,
            "assigned_to_user_id": row.assigned_to_user_id,
            "assigned_to_name": user_name(row.assigned_to_user_id),
            "notes": row.notes, "version": row.version, "missing": missing,
            "updated_at": _aware(row.updated_at).isoformat() if row.updated_at else None,
        }
        if include_revisions:
            result["revisions"] = [{
                "id": rev.id, "version": rev.version,
                "changed_by_user_id": rev.changed_by_user_id,
                "changed_by_name": user_name(rev.changed_by_user_id),
                "change_note": rev.change_note,
                "created_at": _aware(rev.created_at).isoformat(),
            } for rev in TransactionRevision.query.filter_by(transaction_id=row.id).order_by(TransactionRevision.version.desc()).all()]
        return result

    def snapshot(row):
        import json
        data = to_dict(row)
        return json.dumps(data, ensure_ascii=False, sort_keys=True)

    def record_revision(row, actor, note):
        db.session.add(TransactionRevision(
            transaction_id=row.id, version=row.version,
            changed_by_user_id=actor.id,
            change_note=app_module.clean_text(note, 500) or "Aggiornamento trattativa",
            snapshot_json=snapshot(row),
        ))

    def audit(actor, action, row, detail=""):
        fn = (app.extensions.get("aplsai_operations") or {}).get("audit")
        if fn:
            fn(actor, action, "transaction", row.id, detail)

    @app.get("/api/staff/transactions")
    def list_transactions():
        actor, denied = actor_for("transaction_read")
        if denied:
            return denied
        rows = []
        for deal in app_module.Deal.query.order_by(app_module.Deal.updated_at.desc()).all():
            row = ensure_case(deal)
            if actor.role == "operator" and row.assigned_to_user_id not in {None, actor.id}:
                continue
            rows.append(to_dict(row))
        db.session.commit()
        return jsonify(transactions=rows, summary={
            "total": len(rows),
            "open": sum(row["stage"] != "Chiuso" for row in rows),
            "blocked": sum(bool(row["missing"]) for row in rows),
            "closed": sum(row["stage"] == "Chiuso" for row in rows),
        })

    @app.get("/api/staff/transactions/<int:transaction_id>")
    def transaction_detail(transaction_id):
        actor, denied = actor_for("transaction_read")
        if denied:
            return denied
        row = db.session.get(TransactionCase, transaction_id)
        if not row:
            return jsonify(error="Trattativa non trovata."), 404
        if actor.role == "operator" and row.assigned_to_user_id not in {None, actor.id}:
            return jsonify(error="Trattativa non assegnata a questo collaboratore."), 403
        result = to_dict(row, include_revisions=True)
        db.session.commit()
        return jsonify(transaction=result)

    @app.patch("/api/staff/transactions/<int:transaction_id>")
    def update_transaction(transaction_id):
        actor, denied = actor_for("transaction_manage")
        if denied:
            return denied
        row = db.session.get(TransactionCase, transaction_id)
        if not row:
            return jsonify(error="Trattativa non trovata."), 404
        if actor.role == "operator" and row.assigned_to_user_id not in {None, actor.id}:
            return jsonify(error="Trattativa non assegnata a questo collaboratore."), 403
        data = request.get_json(silent=True) or {}
        allowed = {
            "interest_status": INTEREST_STATUSES,
            "deposit_status": DEPOSIT_STATUSES,
            "preliminary_status": PRELIMINARY_STATUSES,
            "assignment_status": ASSIGNMENT_STATUSES,
            "works_status": WORK_STATUSES,
            "closing_status": CLOSING_STATUSES,
        }
        for field, choices in allowed.items():
            if field in data:
                value = app_module.clean_text(data.get(field), 50)
                if value not in choices:
                    return jsonify(error=f"Valore non valido per {field}."), 400
                setattr(row, field, value)
        try:
            if "deposit_amount" in data:
                row.deposit_amount = float(data.get("deposit_amount") or 0)
                if row.deposit_amount < 0:
                    raise ValueError
            for field in ("interest_at", "transcribed_at", "closing_at", "next_action_due_at"):
                if field in data:
                    setattr(row, field, _parse_date(data.get(field)))
        except (TypeError, ValueError):
            return jsonify(error="Importo o data non validi."), 400
        for field, limit in {
            "deposit_reference": 500, "preliminary_reference": 500,
            "assignment_reference": 500, "closing_reference": 500,
            "next_action": 255, "notes": 5000,
        }.items():
            if field in data:
                setattr(row, field, app_module.clean_text(data.get(field), limit))
        if not row.next_action and row.closing_status != "Completata":
            return jsonify(error="La prossima azione è obbligatoria finché la trattativa è aperta."), 400
        if actor.role == "staff" and "assigned_to_user_id" in data:
            value = data.get("assigned_to_user_id")
            try:
                assignee_id = int(value) if value not in {None, ""} else None
            except (TypeError, ValueError):
                return jsonify(error="Responsabile non valido."), 400
            assignee = db.session.get(app_module.User, assignee_id) if assignee_id else None
            if assignee_id and (not assignee or assignee.role != "operator" or not getattr(assignee, "active", True)):
                return jsonify(error="Il responsabile deve essere un collaboratore attivo."), 400
            row.assigned_to_user_id = assignee_id
        row.version += 1
        row.updated_at = utcnow()
        change_note = app_module.clean_text(data.get("change_note"), 500)
        record_revision(row, actor, change_note)
        stage, _ = stage_and_missing(row)
        audit(actor, "transaction_update", row, f"stage={stage}; version={row.version}")
        db.session.commit()
        return jsonify(transaction=to_dict(row, include_revisions=True))

    @app.post("/api/admin/transactions/<int:transaction_id>/validation")
    def validate_transaction(transaction_id):
        actor, denied = actor_for("transaction_approve")
        if denied:
            return denied
        row = db.session.get(TransactionCase, transaction_id)
        if not row:
            return jsonify(error="Trattativa non trovata."), 404
        data = request.get_json(silent=True) or {}
        validation_type = data.get("type")
        status = app_module.clean_text(data.get("status"), 40)
        note = app_module.clean_text(data.get("note"), 500)
        if validation_type not in {"legal", "technical"} or status not in VALIDATION_STATUSES:
            return jsonify(error="Validazione non valida."), 400
        if status in {"Verificata", "Con rilievi"} and not note:
            return jsonify(error="Indicare il professionista o il riferimento della verifica."), 400
        if validation_type == "legal":
            row.legal_validation = status
        else:
            row.technical_validation = status
        row.version += 1
        row.updated_at = utcnow()
        record_revision(row, actor, f"Validazione {validation_type}: {status}. {note}")
        audit(actor, "transaction_validation", row, f"type={validation_type}; status={status}")
        db.session.commit()
        return jsonify(transaction=to_dict(row, include_revisions=True))

    app.extensions["aplsai_transactions"] = {
        "TransactionCase": TransactionCase,
        "TransactionRevision": TransactionRevision,
        "transaction_dict": to_dict,
        "ensure_case": ensure_case,
    }
