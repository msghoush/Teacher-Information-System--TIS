from collections import defaultdict
from datetime import date, datetime, timezone
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

import auth
import models
from auth import get_current_user
from dependencies import get_db
from ui_shell import build_shell_context


router = APIRouter(prefix="/observations", tags=["Observations"])
templates = Jinja2Templates(directory="templates")

FORMAL_OBSERVATION_TARGET = 6
RATING_VALUES = {"0", "1", "2", "3", "4", "5"}

OBSERVATION_CRITERIA = [
    ("A", "Planning and Preparation", 1, "Develops a focused and logically staged lesson with clearly stated and appropriate lesson objectives", "Objectives are clear, measurable, logically sequenced, relevant to curriculum, differentiated, feasible, and supported by prepared resources.", "Objectives are visible and explained; activities flow from review to practice; examples connect to real life; materials support different learners."),
    ("A", "Planning and Preparation", 2, "Lesson is aligned with the weekly plan", "Lesson aligns with the weekly plan, curriculum scope, prior/future learning, pacing, adaptation, and assessment checks.", "Teacher connects to previous and future lessons; pacing follows the plan; exit slips or similar checks confirm learning."),
    ("B", "Culture/Climate Dimension", 1, "Fosters an environment that embraces all learners", "The classroom demonstrates inclusivity, belonging, respect for diversity, and support for all learners.", "Teacher uses students' names, values contributions, displays inclusive materials, and structures participation for all learners."),
    ("B", "Culture/Climate Dimension", 2, "Treats each learner equitably", "Interactions, participation, praise, expectations, rewards, and discipline are fair, consistent, and bias-free.", "Teacher rotates participation, distributes praise fairly, and applies rules consistently."),
    ("B", "Culture/Climate Dimension", 3, "Encourages learners to share their opinions without fear of negative comments from their peers", "The teacher establishes safe dialogue norms, encourages academic risk-taking, and addresses ridicule immediately.", "Students share ideas openly, mistakes are treated as learning opportunities, and debate norms protect all voices."),
    ("B", "Culture/Climate Dimension", 4, "Creates enthusiasm for the learning at hand", "Teacher energy, engagement strategies, curiosity, and celebration of progress create enthusiasm for learning.", "Teacher opens with a hook, uses expressive delivery, praises effort, and displays student work."),
    ("C", "Learning Dimension", 1, "Communicates clear explanations about the activities or tasks", "Instructions are clear, step-by-step, connected to objectives, proactive about confusion, and checked for understanding.", "Teacher states task steps, uses board/visual supports, rephrases when needed, and asks students to restate instructions."),
    ("C", "Learning Dimension", 2, "Implements lessons and/or activities that stimulate learners to use higher order thinking skills", "Tasks require analysis, evaluation, creation, open-ended thinking, justification, discussion, debate, or problem-solving.", "Students compare methods, justify reasoning, design experiments, or respond to open-ended questions."),
    ("C", "Learning Dimension", 3, "Delivers lessons that are relatable to the learners or aligned to their interests", "Instruction connects content to learners' experiences, interests, culture, age, environment, and real-life application.", "Examples reflect students' lives, hobbies, current issues, or authentic applications."),
    ("C", "Learning Dimension", 4, "Monitors learners' understanding of the content and/or the acquisition of skills", "Teacher uses questioning, observation, formative assessment, self/peer assessment, and correction of misconceptions.", "Teacher circulates, checks work, uses exit slips or whiteboards, and reteaches when repeated errors appear."),
    ("C", "Learning Dimension", 5, "Adapts instruction and/or activities to meet individual learner's needs", "Instruction adjusts tasks, groups, modalities, entry points, choices, and support based on learner needs.", "Learners receive differentiated texts, visuals, grouping, assignment choices, or extension tasks."),
    ("C", "Learning Dimension", 6, "Provides learners with purposeful feedback about their progress and/or needs", "Feedback is timely, specific, constructive, balanced, actionable, and encourages reflection.", "Teacher gives specific oral/written feedback and students act on it through revision or reflection."),
    ("D", "Essentials Dimension", 1, "Delivers and/or facilitates the lesson with knowledge and confidence", "Teacher demonstrates subject command, accurate explanations, confident delivery, and anticipation of misconceptions.", "Teacher explains accurately, connects concepts, answers questions, and maintains student attention."),
    ("D", "Essentials Dimension", 2, "Communicates and upholds high expectations for learners' behaviors to maximize their learning and well-being", "Behavior expectations are clear, consistent, fair, reinforced positively, and connected to learning and well-being.", "Students know routines and expectations; teacher redirects calmly and reinforces positive behavior."),
    ("D", "Essentials Dimension", 3, "Facilitates use of resources that support learners' needs", "Resources align with objectives and learner needs, are inclusive, age-appropriate, safe, and purposeful.", "Teacher uses visuals, manipulatives, technology, or lab resources with clear guidance."),
    ("D", "Essentials Dimension", 4, "Implements instructional strategies that actively engage learners", "Instruction uses student-centered strategies, collaboration, varied methods, and active thinking beyond passive listening.", "Students work in pairs, use whiteboards, debate, role play, or solve problems collaboratively."),
    ("D", "Essentials Dimension", 5, "Manages the learning time in an efficient and optimal manner", "Lesson time is used effectively through prompt starts, smooth transitions, focus, balanced pacing, and flexible adjustments.", "Teacher uses timers, keeps transitions short, minimizes wasted time, and has extension tasks ready."),
    ("E", "Agency Dimension", 1, "Empowers learners to be responsible for the learning at hand", "Learners take ownership through independence, inquiry, reflection, accountability, and self-directed learning strategies.", "Students set goals, collect/submit work responsibly, use journals, or solve while the teacher guides."),
    ("E", "Agency Dimension", 2, "Gives learners choices about the learning activities or tasks", "Learners receive meaningful options in assignments, projects, methods, or ways to demonstrate understanding.", "Students choose formats, texts, partners, or task pathways while still meeting objectives."),
    ("E", "Agency Dimension", 3, "Provides assistance for learners to navigate and monitor their learning progress", "Teacher supports goal setting, progress tracking, reflection, identification of strengths, and overcoming challenges.", "Students use checklists, trackers, conferences, journals, or progress charts."),
    ("E", "Agency Dimension", 4, "Encourages learners to persevere with or seek challenging activities or tasks", "Teacher promotes resilience, effort, productive struggle, scaffolding, challenge, and mistakes as learning.", "Students attempt difficult tasks, try again after errors, and reflect on how they overcame difficulty."),
    ("E", "Agency Dimension", 5, "Builds learners' growth mindset and self-efficacy", "Teacher encourages positive self-talk, effort, learning from mistakes, long-term goals, and belief in improvement.", "Teacher highlights persistence; students use growth language and set improvement goals."),
    ("F", "Relationship Dimension", 1, "Promotes respectful and caring interactions toward and between learners", "Teacher models and reinforces respect, care, empathy, safety, support, and positive interactions.", "Interactions are warm and respectful; students feel safe; negative peer interactions are addressed."),
    ("F", "Relationship Dimension", 2, "Cultivates learner cooperation, collaboration, and inclusivity", "Teacher promotes structured cooperation, collaborative learning, inclusivity, participation, and appreciation of strengths.", "Group work includes roles, peer support, and inclusive participation."),
    ("F", "Relationship Dimension", 3, "Preserves learners' dignity while attending to their individual needs", "Individual needs are addressed respectfully, discreetly, empathetically, and without stigma.", "Corrections are private, support is discreet, and learners are not embarrassed or singled out."),
]


