from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin
from app.db.session import get_db
from app.employees import service
from app.models.employee import (
    Employee, EmployeeDepartmentAssignment, EmployeeRoleAssignment, EmployeeStatus,
)
from app.models.user import User
from app.schemas.employee import (
    AssignmentEnd, DepartmentAssignmentRead, EmployeeCreate,
    EmployeeDepartmentAssignmentCreate, EmployeeDismiss, EmployeeReactivate,
    EmployeeRead, EmployeeRoleAssignmentCreate, EmployeeUpdate,
    EmployeeUserLink, EmployeeUserUnlink, RoleAssignmentRead,
)


router = APIRouter(prefix="/employees", tags=["employees"])


def employee_read(db: Session, employee: Employee) -> EmployeeRead:
    result = EmployeeRead.model_validate(employee)
    result.linked_user_id = service.linked_user_id(db, employee.id, employee.tenant_id)
    return result


@router.post("", response_model=EmployeeRead, status_code=status.HTTP_201_CREATED)
def create_employee(
    payload: EmployeeCreate,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> EmployeeRead:
    return employee_read(db, service.create_employee(db, payload, current_admin))


@router.get("", response_model=list[EmployeeRead])
def list_employees(
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
    employee_status: Annotated[EmployeeStatus | None, Query(alias="status")] = None,
) -> list[EmployeeRead]:
    query = service._employee_query(current_admin.tenant_id).order_by(Employee.full_name, Employee.id)
    if employee_status is not None:
        query = query.where(Employee.status == employee_status)
    return [employee_read(db, item) for item in db.scalars(query).all()]


@router.get("/{employee_id}", response_model=EmployeeRead)
def get_employee(
    employee_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> EmployeeRead:
    return employee_read(db, service.get_employee(db, employee_id, current_admin.tenant_id))


@router.patch("/{employee_id}", response_model=EmployeeRead)
def update_employee(
    employee_id: UUID, payload: EmployeeUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> EmployeeRead:
    employee = service.get_employee(db, employee_id, current_admin.tenant_id, lock=True)
    return employee_read(db, service.update_employee(db, employee, payload, current_admin))


@router.post("/{employee_id}/roles", response_model=RoleAssignmentRead, status_code=201)
def assign_role(
    employee_id: UUID, payload: EmployeeRoleAssignmentCreate,
    db: Annotated[Session, Depends(get_db)], current_admin: Annotated[User, Depends(get_current_admin)],
):
    employee = service.get_employee(db, employee_id, current_admin.tenant_id, lock=True)
    return service.assign_role(db, employee, payload, current_admin)


@router.post("/{employee_id}/roles/{assignment_id}/end", response_model=RoleAssignmentRead)
def end_role_assignment(
    employee_id: UUID, assignment_id: UUID, payload: AssignmentEnd,
    db: Annotated[Session, Depends(get_db)], current_admin: Annotated[User, Depends(get_current_admin)],
):
    service.get_employee(db, employee_id, current_admin.tenant_id, lock=True)
    assignment = db.scalar(select(EmployeeRoleAssignment).where(
        EmployeeRoleAssignment.id == assignment_id,
        EmployeeRoleAssignment.employee_id == employee_id,
        EmployeeRoleAssignment.tenant_id == current_admin.tenant_id,
    ).with_for_update())
    return service.end_assignment(db, assignment, payload, current_admin)


@router.post("/{employee_id}/departments", response_model=DepartmentAssignmentRead, status_code=201)
def assign_department(
    employee_id: UUID, payload: EmployeeDepartmentAssignmentCreate,
    db: Annotated[Session, Depends(get_db)], current_admin: Annotated[User, Depends(get_current_admin)],
):
    employee = service.get_employee(db, employee_id, current_admin.tenant_id, lock=True)
    return service.assign_department(db, employee, payload, current_admin)


@router.post("/{employee_id}/departments/{assignment_id}/end", response_model=DepartmentAssignmentRead)
def end_department_assignment(
    employee_id: UUID, assignment_id: UUID, payload: AssignmentEnd,
    db: Annotated[Session, Depends(get_db)], current_admin: Annotated[User, Depends(get_current_admin)],
):
    service.get_employee(db, employee_id, current_admin.tenant_id, lock=True)
    assignment = db.scalar(select(EmployeeDepartmentAssignment).where(
        EmployeeDepartmentAssignment.id == assignment_id,
        EmployeeDepartmentAssignment.employee_id == employee_id,
        EmployeeDepartmentAssignment.tenant_id == current_admin.tenant_id,
    ).with_for_update())
    return service.end_assignment(db, assignment, payload, current_admin)


@router.post("/{employee_id}/dismiss", response_model=EmployeeRead)
def dismiss_employee(
    employee_id: UUID, payload: EmployeeDismiss,
    db: Annotated[Session, Depends(get_db)], current_admin: Annotated[User, Depends(get_current_admin)],
) -> EmployeeRead:
    employee = service.get_employee(db, employee_id, current_admin.tenant_id, lock=True)
    return employee_read(db, service.dismiss_employee(db, employee, payload, current_admin))


@router.post("/{employee_id}/reactivate", response_model=EmployeeRead)
def reactivate_employee(
    employee_id: UUID, payload: EmployeeReactivate,
    db: Annotated[Session, Depends(get_db)], current_admin: Annotated[User, Depends(get_current_admin)],
) -> EmployeeRead:
    employee = service.get_employee(db, employee_id, current_admin.tenant_id, lock=True)
    return employee_read(db, service.reactivate_employee(db, employee, payload, current_admin))


@router.post("/{employee_id}/user", response_model=EmployeeRead)
def link_user(
    employee_id: UUID, payload: EmployeeUserLink,
    db: Annotated[Session, Depends(get_db)], current_admin: Annotated[User, Depends(get_current_admin)],
) -> EmployeeRead:
    employee = service.get_employee(db, employee_id, current_admin.tenant_id, lock=True)
    return employee_read(db, service.link_user(db, employee, payload.user_id, payload.reason, current_admin))


@router.post("/{employee_id}/user/unlink", response_model=EmployeeRead)
def unlink_user(
    employee_id: UUID, payload: EmployeeUserUnlink,
    db: Annotated[Session, Depends(get_db)], current_admin: Annotated[User, Depends(get_current_admin)],
) -> EmployeeRead:
    employee = service.get_employee(db, employee_id, current_admin.tenant_id, lock=True)
    return employee_read(db, service.unlink_user(db, employee, payload.reason, current_admin))
