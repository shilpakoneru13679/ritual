from fastapi import FastAPI, Form, Request, Depends, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from datetime import date, datetime
from typing import List, Optional
import os, json
from dotenv import load_dotenv
from google import genai

from database import get_db, init_db, User, DailyLog, WorkoutPlan, MealPlan
from auth import hash_password, verify_password, create_token, get_current_user_id, require_auth

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
client = genai.Client(api_key=api_key)
MODEL = "gemini-3.5-flash"

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Initialize DB on startup
@app.on_event("startup")
def startup():
    init_db()


# ── HELPERS ──────────────────────────────────────────────────────────────────

def get_user(user_id: int, db: Session) -> Optional[User]:
    return db.query(User).filter(User.id == user_id).first()


DAILY_QUOTES = [
    "Small steps still move you forward.",
    "You don't have to be perfect, just consistent.",
    "Rest is productive too.",
    "Progress, not perfection.",
    "You showed up today, and that counts.",
    "Be proud of how far you've come.",
    "One good habit a day adds up.",
    "You're allowed to take it slow.",
    "Your effort matters more than the outcome.",
    "Today is enough, just as it is.",
    "Trust the process, even on the hard days.",
    "You are doing better than you think.",
    "Growth isn't always loud.",
    "Take care of yourself like you would a friend.",
    "Every day is a fresh start.",
    "Consistency beats intensity.",
    "You don't need to earn rest.",
    "Celebrate the small wins too.",
    "Your pace is the right pace.",
    "Be gentle with yourself today.",
    "Discipline is just self-respect in action.",
    "You're allowed to be a work in progress.",
    "Some days are just about showing up.",
    "Your body is listening to every kind word you say to it.",
    "Energy follows intention.",
    "Stay soft, stay strong.",
    "You're closer than you were yesterday.",
    "Healthy looks different every day, and that's okay.",
    "Nourish yourself like you matter, because you do.",
    "The little rituals are what build the big changes.",
]


def get_daily_quote() -> str:
    """Deterministic quote based on day of year, so it's stable for the whole day."""
    day_index = date.today().timetuple().tm_yday
    return DAILY_QUOTES[day_index % len(DAILY_QUOTES)]


def get_streak(user_id: int, db: Session) -> int:
    """Count consecutive days logged ending today."""
    logs = db.query(DailyLog).filter(DailyLog.user_id == user_id).order_by(DailyLog.date.desc()).all()
    if not logs:
        return 0
    streak = 0
    expected = date.today()
    for log in logs:
        if log.date == expected:
            streak += 1
            expected = expected - __import__("datetime").timedelta(days=1)
        else:
            break
    return streak


def get_daily_insight(log: DailyLog, streak: int) -> str:
    """Generate a short, reactive insight based on today's actual logged data."""
    # Streak takes priority if 3+
    if streak >= 7:
        return f"{streak} days in a row, that's a real habit forming. Keep going."
    if streak >= 3:
        return f"{streak} days in a row of checking in. Great consistency."

    # Low water
    if log.water_oz is not None and log.water_oz > 0 and log.water_oz < 40:
        return "Don't forget to drink some water today."

    # High stress
    if log.stress_level and log.stress_level >= 4:
        return "Another stressful day? Don't forget your mental health matters more than any checklist."

    # Low sleep
    if log.sleep_hours and log.sleep_hours < 6:
        return "That's not a lot of sleep. Try to get some extra rest tonight."

    # Low mood
    if log.mood and log.mood <= 2:
        return "Rough day, huh? Be extra kind to yourself today."

    # Low energy
    if log.energy_level and log.energy_level <= 2:
        return "Low energy today is okay. Listen to what your body needs."

    # Great overall day (high mood + energy, low stress)
    if log.mood and log.mood >= 4 and log.energy_level and log.energy_level >= 4 and (not log.stress_level or log.stress_level <= 2):
        return "You did great today. Keep that momentum going."

    # Default
    return "Thanks for checking in today. Every log adds up."


