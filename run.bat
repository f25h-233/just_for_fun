@echo off
rem One-click launcher: galgame coding Phase 3 (text frontend + rollback).
rem Double-click this file, pick a task, make choices, watch the agent work.
rem In-game: type r to roll back to an earlier choice point.
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================
echo   Galgame Coding - Phase 3 (text frontend + rollback)
echo   pick a task, make choices, watch the story
echo   input r at any choice to roll back
echo ================================================
echo.
python -m galgame_coding.cli --menu
echo.
pause
