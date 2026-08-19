from django.urls import path

from . import views
from . import chat_views

app_name = "help"

urlpatterns = [
    path("", views.help_index, name="index"),
    path("search/", views.help_search, name="search"),
    path("search.json", views.help_search_json, name="search_json"),
    path("chat/", chat_views.chat_message, name="chat"),
    path("chat/lead/", chat_views.chat_lead, name="chat_lead"),
    path("<slug:cat_slug>/<slug:art_slug>/", views.help_article, name="article"),
]
