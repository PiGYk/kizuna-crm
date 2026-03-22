from django.db import models
from django.conf import settings


class Client(models.Model):
    first_name = models.CharField('Ім\'я', max_length=100)
    last_name = models.CharField('Прізвище', max_length=100)
    phone = models.CharField('Телефон', max_length=20)
    email = models.EmailField('Email', blank=True)
    notes = models.TextField('Нотатки', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Клієнт'
        verbose_name_plural = 'Клієнти'
        ordering = ('last_name', 'first_name')

    def __str__(self):
        return f"{self.last_name} {self.first_name}"

    def full_name(self):
        return f"{self.last_name} {self.first_name}"


class Patient(models.Model):
    class Species(models.TextChoices):
        DOG = 'dog', 'Собака'
        CAT = 'cat', 'Кіт'
        RABBIT = 'rabbit', 'Кролик'
        BIRD = 'bird', 'Птах'
        REPTILE = 'reptile', 'Рептилія'
        OTHER = 'other', 'Інше'

    class Sex(models.TextChoices):
        MALE = 'male', 'Самець'
        FEMALE = 'female', 'Самиця'
        UNKNOWN = 'unknown', 'Невідомо'

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='patients', verbose_name='Власник')
    name = models.CharField('Кличка', max_length=100)
    species = models.CharField('Вид', max_length=20, choices=Species.choices, default=Species.DOG)
    breed = models.CharField('Порода', max_length=100, blank=True)
    sex = models.CharField('Стать', max_length=10, choices=Sex.choices, default=Sex.UNKNOWN)
    date_of_birth = models.DateField('Дата народження', null=True, blank=True)
    color = models.CharField('Масть/колір', max_length=100, blank=True)
    photo = models.ImageField('Фото', upload_to='patients/', null=True, blank=True)
    assigned_doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='patients',
        verbose_name='Лікар',
        limit_choices_to={'role__in': ['admin', 'doctor']},
    )
    notes = models.TextField('Нотатки', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Пацієнт'
        verbose_name_plural = 'Пацієнти'
        ordering = ('name',)

    def __str__(self):
        return f"{self.name} ({self.get_species_display()}) — {self.client}"

    def age_display(self):
        if not self.date_of_birth:
            return '—'
        from datetime import date
        today = date.today()
        years = today.year - self.date_of_birth.year - (
            (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
        )
        if years == 0:
            months = (today.year - self.date_of_birth.year) * 12 + today.month - self.date_of_birth.month
            return f"{months} міс."
        return f"{years} р."


class Visit(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='visits', verbose_name='Пацієнт')
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='visits',
        verbose_name='Лікар',
    )
    date = models.DateTimeField('Дата прийому')
    complaint = models.TextField('Скарги', blank=True)
    diagnosis = models.TextField('Діагноз', blank=True)
    treatment = models.TextField('Лікування', blank=True)
    notes = models.TextField('Нотатки', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Візит'
        verbose_name_plural = 'Візити'
        ordering = ('-date',)

    def __str__(self):
        return f"{self.patient.name} — {self.date:%d.%m.%Y}"


class Vaccine(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='vaccines', verbose_name='Пацієнт')
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='vaccines',
        verbose_name='Лікар',
    )
    name = models.CharField('Назва вакцини', max_length=200)
    date = models.DateField('Дата щеплення')
    next_date = models.DateField('Наступне щеплення', null=True, blank=True)
    batch_number = models.CharField('Серія', max_length=100, blank=True)
    notes = models.TextField('Нотатки', blank=True)

    class Meta:
        verbose_name = 'Вакцина'
        verbose_name_plural = 'Вакцини'
        ordering = ('-date',)

    def __str__(self):
        return f"{self.name} — {self.patient.name} ({self.date:%d.%m.%Y})"

    def is_overdue(self):
        from datetime import date
        return self.next_date and self.next_date < date.today()
