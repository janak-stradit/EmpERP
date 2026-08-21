import re
from datetime import date
from typing import Annotated

from pydantic import AfterValidator, BaseModel, EmailStr, Field, model_validator

from app.models.employee import EmployeeStatus
from app.models.user import UserRole

ASSIGNABLE_EMPLOYEE_ROLES = (UserRole.EMPLOYEE, UserRole.HR)

GENDER_OPTIONS = {"male", "female", "non_binary", "undisclosed"}
BANK_ACCOUNT_TYPES = {"savings", "current"}

# Country code is optional so existing plain-digit values from before this
# validation was added (or the HR quick-create form) keep working.
_PHONE_PATTERN = re.compile(r"^(\+\d{1,4}\s?)?\d{6,14}$")
_ACCOUNT_NUMBER_PATTERN = re.compile(r"^\d{9,18}$")
_IFSC_PATTERN = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


def _validate_phone(value: str | None) -> str | None:
    if value is None:
        return value
    value = value.strip()
    if not _PHONE_PATTERN.match(value):
        raise ValueError("Phone must be a country code (e.g. +91) followed by 6-14 digits")
    return value


def _validate_account_number(value: str | None) -> str | None:
    if value is None:
        return value
    value = value.strip()
    if not _ACCOUNT_NUMBER_PATTERN.match(value):
        raise ValueError("Bank account number must be 9-18 digits")
    return value


def _validate_ifsc(value: str | None) -> str | None:
    if value is None:
        return value
    value = value.strip().upper()
    if not _IFSC_PATTERN.match(value):
        raise ValueError("IFSC code must look like AAAA0999999 (4 letters, a zero, 6 letters/digits)")
    return value


def _validate_gender(value: str | None) -> str | None:
    if value is None:
        return value
    value = value.strip().lower()
    if value not in GENDER_OPTIONS:
        raise ValueError(f"gender must be one of {sorted(GENDER_OPTIONS)}")
    return value


def _validate_bank_account_type(value: str | None) -> str | None:
    if value is None:
        return value
    value = value.strip().lower()
    if value not in BANK_ACCOUNT_TYPES:
        raise ValueError(f"bank_account_type must be one of {sorted(BANK_ACCOUNT_TYPES)}")
    return value


PhoneStr = Annotated[str | None, AfterValidator(_validate_phone)]
BankAccountNumberStr = Annotated[str | None, AfterValidator(_validate_account_number)]
IfscStr = Annotated[str | None, AfterValidator(_validate_ifsc)]
GenderStr = Annotated[str | None, AfterValidator(_validate_gender)]
BankAccountTypeStr = Annotated[str | None, AfterValidator(_validate_bank_account_type)]


class EmployeeCreate(BaseModel):
    email: EmailStr
    full_name: str
    initial_password: str = Field(min_length=8)
    role: UserRole = UserRole.EMPLOYEE
    department_id: int | None = None
    designation_id: int | None = None
    reporting_manager_id: int | None = None
    joining_date: date
    probation_end_date: date | None = None
    phone: PhoneStr = None
    personal_email: EmailStr | None = None
    date_of_birth: date | None = None
    gender: GenderStr = None
    address: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: PhoneStr = None
    emergency_contact_relation: str | None = None
    bank_account_number: BankAccountNumberStr = None
    bank_ifsc: IfscStr = None
    bank_name: str | None = None


class EmployeeSelfUpdate(BaseModel):
    phone: PhoneStr = None
    personal_email: EmailStr | None = None
    date_of_birth: date | None = None
    gender: GenderStr = None
    address: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: PhoneStr = None
    emergency_contact_relation: str | None = None
    bank_account_number: BankAccountNumberStr = None
    bank_ifsc: IfscStr = None
    bank_name: str | None = None
    bank_account_holder_name: str | None = None
    bank_branch_name: str | None = None
    bank_account_type: BankAccountTypeStr = None


class EmployeeAdminUpdate(EmployeeSelfUpdate):
    department_id: int | None = None
    designation_id: int | None = None
    reporting_manager_id: int | None = None
    probation_end_date: date | None = None
    status: EmployeeStatus | None = None
    role: UserRole | None = None


class EmployeeAccessUpdate(BaseModel):
    is_active: bool


class EmployeePasswordReset(BaseModel):
    new_password: str = Field(min_length=8, max_length=12)
    confirm_password: str = Field(min_length=8, max_length=12)

    @model_validator(mode="after")
    def validate_matching_passwords(self) -> "EmployeePasswordReset":
        if self.new_password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self


class ModuleAccessUpdate(BaseModel):
    # None clears the override and reverts the employee to standard role-based access.
    modules: list[str] | None = None


class EmployeeDirectoryItem(BaseModel):
    id: int
    employee_code: str
    full_name: str

    model_config = {"from_attributes": True}


class EmployeeListItem(BaseModel):
    id: int
    employee_code: str
    full_name: str
    email: str
    role: UserRole
    department_id: int | None
    designation_id: int | None
    status: EmployeeStatus
    is_active: bool
    is_manager: bool
    joining_date: date

    model_config = {"from_attributes": True}


class EmployeeDetail(BaseModel):
    id: int
    user_id: int
    company_id: int
    employee_code: str
    full_name: str
    email: str
    role: UserRole
    department_id: int | None
    designation_id: int | None
    reporting_manager_id: int | None
    reporting_manager_name: str | None
    is_manager: bool
    joining_date: date
    probation_end_date: date | None
    status: EmployeeStatus
    is_active: bool
    phone: str | None
    personal_email: str | None
    date_of_birth: date | None
    gender: str | None
    address: str | None
    emergency_contact_name: str | None
    emergency_contact_phone: str | None
    emergency_contact_relation: str | None
    bank_account_number: str | None
    bank_ifsc: str | None
    bank_name: str | None
    bank_account_holder_name: str | None
    bank_branch_name: str | None
    bank_account_type: str | None
    has_profile_photo: bool
    profile_completion_percent: int
    module_access: list[str] | None
    enabled_modules: list[str]
