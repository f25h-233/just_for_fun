@echo off
rem One-click launcher: galgame coding Phase 3.1 (multi-chapter task + workspace sandbox + rollback).
rem Double-click this file: plays the 5-chapter task directly (multiple choices, cast appears).
rem In-game: type r at any choice to roll back to an earlier choice point.
rem Custom games: python -m galgame_coding.cli "your task"  (--menu for sample tasks)
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================
echo   Galgame Coding - Phase 3.1 (multi-chapter task)
echo   now playing: 5-chapter Personal Task Management CLI
echo   input r at any choice to roll back
echo   output sandbox: galgame_coding/workspace/
echo ================================================
echo.
python -m galgame_coding.cli
echo.
pause
