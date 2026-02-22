import datetime
import csv
from io import StringIO

from flask import render_template, request, redirect, url_for, flash, Response
from flask_login import login_required, current_user

from app.extensions import db
from app.rbac import require_perm
from app.models import (
    Referentiel,
    Competence,
    Objectif,
    Projet,
    AtelierActivite,
    SessionActivite,
    Evaluation,
    PresenceActivite,
    ObjectifSuivi,
    ProjetAtelier,
    ObjectifCompetenceMap,
    PedagogieModule,
)
from .services import compute_objectif_scores, participant_timeline

from . import bp


@bp.route("/referentiels", methods=["GET", "POST"])
@login_required
@require_perm("pedagogie:view")
def referentiels_list():
    if request.method == "POST":
        action = request.form.get("action") or ""
        if action == "create_referentiel":
            nom = (request.form.get("nom") or "").strip()
            description = (request.form.get("description") or "").strip() or None
            if not nom:
                flash("Nom du référentiel obligatoire.", "danger")
                return redirect(url_for("pedagogie.referentiels_list"))
            ref = Referentiel(nom=nom, description=description)
            db.session.add(ref)
            db.session.commit()
            flash("Référentiel créé.", "success")
            return redirect(url_for("pedagogie.referentiels_list"))

        if action == "delete_referentiel":
            ref_id = int(request.form.get("referentiel_id") or 0)
            ref = Referentiel.query.get_or_404(ref_id)
            db.session.delete(ref)
            db.session.commit()
            flash("Référentiel supprimé.", "warning")
            return redirect(url_for("pedagogie.referentiels_list"))

    referentiels = Referentiel.query.order_by(Referentiel.nom.asc()).all()
    return render_template("pedagogie/referentiels.html", referentiels=referentiels)


@bp.route("/referentiels/<int:referentiel_id>", methods=["GET", "POST"])
@login_required
def referentiels_edit(referentiel_id: int):
    referentiel = Referentiel.query.get_or_404(referentiel_id)

    if request.method == "POST":
        action = request.form.get("action") or ""

        if action == "update_referentiel":
            referentiel.nom = (request.form.get("nom") or "").strip()
            referentiel.description = (request.form.get("description") or "").strip() or None
            if not referentiel.nom:
                flash("Nom obligatoire.", "danger")
                return redirect(url_for("pedagogie.referentiels_edit", referentiel_id=referentiel.id))
            db.session.commit()
            flash("Référentiel mis à jour.", "success")
            return redirect(url_for("pedagogie.referentiels_edit", referentiel_id=referentiel.id))

        if action == "add_competence":
            code = (request.form.get("code") or "").strip()
            nom = (request.form.get("nom") or "").strip()
            description = (request.form.get("description") or "").strip() or None
            if not code or not nom:
                flash("Code et nom de compétence obligatoires.", "danger")
                return redirect(url_for("pedagogie.referentiels_edit", referentiel_id=referentiel.id))
            comp = Competence(
                referentiel_id=referentiel.id,
                code=code,
                nom=nom,
                description=description,
            )
            db.session.add(comp)
            db.session.commit()
            flash("Compétence ajoutée.", "success")
            return redirect(url_for("pedagogie.referentiels_edit", referentiel_id=referentiel.id))

        if action == "delete_competence":
            comp_id = int(request.form.get("competence_id") or 0)
            comp = Competence.query.get_or_404(comp_id)
            if comp.referentiel_id != referentiel.id:
                flash("Compétence invalide.", "danger")
                return redirect(url_for("pedagogie.referentiels_edit", referentiel_id=referentiel.id))
            db.session.delete(comp)
            db.session.commit()
            flash("Compétence supprimée.", "warning")
            return redirect(url_for("pedagogie.referentiels_edit", referentiel_id=referentiel.id))

    competences = Competence.query.filter_by(referentiel_id=referentiel.id).order_by(Competence.code.asc()).all()
    return render_template(
        "pedagogie/referentiel_edit.html",
        referentiel=referentiel,
        competences=competences,
    )


