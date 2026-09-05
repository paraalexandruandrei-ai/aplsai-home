from datetime import datetime, timezone

from flask import jsonify, request, session

from . import db
from .rbac import has_permission


CATEGORIES = {"Ricerca immobili", "Contatti", "Dati e documenti", "Clienti", "Privacy", "Decisioni", "Qualità"}
PRIORITIES = {"Normale", "Alta", "Bloccante"}
AUDIENCES = {"Tutto lo staff", "Operatori", "Admin"}

DEFAULT_RULES = [
    ("Ricerca immobili", "Registrare sempre la fonte", "Inserire collegamento, portale o referente, data dell’ultimo controllo e riferimento dell’annuncio. Non copiare dati senza indicarne l’origine.", "Alta"),
    ("Ricerca immobili", "Controllare i duplicati", "Prima di creare una nuova opportunità verificare che lo stesso collegamento, riferimento o indirizzo non sia già presente.", "Normale"),
    ("Clienti", "Valutare compatibilità attuale e potenziale", "Confrontare l’immobile con il Profilo Abitativo, considerando sia lo stato attuale sia il risultato possibile dopo trasformazione. Evidenziare sempre ciò che resta da verificare.", "Alta"),
    ("Contatti", "Contattare solo referenti verificati", "Usare esclusivamente recapiti presenti nella fonte o confermati. Nessun messaggio può essere inviato a un destinatario presunto.", "Bloccante"),
    ("Contatti", "Nessun impegno senza approvazione", "Non promettere prezzi, lavori, incarichi, acquisti o condizioni contrattuali. Offerte e comunicazioni impegnative richiedono approvazione dell’Admin.", "Bloccante"),
    ("Dati e documenti", "Non trasformare ipotesi in fatti", "Contrassegnare i dati come dichiarati, documentati o verificati. I dati estratti automaticamente devono essere confermati da una persona prima di aggiornare la scheda.", "Bloccante"),
    ("Privacy", "Usare i dati solo per la pratica", "Consultare e condividere dati personali e documenti solo se necessari, usando gli strumenti autorizzati da APLSAI HOME. È vietato riutilizzarli per finalità proprie.", "Bloccante"),
    ("Qualità", "Chiudere ogni attività con esito e prossima azione", "Aggiornare stato, responsabile, data, risultato, informazioni mancanti e prossima azione. Le criticità non risolte devono restare visibili.", "Alta"),
]