def _get_scope_ids(current_user):
    return (
        getattr(current_user, "scope_branch_id", current_user.branch_id),
        getattr(current_user, "scope_academic_year_id", current_user.academic_year_id),
    )


def _teacher_name(teacher) -> str:
    if not teacher:
        return "Unknown Teacher"
    parts = [teacher.first_name, teacher.middle_name, teacher.last_name]
    return " ".join(part for part in parts if part).strip() or f"Teacher #{teacher.id}"


def _teacher_choice_rows(teachers):
    return [
        {
            "id": teacher.id,
            "teacher_id": teacher.teacher_id or "",
            "name": _teacher_name(teacher),
        }
        for teacher in teachers
    ]


def _is_teacher_user(current_user) -> bool:
    return auth.normalize_role(getattr(current_user, "role", "")) == auth.ROLE_USER


def _get_current_teacher(db: Session, current_user):
    user_id = str(getattr(current_user, "user_id", "") or "").strip()
    if not user_id:
        return None
    branch_id, academic_year_id = _get_scope_ids(current_user)
    return db.query(models.Teacher).filter(
        models.Teacher.teacher_id == user_id,
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id,
    ).first()


def _can_create_observation(current_user) -> bool:
    return auth.can_modify_data(current_user) and not _is_teacher_user(current_user)


