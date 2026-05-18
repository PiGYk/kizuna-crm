from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from . import views_payroll

app_name = 'accounts'

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(template_name='accounts/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('register/', views.register, name='register'),
    path('verify/<str:token>/', views.verify_email, name='verify_email'),
    path('verify/resend/', views.resend_verification, name='resend_verification'),

    # Password reset (Django built-in flow)
    path(
        'password-reset/',
        auth_views.PasswordResetView.as_view(
            template_name='accounts/password_reset_form.html',
            email_template_name='accounts/password_reset_email.html',
            subject_template_name='accounts/password_reset_subject.txt',
        ),
        name='password_reset',
    ),
    path(
        'password-reset/done/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='accounts/password_reset_done.html',
        ),
        name='password_reset_done',
    ),
    path(
        'reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='accounts/password_reset_confirm.html',
        ),
        name='password_reset_confirm',
    ),
    path(
        'reset/done/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='accounts/password_reset_complete.html',
        ),
        name='password_reset_complete',
    ),
    path('users/', views.UserListView.as_view(), name='users'),
    path('users/create/', views.UserCreateView.as_view(), name='user_create'),
    path('users/<int:pk>/edit/', views.UserUpdateView.as_view(), name='user_edit'),
    path('users/<int:pk>/password/', views.user_set_password, name='user_password'),

    # Shifts & Payroll
    path('shifts/', views_payroll.shift_list, name='shifts'),
    path('shifts/toggle/', views_payroll.shift_toggle, name='shift_toggle'),
    path('payroll/', views_payroll.payroll_list, name='payroll_list'),
    path('payroll/calculate/', views_payroll.payroll_calculate, name='payroll_calculate'),
    path('payroll/<int:pk>/', views_payroll.payroll_detail, name='payroll_detail'),
    path('payroll/<int:pk>/approve/', views_payroll.payroll_approve, name='payroll_approve'),
    path('payroll/<int:pk>/pay/', views_payroll.payroll_pay, name='payroll_pay'),
    path('payroll/<int:pk>/recalculate/', views_payroll.payroll_recalculate, name='payroll_recalculate'),
    path('payroll/<int:pk>/delete/', views_payroll.payroll_delete, name='payroll_delete'),
]
