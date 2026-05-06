@echo off

REM Check if we should run empty folder removal
if "%1"=="remove-empty" (
    echo Running empty folder removal...

    REM fetch latest
    git pull

    REM Create a virtual env in a folder called "venv" if it doesn't exist
    if not exist venv (
        echo Creating virtual environment...
        py -m venv venv
    )

    REM Activate the virtual env
    call venv\Scripts\activate.bat

    REM Install required packages for the env
    python -m pip install -r requirements.txt

    REM Run empty folder removal
    if "%2"=="" (
        echo Error: Please provide a path to remove empty folders from
        echo Usage: run.bat remove-empty "C:\path\to\content\folder"
        exit /b 1
    )
    python -m cleanup_utilities.remove_empty_folders "%2"
    goto :eof
)

REM Normal GUI mode
REM fetch latest
git pull

REM Create a virtual env in a folder called "venv" if it doesn't exist
if not exist venv (
    echo Creating virtual environment...
    py -m venv venv
)

REM Activate the virtual env
call venv\Scripts\activate.bat

REM Install required packages for the env
python -m pip install -r requirements.txt

REM Run GUI
python -m app.main
