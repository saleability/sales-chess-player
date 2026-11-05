#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include "SalesChessPlayerDll.h"

#define SALES_PATH_CAPACITY MAX_PATH

static HMODULE g_module = NULL;
static HANDLE g_process = NULL;
static DWORD g_process_id = 0;
static DWORD g_last_error = ERROR_SUCCESS;
static SRWLOCK g_lock = {0};

static size_t wide_length(const wchar_t* value) {
    size_t length = 0;
    while (value[length] != L'\0') {
        ++length;
    }
    return length;
}

static BOOL copy_wide(wchar_t* destination, size_t capacity, const wchar_t* source) {
    const size_t length = wide_length(source);
    if (length + 1 > capacity) {
        return FALSE;
    }
    for (size_t i = 0; i <= length; ++i) {
        destination[i] = source[i];
    }
    return TRUE;
}

static BOOL append_wide(wchar_t* destination, size_t capacity, const wchar_t* source) {
    const size_t current_length = wide_length(destination);
    const size_t source_length = wide_length(source);
    if (current_length + source_length + 1 > capacity) {
        return FALSE;
    }
    for (size_t i = 0; i <= source_length; ++i) {
        destination[current_length + i] = source[i];
    }
    return TRUE;
}

static void close_process_handle(void) {
    if (g_process != NULL) {
        CloseHandle(g_process);
        g_process = NULL;
    }
    g_process_id = 0;
}

static BOOL process_handle_is_running(void) {
    if (g_process == NULL) {
        return FALSE;
    }
    const DWORD state = WaitForSingleObject(g_process, 0);
    if (state == WAIT_TIMEOUT) {
        return TRUE;
    }
    if (state == WAIT_OBJECT_0) {
        close_process_handle();
    }
    return FALSE;
}

static HWND find_app_window(void) {
    return FindWindowW(NULL, L"Sales Chess Player");
}

static BOOL app_is_running(void) {
    if (process_handle_is_running()) {
        return TRUE;
    }
    HWND window = find_app_window();
    if (window == NULL) {
        return FALSE;
    }
    GetWindowThreadProcessId(window, &g_process_id);
    if (g_process_id != 0) {
        g_process = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION,
                                FALSE, g_process_id);
    }
    return TRUE;
}

static BOOL get_dll_directory(wchar_t* directory, DWORD capacity) {
    wchar_t path[SALES_PATH_CAPACITY];
    const DWORD length = GetModuleFileNameW(g_module, path, SALES_PATH_CAPACITY);
    if (length == 0 || length >= SALES_PATH_CAPACITY) {
        g_last_error = GetLastError();
        return FALSE;
    }
    wchar_t* slash = NULL;
    for (wchar_t* current = path; *current != L'\0'; ++current) {
        if (*current == L'\\' || *current == L'/') {
            slash = current;
        }
    }
    if (slash == NULL) {
        g_last_error = ERROR_INVALID_NAME;
        return FALSE;
    }
    *slash = L'\0';
    if (!copy_wide(directory, capacity, path)) {
        g_last_error = ERROR_INSUFFICIENT_BUFFER;
        return FALSE;
    }
    return TRUE;
}

typedef struct WindowCloseRequest {
    DWORD process_id;
} WindowCloseRequest;

static BOOL CALLBACK close_app_windows(HWND window, LPARAM parameter) {
    WindowCloseRequest* request = (WindowCloseRequest*)parameter;
    DWORD window_process_id = 0;
    GetWindowThreadProcessId(window, &window_process_id);
    if (window_process_id == request->process_id) {
        PostMessageW(window, WM_CLOSE, 0, 0);
    }
    return TRUE;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID reserved) {
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        g_module = instance;
        DisableThreadLibraryCalls(instance);
    } else if (reason == DLL_PROCESS_DETACH) {
        close_process_handle();
    }
    return TRUE;
}

