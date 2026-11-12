@echo off
rem Compile "Traducteur PDF.exe" : executable autonome (double-clic, sans console).
rem Un environnement virtuel dedie evite d'embarquer des bibliotheques inutiles.
cd /d "%~dp0"
set BUILD=%TEMP%\traducteur_pdf_build
if not exist "%BUILD%\venv\Scripts\python.exe" python -m venv "%BUILD%\venv"
"%BUILD%\venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
"%BUILD%\venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt pyinstaller
"%BUILD%\venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name "Traducteur PDF" ^
  --distpath "%~dp0" --workpath "%BUILD%\work" --specpath "%BUILD%" ^
  "%~dp0interface.pyw"
echo.
echo Termine : "%~dp0Traducteur PDF.exe"
pause
