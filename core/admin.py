"""
Core Admin Module.
ModelAdmin classes have been modularized into their respective domain apps under apps/.
This file retains global admin customizations (branding/header).
"""
from django.contrib import admin

# Super Admin Custom Branding
admin.site.site_header = "لوحة السوبر أدمن"
admin.site.site_title = "لوحة السوبر أدمن"
admin.site.index_title = "لوحة السوبر أدمن"
