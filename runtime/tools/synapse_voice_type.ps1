<#
synapse_voice_type.ps1

One-shot dictation for WSL users:
- Listen to the default Windows microphone
- Print the recognized text to stdout
- Optionally type the text into the currently focused window (e.g., Windows Terminal)
- Optionally press Enter after typing

This is intentionally dependency-light: it uses Windows' built-in System.Speech
and types via SendInput (Unicode) to avoid SendKeys escaping issues.
#>

[CmdletBinding()]
param(
  [string]$Culture = "en-US",
  [int]$InitialSilenceTimeoutSeconds = 5,
  [int]$EndSilenceTimeoutMilliseconds = 800,
  [switch]$TypeToActiveWindow,
  [switch]$PressEnter
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function New-Recognizer([string]$cultureName) {
  Add-Type -AssemblyName System.Speech
  $culture = [System.Globalization.CultureInfo]::GetCultureInfo($cultureName)
  $rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine($culture)
  $rec.SetInputToDefaultAudioDevice()
  $rec.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))
  $rec.InitialSilenceTimeout = [TimeSpan]::FromSeconds($InitialSilenceTimeoutSeconds)
  $rec.EndSilenceTimeout = [TimeSpan]::FromMilliseconds($EndSilenceTimeoutMilliseconds)
  $rec.EndSilenceTimeoutAmbiguous = [TimeSpan]::FromMilliseconds($EndSilenceTimeoutMilliseconds)
  return $rec
}

$cs = @"
using System;
using System.Runtime.InteropServices;

public static class SynapseSendInput {
  [StructLayout(LayoutKind.Sequential)]
  public struct INPUT {
    public uint type;
    public InputUnion U;
  }

  [StructLayout(LayoutKind.Explicit)]
  public struct InputUnion {
    [FieldOffset(0)] public KEYBDINPUT ki;
  }

  [StructLayout(LayoutKind.Sequential)]
  public struct KEYBDINPUT {
    public ushort wVk;
    public ushort wScan;
    public uint dwFlags;
    public uint time;
    public IntPtr dwExtraInfo;
  }

  [DllImport("user32.dll", SetLastError = true)]
  private static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);

  private const uint INPUT_KEYBOARD = 1;
  private const uint KEYEVENTF_KEYUP = 0x0002;
  private const uint KEYEVENTF_UNICODE = 0x0004;
  private const ushort VK_RETURN = 0x0D;

  public static void SendUnicodeString(string text) {
    if (text == null) text = "";
    var inputs = new INPUT[text.Length * 2];
    int idx = 0;
    foreach (char ch in text) {
      inputs[idx++] = new INPUT {
        type = INPUT_KEYBOARD,
        U = new InputUnion { ki = new KEYBDINPUT { wVk = 0, wScan = ch, dwFlags = KEYEVENTF_UNICODE } }
      };
      inputs[idx++] = new INPUT {
        type = INPUT_KEYBOARD,
        U = new InputUnion { ki = new KEYBDINPUT { wVk = 0, wScan = ch, dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP } }
      };
    }
    if (inputs.Length == 0) return;
    uint sent = SendInput((uint)inputs.Length, inputs, Marshal.SizeOf(typeof(INPUT)));
    if (sent != inputs.Length) {
      throw new InvalidOperationException("SendInput failed: sent " + sent + " of " + inputs.Length);
    }
  }

  public static void SendEnter() {
    var inputs = new INPUT[2];
    inputs[0] = new INPUT {
      type = INPUT_KEYBOARD,
      U = new InputUnion { ki = new KEYBDINPUT { wVk = VK_RETURN, wScan = 0, dwFlags = 0 } }
    };
    inputs[1] = new INPUT {
      type = INPUT_KEYBOARD,
      U = new InputUnion { ki = new KEYBDINPUT { wVk = VK_RETURN, wScan = 0, dwFlags = KEYEVENTF_KEYUP } }
    };
    uint sent = SendInput((uint)inputs.Length, inputs, Marshal.SizeOf(typeof(INPUT)));
    if (sent != inputs.Length) {
      throw new InvalidOperationException("SendInput(Enter) failed: sent " + sent + " of " + inputs.Length);
    }
  }
}
"@

Add-Type -TypeDefinition $cs -Language CSharp

$rec = $null
try {
  $rec = New-Recognizer -cultureName $Culture
  $result = $rec.Recognize()
  if ($null -eq $result) {
    exit 2
  }
  $text = ($result.Text ?? "").Trim()
  Write-Output $text

  if ($TypeToActiveWindow) {
    [SynapseSendInput]::SendUnicodeString($text)
    if ($PressEnter) {
      [SynapseSendInput]::SendEnter()
    }
  }
} finally {
  if ($rec -ne $null) {
    try { $rec.Dispose() } catch { }
  }
}