def get_habit_emojis(log: DailyLog, user: User, had_workout: bool) -> List[str]:
    """Compare a day's log against the user's saved goals and return earned emoji badges."""
    emojis = []

    # Sleep goal met
    if log.sleep_hours is not None and user.sleep_goal_hours and log.sleep_hours >= user.sleep_goal_hours:
        emojis.append("😴")

    # Water goal met
    if log.water_oz is not None and user.water_goal_oz and log.water_oz >= user.water_goal_oz:
        emojis.append("💧")

    # Exercise logged that day
    if had_workout:
        emojis.append("💪")

    # Meal/nutrition: count it as met if stress is logged and reasonably low, paired with a decent mood
    # (no direct "meal eaten" tracking exists yet, so we use the daily check-in itself as a proxy for self-care)
    if log.mood is not None and log.mood >= 3:
        emojis.append("🥗")

    return emojis


def get_weekly_summary(user_id: int, user: User, db: Session) -> dict:
    """Compute a rolling 7-day summary: days logged, avg sleep, avg mood, workouts done."""
    week_start = date.today() - __import__("datetime").timedelta(days=6)
    logs = db.query(DailyLog).filter(
        DailyLog.user_id == user_id,
        DailyLog.date >= week_start,
        DailyLog.date <= date.today(),
    ).all()

    days_logged = len(logs)

    sleep_vals = [l.sleep_hours for l in logs if l.sleep_hours is not None]
    avg_sleep = round(sum(sleep_vals) / len(sleep_vals), 1) if sleep_vals else None

    mood_vals = [l.mood for l in logs if l.mood is not None]
    avg_mood = round(sum(mood_vals) / len(mood_vals), 1) if mood_vals else None

    water_vals = [l.water_oz for l in logs if l.water_oz is not None]
    avg_water = round(sum(water_vals) / len(water_vals)) if water_vals else None

    # Count workout days this week using saved workout plan + user's workout_days
    workouts = db.query(WorkoutPlan).filter(
        WorkoutPlan.user_id == user_id,
        WorkoutPlan.week_start >= week_start - __import__("datetime").timedelta(days=7),
    ).all()
    day_names = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
    active_days = [d.strip() for d in (user.workout_days or "").split(",") if d.strip()]
    workout_dates = set()
    for w in workouts:
        if w.week_start:
            for d_name in active_days:
                if d_name in day_names:
                    wd = w.week_start + __import__("datetime").timedelta(days=day_names[d_name])
                    if week_start <= wd <= date.today():
                        workout_dates.add(wd)
    workouts_done = len(workout_dates)

    return {
        "days_logged": days_logged,
        "total_days": 7,
        "avg_sleep": avg_sleep,
        "avg_mood": avg_mood,
        "avg_water": avg_water,
        "workouts_done": workouts_done,
    }


# ── LANDING / AUTH ───────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    user_id = get_current_user_id(request)
    if user_id:
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse("landing.html", {"request": request})


@app.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request, "error": None})


