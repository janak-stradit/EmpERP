# Tickets Module API — Integration Guide

This is a reference for integrating an external application with Stradit Workforce's Tickets module: creating projects, sprints, and tickets, and reading back work as it progresses. It documents the actual behavior of the code in `app/api/v1/tickets.py`, `app/api/v1/auth.py`, and their schemas — not an aspirational spec.

## 1. Base URL & versioning

All endpoints in this guide are mounted under:

```
{server}/api/v1
```

There is no separate API version negotiation — `/api/v1` is the only version today. Interactive, always-current Swagger docs (generated from the same code) are available at `{server}/docs`, and the raw OpenAPI schema at `{server}/openapi.json`, if you want to generate a client instead of hand-rolling one.

## 2. Authentication

Every endpoint below requires a bearer token obtained through the login flow. There is currently no separate API-key / service-account mechanism — an integration authenticates as a real user account, the same way the web app does.

### 2.1 Log in

```
POST /api/v1/auth/login
Content-Type: application/json

{ "email": "integrator@yourcompany.com", "password": "..." }
```

Response (`LoginResponse`):

```json
{
  "requires_2fa": false,
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "must_change_password": false
}
```

- If `requires_2fa` is `true`, `access_token`/`refresh_token` are omitted and a `pre_2fa_token` is returned instead. Complete login with:
  ```
  POST /api/v1/auth/2fa/verify
  { "pre_2fa_token": "...", "code": "123456" }
  ```
  which returns the same token shape as a normal login.
- If `must_change_password` is `true`, the account must call `PUT /api/v1/auth/change-password` before doing anything else — most endpoints will keep working with the issued token, but plan for this state if you're provisioning integration accounts yourself.
- **Recommendation:** create a dedicated user for the integration (its own login, added as a project member with whatever role — see §3) rather than reusing a real employee's credentials.

### 2.2 Use the token

```
Authorization: Bearer <access_token>
```

on every request. Access tokens currently expire after **360 minutes (6 hours)**.

### 2.3 Refresh

```
POST /api/v1/auth/refresh
{ "refresh_token": "..." }
```

returns a fresh `{access_token, refresh_token}` pair (the refresh token rotates on every use). Refresh tokens expire after **1 day** of not being used — if your integration runs continuously, refresh proactively (e.g. every 30–60 minutes) rather than waiting for a 401, the way the web app's own background refresh loop does (`static/js/notifications.js`). If the refresh token has expired, you must log in again.

## 3. Authorization model

Access is scoped per-project via a role stored on `ProjectMember`. A user's effective role on a given project is one of:

| Role | Notes |
|---|---|
| `admin` | Full control, including sprint lifecycle and project settings |
| `manager` | Same as admin for day-to-day ticket/sprint work |
| `developer` | Can create/edit/transition/comment on tickets |
| `tester` | Same permissions as `developer` |
| `viewer` | Read-only |

A company-level `admin`/`super_admin` user (the `User.role` field, distinct from the project role above) always acts as `admin` on every project, even without an explicit `ProjectMember` row. Anyone else who isn't an explicit project member defaults to `viewer` (read-only) on that project.

Permission matrix actually enforced (`app/api/v1/ticket_permissions.py`):

| Action | Roles allowed |
|---|---|
| Create ticket | admin, manager, developer, tester |
| Edit own ticket (reporter or assignee) | admin, manager, developer, tester |
| Edit any ticket | admin, manager |
| Delete ticket | admin, manager |
| Transition ticket status | admin, manager, developer, tester |
| Comment | admin, manager, developer, tester |
| Log work | admin, manager, developer, tester |
| Manage sprints (create/start/complete/delete) | admin, manager |
| Manage project settings | admin |
| Export reports | admin, manager |

**Creating a project itself has no project-role gate** — any authenticated company user can create one, and becomes its `admin` automatically (`POST /api/v1/projects`, see §4.1). Adding your integration user to an *existing* project requires an existing project admin/manager to call `POST /api/v1/projects/{project_id}/members`.

A `403 Forbidden` with `{"detail": "Insufficient project permissions"}` means the authenticated user's role on that specific project doesn't allow the action — check project membership, not just company role.

## 4. Quickstart: create a project → sprint → ticket

### 4.1 Create a project

```
POST /api/v1/projects
{ "key": "DEV", "name": "Development", "description": "optional" }
```

- `key` is uppercased and must be alphanumeric, unique per company, max 10 characters — it becomes the prefix for every ticket key in this project (`DEV-001`, `DEV-002`, ...).
- Creating a project auto-seeds three default statuses (`To Do` / `In Progress` / `Done`, categories `todo`/`inprogress`/`done`) scoped to that project, and — the first time *any* project is created for the company — a default catalog of issue types (Bug, Task, Story, Epic, Sub-task) and priorities (Highest → Lowest), which are shared company-wide across all projects.
- The creating user is automatically added as that project's `admin`.

Response (`ProjectResponse`) includes `id`, `key`, `name`, `is_active`, `my_role`, `open_ticket_count`.

### 4.2 Create a sprint