SALES_CHESS_PLAYER_API int __cdecl SalesChessPlayer_Start(void) {
    AcquireSRWLockExclusive(&g_lock);
    if (app_is_running()) {
        g_last_error = ERROR_SUCCESS;
        ReleaseSRWLockExclusive(&g_lock);
        return 0;
    }

    wchar_t directory[SALES_PATH_CAPACITY];
    if (!get_dll_directory(directory, SALES_PATH_CAPACITY)) {
        ReleaseSRWLockExclusive(&g_lock);
        return -1;
    }
    wchar_t executable[SALES_PATH_CAPACITY];
    const wchar_t* suffix = L"\\SalesChessPlayer.exe";
    if (!copy_wide(executable, SALES_PATH_CAPACITY, directory)
            || !append_wide(executable, SALES_PATH_CAPACITY, suffix)) {
        g_last_error = ERROR_INSUFFICIENT_BUFFER;
        ReleaseSRWLockExclusive(&g_lock);
        return -1;
    }
    if (GetFileAttributesW(executable) == INVALID_FILE_ATTRIBUTES) {
        g_last_error = GetLastError();
        ReleaseSRWLockExclusive(&g_lock);
        return -1;
    }

    wchar_t command_line[SALES_PATH_CAPACITY + 4];
    if (!copy_wide(command_line, SALES_PATH_CAPACITY + 4, L"\"")
            || !append_wide(command_line, SALES_PATH_CAPACITY + 4, executable)
            || !append_wide(command_line, SALES_PATH_CAPACITY + 4, L"\"")) {
        g_last_error = ERROR_INSUFFICIENT_BUFFER;
        ReleaseSRWLockExclusive(&g_lock);
        return -1;
    }
    STARTUPINFOW startup = {0};
    startup.cb = sizeof(startup);
    startup.dwFlags = STARTF_USESHOWWINDOW;
    startup.wShowWindow = SW_SHOWNORMAL;
    PROCESS_INFORMATION process = {0};

    if (!CreateProcessW(executable, command_line, NULL, NULL, FALSE, 0, NULL,
                        directory, &startup, &process)) {
        g_last_error = GetLastError();
        ReleaseSRWLockExclusive(&g_lock);
        return -1;
    }
    CloseHandle(process.hThread);
    close_process_handle();
    g_process = process.hProcess;
    g_process_id = process.dwProcessId;
    g_last_error = ERROR_SUCCESS;
    ReleaseSRWLockExclusive(&g_lock);
    return 1;
}

SALES_CHESS_PLAYER_API int __cdecl SalesChessPlayer_Stop(unsigned long timeout_ms) {
    AcquireSRWLockExclusive(&g_lock);
    if (!app_is_running()) {
        g_last_error = ERROR_SUCCESS;
        ReleaseSRWLockExclusive(&g_lock);
        return 0;
    }

    WindowCloseRequest request;
    request.process_id = g_process_id;
    EnumWindows(close_app_windows, (LPARAM)&request);

    if (g_process != NULL) {
        const DWORD result = WaitForSingleObject(g_process, timeout_ms);
        if (result == WAIT_OBJECT_0) {
            close_process_handle();
            g_last_error = ERROR_SUCCESS;
            ReleaseSRWLockExclusive(&g_lock);
            return 1;
        }
        g_last_error = result == WAIT_TIMEOUT ? ERROR_TIMEOUT : GetLastError();
        ReleaseSRWLockExclusive(&g_lock);
        return -1;
    }

    const DWORD start = GetTickCount();
    while (find_app_window() != NULL) {
        if (GetTickCount() - start >= timeout_ms) {
            g_last_error = ERROR_TIMEOUT;
            ReleaseSRWLockExclusive(&g_lock);
            return -1;
        }
        Sleep(25);
    }
    g_last_error = ERROR_SUCCESS;
    ReleaseSRWLockExclusive(&g_lock);
    return 1;
}

SALES_CHESS_PLAYER_API int __cdecl SalesChessPlayer_IsRunning(void) {
    AcquireSRWLockExclusive(&g_lock);
    const BOOL running = app_is_running();
    g_last_error = ERROR_SUCCESS;
    ReleaseSRWLockExclusive(&g_lock);
    return running ? 1 : 0;
}

SALES_CHESS_PLAYER_API unsigned long __cdecl SalesChessPlayer_GetLastErrorCode(void) {
    AcquireSRWLockExclusive(&g_lock);
    const DWORD error = g_last_error;
    ReleaseSRWLockExclusive(&g_lock);
    return (unsigned long)error;
}
