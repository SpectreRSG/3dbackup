@echo off
rem Double-click this on Windows to build the .exe files yourself.
rem (You need Python installed for this step only - the finished .exe does not.)
python -m pip install --upgrade pyinstaller || goto :error
python packaging\build.py || goto :error
echo.
echo Finished! Your programs are in the "dist" folder.
explorer dist
pause
exit /b 0
:error
echo.
echo Something went wrong - see the messages above.
pause
exit /b 1
