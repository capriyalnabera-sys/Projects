' Silent launcher for the Stock Analyzer web server.
' Launches pythonw.exe (no console window) with the project as working dir.
' Used by the Windows Scheduled Task that fires on user logon.
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "B:\Stock Analyzer"
WshShell.Run """B:\Stock Analyzer\.venv\Scripts\pythonw.exe"" -m src.web", 0, False
Set WshShell = Nothing
