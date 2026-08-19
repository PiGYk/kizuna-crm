from django.urls import path

from . import views

app_name = "help"

urlpatterns = [
    path("", views.help_index, name="index"),
    path("search/", views.help_search, name="search"),
    path("search.json", views.help_search_json, name="search_json"),
    path("<slug:cat_slug>/<slug:art_slug>/", views.help_article, name="article"),
]
