from datetime import datetime, timezone

from flask import jsonify, request, session

from .rbac import has_permission


QUOTE_DEFINITIONS = [
    ("RP-01", "Acquisizione immobile", 238000, "Proprietà / agenzia / notaio", "Proposta/preliminare e verifica prezzo"),
    ("RP-02", "Opere edili", 28000, "Impresa edile qualificata", "Computo e preventivo a corpo"),
    ("RP-03", "Impianti", 11000, "Installatore abilitato", "Preventivo con dichiarazioni finali"),
    ("RP-04", "Energia", 6000, "Termotecnico / installatore", "Preventivo prestazionale"),
    ("RP-05", "Tecnici", 7000, "Tecnico professionista", "Lettera d’incarico professionale"),
    ("RP-06", "Arredi/accessori", 8000, "Rivenditore / falegnameria", "Distinta forniture e montaggio"),
    ("RP-07", "Imposte/oneri/atti", 10000, "Notaio / tecnico / ente", "Prospetto notaio/tecnico/ente"),
    ("RP-08", "Finanza e altri costi", 3000, "Banca / intermediario", "Prospetto banca/intermediario"),
]

SEND_STATUSES = {"Da assegnare", "Bozza", "Inviata", "Risposta ricevuta", "Chiusa", "Invio non riuscito"}
VERIFY_STATUSES = {"Da verificare", "Verificata", "Con rilievi", "Respinta"}


def utcnow():
    return datetime.now(timezone.utc)


def aware(value):
    return value if not value or value.tzinfo else value.replace(tzinfo=timezone.utc)


