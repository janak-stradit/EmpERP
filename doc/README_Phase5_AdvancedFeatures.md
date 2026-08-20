# Phase 5: Advanced Features

## Overview
Polish the system with real-time features, advanced search, notifications, permissions, and extensibility. This phase transforms the tool from functional to professional.

**Duration:** 3–4 weeks  
**Goal:** Real-time updates, JQL search, notifications, permissions, custom fields, integrations

---

## 5.1 Real-Time Updates (SSE)

### Technology Choice
- Server-Sent Events (SSE) over WebSockets
- Why SSE: simpler, HTTP-based, auto-reconnects, works through most proxies
- One SSE connection per user, per browser tab
- Backend: Python generator yielding JSON events

### Events to Push
| Event | Trigger | Payload |
|-------|---------|---------|
| ticket_updated | Any ticket field change | ticket_id, field, old_val, new_val |
| ticket_transitioned | Status change | ticket_id, old_status, new_status |
| comment_added | New comment | ticket_id, comment_id, author |
| sprint_started | Sprint status change | sprint_id, project_id |
| mention | User @mentioned in comment | ticket_id, comment_id |

### Frontend Handling
- Listen to SSE stream on all ticketing pages
- On ticket_updated: refresh ticket detail if currently viewing
- On ticket_transitioned: move card on board if visible
- On comment_added: append comment to activity stream
- On mention: show toast notification + badge increment

### Fallback
- If SSE fails (e.g., proxy blocks it), fall back to 30-second polling
- Detect SSE failure and auto-switch

---

## 5.2 Notifications System

### Notification Types
| Type | Trigger |
|------|---------|
| assigned | Ticket assigned to you |
| mentioned | @username in comment |
| transitioned | Ticket you watch changes status |
| commented | New comment on watched ticket |
| sprint_started | Sprint you are member of starts |
| due_soon | Ticket due within 24 hours |

### Notification Delivery
- In-app: bell icon in navbar with unread count badge
- Dropdown panel showing last 10 notifications
- Mark all as read
- Click notification → navigate to ticket

### Notification UI
- Bell icon with red badge for unread count
- Dropdown: list with avatar, message, time ago, unread dot
- Group by date: Today, Yesterday, Earlier
- Infinite scroll for history

### Settings
- Per-user notification preferences
- Toggle each notification type on/off
- Toggle email notifications (future)

---

## 5.3 Advanced Search (JQL-like)

### Query Syntax
Inspired by Jira Query Language (JQL):

```
project = PROJ AND status = "In Progress"
assignee = currentUser() AND priority = High
sprint = "Sprint 1" AND created >= -7d
text ~ "bug fix"
project = PROJ AND (status = Done OR status = "In Review")
```

### Supported Operators
| Operator | Meaning | Example |
|----------|---------|---------|
| = | Equals | status = Done |
| != | Not equals | assignee != currentUser() |
| IN | In list | status IN (Done, "In Review") |
| ~ | Contains text | text ~ "crash" |
| >=, <=, >, < | Comparison | created >= -7d |
| AND, OR | Logic | status = Done AND priority = High |
| () | Grouping | (A OR B) AND C |

### Functions
| Function | Description |
|----------|-------------|
| currentUser() | Logged-in user |
| now() | Current timestamp |
| startOfDay(), endOfDay() | Day boundaries |
| startOfWeek(), endOfWeek() | Week boundaries |

### Search UI
- Search bar with autocomplete for field names
- Query builder mode: dropdowns for field, operator, value
- Recent searches saved
- Save search as "Filter" with name
- Results in list view with same columns as board list

---

## 5.4 Permission System

### Roles
| Role | Permissions |
|------|------------|
| Admin | Full access: create/delete projects, manage members, delete any ticket |
| Manager | Create tickets, edit any ticket in project, manage sprints, view reports |
| Developer | Create/edit own tickets, transition tickets, comment, upload files |
| Tester | Create bugs, transition to testing statuses, comment |
| Viewer | Read-only: view tickets, boards, dashboard |

### Permission Matrix
| Action | Admin | Manager | Developer | Tester | Viewer |
|--------|-------|---------|-----------|--------|--------|
| Create project | Yes | No | No | No | No |
| Delete project | Yes | No | No | No | No |
| Manage members | Yes | No | No | No | No |
| Create ticket | Yes | Yes | Yes | Yes | No |
| Edit any ticket | Yes | Yes | No | No | No |
| Edit own ticket | Yes | Yes | Yes | Yes | No |
| Delete ticket | Yes | Yes | No | No | No |
| Transition ticket | Yes | Yes | Yes | Yes | No |
| Manage sprints | Yes | Yes | No | No | No |
| View dashboard | Yes | Yes | Yes | Yes | Yes |
| Export reports | Yes | Yes | No | No | No |

