import secrets

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.v1.attendance import router as attendance_router
from app.api.v1.auth import router as auth_router
from app.api.v1.departments import router as departments_router
from app.api.v1.designations import router as designations_router
from app.api.v1.documents import router as documents_router
from app.api.v1.employees import router as employees_router
from app.api.v1.kra import router as kra_router
from app.api.v1.leave import router as leave_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.onboarding import router as onboarding_router
from app.api.v1.pms import router as pms_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(title="Stradit Workforce API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    nonce = secrets.token_urlsafe(16)
    request.state.csp_nonce = nonce

    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}' https://cdn.jsdelivr.net https://code.jquery.com; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "font-src 'self' https://cdn.jsdelivr.net; "
        "connect-src 'self' https://cdn.jsdelivr.net; "
        "img-src 'self' data: blob:;"
    )
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/auth/login")


@app.get("/auth/login", response_class=HTMLResponse, tags=["system"])
def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "auth/login.html", {"csp_nonce": request.state.csp_nonce})


@app.get("/dashboard", response_class=HTMLResponse, tags=["system"])
def dashboard_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "dashboard.html", {"csp_nonce": request.state.csp_nonce})


@app.get("/hr/employees", response_class=HTMLResponse, tags=["system"])
def hr_employees_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "hr/employees.html", {"csp_nonce": request.state.csp_nonce})


@app.get("/hr/onboarding", response_class=HTMLResponse, tags=["system"])
def hr_onboarding_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "hr/onboarding.html", {"csp_nonce": request.state.csp_nonce})


@app.get("/hr/documents", response_class=HTMLResponse, tags=["system"])
def hr_documents_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "hr/documents.html", {"csp_nonce": request.state.csp_nonce})


@app.get("/hr/documents/employee/{employee_id}", response_class=HTMLResponse, tags=["system"])
def hr_document_detail_page(request: Request, employee_id: int) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "hr/document_detail.html", {"csp_nonce": request.state.csp_nonce, "employee_id": employee_id}
    )


@app.get("/hr/leave", response_class=HTMLResponse, tags=["system"])
def hr_leave_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "hr/leave.html", {"csp_nonce": request.state.csp_nonce})


@app.get("/hr/attendance", response_class=HTMLResponse, tags=["system"])
def hr_attendance_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "hr/attendance.html", {"csp_nonce": request.state.csp_nonce})


@app.get("/manager/team-leave", response_class=HTMLResponse, tags=["system"])
def manager_team_leave_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "manager/team_leave.html", {"csp_nonce": request.state.csp_nonce})


@app.get("/employee/profile", response_class=HTMLResponse, tags=["system"])
def employee_profile_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "employee/profile.html", {"csp_nonce": request.state.csp_nonce})


@app.get("/employee/documents", response_class=HTMLResponse, tags=["system"])
def employee_documents_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "employee/documents.html", {"csp_nonce": request.state.csp_nonce})


@app.get("/employee/leave", response_class=HTMLResponse, tags=["system"])
def employee_leave_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "employee/leave.html", {"csp_nonce": request.state.csp_nonce})


@app.get("/employee/attendance", response_class=HTMLResponse, tags=["system"])
def employee_attendance_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "employee/attendance.html", {"csp_nonce": request.state.csp_nonce})


@app.get("/employee/kra", response_class=HTMLResponse, tags=["system"])
def employee_kra_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "employee/kra.html", {"csp_nonce": request.state.csp_nonce})


@app.get("/health", tags=["system"])
def health_check():
    return {"status": "healthy", "service": "Stradit Workforce ERP"}


@app.get("/", response_class=HTMLResponse, tags=["system"])
def root_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "hr/kra.html", {"csp_nonce": request.state.csp_nonce})


@app.get("/hr/kra", response_class=HTMLResponse, tags=["system"])
def hr_kra_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "hr/kra.html", {"csp_nonce": request.state.csp_nonce})


@app.get("/employee/pms", response_class=HTMLResponse, tags=["system"])
def employee_pms_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "employee/pms.html", {"csp_nonce": request.state.csp_nonce})


@app.get("/hr/pms", response_class=HTMLResponse, tags=["system"])
def hr_pms_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "hr/pms.html", {"csp_nonce": request.state.csp_nonce})


app.include_router(auth_router, prefix="/api/v1")
app.include_router(departments_router, prefix="/api/v1")
app.include_router(designations_router, prefix="/api/v1")
app.include_router(employees_router, prefix="/api/v1")
app.include_router(onboarding_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")
app.include_router(leave_router, prefix="/api/v1")
app.include_router(attendance_router, prefix="/api/v1")
app.include_router(kra_router, prefix="/api/v1")
app.include_router(pms_router, prefix="/api/v1")
app.include_router(notifications_router, prefix="/api/v1")
