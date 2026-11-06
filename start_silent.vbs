On Error Resume Next
Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strDir

' Resolve Python executable
pythonPath = "C:\Python315\pythonw.exe"
If Not fso.FileExists(pythonPath) Then
    pythonPath = "C:\Users\maste\AppData\Local\Programs\Python\Python312\pythonw.exe"
End If
If Not fso.FileExists(pythonPath) Then
    pythonPath = "pythonw.exe"
End If

' Run Python OLED app completely hidden without any console window
cmd = chr(34) & pythonPath & chr(34) & " " & chr(34) & strDir & "\app.py" & chr(34)
WshShell.Run cmd, 0, False