def ensure_observation_seed_data(db: Session):
    existing_count = db.query(models.ObservationCriterion).count()
    if existing_count:
        return
    for index, item in enumerate(OBSERVATION_CRITERIA, start=1):
        domain_key, domain_title, indicator_number, title, guidelines, evidence = item
        db.add(
            models.ObservationCriterion(
                domain_key=domain_key,
                domain_title=domain_title,
                indicator_number=indicator_number,
                title=title,
                guidelines=guidelines,
                evidence_examples=evidence,
                sort_order=index,
            )
        )
    db.commit()


def _criteria_by_domain(criteria):
    grouped = []
    current = None
    for criterion in criteria:
        key = criterion.domain_key
        if not current or current["domain_key"] != key:
            current = {
                "domain_key": key,
                "domain_title": criterion.domain_title,
                "criteria": [],
            }
            grouped.append(current)
        current["criteria"].append(criterion)
    return grouped


def _compute_scores(score_rows, criteria_by_id):
    numeric_scores = []
    domain_values = defaultdict(list)
    low_items = []
    high_items = []
    for score in score_rows:
        rating = str(score.rating or "NA").strip().upper()
        if rating == "NA" or rating not in RATING_VALUES:
            continue
        value = int(rating)
        criterion = criteria_by_id.get(score.criterion_id)
        if not criterion:
            continue
        numeric_scores.append(value)
        domain_values[criterion.domain_key].append(value)
        item = {
            "criterion": criterion,
            "rating": value,
            "evidence": str(score.evidence or "").strip(),
        }
        if value <= 2:
            low_items.append(item)
        if value >= 4:
            high_items.append(item)

    overall = round(sum(numeric_scores) / len(numeric_scores), 2) if numeric_scores else None
    domains = []
    for domain_key in sorted(domain_values.keys()):
        values = domain_values[domain_key]
        domain_title = next(
            (
                criterion.domain_title
                for criterion in criteria_by_id.values()
                if criterion.domain_key == domain_key
            ),
            domain_key,
        )
        domains.append(
            {
                "domain_key": domain_key,
                "domain_title": domain_title,
                "average": round(sum(values) / len(values), 2),
                "count": len(values),
            }
        )
    return overall, domains, low_items, high_items


def _build_smart_feedback(score_rows, criteria_by_id):
    overall, domains, low_items, high_items = _compute_scores(score_rows, criteria_by_id)
    strongest = sorted(domains, key=lambda item: item["average"], reverse=True)[:2]
    growth = sorted(domains, key=lambda item: item["average"])[:2]
    strengths = [
        f"{item['criterion'].title} was rated {item['rating']}/5."
        for item in sorted(high_items, key=lambda item: item["rating"], reverse=True)[:3]
    ]
    improvements = [
        f"{item['criterion'].title} needs focused support; current rating is {item['rating']}/5."
        for item in sorted(low_items, key=lambda item: item["rating"])[:3]
    ]
    if not strengths:
        strengths = ["No high-scoring criteria were identified yet; continue collecting specific classroom evidence."]
    if not improvements:
        improvements = ["No critical low-scoring criteria were identified in this observation."]

    return {
        "overall": overall,
        "domain_summary": domains,
        "headline": _feedback_headline(overall),
        "strongest_domains": strongest,
        "growth_domains": growth,
        "strengths": strengths,
        "improvements": improvements,
        "next_steps": _next_steps(overall, growth),
    }


def _feedback_headline(overall):
    if overall is None:
        return "Observation completed without scored criteria."
    if overall >= 4.5:
        return "Outstanding practice is evident across the observed lesson."
    if overall >= 3.5:
        return "Strong practice is evident, with clear areas to keep refining."
    if overall >= 2.5:
        return "Developing practice is visible, and targeted coaching will help the teacher move forward."
    return "This observation shows urgent areas for structured support and follow-up."


def _next_steps(overall, growth_domains):
    if overall is None:
        return ["Add ratings and evidence so the system can generate clearer feedback."]
    steps = []
    if growth_domains:
        labels = ", ".join(item["domain_title"] for item in growth_domains)
        steps.append(f"Prioritize coaching around {labels}.")
    if overall < 3:
        steps.append("Schedule a follow-up observation and agree on one immediate classroom action.")
    else:
        steps.append("Preserve the strongest practices and choose one measurable refinement target for the next lesson.")
    return steps


