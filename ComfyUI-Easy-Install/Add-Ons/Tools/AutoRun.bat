@Echo off&&cd /D %~dp0
Title 'Update Easy-Install Modules' v0.1.3 by ivo
:: Pixaroma Community Edition ::

:: Add a path just in case ::
for /f "delims=" %%G in ('cmd /c "where.exe git.exe 2>nul"') do (set "GIT_PATH=%%~dpG")
set "path=%GIT_PATH%;%windir%\System32;%windir%\System32\WindowsPowerShell\v1.0;%localappdata%\Microsoft\WindowsApps;%PATH%"

set "DIR_LVL=..\..\"
call :SET_COLORS
call :CHECK_FOLDER "ComfyUI-Easy-Install\Add-ons\Tools"
call :CHECK_INUSE "Start ComfyUI.bat"

:: get the parrent folder ::
set "AutoRun_dir=%cd%"
cd %DIR_LVL%
set "parent_dir=%cd%"
cd %AutoRun_dir%

:: Copying the images into the ComfyUI\input folder ::

if exist ".\Helper-CEI\*.jpeg" move ".\Helper-CEI\*.jpeg" "..\..\ComfyUI\input\" >nul 2>&1
if exist ".\Helper-CEI\*.jpg" move ".\Helper-CEI\*.jpg" "..\..\ComfyUI\input\" >nul 2>&1
if exist ".\Helper-CEI\*.png" move ".\Helper-CEI\*.png" "..\..\ComfyUI\input\" >nul 2>&1
if exist ".\Helper-CEI\*.mp3" move ".\Helper-CEI\*.mp3" "..\..\ComfyUI\input\" >nul 2>&1
if exist ".\Helper-CEI\*.mp4" move ".\Helper-CEI\*.mp4" "..\..\ComfyUI\input\" >nul 2>&1

:: Erase old SageAttention bat files ::
if exist ..\..\Add-Ons\SageAttention.bat del ..\..\Add-Ons\SageAttention.bat
if exist ..\..\Add-Ons\SageAttention3.bat del ..\..\Add-Ons\SageAttention3.bat
if exist "..\..\Add-Ons\Torch-Pack\Torch 2.10.0+cu130.bat" del "..\..\Add-Ons\Torch-Pack\Torch 2.10.0+cu130.bat"

:: Updating the bat files ::
if exist ".\Helper-CEI\Update ComfyUI and Nodes.bat" move ".\Helper-CEI\Update ComfyUI and Nodes.bat" "..\..\" >nul 2>&1
if exist ".\Helper-CEI\Update ComfyUI.bat" move ".\Helper-CEI\Update ComfyUI.bat" "..\..\" >nul 2>&1
if exist ".\Helper-CEI\Update Easy-Install.bat" move ".\Helper-CEI\Update Easy-Install.bat" "..\..\" >nul 2>&1
if NOT exist "..\..\Start ComfyUI.bat" move ".\Helper-CEI\Start ComfyUI.bat" "..\..\" >nul 2>&1

:: usage: call :create_shortcut bat ico lnk ::
REM call :create_shortcut "Start ComfyUI.bat" "ComfyUI-EZi.ico" "ComfyUI-EZi.lnk"
REM call :create_shortcut "ComfyUI\output" "ComfyUI-EZi-output.ico" "ComfyUI-EZi output.lnk"
REM call :create_shortcut "Start ComfyUI SageAttention.bat" "ComfyUI-Sage.ico" "ComfyUI-SA.lnk"
REM call :create_shortcut "Start ComfyUI FlashAttention.bat" "ComfyUI-Flash.ico" "ComfyUI-FA.lnk"

