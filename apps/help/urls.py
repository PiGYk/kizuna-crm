from django.urls import path

from . import views

app_name = "help"

urlpatterns = [
    path("", views.help_index, name="index"),
    path("<slug:cat_slug>/<slug:art_slug>/", views.help_article, name="article"),
]