@app.post("/signup", response_class=HTMLResponse)
async def signup(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return templates.TemplateResponse("signup.html", {"request": request, "error": "An account with that email already exists."})

    user = User(name=name, email=email, hashed_password=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_token(user.id)
    response = RedirectResponse("/onboarding", status_code=302)
    response.set_cookie("ritual_token", token, max_age=60*60*24*30, httponly=True)
    return response


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Incorrect email or password."})

    token = create_token(user.id)
    response = RedirectResponse("/dashboard", status_code=302)
    response.set_cookie("ritual_token", token, max_age=60*60*24*30, httponly=True)
    return response


@app.get("/logout")
async def logout():
    response = RedirectResponse("/", status_code=302)
    response.delete_cookie("ritual_token")
    return response


# ── ONBOARDING ───────────────────────────────────────────────────────────────

@app.get("/onboarding", response_class=HTMLResponse)
async def onboarding_page(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=302)
    user = get_user(user_id, db)
    return templates.TemplateResponse("onboarding.html", {"request": request, "user": user})


@app.post("/onboarding", response_class=HTMLResponse)
async def onboarding_submit(
    request: Request,
    goals: List[str] = Form(...),
    equipment: List[str] = Form(...),
    workout_days: List[str] = Form(...),
    workout_duration: int = Form(...),
    dietary_prefs: str = Form(default=""),
    weekly_grocery_budget: float = Form(default=0.0),
    use_videos: str = Form(default="false"),
    video_days: int = Form(default=0),
    video_types: str = Form(default=""),
    weekly_goal: str = Form(default=""),
    sleep_goal_hours: float = Form(default=8.0),
    water_goal_oz: float = Form(default=64.0),
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=302)

    user = get_user(user_id, db)
    user.goals = ",".join(goals)
    user.equipment = ",".join(equipment)
    user.workout_days = ",".join(workout_days)
    user.workout_duration = workout_duration
    user.dietary_prefs = dietary_prefs
    user.weekly_grocery_budget = weekly_grocery_budget
    user.use_videos = use_videos == "true"
    user.video_days = video_days
    user.video_types = video_types
    user.weekly_goal = weekly_goal
    user.sleep_goal_hours = sleep_goal_hours
    user.water_goal_oz = water_goal_oz
    user.onboarded = True
    db.commit()

    return RedirectResponse("/dashboard", status_code=302)


# ── SETTINGS (quick edits to ongoing preferences) ────────────────────────────

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=302)
    user = get_user(user_id, db)
    return templates.TemplateResponse("settings.html", {"request": request, "user": user, "saved": False})


@app.post("/settings", response_class=HTMLResponse)
async def settings_submit(
    request: Request,
    sleep_goal_hours: float = Form(default=8.0),
    water_goal_oz: float = Form(default=64.0),
    dietary_prefs: str = Form(default=""),
    weekly_grocery_budget: float = Form(default=0.0),
    weekly_goal: str = Form(default=""),
    use_videos: str = Form(default="false"),
    video_days: int = Form(default=0),
    video_types: str = Form(default=""),
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=302)

    user = get_user(user_id, db)
    user.sleep_goal_hours = sleep_goal_hours
    user.water_goal_oz = water_goal_oz
    user.dietary_prefs = dietary_prefs
    user.weekly_grocery_budget = weekly_grocery_budget
    user.weekly_goal = weekly_goal
    user.use_videos = use_videos == "true"
    user.video_days = video_days
    user.video_types = video_types
    db.commit()

    return templates.TemplateResponse("settings.html", {"request": request, "user": user, "saved": True})


# ── DASHBOARD ────────────────────────────────────────────────────────────────

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=302)

    user = get_user(user_id, db)
    if not user.onboarded:
        return RedirectResponse("/onboarding", status_code=302)

    # Latest workout and meal plans
    workout = db.query(WorkoutPlan).filter(WorkoutPlan.user_id == user_id).order_by(WorkoutPlan.created_at.desc()).first()
    meal = db.query(MealPlan).filter(MealPlan.user_id == user_id).order_by(MealPlan.created_at.desc()).first()

    # Last 7 daily logs
    logs = db.query(DailyLog).filter(DailyLog.user_id == user_id).order_by(DailyLog.date.desc()).limit(7).all()

    # Today's log
    today_log = db.query(DailyLog).filter(DailyLog.user_id == user_id, DailyLog.date == date.today()).first()

    # Chart data: oldest -> newest, last 7 days
    chart_logs = list(reversed(logs))
    chart_data = {
        "labels": [l.date.strftime("%a") for l in chart_logs],
        "sleep": [l.sleep_hours if l.sleep_hours is not None else None for l in chart_logs],
        "mood": [l.mood if l.mood is not None else None for l in chart_logs],
    }

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "workout": workout,
        "meal": meal,
        "logs": logs,
        "today_log": today_log,
        "today": date.today().strftime("%A, %B %d"),
        "daily_quote": get_daily_quote(),
        "daily_insight": get_daily_insight(today_log, get_streak(user_id, db)) if today_log else None,
        "chart_data": chart_data,
        "weekly_summary": get_weekly_summary(user_id, user, db),
    })


# ── DAILY LOG ────────────────────────────────────────────────────────────────

@app.post("/log", response_class=HTMLResponse)
async def submit_log(
    request: Request,
    sleep_hours: float = Form(...),
    stress_level: int = Form(...),
    energy_level: int = Form(...),
    mood: int = Form(...),
    water_oz: float = Form(default=0.0),
    period: bool = Form(default=False),
    notes: str = Form(default=""),
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=302)

    # Upsert today's log
    existing = db.query(DailyLog).filter(DailyLog.user_id == user_id, DailyLog.date == date.today()).first()
    if existing:
        existing.sleep_hours = sleep_hours
        existing.stress_level = stress_level
        existing.energy_level = energy_level
        existing.mood = mood
        existing.water_oz = water_oz
        existing.period = period
        existing.notes = notes
    else:
        log = DailyLog(
            user_id=user_id, date=date.today(),
            sleep_hours=sleep_hours, stress_level=stress_level,
            energy_level=energy_level, mood=mood, water_oz=water_oz,
            period=period, notes=notes,
        )
        db.add(log)
    db.commit()

    return RedirectResponse("/dashboard", status_code=302)


