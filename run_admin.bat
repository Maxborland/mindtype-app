@echo off
:: Запуск приложения с правами администратора
powershell -Command "Start-Process powershell -ArgumentList '-ExecutionPolicy Bypass -File \"%~dp0run_admin.ps1\"' -Verb RunAs"