@bp.route("/modules", methods=["GET", "POST"])
@login_required
@require_perm("pedagogie:view")
def modules_pedagogiques():
    if request.method == "POST":
        action = request.form.get("action") or ""
        if action == "create_module":
            nom = (request.form.get("nom") or "").strip()
            description = (request.form.get("description") or "").strip() or None
            competence_ids = [int(cid) for cid in request.form.getlist("competence_ids") if cid.isdigit()]
            if not nom:
                flash("Nom du module obligatoire.", "danger")
                return redirect(url_for("pedagogie.modules_pedagogiques"))
            mod = PedagogieModule(nom=nom, description=description)
            if competence_ids:
                mod.competences = Competence.query.filter(Competence.id.in_(competence_ids)).all()
            db.session.add(mod)
            db.session.commit()
            flash("Module pédagogique créé.", "success")
            return redirect(url_for("pedagogie.modules_pedagogiques"))

    referentiels = Referentiel.query.order_by(Referentiel.nom.asc()).all()
    modules = PedagogieModule.query.order_by(PedagogieModule.nom.asc()).all()
    return render_template("pedagogie/modules.html", referentiels=referentiels, modules=modules)


@bp.route("/objectifs", methods=["GET", "POST"])
@login_required
@require_perm("pedagogie:view")
def objectifs():
    projet_id = request.args.get("projet_id", type=int)
    atelier_id = request.args.get("atelier_id", type=int)
    session_id = request.args.get("session_id", type=int)

    if request.method == "POST":
        action = request.form.get("action") or ""
        if action == "create_objectif":
            obj_type = (request.form.get("type") or "").strip()
            titre = (request.form.get("titre") or "").strip()
            description = (request.form.get("description") or "").strip() or None
            seuil_validation = request.form.get("seuil_validation", type=float) or 0.0
            parent_id = request.form.get("parent_id", type=int)
            selected_session_id = request.form.get("session_id", type=int)
            selected_atelier_id = request.form.get("atelier_id", type=int)
            selected_projet_id = request.form.get("projet_id", type=int)

            if not obj_type or not titre:
                flash("Type et titre obligatoires.", "danger")
                return redirect(url_for("pedagogie.objectifs", projet_id=projet_id, atelier_id=atelier_id, session_id=session_id))

            obj = Objectif(
                type=obj_type,
                titre=titre,
                description=description,
                seuil_validation=seuil_validation,
                parent_id=parent_id,
                projet_id=selected_projet_id,
                atelier_id=selected_atelier_id,
                session_id=selected_session_id,
            )
            competence_ids = [int(cid) for cid in request.form.getlist("competence_ids") if cid.isdigit()]
            if competence_ids:
                comps = Competence.query.filter(Competence.id.in_(competence_ids)).all()
                obj.competences = comps
            db.session.add(obj)
            db.session.commit()
            if obj.type == "operationnel" and competence_ids:
                for cid in competence_ids:
                    existing = ObjectifCompetenceMap.query.filter_by(objectif_id=obj.id, competence_id=cid).first()
                    if not existing:
                        db.session.add(ObjectifCompetenceMap(objectif_id=obj.id, competence_id=cid, poids=1.0, actif=True))
                db.session.commit()
            flash("Objectif ajouté.", "success")
            return redirect(url_for("pedagogie.objectifs", projet_id=selected_projet_id, atelier_id=selected_atelier_id, session_id=selected_session_id))

        if action == "delete_objectif":
            obj_id = int(request.form.get("objectif_id") or 0)
            obj = Objectif.query.get_or_404(obj_id)
            db.session.delete(obj)
            db.session.commit()
            flash("Objectif supprimé.", "warning")
            return redirect(url_for("pedagogie.objectifs", projet_id=projet_id, atelier_id=atelier_id, session_id=session_id))

    projets = Projet.query.order_by(Projet.secteur.asc(), Projet.nom.asc()).all()
    ateliers = AtelierActivite.query.filter(AtelierActivite.is_deleted.is_(False)).order_by(AtelierActivite.nom.asc()).all()
    sessions = SessionActivite.query.filter(SessionActivite.is_deleted.is_(False)).order_by(SessionActivite.created_at.desc()).all()
    referentiels = Referentiel.query.order_by(Referentiel.nom.asc()).all()

    objectifs = Objectif.query
    if projet_id:
        objectifs = objectifs.filter(Objectif.projet_id == projet_id)
    if atelier_id:
        objectifs = objectifs.filter(Objectif.atelier_id == atelier_id)
    if session_id:
        objectifs = objectifs.filter(Objectif.session_id == session_id)
    objectifs = objectifs.order_by(Objectif.created_at.asc()).all()

    parent_options = Objectif.query.order_by(Objectif.created_at.asc()).all()

    return render_template(
        "pedagogie/objectifs.html",
        projets=projets,
        ateliers=ateliers,
        sessions=sessions,
        referentiels=referentiels,
        objectifs=objectifs,
        parent_options=parent_options,
        projet_id=projet_id,
        atelier_id=atelier_id,
        session_id=session_id,
    )
    
 
