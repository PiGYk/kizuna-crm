"""Довідка Kizuna CRM — читання статей з файлів Markdown у каталозі help_content/.

Кожен розділ — тека виду ``NN-slug`` з файлами-статтями ``NN-slug.md``.
Людські назви й порядок беремо з YAML-подібного frontmatter на початку файлу:

    ---
    title: Ласкаво просимо
    order: 1
    ---
    # текст статті...

Опис самого розділу (назва, порядок) — у файлі ``_section.md`` тієї ж теки.
Тексти лежать у git і читаються нативно — той самий масив стане базою знань
для майбутнього чат-помічника.
"""
import re
from pathlib import Path

import markdown
from markdown.extensions.toc import slugify_unicode
from django.conf import settings

HELP_ROOT = Path(settings.BASE_DIR) / "help_content"

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_NUM_PREFIX_RE = re.compile(r"^\d+[-_.]*")


def _parse_frontmatter(text):
    """Повертає (meta: dict, body: str)."""
    meta = {}
    m = _FM_RE.match(text)
    if not m:
        return meta, text
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, val = line.split(":", 1)
        meta[key.strip().lower()] = val.strip().strip("\"'")
    return meta, text[m.end():]


def _slug_of(name):
    base = name[:-3] if name.endswith(".md") else name
    return _NUM_PREFIX_RE.sub("", base) or base


def _order_of(name, meta):
    if meta.get("order"):
        try:
            return int(meta["order"])
        except (TypeError, ValueError):
            pass
    m = re.match(r"^(\d+)", name)
    return int(m.group(1)) if m else 999


def _read(path):
    try:
        return path.read_text(encoding="utf-8").lstrip("﻿")
    except OSError:
        return ""


def build_tree():
    """Дерево довідки: [{slug,title,order,articles:[{slug,title,order}]}]."""
    tree = []
    if not HELP_ROOT.is_dir():
        return tree
    for cat_dir in sorted(HELP_ROOT.iterdir()):
        if not cat_dir.is_dir() or cat_dir.name.startswith("."):
            continue
        cat_slug = _slug_of(cat_dir.name)
        cat_title, cat_order = cat_slug, _order_of(cat_dir.name, {})
        section = cat_dir / "_section.md"
        if section.exists():
            meta, _ = _parse_frontmatter(_read(section))
            cat_title = meta.get("title", cat_slug)
            cat_order = _order_of(cat_dir.name, meta)
        articles = []
        for art in sorted(cat_dir.iterdir()):
            if art.name.startswith("_") or not art.name.endswith(".md"):
                continue
            meta, _ = _parse_frontmatter(_read(art))
            articles.append({
                "slug": _slug_of(art.name),
                "title": meta.get("title", _slug_of(art.name)),
                "order": _order_of(art.name, meta),
            })
        articles.sort(key=lambda a: (a["order"], a["title"]))
        tree.append({
            "slug": cat_slug,
            "title": cat_title,
            "order": cat_order,
            "articles": articles,
        })
    tree.sort(key=lambda c: (c["order"], c["title"]))
    return tree


def _find_file(cat_slug, art_slug):
    if not HELP_ROOT.is_dir():
        return None
    for cat_dir in HELP_ROOT.iterdir():
        if not cat_dir.is_dir() or _slug_of(cat_dir.name) != cat_slug:
            continue
        for art in cat_dir.iterdir():
            if art.name.startswith("_") or not art.name.endswith(".md"):
                continue
            if _slug_of(art.name) == art_slug:
                return art
    return None


def render_article(cat_slug, art_slug):
    """dict(title, html, toc) або None, якщо статті нема."""
    path = _find_file(cat_slug, art_slug)
    if path is None:
        return None
    meta, body = _parse_frontmatter(_read(path))
    md = markdown.Markdown(
        extensions=["extra", "toc", "sane_lists", "attr_list"],
        extension_configs={"toc": {"permalink": False, "toc_depth": "2-3", "slugify": slugify_unicode}},
    )
    html = md.convert(body)
    return {
        "title": meta.get("title", art_slug),
        "html": html,
        "toc": md.toc,
    }


def first_article():
    for cat in build_tree():
        if cat["articles"]:
            return cat["slug"], cat["articles"][0]["slug"]
    return None, None
