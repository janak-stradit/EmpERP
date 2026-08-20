# Phase 3: Project & Board Management

## Overview
Transform ticket lists into visual boards. Build Kanban/Scrum boards, sprint planning, backlog management, and multiple view modes. This phase makes the tool visually useful for teams.

**Duration:** 3–4 weeks  
**Goal:** Kanban board with drag-and-drop, sprint planning, backlog, multiple views

---

## 3.1 Kanban Board

### Board Structure
- Horizontal columns = project statuses (To Do, In Progress, Done, etc.)
- Vertical cards = tickets, stacked within their status column
- Each column shows a count badge
- Columns are ordered by status.position
- Board is per-project

### Card Design
Each card displays:
- Ticket key (small, muted): PROJ-42
- Summary (truncated to 2 lines)
- Issue type badge (color-coded)
- Priority indicator (icon for high/critical)
- Assignee avatar (small circle)
- Story points badge (if set)
- Label chips (if any, max 2 visible)
- Due date warning (red if overdue)

### Drag & Drop Behavior
- Drag a card from one column to another = status transition
- Drop triggers API call: POST /api/tickets/{id}/transition
- On success: update column count badges, show toast
- On failure: card snaps back to original column, show error
- Visual feedback during drag: ghost card, drop zone highlight
- Use SortableJS library for cross-browser drag-and-drop

### Column Management
- Add new column button at the end
- Edit column name and color
- Reorder columns (drag column headers)
- Delete empty columns
- Column limits (WIP limits): show warning when count exceeds limit

### Swimlanes
- Horizontal grouping within columns
- Group by: assignee, epic, priority, issue type
- Each swimlane has a header with group name and count
- Collapsible swimlanes

---

## 3.2 Sprint Management

### Sprint Model
| Field | Purpose |
|-------|---------|
| name | Sprint 1, Sprint 2, etc. |
| goal | One-line sprint objective |
| status | future, active, completed, closed |
| start_date | Sprint start |
| end_date | Sprint end (typically 2 weeks) |

### Sprint Lifecycle
1. **Create Sprint**: Name, goal, dates. Status = future.
2. **Start Sprint**: Move status to active. Only one active sprint per project.
3. **During Sprint**: Tickets assigned to sprint appear on board. Track burndown.
4. **Complete Sprint**: Status = completed. Handle incomplete tickets:
   - Move to backlog
   - Move to next sprint
   - Keep in current sprint (extend)
5. **Close Sprint**: Status = closed. Archived for reporting.

### Sprint Board
- Same Kanban board, but filtered to sprint tickets only
- Backlog tickets hidden
- Show sprint goal banner at top
- Sprint stats bar: total points, completed points, days remaining

---

## 3.3 Backlog View

### Layout
- Vertical list of all tickets not in an active/future sprint
- Grouped by epic (optional)
- Each item shows: key, summary, issue type, priority, points, assignee
- Drag items to reorder priority
- Multi-select with checkboxes for bulk actions

### Backlog Actions
- Create ticket (adds to backlog)
- Move to sprint: drag to sprint section or select + "Move to Sprint"
- Start sprint: button to convert backlog into active sprint
- Quick filters: by issue type, priority, assignee, label

### Sprint Sections in Backlog
- Active sprint shown at top (collapsed by default)
- Future sprints shown below
- Backlog (unassigned) at bottom
- Drag tickets between sections to reassign sprints

---

## 3.4 View Switcher

### Available Views
| View | Description | Best For |
|------|-------------|----------|
| Board | Kanban columns | Daily standups, workflow tracking |
| List | Sortable table | Bulk actions, sorting, filtering |
| Calendar | Tickets by due date | Deadline management |
| Timeline | Gantt-style bars | Project planning, dependencies |

### View Persistence
- Remember user's last view per project
- Store preference in localStorage or user settings table
- Default view: Board

---

## 3.5 List View

### Table Columns
- Checkbox (bulk select)
- Ticket key (sortable)
- Summary (sortable)
- Issue type (filterable)
- Status (filterable)
- Priority (sortable)
- Assignee (filterable)
- Sprint (filterable)
- Story points (sortable)
- Due date (sortable)
- Updated (sortable)

### Bulk Actions
- Select multiple tickets → action bar appears
- Actions: change status, assign to user, add label, move to sprint, delete
- Confirmation modal for destructive actions

### Inline Quick Edit
- Double-click a cell to edit inline
- Status dropdown, assignee dropdown, priority dropdown
- Save on blur or Enter key

---

## 3.6 Calendar View

### Display
- Month view by default
- Tickets shown as events on their due date
- Color-coded by status or priority
- Click event to open ticket detail modal
- Drag event to change due date

### Navigation
- Previous/Next month buttons
- Today button
- Week view toggle

---

## 3.7 Board Filters & Quick Search

### Quick Filters (one-click toggles)
- My Issues: tickets assigned to current user
- Recently Updated: last 24 hours
- Done This Week: resolved in last 7 days
- Overdue: past due date, not done

### Text Search on Board
- Search bar filters cards in real-time
- Searches summary and ticket key
- Highlight matching text
- Show "X results" count

### Advanced Filter Panel
- Filter by: assignee, reporter, priority, issue type, status, sprint, label, date range
- Each filter is a multi-select dropdown
- Active filters shown as removable chips
- Save filter sets as "Views" (Phase 5)

---

## 3.8 API Endpoints

### Board Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/projects/{id}/board | Get board data (statuses + tickets) |
| POST | /api/tickets/{id}/position | Update card position within column |
| GET | /api/projects/{id}/backlog | Get backlog tickets |

### Sprint Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/projects/{id}/sprints | Create sprint |
| GET | /api/projects/{id}/sprints | List sprints |
| POST | /api/sprints/{id}/start | Start sprint |
| POST | /api/sprints/{id}/complete | Complete sprint |
| PUT | /api/sprints/{id} | Update sprint |
| DELETE | /api/sprints/{id} | Delete future sprint |
| POST | /api/tickets/{id}/sprint | Assign ticket to sprint |

---

## Deliverables Checklist

- [ ] Kanban board with drag-and-drop status transitions
- [ ] Ticket cards with key, summary, type, priority, assignee, points, labels
- [ ] Column management (add, edit, delete, reorder, WIP limits)
- [ ] Swimlanes (group by assignee, epic, priority)
- [ ] Sprint CRUD (create, start, complete, close)
- [ ] Backlog view with drag-to-sprint
- [ ] View switcher: Board / List / Calendar
- [ ] List view with sortable columns and bulk actions
- [ ] Calendar view with due-date events
- [ ] Quick filters (My Issues, Recently Updated, Done This Week, Overdue)
- [ ] Advanced filter panel with multi-select
- [ ] Real-time card count updates on transitions

---

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Drag-and-drop breaks on mobile | Provide touch-friendly alternative: dropdown status selector on mobile |
| Large boards (100+ tickets) slow down | Virtual scrolling or pagination within columns; load 20 at a time |
| Concurrent edits cause stale board state | Implement optimistic UI updates + SSE for real-time sync |
| Sprint dates overlap | Enforce validation: no two active sprints, future sprints must have start > end of previous |