def _teacher_observation_access_filter(query, db, current_user):
    if not _is_teacher_user(current_user):
        return query
    teacher = _get_current_teacher(db, current_user)
    if not teacher:
        return query.filter(models.Observation.id == -1)
    return query.filter(models.Observation.teacher_id == teacher.id)


@router.get("/")
def observations_page(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    ensure_observation_seed_data(db)
    branch_id, academic_year_id = _get_scope_ids(current_user)
    teachers_query = db.query(models.Teacher).filter(
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id,
    )
    if _is_teacher_user(current_user):
        current_teacher = _get_current_teacher(db, current_user)
        teachers_query = teachers_query.filter(
            models.Teacher.id == (current_teacher.id if current_teacher else -1)
        )
    teachers = teachers_query.order_by(models.Teacher.first_name.asc(), models.Teacher.last_name.asc()).all()

    observation_rows = _teacher_observation_access_filter(
        db.query(models.Observation).filter(
            models.Observation.branch_id == branch_id,
            models.Observation.academic_year_id == academic_year_id,
        ),
        db,
        current_user,
    ).all()
    observations_by_teacher = defaultdict(list)
    for observation in observation_rows:
        observations_by_teacher[observation.teacher_id].append(observation)

    rows = []
    for teacher in teachers:
        teacher_observations = observations_by_teacher.get(teacher.id, [])
        formal_count = sum(1 for item in teacher_observations if item.observation_type == "Formal")
        informal_count = sum(1 for item in teacher_observations if item.observation_type == "Informal")
        scored = [
            float(item.overall_score)
            for item in teacher_observations
            if str(item.overall_score or "").replace(".", "", 1).isdigit()
        ]
        latest = sorted(teacher_observations, key=lambda item: item.observation_date or "", reverse=True)
        rows.append(
            {
                "teacher": teacher,
                "teacher_name": _teacher_name(teacher),
                "formal_count": formal_count,
                "informal_count": informal_count,
                "remaining_formal": max(FORMAL_OBSERVATION_TARGET - formal_count, 0),
                "progress_pct": min(round((formal_count / FORMAL_OBSERVATION_TARGET) * 100), 100),
                "average_score": round(sum(scored) / len(scored), 2) if scored else None,
                "latest": latest[0] if latest else None,
            }
        )

    total_formal = sum(row["formal_count"] for row in rows)
    total_required = len(rows) * FORMAL_OBSERVATION_TARGET
    return templates.TemplateResponse(
        "observations.html",
        {
            "request": request,
            "shell": build_shell_context(
                request,
                db,
                current_user,
                page_key="observations",
                notice=request.query_params.get("notice", ""),
            ),
            "rows": rows,
            "can_create": _can_create_observation(current_user),
            "target": FORMAL_OBSERVATION_TARGET,
            "summary": {
                "teachers": len(rows),
                "total_formal": total_formal,
                "total_required": total_required,
                "completion_pct": round((total_formal / total_required) * 100) if total_required else 0,
            },
        },
    )


@router.get("/new")
def new_observation_page(request: Request, teacher_id: int | None = None, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")
    if not _can_create_observation(current_user):
        return RedirectResponse(url="/observations")

    ensure_observation_seed_data(db)
    branch_id, academic_year_id = _get_scope_ids(current_user)
    teachers = db.query(models.Teacher).filter(
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id,
    ).order_by(models.Teacher.first_name.asc(), models.Teacher.last_name.asc()).all()
    criteria = db.query(models.ObservationCriterion).filter(
        models.ObservationCriterion.is_active == True
    ).order_by(models.ObservationCriterion.sort_order.asc()).all()

    return templates.TemplateResponse(
        "observation_form.html",
        {
            "request": request,
            "shell": build_shell_context(
                request,
                db,
                current_user,
                page_key="observations",
                notice=request.query_params.get("notice", ""),
            ),
            "teachers": _teacher_choice_rows(teachers),
            "criteria_groups": _criteria_by_domain(criteria),
            "today": date.today().isoformat(),
            "selected_teacher_id": teacher_id,
        },
    )


@router.post("/")
async def create_observation(request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")
    if not _can_create_observation(current_user):
        return RedirectResponse(url="/observations")

    ensure_observation_seed_data(db)
    form = await request.form()
    branch_id, academic_year_id = _get_scope_ids(current_user)
    teacher_pk = _parse_int(form.get("teacher_id"))
    teacher = db.query(models.Teacher).filter(
        models.Teacher.id == teacher_pk,
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id,
    ).first()
    if not teacher:
        return RedirectResponse(url="/observations/new?notice=Select+a+valid+teacher.", status_code=302)

    observation_type = str(form.get("observation_type") or "Formal").strip().title()
    if observation_type not in {"Formal", "Informal"}:
        observation_type = "Formal"
    observation = models.Observation(
        branch_id=branch_id,
        academic_year_id=academic_year_id,
        teacher_id=teacher.id,
        evaluator_user_id=current_user.user_id,
        observation_type=observation_type,
        observation_date=str(form.get("observation_date") or date.today().isoformat())[:10],
        term=str(form.get("term") or "").strip(),
        grade=str(form.get("grade") or "").strip(),
        section=str(form.get("section") or "").strip(),
        period=str(form.get("period") or "").strip(),
        subject=str(form.get("subject") or "").strip(),
        status="Final",
        evaluator_notes=str(form.get("evaluator_notes") or "").strip(),
        evaluatee_notes="",
    )
    db.add(observation)
    db.flush()

    criteria = db.query(models.ObservationCriterion).filter(
        models.ObservationCriterion.is_active == True
    ).order_by(models.ObservationCriterion.sort_order.asc()).all()
    score_rows = []
    for criterion in criteria:
        raw_rating = str(form.get(f"rating_{criterion.id}") or "NA").strip().upper()
        rating = raw_rating if raw_rating == "NA" or raw_rating in RATING_VALUES else "NA"
        score = models.ObservationScore(
            observation_id=observation.id,
            criterion_id=criterion.id,
            rating=rating,
            evidence=str(form.get(f"evidence_{criterion.id}") or "").strip(),
        )
        score_rows.append(score)
        db.add(score)

    criteria_by_id = {criterion.id: criterion for criterion in criteria}
    feedback = _build_smart_feedback(score_rows, criteria_by_id)
    observation.overall_score = "" if feedback["overall"] is None else str(feedback["overall"])
    observation.smart_feedback = json.dumps(feedback)
    observation.updated_at = datetime.utcnow()
    db.commit()

    return RedirectResponse(url=f"/observations/{observation.id}", status_code=302)


@router.get("/{observation_id}")
def observation_detail_page(observation_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    observation = _teacher_observation_access_filter(
        db.query(models.Observation).filter(models.Observation.id == observation_id),
        db,
        current_user,
    ).first()
    if not observation:
        return RedirectResponse(url="/observations")

    teacher = db.query(models.Teacher).filter(models.Teacher.id == observation.teacher_id).first()
    criteria = db.query(models.ObservationCriterion).filter(
        models.ObservationCriterion.is_active == True
    ).order_by(models.ObservationCriterion.sort_order.asc()).all()
    criteria_by_id = {criterion.id: criterion for criterion in criteria}
    score_rows = db.query(models.ObservationScore).filter(
        models.ObservationScore.observation_id == observation.id
    ).all()
    scores_by_criterion = {score.criterion_id: score for score in score_rows}
    feedback = {}
    try:
        feedback = json.loads(observation.smart_feedback or "{}")
    except json.JSONDecodeError:
        feedback = _build_smart_feedback(score_rows, criteria_by_id)

    return templates.TemplateResponse(
        "observation_detail.html",
        {
            "request": request,
            "shell": build_shell_context(
                request,
                db,
                current_user,
                page_key="observations",
                notice=request.query_params.get("notice", ""),
            ),
            "observation": observation,
            "teacher": teacher,
            "teacher_name": _teacher_name(teacher),
            "criteria_groups": _criteria_by_domain(criteria),
            "scores_by_criterion": scores_by_criterion,
            "feedback": feedback,
        },
    )


@router.post("/{observation_id}/evaluatee-notes")
async def save_evaluatee_notes(observation_id: int, request: Request, db: Session = Depends(get_db)):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    observation = _teacher_observation_access_filter(
        db.query(models.Observation).filter(models.Observation.id == observation_id),
        db,
        current_user,
    ).first()
    if not observation:
        return RedirectResponse(url="/observations")

    form = await request.form()
    observation.evaluatee_notes = str(form.get("evaluatee_notes") or "").strip()
    observation.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return RedirectResponse(url=f"/observations/{observation.id}?notice=Notes+saved", status_code=302)


def _parse_int(value):
    try:
        return int(str(value or "").strip())
    except ValueError:
        return None
