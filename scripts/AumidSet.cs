using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;

public class AumidSet {
    [DllImport("propsys.dll", CharSet = CharSet.Unicode, EntryPoint = "PSGetPropertyKeyFromName")]
    static extern int SHGetPropertyKeyFromName(string name, out PROPERTYKEY key);

    [DllImport("ole32.dll")]
    static extern int PropVariantClear(ref PROPVARIANT pv);

    [StructLayout(LayoutKind.Sequential)]
    public struct PROPERTYKEY { public Guid fmtid; public uint pid; }

    [StructLayout(LayoutKind.Explicit)]
    public struct PropUnion { [FieldOffset(0)] public IntPtr p; [FieldOffset(0)] public uint u32; }

    [StructLayout(LayoutKind.Sequential)]
    public struct PROPVARIANT {
        public ushort vt; public ushort r1; public ushort r2; public ushort r3;
        public PropUnion u;
    }

    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IPropertyStore {
        void GetCount(out uint c);
        void GetAt(uint i, out PROPERTYKEY k);
        void GetValue(ref PROPERTYKEY k, out PROPVARIANT v);
        void SetValue(ref PROPERTYKEY k, ref PROPVARIANT v);
        void Commit();
    }

    [ComImport, Guid("00021401-0000-0000-C000-000000000046")]
    public class ShellLink { }

    [ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IShellLinkW {
        void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder pszFile, int cch, IntPtr pfd, uint fFlags);
        void GetIDList(out IntPtr ppidl);
        void SetIDList(IntPtr pidl);
        void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder pszName, int cch);
        void SetDescription(string pszName);
        void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder pszDir, int cch);
        void SetWorkingDirectory(string pszDir);
        void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder pszArgs, int cch);
        void SetArguments(string pszArgs);
        void GetHotkey(out ushort pwHotkey);
        void SetHotkey(ushort wHotkey);
        void GetShowCmd(out int piShowCmd);
        void SetShowCmd(int iShowCmd);
        void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] System.Text.StringBuilder pszIconPath, int cch, out int piIcon);
        void SetIconLocation(string pszIconPath, int iIcon);
        void SetRelativePath(string pszPathRel, uint dwReserved);
        void Resolve(IntPtr hwnd, uint fFlags);
        void SetPath(string pszFile);
    }

    [STAThread]
    public static int Main(string[] args) {
        if (args.Length < 5) {
            Console.Error.WriteLine("usage: AumidSet <lnk> <aumid> <target> <arguments> <workdir> [icon]");
            return 2;
        }
        string lnkPath = args[0], aumid = args[1], target = args[2],
               arguments = args[3], workdir = args[4],
               icon = args.Length > 5 ? args[5] : target;

        // 全新 ShellLink 对象：属性存储可写（从磁盘 Load 出来的会拒绝 SetValue）
        IShellLinkW link = (IShellLinkW)new ShellLink();
        link.SetPath(target);
        link.SetArguments(arguments);
        link.SetWorkingDirectory(workdir);
        link.SetDescription("GPUViewer");
        link.SetIconLocation(icon, 0);

        PROPERTYKEY key;
        int hr = SHGetPropertyKeyFromName("System.AppUserModel.ID", out key);
        if (hr != 0) { Console.Error.WriteLine("GetKey hr=0x" + hr.ToString("X")); return 1; }
        IPropertyStore store = (IPropertyStore)link;
        PROPVARIANT pv = new PROPVARIANT();
        pv.vt = 31;
        pv.u.p = Marshal.StringToCoTaskMemUni(aumid);
        try {
            store.SetValue(ref key, ref pv);
            store.Commit();
        } finally { PropVariantClear(ref pv); }

        IPersistFile pf = (IPersistFile)link;
        pf.Save(lnkPath, true);
        Console.WriteLine("OK: " + lnkPath);
        return 0;
    }
}
