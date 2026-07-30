' Launches a PowerShell script with no visible window.
' Used by Windows Task Scheduler tasks so the scraper doesn't pop
' up a black console every 15 minutes while the user is working.
'
' Usage from a scheduled task action:
'   Program:   wscript.exe
'   Arguments: "C:\path\to\run-hidden.vbs" "C:\path\to\script.ps1"
'
' The second argument is the .ps1 file to run. Anything beyond that
' is forwarded to the script as its own arguments.

If WScript.Arguments.Count < 1 Then
    WScript.Quit 1
End If

script = WScript.Arguments(0)
extra  = ""
For i = 1 To WScript.Arguments.Count - 1
    extra = extra & " """ & WScript.Arguments(i) & """"
Next

cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & script & """" & extra

' Run: 0 = hidden window, True = wait for completion so the task
' scheduler sees the real exit code.
WScript.Quit CreateObject("Wscript.Shell").Run(cmd, 0, True)