```
POST /api/v1/projects/{project_id}/sprints
{
  "name": "Sprint 1",
  "goal": "<p>Ship the checkout redesign</p>",
  "start_date": "2026-09-01",
  "end_date": "2026-09-14",
  "linked_project_ids": []
}
```

- All fields except `name` are optional. `goal` is stored as free text (the web UI writes rich-text HTML into it via a WYSIWYG editor, but the API accepts any string).
- `linked_project_ids` lets a sprint span multiple projects — tickets from any linked project can also be pulled into this sprint, and its board/backlog/velocity reporting aggregates across all of them. Every id must belong to a project in the same company or you get a `404`.
- New sprints start in status `future`. Start one with `POST /api/v1/sprints/{sprint_id}/start` (only one sprint per *owning* project can be `active` at a time — starting a second one 400s) and close it with `POST /api/v1/sprints/{sprint_id}/complete`, which requires an `incomplete_action` of `"backlog"` (default), `"next_sprint"` (needs `target_sprint_id`), or `"keep"` for whatever's still not in a `done`-category status.

### 4.3 Create a ticket

```
POST /api/v1/tickets
{
  "project_id": 1,
  "summary": "Fix payment retry bug",
  "description": "optional",
  "issue_type_id": 12,
  "priority_id": 34,
  "assignee_id": null,
  "parent_id": null,
  "epic_id": null,
  "sprint_id": null,
  "story_points": 3,
  "original_estimate": 120,
  "due_date": "2026-09-10"
}
```

- `project_id`, `summary`, and `issue_type_id` are the only required fields. Fetch valid `issue_type_id`/`priority_id` values first via `GET /api/v1/issue-types` and `GET /api/v1/priorities` (company-wide catalogs, not project-scoped).
- `parent_id`/`epic_id`, if set, must reference another ticket **in the same project** — cross-project or self-referencing values 400. Leaving `sprint_id` unset puts the ticket in the backlog.
- The ticket is auto-assigned the project's default status and the next `ticket_key` in sequence; the reporter is set to the calling user (which must have an `Employee` profile — a user with no linked employee record gets a `404` here).

Response is a full `TicketDetailResponse` (see §5.3).

### 4.4 Move it through its workflow

```
POST /api/v1/tickets/{ticket_id}/transition
{ "status_id": 56 }
```

`status_id` must be one of the project's own statuses (`GET /api/v1/projects/{project_id}/statuses`). Moving into/out of a `done`-category status automatically stamps/clears `resolved_at`.

## 5. Core resources

### 5.1 Projects — `/api/v1/projects`

| Method & path | Purpose |
|---|---|
| `GET /projects` | List projects in your company |
| `POST /projects` | Create a project (§4.1) |
| `GET /projects/{id}` | Get one project |
| `PUT /projects/{id}` | Update name/description/lead/is_active (`manage_project`) |
| `GET /projects/{id}/members` | List members + roles |
| `POST /projects/{id}/members` | Add a member: `{"employee_id": int, "role": "developer"}` |
| `PUT /projects/{id}/members/{member_id}` | Change a member's role |
| `DELETE /projects/{id}/members/{member_id}` | Remove a member |
| `GET /projects/{id}/statuses` | List workflow statuses |
| `POST /projects/{id}/statuses` | Add a custom status |

### 5.2 Sprints — `/api/v1/projects/{project_id}/sprints` and `/api/v1/sprints/{sprint_id}`

| Method & path | Purpose |
|---|---|
| `GET /projects/{project_id}/sprints` | List sprints owned by **or linked to** this project |
| `POST /projects/{project_id}/sprints` | Create a sprint (§4.2) |
| `GET /sprints/{id}` | Full detail: totals, **per-project breakdown**, **per-member workload** (`SprintDetailResponse`) |
| `PUT /sprints/{id}` | Update name/goal/dates/`linked_project_ids` |
| `POST /sprints/{id}/start` | Activate (400 if the owning project already has an active sprint) |
| `POST /sprints/{id}/complete` | Close, redistributing incomplete tickets |
| `DELETE /sprints/{id}` | Only while status is `future` |

### 5.3 Tickets — `/api/v1/tickets`

| Method & path | Purpose |
|---|---|
| `GET /tickets?project_id=&status_id=&assignee_id=&sprint_id=&q=&page=&page_size=` | List/search/filter, paginated (default `page_size=25`) |
| `POST /tickets` | Create (§4.3) |
| `GET /tickets/{id}` | Full detail, including `parent`/`epic`/`subtasks`/`epic_tickets` relation summaries |
| `PUT /tickets/{id}` | Partial update — any subset of `summary`, `description`, `issue_type_id`, `priority_id`, `assignee_id`, `parent_id`, `epic_id`, `story_points`, `original_estimate`, `remaining_estimate`, `due_date` |
| `DELETE /tickets/{id}` | Soft delete (`delete_ticket`) |
| `POST /tickets/{id}/transition` | Change status (§4.4) |
| `POST /tickets/{id}/clone` | Duplicate a ticket: `{"summary": str\|null, "include_parent_epic": bool, "include_subtasks": bool, "include_comments": bool, "include_attachments": bool}` (all flags default `true`; `summary` defaults to `"Copy of {original}"`). The clone gets a new key, the project's default status, an empty sprint, and the current user as reporter; requires `create_ticket` |
| `POST /tickets/{id}/position` | Reorder on the board: `{"status_id": int, "position": int}` |
| `POST /tickets/{id}/sprint` | Move to a sprint (or `null` for backlog): `{"sprint_id": int\|null}` — requires `manage_sprints` (admin/manager), unlike most other single-field ticket edits which only need `edit_own_ticket`/`edit_any_ticket` |
| `POST /tickets/{id}/watch` / `DELETE .../watch` | Watch / unwatch |
| `POST /tickets/bulk` | Bulk status/assignee/sprint change or delete across `ticket_ids: [int]` — requires `edit_any_ticket` (admin/manager) on every affected ticket's project |

