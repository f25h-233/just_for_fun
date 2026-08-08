@echo off
rem One-click launcher: galgame coding Phase 3.1 (multi-chapter task + workspace sandbox + rollback).
rem Double-click this file: plays the 5-chapter task directly (multiple choices, cast appears).
rem In-game: type r at any choice to roll back to an earlier choice point.
rem Custom games: python -m galgame_coding.cli "你的任务"   (--menu 可选示例任务)
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================
echo   Galgame Coding - Phase 3.1 (multi-chapter task)
echo   now playing: 五章连播 个人任务管理 CLI
echo   input r at any choice to roll back
echo   output sandbox: galgame_coding/workspace/
echo ================================================
echo.
python -m galgame_coding.cli
echo.
pause
