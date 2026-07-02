from django.contrib.auth import get_user_model
from rest_framework import serializers

from ..models import Branch, Company, PermissionGroup, UserProfile
from ..permissions import get_pos_profile, is_super_admin, profile_company, user_can_access_branch
from ..rbac import ALL_PERMISSION_CODES, permissions_for_profile
from ._helpers import _request_user, _validate_branch_access


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    pin = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    company = serializers.IntegerField(required=False, allow_null=True)


class SwitchBranchSerializer(serializers.Serializer):
    """Body for POST /auth/switch-branch/ — admin posts the target branch ID."""
    branch = serializers.IntegerField()


class PermissionGroupSerializer(serializers.ModelSerializer):
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = PermissionGroup
        fields = ['id', 'company', 'name', 'description', 'permissions', 'member_count', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_member_count(self, obj):
        return obj.members.count()

    def validate_permissions(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Must be a list of permission codes.")
        invalid = sorted(set(value) - set(ALL_PERMISSION_CODES))
        if invalid:
            raise serializers.ValidationError(f"Unknown permission codes: {', '.join(invalid)}")
        return value


class UserProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username")
    first_name = serializers.CharField(source="user.first_name", required=False, allow_blank=True)
    last_name = serializers.CharField(source="user.last_name", required=False, allow_blank=True)
    email = serializers.EmailField(source="user.email", required=False, allow_blank=True)
    full_name = serializers.CharField(source="user.get_full_name", read_only=True)
    last_login = serializers.DateTimeField(source="user.last_login", read_only=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True, trim_whitespace=False)
    effective_permissions = serializers.SerializerMethodField()
    permission_groups = serializers.PrimaryKeyRelatedField(
        many=True, queryset=PermissionGroup.objects.all(), required=False
    )

    class Meta:
        model = UserProfile
        fields = (
            "id", "user", "username", "first_name", "last_name", "email", "full_name",
            "last_login", "password", "pin", "pos_username", "role", "access_level",
            "branch", "company", "custom_permissions", "use_custom_permissions",
            "permission_groups", "effective_permissions", "is_active", "created_at", "updated_at"
        )
        extra_kwargs = {
            "user": {"required": False},
            "pin": {"write_only": True, "required": False, "allow_blank": True},
            "pos_username": {"required": False, "allow_blank": True},
        }

    def get_effective_permissions(self, profile):
        perms = permissions_for_profile(profile)
        if profile.user.is_superuser or "*" in perms:
            return ALL_PERMISSION_CODES
        return perms

    def validate(self, attrs):
        branch = attrs.get("branch")
        company = attrs.get("company")
        if self.instance is None:
            required = {}
            if not attrs.get("role"):
                required["role"] = "Role is required when creating a user."
            if not attrs.get("access_level"):
                required["access_level"] = "Access level is required when creating a user."
            if not branch:
                required["branch"] = "Branch is required when creating a user."
            if required:
                raise serializers.ValidationError(required)
        if branch and company and branch.company_id != company.id:
            raise serializers.ValidationError({"branch": "Branch must belong to the selected company."})

        pos_username = attrs.get("pos_username", "")
        if pos_username:
            resolved_company = company or (branch.company if branch else None)
            if resolved_company:
                qs = UserProfile.objects.filter(company=resolved_company, pos_username=pos_username)
                if self.instance:
                    qs = qs.exclude(pk=self.instance.pk)
                if qs.exists():
                    raise serializers.ValidationError({"pos_username": "This username is already taken in this company."})

        user = _request_user(self.context)
        if not user or not user.is_authenticated:
            return attrs
        if branch and not user_can_access_branch(user, branch):
            raise serializers.ValidationError({"branch": "You do not have access to this branch."})
        if company and not is_super_admin(user):
            active_company = profile_company(get_pos_profile(user))
            if not active_company or company.id != active_company.id:
                raise serializers.ValidationError({"company": "You do not have access to this company."})
        custom_permissions = attrs.get("custom_permissions")
        if custom_permissions is not None:
            if not isinstance(custom_permissions, list):
                raise serializers.ValidationError({"custom_permissions": "Must be a list of permission codes."})
            invalid = sorted(set(custom_permissions) - set(ALL_PERMISSION_CODES))
            if invalid:
                raise serializers.ValidationError({"custom_permissions": f"Unknown permission codes: {', '.join(invalid)}"})
        return attrs

    def create(self, validated_data):
        from django.contrib.auth.hashers import make_password as _hash
        user_data = validated_data.pop("user", {})
        password = validated_data.pop("password", "")
        permission_groups_list = validated_data.pop("permission_groups", [])
        pin = validated_data.get("pin", "")
        if pin:
            validated_data["pin"] = _hash(pin)

        branch = validated_data.get("branch")
        if branch and not validated_data.get("company"):
            validated_data["company"] = branch.company
        company = validated_data.get("company")

        pos_username = validated_data.get("pos_username", "")
        display_username = user_data.get("username", "")

        if not display_username and not pos_username:
            raise serializers.ValidationError({"username": "Username is required."})

        user_model = get_user_model()

        if pos_username and company:
            django_username = f"co{company.id}_{pos_username}"[:150]
            if not display_username:
                user_data["username"] = django_username
        else:
            django_username = display_username
            if pos_username == "" and display_username:
                validated_data["pos_username"] = display_username

        if user_model.objects.filter(username=user_data.get("username", django_username)).exists():
            raise serializers.ValidationError({"username": "A user with this username already exists."})

        user = user_model(**user_data)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.is_active = validated_data.get("is_active", True)
        user.save()

        profile = UserProfile.objects.create(user=user, **validated_data)
        if permission_groups_list:
            profile.permission_groups.set(permission_groups_list)
        return profile

    def update(self, instance, validated_data):
        from django.contrib.auth.hashers import make_password as _hash
        user_data = validated_data.pop("user", None)
        password = validated_data.pop("password", None)
        permission_groups_list = validated_data.pop("permission_groups", None)
        pin = validated_data.get("pin", "")
        if pin:
            validated_data["pin"] = _hash(pin)
        elif "pin" in validated_data:
            validated_data.pop("pin")

        if user_data:
            username = user_data.get("username")
            if username and username != instance.user.username:
                user_model = get_user_model()
                if user_model.objects.filter(username=username).exclude(pk=instance.user_id).exists():
                    raise serializers.ValidationError({"username": "A user with this username already exists."})
            for field, value in user_data.items():
                setattr(instance.user, field, value)

        if password:
            instance.user.set_password(password)

        if user_data or password:
            instance.user.save()

        branch = validated_data.get("branch", instance.branch)
        if branch:
            validated_data["company"] = branch.company
        if "is_active" in validated_data:
            instance.user.is_active = validated_data["is_active"]
            instance.user.save(update_fields=["is_active"])

        instance = super().update(instance, validated_data)
        if permission_groups_list is not None:
            instance.permission_groups.set(permission_groups_list)
        return instance
