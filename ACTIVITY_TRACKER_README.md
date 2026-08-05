# Activity Tracker Module

This module provides a fully integrated, role-based time and activity tracking system within the ERP.

## Overview
The Activity Tracker allows employees to log their daily activities in time blocks (e.g., Deep Work, Meetings, Email), while providing Reporting Persons (Managers) with a consolidated dashboard to monitor team productivity and weekly hours. Super Admins control the organizational structure by mapping employees to their respective reporting managers.

---

## Role-Based Access Control

1. **Super Admin**: 
   - Has exclusive access to **Team Mapping**.
   - Defines which employees report to which managers.
2. **Reporting Person (Manager)**: 
   - Has access to the **Team Dashboard**.
   - Can view aggregated activity summaries, regular hours, and overtime for all mapped team members.
3. **Employee / HR**: 
   - Has access to the **Daily Activity Tracker**.
   - Responsible for filling out day-to-day time activities (in 30-minute blocks). HR may have override permissions to fill data on behalf of employees if needed.

---

## Implementation Plan (Phase-Wise)

### Phase 1: Foundation (Database & Models)
**Goal:** Set up the underlying database schema to store activity data and team hierarchies.
- **Models to Create:**
  - `TeamMapping`: Links an Employee (User) to a Reporting Person (Manager).
  - `ActivityCategory`: Stores standard categories (e.g., Deep Work, Meetings, Email, Break, Planning).
  - `ActivityLog`: Stores the actual time entries (Date, Time Block, Category ID, Employee ID, Duration).
- **Alembic Migrations:** Generate and run migrations for the new tables.

### Phase 2: Data Entry (Employee / HR View)
**Goal:** Build the backend APIs and frontend UI for employees to log their time.
- **Backend APIs:**
  - `GET /api/v1/activities/categories` - Fetch available categories for the dropdowns.
  - `POST /api/v1/activities/log` - Submit daily activity blocks.
  - `GET /api/v1/activities/me` - Fetch the current user's logged activities for the week.
- **Frontend UI:**
  - Create `templates/employee/activity_tracker.html`.
  - Build a grid-based form where users select categories for time blocks and see their daily totals (Regular vs. Overtime).

### Phase 3: Team Dashboard (Reporting Person View)
**Goal:** Provide managers with a high-level summary of their team's activities.
- **Backend APIs:**
  - `GET /api/v1/activities/team-summary` - Aggregate weekly hours by category and employee for the manager's mapped team.
- **Frontend UI:**
  - Create `templates/manager/activity_dashboard.html`.
  - Build a dashboard displaying weekly summaries, total deep work hours, meetings, and overtime across the team.

### Phase 4: Administration (Super Admin View)
**Goal:** Allow Super Admins to manage the organizational structure.
- **Backend APIs:**
  - `POST /api/v1/teams/map` - Assign an employee to a reporting manager.
- **Frontend UI:**
  - Create `templates/admin/team_mapping.html`.
  - Provide a simple interface with dropdowns to map employees to their respective team leads/managers.

---

## Folder Structure

The implementation of the Activity Tracker module will involve creating or modifying the following files:

```text
app/
├── api/
│   └── v1/
│       ├── activities.py       # (New) API endpoints for activity logging and dashboard
│       └── teams.py            # (New) API endpoints for team mapping
├── models/
│   ├── activity.py             # (New) ActivityLog and ActivityCategory models
│   └── team.py                 # (New) TeamMapping model
└── schemas/
    ├── activity.py             # (New) Pydantic schemas for activities
    └── team.py                 # (New) Pydantic schemas for team mapping

templates/
├── admin/
│   └── team_mapping.html       # (New) UI for mapping employees to managers
├── employee/
│   └── activity_tracker.html   # (New) UI for daily time logging
└── manager/
    └── activity_dashboard.html # (New) UI for team activity summary

alembic/
└── versions/
    └── [timestamp]_activity_module.py # (New) Database migration for new tables
```
