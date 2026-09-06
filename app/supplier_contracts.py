from datetime import datetime, timezone

from flask import jsonify, request, session

from .rbac import has_permission


CONTRACT_STATUSES = {"Da formalizzare", "Condizioni da completare", "Attivo", "Sospeso", "Chiuso"}
MILESTONE_STATUSES = {"Pianificata", "In corso", "Consegnata", "Accettata", "Contestata"}
PAYMENT_STATUSES = {"Non richiesto", "Richiesto", "Autorizzato", "Pagato"}
VARIATION_TYPES = {"Riuso", "Completamento", "Riprogettazione"}
DOCUMENTS = [
    ("ARCH", "Architettura tecnica"), ("API", "Documentazione API"), ("DATA", "Schema dati"),
    ("INSTALL", "Installazione e ripristino"), ("THIRD", "Inventario terze parti, open source, licenze e costi"),
    ("CREDS", "Credenziali amministrative"), ("ENVS", "Ambienti sviluppo, test e produzione"),
    ("BACKUP", "Backup e prova di ripristino"), ("CONFIG", "Configurazioni operative"),
    ("EXIT", "Piano di uscita e consegna completa"),
]


def utcnow(): return datetime.now(timezone.utc)


def parse_date(value):
    if value in {None, ""}: return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if not parsed.tzinfo else parsed.astimezone(timezone.utc)