# ── EDIT PAST LOG ─────────────────────────────────────────────────────────────

@app.get("/log/edit/{log_date}", response_class=HTMLResponse)
async def edit_log_page(request: Request, log_date: str, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=302)

    try:
        target_date = datetime.strptime(log_date, "%Y-%m-%d").date()
    except ValueError:
        return RedirectResponse("/calendar", status_code=302)

    log = db.query(DailyLog).filter(DailyLog.user_id == user_id, DailyLog.date == target_date).first()

    return templates.TemplateResponse("edit_log.html", {
        "request": request,
        "log": log,
        "log_date": target_date,
        "is_future": target_date > date.today(),
    })


@app.post("/log/edit/{log_date}", response_class=HTMLResponse)
async def edit_log_submit(
    request: Request,
    log_date: str,
    sleep_hours: float = Form(...),
    stress_level: int = Form(...),
    energy_level: int = Form(...),
    mood: int = Form(...),
    water_oz: float = Form(default=0.0),
    period: bool = Form(default=False),
    notes: str = Form(default=""),
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=302)

    try:
        target_date = datetime.strptime(log_date, "%Y-%m-%d").date()
    except ValueError:
        return RedirectResponse("/calendar", status_code=302)

    existing = db.query(DailyLog).filter(DailyLog.user_id == user_id, DailyLog.date == target_date).first()
    if existing:
        existing.sleep_hours = sleep_hours
        existing.stress_level = stress_level
        existing.energy_level = energy_level
        existing.mood = mood
        existing.water_oz = water_oz
        existing.period = period
        existing.notes = notes
    else:
        log = DailyLog(
            user_id=user_id, date=target_date,
            sleep_hours=sleep_hours, stress_level=stress_level,
            energy_level=energy_level, mood=mood, water_oz=water_oz,
            period=period, notes=notes,
        )
        db.add(log)
    db.commit()

    return RedirectResponse(f"/calendar?year={target_date.year}&month={target_date.month}", status_code=302)


@app.post("/log/delete/{log_date}", response_class=HTMLResponse)
async def delete_log(request: Request, log_date: str, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=302)

    try:
        target_date = datetime.strptime(log_date, "%Y-%m-%d").date()
    except ValueError:
        return RedirectResponse("/calendar", status_code=302)

    log = db.query(DailyLog).filter(DailyLog.user_id == user_id, DailyLog.date == target_date).first()
    if log:
        db.delete(log)
        db.commit()

    return RedirectResponse(f"/calendar?year={target_date.year}&month={target_date.month}", status_code=302)


# ── WORKOUT PLAN ─────────────────────────────────────────────────────────────

@app.post("/workout/generate", response_class=HTMLResponse)
async def generate_workout(
    request: Request,
    override_goal: str = Form(default=""),
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=302)

    user = get_user(user_id, db)
    wants_videos = user.use_videos and user.video_days > 0

    video_instruction = ""
    if wants_videos:
        types_str = user.video_types if user.video_types else "pilates, HIIT circuits, yoga, strength training"
        video_instruction = f"""
For exactly {user.video_days} of the workout days, instead of listing individual exercises, write:
"FOLLOW VIDEO: [a real, specific, well known free YouTube workout type from: {types_str}]"
For example: "FOLLOW VIDEO: 30 minute pilates full body workout" or "FOLLOW VIDEO: 20 minute HIIT circuit no equipment"
Make the video description specific enough that it could be searched on YouTube and found easily (include duration, focus area, and style).
For the remaining days, write the normal exercise list format.
"""

    # Use this-week override if provided, otherwise fall back to saved weekly goal
    active_goal = override_goal.strip() if override_goal.strip() else user.weekly_goal
    goal_instruction = ""
    if active_goal:
        goal_instruction = f"\n- This week's main focus: {active_goal} (prioritize this throughout the week's exercise selection and structure)"

    prompt = f"""
Create a personalized weekly workout plan for someone with these details:
- Goals: {user.goals}
- Available equipment: {user.equipment}
- Workout days: {user.workout_days}
- Session duration: {user.workout_duration} minutes{goal_instruction}

FORMAT (follow exactly):
For each workout day use:
DAY [day name]: [theme e.g. Upper Body Strength]
Warmup: [2-3 minute warmup]
[Exercise name]: [sets] x [reps] : [brief tip]
(list 4-6 exercises)
Cooldown: [1-2 minute cooldown]

{video_instruction}

Rest days: just write "REST DAY: active recovery or rest"
Keep it specific, practical, and achievable.
End with a "This Week's Focus" note: one sentence on what to prioritize.
"""

    try:
        response = client.models.generate_content(model=MODEL, contents=prompt)
        plan_text = response.text
    except Exception as e:
        plan_text = f"Error generating plan: {str(e)}"

    plan = WorkoutPlan(user_id=user_id, plan_text=plan_text, week_start=date.today())
    db.add(plan)
    db.commit()

    return RedirectResponse("/workout", status_code=302)