for /f "delims=" %%D in ('powershell -NoProfile -ExecutionPolicy Bypass -command "[Environment]::GetFolderPath('Desktop')"') do set "DESKTOP=%%D"
if exist ".\Helper-CEI\ComfyUI-EZi-Desktop.ico" if exist ".\Helper-CEI\ComfyUI-EZi.py" (
	echo %green%:::::: Creating desktop shortcut to%yellow% ComfyUI-EZi-Desktop%reset%
	powershell -NoProfile -ExecutionPolicy Bypass -command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%DESKTOP%\ComfyUI-EZi Desktop.lnk'); $s.TargetPath='%parent_dir%\python_embeded\pythonw.exe'; $s.Arguments=('\"{0}\"' -f '%AutoRun_dir%\Helper-CEI\ComfyUI-EZi.py'); $s.WorkingDirectory='%parent_dir%\'; $s.IconLocation='%AutoRun_dir%\Helper-CEI\ComfyUI-EZi-Desktop.ico'; $s.Save();"
)


:: Install new nodes ::
call :get_node https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler	seedvr2_videoupscaler
call :get_node https://github.com/chflame163/ComfyUI_LayerStyle			comfyui_layerstyle
call :get_node https://github.com/kijai/ComfyUI-WanAnimatePreprocess	ComfyUI-WanAnimatePreprocess
call :get_node https://github.com/yolain/ComfyUI-Easy-Sam3				comfyui-easy-sam3
call :get_node https://github.com/kijai/ComfyUI-SCAIL-Pose				ComfyUI-SCAIL-Pose
call :get_node https://github.com/kijai/ComfyUI-MelBandRoFormer			ComfyUI-MelBandRoFormer
call :get_node https://github.com/flybirdxx/ComfyUI-Qwen-TTS			qwen3-tts-comfyui
call :get_node https://github.com/Saganaki22/ComfyUI-FishAudioS2		ComfyUI-fish-audio-s2
call :get_node https://github.com/pixaroma/ComfyUI-Pixaroma				ComfyUI-Pixaroma

:: Postinstall
REM ..\..\python_embeded\python.exe -I -m uv pip uninstall pydantic pydantic-core --quiet
REM ..\..\python_embeded\python.exe -I -m uv pip install pydantic --no-cache --link-mode=copy --quiet
..\..\python_embeded\python.exe -I -m uv pip install pywebview --no-cache --quiet
..\..\python_embeded\python.exe -I -m uv pip install -r "%parent_dir%\ComfyUI\manager_requirements.txt" --no-cache --quiet

if exist ".\Add-DynamicVRAM.bat" del ".\Add-DynamicVRAM.bat"
REM if exist ".\Toggle-DynamicVRAM.bat" call ".\Toggle-DynamicVRAM.bat" -add

Title 'Update Easy-Install Modules' v0.1.1 by ivo

echo.
echo %green%::::::::::::::: %yellow%Installation/Updating SoX%green% :::::::::::::::%reset%
echo.
winget.exe install --id ChrisBagwell.SoX -e --accept-source-agreements --accept-package-agreements --silent
cd .\
echo.

:: Reset numpy to v1.26.4 ::
for /f "tokens=*" %%i in ('..\..\python_embeded\python.exe -c "import numpy; print(numpy.__version__)"') do set NUMPY_VERSION=%%i

if not "%NUMPY_VERSION%"=="1.26.4" (
	echo.
	echo %green%::::::::::::::: Restoring%yellow% Numpy v1.26.4 %green%:::::::::::::::%reset%
	echo.
	..\..\python_embeded\python.exe -I -m pip install --force-reinstall numpy==1.26.4 --no-deps --no-warn-script-location
)

:: Final Messages ::
echo.
echo %green%::::::::: Done. You can read what's new here: ::::::::::%reset%
echo %yellow%https://github.com/Tavris1/ComfyUI-Easy-Install/releases%reset%

REM (goto) 2>nul & (timeout /t 2 /nobreak >nul & del /f /q "%CD%\%~nx0" & echo. & echo %green%::::::::::::::::: Press any key to exit ::::::::::::::::%reset% & pause >nul & exit)

if not defined start goto SkipTime
for /f "delims=" %%i in ('powershell -NoProfile -ExecutionPolicy Bypass -command "$s=[datetime]::ParseExact('%start%','yyyy-MM-dd_HH:mm:ss',$null); $e=Get-Date; [math]::Truncate(($e-$s).TotalSeconds)"') do set diff=%%i
echo. & echo %green%::::::::::::::::: Total Running Time:%red% %diff% %green%seconds%reset%

