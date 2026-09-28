/* dstrigger.exe: send a DualSense USB output report (0x02) through Windows HID: both adaptive
 * triggers to full continuous resistance and the lightbar to purple. Run under Wine to verify output. */
#include <windows.h>
#include <setupapi.h>
#include <hidsdi.h>
#include <stdio.h>

int wmain(int argc, wchar_t **argv)
{
    int off = argc > 1 && !wcscmp(argv[1], L"off");
    GUID hid; HidD_GetHidGuid(&hid);
    HDEVINFO set = SetupDiGetClassDevsW(&hid, NULL, NULL, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);
    SP_DEVICE_INTERFACE_DATA ifd = { sizeof(ifd) };
    for (DWORD i = 0; SetupDiEnumDeviceInterfaces(set, NULL, &hid, i, &ifd); i++) {
        BYTE buf[1024]; PSP_DEVICE_INTERFACE_DETAIL_DATA_W det = (void *)buf; det->cbSize = sizeof(*det);
        if (!SetupDiGetDeviceInterfaceDetailW(set, &ifd, det, sizeof(buf), NULL, NULL)) continue;
        HANDLE h = CreateFileW(det->DevicePath, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING, 0, NULL);
        HIDD_ATTRIBUTES a = { sizeof(a) };
        if (h == INVALID_HANDLE_VALUE || !HidD_GetAttributes(h, &a) || a.VendorID != 0x054c) { CloseHandle(h); continue; }
        BYTE r[48] = {0};
        r[0] = 0x02;
        r[1] = 0x0C;                         /* valid: right + left trigger effects */
        r[2] = 0x04;                         /* valid: lightbar colour */
        if (!off) {
            r[11] = 0x01; r[12] = 0x00; r[13] = 0xFF;   /* right trigger: continuous resistance, from 0, max force */
            r[22] = 0x01; r[23] = 0x00; r[24] = 0xFF;   /* left trigger */
            r[45] = 0x80; r[46] = 0x00; r[47] = 0xFF;   /* lightbar purple */
        } else {
            r[45] = 0x00; r[46] = 0x00; r[47] = 0x40;   /* triggers off (mode 0), dim blue */
        }
        DWORD w = 0;
        BOOL ok = WriteFile(h, r, sizeof(r), &w, NULL);
        wprintf(L"output report to %04x:%04x: %ls (%lu bytes, err %lu)\n", a.VendorID, a.ProductID, ok ? L"sent" : L"FAILED", w, ok ? 0 : GetLastError());
        CloseHandle(h);
        return ok ? 0 : 1;
    }
    wprintf(L"no DualSense raw HID device visible\n");
    return 2;
}
