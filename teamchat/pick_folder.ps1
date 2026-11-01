# Crewroom's folder picker on Windows: the modern File Explorer-style "Select Folder" window (IFileOpenDialog).
# Run by system.pick_folder:   powershell -NoProfile -STA -File pick_folder.ps1     (title in CR_TITLE, start in CR_START)
# Prints the chosen folder, or nothing if cancelled. Falls back to the old folder browser if the modern one fails.
Add-Type -AssemblyName System.Windows.Forms
Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;

public static class CrewroomPicker {
    [ComImport, Guid("DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7")] class FileOpenDialog { }

    [ComImport, Guid("42f85136-db7e-439c-85f1-e4075d135fc8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IFileDialog {
        [PreserveSig] int Show(IntPtr parent);
        void SetFileTypes(uint count, IntPtr types);
        void SetFileTypeIndex(uint index);
        void GetFileTypeIndex(out uint index);
        void Advise(IntPtr events, out uint cookie);
        void Unadvise(uint cookie);
        void SetOptions(uint options);
        void GetOptions(out uint options);
        void SetDefaultFolder(IShellItem item);
        void SetFolder(IShellItem item);
        void GetFolder(out IShellItem item);
        void GetCurrentSelection(out IShellItem item);
        void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string name);
        void GetFileName([MarshalAs(UnmanagedType.LPWStr)] out string name);
        void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string title);
        void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string label);
        void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string label);
        void GetResult(out IShellItem item);
    }

    [ComImport, Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IShellItem {
        void BindToHandler(IntPtr bc, ref Guid handler, ref Guid riid, out IntPtr result);
        void GetParent(out IShellItem parent);
        void GetDisplayName(uint kind, [MarshalAs(UnmanagedType.LPWStr)] out string name);
    }

    [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
    static extern void SHCreateItemFromParsingName(string path, IntPtr bc, ref Guid riid, out IShellItem item);

    // Windows keeps background programs from bringing windows forward; joining the input of the window in front
    // for a moment lifts that, so the picker opens on top of Crewroom instead of behind it.
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, IntPtr process);
    [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] static extern bool AttachThreadInput(uint from, uint to, bool attach);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll")] static extern bool BringWindowToTop(IntPtr window);

    public static void ToFront(IntPtr window) {
        uint front = GetWindowThreadProcessId(GetForegroundWindow(), IntPtr.Zero), me = GetCurrentThreadId();
        AttachThreadInput(me, front, true);
        BringWindowToTop(window);
        SetForegroundWindow(window);
        AttachThreadInput(me, front, false);
    }

    const uint PICK_FOLDERS = 0x20, FILE_SYSTEM_ONLY = 0x40, FILE_SYSTEM_PATH = 0x80058000;

    // The chosen folder, "" if cancelled. show=false only builds the dialog (a self-check).
    public static string Pick(IntPtr owner, string title, string start, bool show = true) {
        IFileDialog dialog = (IFileDialog)new FileOpenDialog();
        uint options;
        dialog.GetOptions(out options);
        dialog.SetOptions(options | PICK_FOLDERS | FILE_SYSTEM_ONLY);
        dialog.SetTitle(title);
        dialog.SetOkButtonLabel("Select folder");
        if (!string.IsNullOrEmpty(start) && Directory.Exists(start)) {
            Guid shellItem = typeof(IShellItem).GUID;
            IShellItem folder;
            SHCreateItemFromParsingName(start, IntPtr.Zero, ref shellItem, out folder);
            dialog.SetFolder(folder);
        }
        if (!show) return "ready";
        if (dialog.Show(owner) != 0) return "";
        IShellItem result;
        dialog.GetResult(out result);
        string path;
        result.GetDisplayName(FILE_SYSTEM_PATH, out path);
        return path;
    }
}
'@

$owner = New-Object System.Windows.Forms.Form -Property @{ TopMost = $true; ShowInTaskbar = $false; Opacity = 0; StartPosition = 'CenterScreen'; Width = 1; Height = 1 }
$owner.Show()
[CrewroomPicker]::ToFront($owner.Handle)
$owner.Activate()
[Console]::OutputEncoding = [Text.Encoding]::UTF8
if ($env:CR_DRY_RUN) { 'modern picker: ' + [CrewroomPicker]::Pick($owner.Handle, 'check', $env:CR_START, $false); $owner.Close(); exit }
try {
    [CrewroomPicker]::Pick($owner.Handle, $env:CR_TITLE, $env:CR_START)
} catch {
    $old = New-Object System.Windows.Forms.FolderBrowserDialog -Property @{ Description = $env:CR_TITLE; SelectedPath = $env:CR_START; ShowNewFolderButton = $true }
    if ($old.ShowDialog($owner) -eq 'OK') { $old.SelectedPath }
}
$owner.Close()
