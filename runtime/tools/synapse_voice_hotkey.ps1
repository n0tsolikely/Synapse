<#
synapse_voice_hotkey.ps1

WSL-friendly Windows-side hotkey listener for dictation.

Modes:
- push   (default): press HOTKEY, speak one phrase, it types the result.
- toggle: press HOTKEY to arm/disarm; when armed it types each recognized phrase.

Defaults:
- HOTKEY: Ctrl+Alt+Space
- EXIT:   Ctrl+Alt+Q

This uses:
- System.Speech for dictation (offline on Windows)
- SendInput for Unicode typing to the currently focused window

Run (from WSL) via the provided start script:
  bash runtime/tools/synapse_voice_hotkey_start.sh
#>

[CmdletBinding()]
param(
  [ValidateSet("push","toggle")]
  [string]$Mode = "push",
  [string]$Culture = "en-US",
  [int]$InitialSilenceTimeoutSeconds = 5,
  [int]$EndSilenceTimeoutMilliseconds = 800,
  [switch]$PressEnter,
  [switch]$PrintRecognized,
  [string]$Hotkey = "CTRL+ALT+SPACE",
  [string]$ExitHotkey = "CTRL+ALT+Q"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms

$cs = @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Windows.Forms;

public static class SynapseSendInput {
  [StructLayout(LayoutKind.Sequential)]
  public struct INPUT { public uint type; public InputUnion U; }

  [StructLayout(LayoutKind.Explicit)]
  public struct InputUnion { [FieldOffset(0)] public KEYBDINPUT ki; }

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
    if (sent != inputs.Length) throw new InvalidOperationException("SendInput failed: sent " + sent + " of " + inputs.Length);
  }

  public static void SendEnter() {
    var inputs = new INPUT[2];
    inputs[0] = new INPUT { type = INPUT_KEYBOARD, U = new InputUnion { ki = new KEYBDINPUT { wVk = VK_RETURN, wScan = 0, dwFlags = 0 } } };
    inputs[1] = new INPUT { type = INPUT_KEYBOARD, U = new InputUnion { ki = new KEYBDINPUT { wVk = VK_RETURN, wScan = 0, dwFlags = KEYEVENTF_KEYUP } } };
    uint sent = SendInput((uint)inputs.Length, inputs, Marshal.SizeOf(typeof(INPUT)));
    if (sent != inputs.Length) throw new InvalidOperationException("SendInput(Enter) failed: sent " + sent + " of " + inputs.Length);
  }
}

public class SynapseHotkeyWindow : NativeWindow, IDisposable {
  private const int WM_HOTKEY = 0x0312;

  [DllImport("user32.dll", SetLastError = true)]
  private static extern bool RegisterHotKey(IntPtr hWnd, int id, uint fsModifiers, uint vk);

  [DllImport("user32.dll", SetLastError = true)]
  private static extern bool UnregisterHotKey(IntPtr hWnd, int id);

  private readonly Dictionary<int, Action> _handlers = new Dictionary<int, Action>();

  public SynapseHotkeyWindow() { CreateHandle(new CreateParams()); }

  public void Register(int id, uint modifiers, Keys key, Action handler) {
    if (!RegisterHotKey(this.Handle, id, modifiers, (uint)key)) {
      throw new InvalidOperationException("RegisterHotKey failed for id=" + id + " key=" + key + " modifiers=" + modifiers);
    }
    _handlers[id] = handler;
  }

  protected override void WndProc(ref Message m) {
    if (m.Msg == WM_HOTKEY) {
      int id = m.WParam.ToInt32();
      Action handler;
      if (_handlers.TryGetValue(id, out handler)) {
        try { handler(); } catch { }
      }
    }
    base.WndProc(ref m);
  }

  public void Dispose() {
    foreach (var id in _handlers.Keys) {
      try { UnregisterHotKey(this.Handle, id); } catch { }
    }
    _handlers.Clear();
    DestroyHandle();
  }
}
"@

Add-Type -TypeDefinition $cs -Language CSharp

function Parse-Hotkey([string]$spec) {
  $mods = 0
  $keyName = $null

  foreach ($part in ($spec -split "\\+")) {
    $p = $part.Trim().ToUpperInvariant()
    if ($p -eq "CTRL" -or $p -eq "CONTROL") { $mods = $mods -bor 0x0002; continue }
    if ($p -eq "ALT") { $mods = $mods -bor 0x0001; continue }
    if ($p -eq "SHIFT") { $mods = $mods -bor 0x0004; continue }
    if ($p -eq "WIN" -or $p -eq "WINDOWS") { $mods = $mods -bor 0x0008; continue }
    $keyName = $p
  }

  if ([string]::IsNullOrWhiteSpace($keyName)) {
    throw "invalid hotkey spec: '$spec' (missing key)"
  }

  $key = [System.Windows.Forms.Keys]::$keyName
  return @{ Mods = [uint32]$mods; Key = $key }
}

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

$hk = Parse-Hotkey $Hotkey
$exitHk = Parse-Hotkey $ExitHotkey

$window = New-Object SynapseHotkeyWindow
$running = $true
$busy = $false
$armed = $false
$rec = $null
$lastText = ""

function Type-Text([string]$text) {
  if ([string]::IsNullOrWhiteSpace($text)) { return }
  [SynapseSendInput]::SendUnicodeString($text)
  if ($PressEnter) { [SynapseSendInput]::SendEnter() }
}

function Recognize-OneShot() {
  if ($busy) { return }
  $busy = $true
  try {
    $r = New-Recognizer -cultureName $Culture
    try {
      $result = $r.Recognize()
      if ($null -eq $result) { return }
      $text = ($result.Text ?? "").Trim()
      if ($PrintRecognized) { Write-Output $text }
      Type-Text $text
    } finally {
      $r.Dispose()
    }
  } finally {
    $busy = $false
  }
}

function Toggle-Arm() {
  if ($busy) { return }
  if (-not $armed) {
    $armed = $true
    $rec = New-Recognizer -cultureName $Culture
    $rec.add_SpeechRecognized({
      if (-not $armed) { return }
      $t = ($_.Result.Text ?? "").Trim()
      if ([string]::IsNullOrWhiteSpace($t)) { return }
      if ($t -eq $lastText) { return }
      $lastText = $t
      if ($PrintRecognized) { Write-Output $t }
      Type-Text $t
    })
    $rec.RecognizeAsync([System.Speech.Recognition.RecognizeMode]::Multiple)
    [console]::beep(880,150)
  } else {
    $armed = $false
    if ($rec -ne $null) {
      try { $rec.RecognizeAsyncCancel() } catch { }
      try { $rec.RecognizeAsyncStop() } catch { }
      try { $rec.Dispose() } catch { }
      $rec = $null
    }
    [console]::beep(440,120)
  }
}

$window.Register(1, $hk.Mods, $hk.Key, [Action]{
  if ($Mode -eq "toggle") { Toggle-Arm } else { Recognize-OneShot }
})
$window.Register(2, $exitHk.Mods, $exitHk.Key, [Action]{
  $running = $false
})

try {
  while ($running) {
    [System.Windows.Forms.Application]::DoEvents() | Out-Null
    Start-Sleep -Milliseconds 25
  }
} finally {
  if ($rec -ne $null) {
    try { $rec.RecognizeAsyncCancel() } catch { }
    try { $rec.RecognizeAsyncStop() } catch { }
    try { $rec.Dispose() } catch { }
  }
  $window.Dispose()
}

