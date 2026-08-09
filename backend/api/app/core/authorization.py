from app.models.user import User


def has_request_view_access(user: User) -> bool:
    """Single authorization seam for tenant-scoped request reads."""
    return user.is_admin or user.can_view_requests