@app.post("/workout/regenerate-day", response_class=HTMLResponse)
async def regenerate_workout_day(
    request: Request,
    day_name: str = Form(...),
    db: Session = Depends(get_db),
):
    """Regenerate just one day's block within the most recent workout plan."""
    user_id = get_current_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=302)

    user = get_user(user_id, db)
    plan = db.query(WorkoutPlan).filter(WorkoutPlan.user_id == user_id).order_by(WorkoutPlan.created_at.desc()).first()
    if not plan:
        return RedirectResponse("/workout", status_code=302)

    prompt = f"""
Create just ONE day of a workout plan for the day "{day_name}", for someone with these details:
- Goals: {user.goals}
- Available equipment: {user.equipment}
- Session duration: {user.workout_duration} minutes
{f"- This week's main focus: {user.weekly_goal}" if user.weekly_goal else ""}

FORMAT (follow exactly, nothing else, no preamble):
DAY {day_name}: [a short evocative theme title]
Warmup: [2-3 minute warmup]
[Exercise name]: [sets] x [reps] : [brief tip]
(list 4-6 exercises)
Cooldown: [1-2 minute cooldown]

Keep it specific, practical, and achievable. Do not include any other days or commentary.
"""

    try:
        response = client.models.generate_content(model=MODEL, contents=prompt)
        new_day_block = response.text.strip()
    except Exception:
        return RedirectResponse("/workout", status_code=302)

    # Replace the matching day block in plan_text
    import re
    pattern = re.compile(
        rf"DAY\s+{re.escape(day_name)}\s*[:].*?(?=\nDAY\s+\w+\s*[:]|\Z)",
        re.DOTALL | re.IGNORECASE
    )
    if pattern.search(plan.plan_text):
        plan.plan_text = pattern.sub(new_day_block + "\n", plan.plan_text, count=1)
    else:
        # Day not found (shouldn't normally happen) - just append it
        plan.plan_text = plan.plan_text + "\n\n" + new_day_block

    db.commit()

    return RedirectResponse("/workout", status_code=302)


@app.get("/workout", response_class=HTMLResponse)
async def workout_page(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=302)

    user = get_user(user_id, db)
    plan = db.query(WorkoutPlan).filter(WorkoutPlan.user_id == user_id).order_by(WorkoutPlan.created_at.desc()).first()

    return templates.TemplateResponse("workout.html", {
        "request": request,
        "user": user,
        "plan": plan,
    })


# ── MEAL PLAN ────────────────────────────────────────────────────────────────

@app.get("/meals", response_class=HTMLResponse)
async def meals_page(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=302)

    user = get_user(user_id, db)
    plan = db.query(MealPlan).filter(MealPlan.user_id == user_id).order_by(MealPlan.created_at.desc()).first()

    return templates.TemplateResponse("meals.html", {
        "request": request,
        "user": user,
        "plan": plan,
    })