def init_supplier_contracts(app, app_module):
    if app.extensions.get("aplsai_supplier_contracts"): return
    db = app_module.db

    class SupplierContract(db.Model):
        __tablename__ = "supplier_contract_control"
        id = db.Column(db.Integer, primary_key=True)
        code = db.Column(db.String(40), nullable=False, unique=True)
        procurement_case_id = db.Column(db.Integer, db.ForeignKey("procurement_case.id"), nullable=False, unique=True)
        offer_id = db.Column(db.Integer, db.ForeignKey("procurement_offer.id"), nullable=False)
        partner_id = db.Column(db.Integer, db.ForeignKey("partner_registry.id"), nullable=False)
        title = db.Column(db.String(220), nullable=False)
        contract_ref = db.Column(db.String(500), nullable=False, default="")
        signed_evidence = db.Column(db.String(500), nullable=False, default="")
        requirements_frozen_ref = db.Column(db.String(500), nullable=False, default="")
        golden_cases_ref = db.Column(db.String(500), nullable=False, default="")
        sources_criteria_signed_ref = db.Column(db.String(500), nullable=False, default="")
        professional_verification_ref = db.Column(db.String(500), nullable=False, default="")
        ip_assignment_ref = db.Column(db.String(500), nullable=False, default="")
        preexisting_components_ref = db.Column(db.String(500), nullable=False, default="")
        repository_control_ref = db.Column(db.String(500), nullable=False, default="")
        cloud_control_ref = db.Column(db.String(500), nullable=False, default="")
        credentials_control_ref = db.Column(db.String(500), nullable=False, default="")
        data_control_ref = db.Column(db.String(500), nullable=False, default="")
        exit_plan_ref = db.Column(db.String(500), nullable=False, default="")
        status = db.Column(db.String(50), nullable=False, default="Da formalizzare")
        start_note = db.Column(db.Text, nullable=False, default="")
        started_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        started_at = db.Column(db.DateTime(timezone=True))
        closing_note = db.Column(db.Text, nullable=False, default="")
        closed_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        closed_at = db.Column(db.DateTime(timezone=True))
        version = db.Column(db.Integer, nullable=False, default=1)
        created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    class ContractMilestone(db.Model):
        __tablename__ = "supplier_contract_milestone"
        id = db.Column(db.Integer, primary_key=True)
        contract_id = db.Column(db.Integer, db.ForeignKey("supplier_contract_control.id"), nullable=False, index=True)
        code = db.Column(db.String(40), nullable=False)
        title = db.Column(db.String(220), nullable=False)
        module_scope = db.Column(db.Text, nullable=False)
        deliverable = db.Column(db.Text, nullable=False)
        acceptance_criteria = db.Column(db.Text, nullable=False)
        dependencies = db.Column(db.Text, nullable=False, default="")
        planned_amount = db.Column(db.Float, nullable=False, default=0)
        due_at = db.Column(db.DateTime(timezone=True))
        status = db.Column(db.String(40), nullable=False, default="Pianificata")
        evidence_ref = db.Column(db.String(500), nullable=False, default="")
        test_result = db.Column(db.Text, nullable=False, default="")
        critical_defects = db.Column(db.Integer, nullable=False, default=0)
        residual_defects = db.Column(db.Text, nullable=False, default="")
        cost_to_complete = db.Column(db.Float, nullable=False, default=0)
        acceptance_note = db.Column(db.Text, nullable=False, default="")
        accepted_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        accepted_at = db.Column(db.DateTime(timezone=True))
        payment_status = db.Column(db.String(40), nullable=False, default="Non richiesto")
        requested_amount = db.Column(db.Float, nullable=False, default=0)
        payment_evidence = db.Column(db.String(500), nullable=False, default="")
        authorized_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        authorized_at = db.Column(db.DateTime(timezone=True))
        paid_amount = db.Column(db.Float, nullable=False, default=0)
        paid_ref = db.Column(db.String(500), nullable=False, default="")
        paid_at = db.Column(db.DateTime(timezone=True))
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
        __table_args__ = (db.UniqueConstraint("contract_id", "code", name="uq_supplier_contract_milestone"),)

    class ContractDocument(db.Model):
        __tablename__ = "supplier_contract_document"
        id = db.Column(db.Integer, primary_key=True)
        contract_id = db.Column(db.Integer, db.ForeignKey("supplier_contract_control.id"), nullable=False, index=True)
        code = db.Column(db.String(40), nullable=False)
        title = db.Column(db.String(250), nullable=False)
        status = db.Column(db.String(40), nullable=False, default="Da consegnare")
        evidence_ref = db.Column(db.String(500), nullable=False, default="")
        note = db.Column(db.Text, nullable=False, default="")
        verified_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        verified_at = db.Column(db.DateTime(timezone=True))
        __table_args__ = (db.UniqueConstraint("contract_id", "code", name="uq_supplier_contract_document"),)

    class ContractVariation(db.Model):
        __tablename__ = "supplier_contract_variation"
        id = db.Column(db.Integer, primary_key=True)
        contract_id = db.Column(db.Integer, db.ForeignKey("supplier_contract_control.id"), nullable=False, index=True)
        milestone_id = db.Column(db.Integer, db.ForeignKey("supplier_contract_milestone.id"))
        description = db.Column(db.Text, nullable=False)
        reason = db.Column(db.Text, nullable=False)
        change_type = db.Column(db.String(40), nullable=False)
        cost_impact = db.Column(db.Float, nullable=False, default=0)
        delay_days = db.Column(db.Integer, nullable=False, default=0)
        evidence_ref = db.Column(db.String(500), nullable=False)
        status = db.Column(db.String(40), nullable=False, default="Da approvare")
        decision_note = db.Column(db.Text, nullable=False, default="")
        decided_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        decided_at = db.Column(db.DateTime(timezone=True))
        created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    class ContractEvent(db.Model):
        __tablename__ = "supplier_contract_event"
        id = db.Column(db.Integer, primary_key=True)
        contract_id = db.Column(db.Integer, db.ForeignKey("supplier_contract_control.id"), nullable=False, index=True)
        object_type = db.Column(db.String(40), nullable=False)
        object_id = db.Column(db.Integer)
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

    def event(contract, user, action, detail="", object_type="Contratto", object_id=None):
        db.session.add(ContractEvent(contract_id=contract.id, object_type=object_type, object_id=object_id,
                                     actor_user_id=user.id, action=action, detail=app_module.clean_text(detail, 500)))

    def start_missing(row, software):
        fields = [(row.contract_ref, "contratto firmato"), (row.signed_evidence, "evidenza firma"),
                  (row.requirements_frozen_ref, "requisiti congelati"), (row.golden_cases_ref, "Casi Oro v1.0"),
                  (row.sources_criteria_signed_ref, "fonti, responsabili e criteri firmati"),
                  (row.professional_verification_ref, "verifica professionale dei presupposti")]
        if software:
            fields += [(row.ip_assignment_ref, "cessione diritti sul codice"),
                       (row.preexisting_components_ref, "disciplina componenti preesistenti"),
                       (row.repository_control_ref, "controllo repository"), (row.cloud_control_ref, "controllo cloud"),
                       (row.credentials_control_ref, "controllo credenziali"), (row.data_control_ref, "controllo dati")]
        return [label for value, label in fields if not value]

    def milestone_dict(row):
        approved_extra = sum(v.cost_impact for v in ContractVariation.query.filter_by(milestone_id=row.id, status="Approvata").all())
        return {"id":row.id,"contract_id":row.contract_id,"code":row.code,"title":row.title,"module_scope":row.module_scope,
                "deliverable":row.deliverable,"acceptance_criteria":row.acceptance_criteria,"dependencies":row.dependencies,
                "planned_amount":row.planned_amount,"approved_extra":approved_extra,"authorized_limit":row.planned_amount+approved_extra,
                "due_at":row.due_at.isoformat() if row.due_at else None,"status":row.status,"evidence_ref":row.evidence_ref,
                "test_result":row.test_result,"critical_defects":row.critical_defects,"residual_defects":row.residual_defects,
                "cost_to_complete":row.cost_to_complete,"acceptance_note":row.acceptance_note,
                "accepted_at":row.accepted_at.isoformat() if row.accepted_at else None,"payment_status":row.payment_status,
                "requested_amount":row.requested_amount,"payment_evidence":row.payment_evidence,"paid_amount":row.paid_amount,
                "paid_ref":row.paid_ref,"paid_at":row.paid_at.isoformat() if row.paid_at else None}

    def contract_dict(row, history=False):
        procurement_ext = app.extensions.get("aplsai_procurement") or {}; Case = procurement_ext.get("ProcurementCase"); Offer = procurement_ext.get("ProcurementOffer")
        partner_ext = app.extensions.get("aplsai_partners") or {}; Partner = partner_ext.get("Partner")
        case = db.session.get(Case, row.procurement_case_id) if Case else None; offer = db.session.get(Offer, row.offer_id) if Offer else None
        partner = db.session.get(Partner, row.partner_id) if Partner else None; software = bool(case and case.case_type == "Software e tecnologia")
        milestones = ContractMilestone.query.filter_by(contract_id=row.id).order_by(ContractMilestone.id).all()
        documents = ContractDocument.query.filter_by(contract_id=row.id).order_by(ContractDocument.id).all()
        variations = ContractVariation.query.filter_by(contract_id=row.id).order_by(ContractVariation.id).all()
        approved_variations = sum(x.cost_impact for x in variations if x.status == "Approvata")
        planned = sum(x.planned_amount for x in milestones); paid = sum(x.paid_amount for x in milestones)
        data = {"id":row.id,"code":row.code,"procurement_case_id":row.procurement_case_id,"offer_id":row.offer_id,
                "partner_id":row.partner_id,"partner_name":partner.name if partner else "","title":row.title,
                "case_type":case.case_type if case else "","offer_tco_24m":procurement_ext.get("offer_dict")(offer, case.case_type).get("tco_24m") if offer and case and procurement_ext.get("offer_dict") else 0,
                "contract_ref":row.contract_ref,"signed_evidence":row.signed_evidence,"requirements_frozen_ref":row.requirements_frozen_ref,
                "golden_cases_ref":row.golden_cases_ref,"sources_criteria_signed_ref":row.sources_criteria_signed_ref,
                "professional_verification_ref":row.professional_verification_ref,"ip_assignment_ref":row.ip_assignment_ref,
                "preexisting_components_ref":row.preexisting_components_ref,"repository_control_ref":row.repository_control_ref,
                "cloud_control_ref":row.cloud_control_ref,"credentials_control_ref":row.credentials_control_ref,
                "data_control_ref":row.data_control_ref,"exit_plan_ref":row.exit_plan_ref,"status":row.status,
                "start_note":row.start_note,"started_at":row.started_at.isoformat() if row.started_at else None,
                "closing_note":row.closing_note,"closed_at":row.closed_at.isoformat() if row.closed_at else None,
                "version":row.version,"start_missing":start_missing(row, software),"planned_total":planned,
                "approved_variations_total":approved_variations,"authorized_contract_total":planned+approved_variations,
                "paid_total":paid,"milestones":[milestone_dict(x) for x in milestones],
                "documents":[{"id":x.id,"code":x.code,"title":x.title,"status":x.status,"evidence_ref":x.evidence_ref,
                              "note":x.note,"verified_at":x.verified_at.isoformat() if x.verified_at else None} for x in documents],
                "variations":[{"id":x.id,"milestone_id":x.milestone_id,"description":x.description,"reason":x.reason,
                               "change_type":x.change_type,"cost_impact":x.cost_impact,"delay_days":x.delay_days,
                               "evidence_ref":x.evidence_ref,"status":x.status,"decision_note":x.decision_note,
                               "decided_at":x.decided_at.isoformat() if x.decided_at else None} for x in variations]}
        if history: data["events"]=[{"id":x.id,"object_type":x.object_type,"object_id":x.object_id,"actor_user_id":x.actor_user_id,
                                     "action":x.action,"detail":x.detail,"created_at":x.created_at.isoformat()}
                                    for x in ContractEvent.query.filter_by(contract_id=row.id).order_by(ContractEvent.id.desc()).all()]
        return data

    @app.get("/api/staff/supplier-contracts")
    def list_supplier_contracts():
        user, denied = actor("supplier_contract_read")
        if denied: return denied
        return jsonify(contracts=[contract_dict(x) for x in SupplierContract.query.order_by(SupplierContract.id.desc()).all()])

    @app.get("/api/staff/supplier-contracts/<int:contract_id>")
    def get_supplier_contract(contract_id):
        user, denied = actor("supplier_contract_read")
        if denied: return denied
        row=db.session.get(SupplierContract,contract_id)
        return jsonify(contract=contract_dict(row,True)) if row else (jsonify(error="Contratto non trovato."),404)

    @app.post("/api/staff/supplier-contracts")
    def create_supplier_contract():
        user, denied = actor("supplier_contract_manage")
        if denied: return denied
        data=request.get_json(silent=True) or {}; procurement_ext=app.extensions.get("aplsai_procurement") or {}
        Case=procurement_ext.get("ProcurementCase");Offer=procurement_ext.get("ProcurementOffer")
        try: case_id=int(data.get("procurement_case_id"))
        except (TypeError,ValueError):case_id=0
        case=db.session.get(Case,case_id) if Case and case_id else None;offer=db.session.get(Offer,case.selected_offer_id) if case and case.selected_offer_id else None
        if not case or case.status!="Decisa" or not offer or offer.review_status!="Verificata":return jsonify(error="Serve un confronto deciso con offerta verificata."),409
        if SupplierContract.query.filter_by(procurement_case_id=case.id).first():return jsonify(error="Il contratto per questo confronto esiste già."),409
        row=SupplierContract(code="TEMP",procurement_case_id=case.id,offer_id=offer.id,partner_id=offer.partner_id,title=case.title,created_by_user_id=user.id)
        db.session.add(row);db.session.flush();row.code=f"CF-{row.id:05d}"
        if case.case_type=="Software e tecnologia":
            for code,title in DOCUMENTS:db.session.add(ContractDocument(contract_id=row.id,code=code,title=title))
        event(row,user,"Contratto operativo creato",case.title);db.session.commit();return jsonify(contract=contract_dict(row,True)),201

    @app.patch("/api/staff/supplier-contracts/<int:contract_id>")
    def update_supplier_contract(contract_id):
        user,denied=actor("supplier_contract_manage")
        if denied:return denied
        row=db.session.get(SupplierContract,contract_id);data=request.get_json(silent=True) or {}
        if not row:return jsonify(error="Contratto non trovato."),404
        for key in ("contract_ref","signed_evidence","requirements_frozen_ref","golden_cases_ref","sources_criteria_signed_ref",
                    "professional_verification_ref","ip_assignment_ref","preexisting_components_ref","repository_control_ref",
                    "cloud_control_ref","credentials_control_ref","data_control_ref","exit_plan_ref"):
            if key in data:setattr(row,key,app_module.clean_text(data.get(key),500))
        if row.status=="Da formalizzare":row.status="Condizioni da completare"
        row.version+=1;event(row,user,"Condizioni aggiornate",data.get("change_note",""));db.session.commit();return jsonify(contract=contract_dict(row,True))

    @app.post("/api/admin/supplier-contracts/<int:contract_id>/start")
    def authorize_supplier_contract_start(contract_id):
        user,denied=actor("supplier_contract_approve")
        if denied:return denied
        row=db.session.get(SupplierContract,contract_id);note=app_module.clean_text((request.get_json(silent=True) or {}).get("note"),5000)
        if not row:return jsonify(error="Contratto non trovato."),404
        missing=contract_dict(row)["start_missing"]
        if missing:return jsonify(error="Avvio bloccato: mancano "+", ".join(missing)+"."),409
        if not note:return jsonify(error="La motivazione dell’avvio è obbligatoria."),400
        row.status="Attivo";row.start_note=note;row.started_by_user_id=user.id;row.started_at=utcnow();row.version+=1
        event(row,user,"Avvio autorizzato",note);db.session.commit();return jsonify(contract=contract_dict(row,True))

    @app.post("/api/staff/supplier-contracts/<int:contract_id>/milestones")
    def create_supplier_contract_milestone(contract_id):
        user,denied=actor("supplier_contract_manage")
        if denied:return denied
        row=db.session.get(SupplierContract,contract_id);data=request.get_json(silent=True) or {}
        code=app_module.clean_text(data.get("code"),40);title=app_module.clean_text(data.get("title"),220)
        scope=app_module.clean_text(data.get("module_scope"),5000);deliverable=app_module.clean_text(data.get("deliverable"),5000);criteria=app_module.clean_text(data.get("acceptance_criteria"),5000)
        if not row or not all((code,title,scope,deliverable,criteria)):return jsonify(error="Codice, titolo, modulo, risultato e criteri sono obbligatori."),400
        try:amount=max(0,float(data.get("planned_amount") or 0));due=parse_date(data.get("due_at"))
        except (TypeError,ValueError):return jsonify(error="Importo o scadenza non validi."),400
        milestone=ContractMilestone(contract_id=row.id,code=code,title=title,module_scope=scope,deliverable=deliverable,
            acceptance_criteria=criteria,dependencies=app_module.clean_text(data.get("dependencies"),5000),planned_amount=amount,due_at=due)
        db.session.add(milestone);db.session.flush();event(row,user,"Milestone creata",code,"Milestone",milestone.id)
        try:db.session.commit()
        except Exception:db.session.rollback();return jsonify(error="Codice milestone già utilizzato."),409
        return jsonify(contract=contract_dict(row,True)),201

    @app.patch("/api/staff/contract-milestones/<int:milestone_id>")
    def update_supplier_contract_milestone(milestone_id):
        user,denied=actor("supplier_contract_manage")
        if denied:return denied
        row=db.session.get(ContractMilestone,milestone_id);data=request.get_json(silent=True) or {}
        if not row:return jsonify(error="Milestone non trovata."),404
        if row.status=="Accettata":return jsonify(error="Milestone già accettata: il consuntivo è bloccato."),409
        contract=db.session.get(SupplierContract,row.contract_id)
        for key,limit in (("evidence_ref",500),("test_result",5000),("residual_defects",5000),("payment_evidence",500)):
            if key in data:setattr(row,key,app_module.clean_text(data.get(key),limit))
        try:
            for key in ("cost_to_complete","requested_amount"):
                if key in data:
                    value=float(data.get(key) or 0)
                    if value<0:raise ValueError
                    setattr(row,key,value)
            if "critical_defects" in data:
                row.critical_defects=int(data.get("critical_defects") or 0)
                if row.critical_defects<0:raise ValueError
        except (TypeError,ValueError):return jsonify(error="Consuntivo non valido."),400
        if "status" in data:
            if data["status"] not in MILESTONE_STATUSES-{"Accettata"}:return jsonify(error="Stato non valido."),400
            row.status=data["status"]
        if row.requested_amount>0 and row.payment_status=="Non richiesto":row.payment_status="Richiesto"
        event(contract,user,"Milestone aggiornata",row.code,"Milestone",row.id);db.session.commit();return jsonify(contract=contract_dict(contract,True))

    @app.post("/api/admin/contract-milestones/<int:milestone_id>/accept")
    def accept_supplier_contract_milestone(milestone_id):
        user,denied=actor("supplier_contract_approve")
        if denied:return denied
        row=db.session.get(ContractMilestone,milestone_id);note=app_module.clean_text((request.get_json(silent=True) or {}).get("note"),5000)
        if not row:return jsonify(error="Milestone non trovata."),404
        contract=db.session.get(SupplierContract,row.contract_id)
        if row.status!="Consegnata" or not row.evidence_ref or not row.test_result or not note:return jsonify(error="Accettazione bloccata: servono consegna, evidenza, collaudo e verbale."),409
        if row.critical_defects:return jsonify(error="Accettazione bloccata: correggere i difetti critici."),409
        row.status="Accettata";row.acceptance_note=note;row.accepted_by_user_id=user.id;row.accepted_at=utcnow()
        event(contract,user,"Milestone accettata",row.code,"Milestone",row.id);db.session.commit();return jsonify(contract=contract_dict(contract,True))

    @app.post("/api/admin/contract-milestones/<int:milestone_id>/authorize-payment")
    def authorize_supplier_contract_payment(milestone_id):
        user,denied=actor("supplier_contract_approve")
        if denied:return denied
        row=db.session.get(ContractMilestone,milestone_id);data=request.get_json(silent=True) or {};evidence=app_module.clean_text(data.get("evidence_ref"),500)
        if not row:return jsonify(error="Milestone non trovata."),404
        contract=db.session.get(SupplierContract,row.contract_id);limit=milestone_dict(row)["authorized_limit"]
        if row.status!="Accettata" or row.requested_amount<=0 or not evidence:return jsonify(error="Pagamento bloccato: milestone accettata, importo ed evidenza sono obbligatori."),409
        if row.requested_amount>limit:return jsonify(error="Pagamento superiore all’importo contrattuale e alle varianti approvate."),409
        row.payment_status="Autorizzato";row.payment_evidence=evidence;row.authorized_by_user_id=user.id;row.authorized_at=utcnow()
        event(contract,user,"Pagamento autorizzato",f"{row.code}: {row.requested_amount}","Milestone",row.id);db.session.commit();return jsonify(contract=contract_dict(contract,True))

    @app.post("/api/admin/contract-milestones/<int:milestone_id>/paid")
    def mark_supplier_contract_paid(milestone_id):
        user,denied=actor("supplier_contract_approve")
        if denied:return denied
        row=db.session.get(ContractMilestone,milestone_id);data=request.get_json(silent=True) or {};ref=app_module.clean_text(data.get("paid_ref"),500)
        if not row or row.payment_status!="Autorizzato" or not ref:return jsonify(error="Pagamento non autorizzato o riferimento mancante."),409
        try:amount=float(data.get("paid_amount") or 0)
        except (TypeError,ValueError):return jsonify(error="Importo pagato non valido."),400
        if amount<=0 or amount>row.requested_amount:return jsonify(error="Importo pagato superiore a quello autorizzato o non valido."),409
        contract=db.session.get(SupplierContract,row.contract_id);row.payment_status="Pagato";row.paid_amount=amount;row.paid_ref=ref;row.paid_at=utcnow()
        event(contract,user,"Pagamento registrato",f"{row.code}: {amount}","Milestone",row.id);db.session.commit();return jsonify(contract=contract_dict(contract,True))

    @app.post("/api/staff/supplier-contracts/<int:contract_id>/variations")
    def create_supplier_contract_variation(contract_id):
        user,denied=actor("supplier_contract_manage")
        if denied:return denied
        contract=db.session.get(SupplierContract,contract_id);data=request.get_json(silent=True) or {};kind=data.get("change_type")
        description=app_module.clean_text(data.get("description"),5000);reason=app_module.clean_text(data.get("reason"),5000);evidence=app_module.clean_text(data.get("evidence_ref"),500)
        if not contract or kind not in VARIATION_TYPES or not description or not reason or not evidence:return jsonify(error="Descrizione, motivo, tipo ed evidenza sono obbligatori."),400
        try:
            milestone_id=int(data.get("milestone_id")) if data.get("milestone_id") else None;cost=float(data.get("cost_impact") or 0);delay=int(data.get("delay_days") or 0)
        except (TypeError,ValueError):return jsonify(error="Impatto variante non valido."),400
        milestone=db.session.get(ContractMilestone,milestone_id) if milestone_id else None
        if milestone_id and (not milestone or milestone.contract_id!=contract.id):return jsonify(error="Milestone collegata non valida."),400
        row=ContractVariation(contract_id=contract.id,milestone_id=milestone_id,description=description,reason=reason,change_type=kind,
                              cost_impact=cost,delay_days=delay,evidence_ref=evidence,created_by_user_id=user.id)
        db.session.add(row);db.session.flush();event(contract,user,"Variante proposta",kind,"Variante",row.id);db.session.commit();return jsonify(contract=contract_dict(contract,True)),201

    @app.post("/api/admin/contract-variations/<int:variation_id>/decision")
    def decide_supplier_contract_variation(variation_id):
        user,denied=actor("supplier_contract_approve")
        if denied:return denied
        row=db.session.get(ContractVariation,variation_id);data=request.get_json(silent=True) or {};approved=bool(data.get("approved"));note=app_module.clean_text(data.get("note"),5000)
        if not row or not note:return jsonify(error="Variante o motivazione non valida."),400
        contract=db.session.get(SupplierContract,row.contract_id);row.status="Approvata" if approved else "Respinta";row.decision_note=note;row.decided_by_user_id=user.id;row.decided_at=utcnow()
        event(contract,user,"Variante decisa",row.status,"Variante",row.id);db.session.commit();return jsonify(contract=contract_dict(contract,True))

    @app.patch("/api/staff/contract-documents/<int:document_id>")
    def update_supplier_contract_document(document_id):
        user,denied=actor("supplier_contract_manage")
        if denied:return denied
        row=db.session.get(ContractDocument,document_id);data=request.get_json(silent=True) or {};status=data.get("status")
        if not row or status not in {"Da consegnare","Consegnato","Verificato","Con rilievi"}:return jsonify(error="Documento o stato non valido."),400
        evidence=app_module.clean_text(data.get("evidence_ref"),500);note=app_module.clean_text(data.get("note"),5000)
        if status in {"Consegnato","Verificato"} and not evidence:return jsonify(error="Il riferimento del documento è obbligatorio."),400
        if status=="Verificato" and not has_permission(user.role,"supplier_contract_approve"):return jsonify(error="Solo l’Admin può verificare il documento."),403
        contract=db.session.get(SupplierContract,row.contract_id);row.status=status;row.evidence_ref=evidence;row.note=note
        if status=="Verificato":row.verified_by_user_id=user.id;row.verified_at=utcnow()
        event(contract,user,"Documento aggiornato",f"{row.code}: {status}","Documento",row.id);db.session.commit();return jsonify(contract=contract_dict(contract,True))

    @app.post("/api/admin/supplier-contracts/<int:contract_id>/close")
    def close_supplier_contract(contract_id):
        user,denied=actor("supplier_contract_approve")
        if denied:return denied
        row=db.session.get(SupplierContract,contract_id);note=app_module.clean_text((request.get_json(silent=True) or {}).get("note"),5000)
        if not row or not note:return jsonify(error="Contratto o nota finale non valida."),400
        data=contract_dict(row);missing=[]
        if not data["milestones"]:missing.append("nessuna milestone contrattuale")
        if any(x["status"]!="Accettata" for x in data["milestones"]):missing.append("milestone non accettate")
        if any(x["status"]!="Verificato" for x in data["documents"]):missing.append("documenti non verificati")
        if any(x["status"]=="Da approvare" for x in data["variations"]):missing.append("varianti da decidere")
        if not row.exit_plan_ref:missing.append("piano di uscita")
        if missing:return jsonify(error="Chiusura bloccata: "+", ".join(missing)+"."),409
        row.status="Chiuso";row.closing_note=note;row.closed_by_user_id=user.id;row.closed_at=utcnow();row.version+=1
        event(row,user,"Contratto chiuso",note);db.session.commit();return jsonify(contract=contract_dict(row,True))

    app.extensions["aplsai_supplier_contracts"]={"SupplierContract":SupplierContract,"ContractMilestone":ContractMilestone,
        "ContractDocument":ContractDocument,"ContractVariation":ContractVariation,"ContractEvent":ContractEvent,
        "contract_dict":contract_dict,"milestone_dict":milestone_dict}
