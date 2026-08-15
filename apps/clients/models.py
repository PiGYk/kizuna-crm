from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from apps.clinic.managers import OrgManager, RelatedOrgManager
from apps.clinic.uploads import patient_photo_path, analysis_image_path


class Client(models.Model):
    first_name = models.CharField('Ім\'я', max_length=100)
    last_name = models.CharField('Прізвище', max_length=100)
    phone = models.CharField('Телефон', max_length=20, db_index=True)
    email = models.EmailField('Email', blank=True)
    notes = models.TextField('Нотатки', blank=True)
    discount_percent = models.DecimalField(
        'Знижка, %', max_digits=5, decimal_places=2, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text='Персональна знижка клієнта (0–100)'
    )
    organization = models.ForeignKey(
        'clinic.Organization',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='clients',
        verbose_name='Організація',
    )
    is_archived = models.BooleanField('Архівовано', default=False, db_index=True)
    archived_at = models.DateTimeField('Дата архівування', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrgManager()

    class Meta:
        verbose_name = 'Клієнт'
        verbose_name_plural = 'Клієнти'
        ordering = ('last_name', 'first_name')
        indexes = [
            models.Index(fields=['organization', 'is_archived', 'last_name'], name='client_org_arch_lname_idx'),
        ]

    def __str__(self):
        return f"{self.last_name} {self.first_name}"

    def full_name(self):
        return f"{self.last_name} {self.first_name}"

    def archive(self):
        from django.utils import timezone
        self.is_archived = True
        self.archived_at = timezone.now()
        self.save(update_fields=['is_archived', 'archived_at'])
        # Каскад на пацієнтів
        self.patients.update(is_archived=True, archived_at=self.archived_at)


class Patient(models.Model):
    class Species(models.TextChoices):
        DOG = 'dog', 'Собака'
        CAT = 'cat', 'Кіт'
        RABBIT = 'rabbit', 'Кролик'
        BIRD = 'bird', 'Птах'
        HAMSTER = 'hamster', 'Хом\'як'
        GUINEA_PIG = 'guinea_pig', 'Морська свинка'
        FERRET = 'ferret', 'Тхір'
        CHINCHILLA = 'chinchilla', 'Шиншила'
        RAT = 'rat', 'Щур / Миша'
        TURTLE = 'turtle', 'Черепаха'
        REPTILE = 'reptile', 'Ящірка / Змія'
        FISH = 'fish', 'Риба'
        HEDGEHOG = 'hedgehog', 'Їжак'
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
    age = models.CharField('Вік', max_length=30, blank=True)
    is_neutered = models.BooleanField('Кастрований/стерилізований', default=False)
    color = models.CharField('Масть/колір', max_length=100, blank=True)
    photo = models.ImageField('Фото', upload_to=patient_photo_path, null=True, blank=True)
    assigned_doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='patients',
        verbose_name='Лікар',
        limit_choices_to={'role__in': ['admin', 'doctor']},
    )
    notes = models.TextField('Нотатки', blank=True)
    allergies = models.TextField('Алергії / хронічні', blank=True,
        help_text='Алергії на препарати, хронічні захворювання — видно на картці червоним')
    is_archived = models.BooleanField('Архівовано', default=False, db_index=True)
    archived_at = models.DateTimeField('Дата архівування', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = RelatedOrgManager('client__organization')

    class Meta:
        verbose_name = 'Пацієнт'
        verbose_name_plural = 'Пацієнти'
        ordering = ('name',)
        indexes = [
            models.Index(fields=['client', 'name'], name='patient_client_name_idx'),
            models.Index(fields=['species'], name='patient_species_idx'),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_species_display()}) — {self.client}"

    def archive(self):
        from django.utils import timezone
        self.is_archived = True
        self.archived_at = timezone.now()
        self.save(update_fields=['is_archived', 'archived_at'])

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.photo:
            self._compress_photo()

    def _compress_photo(self):
        from PIL import Image, ImageOps
        MAX_SIZE = 1200
        try:
            img = Image.open(self.photo.path)
        except Exception:
            return
        img = ImageOps.exif_transpose(img)
        if img.width <= MAX_SIZE and img.height <= MAX_SIZE:
            if img.mode in ('RGBA', 'P', 'LA'):
                img = img.convert('RGB')
            img.save(self.photo.path, 'JPEG', quality=82, optimize=True)
            return
        img.thumbnail((MAX_SIZE, MAX_SIZE), Image.LANCZOS)
        if img.mode in ('RGBA', 'P', 'LA'):
            img = img.convert('RGB')
        img.save(self.photo.path, 'JPEG', quality=82, optimize=True)

    def age_display(self):
        if self.age:
            return self.age
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
    follow_up_date = models.DateField('Контрольний візит', null=True, blank=True,
        help_text='Дата повторного огляду')
    created_at = models.DateTimeField(auto_now_add=True)

    objects = RelatedOrgManager('patient__client__organization')

    class Meta:
        verbose_name = 'Візит'
        verbose_name_plural = 'Візити'
        ordering = ('-date',)
        indexes = [
            models.Index(fields=['patient', '-date'], name='visit_patient_date_idx'),
            models.Index(fields=['date'], name='visit_date_idx'),
        ]

    def __str__(self):
        return f"{self.patient.name} — {self.date:%d.%m.%Y}"


