# Kizuna CRM

Система управління ветеринарною клінікою.

## Стек
- Django + HTMX + Tailwind CSS
- PostgreSQL
- Docker + Nginx

## Запуск (dev)

```bash
cp .env.example .env
docker compose up --build
```

## Запуск (prod)

```bash
cp .env.example .env
# заповнити .env
docker compose -f docker-compose.prod.yml up -d --build
```