:SkipTime
echo. & echo %green%::::::::::::::::: Press any key to exit ::::::::::::::::%reset% & pause >nul & exit

:: ================================ END ===========================

:create_shortcut

set "bat_name=%~1"
set "ico_name=%~2"
set "lnk_name=%~3"

:: Get real Desktop path ::
for /f "delims=" %%D in ('powershell -NoProfile -ExecutionPolicy Bypass -command "[Environment]::GetFolderPath('Desktop')"') do set "DESKTOP=%%D"
:: Create a shortcut on the desktop ::
if exist ".\Helper-CEI\%ico_name%" if exist "..\..\%bat_name%" (
	echo %green%:::::: Creating desktop shortcut to%yellow% %bat_name%%reset%
	powershell -NoProfile -ExecutionPolicy Bypass -command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%DESKTOP%\%lnk_name%'); $s.TargetPath='%parent_dir%\%bat_name%'; $s.WorkingDirectory='%parent_dir%\'; $s.IconLocation='%AutoRun_dir%\Helper-CEI\%ico_name%'; $s.Save();"
)

goto :eof


:: Install nodes ::
:get_node
set "git_url=%~1"
set "git_folder=%~2"

if exist "..\..\ComfyUI\custom_nodes\%git_folder%\" goto :eof
echo.
echo %green%::::::::::::::: Installing%yellow% %git_folder% %green%:::::::::::::::%reset%
echo.

cd "%parent_dir%"

git.exe clone %git_url% ComfyUI/custom_nodes/%git_folder%

setlocal enabledelayedexpansion
if exist ".\ComfyUI\custom_nodes\%git_folder%\requirements.txt" (
    for %%F in (".\ComfyUI\custom_nodes\%git_folder%\requirements.txt") do set filesize=%%~zF
    if not !filesize! equ 0 (
        .\python_embeded\python.exe -I -m uv pip install -r ".\ComfyUI\custom_nodes\%git_folder%\requirements.txt" --no-cache --link-mode=copy
    )
)

if exist ".\ComfyUI\custom_nodes\%git_folder%\install.py" (
    for %%F in (".\ComfyUI\custom_nodes\%git_folder%\install.py") do set filesize=%%~zF
    if not !filesize! equ 0 (
	.\python_embeded\python.exe -I ".\ComfyUI\custom_nodes\%git_folder%\install.py"
	)
)
endlocal

cd %AutoRun_dir%

goto :eof

:SET_COLORS
set warning=[33m
set    gray=[90m
set     red=[91m
set   green=[92m
set  yellow=[93m
set    blue=[94m
set magenta=[95m
set    cyan=[96m
set   white=[97m
set   reset=[0m
GOTO :EOF

:CHECK_INUSE
set "StartComfyUI=%DIR_LVL%%~1"
if exist %StartComfyUI% (
	set PORT=8188
	for /f %%A in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "([regex]::Match((Get-Content '%StartComfyUI%' -Raw), '--port\s+(\d+)')).Groups[1].Value"') do set PORT=%%A
	for /f %%A in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue) { 1 } else { 0 }"') do set INUSE=%%A
	if "%INUSE%"=="1" (
		echo.
		echo    %white%ComfyUI%reset% is already running on port %green%%PORT%%reset%. %white%Please close it first.%reset%
		echo.
		echo    %gray%Press any key to exit...%reset%&&pause>nul&&exit
)
)
GOTO :EOF

:CHECK_FOLDER
set "PYTHON_EXE="
set "PREF_FOLDER=%~1"

if exist "%DIR_LVL%python_embeded\python.exe" (set "PYTHON_EXE=%DIR_LVL%python_embeded\python.exe")

if "%PYTHON_EXE%"=="" (
	echo.
    echo    %green%Please run this file from the %yellow%%~1%green% folder.%reset%
	echo.
    echo    %gray%Press any key to exit...%reset%&Pause>nul
    exit
)
GOTO :EOF