class VisitTemplate(models.Model):
    """Шаблон для швидкого створення типового візиту."""
    name = models.CharField('Назва шаблону', max_length=200)
    complaint = models.TextField('Скарги', blank=True)
    diagnosis = models.TextField('Діагноз', blank=True)
    treatment = models.TextField('Лікування', blank=True)
    notes = models.TextField('Нотатки', blank=True)
    organization = models.ForeignKey(
        'clinic.Organization', on_delete=models.CASCADE,
        null=True, blank=True, related_name='visit_templates',
    )
    is_active = models.BooleanField('Активний', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrgManager()

    class Meta:
        verbose_name = 'Шаблон візиту'
        verbose_name_plural = 'Шаблони візитів'
        ordering = ('name',)

    def __str__(self):
        return self.name


class Prescription(models.Model):
    """Призначення лікаря після візиту."""
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name='prescriptions', verbose_name='Візит')
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='prescriptions', verbose_name='Пацієнт')
    medication = models.CharField('Препарат', max_length=200)
    dosage = models.CharField('Дозування', max_length=200)
    frequency = models.CharField('Частота', max_length=100, help_text='Наприклад: 2 рази на день')
    duration = models.CharField('Тривалість', max_length=100, help_text='Наприклад: 7 днів')
    notes = models.TextField('Примітки', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Призначення'
        verbose_name_plural = 'Призначення'
        ordering = ('-created_at',)

    def __str__(self):
        return f'{self.medication} — {self.patient.name}'


class PatientAnalysis(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='analyses', verbose_name='Пацієнт')
    title = models.CharField('Назва', max_length=200)
    image = models.FileField('Файл', upload_to=analysis_image_path)
    date = models.DateField('Дата')
    notes = models.TextField('Нотатки', blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name='Завантажив',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = RelatedOrgManager('patient__client__organization')

    class Meta:
        verbose_name = 'Аналіз'
        verbose_name_plural = 'Аналізи'
        ordering = ('-date',)

    def __str__(self):
        return f"{self.title} — {self.patient.name} ({self.date:%d.%m.%Y})"

    @property
    def is_image(self):
        if not self.image:
            return False
        import os
        return os.path.splitext(self.image.name)[1].lower() in (
            '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.tif'
        )

    @property
    def is_pdf(self):
        if not self.image:
            return False
        import os
        return os.path.splitext(self.image.name)[1].lower() == '.pdf'

    @property
    def file_icon(self):
        if not self.image:
            return '📎'
        import os
        ext = os.path.splitext(self.image.name)[1].lower()
        if ext in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'):
            return '🖼'
        if ext == '.pdf':
            return '📄'
        if ext in ('.doc', '.docx'):
            return '📝'
        if ext in ('.xls', '.xlsx'):
            return '📊'
        if ext in ('.mp4', '.mov', '.avi', '.mkv', '.webm', '.3gp'):
            return '🎬'
        return '📎'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.image and self.is_image:
            self._fix_orientation()

    def _fix_orientation(self):
        from PIL import Image, ImageOps
        MAX_SIZE = 2400
        try:
            img = Image.open(self.image.path)
        except Exception:
            return
        img = ImageOps.exif_transpose(img)
        if img.width > MAX_SIZE or img.height > MAX_SIZE:
            img.thumbnail((MAX_SIZE, MAX_SIZE), Image.LANCZOS)
        if img.mode in ('RGBA', 'P', 'LA'):
            img = img.convert('RGB')
        img.save(self.image.path, 'JPEG', quality=85, optimize=True)


def patient_document_path(instance, filename):
    return f'patients/{instance.patient.client_id}/{instance.patient_id}/docs/{filename}'


class PatientDocument(models.Model):
    """Документ пацієнта (PDF, відео, інші файли)."""
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='documents', verbose_name='Пацієнт')
    # Прив'язка до конкретного прийому — щоб знімок чи УЗД лежали не просто
    # в картці тварини, а в тому візиті, де їх зробили (прохання Ірпеня 10.08).
    # Порожнє — документ загальний по тварині, як було досі.
    visit = models.ForeignKey(
        'Visit', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='documents', verbose_name='Візит',
    )
    title = models.CharField('Назва', max_length=200)
    file = models.FileField('Файл', upload_to=patient_document_path)
    date = models.DateField('Дата')
    notes = models.TextField('Нотатки', blank=True)
    uploaded_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name='Завантажив',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = RelatedOrgManager('patient__client__organization')

    class Meta:
        verbose_name = 'Документ'
        verbose_name_plural = 'Документи'
        ordering = ('-date',)

    def __str__(self):
        return f'{self.title} — {self.patient.name}'

    @property
    def extension(self):
        import os
        return os.path.splitext(self.file.name)[1].lower()

    @property
    def is_image(self):
        return self.extension in ('.jpg', '.jpeg', '.png', '.webp', '.gif')

    @property
    def is_pdf(self):
        return self.extension == '.pdf'


from .models_health import HealthCheck  # noqa: E402, F401


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
    valid_until = models.DateField('Діє до', null=True, blank=True)
    batch_number = models.CharField('Серія', max_length=100, blank=True)
    notes = models.TextField('Нотатки', blank=True)
    reminder_sent = models.BooleanField('Нагадування відправлено', default=False)

    objects = RelatedOrgManager('patient__client__organization')

    class Meta:
        verbose_name = 'Вакцина'
        verbose_name_plural = 'Вакцини'
        ordering = ('-date',)
        indexes = [
            models.Index(fields=['patient'], name='vacc_patient_idx'),
            models.Index(fields=['next_date'], name='vacc_next_date_idx'),
            models.Index(fields=['valid_until'], name='vacc_valid_until_idx'),
        ]

    def __str__(self):
        return f"{self.name} — {self.patient.name} ({self.date:%d.%m.%Y})"

    def is_overdue(self):
        from datetime import date
        return self.next_date and self.next_date < date.today()

    # Скільки днів до кінця дії планувати повторне щеплення
    REVACCINATION_LEAD_DAYS = 14

    @staticmethod
    def _plus_one_year(d):
        """Та сама дата наступного року (29 лютого → 28 лютого)."""
        try:
            return d.replace(year=d.year + 1)
        except ValueError:
            return d.replace(year=d.year + 1, day=28)

    def save(self, *args, **kwargs):
        """Автодати щеплення, якщо їх не заповнили руками.

        «Діє до» — рівно рік від щеплення (термін захисту).
        «Наступне» — на два тижні раніше, щоб тварину привели ДО того, як
        захист скінчиться. Заповнене руками не чіпаємо. Прохання Ірпеня 10.08.
        """
        if self.date:
            if not self.valid_until:
                self.valid_until = self._plus_one_year(self.date)
            if not self.next_date:
                from datetime import timedelta
                # рахуємо саме від «діє до» — якщо лікар поставив свій термін
                # дії, повторне щеплення має триматись за нього, а не за дату
                # попереднього уколу
                self.next_date = (
                    self.valid_until - timedelta(days=self.REVACCINATION_LEAD_DAYS)
                )
        super().save(*args, **kwargs)


class Hospitalization(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'На стаціонарі'
        DISCHARGED = 'discharged', 'Виписаний'

    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE,
        related_name='hospitalizations', verbose_name='Пацієнт'
    )
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='hospitalizations', verbose_name='Лікар'
    )
    organization = models.ForeignKey(
        'clinic.Organization', on_delete=models.CASCADE,
        related_name='hospitalizations', verbose_name='Організація'
    )
    reason = models.TextField('Причина госпіталізації')
    diagnosis = models.TextField('Діагноз', blank=True)
    treatment = models.TextField('Призначення', blank=True)
    notes = models.TextField('Нотатки', blank=True)
    status = models.CharField(
        'Статус', max_length=20, choices=Status.choices, default=Status.ACTIVE
    )
    admitted_at = models.DateTimeField('Дата надходження', auto_now_add=True)
    discharged_at = models.DateTimeField('Дата виписки', null=True, blank=True)
    discharge_notes = models.TextField('Нотатки при виписці', blank=True)

    objects = RelatedOrgManager('patient__client__organization')

    class Meta:
        verbose_name = 'Госпіталізація'
        verbose_name_plural = 'Стаціонар'
        ordering = ('-admitted_at',)
        indexes = [
            models.Index(fields=['organization', 'status'], name='hosp_org_status_idx'),
        ]

    def __str__(self):
        return f"{self.patient.name} — {self.get_status_display()} ({self.admitted_at:%d.%m.%Y})"


