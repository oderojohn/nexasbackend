from rest_framework import serializers

from ..permissions import user_can_access_branch


def _request_user(context):
    request = context.get("request") if context else None
    return request.user if request else None


def _validate_branch_access(context, branch):
    user = _request_user(context)
    if user and user.is_authenticated and user_can_access_branch(user, branch):
        return branch
    raise serializers.ValidationError({"branch": "You do not have access to this branch."})


def _validate_same_branch(value, branch, field_name):
    if value and branch and value.branch_id != branch.id:
        raise serializers.ValidationError({field_name: "Must belong to the selected branch."})
