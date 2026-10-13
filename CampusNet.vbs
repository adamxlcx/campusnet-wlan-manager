' ===================================================================
'  CampusNet 启动器（完全隐藏控制台窗口）
'  用法：双击本文件即可（默认显示主界面）
'        wscript CampusNet.vbs --minimized   →  直接最小化到任务栏托盘
'  说明：优先使用项目内 .venv\Scripts\pythonw.exe，其次 venv，最后 PATH 里的 pythonw.exe
' ===================================================================
Option Explicit

Dim fso, shell, here, appPath, pythonw, args, i, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

here = fso.GetParentFolderName(WScript.ScriptFullName)
appPath = fso.BuildPath(here, "app.py")

pythonw = "pythonw.exe"
Dim candidates
candidates = Array(fso.BuildPath(here, ".venv\Scripts\pythonw.exe"), _
                   fso.BuildPath(here, "venv\Scripts\pythonw.exe"))
For i = 0 To UBound(candidates)
    If fso.FileExists(candidates(i)) Then
        pythonw = candidates(i)
        Exit For
    End If
Next

args = ""
For i = 0 To WScript.Arguments.Count - 1
    args = args & " " & Chr(34) & WScript.Arguments(i) & Chr(34)
Next

shell.CurrentDirectory = here
cmd = Chr(34) & pythonw & Chr(34) & " " & Chr(34) & appPath & Chr(34) & args
shell.Run cmd, 0, False