class WeightRecord(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='weights', verbose_name='Пацієнт')
    date = models.DateField('Дата зважування')
    weight = models.DecimalField('Вага (кг)', max_digits=6, decimal_places=2)
    notes = models.CharField('Нотатки', max_length=200, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name='Хто зважував',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = RelatedOrgManager('patient__client__organization')

    class Meta:
        verbose_name = 'Вага'
        verbose_name_plural = 'Записи ваги'
        ordering = ('date',)

    def __str__(self):
        return f"{self.patient.name} — {self.weight} кг ({self.date:%d.%m.%Y})"


class UltrasoundReport(models.Model):
    """Протокол УЗД черевної порожнини."""
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='ultrasounds', verbose_name='Пацієнт')
    visit = models.ForeignKey('Visit', on_delete=models.SET_NULL, null=True, blank=True, related_name='ultrasounds')
    doctor = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name='Лікар',
    )
    date = models.DateField('Дата дослідження')

    # ── Печінка ──
    liver_size = models.CharField('Розмір печінки', max_length=50, blank=True, help_text='Норма / збільшена / зменшена')
    liver_echogenicity = models.CharField('Ехогенність печінки', max_length=50, blank=True, help_text='Нормальна / підвищена / знижена / неоднорідна')
    liver_structure = models.CharField('Структура печінки', max_length=100, blank=True, help_text='Однорідна / неоднорідна, дифузні зміни')
    liver_vessels = models.CharField('Судини печінки', max_length=100, blank=True, help_text='Не розширені / розширені')
    liver_notes = models.TextField('Коментар (печінка)', blank=True)

    # ── Жовчний міхур ──
    gallbladder_size = models.CharField('Розмір ЖМ', max_length=50, blank=True, help_text='Довжина × ширина мм')
    gallbladder_wall = models.CharField('Стінка ЖМ', max_length=50, blank=True, help_text='Не потовщена / потовщена до ___ мм')
    gallbladder_content = models.CharField('Вміст ЖМ', max_length=100, blank=True, help_text='Анехогенний / сладж / конкременти')
    gallbladder_notes = models.TextField('Коментар (ЖМ)', blank=True)

    # ── Селезінка ──
    spleen_size = models.CharField('Розмір селезінки', max_length=50, blank=True, help_text='Норма / збільшена')
    spleen_echogenicity = models.CharField('Ехогенність селезінки', max_length=50, blank=True)
    spleen_structure = models.CharField('Структура селезінки', max_length=100, blank=True)
    spleen_notes = models.TextField('Коментар (селезінка)', blank=True)

    # ── Нирки ──
    kidney_left_size = models.CharField('Ліва нирка розмір', max_length=50, blank=True, help_text='Довжина × ширина мм')
    kidney_left_cortex = models.CharField('Кірковий шар лівої', max_length=50, blank=True, help_text='мм')
    kidney_right_size = models.CharField('Права нирка розмір', max_length=50, blank=True, help_text='Довжина × ширина мм')
    kidney_right_cortex = models.CharField('Кірковий шар правої', max_length=50, blank=True, help_text='мм')
    kidney_echogenicity = models.CharField('Ехогенність нирок', max_length=50, blank=True)
    kidney_pelvis = models.CharField('Ниркова миска', max_length=100, blank=True, help_text='Не розширена / розширена до ___ мм')
    kidney_notes = models.TextField('Коментар (нирки)', blank=True)

    # ── Сечовий міхур ──
    bladder_filling = models.CharField('Наповнення СМ', max_length=50, blank=True, help_text='Помірне / достатнє / переповнений')
    bladder_wall = models.CharField('Стінка СМ', max_length=50, blank=True, help_text='Не потовщена / потовщена до ___ мм')
    bladder_content = models.CharField('Вміст СМ', max_length=100, blank=True, help_text='Анехогенний / осад / конкременти')
    bladder_notes = models.TextField('Коментар (СМ)', blank=True)

    # ── Шлунок / кишківник ──
    gi_notes = models.TextField('ШКТ', blank=True, help_text='Стінка, перистальтика, вміст, лімфовузли')

    # ── Матка / простата ──
    reproductive_notes = models.TextField('Репродуктивна система', blank=True, help_text='Матка / простата / яєчники')

    # ── Вільна рідина ──
    free_fluid = models.CharField('Вільна рідина', max_length=100, blank=True, help_text='Відсутня / присутня (локалізація, об\'єм)')

    # ── Висновок ──
    conclusion = models.TextField('Висновок', blank=True)
    recommendations = models.TextField('Рекомендації', blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    objects = RelatedOrgManager('patient__client__organization')

    class Meta:
        ordering = ['-date']
        verbose_name = 'Протокол УЗД'
        verbose_name_plural = 'Протоколи УЗД'

    def __str__(self):
        return f'УЗД {self.patient.name} — {self.date:%d.%m.%Y}'
