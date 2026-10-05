' Silent Launcher for Power & Memory Sentry (Windows 10)
' Runs pythonw.exe completely in the background without any flashing black CMD window.

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")
strDir = objFSO.GetParentFolderName(WScript.ScriptFullName)

' Run pythonw with hidden window (0)
objShell.CurrentDirectory = strDir
objShell.Run "pythonw.exe """ & strDir & "\widget.py""", 0, False
