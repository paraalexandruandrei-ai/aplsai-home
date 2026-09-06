from datetime import datetime, timezone

from flask import jsonify, request, session

from .rbac import has_permission


CASE_STATUSES = {"Da preparare", "In lavorazione", "In verifica", "Superato", "Non superato", "Bloccato"}
CHECK_STATUSES = {"Da eseguire", "Superata", "Non superata", "Bloccata"}

CASE_DEFINITIONS = [
    ("CO 01", "Percorso cliente–immobile", "Provare il percorso completo su un cliente e un immobile reali.", [
        ("01.01", "Profilo cliente completo", "Il profilo abitativo contiene esigenze, budget, tempi e strategia."),
        ("01.02", "Immobile reale registrato", "La scheda immobile è registrata anche se alcuni dati restano da verificare."),
        ("01.03", "Compatibilità calcolata", "Il motore distingue situazione attuale, potenziale e verifiche mancanti."),
        ("01.04", "Scenario progettuale", "È presente almeno uno scenario coerente con la richiesta del cliente."),
        ("01.05", "Preventivi e costi", "Le otto schede preventivo sono assegnate e i costi disponibili sono registrati."),
        ("01.06", "Fattibilità completa", "La decisione considera margine, tempi, rischi e capitale disponibile."),
        ("01.07", "Proposta controllata", "La proposta è stata verificata dall’Admin prima della condivisione."),
        ("01.08", "Evidenze conservate", "Documenti, esiti e responsabilità del caso sono rintracciabili."),
    ]),
    ("CO 02", "Motore economico e capitale", "Provare la sostenibilità economica e finanziaria dell’operazione.", [
        ("02.01", "Prezzo di acquisizione", "Prezzo e fonte sono documentati."),
        ("02.02", "Costi tecnici", "Progettazione, pratiche e verifiche sono valorizzate o segnalate come mancanti."),
        ("02.03", "Costi lavori", "Lavori minimi e massimi derivano da preventivi identificabili."),
        ("02.04", "Costi accessori", "Imposte, notaio, intermediazione e imprevisti sono considerati."),
        ("02.05", "Ricavo prudente", "Il ricavo atteso utilizza un valore prudente e una fonte dichiarata."),
        ("02.06", "Margine operativo", "Il margine è calcolato sugli importi minimi e massimi disponibili."),
        ("02.07", "Piano di cassa", "Entrate, uscite e SAL sono distribuiti nel tempo."),
        ("02.08", "Copertura finanziaria", "Capitale proprio, banca e investitori sono distinti e verificati."),
        ("02.09", "Stress finanziario", "Il sistema evidenzia fabbisogno aggiuntivo e saldo minimo."),
        ("02.10", "Decisione motivata", "Procedere, sospendere o rifiutare è motivato e approvato."),
    ]),
    ("CO 03", "Robustezza e controllo", "Provare sicurezza, incompletezza dei dati e continuità operativa.", [
        ("03.01", "Dati incompleti", "Il sistema salva le schede incomplete senza inventare valori."),
        ("03.02", "Sollecito informazioni", "I dati mancanti generano un sollecito mirato e tracciabile."),
        ("03.03", "Conferma umana", "I dati estratti dalle risposte non sono applicati senza conferma."),
        ("03.04", "Ruoli separati", "Admin, operatore, partner e cliente vedono solo le funzioni autorizzate."),
        ("03.05", "Regole staff", "Le regole obbligatorie risultano lette prima dell’operatività."),
        ("03.06", "Tracciamento modifiche", "Le azioni rilevanti e le revisioni sono conservate."),
        ("03.07", "Archiviazione recuperabile", "Clienti, opportunità e immobili archiviati restano recuperabili."),
        ("03.08", "Esportazione Excel", "Il pacchetto operativo è completo, leggibile e non duplica i record."),
        ("03.09", "Uso da cellulare", "Le funzioni essenziali sono utilizzabili da smartphone."),
        ("03.10", "Continuità del servizio", "Avvio, salute applicativa e gestione degli errori sono verificati."),
    ]),
]


