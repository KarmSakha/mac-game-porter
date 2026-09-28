/* padtest.exe: what a Windows game sees of connected controllers (raw HID + XInput). Run under Wine. */
#include <windows.h>
#include <setupapi.h>
#include <hidsdi.h>
#include <xinput.h>
#include <stdio.h>

int wmain(void)
{
    GUID hid; HidD_GetHidGuid(&hid);
    HDEVINFO set = SetupDiGetClassDevsW(&hid, NULL, NULL, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);
    SP_DEVICE_INTERFACE_DATA ifd = { sizeof(ifd) };
    for (DWORD i = 0; SetupDiEnumDeviceInterfaces(set, NULL, &hid, i, &ifd); i++) {
        BYTE buf[1024]; PSP_DEVICE_INTERFACE_DETAIL_DATA_W det = (void *)buf; det->cbSize = sizeof(*det);
        if (!SetupDiGetDeviceInterfaceDetailW(set, &ifd, det, sizeof(buf), NULL, NULL)) continue;
        HANDLE h = CreateFileW(det->DevicePath, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                               NULL, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, NULL);
        HIDD_ATTRIBUTES a = { sizeof(a) };
        if (h == INVALID_HANDLE_VALUE || !HidD_GetAttributes(h, &a)) { wprintf(L"[%lu] %ls (open failed %lu)\n", i, det->DevicePath, GetLastError()); continue; }
        WCHAR prod[128] = L""; HidD_GetProductString(h, prod, sizeof(prod));
        PHIDP_PREPARSED_DATA pp; HIDP_CAPS caps = {0};
        if (HidD_GetPreparsedData(h, &pp)) { HidP_GetCaps(pp, &caps); HidD_FreePreparsedData(pp); }
        wprintf(L"[%lu] %04x:%04x '%ls' usage %x:%x in=%u out=%u feat=%u\n    %ls\n", i, a.VendorID, a.ProductID, prod,
                caps.UsagePage, caps.Usage, caps.InputReportByteLength, caps.OutputReportByteLength,
                caps.FeatureReportByteLength, det->DevicePath);
        if (a.VendorID == 0x054c) {
            BYTE feat[64] = { 0x05 };   /* DualSense calibration feature report */
            wprintf(L"    feature 0x05: %ls\n", HidD_GetFeature(h, feat, sizeof(feat)) ? L"ok" : L"FAILED");
            for (int r = 0; r < 3; r++) {
                BYTE rep[128] = {0}; DWORD got = 0; OVERLAPPED ov = {0}; ov.hEvent = CreateEventW(NULL, TRUE, FALSE, NULL);
                if (!ReadFile(h, rep, caps.InputReportByteLength, NULL, &ov) && GetLastError() != ERROR_IO_PENDING) { wprintf(L"    read error %lu\n", GetLastError()); break; }
                if (WaitForSingleObject(ov.hEvent, 2000) != WAIT_OBJECT_0) { wprintf(L"    read TIMEOUT (no input reports)\n"); CancelIo(h); break; }
                GetOverlappedResult(h, &ov, &got, FALSE);
                wprintf(L"    report %lu bytes: %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x\n", got, rep[0], rep[1], rep[2], rep[3], rep[4], rep[5], rep[6], rep[7], rep[8], rep[9]);
            }
        }
        CloseHandle(h);
    }
    for (DWORD u = 0; u < 4; u++) {
        XINPUT_STATE st; DWORD rc = XInputGetState(u, &st);
        wprintf(L"XInput %lu: %ls\n", u, rc == ERROR_SUCCESS ? L"connected" : L"-");
    }
    return 0;
}