@app.get("/meals/grocery-print", response_class=HTMLResponse)
async def grocery_print(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=302)

    plan = db.query(MealPlan).filter(MealPlan.user_id == user_id).order_by(MealPlan.created_at.desc()).first()
    if not plan:
        return RedirectResponse("/meals", status_code=302)

    return templates.TemplateResponse("grocery_print.html", {
        "request": request,
        "plan": plan,
        "date_generated": date.today().strftime("%B %-d, %Y"),
    })


@app.post("/meals/generate", response_class=HTMLResponse)
async def generate_meals(
    request: Request,
    mode: str = Form(...),       # "budget" or "groceries"
    budget: float = Form(default=0.0),
    groceries: str = Form(default=""),
    food_prefs: str = Form(default=""),
    macro_prefs: str = Form(default=""),
    show_macros: str = Form(default="false"),
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=302)

    user = get_user(user_id, db)
    wants_macros = show_macros == "true"

    if mode == "budget":
        context = f"Weekly grocery budget: ${budget}. Recommend what to buy and build meals around it."
    else:
        context = f"The user already has these groceries: {groceries}. Build meals using only what they have."

    prefs_context = ""
    if food_prefs.strip():
        prefs_context = f"\n- Food likes/dislikes: {food_prefs.strip()} (respect this closely: avoid disliked foods entirely, lean into liked ones where it makes sense)"

    macro_context = ""
    if macro_prefs.strip():
        macro_context = f"\n- Nutrition focus: {macro_prefs.strip()} (prioritize this in ingredient choices and portions across all meals)"

    macro_format_instruction = ""
    if wants_macros:
        macro_format_instruction = """
For every single meal (breakfast, lunch, dinner, snack), end the line with a rough macro estimate in parentheses in this exact format:
(approx [X] cal, [X]g protein, [X]g carbs, [X]g fat, [X]g fiber)
Estimates don't need to be precise, just reasonable and consistent with the meal described.
"""

    prompt = f"""
Create a 7-day meal prep plan for someone with these details:
- Dietary preferences: {user.dietary_prefs or 'no restrictions'}
- {context}{prefs_context}{macro_context}

FORMAT (follow exactly):
For each day:
DAY [day]: 
Breakfast: [meal + quick prep note]
Lunch: [meal + quick prep note]
Dinner: [meal + quick prep note]
Snack: [snack idea]
{macro_format_instruction}
Then add a GROCERY LIST section:
GROCERY LIST:
- [item]: [quantity/amount]
(list everything needed, organized by produce, protein, dairy, pantry)

Keep meals realistic, practical, and good for meal prepping in batches.
"""

    try:
        response = client.models.generate_content(model=MODEL, contents=prompt)
        full_text = response.text

        # Split into plan and grocery list
        if "GROCERY LIST" in full_text:
            parts = full_text.split("GROCERY LIST:")
            plan_text = parts[0].strip()
            grocery_list = "GROCERY LIST:\n" + parts[1].strip()
        else:
            plan_text = full_text
            grocery_list = ""

    except Exception as e:
        plan_text = f"Error generating plan: {str(e)}"
        grocery_list = ""

    meal = MealPlan(
        user_id=user_id,
        plan_text=plan_text,
        grocery_list=grocery_list,
        budget=budget if mode == "budget" else None,
        food_prefs=food_prefs,
        macro_prefs=macro_prefs,
        show_macros=wants_macros,
    )
    db.add(meal)
    db.commit()

    return RedirectResponse("/meals", status_code=302)