@bp.route("/suivi")
@login_required
@require_perm("pedagogie:view")
def suivi_pedagogique():
    # On récupère tout pour les filtres
    projets = Projet.query.order_by(Projet.nom.asc()).all()
    ateliers = AtelierActivite.query.filter_by(is_deleted=False).order_by(AtelierActivite.nom.asc()).all()
    
    # Récupération des paramètres de filtre
    projet_id = request.args.get("projet_id", type=int)
    atelier_id = request.args.get("atelier_id", type=int)
    
    # Stats globales simples
    total_competences = Competence.query.count()
    total_evaluations = Evaluation.query.count()
    
    # Si on veut filtrer les évaluations par projet/atelier, ça demande des jointures plus complexes
    # Pour l'instant, on affiche la page de base pour vérifier que ça marche
    
    return render_template(
        "stats_pedagogie.html", # Assure-toi que ce fichier existe bien dans templates/
        projets=projets,
        ateliers=ateliers,
        selected_projet=projet_id,
        selected_atelier=atelier_id,
        total_competences=total_competences,
        total_evaluations=total_evaluations
    )


@bp.route("/kiosk", methods=["GET", "POST"])
@login_required
@require_perm("pedagogie:view")
def kiosk_pedagogique():
    session_id = request.args.get("session_id", type=int)
    participant_id = request.args.get("participant_id", type=int)

    sessions = (
        SessionActivite.query.filter(SessionActivite.is_deleted.is_(False))
        .order_by(SessionActivite.created_at.desc())
        .limit(200)
        .all()
    )
    session = SessionActivite.query.get(session_id) if session_id else None

    participants = []
    if session:
        participants = (
            db.session.query(PresenceActivite)
            .filter(PresenceActivite.session_id == session.id)
            .join(PresenceActivite.participant)
            .order_by(PresenceActivite.created_at.asc())
            .all()
        )

    objectifs = []
    if session:
        projet_ids = [
            pid for (pid,) in db.session.query(ProjetAtelier.projet_id).filter(ProjetAtelier.atelier_id == session.atelier_id).all()
        ]

        objectifs_generaux = []
        if projet_ids:
            objectifs_generaux = (
                Objectif.query.filter(Objectif.type == "general", Objectif.projet_id.in_(projet_ids))
                .order_by(Objectif.created_at.asc())
                .all()
            )
        objectifs_specifiques = (
            Objectif.query.filter(Objectif.type == "specifique", Objectif.atelier_id == session.atelier_id)
            .order_by(Objectif.created_at.asc())
            .all()
        )
        objectifs_operationnels = (
            Objectif.query.filter(Objectif.type == "operationnel", Objectif.session_id == session.id)
            .order_by(Objectif.created_at.asc())
            .all()
        )
        objectifs = [*objectifs_generaux, *objectifs_specifiques, *objectifs_operationnels]

    if request.method == "POST" and session:
        mode = (request.form.get("mode") or "ressenti").strip()
        mode = mode if mode in {"ressenti", "competence", "mixte"} else "ressenti"

        participant_id_post = request.form.get("participant_id", type=int)
        objectif_ids = [int(x) for x in request.form.getlist("objectif_ids") if x.isdigit()]
        today = datetime.date.today()

        saved = 0
        for oid in objectif_ids:
            etat = request.form.get(f"etat_{oid}", type=int)
            ressenti = request.form.get(f"ressenti_{oid}", type=int)
            commentaire = (request.form.get(f"commentaire_{oid}") or "").strip() or None

            if etat is None and ressenti is None and commentaire is None:
                continue

            item = ObjectifSuivi.query.filter_by(
                objectif_id=oid,
                session_id=session.id,
                participant_id=participant_id_post,
                date_saisie=today,
            ).first()
            if not item:
                item = ObjectifSuivi(
                    objectif_id=oid,
                    session_id=session.id,
                    participant_id=participant_id_post,
                    date_saisie=today,
                    user_id=current_user.id,
                )
                db.session.add(item)

            item.mode = mode
            item.etat = etat if etat is not None else item.etat
            item.ressenti = ressenti if ressenti in (1, 2, 3, 4, 5) else None
            item.commentaire = commentaire
            item.user_id = current_user.id
            saved += 1

        db.session.commit()
        flash(f"{saved} suivi(s) objectif enregistré(s).", "success")
        return redirect(url_for("pedagogie.kiosk_pedagogique", session_id=session.id, participant_id=participant_id_post))

    recent_rows = []
    if session:
        q = ObjectifSuivi.query.filter(ObjectifSuivi.session_id == session.id)
        if participant_id:
            q = q.filter(ObjectifSuivi.participant_id == participant_id)
        recent_rows = q.order_by(ObjectifSuivi.updated_at.desc()).limit(40).all()

    return render_template(
        "pedagogie/kiosk.html",
        sessions=sessions,
        selected_session=session,
        participants=participants,
        selected_participant_id=participant_id,
        objectifs=objectifs,
        recent_rows=recent_rows,
    )


