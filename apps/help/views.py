from django.http import Http404
from django.shortcuts import redirect, render

from . import content


def _base_ctx(active_cat=None, active_art=None):
    return {
        "help_tree": content.build_tree(),
        "active_cat": active_cat,
        "active_art": active_art,
    }


def help_index(request):
    """Головна довідки: ведемо на першу статтю першого розділу."""
    cat, art = content.first_article()
    if cat is None:
        return render(request, "help/empty.html", _base_ctx())
    return redirect("help:article", cat_slug=cat, art_slug=art)


def help_article(request, cat_slug, art_slug):
    data = content.render_article(cat_slug, art_slug)
    if data is None:
        raise Http404("Стаття довідки не знайдена")
    ctx = _base_ctx(cat_slug, art_slug)
    cat_title = next(
        (c["title"] for c in ctx["help_tree"] if c["slug"] == cat_slug), cat_slug
    )
    ctx.update({"article": data, "cat_title": cat_title})
    return render(request, "help/article.html", ctx)