@app.post("/meals/regenerate-day", response_class=HTMLResponse)
async def regenerate_meal_day(
    request: Request,
    day_name: str = Form(...),
    db: Session = Depends(get_db),
):
    """Regenerate just one day's meals within the most recent meal plan."""
    user_id = get_current_user_id(request)
    if not user_id:
        return RedirectResponse("/meals", status_code=302)

    user = get_user(user_id, db)
    plan = db.query(MealPlan).filter(MealPlan.user_id == user_id).order_by(MealPlan.created_at.desc()).first()
    if not plan:
        return RedirectResponse("/meals", status_code=302)

    prefs_context = ""
    if plan.food_prefs and plan.food_prefs.strip():
        prefs_context = f"\n- Food likes/dislikes: {plan.food_prefs.strip()}"

    macro_context = ""
    if plan.macro_prefs and plan.macro_prefs.strip():
        macro_context = f"\n- Nutrition focus: {plan.macro_prefs.strip()}"

    macro_format_instruction = ""
    if plan.show_macros:
        macro_format_instruction = """
For every meal, end the line with a rough macro estimate in parentheses:
(approx [X] cal, [X]g protein, [X]g carbs, [X]g fat, [X]g fiber)
"""

    prompt = f"""
Create just ONE day of meals for "{day_name}", for someone with these details:
- Dietary preferences: {user.dietary_prefs or 'no restrictions'}{prefs_context}{macro_context}

FORMAT (follow exactly, nothing else, no preamble, no grocery list):
DAY {day_name}: 
Breakfast: [meal + quick prep note]
Lunch: [meal + quick prep note]
Dinner: [meal + quick prep note]
Snack: [snack idea]
{macro_format_instruction}
Keep meals realistic, practical, and good for meal prepping.
"""

    try:
        response = client.models.generate_content(model=MODEL, contents=prompt)
        new_day_block = response.text.strip()
    except Exception:
        return RedirectResponse("/meals", status_code=302)

    import re
    pattern = re.compile(
        rf"DAY\s+{re.escape(day_name)}\s*[:].*?(?=\nDAY\s+\w+\s*[:]|\Z)",
        re.DOTALL | re.IGNORECASE
    )
    if pattern.search(plan.plan_text):
        plan.plan_text = pattern.sub(new_day_block + "\n", plan.plan_text, count=1)
    else:
        plan.plan_text = plan.plan_text + "\n\n" + new_day_block

    db.commit()

    return RedirectResponse("/meals", status_code=302)


# ── CALENDAR / HABIT TRACKER ─────────────────────────────────────────────────

import calendar as cal_module

@app.get("/calendar", response_class=HTMLResponse)
async def calendar_page(
    request: Request,
    year: int = None,
    month: int = None,
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=302)

    user = get_user(user_id, db)

    today = date.today()
    view_year = year if year else today.year
    view_month = month if month else today.month

    # Get all logs for this month
    first_day = date(view_year, view_month, 1)
    last_day_num = cal_module.monthrange(view_year, view_month)[1]
    last_day = date(view_year, view_month, last_day_num)

    logs = db.query(DailyLog).filter(
        DailyLog.user_id == user_id,
        DailyLog.date >= first_day,
        DailyLog.date <= last_day,
    ).all()

    # Get workout plans this month (rough proxy: any plan created with week_start in this month means workouts happened that week)
    workouts = db.query(WorkoutPlan).filter(
        WorkoutPlan.user_id == user_id,
        WorkoutPlan.week_start >= first_day,
        WorkoutPlan.week_start <= last_day,
    ).all()
    workout_dates = set()
    for w in workouts:
        if w.week_start:
            # Mark the workout days of that week as "had workout" using user's saved workout_days
            day_names = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
            active_days = [d.strip() for d in (user.workout_days or "").split(",") if d.strip()]
            for d_name in active_days:
                if d_name in day_names:
                    offset = day_names[d_name]
                    workout_date = w.week_start + __import__("datetime").timedelta(days=offset)
                    workout_dates.add(workout_date)

    # Build day -> emoji map
    day_emojis = {}
    for log in logs:
        had_workout = log.date in workout_dates
        emojis = get_habit_emojis(log, user, had_workout)
        if emojis:
            day_emojis[log.date.day] = emojis

    # Calendar grid structure
    cal_obj = cal_module.Calendar(firstweekday=6)  # Sunday start
    month_weeks = cal_obj.monthdayscalendar(view_year, view_month)

    prev_month = view_month - 1 if view_month > 1 else 12
    prev_year = view_year if view_month > 1 else view_year - 1
    next_month = view_month + 1 if view_month < 12 else 1
    next_year = view_year if view_month < 12 else view_year + 1

    has_any_logs = db.query(DailyLog).filter(DailyLog.user_id == user_id).first() is not None

    return templates.TemplateResponse("calendar.html", {
        "request": request,
        "user": user,
        "month_name": cal_module.month_name[view_month],
        "view_year": view_year,
        "view_month": view_month,
        "month_weeks": month_weeks,
        "day_emojis": day_emojis,
        "today": today,
        "prev_month": prev_month,
        "prev_year": prev_year,
        "next_month": next_month,
        "next_year": next_year,
        "has_any_logs": has_any_logs,
    })