@bp.route("/participant/<int:participant_id>/passeport")
@login_required
@require_perm("pedagogie:view")
def participant_passeport(participant_id: int):
    participant, events, current_levels = participant_timeline(participant_id)
    return render_template(
        "pedagogie/participant_passeport.html",
        participant=participant,
        events=events,
        current_levels=current_levels,
    )


@bp.route("/pilotage")
@login_required
@require_perm("pedagogie:view")
def pilotage_objectifs():
    projet_id = request.args.get("projet_id", type=int)
    start_date = request.args.get("start_date") or None
    end_date = request.args.get("end_date") or None
    start = datetime.datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
    end = datetime.datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None

    rows = compute_objectif_scores(projet_id=projet_id, start_date=start, end_date=end)
    projets = Projet.query.order_by(Projet.nom.asc()).all()
    return render_template("pedagogie/pilotage.html", rows=rows, projets=projets, projet_id=projet_id, start_date=start_date, end_date=end_date)


@bp.route("/export_ra.csv")
@login_required
@require_perm("pedagogie:view")
def export_ra_csv():
    projet_id = request.args.get("projet_id", type=int)
    start_date = request.args.get("start_date") or None
    end_date = request.args.get("end_date") or None
    start = datetime.datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
    end = datetime.datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None
    rows = compute_objectif_scores(projet_id=projet_id, start_date=start, end_date=end)

    sio = StringIO()
    w = csv.writer(sio)
    w.writerow(["Projet", "Type objectif", "Objectif", "Score atteinte %", "Nb évaluations", "Nb participants"])
    for r in rows:
        obj = r["objectif"]
        w.writerow([
            obj.projet.nom if obj.projet else "",
            obj.type,
            obj.titre,
            "" if r["score"] is None else r["score"],
            r["evaluations"],
            r["participants"],
        ])
    return Response(
        sio.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=rapport_activite_pedagogie.csv"},
    )