`TicketDetailResponse` (the shape returned by create/get/update) includes: `id`, `project_id`, `project_key`, `ticket_key`, `summary`, `description`, `issue_type`, `status`, `priority`, `reporter_id`/`reporter_name`, `assignee_id`/`assignee_name`, `parent_id`/`epic_id` (raw ids) plus `parent`/`epic` (nested `{id, ticket_key, summary, status_name, status_color}` or `null`), `subtasks`/`epic_tickets` (arrays of that same shape), `sprint_id`, `board_position`, `story_points`, `original_estimate`/`remaining_estimate`/`time_spent` (all in minutes), `due_date`, `resolved_at`, `created_at`/`updated_at`, `is_watching`, `watcher_count`, `labels`, `my_role` (your effective role on this ticket's project).

### 5.4 Comments — `/api/v1/tickets/{ticket_id}/comments`

`GET` (list), `POST {"body": str, "is_internal": bool}`, `PUT /{comment_id} {"body": str}` (author-only, within 15 minutes of posting — 400s after that), `DELETE /{comment_id}`. `is_internal` comments are a visibility flag your own client is responsible for respecting — the API doesn't currently filter them per-viewer.

### 5.5 Attachments — `/api/v1/tickets/{ticket_id}/attachments`

`GET` (list), `POST` as `multipart/form-data` with a `file` field, `GET /{attachment_id}/download` (streams the file), `DELETE /{attachment_id}`.

### 5.6 Work logs — `/api/v1/tickets/{ticket_id}/worklogs`

`GET` (list), `POST {"minutes_spent": int, "log_date": "YYYY-MM-DD", "description": str|null}` — accumulates into the ticket's `time_spent`.

### 5.7 Labels — `/api/v1/projects/{project_id}/labels` and `/api/v1/tickets/{ticket_id}/labels`

Project-scoped label catalog (`POST {"name": str, "color": "#rrggbb"}`); attach/detach on a ticket via `POST /tickets/{id}/labels {"label_id": int}` and `DELETE /tickets/{id}/labels/{label_id}`.

## 6. Read-only aggregate views

These exist mainly for the web UI but are plain JSON and fine to consume directly:

| Path | Returns |
|---|---|
| `GET /projects/{id}/board?sprint_id=` | Kanban view: statuses + tickets for the active (or given) sprint |
| `GET /projects/{id}/backlog` | Active sprint, future sprints, and unsprinted backlog, each with their tickets |
| `GET /tickets/board?project_id=&project_id=&assignee_id=` | Cross-project board across **every project in your company** (no per-project membership check on this read) — optionally scoped to specific `project_id`s |
| `GET /tickets/export?...` (same filters as list) | CSV export |
| `GET /tickets/time-report?...` | Logged-time rollup by employee |
| `GET /dashboard/{project_id}` | KPIs, status distribution, sprint progress, recent activity |
| `GET /dashboard/{project_id}/burndown?sprint_id=` | Burndown series |
| `GET /dashboard/{project_id}/velocity` | Last 6 completed sprints |
| `GET /reports/sprint/{sprint_id}` | Full sprint report: completed/incomplete tickets, cycle time, contribution |

## 7. Errors

- `400 Bad Request` — `{"detail": "human-readable message"}` for domain validation (bad status transition target, duplicate project key, cross-project parent/epic, etc.).
- `403 Forbidden` — `{"detail": "Insufficient project permissions"}`.
- `404 Not Found` — `{"detail": "..."}` for missing/inaccessible resources. Note that "inaccessible" and "doesn't exist" are indistinguishable by design — a ticket in a project outside your company (or, for a resource like a sprint, outside the projects it's linked to) 404s rather than 403s.
- `422 Unprocessable Entity` — standard FastAPI/Pydantic body validation errors: `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}`.

## 8. Not currently supported

Worth knowing before you design around them:

- No API-key/service-account auth — only user login (§2).
- No webhooks — integrations needing near-real-time updates must poll (e.g. `GET /tickets?project_id=&q=` with `updated_at` client-side filtering, since there's no `updated_since` query param today).
- No bulk *create* endpoint for tickets (only bulk status/assignee/sprint update and delete) — creating many tickets means one `POST /tickets` call each.
- No cross-ticket "blocks / blocked by" relationship — only `parent_id` (sub-task) and `epic_id`.
