# Phase 2: Core Ticketing Engine

## Overview
Build the heart of the system: tickets, workflows, comments, attachments, and the activity audit trail. This is the most critical phase — everything else builds on top of this.

**Duration:** 3–4 weeks  
**Goal:** Full ticket lifecycle, status transitions, comments, file uploads, search basics

---

## 2.1 Ticket Data Model

### Core Fields
| Field | Type | Notes |
|-------|------|-------|
| ticket_key | VARCHAR(20) | Unique, auto-generated: PROJ-001, PROJ-002 |
| project_id | FK | Every ticket belongs to exactly one project |
| summary | VARCHAR(255) | Required, short title |
| description | TEXT | Rich text / markdown support |
| issue_type_id | FK | Bug, Task, Story, Epic, Sub-task |
| status_id | FK | Current workflow state |
| priority_id | FK | Highest → Lowest |
| reporter_id | FK | Who created it |
| assignee_id | FK | Who is working on it (nullable) |
| parent_id | FK | Self-referencing for sub-tasks |
| epic_id | FK | Self-referencing for epic linkage |
| sprint_id | FK | Which sprint (nullable = backlog) |
| story_points | INTEGER | Agile estimation |
| original_estimate | INTEGER | Minutes |
| remaining_estimate | INTEGER | Minutes |
| time_spent | INTEGER | Minutes, accumulated from work logs |
| due_date | DATE | Deadline |
| resolved_at | TIMESTAMP | When moved to a "done" category status |

### Auto-Key Generation Logic
- When a ticket is created, count existing tickets in the project
- Format: `{PROJECT_KEY}-{SEQUENCE:03d}`
- Example: Project key `DEV` → first ticket = `DEV-001`, 100th = `DEV-100`
- Sequence is per-project, not global
- Handle race conditions: use database sequence or atomic counter

### Hierarchy Rules
- A ticket can have one parent (sub-task relationship)
- A ticket can belong to one epic (epic linkage)
- Epic tickets cannot have parents
- Sub-tasks cannot have their own sub-tasks (one level deep)
- UI should visually indent sub-tasks under their parent

---

## 2.2 Ticket CRUD Operations

### Create Ticket
- Form fields: summary (required), description, issue type, priority, assignee, parent, epic, sprint, story points, due date
- Auto-set: reporter = current user, status = default status, ticket_key = auto-generated
- On create: log activity "Ticket PROJ-001 created"

### Read Ticket
- Detail page loads: ticket metadata + description + comments + activity history + attachments
- Include related tickets: siblings (same parent), children (if epic), parent (if sub-task)
- Show watchers list

### Update Ticket
- Inline editing for: assignee, priority, status, due date, story points
- Full edit for: summary, description, issue type
- Every field change logs an activity entry with old_value and new_value
- Updating status to a "done" category sets resolved_at timestamp

### Delete Ticket
- Soft delete only: set status to deleted or add deleted_at field
- Hard delete is admin-only and should be avoided
- Deleted tickets are hidden from normal views but searchable by admins

---

## 2.3 Status Workflow & Transitions

### Workflow Model
- Statuses are per-project, not global
- Each status has a category: `todo`, `inprogress`, `done`
- Categories drive dashboard metrics and sprint burndown
- No hard-coded workflow rules initially — any status can transition to any other
- Future enhancement: configurable transition rules (e.g., "In Review" can only go to "Done" or "In Progress")

### Transition Behavior
- When status changes, log a "transitioned" activity
- If new status category is `done`, set `resolved_at = NOW()`
- If old status was `done` and new is not, clear `resolved_at`
- Notify watchers of the transition
- Update board position if moved via drag-and-drop

---

## 2.4 Comments System

### Comment Types
- Public comments: visible to all project members
- Internal notes: visible only to admins/managers (flag: is_internal)
- Comments support rich text (basic HTML or markdown rendering)

### Comment Features
- Author name, avatar, timestamp
- Edit own comments (within time window, e.g., 15 minutes)
- Delete own comments (soft delete)
- @mentions: typing `@username` sends notification to that user
- Comment threading: reply to specific comments (Phase 5)

