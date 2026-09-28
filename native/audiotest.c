/* audiotest.exe: list Windows audio render endpoints as a game sees them (name, channels, ids). */
#define COBJMACROS
#define INITGUID
#include <windows.h>
#include <mmdeviceapi.h>
#include <audioclient.h>
#include <functiondiscoverykeys_devpkey.h>
#include <stdio.h>

DEFINE_PROPERTYKEY(PKEY_Device_ContainerId_, 0x8c7ed206, 0x3f8a, 0x4827, 0xb3, 0xab, 0xae, 0x9e, 0x1f, 0xae, 0xfc, 0x6c, 2);
DEFINE_PROPERTYKEY(PKEY_Device_InstanceId_, 0x78c34fc8, 0x104a, 0x4aca, 0x9e, 0xa4, 0x52, 0x4d, 0x52, 0x99, 0x6e, 0x57, 256);

static void show(IPropertyStore *ps, const PROPERTYKEY *k, const wchar_t *label)
{
    PROPVARIANT v; PropVariantInit(&v);
    if (SUCCEEDED(IPropertyStore_GetValue(ps, k, &v))) {
        if (v.vt == VT_LPWSTR) wprintf(L"    %ls: %ls\n", label, v.pwszVal);
        else if (v.vt == VT_CLSID) { WCHAR g[64]; StringFromGUID2(v.puuid, g, 64); wprintf(L"    %ls: %ls\n", label, g); }
        else wprintf(L"    %ls: (vt %d)\n", label, v.vt);
    }
    PropVariantClear(&v);
}

int wmain(void)
{
    CoInitializeEx(NULL, COINIT_MULTITHREADED);
    IMMDeviceEnumerator *en; IMMDeviceCollection *col; UINT n;
    if (FAILED(CoCreateInstance(&CLSID_MMDeviceEnumerator, NULL, CLSCTX_ALL, &IID_IMMDeviceEnumerator, (void **)&en))) return 1;
    IMMDeviceEnumerator_EnumAudioEndpoints(en, eRender, DEVICE_STATE_ACTIVE, &col);
    IMMDeviceCollection_GetCount(col, &n);
    for (UINT i = 0; i < n; i++) {
        IMMDevice *d; IPropertyStore *ps; LPWSTR id; IAudioClient *ac; WAVEFORMATEX *fmt = NULL;
        IMMDeviceCollection_Item(col, i, &d);
        IMMDevice_GetId(d, &id);
        IMMDevice_OpenPropertyStore(d, STGM_READ, &ps);
        wprintf(L"[%u] %ls\n", i, id);
        show(ps, &PKEY_Device_FriendlyName, L"name");
        show(ps, &PKEY_Device_ContainerId_, L"container");
        show(ps, &PKEY_Device_InstanceId_, L"instance");
        if (SUCCEEDED(IMMDevice_Activate(d, &IID_IAudioClient, CLSCTX_ALL, NULL, (void **)&ac)) &&
            SUCCEEDED(IAudioClient_GetMixFormat(ac, &fmt)))
            wprintf(L"    mix format: %u ch, %lu Hz\n", fmt->nChannels, fmt->nSamplesPerSec);
    }
    return 0;
}
