from datetime import datetime, timedelta, timezone

from flask import jsonify, request, session

from .rbac import has_permission


PRIORITIES = {"Normale", "Alta", "Urgente", "Bloccante"}
STATUSES = {"Da fare", "In corso", "In verifica", "Completata", "Bloccata", "Annullata"}
CATEGORIES = {
    "Clienti", "Ricerca immobili", "Contatti", "Analisi tecnica",
    "Documenti", "Amministrazione", "Cantiere", "Altro",
}
LINK_TYPES = {"Generale", "Cliente", "Immobile", "Opportunità", "Trattativa"}


def utcnow():
    return datetime.now(timezone.utc)


def _aware(value):
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _parse_datetime(value):
    if value in {None, ""}:
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("Scadenza non valida.")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def init_work_tasks(app, app_module):
    if app.extensions.get("aplsai_work_tasks"):
        return

    db = app_module.db

    class WorkTask(db.Model):
        __tablename__ = "work_task"
        id = db.Column(db.Integer, primary_key=True)
        title = db.Column(db.String(220), nullable=False)
        description = db.Column(db.Text, nullable=False, default="")
        category = db.Column(db.String(60), nullable=False, default="Altro")
        priority = db.Column(db.String(30), nullable=False, default="Normale", index=True)
        status = db.Column(db.String(30), nullable=False, default="Da fare", index=True)
        assigned_to_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
        created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        due_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
        link_type = db.Column(db.String(40), nullable=False, default="Generale")
        link_id = db.Column(db.String(80), nullable=False, default="")
        completion_note = db.Column(db.Text, nullable=False, default="")
        blocked_reason = db.Column(db.Text, nullable=False, default="")
        approval_note = db.Column(db.Text, nullable=False, default="")
        completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
        approved_at = db.Column(db.DateTime(timezone=True), nullable=True)
        approved_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
        updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    class WorkTaskUpdate(db.Model):
        __tablename__ = "work_task_update"
        id = db.Column(db.Integer, primary_key=True)
        task_id = db.Column(db.Integer, db.ForeignKey("work_task.id"), nullable=False, index=True)
        author_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
        update_type = db.Column(db.String(40), nullable=False, default="Nota")
        message = db.Column(db.Text, nullable=False)
        created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    with app.app_context():
        db.create_all()

    def staff_user(permission="task_read"):
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

    def audit(actor, action, task_id, detail=""):
        fn = (app.extensions.get("aplsai_operations") or {}).get("audit")
        if fn:
            fn(actor, action, "work_task", task_id, detail)

    def user_name(user_id):
        user = db.session.get(app_module.User, user_id) if user_id else None
        return user.name if user else ""

    def is_assigned(task, actor):
        return actor.role == "staff" or task.assigned_to_user_id == actor.id

    def task_dict(task, include_updates=False):
        due = _aware(task.due_at)
        result = {
            "id": task.id, "title": task.title, "description": task.description,
            "category": task.category, "priority": task.priority, "status": task.status,
            "assigned_to_user_id": task.assigned_to_user_id,
            "assigned_to_name": user_name(task.assigned_to_user_id),
            "created_by_user_id": task.created_by_user_id,
            "created_by_name": user_name(task.created_by_user_id),
            "due_at": due.isoformat() if due else None,
            "overdue": bool(due and task.status not in {"Completata", "Annullata"} and due < utcnow()),
            "link_type": task.link_type, "link_id": task.link_id,
            "completion_note": task.completion_note, "blocked_reason": task.blocked_reason,
            "approval_note": task.approval_note,
            "completed_at": _aware(task.completed_at).isoformat() if task.completed_at else None,
            "approved_at": _aware(task.approved_at).isoformat() if task.approved_at else None,
            "approved_by_user_id": task.approved_by_user_id,
            "approved_by_name": user_name(task.approved_by_user_id),
            "created_at": _aware(task.created_at).isoformat() if task.created_at else None,
            "updated_at": _aware(task.updated_at).isoformat() if task.updated_at else None,
        }
        if include_updates:
            rows = WorkTaskUpdate.query.filter_by(task_id=task.id).order_by(WorkTaskUpdate.created_at.desc()).all()
            result["updates"] = [{
                "id": row.id, "author_user_id": row.author_user_id,
                "author_name": user_name(row.author_user_id), "type": row.update_type,
                "message": row.message,
                "created_at": _aware(row.created_at).isoformat() if row.created_at else None,
            } for row in rows]
        return result

    def validate_assignee(value):
        if value in {None, ""}:
            return None
        try:
            user_id = int(value)
        except (TypeError, ValueError):
            raise ValueError("Collaboratore non valido.")
        user = db.session.get(app_module.User, user_id)
        if not user or user.role != "operator" or getattr(user, "active", True) is False:
            raise ValueError("Il responsabile deve essere un collaboratore attivo.")
        return user_id

    def add_update(task, actor, update_type, message):
        text = app_module.clean_text(message, 4000)
        if text:
            db.session.add(WorkTaskUpdate(
                task_id=task.id, author_user_id=actor.id,
                update_type=update_type, message=text,
            ))

    @app.get("/api/staff/tasks")
    def list_tasks():
        actor, denied = staff_user("task_read")
        if denied:
            return denied
        query = WorkTask.query
        if actor.role == "operator":
            query = query.filter_by(assigned_to_user_id=actor.id)
        requested_status = request.args.get("status", "").strip()
        if requested_status and requested_status != "Tutte":
            if requested_status not in STATUSES:
                return jsonify(error="Stato non valido."), 400
            query = query.filter_by(status=requested_status)
        rows = query.order_by(WorkTask.due_at.asc(), WorkTask.id.desc()).all()
        data = [task_dict(row) for row in rows]
        priority_rank = {"Bloccante": 0, "Urgente": 1, "Alta": 2, "Normale": 3}
        data.sort(key=lambda row: (
            0 if row["overdue"] else 1,
            row["due_at"] or "9999-12-31T23:59:59+00:00",
            priority_rank.get(row["priority"], 9),
        ))
        active = [row for row in data if row["status"] not in {"Completata", "Annullata"}]
        now, soon = utcnow(), utcnow() + timedelta(hours=48)
        notifications = []
        for row in active:
            due = datetime.fromisoformat(row["due_at"]) if row["due_at"] else None
            if row["overdue"]:
                notifications.append({"level": "Urgente", "task_id": row["id"], "message": f"Scadenza superata: {row['title']}"})
            elif due and now <= due <= soon:
                notifications.append({"level": "Alta", "task_id": row["id"], "message": f"In scadenza entro 48 ore: {row['title']}"})
            elif actor.role == "staff" and not row["assigned_to_user_id"]:
                notifications.append({"level": "Alta", "task_id": row["id"], "message": f"Incarico senza responsabile: {row['title']}"})
            if actor.role == "staff" and row["status"] == "In verifica":
                notifications.append({"level": "Alta", "task_id": row["id"], "message": f"Attende verifica Admin: {row['title']}"})
        return jsonify(tasks=data, notifications=notifications, summary={
            "active": len(active),
            "overdue": sum(row["overdue"] for row in active),
            "pending_approval": sum(row["status"] == "In verifica" for row in active),
            "unassigned": sum(not row["assigned_to_user_id"] for row in active),
        })

    @app.get("/api/staff/tasks/<int:task_id>")
    def task_detail(task_id):
        actor, denied = staff_user("task_read")
        if denied:
            return denied
        task = db.session.get(WorkTask, task_id)
        if not task:
            return jsonify(error="Incarico non trovato."), 404
        if not is_assigned(task, actor):
            return jsonify(error="Incarico non assegnato a questo collaboratore."), 403
        return jsonify(task=task_dict(task, include_updates=True))

    @app.post("/api/admin/tasks")
    def create_task():
        actor, denied = staff_user("task_manage")
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        title = app_module.clean_text(data.get("title"), 220)
        description = app_module.clean_text(data.get("description"), 6000)
        category = app_module.clean_text(data.get("category"), 60) or "Altro"
        priority = app_module.clean_text(data.get("priority"), 30) or "Normale"
        link_type = app_module.clean_text(data.get("link_type"), 40) or "Generale"
        link_id = app_module.clean_text(data.get("link_id"), 80)
        if not title or not description:
            return jsonify(error="Titolo e istruzioni sono obbligatori."), 400
        if category not in CATEGORIES or priority not in PRIORITIES or link_type not in LINK_TYPES:
            return jsonify(error="Categoria, priorità o collegamento non validi."), 400
        try:
            assignee = validate_assignee(data.get("assigned_to_user_id"))
            due_at = _parse_datetime(data.get("due_at"))
        except (ValueError, TypeError) as exc:
            return jsonify(error=str(exc)), 400
        if not assignee or not due_at:
            return jsonify(error="Responsabile e scadenza sono obbligatori."), 400
        if due_at <= utcnow():
            return jsonify(error="La scadenza deve essere futura."), 400
        task = WorkTask(
            title=title, description=description, category=category, priority=priority,
            assigned_to_user_id=assignee, created_by_user_id=actor.id, due_at=due_at,
            link_type=link_type, link_id=link_id,
        )
        db.session.add(task)
        db.session.flush()
        add_update(task, actor, "Creazione", f"Incarico assegnato a {user_name(assignee)}.")
        audit(actor, "work_task_create", task.id, f"assigned_to={assignee}; due={due_at.isoformat()}")
        db.session.commit()
        return jsonify(task=task_dict(task, include_updates=True)), 201

    @app.patch("/api/staff/tasks/<int:task_id>")
    def update_task(task_id):
        actor, denied = staff_user("task_read")
        if denied:
            return denied
        task = db.session.get(WorkTask, task_id)
        if not task:
            return jsonify(error="Incarico non trovato."), 404
        if not is_assigned(task, actor):
            return jsonify(error="Incarico non assegnato a questo collaboratore."), 403
        data = request.get_json(silent=True) or {}
        previous_status = task.status
        if actor.role == "staff":
            if "title" in data:
                task.title = app_module.clean_text(data.get("title"), 220)
            if "description" in data:
                task.description = app_module.clean_text(data.get("description"), 6000)
            if "category" in data:
                task.category = app_module.clean_text(data.get("category"), 60)
            if "priority" in data:
                task.priority = app_module.clean_text(data.get("priority"), 30)
            if "link_type" in data:
                task.link_type = app_module.clean_text(data.get("link_type"), 40)
            if "link_id" in data:
                task.link_id = app_module.clean_text(data.get("link_id"), 80)
            try:
                if "assigned_to_user_id" in data:
                    task.assigned_to_user_id = validate_assignee(data.get("assigned_to_user_id"))
                if "due_at" in data:
                    task.due_at = _parse_datetime(data.get("due_at"))
            except (ValueError, TypeError) as exc:
                return jsonify(error=str(exc)), 400
        if "status" in data:
            status = app_module.clean_text(data.get("status"), 30)
            if status not in STATUSES or status == "Completata":
                return jsonify(error="Stato non valido o non autorizzato."), 400
            if task.status in {"Completata", "Annullata"} and actor.role != "staff":
                return jsonify(error="L’incarico è chiuso e può essere riaperto solo dall’Admin."), 409
            task.status = status
        if "completion_note" in data:
            task.completion_note = app_module.clean_text(data.get("completion_note"), 6000)
        if "blocked_reason" in data:
            task.blocked_reason = app_module.clean_text(data.get("blocked_reason"), 4000)
        if not task.title or not task.description or task.category not in CATEGORIES or task.priority not in PRIORITIES:
            return jsonify(error="Dati dell’incarico non validi."), 400
        if task.link_type not in LINK_TYPES:
            return jsonify(error="Collegamento non valido."), 400
        if task.status == "In verifica" and not task.completion_note:
            return jsonify(error="Descrivi il risultato prima di richiedere la verifica."), 400
        if task.status == "Bloccata" and not task.blocked_reason:
            return jsonify(error="Indica il motivo del blocco."), 400
        if task.status == "In verifica" and previous_status != "In verifica":
            task.completed_at = utcnow()
        task.updated_at = utcnow()
        note = app_module.clean_text(data.get("update_note"), 4000)
        add_update(task, actor, "Cambio stato" if task.status != previous_status else "Aggiornamento", note or f"Stato: {task.status}.")
        audit(actor, "work_task_update", task.id, f"status={task.status}; previous={previous_status}")
        db.session.commit()
        return jsonify(task=task_dict(task, include_updates=True))

    @app.post("/api/staff/tasks/<int:task_id>/comments")
    def add_comment(task_id):
        actor, denied = staff_user("task_read")
        if denied:
            return denied
        task = db.session.get(WorkTask, task_id)
        if not task:
            return jsonify(error="Incarico non trovato."), 404
        if not is_assigned(task, actor):
            return jsonify(error="Incarico non assegnato a questo collaboratore."), 403
        message = app_module.clean_text((request.get_json(silent=True) or {}).get("message"), 4000)
        if not message:
            return jsonify(error="Scrivi un aggiornamento."), 400
        add_update(task, actor, "Nota", message)
        task.updated_at = utcnow()
        audit(actor, "work_task_comment", task.id)
        db.session.commit()
        return jsonify(task=task_dict(task, include_updates=True)), 201

    @app.post("/api/admin/tasks/<int:task_id>/decision")
    def decide_task(task_id):
        actor, denied = staff_user("task_approve")
        if denied:
            return denied
        task = db.session.get(WorkTask, task_id)
        if not task:
            return jsonify(error="Incarico non trovato."), 404
        if task.status != "In verifica":
            return jsonify(error="L’incarico non è in attesa di verifica."), 409
        data = request.get_json(silent=True) or {}
        approved = data.get("approved")
        note = app_module.clean_text(data.get("note"), 4000)
        if not isinstance(approved, bool):
            return jsonify(error="Decisione non valida."), 400
        if not approved and not note:
            return jsonify(error="Indica cosa deve essere corretto."), 400
        task.approval_note = note
        if approved:
            task.status = "Completata"
            task.approved_at = utcnow()
            task.approved_by_user_id = actor.id
            action, message = "work_task_approve", note or "Risultato verificato e approvato."
        else:
            task.status = "In corso"
            task.approved_at = None
            task.approved_by_user_id = None
            action, message = "work_task_reject", f"Correzione richiesta: {note}"
        task.updated_at = utcnow()
        add_update(task, actor, "Decisione Admin", message)
        audit(actor, action, task.id, note)
        db.session.commit()
        return jsonify(task=task_dict(task, include_updates=True))

    app.extensions["aplsai_work_tasks"] = {
        "WorkTask": WorkTask, "WorkTaskUpdate": WorkTaskUpdate, "task_dict": task_dict,
    }
