# Phase 4: Dashboard & Analytics

## Overview
Build visual dashboards that give teams and managers insight into progress, workload, and bottlenecks. Charts, KPI cards, and reports turn raw ticket data into actionable intelligence.

**Duration:** 2–3 weeks  
**Goal:** Dashboard with KPIs, charts, burndown, velocity, workload distribution

---

## 4.1 Dashboard Layout

### Page Structure
- Full-width container
- Top row: 4 KPI cards (Open, In Progress, Completed This Week, Overdue)
- Middle rows: Charts (2 per row)
- Bottom row: Widgets (My Tickets, Recent Activity)
- All sections are collapsible
- Responsive: stacks vertically on mobile

### Per-Project vs Global Dashboard
- Default: project-specific dashboard (current project context)
- Global dashboard (admin only): aggregates across all projects
- User can switch context via project selector

---

## 4.2 KPI Cards

### Card Design
- Left side: metric name + large number
- Right side: icon in a colored circle
- Bottom: trend indicator (up/down arrow + percentage vs last period)
- Color-coded border-left: primary (blue), warning (yellow), success (green), danger (red)

### Metrics
| Card | Value | Color | Icon |
|------|-------|-------|------|
| Open Tickets | Count of non-done tickets | Blue | Ticket |
| In Progress | Count of in-progress tickets | Yellow | Arrow repeat |
| Completed (This Week) | Done in last 7 days | Green | Check circle |
| Overdue | Past due date, not done | Red | Exclamation triangle |

### Trend Calculation
- Compare current value vs same metric 7 days ago
- Show percentage change
- Green arrow up = good (more completed), Red arrow up = bad (more overdue)

---

## 4.3 Charts

### Chart Library
- Use Chart.js (lightweight, Bootstrap-compatible)
- Alternative: ApexCharts for more interactive features
- All charts responsive and printable

### Status Distribution (Doughnut Chart)
- Segments = project statuses
- Colors = status colors
- Center text = total tickets
- Legend below
- Click segment to filter board by that status

### Sprint Burndown (Line Chart)
- X-axis: sprint days (dates)
- Y-axis: remaining story points
- Two lines:
  - Ideal: straight diagonal from total points to 0
  - Actual: daily remaining points based on tickets moved to done
- Only shown when a sprint is active
- Updates daily

### Team Velocity (Bar Chart)
- X-axis: last 6 completed sprints
- Y-axis: story points
- Two bars per sprint:
  - Committed (blue): total points at sprint start
  - Completed (green): points in done status at sprint end
- Average velocity line overlay
- Hover tooltip shows exact numbers

### Workload Distribution (Horizontal Bar Chart)
- X-axis: number of open tickets
- Y-axis: team member names
- Color intensity by ticket count
- Click bar to filter board by that assignee
- Shows unassigned count separately

### Ticket Creation Trend (Line Chart)
- X-axis: last 30 days
- Y-axis: tickets created per day
- Line smoothed with tension
- Show average line

### Resolution Time (Bar Chart)
- X-axis: time buckets (0-1 day, 1-3 days, 3-7 days, 7-14 days, 14+ days)
- Y-axis: number of tickets
- Helps identify slow resolution patterns

---

## 4.4 Widgets

### My Open Tickets
- List of tickets assigned to current user
- Columns: key, summary, status badge, due date
- Sorted by due date (overdue first)
- Limit to 10, with "View All" link
- Click opens ticket detail

### Recent Activity
- Stream of latest actions across project
- Shows: actor avatar + name, action, ticket key, time ago
- Actions: created, assigned, transitioned, commented
- Limit to 15 items
- Auto-refresh every 30 seconds (SSE or polling)

### Sprint Progress
- Mini progress bar: completed / total points
- Days remaining counter
- Tickets remaining count
- Only shown if active sprint exists

---

## 4.5 Reports

### Sprint Report (Auto-generated on sprint complete)
- Sprint name and dates
- Goal
- Committed vs completed points
- Tickets completed list
- Tickets not completed list (with reason)
- Average cycle time
- Team member contribution

### Burndown Report
- Exportable as PDF or image
- Includes ideal vs actual lines
- Sprint metadata

### Workload Report
- Table: member name, open tickets, in-progress, overdue, total points
- Export to CSV

---

## 4.6 Dashboard Data Service

### Query Patterns
- All metrics should be computed in a single service call per dashboard load
- Use SQL aggregation (COUNT, SUM, AVG) rather than Python loops
- Cache dashboard data for 5 minutes to reduce DB load
- Invalidate cache on ticket create/update/delete

### Performance
- Dashboard should load in < 2 seconds
- Use database indexes on: status_id, assignee_id, created_at, resolved_at
- Pre-compute heavy metrics in background (optional Phase 5)

---

## 4.7 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/dashboard/{project_id} | All dashboard data |
| GET | /api/dashboard/{project_id}/burndown | Burndown chart data |
| GET | /api/dashboard/{project_id}/velocity | Velocity chart data |
| GET | /api/reports/sprint/{sprint_id} | Sprint report |
| GET | /api/reports/workload | Workload report |

---

## Deliverables Checklist

- [ ] 4 KPI cards with trend indicators
- [ ] Status distribution doughnut chart
- [ ] Sprint burndown line chart (ideal vs actual)
- [ ] Team velocity bar chart (committed vs completed)
- [ ] Workload distribution horizontal bar chart
- [ ] Ticket creation trend line chart
- [ ] Resolution time distribution bar chart
- [ ] My Open Tickets widget
- [ ] Recent Activity widget with auto-refresh
- [ ] Sprint Progress mini widget
- [ ] Sprint completion report (auto-generated)
- [ ] Export reports to PDF/CSV
- [ ] Dashboard data cached for performance
- [ ] All charts responsive and printable

---

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Dashboard queries slow with large datasets | Add composite indexes, cache results, paginate widgets |
| Charts look different across browsers | Test Chart.js on Chrome, Firefox, Safari; use Canvas not SVG |
| Burndown data inaccurate if tickets added mid-sprint | Recalculate baseline when scope changes; show scope change events |
| Users want custom dashboards | Design dashboard as configurable widget grid (Phase 5) |
