"""
Usage:
  python manage.py create_pos_user
  python manage.py create_pos_user --username john --password pass123 --role cashier --branch 2
  python manage.py create_pos_user --username john --password pass123 --role cashier --branch 2 --pin 1234

Multiple users named "john" can exist in different companies when --username sets
the per-company display name (pos_username). The Django auth username is auto-generated
as co{company_id}_{username} to stay globally unique.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError

from pos.models import Branch, UserProfile


ROLES = [r[0] for r in UserProfile.ROLE_CHOICES]
ACCESS_LEVELS = [a[0] for a in UserProfile.ACCESS_LEVEL_CHOICES]


class Command(BaseCommand):
    help = "Create a POS user (Django User + UserProfile) interactively or via flags."

    def add_arguments(self, parser):
        parser.add_argument("--username", help="Display username (unique per company / pos_username)")
        parser.add_argument("--password", help="Login password")
        parser.add_argument("--pin", default="", help="Optional PIN for PIN login")
        parser.add_argument(
            "--role",
            choices=ROLES,
            default=UserProfile.CASHIER,
            help=f"POS role ({', '.join(ROLES)}). Default: cashier",
        )
        parser.add_argument(
            "--access",
            dest="access_level",
            choices=ACCESS_LEVELS,
            default=UserProfile.BRANCH_STAFF,
            help=f"Access level ({', '.join(ACCESS_LEVELS)}). Default: branch_staff",
        )
        parser.add_argument("--branch", type=int, help="Branch ID (leave blank to pick interactively)")
        parser.add_argument("--superuser", action="store_true", help="Make a Django superuser with super_admin access")

    def handle(self, *args, **options):
        User = get_user_model()

        # --- username (pos_username) ---
        pos_username = options["username"]
        if not pos_username:
            pos_username = input("Username (display name within company): ").strip()
        if not pos_username:
            raise CommandError("Username is required.")

        # --- password ---
        password = options["password"]
        if not password:
            import getpass
            password = getpass.getpass("Password: ")
            confirm = getpass.getpass("Confirm password: ")
            if password != confirm:
                raise CommandError("Passwords do not match.")
        if not password:
            raise CommandError("Password is required.")

        # --- branch ---
        branch_id = options["branch"]
        if branch_id:
            branch = Branch.objects.filter(pk=branch_id, is_active=True).first()
            if not branch:
                raise CommandError(f"Branch {branch_id} not found or inactive.")
        else:
            branches = list(Branch.objects.select_related("company").filter(is_active=True))
            if not branches:
                raise CommandError("No active branches found. Create a branch first via /admin/.")
            self.stdout.write("\nAvailable branches:")
            for b in branches:
                self.stdout.write(f"  [{b.id}] {b.name} ({b.company.name})")
            picked = input("Branch ID: ").strip()
            branch = Branch.objects.filter(pk=picked, is_active=True).first()
            if not branch:
                raise CommandError(f"Branch {picked} not found.")

        company = branch.company

        # --- role / access ---
        role = options["role"]
        access_level = options["access_level"]
        if options["superuser"]:
            role = UserProfile.ADMIN
            access_level = UserProfile.SUPER_ADMIN

        # --- check pos_username uniqueness within company ---
        if UserProfile.objects.filter(company=company, pos_username=pos_username).exists():
            raise CommandError(f"A user with username '{pos_username}' already exists in {company.name}.")

        # --- generate a globally unique Django username ---
        django_username = f"co{company.id}_{pos_username}"[:150]
        if User.objects.filter(username=django_username).exists():
            raise CommandError(f"Django username '{django_username}' already taken.")

        # --- pin ---
        raw_pin = options["pin"]
        hashed_pin = make_password(raw_pin) if raw_pin else ""

        # --- create ---
        user = User.objects.create_user(
            username=django_username,
            password=password,
            is_superuser=options["superuser"],
            is_staff=options["superuser"],
        )
        profile = UserProfile.objects.create(
            user=user,
            pos_username=pos_username,
            role=role,
            access_level=access_level,
            branch=branch,
            company=company,
            pin=hashed_pin,
            is_active=True,
        )

        self.stdout.write(self.style.SUCCESS(
            f"\nCreated user '{pos_username}' in {company.name}"
            f"\n  Role        : {profile.role}"
            f"\n  Access level: {profile.access_level}"
            f"\n  Branch      : {branch.name} ({company.name})"
            f"\n  Django user : {django_username}"
            f"\n  PIN login   : {'yes' if raw_pin else 'no'}"
        ))
