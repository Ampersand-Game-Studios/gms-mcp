@echo off
REM Project-local wrapper for GMS Tools
REM Usage from repo root: .\cli\gms.bat --help
setlocal
set "REPO_ROOT=%~dp0.."
set "PYTHONPATH=%REPO_ROOT%\\src;%PYTHONPATH%"
python -m gms_helpers.gms %*









