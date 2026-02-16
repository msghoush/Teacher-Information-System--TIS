@app.get("/subjects")
def subjects_page(request: Request, db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse(url="/")

    user = db.query(models.User).filter(models.User.user_id == user_id).first()

    subjects = db.query(models.Subject).filter(
        models.Subject.branch_id == user.branch_id,
        models.Subject.academic_year_id == user.academic_year_id
    ).all()

    return templates.TemplateResponse("subjects.html", {
        "request": request,
        "subjects": subjects
    })


@app.post("/subjects")
def add_subject(request: Request,
                subject_code: str = Form(...),
                subject_name: str = Form(...),
                weekly_hours: int = Form(...),
                grade: int = Form(...),
                db: Session = Depends(get_db)):

    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse(url="/")

    user = db.query(models.User).filter(models.User.user_id == user_id).first()

    new_subject = models.Subject(
        subject_code=subject_code,
        subject_name=subject_name,
        weekly_hours=weekly_hours,
        grade=grade,
        branch_id=user.branch_id,
        academic_year_id=user.academic_year_id
    )

    db.add(new_subject)
    db.commit()

    return RedirectResponse(url="/subjects", status_code=302)