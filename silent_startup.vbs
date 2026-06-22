Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Get the directory of this VBScript file
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
batPath = scriptDir & "\run.bat"

' Run the batch file silently (window style 0 = hidden)
WshShell.Run Chr(34) & batPath & Chr(34), 0

Set WshShell = Nothing
Set fso = Nothing
