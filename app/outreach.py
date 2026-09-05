import json
import re
from datetime import datetime, timezone

from flask import jsonify, request, session

from . import db
from .rbac import has_permission


INQUIRY_STATUSES = {
    "Destinatario da verificare", "Bozza", "Da approvare", "Approvata",
    "Inviata", "Risposta ricevuta", "Chiusa", "Annullata",
}
REPLY_STATUSES = {"Da esaminare", "Dati confermati", "Archiviata"}
EMAIL_PATTERN = re.compile(r"(?<![\w.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![\w.-])", re.I)


def init_outreach(app, app_module):
    if app.extensions.get("aplsai_outreach"):
        return

    opportunities = app.extensions.get("aplsai_opportunities") or {}
    PropertyOpportunity = opportunities.get("PropertyOpportunity")
    opportunity_dict = opportunities.get("opportunity_dict")
    if not PropertyOpportunity or not opportunity_dict:
        raise RuntimeError("Il modulo opportunità deve essere inizializzato prima dei contatti.")

    class OpportunityInquiry(db.Model):
        __tablename__ = "opportunity_inquiry"
        id = db.Column(db.Integer, primary_key=True)
        opportunity_id = db.Column(db.Integer, db.ForeignKey("property_opportunity.id"), nullable=False, index=True)
        recipient_name = db.Column(db.String(160), nullable=False, default="")
        recipient_email = db.Column(db.String(254), nullable=False, default="")
        recipient_verified = db.Column(db.Boolean, nullable=False, default=False)
        subject = db.Column(db.String(240), nullable=False)
        body = db.Column(db.Text, nullable=False)
        missing_fields_json = db.Column(db.Text, nullable=False, default="[]")
        custom_questions_json = db.Column(db.Text, nullable=False, default="[]")
        status = db.Column(db.String(50), nullable=False, default="Bozza", index=True)
        approved_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        approved_at = db.Column(db.DateTime(timezone=True))
        sent_at = db.Column(db.DateTime(timezone=True))
        external_thread_id = db.Column(db.String(255), nullable=False, default="")
        created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)

    class InquiryReply(db.Model):
        __tablename__ = "inquiry_reply"
        id = db.Column(db.Integer, primary_key=True)
        inquiry_id = db.Column(db.Integer, db.ForeignKey("opportunity_inquiry.id"), nullable=False, index=True)
        sender_email = db.Column(db.String(254), nullable=False, default="")
        body = db.Column(db.Text, nullable=False)
        extracted_json = db.Column(db.Text, nullable=False, default="{}")
        status = db.Column(db.String(40), nullable=False, default="Da esaminare")
        source_message_id = db.Column(db.String(255), nullable=False, default="")
        received_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)
        reviewed_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        reviewed_at = db.Column(db.DateTime(timezone=True))
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)

    with app.app_context():
        db.create_all()

    def staff_user(permission):
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
            fn(actor, action, "opportunity_inquiry", object_id, detail)

    def safe_json(value, fallback):
        try:
            parsed = json.loads(value or "")
            return parsed if isinstance(parsed, type(fallback)) else fallback
        except (TypeError, ValueError):
            return fallback

    def extract_email(value):
        match = EMAIL_PATTERN.search(value or "")
        return match.group(1).lower() if match else ""

    def missing_information(opportunity):
        checks = []
        def add(code, label, question):
            checks.append({"code": code, "label": label, "question": question})
        if opportunity.availability == "Da verificare":
            add("availability", "disponibilità attuale", "L’immobile è ancora disponibile? In caso contrario, è già in trattativa o venduto?")
        if not opportunity.address:
            add("address", "indirizzo completo", "Qual è l’indirizzo completo dell’immobile?")
        if opportunity.price is None:
            add("price", "prezzo richiesto", "Qual è il prezzo richiesto aggiornato?")
        if opportunity.sqm is None:
            add("sqm", "metratura", "Qual è la superficie commerciale dichiarata in metri quadrati?")
        if opportunity.property_type == "Da definire":
            add("property_type", "tipologia", "Qual è la tipologia catastale o commerciale dell’immobile?")
        if opportunity.state == "Da verificare":
            add("state", "stato manutentivo", "In quali condizioni si trova l’immobile e sono previsti lavori?")
        if opportunity.documents_status in {"Da verificare", "Mancanti"}:
            add("documents_status", "documentazione disponibile", "Quali documenti dell’immobile sono già disponibili per una verifica preliminare?")
        if opportunity.planimetry_status in {"Da verificare", "Mancante"}:
            add("planimetry_status", "planimetria", "È disponibile una planimetria aggiornata?")
        return checks

    def default_message(opportunity, missing):
        reference = opportunity.external_ref or f"opportunità APLSAI #{opportunity.id}"
        questions = "\n".join(f"- {item['question']}" for item in missing)
        if not questions:
            questions = "- Ci conferma che i dati pubblicati nell’annuncio sono ancora aggiornati?"
        subject = f"Richiesta informazioni immobile – {reference}"
        body = (
            f"Buongiorno{(' ' + opportunity.contact_name) if opportunity.contact_name else ''},\n\n"
            f"la contattiamo in riferimento all’immobile «{opportunity.title}»"
            f"{(' pubblicato da ' + opportunity.source_name) if opportunity.source_name else ''}. "
            "Stiamo svolgendo una valutazione preliminare per verificarne la compatibilità con richieste abitative attive.\n\n"
            "Avremmo bisogno delle seguenti informazioni:\n"
            f"{questions}\n\n"
            "Può rispondere direttamente a questa email, mantenendo l’oggetto del messaggio. "
            f"Riferimento interno: APLSAI-OPP-{opportunity.id:05d}.\n\n"
            "Grazie,\nAPLSAI HOME"
        )
        return subject, body

    def extract_reply(body):
        """Conservative suggestions only: every value must be confirmed by staff."""
        text = app_module.clean_text(body, 12000)
        lower = text.lower()
        values = {}
        evidence = {}
        if re.search(r"\b(non (?:è|e|risulta) (?:più )?disponibile|vendut[oa]|già locat[oa])\b", lower):
            values["availability"] = "Non disponibile"
            evidence["availability"] = "La risposta indica indisponibilità o conclusione."
        elif re.search(r"\b(ancora disponibile|è disponibile|e disponibile|disponibile da subito)\b", lower):
            values["availability"] = "Disponibile"
            evidence["availability"] = "La risposta indica disponibilità."
        price_match = re.search(r"(?:prezzo|richiesta|euro|€)\s*(?::|è|e)?\s*€?\s*([0-9][0-9. ]{3,})(?:,\d{1,2})?", lower)
        if price_match:
            raw = re.sub(r"[. ]", "", price_match.group(1))
            try:
                value = float(raw)
                if 1000 <= value <= 100000000:
                    values["price"] = value
                    evidence["price"] = price_match.group(0)[:160]
            except ValueError:
                pass
        sqm_match = re.search(r"(?:superficie|metratura|mq|m²)\s*(?::|è|e)?\s*([0-9]{2,5}(?:[.,][0-9]+)?)|([0-9]{2,5}(?:[.,][0-9]+)?)\s*(?:mq|m²)", lower)
        if sqm_match:
            raw = next((g for g in sqm_match.groups() if g), "").replace(",", ".")
            try:
                value = float(raw)
                if 10 <= value <= 100000:
                    values["sqm"] = value
                    evidence["sqm"] = sqm_match.group(0)[:160]
            except ValueError:
                pass
        if re.search(r"\b(planimetria (?:è |e )?(?:disponibile|allegata|presente)|allego la planimetria)\b", lower):
            values["planimetry_status"] = "Disponibile"
            evidence["planimetry_status"] = "La risposta menziona una planimetria disponibile o allegata."
        return {"suggested_updates": values, "evidence": evidence, "requires_confirmation": True}

    def reply_dict(reply):
        return {
            "id": reply.id, "inquiry_id": reply.inquiry_id,
            "sender_email": reply.sender_email, "body": reply.body,
            "extracted": safe_json(reply.extracted_json, {}), "status": reply.status,
            "source_message_id": reply.source_message_id,
            "received_at": reply.received_at.isoformat() if reply.received_at else None,
            "reviewed_at": reply.reviewed_at.isoformat() if reply.reviewed_at else None,
        }

    def inquiry_dict(inquiry, include_replies=False):
        opportunity = db.session.get(PropertyOpportunity, inquiry.opportunity_id)
        result = {
            "id": inquiry.id, "opportunity_id": inquiry.opportunity_id,
            "opportunity_title": opportunity.title if opportunity else "Opportunità rimossa",
            "recipient_name": inquiry.recipient_name, "recipient_email": inquiry.recipient_email,
            "recipient_verified": inquiry.recipient_verified, "subject": inquiry.subject,
            "body": inquiry.body, "missing_fields": safe_json(inquiry.missing_fields_json, []),
            "custom_questions": safe_json(inquiry.custom_questions_json, []), "status": inquiry.status,
            "approved_at": inquiry.approved_at.isoformat() if inquiry.approved_at else None,
            "sent_at": inquiry.sent_at.isoformat() if inquiry.sent_at else None,
            "external_thread_id": inquiry.external_thread_id,
            "created_at": inquiry.created_at.isoformat() if inquiry.created_at else None,
            "updated_at": inquiry.updated_at.isoformat() if inquiry.updated_at else None,
        }
        if include_replies:
            replies = InquiryReply.query.filter_by(inquiry_id=inquiry.id).order_by(InquiryReply.received_at.desc()).all()
            result["replies"] = [reply_dict(row) for row in replies]
        return result

    def notifications():
        results = []
        opportunities_rows = PropertyOpportunity.query.filter(PropertyOpportunity.archived_at.is_(None)).order_by(PropertyOpportunity.updated_at.desc()).all()
        for opportunity in opportunities_rows:
            missing = missing_information(opportunity)
            latest = OpportunityInquiry.query.filter_by(opportunity_id=opportunity.id).order_by(OpportunityInquiry.created_at.desc()).first()
            if not extract_email(opportunity.contact_details):
                results.append({"level": "warning", "type": "missing_contact", "opportunity_id": opportunity.id, "message": f"{opportunity.title}: manca un indirizzo email verificabile."})
            if missing:
                labels = ", ".join(item["label"] for item in missing[:4])
                suffix = "…" if len(missing) > 4 else ""
                results.append({"level": "info", "type": "missing_data", "opportunity_id": opportunity.id, "message": f"{opportunity.title}: da chiedere {labels}{suffix}."})
            if latest and latest.status == "Da approvare":
                results.append({"level": "action", "type": "approval", "opportunity_id": opportunity.id, "inquiry_id": latest.id, "message": f"{opportunity.title}: messaggio pronto per l’approvazione dell’admin."})
            if latest and latest.status == "Inviata":
                results.append({"level": "waiting", "type": "awaiting_reply", "opportunity_id": opportunity.id, "inquiry_id": latest.id, "message": f"{opportunity.title}: risposta ancora attesa."})
        for reply in InquiryReply.query.filter_by(status="Da esaminare").order_by(InquiryReply.received_at.desc()).all():
            inquiry = db.session.get(OpportunityInquiry, reply.inquiry_id)
            opportunity = db.session.get(PropertyOpportunity, inquiry.opportunity_id) if inquiry else None
            results.insert(0, {"level": "action", "type": "reply_review", "opportunity_id": opportunity.id if opportunity else None, "inquiry_id": inquiry.id if inquiry else None, "reply_id": reply.id, "message": f"{opportunity.title if opportunity else 'Opportunità'}: risposta ricevuta, dati da confermare."})
        return results

    @app.get("/api/staff/outreach")
    def outreach_dashboard():
        actor, denied = staff_user("outreach_read")
        if denied:
            return denied
        rows = OpportunityInquiry.query.order_by(OpportunityInquiry.updated_at.desc()).limit(200).all()
        notes = notifications()
        return jsonify(
            inquiries=[inquiry_dict(row) for row in rows], notifications=notes,
            counts={
                "drafts": sum(row.status in {"Bozza", "Destinatario da verificare", "Da approvare"} for row in rows),
                "awaiting_reply": sum(row.status == "Inviata" for row in rows),
                "replies_to_review": InquiryReply.query.filter_by(status="Da esaminare").count(),
            },
        )

    @app.post("/api/staff/opportunities/<int:opportunity_id>/inquiries")
    def inquiry_generate(opportunity_id):
        actor, denied = staff_user("outreach_manage")
        if denied:
            return denied
        opportunity = db.session.get(PropertyOpportunity, opportunity_id)
        if not opportunity or opportunity.archived_at:
            return jsonify(error="Opportunità non trovata o archiviata."), 404
        data = request.get_json(silent=True) or {}
        missing = missing_information(opportunity)
        subject, body = default_message(opportunity, missing)
        recipient_email = app_module.clean_email(data.get("recipient_email") or extract_email(opportunity.contact_details))
        recipient_name = app_module.clean_text(data.get("recipient_name") or opportunity.contact_name, 160)
        verified = bool(data.get("recipient_verified")) and app_module.valid_email(recipient_email)
        custom = data.get("custom_questions") or []
        if not isinstance(custom, list) or len(custom) > 20:
            return jsonify(error="Domande aggiuntive non valide."), 400
        custom = [app_module.clean_text(item, 500) for item in custom if app_module.clean_text(item, 500)]
        if custom:
            body = body.replace("\n\nPuò rispondere", "\n" + "\n".join(f"- {q}" for q in custom) + "\n\nPuò rispondere")
        inquiry = OpportunityInquiry(
            opportunity_id=opportunity.id, recipient_name=recipient_name,
            recipient_email=recipient_email if app_module.valid_email(recipient_email) else "",
            recipient_verified=verified, subject=subject, body=body,
            missing_fields_json=json.dumps(missing, ensure_ascii=False),
            custom_questions_json=json.dumps(custom, ensure_ascii=False),
            status="Bozza" if verified else "Destinatario da verificare",
            created_by_user_id=actor.id,
        )
        db.session.add(inquiry)
        db.session.flush()
        audit(actor, "inquiry_generate", inquiry.id, f"opportunity={opportunity.id}; verified={verified}")
        db.session.commit()
        return jsonify(inquiry=inquiry_dict(inquiry, include_replies=True)), 201

    @app.patch("/api/staff/inquiries/<int:inquiry_id>")
    def inquiry_update(inquiry_id):
        actor, denied = staff_user("outreach_manage")
        if denied:
            return denied
        inquiry = db.session.get(OpportunityInquiry, inquiry_id)
        if not inquiry:
            return jsonify(error="Richiesta non trovata."), 404
        if inquiry.status in {"Inviata", "Risposta ricevuta", "Chiusa", "Annullata"}:
            return jsonify(error="La richiesta non è più modificabile."), 409
        data = request.get_json(silent=True) or {}
        if "recipient_email" in data:
            email = app_module.clean_email(data.get("recipient_email"))
            if not app_module.valid_email(email):
                return jsonify(error="Indirizzo email del destinatario non valido."), 400
            inquiry.recipient_email = email
            inquiry.recipient_verified = False
        if "recipient_name" in data:
            inquiry.recipient_name = app_module.clean_text(data.get("recipient_name"), 160)
        if "subject" in data:
            inquiry.subject = app_module.clean_text(data.get("subject"), 240)
        if "body" in data:
            inquiry.body = app_module.clean_text(data.get("body"), 12000)
        if data.get("recipient_verified") is True:
            if not app_module.valid_email(inquiry.recipient_email):
                return jsonify(error="Inserire un indirizzo email valido prima della verifica."), 400
            inquiry.recipient_verified = True
        if data.get("request_approval") is True:
            if not inquiry.recipient_verified or not inquiry.subject or not inquiry.body:
                return jsonify(error="Verificare destinatario e testo prima di chiedere l’approvazione."), 409
            inquiry.status = "Da approvare"
        else:
            inquiry.status = "Bozza" if inquiry.recipient_verified else "Destinatario da verificare"
        inquiry.updated_at = datetime.now(timezone.utc)
        audit(actor, "inquiry_update", inquiry.id, f"status={inquiry.status}")
        db.session.commit()
        return jsonify(inquiry=inquiry_dict(inquiry, include_replies=True))

    @app.post("/api/staff/inquiries/<int:inquiry_id>/approve")
    def inquiry_approve(inquiry_id):
        actor, denied = staff_user("outreach_approve")
        if denied:
            return denied
        inquiry = db.session.get(OpportunityInquiry, inquiry_id)
        if not inquiry:
            return jsonify(error="Richiesta non trovata."), 404
        if inquiry.status != "Da approvare" or not inquiry.recipient_verified:
            return jsonify(error="La richiesta deve avere destinatario verificato ed essere pronta per l’approvazione."), 409
        inquiry.status = "Approvata"
        inquiry.approved_by_user_id = actor.id
        inquiry.approved_at = datetime.now(timezone.utc)
        inquiry.updated_at = inquiry.approved_at
        audit(actor, "inquiry_approve", inquiry.id, f"recipient={inquiry.recipient_email}")
        db.session.commit()
        return jsonify(inquiry=inquiry_dict(inquiry, include_replies=True))

    @app.post("/api/staff/inquiries/<int:inquiry_id>/mark-sent")
    def inquiry_mark_sent(inquiry_id):
        actor, denied = staff_user("outreach_approve")
        if denied:
            return denied
        inquiry = db.session.get(OpportunityInquiry, inquiry_id)
        if not inquiry:
            return jsonify(error="Richiesta non trovata."), 404
        if inquiry.status != "Approvata":
            return jsonify(error="Solo una richiesta approvata può essere registrata come inviata."), 409
        data = request.get_json(silent=True) or {}
        inquiry.status = "Inviata"
        inquiry.external_thread_id = app_module.clean_text(data.get("external_thread_id"), 255)
        inquiry.sent_at = datetime.now(timezone.utc)
        inquiry.updated_at = inquiry.sent_at
        audit(actor, "inquiry_mark_sent", inquiry.id)
        db.session.commit()
        return jsonify(inquiry=inquiry_dict(inquiry, include_replies=True))

    @app.get("/api/staff/inquiries/<int:inquiry_id>")
    def inquiry_detail(inquiry_id):
        actor, denied = staff_user("outreach_read")
        if denied:
            return denied
        inquiry = db.session.get(OpportunityInquiry, inquiry_id)
        if not inquiry:
            return jsonify(error="Richiesta non trovata."), 404
        return jsonify(inquiry=inquiry_dict(inquiry, include_replies=True))

    @app.post("/api/staff/inquiries/<int:inquiry_id>/replies")
    def reply_capture(inquiry_id):
        actor, denied = staff_user("outreach_manage")
        if denied:
            return denied
        inquiry = db.session.get(OpportunityInquiry, inquiry_id)
        if not inquiry:
            return jsonify(error="Richiesta non trovata."), 404
        data = request.get_json(silent=True) or {}
        body = app_module.clean_text(data.get("body"), 12000)
        sender = app_module.clean_email(data.get("sender_email"))
        if not body:
            return jsonify(error="Incollare il testo della risposta."), 400
        if sender and not app_module.valid_email(sender):
            return jsonify(error="Email del mittente non valida."), 400
        source_message_id = app_module.clean_text(data.get("source_message_id"), 255)
        if source_message_id and InquiryReply.query.filter_by(source_message_id=source_message_id).first():
            return jsonify(error="Questa risposta è già stata acquisita."), 409
        reply = InquiryReply(
            inquiry_id=inquiry.id, sender_email=sender, body=body,
            extracted_json=json.dumps(extract_reply(body), ensure_ascii=False),
            source_message_id=source_message_id,
        )
        db.session.add(reply)
        inquiry.status = "Risposta ricevuta"
        inquiry.updated_at = datetime.now(timezone.utc)
        db.session.flush()
        audit(actor, "inquiry_reply_capture", inquiry.id, f"reply={reply.id}")
        db.session.commit()
        return jsonify(reply=reply_dict(reply), inquiry=inquiry_dict(inquiry, include_replies=True)), 201

    @app.post("/api/staff/inquiry-replies/<int:reply_id>/apply")
    def reply_apply(reply_id):
        actor, denied = staff_user("outreach_manage")
        if denied:
            return denied
        reply = db.session.get(InquiryReply, reply_id)
        if not reply:
            return jsonify(error="Risposta non trovata."), 404
        if reply.status != "Da esaminare":
            return jsonify(error="Questa risposta è già stata esaminata."), 409
        inquiry = db.session.get(OpportunityInquiry, reply.inquiry_id)
        opportunity = db.session.get(PropertyOpportunity, inquiry.opportunity_id) if inquiry else None
        if not opportunity:
            return jsonify(error="Opportunità collegata non trovata."), 404
        data = request.get_json(silent=True) or {}
        updates = data.get("confirmed_updates") or {}
        if not isinstance(updates, dict):
            return jsonify(error="Dati confermati non validi."), 400
        allowed = {"availability", "address", "price", "sqm", "property_type", "state", "documents_status", "planimetry_status"}
        if set(updates) - allowed:
            return jsonify(error="La risposta contiene campi non aggiornabili."), 400
        apply_payload = opportunities.get("apply_payload")
        record_revision = opportunities.get("record_revision")
        if not apply_payload or not record_revision:
            return jsonify(error="Aggiornamento opportunità non disponibile."), 503
        try:
            apply_payload(opportunity, updates)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        opportunity.version += 1
        opportunity.updated_at = datetime.now(timezone.utc)
        record_revision(opportunity, actor, f"Dati confermati dalla risposta #{reply.id}")
        reply.status = "Dati confermati"
        reply.reviewed_by_user_id = actor.id
        reply.reviewed_at = datetime.now(timezone.utc)
        inquiry.status = "Chiusa" if not missing_information(opportunity) else "Risposta ricevuta"
        inquiry.updated_at = reply.reviewed_at
        audit(actor, "inquiry_reply_apply", inquiry.id, f"reply={reply.id}; fields={','.join(sorted(updates))}")
        db.session.commit()
        return jsonify(reply=reply_dict(reply), inquiry=inquiry_dict(inquiry, include_replies=True), opportunity=opportunity_dict(opportunity, include_details=True))

    app.extensions["aplsai_outreach"] = {
        "OpportunityInquiry": OpportunityInquiry, "InquiryReply": InquiryReply,
        "missing_information": missing_information, "inquiry_dict": inquiry_dict,
    }
