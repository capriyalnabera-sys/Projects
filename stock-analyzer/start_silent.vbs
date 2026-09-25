' Silent launcher for the Stock Analyzer web server.
' Launches pythonw.exe (no console window) from this script's own folder,
' so it works wherever the project is cloned. Useful for a Windows
' Scheduled Task that fires on user logon.
' NOTE: run run-web.bat once first - it creates .venv and installs deps.
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = here
WshShell.Run """" & here & "\.venv\Scripts\pythonw.exe"" -m src.web", 0, False
Set WshShell = Nothing
