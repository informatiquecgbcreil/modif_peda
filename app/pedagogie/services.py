from __future__ import annotations

from collections import defaultdict
from datetime import date
from app.models import Evaluation, Objectif, ObjectifCompetenceMap, Participant


def _latest_eval_map(competence_ids: set[int], start_date: date | None = None, end_date: date | None = None):
    if not competence_ids:
        return {}

    q = Evaluation.query.filter(Evaluation.competence_id.in_(competence_ids))
    if start_date:
        q = q.filter(Evaluation.date_evaluation >= start_date)
    if end_date:
        q = q.filter(Evaluation.date_evaluation <= end_date)

    rows = q.order_by(Evaluation.participant_id.asc(), Evaluation.competence_id.asc(), Evaluation.date_evaluation.asc(), Evaluation.id.asc()).all()
    latest = {}
    for e in rows:
        latest[(e.participant_id, e.competence_id)] = e
    return latest


def participant_timeline(participant_id: int):
    participant = Participant.query.get_or_404(participant_id)
    events = (
        Evaluation.query
        .filter(Evaluation.participant_id == participant_id)
        .order_by(Evaluation.date_evaluation.asc(), Evaluation.id.asc())
        .all()
    )

    current_levels: dict[int, int] = {}
    for e in events:
        current_levels[e.competence_id] = e.etat

    return participant, events, current_levels


def compute_objectif_scores(projet_id: int | None = None, start_date: date | None = None, end_date: date | None = None):
    objectifs_q = Objectif.query
    if projet_id:
        objectifs_q = objectifs_q.filter(Objectif.projet_id == projet_id)
    objectifs = objectifs_q.order_by(Objectif.created_at.asc()).all()

    objectif_by_id = {o.id: o for o in objectifs}
    children = defaultdict(list)
    for obj in objectifs:
        if obj.parent_id:
            children[obj.parent_id].append(obj.id)

    maps = ObjectifCompetenceMap.query.filter(
        ObjectifCompetenceMap.objectif_id.in_(objectif_by_id.keys()),
        ObjectifCompetenceMap.actif.is_(True),
    ).all() if objectif_by_id else []

    comp_ids = {m.competence_id for m in maps}
    latest_map = _latest_eval_map(comp_ids, start_date=start_date, end_date=end_date)

    part_by_obj = defaultdict(set)
    eval_count_by_obj = defaultdict(int)
    score_by_obj = {}

    grouped = defaultdict(list)
    for m in maps:
        grouped[m.objectif_id].append(m)

    for obj_id, items in grouped.items():
        numerator = 0.0
        denom = 0.0
        for m in items:
            w = float(m.poids or 1.0)
            denom += w
            comp_values = [
                ev.etat for (pid, cid), ev in latest_map.items()
                if cid == m.competence_id
            ]
            if comp_values:
                numerator += (sum(comp_values) / len(comp_values)) * w
                for (pid, cid), _ in latest_map.items():
                    if cid == m.competence_id:
                        part_by_obj[obj_id].add(pid)
                eval_count_by_obj[obj_id] += len(comp_values)
        score_by_obj[obj_id] = round((numerator / (denom * 3.0) * 100.0), 1) if denom > 0 else None

    def rollup(obj_id: int):
        if score_by_obj.get(obj_id) is not None:
            return score_by_obj[obj_id]
        child_scores = [rollup(cid) for cid in children.get(obj_id, [])]
        child_scores = [s for s in child_scores if s is not None]
        if not child_scores:
            return None
        return round(sum(child_scores) / len(child_scores), 1)

    data = []
    for obj in objectifs:
        s = rollup(obj.id)
        data.append({
            "objectif": obj,
            "score": s,
            "participants": len(part_by_obj.get(obj.id, set())),
            "evaluations": eval_count_by_obj.get(obj.id, 0),
        })
    return data