def parse_date(value):
    if value in {None, ""}:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if not parsed.tzinfo:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def init_quotes(app, app_module):
    if app.extensions.get("aplsai_quotes"):
        return
    db = app_module.db

    class QuoteRequest(db.Model):
        __tablename__ = "quote_request"
        id = db.Column(db.Integer, primary_key=True)
        pilot_case_id = db.Column(db.Integer, nullable=False, index=True)
        property_id = db.Column(db.Integer, db.ForeignKey("property.id"), nullable=False, index=True)
        code = db.Column(db.String(20), nullable=False)
        category = db.Column(db.String(120), nullable=False)
        estimate_v1 = db.Column(db.Float, nullable=False, default=0)
        recipient_type = db.Column(db.String(160), nullable=False)
        recipient_company = db.Column(db.String(220), nullable=False, default="DA ASSEGNARE")
        recipient_email = db.Column(db.String(255), nullable=False, default="")
        recipient_verified = db.Column(db.Boolean, nullable=False, default=False)
        send_status = db.Column(db.String(40), nullable=False, default="Da assegnare")
        sent_at = db.Column(db.DateTime(timezone=True))
        due_at = db.Column(db.DateTime(timezone=True))
        offer_at = db.Column(db.DateTime(timezone=True))
        offered_net = db.Column(db.Float)
        offered_vat = db.Column(db.Float)
        offered_total = db.Column(db.Float)
        validity = db.Column(db.String(160), nullable=False, default="")
        timing = db.Column(db.String(160), nullable=False, default="")
        payment_terms = db.Column(db.String(500), nullable=False, default="")
        offer_manager = db.Column(db.String(220), nullable=False, default="")
        completeness = db.Column(db.String(40), nullable=False, default="Incompleta")
        verification_status = db.Column(db.String(40), nullable=False, default="Da verificare")
        document_ref = db.Column(db.String(500), nullable=False, default="")
        required_document = db.Column(db.String(255), nullable=False)
        notes = db.Column(db.Text, nullable=False, default="")
        verified_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        verified_at = db.Column(db.DateTime(timezone=True))
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
        __table_args__ = (db.UniqueConstraint("pilot_case_id", "code", name="uq_quote_case_code"),)

    class QuoteEvent(db.Model):
        __tablename__ = "quote_event"
        id = db.Column(db.Integer, primary_key=True)
        quote_id = db.Column(db.Integer, db.ForeignKey("quote_request.id"), nullable=False, index=True)
        actor_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        action = db.Column(db.String(80), nullable=False)
        note = db.Column(db.String(500), nullable=False, default="")
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    with app.app_context():
        db.create_all()

    def actor_for(permission):
        actor = db.session.get(app_module.User, session.get("uid")) if session.get("uid") else None
        if not actor or actor.role not in {"staff", "operator"}:
            return None, (jsonify(error="Non autenticato."), 401)
        if not has_permission(actor.role, permission):
            return None, (jsonify(error="Permesso insufficiente."), 403)
        return actor, None

    def event(row, actor, action, note=""):
        db.session.add(QuoteEvent(quote_id=row.id, actor_user_id=actor.id, action=action, note=app_module.clean_text(note, 500)))

    def missing(row):
        fields = []
        for value, label in ((row.recipient_company, "emittente"), (row.offer_at, "data offerta"),
                             (row.offered_total, "importo totale"), (row.validity, "validità"),
                             (row.notes, "perimetro e condizioni"), (row.document_ref, "documento allegato")):
            if value in {None, "", "DA ASSEGNARE"}:
                fields.append(label)
        return fields

    def as_dict(row):
        left = None
        if row.due_at:
            left = (aware(row.due_at).date() - utcnow().date()).days
        return {key: getattr(row, key) for key in (
            "id", "pilot_case_id", "property_id", "code", "category", "estimate_v1", "recipient_type",
            "recipient_company", "recipient_email", "recipient_verified", "send_status", "offered_net",
            "offered_vat", "offered_total", "validity", "timing", "payment_terms", "offer_manager",
            "completeness", "verification_status", "document_ref", "required_document", "notes") } | {
            "sent_at": aware(row.sent_at).isoformat() if row.sent_at else None,
            "due_at": aware(row.due_at).isoformat() if row.due_at else None,
            "offer_at": aware(row.offer_at).isoformat() if row.offer_at else None,
            "days_remaining": left, "missing": missing(row),
        }

    def email_body(row):
        prop = db.session.get(app_module.Property, row.property_id)
        ref = prop.ref if prop else f"immobile {row.property_id}"
        return (f"Buongiorno,\n\nAPLSAI HOME richiede un’offerta per {row.category} relativa a {ref}.\n"
                f"Documento richiesto: {row.required_document}.\n\nIndicare imponibile, IVA, totale, validità, tempi, modalità di pagamento e responsabile dell’offerta. "
                "Separare prestazione principale, opzioni, esclusioni, canoni, manutenzioni e costi di terzi; "
                "specificare quantità, marche o livello prestazionale, garanzie e documenti finali.\n\n"
                f"Scadenza risposta: {aware(row.due_at).strftime('%d/%m/%Y') if row.due_at else 'da concordare'}.\n"
                "Rispondere direttamente a questa email allegando l’offerta.\n\nAPLSAI HOME")

    def try_auto_send(row, actor):
        gmail = app.extensions.get("aplsai_gmail") or {}
        sender = gmail.get("send_plain_email")
        if not row.recipient_verified or not app_module.valid_email(row.recipient_email):
            row.send_status = "Bozza" if row.recipient_company != "DA ASSEGNARE" else "Da assegnare"
            return False, "Destinatario non verificato: richiesta conservata senza invio."
        if not sender:
            row.send_status = "Bozza"
            return False, "Gmail non collegata: richiesta conservata senza invio."
        try:
            sender(row.recipient_email, f"Richiesta {row.code} – {row.category} – APLSAI HOME", email_body(row))
            row.send_status, row.sent_at = "Inviata", utcnow()
            event(row, actor, "Invio automatico", row.recipient_email)
            return True, "Richiesta inviata automaticamente."
        except Exception as exc:
            row.send_status = "Invio non riuscito"
            event(row, actor, "Invio non riuscito", str(exc))
            return False, "Invio non riuscito; la richiesta resta registrata."

    @app.get("/api/staff/quotes")
    def list_quotes():
        actor, denied = actor_for("quote_read")
        if denied: return denied
        rows = QuoteRequest.query.order_by(QuoteRequest.code.asc()).all()
        return jsonify(quotes=[as_dict(x) for x in rows], summary={
            "total": len(rows), "sent": sum(x.send_status == "Inviata" for x in rows),
            "received": sum(x.send_status == "Risposta ricevuta" for x in rows),
            "verified": sum(x.verification_status == "Verificata" for x in rows)})

    @app.post("/api/staff/quotes/prepare-co01")
    def prepare_co01():
        actor, denied = actor_for("quote_manage")
        if denied: return denied
        PilotCase = (app.extensions.get("aplsai_pilot_cases") or {}).get("PilotCase")
        case = PilotCase.query.filter_by(code="CO 01").first() if PilotCase else None
        if not case or not case.property_id:
            return jsonify(error="Collega prima un immobile reale al Caso Oro CO 01."), 400
        created = 0
        for code, category, estimate, recipient_type, document in QUOTE_DEFINITIONS:
            if not QuoteRequest.query.filter_by(pilot_case_id=case.id, code=code).first():
                row = QuoteRequest(pilot_case_id=case.id, property_id=case.property_id, code=code,
                                   category=category, estimate_v1=estimate, recipient_type=recipient_type,
                                   required_document=document)
                db.session.add(row); db.session.flush(); event(row, actor, "Scheda preparata", "CO 01")
                created += 1
        db.session.commit()
        return jsonify(created=created, quotes=[as_dict(x) for x in QuoteRequest.query.filter_by(pilot_case_id=case.id).order_by(QuoteRequest.code).all()])

    @app.patch("/api/staff/quotes/<int:quote_id>")
    def update_quote(quote_id):
        actor, denied = actor_for("quote_manage")
        if denied: return denied
        row = db.session.get(QuoteRequest, quote_id)
        if not row: return jsonify(error="Scheda preventivo non trovata."), 404
        data = request.get_json(silent=True) or {}
        for key, limit in (("recipient_company", 220), ("recipient_email", 255), ("validity", 160),
                           ("timing", 160), ("payment_terms", 500), ("offer_manager", 220),
                           ("document_ref", 500), ("notes", 5000)):
            if key in data: setattr(row, key, app_module.clean_text(data.get(key), limit))
        if "recipient_email" in data: row.recipient_email = app_module.clean_email(data.get("recipient_email"))
        if "recipient_verified" in data: row.recipient_verified = bool(data.get("recipient_verified"))
        for key in ("offered_net", "offered_vat", "offered_total"):
            if key in data: setattr(row, key, float(data[key]) if data[key] not in {None, ""} else None)
        for key in ("due_at", "offer_at"):
            if key in data: setattr(row, key, parse_date(data.get(key)))
        row.completeness = "Completa" if not missing(row) else "Incompleta"
        if row.offered_total is not None: row.send_status = "Risposta ricevuta"
        event(row, actor, "Aggiornamento", data.get("change_note") or "Scheda aggiornata")
        sent, message = (False, "Scheda salvata.")
        if data.get("auto_send") and row.send_status not in {"Inviata", "Risposta ricevuta", "Chiusa"}:
            sent, message = try_auto_send(row, actor)
        db.session.commit()
        return jsonify(quote=as_dict(row), sent=sent, message=message)

    @app.post("/api/admin/quotes/<int:quote_id>/verify")
    def verify_quote(quote_id):
        actor, denied = actor_for("quote_approve")
        if denied: return denied
        row = db.session.get(QuoteRequest, quote_id)
        if not row: return jsonify(error="Scheda preventivo non trovata."), 404
        data = request.get_json(silent=True) or {}; status = data.get("status", "Verificata")
        if status not in VERIFY_STATUSES: return jsonify(error="Esito non valido."), 400
        if status == "Verificata" and missing(row):
            return jsonify(error="Il preventivo non può entrare nella fattibilità: mancano " + ", ".join(missing(row)) + "."), 400
        row.verification_status, row.verified_by_user_id, row.verified_at = status, actor.id, utcnow()
        if status == "Verificata": row.send_status = "Chiusa"
        event(row, actor, "Verifica Admin", data.get("note") or status); db.session.commit()
        return jsonify(quote=as_dict(row))

    app.extensions["aplsai_quotes"] = {"QuoteRequest": QuoteRequest, "QuoteEvent": QuoteEvent, "definitions": QUOTE_DEFINITIONS}