### Activity Integration
- Comments are stored in `ticket_comments` table
- Also logged in `ticket_activities` as "commented" action
- Activity stream shows both field changes and comments in chronological order

---

## 2.5 File Attachments

### Upload Handling
- Max file size: 10MB (configurable)
- Allowed types: images (png, jpg, gif), documents (pdf, doc, docx), text files
- Store files on disk (or S3 in production), save path in database
- Generate thumbnails for images
- Virus scan uploads (integrate ClamAV or similar in production)

### Attachment Display
- List attachments in ticket detail sidebar
- Click to preview images inline
- Download link for documents
- Show file size and upload date
- Delete attachment (uploader or admin only)

---

## 2.6 Activity Audit Trail

### What Gets Logged
| Action | Fields Tracked |
|--------|---------------|
| created | ticket_id, actor_id, action="created" |
| updated | field_name, old_value, new_value |
| transitioned | old status name → new status name |
| commented | comment body reference |
| assigned | old assignee → new assignee |
| attachment_added | filename |
| attachment_deleted | filename |

### Activity Display
- Chronological stream on ticket detail page
- Group rapid consecutive edits by same user within 5 minutes
- Show user avatar, name, action, timestamp
- Clickable links to referenced tickets
- Filter by action type (optional)

---

## 2.7 Basic Search

### Search Scope
- Full-text search on ticket summary and description
- Filter by: project, status, assignee, reporter, priority, issue type, sprint
- Sort by: created date, updated date, priority, due date

### Search UI
- Search bar in top navigation
- Advanced search panel with filter chips
- Results in table view with key, summary, status, assignee, updated date
- Pagination with 25/50/100 per page options

---

## 2.8 Ticket Detail Page UI

### Layout: Two-Column
**Left column (wider, ~66%):**
- Breadcrumb: Projects > Project Name > Ticket Key
- Ticket title (editable inline)
- Action buttons: Edit, Assign to Me, Watch, Delete
- Description (rich text editor or markdown)
- Activity stream (comments + field changes mixed)
- Add comment box

**Right column (narrower, ~33%):**
- Status dropdown (with color coding)
- Assignee dropdown (with user search)
- Priority dropdown
- Due date picker
- Story points input
- Time tracking bar (original vs spent)
- Labels (add/remove badges)
- Meta: created, updated, reporter
- Attachments list

### Inline Editing
- Click any field in the right sidebar to edit
- Auto-save on blur or explicit Save button
- Show loading spinner during save
- Toast notification on success/error

---

## 2.9 API Endpoints

### Ticket Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/tickets | Create ticket |
| GET | /api/tickets | List tickets (with filters) |
| GET | /api/tickets/{id} | Get ticket detail |
| PUT | /api/tickets/{id} | Update ticket |
| DELETE | /api/tickets/{id} | Soft delete |
| POST | /api/tickets/{id}/transition | Change status |
| POST | /api/tickets/{id}/comments | Add comment |
| GET | /api/tickets/{id}/comments | List comments |
| DELETE | /api/tickets/{id}/comments/{cid} | Delete comment |
| POST | /api/tickets/{id}/attachments | Upload file |
| GET | /api/tickets/{id}/activities | Get activity stream |

---

## Deliverables Checklist

- [ ] Ticket model with all fields and relationships
- [ ] Auto-generated ticket keys (PROJ-001 format)
- [ ] Ticket create form with all fields
- [ ] Ticket detail page with two-column layout
- [ ] Inline editing for sidebar fields (assignee, priority, status, etc.)
- [ ] Status workflow transitions with activity logging
- [ ] Comments system (public + internal notes)
- [ ] File attachments with upload and preview
- [ ] Activity audit trail (created, updated, transitioned, commented)
- [ ] Basic search with full-text and filters
- [ ] Soft delete for tickets
- [ ] All API endpoints implemented and tested

---

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Ticket key collisions under high concurrency | Use database sequence or SELECT FOR UPDATE on counter |
| Rich text editor adds heavy JS bundle | Start with simple textarea + markdown, upgrade to editor later |
| File uploads fill disk | Implement cleanup job for orphaned files, set quotas per project |
| Activity log grows unbounded | Archive old activities (> 1 year) to separate table or cold storage |
