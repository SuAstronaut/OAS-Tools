@echo off
chcp 65001 >nul
title OAS Excel Importer
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launcher.ps1"
if errorlevel 1 pause