### Implementation
- Decorator: `@require_permission('ticket:edit')`
- Check user's role in project_members table
- Admin bypasses all checks
- Return 403 Forbidden with clear message

---

## 5.5 Custom Fields

### Field Types
| Type | UI Widget | Storage |
|------|-----------|---------|
| Text | Single-line input | VARCHAR |
| Text Area | Multi-line textarea | TEXT |
| Number | Number input | INTEGER |
| Date | Date picker | DATE |
| Select | Dropdown | VARCHAR (selected option) |
| Multi-Select | Multi-dropdown | JSONB (array of values) |
| User | User search dropdown | INTEGER (user_id) |
| Checkbox | Toggle switch | BOOLEAN |
| URL | URL input | VARCHAR |

### Per-Project Configuration
- Admin creates custom fields per project
- Sets: name, type, required, options (for select types), position
- Fields appear on ticket create/edit forms
- Fields display on ticket detail sidebar
- Fields are searchable and filterable

### Database Design
- custom_fields table: project_id, name, type, options (JSONB), is_required, position
- ticket_custom_values table: ticket_id, custom_field_id, value (TEXT)
- Value stored as text and cast based on field_type

---

## 5.6 Watchers & Subscriptions

### Watching a Ticket
- Star/watch button on ticket detail
- Watchers receive notifications on: transitions, comments, assignments
- Unwatch to stop notifications
- Auto-watch: reporter and assignee are auto-watchers
- Show watcher count and avatars on ticket detail

### Watching a Project
- Watch entire project → notifications for all tickets
- Useful for project managers and stakeholders
- Unwatch project to reduce noise

---

## 5.7 Labels

### Label Management
- Create labels per project: name + color
- Colors: preset palette or custom hex
- Apply multiple labels to a ticket
- Labels shown as colored badges on cards and detail page
- Click label to filter board by that label
- Delete label removes it from all tickets

---

## 5.8 Time Tracking

### Log Work
- Button on ticket detail: "Log Work"
- Modal: time spent (hours/minutes), date, description
- Accumulates into time_spent field
- Updates remaining_estimate automatically
- Shows in activity stream

### Time Reports
- Per-project time report: member, total logged time, per-ticket breakdown
- Per-sprint time report: planned vs actual
- Export to CSV

---

## 5.9 API Integrations (Webhooks)

### Outgoing Webhooks
- Configure webhook URL per project
- Events: ticket_created, ticket_updated, ticket_transitioned, comment_added
- POST JSON payload to external URL
- Retry on failure (3 attempts)
- Log webhook deliveries

### Use Cases
- Slack notification on ticket creation
- GitHub issue sync
- CI/CD pipeline trigger on status change
- Email service integration

---

## 5.10 Data Export

### Export Formats
- CSV: tickets list with all fields
- JSON: full ticket data including comments and history
- PDF: sprint report, individual ticket summary

### Export Scope
- Current filter/view results
- Full project
- Date range

---

## Deliverables Checklist

- [ ] SSE real-time updates for ticket changes
- [ ] Notification system (in-app bell + dropdown)
- [ ] Notification preferences per user
- [ ] Advanced search with JQL-like syntax
- [ ] Query builder (dropdown-based search)
- [ ] Saved filters
- [ ] Role-based permission system (5 roles)
- [ ] Permission decorators on all routes
- [ ] Custom fields per project (8 types)
- [ ] Watchers (watch/unwatch tickets and projects)
- [ ] Labels with colors
- [ ] Time tracking (log work, reports)
- [ ] Outgoing webhooks
- [ ] Data export (CSV, JSON, PDF)
- [ ] Auto-reconnect SSE with polling fallback

---

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| SSE connections exhaust server resources | Limit to 1000 concurrent per worker; use Redis pub/sub for multi-worker setups |
| JQL parser becomes complex | Start with simple parser, use existing library if available, or build grammar-based parser |
| Custom fields slow down queries | Index custom field values, limit custom fields to 20 per project |
| Webhook delivery failures flood retry queue | Exponential backoff, max 3 retries, dead letter queue |
