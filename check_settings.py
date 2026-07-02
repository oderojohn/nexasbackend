import os, sys
sys.path.insert(0, r'C:\Users\SERVER\Desktop\sms\backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from django.conf import settings
print("DATABASES:", settings.DATABASES)
print("NAME:", settings.DATABASES['default']['NAME'])
