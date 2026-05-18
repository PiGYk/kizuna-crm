import time
import requests
from django.core.management.base import BaseCommand
from apps.tg.models import TelegramChat
from apps.tg.views import _get_token


class Command(BaseCommand):
    help = 'Завантажує аватарки для всіх Telegram-чатів без avatar_file_id'

    def handle(self, *args, **options):
        chats = TelegramChat.objects.filter(avatar_file_id='')
        total = chats.count()
        self.stdout.write(f'Чатів без аватарки: {total}')

        updated = 0
        failed = 0

        for chat in chats.iterator():
            token = _get_token(chat.organization)
            try:
                resp = requests.get(
                    f'https://api.telegram.org/bot{token}/getUserProfilePhotos',
                    params={'user_id': chat.tg_user_id, 'limit': 1},
                    timeout=10,
                ).json()
                photos = resp.get('result', {}).get('photos', [])
                if photos:
                    chat.avatar_file_id = photos[0][0]['file_id']  # найменший розмір
                    chat.save(update_fields=['avatar_file_id'])
                    updated += 1
                    self.stdout.write(f'  ✓ {chat.display_name}')
                else:
                    failed += 1
                    self.stdout.write(f'  – {chat.display_name} (немає фото)')
            except Exception as e:
                failed += 1
                self.stdout.write(f'  ✗ {chat.display_name}: {e}')

            time.sleep(0.05)  # ~20 req/s, щоб не флудити API

        self.stdout.write(self.style.SUCCESS(
            f'\nГотово. Оновлено: {updated}, без фото: {failed}'
        ))
