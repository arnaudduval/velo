from django.contrib import admin
from .models import Col
from .activity import Activity

admin.site.register(Col)
admin.site.register(Activity)

