"""Вхід за логіном АБО email (16.11.2026, ANVAR: «логин не помню»).

Скидання пароля просить email, а сторінка входу пускала лише за логіном. Після
скидання людина вводила пошту й отримувала «Невірний логін або пароль».

Стоїть у AUTHENTICATION_BACKENDS ПІСЛЯ ModelBackend: звичайний вхід за точним
логіном як був, сюди доходять лише ті спроби, яких ModelBackend не впізнав.
ModelBackend зі списку не прибирати: старі сесії зберігають його шлях, і без
нього викине всіх, хто зараз у системі.

Введене зводиться до ОДНОГО користувача, і лише потім перевіряється пароль,
без перебору кандидатів:
  1) логін точно;
  2) логін без огляду на регістр, якщо такий лише один (планшет сам пише
     першу літеру великою: «Anvar…» замість «anvar…»);
  3) email без огляду на регістр, якщо серед активних він рівно в одного.
Пошта, спільна для кількох акаунтів (демо-клініки), за поштою не пускає,
тільки за логіном.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class LoginOrEmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if username is None or password is None:
            return None
        user = self._resolve(UserModel, username.strip())
        if user is None:
            # Як у ModelBackend: хешуємо вхолосту, щоб за часом відповіді не можна
            # було вгадати, чи існує такий логін або пошта.
            UserModel().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    @staticmethod
    def _resolve(UserModel, ident):
        if not ident:
            return None
        users = UserModel._default_manager
        try:
            return users.get_by_natural_key(ident)
        except UserModel.DoesNotExist:
            pass
        same = list(users.filter(username__iexact=ident)[:2])
        if len(same) == 1:
            return same[0]
        if '@' in ident:
            by_mail = list(users.filter(email__iexact=ident, is_active=True)[:2])
            if len(by_mail) == 1:
                return by_mail[0]
        return None
