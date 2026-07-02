from .models import UserProfile


def get_pos_profile(user):
    return getattr(user, "pos_profile", None)


def profile_company(profile):
    if not profile:
        return None
    return profile.company or (profile.branch.company if profile.branch_id else None)


def user_active_branch(user):
    profile = get_pos_profile(user)
    return profile.branch if (profile and profile.branch_id) else None


def is_super_admin(user):
    if not user.is_authenticated:
        return False
    profile = get_pos_profile(user)
    return bool(
        user.is_superuser
        or (profile and profile.access_level == UserProfile.SUPER_ADMIN)
    )


def is_company_admin(user):
    if not user.is_authenticated:
        return False
    profile = get_pos_profile(user)
    return bool(
        is_super_admin(user)
        or (profile and profile.access_level == UserProfile.COMPANY_ADMIN)
    )


def is_branch_admin(user):
    if not user.is_authenticated:
        return False
    profile = get_pos_profile(user)
    return bool(
        is_company_admin(user)
        or (profile and profile.access_level == UserProfile.BRANCH_ADMIN)
    )


def user_can_access_branch(user, branch):
    if not user.is_authenticated or not branch:
        return False
    profile = get_pos_profile(user)
    if is_super_admin(user):
        return True
    if not profile:
        return False
    company = profile_company(profile)
    if profile.access_level == UserProfile.COMPANY_ADMIN:
        return bool(company and company.id == branch.company_id)
    return bool(profile.branch_id and profile.branch_id == branch.id)


def is_pos_admin(user):
    if not user.is_authenticated:
        return False
    profile = get_pos_profile(user)
    return bool(
        user.is_superuser
        or (profile and profile.access_level in [
            UserProfile.BRANCH_ADMIN,
            UserProfile.COMPANY_ADMIN,
            UserProfile.SUPER_ADMIN,
        ])
    )
