from datetime import datetime, timezone

from flask import jsonify, request, session

from .rbac import has_permission


PARTNER_TYPES = {"Impresa", "Tecnico", "Professionista", "Fornitore", "Software house", "Finanziatore", "Notaio o legale", "Altro"}
PARTNER_STATUSES = {"Da qualificare", "Idoneo", "Con riserva", "Sospeso", "Escluso"}
ASSIGNMENT_STATUSES = {"Da confermare", "Confermato", "In corso", "Consegnato", "Accettato", "Contestato", "Chiuso"}
VALIDATIONS = {"Da verificare", "Conforme", "Con rilievi", "Non conforme"}


def utcnow(): return datetime.now(timezone.utc)


def parse_date(value):
    if value in {None, ""}: return None
    out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return out.replace(tzinfo=timezone.utc) if not out.tzinfo else out.astimezone(timezone.utc)


def init_partners(app, app_module):
    if app.extensions.get("aplsai_partners"): return
    db = app_module.db

    class Partner(db.Model):
        __tablename__ = "partner_registry"
        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String(220), nullable=False)
        partner_type = db.Column(db.String(60), nullable=False)
        tax_reference = db.Column(db.String(100), nullable=False, default="")
        contact_name = db.Column(db.String(220), nullable=False, default="")
        email = db.Column(db.String(220), nullable=False, default="")
        phone = db.Column(db.String(80), nullable=False, default="")
        zones = db.Column(db.Text, nullable=False, default="")
        specialties = db.Column(db.Text, nullable=False, default="")
        capacity_note = db.Column(db.Text, nullable=False, default="")
        availability = db.Column(db.String(100), nullable=False, default="Da verificare")
        documents_status = db.Column(db.String(60), nullable=False, default="Da verificare")
        documents_ref = db.Column(db.String(500), nullable=False, default="")
        nda_status = db.Column(db.String(60), nullable=False, default="Da verificare")
        nda_ref = db.Column(db.String(500), nullable=False, default="")
        contract_ref = db.Column(db.String(500), nullable=False, default="")
        specifications_ref = db.Column(db.String(500), nullable=False, default="")
        accepted_offer_ref = db.Column(db.String(500), nullable=False, default="")
        approved_plan_ref = db.Column(db.String(500), nullable=False, default="")
        conflict_declaration = db.Column(db.Text, nullable=False, default="")
        confidentiality_note = db.Column(db.Text, nullable=False, default="")
        status = db.Column(db.String(40), nullable=False, default="Da qualificare")
        decision_note = db.Column(db.Text, nullable=False, default="")
        decision_evidence = db.Column(db.String(500), nullable=False, default="")
        decided_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        decided_at = db.Column(db.DateTime(timezone=True))
        version = db.Column(db.Integer, nullable=False, default=1)
        active = db.Column(db.Boolean, nullable=False, default=True)
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    class PartnerPerformanceAssignment(db.Model):
        __tablename__ = "partner_performance_assignment"
        id = db.Column(db.Integer, primary_key=True)
        partner_id = db.Column(db.Integer, db.ForeignKey("partner_registry.id"), nullable=False, index=True)
        quote_id = db.Column(db.Integer, nullable=True, index=True)
        worksite_id = db.Column(db.Integer, nullable=True, index=True)
        phase_id = db.Column(db.Integer, nullable=True, index=True)
        role = db.Column(db.String(220), nullable=False)
        scope = db.Column(db.Text, nullable=False)
        assumptions = db.Column(db.Text, nullable=False, default="")
        exclusions = db.Column(db.Text, nullable=False, default="")
        dependencies = db.Column(db.Text, nullable=False, default="")
        quoted_cost = db.Column(db.Float, nullable=False, default=0)
        final_cost = db.Column(db.Float, nullable=False, default=0)
        extra_cost = db.Column(db.Float, nullable=False, default=0)
        delay_cost = db.Column(db.Float, nullable=False, default=0)
        nonconformity_cost = db.Column(db.Float, nullable=False, default=0)
        operational_cost = db.Column(db.Float, nullable=False, default=0)
        promised_end_at = db.Column(db.DateTime(timezone=True))
        actual_end_at = db.Column(db.DateTime(timezone=True))
        status = db.Column(db.String(40), nullable=False, default="Da confermare")
        quality_validation = db.Column(db.String(40), nullable=False, default="Da verificare")
        documentation_validation = db.Column(db.String(40), nullable=False, default="Da verificare")
        evidence_ref = db.Column(db.String(500), nullable=False, default="")
        critical_defects = db.Column(db.Integer, nullable=False, default=0)
        nonconformities = db.Column(db.Integer, nullable=False, default=0)
        performance_note = db.Column(db.Text, nullable=False, default="")
        accepted_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        accepted_at = db.Column(db.DateTime(timezone=True))
        created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    class PartnerEvent(db.Model):
        __tablename__ = "partner_event"
        id = db.Column(db.Integer, primary_key=True)
        partner_id = db.Column(db.Integer, db.ForeignKey("partner_registry.id"), nullable=False, index=True)
        assignment_id = db.Column(db.Integer)
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

    def event(partner, user, action, detail="", assignment=None):
        db.session.add(PartnerEvent(partner_id=partner.id, assignment_id=assignment.id if assignment else None,
                                    actor_user_id=user.id, action=action, detail=app_module.clean_text(detail, 500)))

    def assignment_dict(row):
        total = row.final_cost + row.extra_cost + row.delay_cost + row.nonconformity_cost + row.operational_cost
        delay = None
        if row.promised_end_at and row.actual_end_at:
            delay = max(0, (row.actual_end_at.replace(tzinfo=None) - row.promised_end_at.replace(tzinfo=None)).days)
        return {"id":row.id,"partner_id":row.partner_id,"quote_id":row.quote_id,"worksite_id":row.worksite_id,
                "phase_id":row.phase_id,"role":row.role,"scope":row.scope,"assumptions":row.assumptions,
                "exclusions":row.exclusions,"dependencies":row.dependencies,"quoted_cost":row.quoted_cost,
                "final_cost":row.final_cost,"extra_cost":row.extra_cost,"delay_cost":row.delay_cost,
                "nonconformity_cost":row.nonconformity_cost,"operational_cost":row.operational_cost,
                "total_supplier_cost":total,"cost_variance":total-row.quoted_cost,
                "promised_end_at":row.promised_end_at.isoformat() if row.promised_end_at else None,
                "actual_end_at":row.actual_end_at.isoformat() if row.actual_end_at else None,"delay_days":delay,
                "status":row.status,"quality_validation":row.quality_validation,
                "documentation_validation":row.documentation_validation,"evidence_ref":row.evidence_ref,
                "critical_defects":row.critical_defects,"nonconformities":row.nonconformities,
                "performance_note":row.performance_note,"accepted_at":row.accepted_at.isoformat() if row.accepted_at else None}

    def partner_dict(row, include_history=False):
        assignments = PartnerPerformanceAssignment.query.filter_by(partner_id=row.id).order_by(PartnerPerformanceAssignment.created_at.desc()).all()
        completed = [assignment_dict(x) for x in assignments if x.status in {"Accettato", "Chiuso", "Contestato"}]
        total_quoted = sum(x["quoted_cost"] for x in completed); total_cost = sum(x["total_supplier_cost"] for x in completed)
        measured_delays = [x["delay_days"] for x in completed if x["delay_days"] is not None]
        indicators = {"assignments":len(assignments),"measured_assignments":len(completed),"quoted_total":total_quoted,
                      "supplier_cost_total":total_cost,"cost_variance":total_cost-total_quoted,
                      "average_delay_days":round(sum(measured_delays)/len(measured_delays),1) if measured_delays else None,
                      "critical_defects":sum(x["critical_defects"] for x in completed),
                      "nonconformities":sum(x["nonconformities"] for x in completed),
                      "quality_conformity":sum(x["quality_validation"]=="Conforme" for x in completed),
                      "documentation_conformity":sum(x["documentation_validation"]=="Conforme" for x in completed)}
        qualification_missing=[]
        if row.nda_status!="Firmato" or not row.nda_ref: qualification_missing.append("NDA firmato")
        if row.documents_status!="Verificati" or not row.documents_ref: qualification_missing.append("documenti verificati")
        if not row.conflict_declaration: qualification_missing.append("dichiarazione conflitti")
        data={"id":row.id,"name":row.name,"partner_type":row.partner_type,"tax_reference":row.tax_reference,
              "contact_name":row.contact_name,"email":row.email,"phone":row.phone,"zones":row.zones,
              "specialties":row.specialties,"capacity_note":row.capacity_note,"availability":row.availability,
              "documents_status":row.documents_status,"documents_ref":row.documents_ref,"nda_status":row.nda_status,
              "nda_ref":row.nda_ref,"contract_ref":row.contract_ref,"specifications_ref":row.specifications_ref,
              "accepted_offer_ref":row.accepted_offer_ref,"approved_plan_ref":row.approved_plan_ref,
              "conflict_declaration":row.conflict_declaration,"confidentiality_note":row.confidentiality_note,
              "status":row.status,"decision_note":row.decision_note,"decision_evidence":row.decision_evidence,
              "decided_at":row.decided_at.isoformat() if row.decided_at else None,"version":row.version,
              "active":row.active,"qualification_missing":qualification_missing,"indicators":indicators,
              "assignments":[assignment_dict(x) for x in assignments],"updated_at":row.updated_at.isoformat() if row.updated_at else None}
        if include_history:data["events"]=[{"id":x.id,"assignment_id":x.assignment_id,"action":x.action,"detail":x.detail,
                                           "actor_user_id":x.actor_user_id,"created_at":x.created_at.isoformat()}
                                          for x in PartnerEvent.query.filter_by(partner_id=row.id).order_by(PartnerEvent.id.desc()).all()]
        return data

    @app.get("/api/staff/partners")
    def list_partners():
        user,denied=actor("partner_registry_read")
        if denied:return denied
        return jsonify(partners=[partner_dict(x) for x in Partner.query.order_by(Partner.name).all()])

    @app.get("/api/staff/partners/<int:partner_id>")
    def get_partner(partner_id):
        user,denied=actor("partner_registry_read")
        if denied:return denied
        row=db.session.get(Partner,partner_id)
        return (jsonify(partner=partner_dict(row,True)) if row else (jsonify(error="Partner non trovato."),404))

    @app.post("/api/staff/partners")
    def create_partner():
        user,denied=actor("partner_registry_manage")
        if denied:return denied
        data=request.get_json(silent=True) or {};name=app_module.clean_text(data.get("name"),220);kind=data.get("partner_type")
        if not name or kind not in PARTNER_TYPES:return jsonify(error="Nome e tipo di partner sono obbligatori."),400
        row=Partner(name=name,partner_type=kind);db.session.add(row);db.session.flush();event(row,user,"Partner registrato",name);db.session.commit()
        return jsonify(partner=partner_dict(row,True)),201

    @app.patch("/api/staff/partners/<int:partner_id>")
    def update_partner(partner_id):
        user,denied=actor("partner_registry_manage")
        if denied:return denied
        row=db.session.get(Partner,partner_id)
        if not row:return jsonify(error="Partner non trovato."),404
        data=request.get_json(silent=True) or {}
        for key,limit in (("name",220),("tax_reference",100),("contact_name",220),("email",220),("phone",80),("zones",2000),
                          ("specialties",2000),("capacity_note",5000),("availability",100),("documents_status",60),
                          ("documents_ref",500),("nda_status",60),("nda_ref",500),("contract_ref",500),("specifications_ref",500),
                          ("accepted_offer_ref",500),("approved_plan_ref",500),("conflict_declaration",5000),("confidentiality_note",5000)):
            if key in data:setattr(row,key,app_module.clean_text(data.get(key),limit))
        if "partner_type" in data:
            if data["partner_type"] not in PARTNER_TYPES:return jsonify(error="Tipo partner non valido."),400
            row.partner_type=data["partner_type"]
        row.version+=1;event(row,user,"Anagrafica aggiornata",data.get("change_note",""));db.session.commit();return jsonify(partner=partner_dict(row,True))

    @app.post("/api/admin/partners/<int:partner_id>/decision")
    def decide_partner(partner_id):
        user,denied=actor("partner_registry_approve")
        if denied:return denied
        row=db.session.get(Partner,partner_id);data=request.get_json(silent=True) or {};status=data.get("status");note=app_module.clean_text(data.get("note"),5000);evidence=app_module.clean_text(data.get("evidence_ref"),500)
        if not row:return jsonify(error="Partner non trovato."),404
        if status not in PARTNER_STATUSES or not note or not evidence:return jsonify(error="Stato, motivazione ed evidenza sono obbligatori."),400
        missing=partner_dict(row)["qualification_missing"]
        if status=="Idoneo" and missing:return jsonify(error="Idoneità bloccata: completare "+", ".join(missing)+"."),409
        row.status=status;row.decision_note=note;row.decision_evidence=evidence;row.decided_by_user_id=user.id;row.decided_at=utcnow();row.active=status not in {"Sospeso","Escluso"};row.version+=1
        event(row,user,"Decisione partner",status);db.session.commit();return jsonify(partner=partner_dict(row,True))

    @app.post("/api/staff/partners/<int:partner_id>/assignments")
    def create_assignment(partner_id):
        user,denied=actor("partner_registry_manage")
        if denied:return denied
        partner=db.session.get(Partner,partner_id);data=request.get_json(silent=True) or {};role=app_module.clean_text(data.get("role"),220);scope=app_module.clean_text(data.get("scope"),5000)
        if not partner or not partner.active:return jsonify(error="Partner non disponibile."),409
        if not role or not scope:return jsonify(error="Ruolo e perimetro dell’incarico sono obbligatori."),400
        try:
            quote_id=int(data["quote_id"]) if data.get("quote_id") else None;worksite_id=int(data["worksite_id"]) if data.get("worksite_id") else None;phase_id=int(data["phase_id"]) if data.get("phase_id") else None
            quoted=float(data.get("quoted_cost") or 0)
        except (TypeError,ValueError):return jsonify(error="Collegamenti o importo non validi."),400
        Quote=(app.extensions.get("aplsai_quotes") or {}).get("QuoteRequest");Worksite=(app.extensions.get("aplsai_worksites") or {}).get("WorksiteProject");Phase=(app.extensions.get("aplsai_worksites") or {}).get("WorksitePhase")
        if quote_id and (not Quote or not db.session.get(Quote,quote_id)):return jsonify(error="Preventivo collegato non valido."),400
        if worksite_id and (not Worksite or not db.session.get(Worksite,worksite_id)):return jsonify(error="Cantiere collegato non valido."),400
        if phase_id and (not Phase or not db.session.get(Phase,phase_id)):return jsonify(error="Fase collegata non valida."),400
        row=PartnerPerformanceAssignment(partner_id=partner.id,quote_id=quote_id,worksite_id=worksite_id,phase_id=phase_id,role=role,scope=scope,
                              assumptions=app_module.clean_text(data.get("assumptions"),5000),exclusions=app_module.clean_text(data.get("exclusions"),5000),
                              dependencies=app_module.clean_text(data.get("dependencies"),5000),quoted_cost=max(0,quoted),created_by_user_id=user.id,
                              promised_end_at=parse_date(data.get("promised_end_at")))
        db.session.add(row);db.session.flush();event(partner,user,"Incarico registrato",role,row);db.session.commit();return jsonify(partner=partner_dict(partner,True)),201

    @app.patch("/api/staff/partner-assignments/<int:assignment_id>")
    def update_assignment(assignment_id):
        user,denied=actor("partner_registry_manage")
        if denied:return denied
        row=db.session.get(PartnerPerformanceAssignment,assignment_id);partner=db.session.get(Partner,row.partner_id) if row else None;data=request.get_json(silent=True) or {}
        if not row:return jsonify(error="Incarico non trovato."),404
        try:
            for key in ("quoted_cost","final_cost","extra_cost","delay_cost","nonconformity_cost","operational_cost"):
                if key in data:
                    value=float(data.get(key) or 0)
                    if value<0:raise ValueError
                    setattr(row,key,value)
            for key in ("critical_defects","nonconformities"):
                if key in data:
                    value=int(data.get(key) or 0)
                    if value<0:raise ValueError
                    setattr(row,key,value)
            if "actual_end_at" in data:row.actual_end_at=parse_date(data.get("actual_end_at"))
        except (TypeError,ValueError):return jsonify(error="Consuntivo non valido."),400
        for key,limit in (("evidence_ref",500),("performance_note",5000)):
            if key in data:setattr(row,key,app_module.clean_text(data.get(key),limit))
        for key in ("quality_validation","documentation_validation"):
            if key in data:
                if data[key] not in VALIDATIONS:return jsonify(error="Validazione non valida."),400
                setattr(row,key,data[key])
        if "status" in data:
            status=data["status"]
            if status not in ASSIGNMENT_STATUSES-{"Accettato","Chiuso"}:return jsonify(error="Stato incarico non valido."),400
            row.status=status
        event(partner,user,"Incarico aggiornato",row.status,row);db.session.commit();return jsonify(partner=partner_dict(partner,True))

    @app.post("/api/admin/partner-assignments/<int:assignment_id>/accept")
    def accept_assignment(assignment_id):
        user,denied=actor("partner_registry_approve")
        if denied:return denied
        row=db.session.get(PartnerPerformanceAssignment,assignment_id);partner=db.session.get(Partner,row.partner_id) if row else None;data=request.get_json(silent=True) or {};note=app_module.clean_text(data.get("note"),5000)
        if not row:return jsonify(error="Incarico non trovato."),404
        if not row.evidence_ref or not row.actual_end_at or row.quality_validation=="Da verificare" or row.documentation_validation=="Da verificare" or not note:
            return jsonify(error="Accettazione bloccata: servono consuntivo, evidenza, data effettiva, validazioni e nota."),409
        if row.critical_defects:return jsonify(error="Accettazione bloccata: difetti critici aperti."),409
        row.status="Accettato";row.performance_note=note;row.accepted_by_user_id=user.id;row.accepted_at=utcnow();event(partner,user,"Prestazione accettata",row.role,row);db.session.commit();return jsonify(partner=partner_dict(partner,True))

    app.extensions["aplsai_partners"]={"Partner":Partner,"PartnerAssignment":PartnerPerformanceAssignment,"PartnerEvent":PartnerEvent,"partner_dict":partner_dict,"assignment_dict":assignment_dict}
