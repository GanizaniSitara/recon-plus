@echo off
title recon-plus
chcp 65001 >nul 2>&1
powershell -Command "python -m recon_plus %*"