def utcnow():
    return datetime.now(timezone.utc)


def _aware(value):
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def init_pilot_cases(app, app_module):
    if app.extensions.get("aplsai_pilot_cases"):
        return

    db = app_module.db

    class PilotCase(db.Model):
        __tablename__ = "pilot_case"
        id = db.Column(db.Integer, primary_key=True)
        code = db.Column(db.String(20), unique=True, nullable=False, index=True)
        title = db.Column(db.String(220), nullable=False)
        objective = db.Column(db.Text, nullable=False, default="")
        status = db.Column(db.String(40), nullable=False, default="Da preparare", index=True)
        client_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
        opportunity_id = db.Column(db.Integer, nullable=True)
        property_id = db.Column(db.Integer, db.ForeignKey("property.id"), nullable=True)
        scenario_id = db.Column(db.Integer, nullable=True)
        feasibility_id = db.Column(db.Integer, nullable=True)
        assigned_to_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
        notes = db.Column(db.Text, nullable=False, default="")
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    class PilotCheck(db.Model):
        __tablename__ = "pilot_check"
        id = db.Column(db.Integer, primary_key=True)
        case_id = db.Column(db.Integer, db.ForeignKey("pilot_case.id"), nullable=False, index=True)
        code = db.Column(db.String(20), unique=True, nullable=False, index=True)
        title = db.Column(db.String(220), nullable=False)
        expected_result = db.Column(db.Text, nullable=False, default="")
        status = db.Column(db.String(40), nullable=False, default="Da eseguire", index=True)
        evidence_ref = db.Column(db.Text, nullable=False, default="")
        result_note = db.Column(db.Text, nullable=False, default="")
        executed_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
        executed_at = db.Column(db.DateTime(timezone=True), nullable=True)
        verification_status = db.Column(db.String(30), nullable=False, default="Da verificare")
        verification_note = db.Column(db.Text, nullable=False, default="")
        verified_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
        verified_at = db.Column(db.DateTime(timezone=True), nullable=True)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    with app.app_context():
        db.create_all()
        for code, title, objective, checks in CASE_DEFINITIONS:
            case = PilotCase.query.filter_by(code=code).first()
            if not case:
                case = PilotCase(code=code, title=title, objective=objective)
                db.session.add(case)
                db.session.flush()
            for check_code, check_title, expected in checks:
                if not PilotCheck.query.filter_by(code=check_code).first():
                    db.session.add(PilotCheck(
                        case_id=case.id, code=check_code, title=check_title,
                        expected_result=expected,
                    ))
        db.session.commit()

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

    def name_for(user_id):
        user = db.session.get(app_module.User, user_id) if user_id else None
        return user.name if user else ""

    def recalculate(case):
        checks = PilotCheck.query.filter_by(case_id=case.id).all()
        if checks and all(c.verification_status == "Approvata" for c in checks):
            case.status = "Superato"
        elif any(c.verification_status == "Respinta" for c in checks):
            case.status = "Non superato"
        elif checks and all(c.status != "Da eseguire" for c in checks):
            case.status = "In verifica"
        elif any(c.status != "Da eseguire" for c in checks):
            case.status = "In lavorazione"
        else:
            case.status = "Da preparare"
        case.updated_at = utcnow()

    def check_dict(row):
        return {
            "id": row.id, "case_id": row.case_id, "code": row.code,
            "title": row.title, "expected_result": row.expected_result,
            "status": row.status, "evidence_ref": row.evidence_ref,
            "result_note": row.result_note,
            "executed_by_user_id": row.executed_by_user_id,
            "executed_by_name": name_for(row.executed_by_user_id),
            "executed_at": _aware(row.executed_at).isoformat() if row.executed_at else None,
            "verification_status": row.verification_status,
            "verification_note": row.verification_note,
            "verified_by_user_id": row.verified_by_user_id,
            "verified_by_name": name_for(row.verified_by_user_id),
            "verified_at": _aware(row.verified_at).isoformat() if row.verified_at else None,
            "updated_at": _aware(row.updated_at).isoformat() if row.updated_at else None,
        }

    def case_dict(row, include_checks=True):
        checks = PilotCheck.query.filter_by(case_id=row.id).order_by(PilotCheck.code.asc()).all()
        approved = sum(c.verification_status == "Approvata" for c in checks)
        result = {
            "id": row.id, "code": row.code, "title": row.title,
            "objective": row.objective, "status": row.status,
            "client_id": row.client_id, "opportunity_id": row.opportunity_id,
            "property_id": row.property_id, "scenario_id": row.scenario_id,
            "feasibility_id": row.feasibility_id,
            "assigned_to_user_id": row.assigned_to_user_id,
            "assigned_to_name": name_for(row.assigned_to_user_id),
            "notes": row.notes, "approved_checks": approved,
            "total_checks": len(checks),
            "updated_at": _aware(row.updated_at).isoformat() if row.updated_at else None,
        }
        if include_checks:
            result["checks"] = [check_dict(check) for check in checks]
        return result

    def audit(actor, action, object_type, object_id, detail=""):
        fn = (app.extensions.get("aplsai_operations") or {}).get("audit")
        if fn:
            fn(actor, action, object_type, object_id, detail)

    def valid_link(field, value):
        if value is None:
            return True
        if field == "client_id":
            profile = app_module.ClientProfile.query.filter_by(user_id=value).first()
            return bool(profile and not profile.is_test and not profile.archived_at)
        if field == "property_id":
            prop = db.session.get(app_module.Property, value)
            return bool(prop and not prop.archived_at)
        if field == "assigned_to_user_id":
            user = db.session.get(app_module.User, value)
            return bool(user and user.role == "operator" and getattr(user, "active", True))
        extension_name, model_name = {
            "opportunity_id": ("aplsai_opportunities", "PropertyOpportunity"),
            "scenario_id": ("aplsai_scenarios", "PropertyScenario"),
            "feasibility_id": ("aplsai_feasibility", "FeasibilityAnalysis"),
        }[field]
        model = (app.extensions.get(extension_name) or {}).get(model_name)
        record = db.session.get(model, value) if model else None
        return bool(record and not getattr(record, "archived_at", None))

    @app.get("/api/staff/pilot-cases")
    def list_pilot_cases():
        actor, denied = actor_for("pilot_read")
        if denied:
            return denied
        rows = PilotCase.query.order_by(PilotCase.code.asc()).all()
        if actor.role == "operator":
            rows = [row for row in rows if row.assigned_to_user_id in {None, actor.id}]
        return jsonify(cases=[case_dict(row) for row in rows], summary={
            "cases": len(rows),
            "passed": sum(row.status == "Superato" for row in rows),
            "checks": sum(PilotCheck.query.filter_by(case_id=row.id).count() for row in rows),
            "approved": sum(PilotCheck.query.filter_by(case_id=row.id, verification_status="Approvata").count() for row in rows),
        })

    @app.patch("/api/staff/pilot-cases/<int:case_id>")
    def update_pilot_case(case_id):
        actor, denied = actor_for("pilot_manage")
        if denied:
            return denied
        row = db.session.get(PilotCase, case_id)
        if not row:
            return jsonify(error="Caso di collaudo non trovato."), 404
        if actor.role == "operator" and row.assigned_to_user_id not in {None, actor.id}:
            return jsonify(error="Caso non assegnato a questo collaboratore."), 403
        data = request.get_json(silent=True) or {}
        for field in ("client_id", "opportunity_id", "property_id", "scenario_id", "feasibility_id", "assigned_to_user_id"):
            if field in data:
                value = data.get(field)
                try:
                    value = int(value) if value not in {None, ""} else None
                except (TypeError, ValueError):
                    return jsonify(error="Collegamento non valido."), 400
                if field == "assigned_to_user_id" and actor.role != "staff":
                    return jsonify(error="Solo l’Admin può assegnare il caso."), 403
                if not valid_link(field, value):
                    return jsonify(error="Il collegamento selezionato non esiste, è archiviato o non è utilizzabile."), 400
                setattr(row, field, value)
        if "notes" in data:
            row.notes = app_module.clean_text(data.get("notes"), 5000)
        if data.get("status") == "Bloccato":
            row.status = "Bloccato"
        elif "status" in data and data.get("status") not in CASE_STATUSES:
            return jsonify(error="Stato del caso non valido."), 400
        else:
            recalculate(row)
        audit(actor, "pilot_case_update", "pilot_case", row.id, f"status={row.status}")
        db.session.commit()
        return jsonify(case=case_dict(row))

    @app.patch("/api/staff/pilot-checks/<int:check_id>")
    def update_pilot_check(check_id):
        actor, denied = actor_for("pilot_manage")
        if denied:
            return denied
        row = db.session.get(PilotCheck, check_id)
        if not row:
            return jsonify(error="Prova non trovata."), 404
        case = db.session.get(PilotCase, row.case_id)
        if actor.role == "operator" and case.assigned_to_user_id not in {None, actor.id}:
            return jsonify(error="Caso non assegnato a questo collaboratore."), 403
        data = request.get_json(silent=True) or {}
        status = app_module.clean_text(data.get("status"), 40)
        evidence = app_module.clean_text(data.get("evidence_ref"), 2000)
        note = app_module.clean_text(data.get("result_note"), 5000)
        if status not in CHECK_STATUSES:
            return jsonify(error="Esito della prova non valido."), 400
        if status != "Da eseguire" and (not evidence or not note):
            return jsonify(error="Per registrare l’esito servono evidenza e nota del risultato."), 400
        row.status = status
        row.evidence_ref = evidence
        row.result_note = note
        row.executed_by_user_id = actor.id if status != "Da eseguire" else None
        row.executed_at = utcnow() if status != "Da eseguire" else None
        row.verification_status = "Da verificare"
        row.verification_note = ""
        row.verified_by_user_id = None
        row.verified_at = None
        recalculate(case)
        audit(actor, "pilot_check_execute", "pilot_check", row.id, f"status={status}")
        db.session.commit()
        return jsonify(case=case_dict(case), check=check_dict(row))

    @app.post("/api/admin/pilot-checks/<int:check_id>/verify")
    def verify_pilot_check(check_id):
        actor, denied = actor_for("pilot_approve")
        if denied:
            return denied
        row = db.session.get(PilotCheck, check_id)
        if not row:
            return jsonify(error="Prova non trovata."), 404
        if row.status == "Da eseguire":
            return jsonify(error="La prova deve essere eseguita prima della verifica."), 409
        data = request.get_json(silent=True) or {}
        approved = data.get("approved") is True
        note = app_module.clean_text(data.get("note"), 5000)
        if not approved and not note:
            return jsonify(error="Indicare la correzione richiesta."), 400
        row.verification_status = "Approvata" if approved else "Respinta"
        row.verification_note = note
        row.verified_by_user_id = actor.id
        row.verified_at = utcnow()
        case = db.session.get(PilotCase, row.case_id)
        recalculate(case)
        audit(actor, "pilot_check_verify", "pilot_check", row.id, row.verification_status)
        db.session.commit()
        return jsonify(case=case_dict(case), check=check_dict(row))

    app.extensions["aplsai_pilot_cases"] = {
        "PilotCase": PilotCase,
        "PilotCheck": PilotCheck,
        "case_dict": case_dict,
    }
