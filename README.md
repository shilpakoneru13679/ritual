# Ritual

A personalized wellness companion that generates AI-powered workout plans and meal prep, tracks daily habits, and shows your progress over time.

**Live demo:** [ritual-86sn.onrender.com](https://ritual-86sn.onrender.com)

---

## What it does

Ritual is a full-stack wellness app where users create an account, complete a one-time onboarding (goals, equipment, dietary prefs, daily targets), and get a personalized routine built around who they actually are.

Every day you log how you slept, how stressed you are, your energy, mood, and water intake. Ritual compares that against your personal goals and marks off habit emojis on your calendar. Over time you can see patterns — where you're consistent, where you're slipping, what correlates with better days.

---

## Features

**Auth and accounts**
- Signup, login, and logout with JWT cookie-based auth
- Passwords hashed with bcrypt directly (no third-party auth provider)
- 30-day persistent sessions via HTTP-only cookies

**Onboarding**
- Sets goals, equipment, workout days, session duration, dietary preferences, grocery budget, YouTube video preferences, and daily habit targets (sleep and water goals) all in one flow
- Everything feeds downstream into AI generation and habit tracking automatically

**Workout plans**
- AI-generated weekly plan tailored to goals, equipment, available days, and session length
- YouTube video integration — pick how many days and what style (pilates, HIIT, yoga, etc.) and those days get a specific searchable video suggestion instead of a text exercise list
- Set a weekly focus that shapes the entire plan
- Regenerate any single day without redoing the full week

**Meal planning**
- Two modes: give a budget (we recommend what to buy) or list what you have (we build meals around it)
- Open-ended food likes/dislikes field
- Macro nutrition focus chips (high protein, low carb, etc.)
- Optional per-meal macro estimates (calories, protein, carbs, fat, fiber)
- Regenerate any single day's meals independently
- Printable grocery list that opens in a clean print-optimized page with checkbox rows

**Daily check-in**
- Logs sleep, stress, energy, mood, water intake, period tracking, and free-form notes
- Reactive insight message based on actual data (low sleep, high stress, streak detection, etc.)
- Quote of the day (deterministic per-day rotation, no extra API calls)
- Edit or delete any past log directly from the calendar

**Habit tracker calendar**
- Monthly calendar view with prev/next navigation
- Each day shows emoji badges for habits met: 😴 sleep goal, 💧 water goal, 💪 workout day, 🥗 mood check-in
- Days with all 4 habits get a gold "perfect day" highlight
- Click any day to log or edit that day's entry

**Dashboard**
- Weekly summary card: days logged, average sleep, average mood, workouts completed
- 7-day dual-axis trend chart (sleep and mood) using Chart.js
- Reactive daily check-in with sliders
- Quick links to latest workout and meal plans

**Settings**
- Dedicated lightweight settings page for editing daily targets, meal preferences, and workout video preferences without re-doing full onboarding

---

## Tech stack

| Layer | Tech |
|---|---|
| Backend | Python, FastAPI |
| Database | PostgreSQL + SQLAlchemy ORM |
| Auth | JWT (python-jose) + bcrypt |
| Templating | Jinja2 |
| AI | Google Gemini API (gemini-3.5-flash) |
| Charts | Chart.js |
| Deployment | Render (web service + managed PostgreSQL) |

---

## How it's built

**Auth** — no third-party auth provider. Passwords hashed with bcrypt directly, sessions stored as JWT tokens in HTTP-only cookies with a 30-day expiry. Token validation runs on every protected route.

**Database schema** — 4 tables: `users`, `daily_logs`, `workout_plans`, `meal_plans`. All tied by `user_id`. `MealPlan` stores the generation context (food prefs, macro prefs, macro toggle) so single-day regeneration can reuse the exact same settings.

**Habit tracking logic** — `get_habit_emojis()` compares each day's log against the user's saved goals from onboarding. No separate habit-log table needed — the comparison happens at query time against `DailyLog` fields.

**Single-day regeneration** — asks Gemini to regenerate just one day's block in the same format, then uses a regex replace to swap that section into the existing `plan_text`, leaving the rest of the week untouched.

**Structured Gemini prompts** — all AI outputs use strict format instructions so the responses can be parsed client-side by JavaScript into styled UI components rather than raw text dumps.

---

## Running locally

```bash
git clone https://github.com/shilpakoneru13679/ritual.git
cd ritual
pip install -r requirements.txt
```

Create a `.env` file:
```
GEMINI_API_KEY=your_key_here
SECRET_KEY=any-random-string
DATABASE_URL=postgresql://localhost/ritual
```

Set up the database:
```bash
createdb ritual
```

Run:
```bash
uvicorn main:app --reload
```

Open `http://127.0.0.1:8000`

---

## Project structure

```
ritual/
├── main.py          # All FastAPI routes (~20 endpoints)
├── database.py      # SQLAlchemy models and DB init
├── auth.py          # JWT + bcrypt auth utilities
├── requirements.txt
├── .env             # Not committed
└── templates/
    ├── landing.html
    ├── signup.html
    ├── login.html
    ├── onboarding.html
    ├── dashboard.html
    ├── workout.html
    ├── meals.html
    ├── calendar.html
    ├── settings.html
    ├── edit_log.html
    └── grocery_print.html
```

---

Built by Shilpa Koneru