def init_staff_protocol(app, app_module):
    if app.extensions.get("aplsai_staff_protocol"):
        return

    class StaffRule(db.Model):
        __tablename__ = "staff_rule"
        id = db.Column(db.Integer, primary_key=True)
        category = db.Column(db.String(80), nullable=False)
        title = db.Column(db.String(180), nullable=False)
        instructions = db.Column(db.Text, nullable=False)
        priority = db.Column(db.String(30), nullable=False, default="Normale")
        audience = db.Column(db.String(40), nullable=False, default="Tutto lo staff")
        mandatory = db.Column(db.Boolean, nullable=False, default=True)
        active = db.Column(db.Boolean, nullable=False, default=True)
        sort_order = db.Column(db.Integer, nullable=False, default=0)
        version = db.Column(db.Integer, nullable=False, default=1)
        created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)

    class StaffRuleAcknowledgement(db.Model):
        __tablename__ = "staff_rule_acknowledgement"
        id = db.Column(db.Integer, primary_key=True)
        rule_id = db.Column(db.Integer, db.ForeignKey("staff_rule.id"), nullable=False, index=True)
        user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
        rule_version = db.Column(db.Integer, nullable=False)
        acknowledged_at = db.Column(db.DateTime(timezone=True), nullable=False, default=app_module.utcnow)
        __table_args__ = (db.UniqueConstraint("rule_id", "user_id", "rule_version", name="uq_staff_rule_ack_version"),)

    with app.app_context():
        db.create_all()
        if StaffRule.query.count() == 0:
            for order, (category, title, instructions, priority) in enumerate(DEFAULT_RULES, start=1):
                db.session.add(StaffRule(
                    category=category, title=title, instructions=instructions,
                    priority=priority, audience="Tutto lo staff", mandatory=True,
                    sort_order=order,
                ))
            db.session.commit()

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
            fn(actor, action, "staff_rule", object_id, detail)

    def applies(rule, actor):
        if rule.audience == "Tutto lo staff":
            return True
        if rule.audience == "Admin":
            return actor.role == "staff"
        return actor.role == "operator"

    def required_rules_for(user):
        return [
            row for row in StaffRule.query.filter_by(active=True, mandatory=True).order_by(StaffRule.sort_order.asc()).all()
            if applies(row, user)
        ]

    def pending_rules_for(user):
        required = required_rules_for(user)
        if not required:
            return []
        acknowledged = {
            (row.rule_id, row.rule_version)
            for row in StaffRuleAcknowledgement.query.filter_by(user_id=user.id).all()
        }
        return [row for row in required if (row.id, row.version) not in acknowledged]

    def rule_dict(rule, actor=None):
        acknowledged = False
        acknowledged_at = None
        if actor:
            row = StaffRuleAcknowledgement.query.filter_by(
                rule_id=rule.id, user_id=actor.id, rule_version=rule.version,
            ).first()
            acknowledged = bool(row)
            acknowledged_at = row.acknowledged_at.isoformat() if row else None
        return {
            "id": rule.id, "category": rule.category, "title": rule.title,
            "instructions": rule.instructions, "priority": rule.priority,
            "audience": rule.audience, "mandatory": rule.mandatory,
            "active": rule.active, "sort_order": rule.sort_order, "version": rule.version,
            "acknowledged": acknowledged, "acknowledged_at": acknowledged_at,
            "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
        }

    def apply_rule(rule, data):
        if "category" in data:
            rule.category = app_module.clean_text(data.get("category"), 80)
        if "title" in data:
            rule.title = app_module.clean_text(data.get("title"), 180)
        if "instructions" in data:
            rule.instructions = app_module.clean_text(data.get("instructions"), 6000)
        if "priority" in data:
            rule.priority = app_module.clean_text(data.get("priority"), 30)
        if "audience" in data:
            rule.audience = app_module.clean_text(data.get("audience"), 40)
        if "mandatory" in data:
            if not isinstance(data.get("mandatory"), bool):
                raise ValueError("Obbligatorietà non valida.")
            rule.mandatory = data["mandatory"]
        if "active" in data:
            if not isinstance(data.get("active"), bool):
                raise ValueError("Stato regola non valido.")
            rule.active = data["active"]
        if "sort_order" in data:
            try:
                rule.sort_order = max(0, min(int(data.get("sort_order")), 10000))
            except (TypeError, ValueError):
                raise ValueError("Ordine non valido.")
        if not rule.title or not rule.instructions or rule.category not in CATEGORIES:
            raise ValueError("Titolo, istruzioni o categoria non validi.")
        if rule.priority not in PRIORITIES or rule.audience not in AUDIENCES:
            raise ValueError("Priorità o destinatari non validi.")

    @app.get("/api/staff/protocol")
    def protocol_list():
        actor, denied = staff_user("protocol_read")
        if denied:
            return denied
        include_inactive = request.args.get("include_inactive") == "1" and has_permission(actor.role, "protocol_manage")
        query = StaffRule.query
        if not include_inactive:
            query = query.filter_by(active=True)
        management_view = include_inactive and has_permission(actor.role, "protocol_manage")
        all_rows = query.order_by(StaffRule.sort_order.asc(), StaffRule.id.asc()).all()
        rows = all_rows if management_view else [row for row in all_rows if applies(row, actor)]
        data = [rule_dict(row, actor) for row in rows]
        mandatory = [row for row, source in zip(data, rows) if row["mandatory"] and source.active and applies(source, actor)]
        return jsonify(rules=data, summary={
            "total": len(data), "mandatory": len(mandatory),
            "acknowledged": sum(row["acknowledged"] for row in mandatory),
            "pending": sum(not row["acknowledged"] for row in mandatory),
        })

    @app.post("/api/admin/staff-rules")
    def rule_create():
        actor, denied = staff_user("protocol_manage")
        if denied:
            return denied
        rule = StaffRule(category="", title="", instructions="", created_by_user_id=actor.id)
        try:
            apply_rule(rule, request.get_json(silent=True) or {})
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        db.session.add(rule)
        db.session.flush()
        audit(actor, "staff_rule_create", rule.id, f"priority={rule.priority}")
        db.session.commit()
        return jsonify(rule=rule_dict(rule, actor)), 201

    @app.patch("/api/admin/staff-rules/<int:rule_id>")
    def rule_update(rule_id):
        actor, denied = staff_user("protocol_manage")
        if denied:
            return denied
        rule = db.session.get(StaffRule, rule_id)
        if not rule:
            return jsonify(error="Regola non trovata."), 404
        data = request.get_json(silent=True) or {}
        try:
            apply_rule(rule, data)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        rule.version += 1
        rule.updated_at = datetime.now(timezone.utc)
        audit(actor, "staff_rule_update", rule.id, f"version={rule.version}; active={rule.active}")
        db.session.commit()
        return jsonify(rule=rule_dict(rule, actor))

    @app.get("/api/admin/staff-compliance")
    def staff_compliance():
        actor, denied = staff_user("protocol_manage")
        if denied:
            return denied
        operators = app_module.User.query.filter_by(role="operator").order_by(app_module.User.name.asc()).all()
        results = []
        for operator in operators:
            required = required_rules_for(operator)
            pending = pending_rules_for(operator)
            acknowledged_at = [
                row.acknowledged_at for row in StaffRuleAcknowledgement.query.filter_by(user_id=operator.id).all()
                if row.acknowledged_at
            ]
            results.append({
                "user_id": operator.id, "name": operator.name, "email": operator.email,
                "active": bool(getattr(operator, "active", True)),
                "required": len(required), "acknowledged": len(required) - len(pending),
                "pending": [{"id": row.id, "title": row.title, "version": row.version} for row in pending],
                "compliant": len(pending) == 0,
                "last_acknowledged_at": max(acknowledged_at).isoformat() if acknowledged_at else None,
            })
        return jsonify(operators=results)

    @app.before_request
    def enforce_operator_protocol():
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return None
        if not request.path.startswith("/api/staff/"):
            return None
        if request.path in {"/api/staff/login", "/api/staff/password"} or (
            request.path.startswith("/api/staff/protocol/") and request.path.endswith("/acknowledge")
        ):
            return None
        uid = session.get("uid")
        actor = db.session.get(app_module.User, uid) if uid else None
        if not actor or actor.role != "operator":
            return None
        pending = pending_rules_for(actor)
        if not pending:
            return None
        audit(actor, "staff_action_blocked_protocol", "system", f"path={request.path}; pending={len(pending)}")
        db.session.commit()
        return jsonify(
            error="Prima di continuare devi leggere e confermare le regole obbligatorie nella sezione Regole staff.",
            code="STAFF_PROTOCOL_REQUIRED",
            pending_rules=[{"id": row.id, "title": row.title, "version": row.version} for row in pending],
        ), 428

    @app.post("/api/staff/protocol/<int:rule_id>/acknowledge")
    def rule_acknowledge(rule_id):
        actor, denied = staff_user("protocol_read")
        if denied:
            return denied
        rule = db.session.get(StaffRule, rule_id)
        if not rule or not rule.active or not applies(rule, actor):
            return jsonify(error="Regola non disponibile."), 404
        existing = StaffRuleAcknowledgement.query.filter_by(
            rule_id=rule.id, user_id=actor.id, rule_version=rule.version,
        ).first()
        if not existing:
            existing = StaffRuleAcknowledgement(rule_id=rule.id, user_id=actor.id, rule_version=rule.version)
            db.session.add(existing)
            audit(actor, "staff_rule_acknowledge", rule.id, f"version={rule.version}")
            db.session.commit()
        return jsonify(rule=rule_dict(rule, actor))

    app.extensions["aplsai_staff_protocol"] = {
        "StaffRule": StaffRule, "StaffRuleAcknowledgement": StaffRuleAcknowledgement,
        "rule_dict": rule_dict, "pending_rules_for": pending_rules_for,
    }
